"""Voting commands - create polls and track participation."""
import discord
from discord.ext import commands
from datetime import datetime, timezone, timedelta
import aiosqlite
import re
from xp_bot.config import DB_PATH, DB_TIMEOUT


async def get_active_vote(guild_id: int, channel_id: int) -> tuple | None:
    """Get the active vote in a channel if one exists and hasn't expired."""
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        cursor = await db.execute("""
            SELECT id, message_id, question, end_time, message_count
            FROM votes
            WHERE guild_id = ? AND channel_id = ? AND ended = 0
            ORDER BY created_at DESC
            LIMIT 1
        """, (guild_id, channel_id))
        row = await cursor.fetchone()
        
        if not row:
            return None
        
        vote_id, message_id, question, end_time_str, message_count = row
        end_time = datetime.fromisoformat(end_time_str)
        
        # Check if vote has expired
        if datetime.now(timezone.utc) > end_time:
            # Mark as ended
            await db.execute("""
                UPDATE votes SET ended = 1 WHERE id = ?
            """, (vote_id,))
            await db.commit()
            return None
        
        return (vote_id, message_id, question, end_time, message_count)


async def has_been_reminded(vote_id: int, user_id: int) -> bool:
    """Check if a user has been reminded about a vote."""
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        cursor = await db.execute("""
            SELECT 1 FROM vote_reminders
            WHERE vote_id = ? AND user_id = ?
        """, (vote_id, user_id))
        return await cursor.fetchone() is not None


async def mark_as_reminded(vote_id: int, user_id: int):
    """Mark a user as having been reminded about a vote."""
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        await db.execute("""
            INSERT OR IGNORE INTO vote_reminders (vote_id, user_id, reminded_at)
            VALUES (?, ?, ?)
        """, (vote_id, user_id, datetime.now(timezone.utc).isoformat()))
        await db.commit()


async def increment_message_count(vote_id: int) -> int:
    """Increment and return the message count for a vote."""
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        await db.execute("""
            UPDATE votes SET message_count = message_count + 1
            WHERE id = ?
        """, (vote_id,))
        await db.commit()
        
        cursor = await db.execute("""
            SELECT message_count FROM votes WHERE id = ?
        """, (vote_id,))
        row = await cursor.fetchone()
        return row[0] if row else 0


async def track_early_participant(vote_id: int, user_id: int):
    """Track users who participated in the first 10 messages."""
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        await db.execute("""
            INSERT OR IGNORE INTO vote_early_participants (vote_id, user_id, participated_at)
            VALUES (?, ?, ?)
        """, (vote_id, user_id, datetime.now(timezone.utc).isoformat()))
        await db.commit()


async def was_early_participant(vote_id: int, user_id: int) -> bool:
    """Check if a user participated in the first 10 messages."""
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        cursor = await db.execute("""
            SELECT 1 FROM vote_early_participants
            WHERE vote_id = ? AND user_id = ?
        """, (vote_id, user_id))
        return await cursor.fetchone() is not None


async def check_and_send_reminder(message: discord.Message, bot: commands.Bot):
    """Check if we should send a vote reminder to this user."""
    # Ignore bots
    if message.author.bot:
        return
    
    # Check if there's an active vote in this channel
    vote_data = await get_active_vote(message.guild.id, message.channel.id)
    if not vote_data:
        return
    
    vote_id, vote_message_id, question, end_time, message_count = vote_data
    
    # Increment message count
    new_count = await increment_message_count(vote_id)
    
    # Track early participants (first 10 messages)
    if new_count <= 10:
        await track_early_participant(vote_id, message.author.id)
        return
    
    # Don't remind users who were active in the first 10 messages
    if await was_early_participant(vote_id, message.author.id):
        return
    
    # Check if user has already been reminded
    if await has_been_reminded(vote_id, message.author.id):
        return
    
    # Mark as reminded first to avoid race conditions
    await mark_as_reminded(vote_id, message.author.id)
    
    # Create the reminder message with jump link
    vote_url = f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{vote_message_id}"
    
    try:
        # Calculate time remaining
        time_remaining = end_time - datetime.now(timezone.utc)
        hours_remaining = int(time_remaining.total_seconds() / 3600)
        
        reminder_msg = await message.channel.send(
            f"📊 Hey {message.author.mention}! There's an active vote: **{question}**\n"
            f"[Jump to vote]({vote_url}) • {hours_remaining}h remaining"
        )
        
        # Delete after 10 seconds
        await reminder_msg.delete(delay=10)
        
    except Exception as e:
        print(f"[voting] Failed to send reminder: {e}")


