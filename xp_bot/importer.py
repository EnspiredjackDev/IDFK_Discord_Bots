"""Import functionality for channel history."""
import random
import asyncio
from dataclasses import dataclass
import discord
import aiosqlite

from xp_bot.config import (
    IMPORT_XP_MIN, IMPORT_XP_MAX, IMPORT_COOLDOWN_SECONDS,
    IMPORT_SLEEP_EVERY, IMPORT_SLEEP_SECONDS, IMPORT_BATCH_SIZE, DB_TIMEOUT
)
from xp_bot.database import get_import_cursor, set_import_cursor, get_xp, set_xp
from xp_bot.archiving import archive_path, msg_to_archive_dict, append_jsonl

# Global stop flag for import runs
IMPORT_STOP_REQUESTED = False

@dataclass
class ImportStats:
    """Statistics for an import operation."""
    messages_seen: int = 0
    messages_archived: int = 0
    xp_events: int = 0
    xp_total_awarded: int = 0
    users_touched: int = 0

async def import_text_channel(
    channel: discord.TextChannel,
    db_path: str,
    *,
    resume: bool = True,
    archive: bool = True,
    dry_run: bool = False,
    no_xp: bool = False
) -> ImportStats:
    """
    Import channel history from oldest->newest.
    
    Args:
        channel: The Discord text channel to import
        db_path: Path to the database file
        resume: If True, continues from last saved cursor
        archive: If True, writes messages to JSONL archive
        dry_run: If True, doesn't save XP or cursor (but still archives if archive=True)
        no_xp: If True, archives messages but doesn't award any XP (useful for stats-only channels)
    
    Returns:
        ImportStats object with import statistics
    """
    global IMPORT_STOP_REQUESTED

    stats = ImportStats()
    guild = channel.guild

    # per-user last-award timestamp for import (seconds since epoch)
    last_award: dict[int, float] = {}
    users_touched: set[int] = set()

    archive_file = archive_path(guild.id, channel.id) if archive else None

    # Get initial cursor outside the main loop
    async with aiosqlite.connect(db_path, timeout=DB_TIMEOUT) as db:
        last_id = await get_import_cursor(db, guild.id, channel.id) if resume else 0

    # Use after=Object(id=last_id) to continue from checkpoint
    after_obj = discord.Object(id=last_id) if last_id else None

    # Oldest -> newest for stable cooldown logic
    history_iter = channel.history(
        limit=None,
        oldest_first=True,
        after=after_obj
    )

    last_processed_id = last_id
    batch_xp_updates: dict[int, int] = {}  # user_id -> total_xp_gain

    async for msg in history_iter:
        if IMPORT_STOP_REQUESTED:
            break

        # Add a tiny delay between each message to avoid rate limits
        await asyncio.sleep(0.01)  # 10ms delay = max ~100 messages/second

        stats.messages_seen += 1
        last_processed_id = msg.id

        # Archive
        if archive and archive_file:
            append_jsonl(archive_file, msg_to_archive_dict(msg))
            stats.messages_archived += 1

        # Skip bots for XP (still archived)
        if msg.author.bot:
            continue

        # Skip XP awarding if no_xp flag is set
        if no_xp:
            continue

        # Import XP awarding logic:
        # 1 event per user per minute based on message timestamp
        ts = msg.created_at.replace(tzinfo=discord.utils.utcnow().tzinfo).timestamp()
        prev = last_award.get(msg.author.id, 0.0)
        if ts - prev < IMPORT_COOLDOWN_SECONDS:
            continue

        last_award[msg.author.id] = ts
        users_touched.add(msg.author.id)

        gain = random.randint(IMPORT_XP_MIN, IMPORT_XP_MAX)
        stats.xp_events += 1
        stats.xp_total_awarded += gain

        if not dry_run:
            # Accumulate XP changes in memory
            batch_xp_updates[msg.author.id] = batch_xp_updates.get(msg.author.id, 0) + gain

        # Commit batches periodically to avoid holding locks
        if not dry_run and stats.messages_seen % IMPORT_BATCH_SIZE == 0:
            async with aiosqlite.connect(db_path, timeout=DB_TIMEOUT) as db:
                for user_id, xp_gain in batch_xp_updates.items():
                    old_xp = await get_xp(db, guild.id, user_id)
                    await set_xp(db, guild.id, user_id, old_xp + xp_gain)
                await set_import_cursor(db, guild.id, channel.id, last_processed_id)
                await db.commit()
            batch_xp_updates.clear()

        # Gentle pacing
        if stats.messages_seen % IMPORT_SLEEP_EVERY == 0:
            await asyncio.sleep(IMPORT_SLEEP_SECONDS)

    # Final commit for any remaining XP updates and cursor
    if not dry_run:
        async with aiosqlite.connect(db_path, timeout=DB_TIMEOUT) as db:
            for user_id, xp_gain in batch_xp_updates.items():
                old_xp = await get_xp(db, guild.id, user_id)
                await set_xp(db, guild.id, user_id, old_xp + xp_gain)
            if last_processed_id and last_processed_id != last_id:
                await set_import_cursor(db, guild.id, channel.id, last_processed_id)
            await db.commit()

    stats.users_touched = len(users_touched)
    return stats
