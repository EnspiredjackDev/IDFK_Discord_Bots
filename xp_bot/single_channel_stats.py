"""Single channel statistics gathering from archived messages."""
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from typing import Optional, Dict, List, Tuple
import aiosqlite

from xp_bot.config import DB_PATH, DB_TIMEOUT
from xp_bot.database import get_main_user_id

def parse_timestamp(ts_str: str) -> datetime:
    """Parse ISO timestamp string to datetime."""
    return datetime.fromisoformat(ts_str.replace('+00:00', '')).replace(tzinfo=timezone.utc)

async def gather_single_channel_stats(guild_id: int, channel_id: int) -> Optional[dict]:
    """
    Gather comprehensive statistics for a single channel from archived messages.
    
    Alt accounts are merged with their main accounts in all statistics.
    
    Returns dict with:
    - channel_name: str
    - total_messages: total message count
    - unique_users: number of unique users (after merging alts)
    - user_contributions: list of (user_id, message_count) tuples sorted by count
    - first_message: datetime
    - last_message: datetime
    - messages_by_hour: dict of hour -> message count
    - messages_by_day: dict of day_of_week -> message count
    - messages_by_year: dict of year -> message count
    - edited_messages: count of edited messages
    """
    archive_base = Path(f"archives/{guild_id}")
    archive_file = archive_base / f"{channel_id}.jsonl"
    
    if not archive_file.exists():
        return None
    
    # Build a mapping of all user IDs to their main IDs
    user_id_mapping = {}
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        # Get all user aliases for this guild
        async with db.execute("""
            SELECT alt_user_id, main_user_id FROM user_aliases WHERE guild_id = ?
        """, (guild_id,)) as cur:
            async for row in cur:
                alt_id, main_id = row
                user_id_mapping[alt_id] = main_id
    
    # Statistics accumulators
    channel_name = None
    total_messages = 0
    unique_users = set()
    user_contributions = defaultdict(int)
    first_message = None
    last_message = None
    messages_by_hour = defaultdict(int)
    messages_by_day = defaultdict(int)
    messages_by_year = defaultdict(int)
    edited_messages = 0
    
    # Process channel archive file
    with open(archive_file, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                msg = json.loads(line.strip())
                
                if channel_name is None:
                    channel_name = msg.get('channel_name', 'Unknown')
                
                user_id = msg.get('author_id')
                # Resolve to main user ID if this is an alt
                effective_user_id = user_id_mapping.get(user_id, user_id)
                
                created_at = parse_timestamp(msg['created_at'])
                
                total_messages += 1
                unique_users.add(effective_user_id)
                user_contributions[effective_user_id] += 1
                
                # Track first and last messages
                if first_message is None or created_at < first_message:
                    first_message = created_at
                if last_message is None or created_at > last_message:
                    last_message = created_at
                
                # Distribution statistics
                messages_by_hour[created_at.hour] += 1
                messages_by_day[created_at.weekday()] += 1
                messages_by_year[created_at.year] += 1
                
                # Check if edited
                if msg.get('edited_at') is not None:
                    edited_messages += 1
                
            except (json.JSONDecodeError, KeyError) as e:
                # Skip malformed lines
                continue
    
    if total_messages == 0:
        return None
    
    # Sort user contributions
    sorted_contributions = sorted(
        user_contributions.items(),
        key=lambda x: x[1],
        reverse=True
    )
    
    # Calculate days of activity
    days_active = (last_message - first_message).days if first_message and last_message else 0
    avg_messages_per_day = total_messages / max(1, days_active)
    
    return {
        'channel_name': channel_name,
        'total_messages': total_messages,
        'unique_users': len(unique_users),
        'user_contributions': sorted_contributions,
        'first_message': first_message,
        'last_message': last_message,
        'days_active': days_active,
        'avg_messages_per_day': avg_messages_per_day,
        'messages_by_hour': dict(messages_by_hour),
        'messages_by_day': dict(messages_by_day),
        'messages_by_year': dict(messages_by_year),
        'edited_messages': edited_messages,
    }