def parse_duration(duration_str: str) -> tuple[timedelta | None, str]:
    """
    Parse a duration string and return a timedelta and the remaining string.
    
    Supports:
    - s/sec/seconds for seconds
    - m/min/minutes for minutes
    - h/hr/hours for hours
    - d/day/days for days
    - w/week/weeks for weeks
    - Plain numbers default to hours
    
    Returns (timedelta, remaining_string) or (None, original_string) if no duration found
    """
    # Try to match duration at the start: number followed by optional unit
    pattern = r'^(\d+)([smhdw]|sec|min|hr|hour|day|week|seconds|minutes|hours|days|weeks)?\s+'
    match = re.match(pattern, duration_str, re.IGNORECASE)
    
    if not match:
        return None, duration_str
    
    amount = int(match.group(1))
    unit = match.group(2).lower() if match.group(2) else 'h'  # Default to hours
    
    # Normalize unit to single letter
    unit_map = {
        's': 'seconds', 'sec': 'seconds', 'second': 'seconds', 'seconds': 'seconds',
        'm': 'minutes', 'min': 'minutes', 'minute': 'minutes', 'minutes': 'minutes',
        'h': 'hours', 'hr': 'hours', 'hour': 'hours', 'hours': 'hours',
        'd': 'days', 'day': 'days', 'days': 'days',
        'w': 'weeks', 'week': 'weeks', 'weeks': 'weeks',
    }
    
    unit_normalized = unit_map.get(unit, 'hours')
    
    # Create timedelta
    kwargs = {unit_normalized: amount}
    duration = timedelta(**kwargs)
    
    # Return duration and remaining string
    remaining = duration_str[match.end():].strip()
    return duration, remaining


