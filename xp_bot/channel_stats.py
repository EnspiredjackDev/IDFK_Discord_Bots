"""Channel statistics gathering from archived messages."""
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from typing import Optional, Dict, List, Tuple
import aiosqlite

from xp_bot.config import DB_PATH, DB_TIMEOUT

def parse_timestamp(ts_str: str) -> datetime:
    """Parse ISO timestamp string to datetime."""
    return datetime.fromisoformat(ts_str.replace('+00:00', '')).replace(tzinfo=timezone.utc)

async def gather_channel_stats(guild_id: int) -> Optional[dict]:
    """
    Gather comprehensive statistics for all channels from archived messages.
    
    Alt accounts are merged with their main accounts in all statistics.
    
    Returns dict with:
    - total_messages: total message count across all channels
    - channels: dict of channel_name -> {
        message_count: int,
        unique_users: set of user_ids,
        most_active_user_id: user_id,
        most_active_user_count: message count,
        first_message: datetime,
        last_message: datetime
      }
    - top_channels: list of (channel_name, message_count) tuples sorted by count
    """
    archive_base = Path(f"archives/{guild_id}")
    
    if not archive_base.exists():
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
    total_messages = 0
    channels = defaultdict(lambda: {
        'message_count': 0,
        'unique_users': set(),
        'user_messages': defaultdict(int),
        'first_message': None,
        'last_message': None
    })
    
    # Process all channel archive files
    for archive_file in archive_base.glob("*.jsonl"):
        with open(archive_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    msg = json.loads(line.strip())
                    
                    channel_name = msg.get('channel_name', 'Unknown')
                    user_id = msg.get('author_id')
                    # Resolve to main user ID if this is an alt
                    effective_user_id = user_id_mapping.get(user_id, user_id)
                    
                    created_at = parse_timestamp(msg['created_at'])
                    
                    # Update channel stats
                    channel_data = channels[channel_name]
                    channel_data['message_count'] += 1
                    channel_data['unique_users'].add(effective_user_id)
                    channel_data['user_messages'][effective_user_id] += 1
                    
                    # Track first and last messages
                    if channel_data['first_message'] is None or created_at < channel_data['first_message']:
                        channel_data['first_message'] = created_at
                    if channel_data['last_message'] is None or created_at > channel_data['last_message']:
                        channel_data['last_message'] = created_at
                    
                    total_messages += 1
                    
                except (json.JSONDecodeError, KeyError) as e:
                    # Skip malformed lines
                    continue
    
    if total_messages == 0:
        return None
    
    # Process channel data to find most active user in each channel
    processed_channels = {}
    for channel_name, data in channels.items():
        most_active_user_id = None
        most_active_user_count = 0
        
        if data['user_messages']:
            most_active_user_id = max(data['user_messages'].items(), key=lambda x: x[1])[0]
            most_active_user_count = data['user_messages'][most_active_user_id]
        
        processed_channels[channel_name] = {
            'message_count': data['message_count'],
            'unique_users': len(data['unique_users']),
            'most_active_user_id': most_active_user_id,
            'most_active_user_count': most_active_user_count,
            'first_message': data['first_message'],
            'last_message': data['last_message']
        }
    
    # Get top channels sorted by message count
    top_channels = sorted(
        [(name, data['message_count']) for name, data in processed_channels.items()],
        key=lambda x: x[1],
        reverse=True
    )
    
    return {
        'total_messages': total_messages,
        'channels': processed_channels,
        'top_channels': top_channels
    }

def format_channel_stats_message(stats: dict, guild_name: str) -> str:
    """Format channel statistics into a Discord message."""
    lines = [
        f"📊 **Channel Statistics for {guild_name}**",
        "",
        f"**Total Messages:** {stats['total_messages']:,}",
        f"**Total Channels:** {len(stats['channels'])}",
        "",
        "**Top 10 Most Active Channels:**"
    ]
    
    for i, (channel, count) in enumerate(stats['top_channels'][:10], 1):
        pct = (count / stats['total_messages']) * 100
        channel_data = stats['channels'][channel]
        lines.append(f"{i}. **#{channel}** — {count:,} messages ({pct:.1f}%) • {channel_data['unique_users']} users")
    
    return "\n".join(lines)
