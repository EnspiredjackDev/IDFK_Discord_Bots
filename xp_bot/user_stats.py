"""User statistics gathering from archived messages."""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Optional
import discord
import aiosqlite

from xp_bot.config import DB_PATH, DB_TIMEOUT
from xp_bot.database import get_main_user_id, get_user_aliases

def parse_timestamp(ts_str: str) -> datetime:
    """Parse ISO timestamp string to datetime."""
    return datetime.fromisoformat(ts_str.replace('+00:00', '')).replace(tzinfo=timezone.utc)

async def gather_user_stats(guild_id: int, user_id: int) -> Optional[dict]:
    """
    Gather comprehensive statistics for a user from archived messages.
    
    If the user is part of a merged account group, stats include all accounts.
    
    Returns dict with:
    - first_message_date: datetime of first message
    - total_messages: total message count
    - deleted_messages: count of deleted messages
    - edited_messages: count of edited messages
    - avg_messages_per_day: average messages per day since joining
    - most_active_hour: hour of day (0-23) with most messages
    - most_active_day: day of week (0=Monday, 6=Sunday) with most messages
    - most_active_month: month (1-12) with most messages
    - hourly_distribution: dict of hour -> message count
    - daily_distribution: dict of day_of_week -> message count
    - monthly_distribution: dict of month -> message count
    - yearly_distribution: dict of year -> message count
    - channels_used: dict of channel_name -> message count
    """
    # Get all user IDs to include (main + alts)
    user_ids_to_include = set([user_id])
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        # Check if this user is an alt, get their main
        main_user_id = await get_main_user_id(db, guild_id, user_id)
        if main_user_id != user_id:
            # This is an alt, include the main
            user_ids_to_include.add(main_user_id)
        
        # Get all alts of the main user
        alts = await get_user_aliases(db, guild_id, main_user_id)
        user_ids_to_include.update(alts)
    
    archive_base = Path(f"archives/{guild_id}")
    
    if not archive_base.exists():
        return None
    
    # Statistics accumulators
    first_message = None
    total_messages = 0
    deleted_messages = 0
    edited_messages = 0
    
    hourly_distribution = defaultdict(int)
    daily_distribution = defaultdict(int)
    monthly_distribution = defaultdict(int)
    yearly_distribution = defaultdict(int)
    channels_used = defaultdict(int)
    
    # Track message IDs we've seen (to detect deleted messages)
    message_ids_seen = set()
    
    # Process all channel archive files
    for archive_file in archive_base.glob("*.jsonl"):
        with open(archive_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    msg = json.loads(line.strip())
                    
                    # Check if this message is from any of our user IDs
                    if msg.get('author_id') in user_ids_to_include:
                        message_ids_seen.add(msg['id'])
                        total_messages += 1
                        
                        # Parse timestamp
                        created_at = parse_timestamp(msg['created_at'])
                        
                        # Track first message
                        if first_message is None or created_at < first_message:
                            first_message = created_at
                        
                        # Check if edited
                        if msg.get('edited_at') is not None:
                            edited_messages += 1
                        
                        # Distribution statistics
                        hourly_distribution[created_at.hour] += 1
                        daily_distribution[created_at.weekday()] += 1
                        monthly_distribution[created_at.month] += 1
                        yearly_distribution[created_at.year] += 1
                        
                        # Channel usage
                        channel_name = msg.get('channel_name', 'Unknown')
                        channels_used[channel_name] += 1
                        
                except (json.JSONDecodeError, KeyError) as e:
                    # Skip malformed lines
                    continue
    
    # If no messages found
    if total_messages == 0:
        return None
    
    # Calculate days since first message
    now = datetime.now(timezone.utc)
    days_since_join = max(1, (now - first_message).days)
    avg_messages_per_day = total_messages / days_since_join
    
    # Find most active times
    most_active_hour = max(hourly_distribution.items(), key=lambda x: x[1])[0] if hourly_distribution else 0
    most_active_day = max(daily_distribution.items(), key=lambda x: x[1])[0] if daily_distribution else 0
    most_active_month = max(monthly_distribution.items(), key=lambda x: x[1])[0] if monthly_distribution else 1
    
    # Get top channels
    top_channels = sorted(channels_used.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # Get voice statistics
    voice_stats = None
    try:
        from xp_bot.voice_tracking import get_user_voice_stats
        voice_stats = await get_user_voice_stats(guild_id, user_id)
    except Exception as e:
        print(f"[user_stats] Failed to get voice stats: {e}")
    
    return {
        'first_message_date': first_message,
        'total_messages': total_messages,
        'deleted_messages': deleted_messages,  # Note: We can't accurately track this from archives alone
        'edited_messages': edited_messages,
        'avg_messages_per_day': avg_messages_per_day,
        'days_since_join': days_since_join,
        'most_active_hour': most_active_hour,
        'most_active_day': most_active_day,
        'most_active_month': most_active_month,
        'hourly_distribution': dict(hourly_distribution),
        'daily_distribution': dict(daily_distribution),
        'monthly_distribution': dict(monthly_distribution),
        'yearly_distribution': dict(yearly_distribution),
        'top_channels': top_channels,
        'voice_stats': voice_stats,
    }

def format_stats_message(stats: dict, username: str) -> str:
    """Format statistics into a Discord message."""
    day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    month_names = ['', 'January', 'February', 'March', 'April', 'May', 'June', 
                   'July', 'August', 'September', 'October', 'November', 'December']
    
    # Format first message date
    first_msg_str = stats['first_message_date'].strftime('%B %d, %Y')
    
    # Build the message
    lines = [
        f"📊 **Statistics for {username}**",
        "",
        f"🗓️ **First Message:** {first_msg_str}",
        f"📝 **Total Messages:** {stats['total_messages']:,}",
        f"✏️ **Edited Messages:** {stats['edited_messages']:,} ({stats['edited_messages']/stats['total_messages']*100:.1f}%)",
        f"📅 **Days Active:** {stats['days_since_join']:,} days",
        f"📈 **Average Messages/Day:** {stats['avg_messages_per_day']:.1f}",
        "",
        "⏰ **Most Active Times:**",
        f"• **Hour:** {stats['most_active_hour']:02d}:00 - {stats['most_active_hour']:02d}:59",
        f"• **Day:** {day_names[stats['most_active_day']]}",
        f"• **Month:** {month_names[stats['most_active_month']]}",
    ]
    
    # Add top channels
    if stats['top_channels']:
        lines.append("")
        lines.append("💬 **Top Channels:**")
        for i, (channel, count) in enumerate(stats['top_channels'][:3], 1):
            percentage = (count / stats['total_messages']) * 100
            lines.append(f"{i}. **#{channel}** — {count:,} messages ({percentage:.1f}%)")
    
    # Add yearly breakdown if multiple years
    if len(stats['yearly_distribution']) > 1:
        lines.append("")
        lines.append("📆 **Activity by Year:**")
        for year in sorted(stats['yearly_distribution'].keys(), reverse=True):
            count = stats['yearly_distribution'][year]
            lines.append(f"• **{year}:** {count:,} messages")
    
    return "\n".join(lines)

def create_activity_chart(hourly_dist: dict, daily_dist: dict) -> str:
    """Create a simple ASCII chart for activity patterns."""
    # Hourly chart (0-23)
    hourly_chart = []
    max_hourly = max(hourly_dist.values()) if hourly_dist else 1
    
    hourly_chart.append("**📊 Hourly Activity (24h):**")
    hourly_chart.append("```")
    
    # Group hours into 6 4-hour blocks for readability
    blocks = [
        (0, 4, "00-04"),
        (4, 8, "04-08"),
        (8, 12, "08-12"),
        (12, 16, "12-16"),
        (16, 20, "16-20"),
        (20, 24, "20-24"),
    ]
    
    for start, end, label in blocks:
        block_total = sum(hourly_dist.get(h, 0) for h in range(start, end))
        bar_length = int((block_total / max_hourly) * 20) if max_hourly > 0 else 0
        bar = "█" * bar_length
        hourly_chart.append(f"{label}: {bar} {block_total}")
    
    hourly_chart.append("```")
    
    # Daily chart
    day_names_short = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    daily_chart = []
    max_daily = max(daily_dist.values()) if daily_dist else 1
    
    daily_chart.append("**📅 Weekly Activity:**")
    daily_chart.append("```")
    
    for day_num, day_name in enumerate(day_names_short):
        count = daily_dist.get(day_num, 0)
        bar_length = int((count / max_daily) * 20) if max_daily > 0 else 0
        bar = "█" * bar_length
        daily_chart.append(f"{day_name}: {bar} {count}")
    
    daily_chart.append("```")
    
    return "\n".join(hourly_chart) + "\n" + "\n".join(daily_chart)
