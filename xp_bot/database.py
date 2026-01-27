"""Database operations for XP and import state tracking."""
import aiosqlite
from xp_bot.config import DB_TIMEOUT

async def init_db(db_path: str):
    """Initialize database tables."""
    async with aiosqlite.connect(db_path, timeout=DB_TIMEOUT) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_xp (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            xp INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS import_state (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            last_message_id INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, channel_id)
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS last_message (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            last_message_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, channel_id, user_id)
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_aliases (
            guild_id INTEGER NOT NULL,
            alt_user_id INTEGER NOT NULL,
            main_user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, alt_user_id)
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            end_time TEXT NOT NULL,
            ended INTEGER NOT NULL DEFAULT 0,
            winner_id INTEGER,
            num_winners INTEGER NOT NULL DEFAULT 1
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS giveaway_entries (
            giveaway_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            entered_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (giveaway_id, user_id),
            FOREIGN KEY (giveaway_id) REFERENCES giveaways(id) ON DELETE CASCADE
        )
        """)
        await db.commit()

async def get_xp(db, guild_id: int, user_id: int) -> int:
    """Get XP for a user in a guild."""
    async with db.execute(
        "SELECT xp FROM user_xp WHERE guild_id=? AND user_id=?",
        (guild_id, user_id)
    ) as cur:
        row = await cur.fetchone()
        return int(row[0]) if row else 0

async def set_xp(db, guild_id: int, user_id: int, xp: int):
    """Set XP for a user in a guild."""
    await db.execute("""
        INSERT INTO user_xp (guild_id, user_id, xp)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET xp=excluded.xp
    """, (guild_id, user_id, int(xp)))

async def add_xp(db, guild_id: int, user_id: int, amount: int) -> tuple[int, int]:
    """Add XP to a user. Returns (old_xp, new_xp)."""
    old_xp = await get_xp(db, guild_id, user_id)
    new_xp = old_xp + amount
    await set_xp(db, guild_id, user_id, new_xp)
    return old_xp, new_xp

async def get_import_cursor(db, guild_id: int, channel_id: int) -> int:
    """Get the last processed message ID for a channel."""
    async with db.execute(
        "SELECT last_message_id FROM import_state WHERE guild_id=? AND channel_id=?",
        (guild_id, channel_id)
    ) as cur:
        row = await cur.fetchone()
        return int(row[0]) if row else 0

async def set_import_cursor(db, guild_id: int, channel_id: int, last_message_id: int):
    """Save the import cursor for a channel."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    await db.execute("""
        INSERT INTO import_state (guild_id, channel_id, last_message_id, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id, channel_id)
        DO UPDATE SET last_message_id=excluded.last_message_id, updated_at=excluded.updated_at
    """, (guild_id, channel_id, int(last_message_id), now))

async def update_last_message(db, guild_id: int, channel_id: int, user_id: int, timestamp: str):
    """Update the last message timestamp for a user in a channel."""
    await db.execute("""
        INSERT INTO last_message (guild_id, channel_id, user_id, last_message_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id, channel_id, user_id)
        DO UPDATE SET last_message_at=excluded.last_message_at
    """, (guild_id, channel_id, user_id, timestamp))

async def get_last_message(db, guild_id: int, channel_id: int, user_id: int) -> str | None:
    """Get the last message timestamp for a user in a channel."""
    async with db.execute(
        "SELECT last_message_at FROM last_message WHERE guild_id=? AND channel_id=? AND user_id=?",
        (guild_id, channel_id, user_id)
    ) as cur:
        row = await cur.fetchone()
        return row[0] if row else None

async def get_main_user_id(db, guild_id: int, user_id: int) -> int:
    """Get the main user ID for a user (resolves aliases). Returns user_id if no alias exists."""
    async with db.execute(
        "SELECT main_user_id FROM user_aliases WHERE guild_id=? AND alt_user_id=?",
        (guild_id, user_id)
    ) as cur:
        row = await cur.fetchone()
        return int(row[0]) if row else user_id

async def set_user_alias(db, guild_id: int, alt_user_id: int, main_user_id: int):
    """Set an alias relationship between two users."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    await db.execute("""
        INSERT INTO user_aliases (guild_id, alt_user_id, main_user_id, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id, alt_user_id)
        DO UPDATE SET main_user_id=excluded.main_user_id, created_at=excluded.created_at
    """, (guild_id, alt_user_id, main_user_id, now))

async def remove_user_alias(db, guild_id: int, alt_user_id: int):
    """Remove an alias relationship."""
    await db.execute(
        "DELETE FROM user_aliases WHERE guild_id=? AND alt_user_id=?",
        (guild_id, alt_user_id)
    )

async def get_user_aliases(db, guild_id: int, main_user_id: int) -> list[int]:
    """Get all alt accounts linked to a main user."""
    async with db.execute(
        "SELECT alt_user_id FROM user_aliases WHERE guild_id=? AND main_user_id=?",
        (guild_id, main_user_id)
    ) as cur:
        rows = await cur.fetchall()
        return [int(row[0]) for row in rows]

async def get_combined_xp(db, guild_id: int, user_id: int) -> int:
    """Get combined XP for a user and all their alts."""
    main_id = await get_main_user_id(db, guild_id, user_id)
    
    # Get XP from main account
    total_xp = await get_xp(db, guild_id, main_id)
    
    # Get XP from all alts
    alts = await get_user_aliases(db, guild_id, main_id)
    for alt_id in alts:
        total_xp += await get_xp(db, guild_id, alt_id)
    
    return total_xp
