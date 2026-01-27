"""Word usage statistics gathering from archived messages."""
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from typing import Optional, Dict, List, Tuple
import re
import aiosqlite

from xp_bot.config import DB_PATH, DB_TIMEOUT
from xp_bot.database import get_main_user_id

def parse_timestamp(ts_str: str) -> datetime:
    """Parse ISO timestamp string to datetime."""
    return datetime.fromisoformat(ts_str.replace('+00:00', '')).replace(tzinfo=timezone.utc)

async def gather_word_stats(guild_id: int, channel_id: int, words: List[str]) -> Optional[dict]:
    """
    Gather statistics for specific word(s) usage in a channel.
    
    Alt accounts are merged with their main accounts in all statistics.
    
    Args:
        guild_id: Guild ID
        channel_id: Channel ID
        words: List of words to search for (case-insensitive)
    
    Returns dict with:
    - channel_name: str
    - searched_words: list of words searched
    - total_occurrences: total count of word occurrences
    - total_messages_with_word: number of messages containing the word(s)
    - user_occurrences: dict of user_id -> occurrence count
    - user_message_count: dict of user_id -> message count containing word(s)
    - first_usage: datetime of first usage
    - last_usage: datetime of last usage
    - usage_by_year: dict of year -> occurrence count
    - usage_by_month: dict of month -> occurrence count
    - top_users: list of (user_id, occurrence_count) tuples
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
    
    # Normalize words to lowercase for case-insensitive matching
    search_words = [word.lower() for word in words]
    
    # Statistics accumulators
    channel_name = None
    total_occurrences = 0
    total_messages_with_word = 0
    user_occurrences = defaultdict(int)
    user_message_count = defaultdict(int)
    first_usage = None
    last_usage = None
    usage_by_year = defaultdict(int)
    usage_by_month = defaultdict(int)
    
    # Process channel archive file
    with open(archive_file, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                msg = json.loads(line.strip())
                
                if channel_name is None:
                    channel_name = msg.get('channel_name', 'Unknown')
                
                content = msg.get('content', '').lower()
                user_id = msg.get('author_id')
                # Resolve to main user ID if this is an alt
                effective_user_id = user_id_mapping.get(user_id, user_id)
                
                created_at = parse_timestamp(msg['created_at'])
                
                # Count occurrences of each word in this message
                message_occurrences = 0
                for word in search_words:
                    # Use word boundary regex for accurate matching
                    pattern = r'\b' + re.escape(word) + r'\b'
                    matches = len(re.findall(pattern, content, re.IGNORECASE))
                    message_occurrences += matches
                
                if message_occurrences > 0:
                    total_occurrences += message_occurrences
                    total_messages_with_word += 1
                    user_occurrences[effective_user_id] += message_occurrences
                    user_message_count[effective_user_id] += 1
                    
                    # Track first and last usage
                    if first_usage is None or created_at < first_usage:
                        first_usage = created_at
                    if last_usage is None or created_at > last_usage:
                        last_usage = created_at
                    
                    # Usage distribution
                    usage_by_year[created_at.year] += message_occurrences
                    usage_by_month[created_at.month] += message_occurrences
                
            except (json.JSONDecodeError, KeyError) as e:
                # Skip malformed lines
                continue
    
    if total_occurrences == 0:
        return None
    
    # Sort users by occurrence count
    top_users = sorted(
        user_occurrences.items(),
        key=lambda x: x[1],
        reverse=True
    )
    
    return {
        'channel_name': channel_name,
        'searched_words': words,
        'total_occurrences': total_occurrences,
        'total_messages_with_word': total_messages_with_word,
        'user_occurrences': dict(user_occurrences),
        'user_message_count': dict(user_message_count),
        'first_usage': first_usage,
        'last_usage': last_usage,
        'usage_by_year': dict(usage_by_year),
        'usage_by_month': dict(usage_by_month),
        'top_users': top_users,
    }
