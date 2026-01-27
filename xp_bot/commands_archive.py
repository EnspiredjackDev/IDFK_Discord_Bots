"""Commands for viewing archived messages."""
import json
from typing import Optional
from pathlib import Path
from datetime import datetime
import discord
from discord.ext import commands

from xp_bot.archiving import archive_path

# Store for tracking active views (message_id -> view_data)
active_views = {}

def truncate_text(text: str, max_len: int = 50) -> str:
    """Truncate text to max length, adding ellipsis if needed."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."

def parse_archive_entries(archive_file: Path, event_type: str = "delete", limit: int = 10):
    """Parse archive file and extract entries of a specific type."""
    entries = []
    if not archive_file.exists():
        return entries
    
    with archive_file.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line.strip())
                if obj.get("event") == event_type:
                    entries.append(obj)
            except json.JSONDecodeError:
                continue
    
    # Return the most recent entries (file is chronological)
    return entries[-limit:]

def find_message_content(archive_file: Path, message_id: int) -> Optional[str]:
    """Find the original content of a message by its ID."""
    if not archive_file.exists():
        return None
    
    with archive_file.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line.strip())
                # Look for the original message (not an event)
                if obj.get("id") == message_id and "event" not in obj:
                    return obj.get("content", "")
            except json.JSONDecodeError:
                continue
    return None

@commands.command()
async def deletes(ctx: commands.Context, channel: Optional[discord.TextChannel] = None, limit: int = 10):
    """
    Show recent deleted messages in a channel.
    
    Usage:
      !deletes             - Show deletes from current channel
      !deletes #general    - Show deletes from #general
      !deletes #general 20 - Show last 20 deletes from #general (max 50)
    """
    channel = channel or ctx.channel
    limit = max(1, min(limit, 50))  # Cap at 50
    
    archive_file = archive_path(ctx.guild.id, channel.id)
    
    if not archive_file.exists():
        await ctx.reply(f"No archive found for {channel.mention}.")
        return
    
    # Get deleted messages
    deletes_list = parse_archive_entries(archive_file, "delete", limit)
    
    if not deletes_list:
        await ctx.reply(f"No deleted messages found in {channel.mention}.")
        return
    
    # Build the message list with truncated content
    lines = [f"**Recent deleted messages in {channel.mention}:**\n"]
    message_map = {}  # index -> (message_id, full_content)
    
    for i, entry in enumerate(reversed(deletes_list), start=1):
        msg_id = entry.get("id")
        author_id = entry.get("author_id")
        deleted_at = entry.get("deleted_at", "")
        
        # Find the original message content
        content = find_message_content(archive_file, msg_id)
        if content is None:
            content = "[Content not found in archive]"
        
        # Get author mention or fallback
        author_mention = f"<@{author_id}>" if author_id else "Unknown"
        
        # Truncate for display
        truncated = truncate_text(content, 40)
        
        # Parse timestamp for better display
        try:
            dt = datetime.fromisoformat(deleted_at.replace('Z', '+00:00'))
            time_str = dt.strftime("%m/%d %H:%M")
        except:
            time_str = "Unknown time"
        
        lines.append(f"`{i}.` {author_mention} ({time_str}): {truncated}")
        message_map[i] = (msg_id, content, author_id, deleted_at)
    
    lines.append(f"\n*Use `!showdelete {channel.mention} <number>` to see full message*")
    
    # Store the mapping for later retrieval
    response = await ctx.reply("\n".join(lines))
    active_views[response.id] = {
        "guild_id": ctx.guild.id,
        "channel_id": channel.id,
        "messages": message_map,
        "expires": datetime.now().timestamp() + 600  # 10 min expiry
    }
    
@commands.command()
async def showdelete(ctx: commands.Context, channel: discord.TextChannel, index: int):
    """
    Show the full content of a deleted message by index.
    
    Usage:
      !showdelete #general 1
    
    Use the index number from the !deletes command output.
    """
    archive_file = archive_path(ctx.guild.id, channel.id)
    
    if not archive_file.exists():
        await ctx.reply(f"No archive found for {channel.mention}.")
        return
    
    # Get all deletes and find by index
    deletes_list = parse_archive_entries(archive_file, "delete", 50)
    
    if not deletes_list or index < 1 or index > len(deletes_list):
        await ctx.reply(f"Invalid index. Use `!deletes {channel.mention}` to see available messages.")
        return
    
    # Get the message (reverse order, most recent first)
    entry = list(reversed(deletes_list))[index - 1]
    msg_id = entry.get("id")
    author_id = entry.get("author_id")
    deleted_at = entry.get("deleted_at", "")
    
    # Find the original content
    content = find_message_content(archive_file, msg_id)
    if content is None:
        content = "[Content not found in archive]"
    
    # Build embed for better display
    embed = discord.Embed(
        title="Deleted Message",
        description=content if content else "*[Empty message]*",
        color=discord.Color.red()
    )
    
    if author_id:
        member = ctx.guild.get_member(author_id)
        author_name = member.display_name if member else f"User {author_id}"
        embed.set_author(name=author_name, icon_url=member.avatar.url if member and member.avatar else None)
    
    embed.add_field(name="Channel", value=channel.mention, inline=True)
    embed.add_field(name="Message ID", value=f"`{msg_id}`", inline=True)
    
    try:
        dt = datetime.fromisoformat(deleted_at.replace('Z', '+00:00'))
        embed.add_field(name="Deleted At", value=f"<t:{int(dt.timestamp())}:F>", inline=False)
    except:
        embed.add_field(name="Deleted At", value=deleted_at, inline=False)
    
    await ctx.reply(embed=embed)

@commands.command()
async def edits(ctx: commands.Context, channel: Optional[discord.TextChannel] = None, limit: int = 10):
    """
    Show recent edited messages in a channel with before/after content.
    
    Usage:
      !edits             - Show edits from current channel
      !edits #general    - Show edits from #general
      !edits #general 20 - Show last 20 edits from #general (max 50)
    """
    channel = channel or ctx.channel
    limit = max(1, min(limit, 50))
    
    archive_file = archive_path(ctx.guild.id, channel.id)
    
    if not archive_file.exists():
        await ctx.reply(f"No archive found for {channel.mention}.")
        return
    
    # Get edited messages
    edits_list = parse_archive_entries(archive_file, "edit", limit)
    
    if not edits_list:
        await ctx.reply(f"No edited messages found in {channel.mention}.")
        return
    
    # Build the message list
    lines = [f"**Recent edited messages in {channel.mention}:**\n"]
    
    for i, entry in enumerate(reversed(edits_list), start=1):
        author_id = entry.get("author_id")
        before = entry.get("before_content", "")
        after = entry.get("after_content", "")
        edited_at = entry.get("edited_at", "")
        
        author_mention = f"<@{author_id}>" if author_id else "Unknown"
        
        before_truncated = truncate_text(before, 30)
        after_truncated = truncate_text(after, 30)
        
        try:
            dt = datetime.fromisoformat(edited_at.replace('Z', '+00:00'))
            time_str = dt.strftime("%m/%d %H:%M")
        except:
            time_str = "Unknown"
        
        lines.append(f"`{i}.` {author_mention} ({time_str}):")
        lines.append(f"  Before: {before_truncated}")
        lines.append(f"  After: {after_truncated}")
    
    await ctx.reply("\n".join(lines))

def setup(bot: commands.Bot):
    """Add archive viewing commands to the bot."""
    bot.add_command(deletes)
    bot.add_command(showdelete)
    bot.add_command(edits)