@commands.command(name="vote")
async def create_vote(ctx: commands.Context, *, args: str):
    """
    Start a new vote/poll in the current channel.
    
    The vote will last for the specified duration (default 24 hours).
    Users can react with 👍 for yes or 👎 for no.
    After 10 messages, users who haven't been reminded will get a notification.
    
    Duration units:
      s/sec/seconds - seconds
      m/min/minutes - minutes
      h/hr/hours - hours (default)
      d/day/days - days
      w/week/weeks - weeks
    
    Usage:
      !vote <question>
      !vote <duration> <question>
    
    Examples:
      !vote Should we watch a movie tonight?
      !vote 2d Should we have a game night this weekend?
      !vote 30m Quick poll: pizza or burgers?
      !vote 1w What movie should we watch?
      !vote 12 Should we go out tonight? (12 hours)
    """
    # Check for active vote in this channel
    existing_vote = await get_active_vote(ctx.guild.id, ctx.channel.id)
    if existing_vote:
        await ctx.reply("⚠️ There's already an active vote in this channel! Please wait for it to end.")
        return
    
    # Try to parse duration from the start of args
    duration, question = parse_duration(args)
    
    # If no duration was parsed, use default and treat everything as question
    if duration is None:
        duration = timedelta(hours=24)
        question = args
    
    # Validate duration (max 4 weeks)
    max_duration = timedelta(weeks=4)
    if duration > max_duration:
        await ctx.reply(f"⚠️ Duration too long! Maximum is 4 weeks.")
        return
    
    # Validate question
    if not question or len(question.strip()) == 0:
        await ctx.reply("⚠️ Please provide a question for the vote!")
        return
    
    # Validate question
    if not question or len(question.strip()) == 0:
        await ctx.reply("⚠️ Please provide a question for the vote!")
        return
    
    # Create end time
    end_time = datetime.now(timezone.utc) + duration
    
    # Format duration for display
    total_seconds = int(duration.total_seconds())
    if total_seconds < 60:
        duration_str = f"{total_seconds}s"
    elif total_seconds < 3600:
        duration_str = f"{total_seconds // 60}m"
    elif total_seconds < 86400:
        duration_str = f"{total_seconds // 3600}h"
    elif total_seconds < 604800:
        duration_str = f"{total_seconds // 86400}d"
    else:
        duration_str = f"{total_seconds // 604800}w"
    
    # Create the vote embed
    embed = discord.Embed(
        title="📊 Vote",
        description=question,
        color=discord.Color.blue(),
        timestamp=end_time
    )
    embed.add_field(name="React to vote", value="👍 Yes\n\n👎 No", inline=False)
    embed.set_footer(text=f"Started by {ctx.author.display_name} • Duration: {duration_str} • Vote ends")
    
    vote_message = await ctx.send(embed=embed)
    
    # Add reactions
    await vote_message.add_reaction("👍")
    await vote_message.add_reaction("👎")
    
    # Store in database
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        await db.execute("""
            INSERT INTO votes (guild_id, channel_id, message_id, question, created_by, created_at, end_time, message_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            ctx.guild.id,
            ctx.channel.id,
            vote_message.id,
            question,
            ctx.author.id,
            datetime.now(timezone.utc).isoformat(),
            end_time.isoformat()
        ))
        await db.commit()
    
    # Delete the command message to keep chat clean
    try:
        await ctx.message.delete()
    except:
        pass


@commands.command(name="endvote")
async def end_vote(ctx: commands.Context):
    """
    End the active vote in the current channel and show results.
    
    Only the person who created the vote or admins can end it early.
    
    Usage:
      !endvote
    """
    vote_data = await get_active_vote(ctx.guild.id, ctx.channel.id)
    if not vote_data:
        await ctx.reply("❌ There's no active vote in this channel.")
        return
    
    vote_id, vote_message_id, question, end_time, message_count = vote_data
    
    # Check permissions
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        cursor = await db.execute("""
            SELECT created_by FROM votes WHERE id = ?
        """, (vote_id,))
        row = await cursor.fetchone()
        created_by = row[0] if row else None
    
    is_creator = created_by == ctx.author.id
    is_admin = ctx.author.guild_permissions.administrator
    
    if not (is_creator or is_admin):
        await ctx.reply("❌ Only the vote creator or administrators can end the vote early.")
        return
    
    # Fetch the vote message to count reactions
    try:
        vote_message = await ctx.channel.fetch_message(vote_message_id)
        
        yes_count = 0
        no_count = 0
        
        for reaction in vote_message.reactions:
            if str(reaction.emoji) == "👍":
                yes_count = reaction.count - 1  # Subtract bot's reaction
            elif str(reaction.emoji) == "👎":
                no_count = reaction.count - 1  # Subtract bot's reaction
        
        # Create results embed
        total_votes = yes_count + no_count
        yes_percent = (yes_count / total_votes * 100) if total_votes > 0 else 0
        no_percent = (no_count / total_votes * 100) if total_votes > 0 else 0
        
        result_embed = discord.Embed(
            title="📊 Vote Results",
            description=question,
            color=discord.Color.green() if yes_count > no_count else discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        result_embed.add_field(
            name="Results",
            value=f"👍 Yes: **{yes_count}** ({yes_percent:.1f}%)\n"
                  f"👎 No: **{no_count}** ({no_percent:.1f}%)\n"
                  f"Total votes: **{total_votes}**",
            inline=False
        )
        result_embed.set_footer(text="Vote ended")
        
        await ctx.send(embed=result_embed)
        
        # Mark as ended
        async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
            await db.execute("""
                UPDATE votes SET ended = 1 WHERE id = ?
            """, (vote_id,))
            await db.commit()
        
    except discord.NotFound:
        await ctx.reply("⚠️ Vote message not found. Marking as ended.")
        async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
            await db.execute("""
                UPDATE votes SET ended = 1 WHERE id = ?
            """, (vote_id,))
            await db.commit()


def setup(bot: commands.Bot):
    """Register voting commands."""
    bot.add_command(create_vote)
    bot.add_command(end_vote)
