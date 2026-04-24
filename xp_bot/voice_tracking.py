"""Voice channel tracking and statistics."""
from datetime import datetime, timezone
from typing import Optional
import aiosqlite
from xp_bot.config import DB_TIMEOUT, DB_PATH, VOICE_XP_ENABLED, VOICE_XP_PER_MINUTE, VOICE_XP_MIN_DURATION
from xp_bot.database import add_xp
from xp_bot.leveling import level_from_total_xp

# In-memory storage for active voice sessions
# Format: {(guild_id, user_id): {"channel_id": int, "joined_at": str, "companions": set}}
active_sessions: dict[tuple[int, int], dict] = {}


async def user_joined_voice(guild_id: int, user_id: int, channel_id: int, timestamp: Optional[datetime] = None):
    """
    Record when a user joins a voice channel.
    
    Args:
        guild_id: The guild ID
        user_id: The user ID
        channel_id: The voice channel ID
        timestamp: When they joined (defaults to now)
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    
    joined_at = timestamp.isoformat()
    
    # Get current members in the channel
    companions = get_channel_members(guild_id, channel_id)
    companions.discard(user_id)  # Remove the user themselves
    
    # Store active session
    active_sessions[(guild_id, user_id)] = {
        "channel_id": channel_id,
        "joined_at": joined_at,
        "companions": companions.copy()
    }
    
    # Start companion tracking for existing members
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        for companion_id in companions:
            await db.execute("""
                INSERT INTO voice_companions 
                (guild_id, user_id, companion_id, channel_id, session_start)
                VALUES (?, ?, ?, ?, ?)
            """, (guild_id, user_id, companion_id, channel_id, joined_at))
            
            # Also record from companion's perspective
            await db.execute("""
                INSERT INTO voice_companions 
                (guild_id, user_id, companion_id, channel_id, session_start)
                VALUES (?, ?, ?, ?, ?)
            """, (guild_id, companion_id, user_id, channel_id, joined_at))
        
        await db.commit()


async def user_left_voice(guild_id: int, user_id: int, timestamp: Optional[datetime] = None) -> tuple[int, int, int]:
    """
    Record when a user leaves a voice channel.
    
    Args:
        guild_id: The guild ID
        user_id: The user ID
        timestamp: When they left (defaults to now)
    
    Returns:
        Tuple of (duration_seconds, old_level, new_level)
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    
    left_at = timestamp.isoformat()
    
    # Get active session
    key = (guild_id, user_id)
    if key not in active_sessions:
        return (0, 0, 0)  # No active session to close
    
    session = active_sessions.pop(key)
    joined_at = session["joined_at"]
    channel_id = session["channel_id"]
    companions = session["companions"]
    
    # Calculate duration
    joined_time = datetime.fromisoformat(joined_at)
    left_time = datetime.fromisoformat(left_at)
    duration_seconds = int((left_time - joined_time).total_seconds())
    
    # Award XP based on voice time
    old_level = 0
    new_level = 0
    if VOICE_XP_ENABLED and duration_seconds >= VOICE_XP_MIN_DURATION:
        minutes_in_vc = duration_seconds / 60.0
        xp_gained = int(minutes_in_vc * VOICE_XP_PER_MINUTE)
        
        if xp_gained > 0:
            async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
                # Get old XP and level
                from xp_bot.database import get_xp
                old_xp = await get_xp(db, guild_id, user_id)
                old_level = level_from_total_xp(old_xp)
                
                # Add XP
                _, new_xp = await add_xp(db, guild_id, user_id, xp_gained)
                new_level = level_from_total_xp(new_xp)
                
                await db.commit()
                print(f"[voice-xp] Awarded {xp_gained} XP to user {user_id} for {duration_seconds}s in VC")
    
    # Save to database
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        # Save voice session
        await db.execute("""
            INSERT INTO voice_sessions 
            (guild_id, channel_id, user_id, joined_at, left_at, duration_seconds)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (guild_id, channel_id, user_id, joined_at, left_at, duration_seconds))
        
        # Update companion sessions
        for companion_id in companions:
            # Update user's companion record
            await db.execute("""
                UPDATE voice_companions 
                SET session_end = ?, duration_seconds = ?
                WHERE guild_id = ? AND user_id = ? AND companion_id = ? 
                AND channel_id = ? AND session_start = ? AND session_end IS NULL
            """, (left_at, duration_seconds, guild_id, user_id, companion_id, 
                  channel_id, joined_at))
            
            # Update companion's record with user
            await db.execute("""
                UPDATE voice_companions 
                SET session_end = ?, duration_seconds = ?
                WHERE guild_id = ? AND user_id = ? AND companion_id = ? 
                AND channel_id = ? AND session_start = ? AND session_end IS NULL
            """, (left_at, duration_seconds, guild_id, companion_id, user_id, 
                  channel_id, joined_at))
        
        await db.commit()
    
    return (duration_seconds, old_level, new_level)


async def user_moved_voice(guild_id: int, user_id: int, old_channel_id: int, 
                          new_channel_id: int, timestamp: Optional[datetime] = None):
    """
    Record when a user moves between voice channels.
    
    Args:
        guild_id: The guild ID
        user_id: The user ID
        old_channel_id: The previous voice channel ID
        new_channel_id: The new voice channel ID
        timestamp: When they moved (defaults to now)
    """
    # Leave old channel
    await user_left_voice(guild_id, user_id, timestamp)
    # Join new channel
    await user_joined_voice(guild_id, user_id, new_channel_id, timestamp)


def get_channel_members(guild_id: int, channel_id: int) -> set[int]:
    """
    Get all members currently in a voice channel.
    
    Args:
        guild_id: The guild ID
        channel_id: The voice channel ID
    
    Returns:
        Set of user IDs currently in the channel
    """
    members = set()
    for (g_id, u_id), session in active_sessions.items():
        if g_id == guild_id and session["channel_id"] == channel_id:
            members.add(u_id)
    return members


async def get_user_voice_stats(guild_id: int, user_id: int) -> dict:
    """
    Get voice channel statistics for a user.
    
    Returns:
        Dictionary with:
        - total_time: Total seconds in voice channels
        - sessions_count: Number of voice sessions
        - favorite_channel: Most used voice channel (id, name, time)
        - top_companions: List of (user_id, time_seconds) tuples
    """
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        # Get total time and session count
        async with db.execute("""
            SELECT 
                COALESCE(SUM(duration_seconds), 0) as total_time,
                COUNT(*) as sessions_count
            FROM voice_sessions
            WHERE guild_id = ? AND user_id = ? AND duration_seconds IS NOT NULL
        """, (guild_id, user_id)) as cur:
            row = await cur.fetchone()
            total_time = row[0] if row else 0
            sessions_count = row[1] if row else 0
        
        # Get favorite channel
        async with db.execute("""
            SELECT channel_id, SUM(duration_seconds) as total
            FROM voice_sessions
            WHERE guild_id = ? AND user_id = ? AND duration_seconds IS NOT NULL
            GROUP BY channel_id
            ORDER BY total DESC
            LIMIT 1
        """, (guild_id, user_id)) as cur:
            row = await cur.fetchone()
            favorite_channel = (row[0], row[1]) if row else (None, 0)
        
        # Get top companions
        async with db.execute("""
            SELECT companion_id, SUM(duration_seconds) as total
            FROM voice_companions
            WHERE guild_id = ? AND user_id = ? AND duration_seconds IS NOT NULL
            GROUP BY companion_id
            ORDER BY total DESC
            LIMIT 10
        """, (guild_id, user_id)) as cur:
            top_companions = await cur.fetchall()
        
        return {
            "total_time": int(total_time),
            "sessions_count": int(sessions_count),
            "favorite_channel": favorite_channel,
            "top_companions": [(int(row[0]), int(row[1])) for row in top_companions]
        }


async def get_channel_stats(guild_id: int, channel_id: int) -> dict:
    """
    Get statistics for a voice channel.
    
    Returns:
        Dictionary with:
        - total_time: Total time spent by all users
        - unique_users: Number of unique users
        - top_users: List of (user_id, time_seconds) tuples
    """
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        # Get total time
        async with db.execute("""
            SELECT COALESCE(SUM(duration_seconds), 0) as total_time
            FROM voice_sessions
            WHERE guild_id = ? AND channel_id = ? AND duration_seconds IS NOT NULL
        """, (guild_id, channel_id)) as cur:
            row = await cur.fetchone()
            total_time = row[0] if row else 0
        
        # Get unique users
        async with db.execute("""
            SELECT COUNT(DISTINCT user_id) as unique_users
            FROM voice_sessions
            WHERE guild_id = ? AND channel_id = ?
        """, (guild_id, channel_id)) as cur:
            row = await cur.fetchone()
            unique_users = row[0] if row else 0
        
        # Get top users
        async with db.execute("""
            SELECT user_id, SUM(duration_seconds) as total
            FROM voice_sessions
            WHERE guild_id = ? AND channel_id = ? AND duration_seconds IS NOT NULL
            GROUP BY user_id
            ORDER BY total DESC
            LIMIT 10
        """, (guild_id, channel_id)) as cur:
            top_users = await cur.fetchall()
        
        return {
            "total_time": int(total_time),
            "unique_users": int(unique_users),
            "top_users": [(int(row[0]), int(row[1])) for row in top_users]
        }


def format_duration(seconds: int) -> str:
    """Format duration in seconds to human-readable string."""
    if seconds < 60:
        return f"{seconds}s"
    
    minutes = seconds // 60
    seconds = seconds % 60
    
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    
    hours = minutes // 60
    minutes = minutes % 60
    
    if hours < 24:
        return f"{hours}h {minutes}m"
    
    days = hours // 24
    hours = hours % 24
    
    return f"{days}d {hours}h {minutes}m"
