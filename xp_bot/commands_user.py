"""Bot commands for user interactions."""
from typing import Optional
import discord
from discord.ext import commands
import aiosqlite
from datetime import datetime, timezone

from xp_bot.config import DB_PATH, DB_TIMEOUT
from xp_bot.database import get_xp, get_last_message
from xp_bot.leveling import level_from_total_xp, total_xp_for_level, xp_to_next
from xp_bot.rank_card import create_rank_card, download_avatar
from xp_bot.leaderboard_card import create_leaderboard_card
from xp_bot.user_stats import gather_user_stats, format_stats_message, create_activity_chart
from xp_bot.stats_card import create_stats_card
from xp_bot.channel_stats import gather_channel_stats, format_channel_stats_message
from xp_bot.channel_stats_card import create_channel_stats_card
from xp_bot.single_channel_stats import gather_single_channel_stats
from xp_bot.single_channel_stats_card import create_single_channel_stats_card
from xp_bot.word_stats import gather_word_stats
from xp_bot.word_stats_card import create_word_stats_card
from xp_bot.word_counter import word_counter_manager

@commands.command()
async def rank(ctx: commands.Context, user_input: Optional[str] = None):
    """
    Show rank and XP for a user with a graphical card.
    
    Usage:
      !rank           - Show your own rank
      !rank @user     - Show rank for mentioned user
      !rank 12345     - Show rank for user by ID
    """
    # Determine which user to check
    user = None
    user_id = None
    
    if user_input is None:
        # No argument provided, use command author
        user = ctx.author
        user_id = ctx.author.id
    else:
        # Try to parse user_input as a user mention, ID, or member
        # Strip mention format if present
        user_input_stripped = user_input.strip('<@!>').strip('<@>')
        
        try:
            user_id = int(user_input_stripped)
            # Try to get as a guild member first (from cache, includes status)
            user = ctx.guild.get_member(user_id)
            if user is None:
                # Not in cache, try to fetch as a user (won't have status)
                try:
                    user = await ctx.bot.fetch_user(user_id)
                except (discord.NotFound, discord.HTTPException):
                    await ctx.reply(f"Could not find user with ID {user_id}.")
                    return
        except ValueError:
            # Not a valid ID
            await ctx.reply(f"Invalid user ID or mention: {user_input}")
            return
    
    # Get user's XP and calculate rank
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        from xp_bot.database import get_combined_xp, get_main_user_id
        
        # Resolve to main account if this is an alt
        main_user_id = await get_main_user_id(db, ctx.guild.id, user_id)
        xp = await get_combined_xp(db, ctx.guild.id, user_id)
        
        # Get rank by counting users with more COMBINED XP
        # Build a temp table of combined XP for all users
        async with db.execute("""
            SELECT DISTINCT 
                COALESCE(a.main_user_id, ux.user_id) as effective_user_id,
                SUM(ux.xp) as total_xp
            FROM user_xp ux
            LEFT JOIN user_aliases a ON a.guild_id = ux.guild_id AND a.alt_user_id = ux.user_id
            WHERE ux.guild_id = ?
            GROUP BY effective_user_id
            HAVING SUM(ux.xp) > ?
        """, (ctx.guild.id, xp)) as cur:
            rank = await cur.fetchall()
            rank = len(rank) + 1

    lvl = level_from_total_xp(xp)
    current_level_xp = total_xp_for_level(lvl)
    into = xp - current_level_xp
    nxt = xp_to_next(lvl)

    # Download avatar
    avatar_url = user.display_avatar.url
    avatar_image = await download_avatar(avatar_url)
    
    # Determine status color
    # If user is a Member, use their actual status, otherwise default to gray
    if isinstance(user, discord.Member):
        status_map = {
            discord.Status.online: "green",
            discord.Status.idle: "yellow",
            discord.Status.dnd: "red",
            discord.Status.offline: "gray"
        }
        status_color = status_map.get(user.status, "gray")
    else:
        # User has left the server, use gray
        status_color = "gray"
    
    # Generate rank card
    try:
        # Get display name - use name for User objects, display_name for Members
        display_name = user.display_name if isinstance(user, discord.Member) else user.name
        discriminator_str = f"#{user.discriminator}" if user.discriminator != "0" else ""
        
        card_buffer = create_rank_card(
            username=display_name,
            discriminator=discriminator_str,
            level=lvl,
            rank=rank,
            current_xp=into,
            needed_xp=nxt,
            total_xp=xp,
            avatar_image=avatar_image,
            status_color=status_color
        )
        
        # Send as file
        file = discord.File(fp=card_buffer, filename="rank.png")
        await ctx.reply(file=file)
        
    except Exception as e:
        # Fallback to text if image generation fails
        print(f"[rank_card] Failed to generate image: {e}")
        display_name = user.display_name if isinstance(user, discord.Member) else user.name
        await ctx.reply(
            f"**{display_name}**\n"
            f"Rank: **#{rank}**\n"
            f"Level: **{lvl}**\n"
            f"XP: **{xp}**\n"
            f"Progress: **{into}/{nxt}**"
        )

@commands.command()
async def leaderboard(ctx: commands.Context, top: int = 10):
    """
    Show the XP leaderboard with a graphical card.
    
    Usage:
      !leaderboard      - Show top 10 users
      !leaderboard 25   - Show top 25 users (max)
    
    Note: Merged accounts show combined XP total.
    """
    top = max(1, min(top, 25))
    
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        # Get combined XP for all users (accounting for merged accounts)
        async with db.execute("""
            SELECT 
                COALESCE(a.main_user_id, ux.user_id) as effective_user_id,
                SUM(ux.xp) as total_xp
            FROM user_xp ux
            LEFT JOIN user_aliases a ON a.guild_id = ux.guild_id AND a.alt_user_id = ux.user_id
            WHERE ux.guild_id = ?
            GROUP BY effective_user_id
            ORDER BY total_xp DESC
            LIMIT ?
        """, (ctx.guild.id, top)) as cur:
            rows = await cur.fetchall()

    if not rows:
        await ctx.reply("No data yet.")
        return
    
    # Prepare entries for the card
    entries = []
    avatar_urls = []
    
    for i, (user_id, xp) in enumerate(rows, start=1):
        member = ctx.guild.get_member(user_id)
        if member:
            username = member.display_name
            discriminator = f"#{member.discriminator}" if member.discriminator != "0" else ""
            avatar_urls.append(member.display_avatar.url)
        else:
            # User not in guild, try to fetch as User
            try:
                user = await ctx.bot.fetch_user(user_id)
                username = user.name
                discriminator = f"#{user.discriminator}" if user.discriminator != "0" else ""
                avatar_urls.append(user.display_avatar.url)
            except (discord.NotFound, discord.HTTPException):
                username = f"User {user_id}"
                discriminator = ""
                avatar_urls.append(None)
        
        lvl = level_from_total_xp(int(xp))
        current_level_xp = total_xp_for_level(lvl)
        xp_into_level = int(xp) - current_level_xp
        xp_needed = xp_to_next(lvl)
        progress_ratio = xp_into_level / xp_needed if xp_needed > 0 else 0
        
        entries.append((i, username, discriminator, lvl, int(xp), None, progress_ratio))
    
    # Download avatars
    try:
        avatars = []
        for url in avatar_urls:
            if url:
                avatar = await download_avatar(url)
                avatars.append(avatar)
            else:
                avatars.append(None)
        
        # Update entries with avatars
        entries = [
            (rank, name, disc, lvl, xp, avatar, prog)
            for (rank, name, disc, lvl, xp, _, prog), avatar in zip(entries, avatars)
        ]
        
        # Generate leaderboard card
        card_buffer = create_leaderboard_card(entries, ctx.guild.name)
        
        # Send as file
        file = discord.File(fp=card_buffer, filename="leaderboard.png")
        await ctx.reply(file=file)
        
    except Exception as e:
        # Fallback to text if image generation fails
        print(f"[leaderboard_card] Failed to generate image: {e}")
        import traceback
        traceback.print_exc()
        
        lines = []
        for i, (user_id, xp) in enumerate(rows, start=1):
            member = ctx.guild.get_member(user_id)
            if member:
                name = member.display_name
            else:
                try:
                    user = await ctx.bot.fetch_user(user_id)
                    name = user.name
                except (discord.NotFound, discord.HTTPException):
                    name = f"User {user_id}"
            lvl = level_from_total_xp(int(xp))
            lines.append(f"**{i}. {name}** — Lvl {lvl} ({xp} XP)")
        await ctx.reply("\n".join(lines))

@commands.command()
async def leaderboardtext(ctx: commands.Context, top: int = 10):
    """
    Show the XP leaderboard (text only).
    
    Usage:
      !leaderboardtext      - Show top 10 users
      !leaderboardtext 25   - Show top 25 users (max)
    
    Note: Merged accounts show combined XP total.
    """
    top = max(1, min(top, 25))
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        # Get combined XP for all users (accounting for merged accounts)
        async with db.execute("""
            SELECT 
                COALESCE(a.main_user_id, ux.user_id) as effective_user_id,
                SUM(ux.xp) as total_xp
            FROM user_xp ux
            LEFT JOIN user_aliases a ON a.guild_id = ux.guild_id AND a.alt_user_id = ux.user_id
            WHERE ux.guild_id = ?
            GROUP BY effective_user_id
            ORDER BY total_xp DESC
            LIMIT ?
        """, (ctx.guild.id, top)) as cur:
            rows = await cur.fetchall()

    lines = []
    for i, (user_id, xp) in enumerate(rows, start=1):
        member = ctx.guild.get_member(user_id)
        if member:
            name = member.display_name
        else:
            # User not in guild, try to fetch as User
            try:
                user = await ctx.bot.fetch_user(user_id)
                name = user.name
            except (discord.NotFound, discord.HTTPException):
                name = f"User {user_id}"
        lvl = level_from_total_xp(int(xp))
        lines.append(f"**{i}. {name}** — Lvl {lvl} ({xp:,} XP)")
    await ctx.reply("\n".join(lines) if lines else "No data yet.")

@commands.command()
async def ranktext(ctx: commands.Context, member: Optional[discord.Member] = None):
    """
    Show rank and XP for a user (text only).
    
    Usage:
      !ranktext           - Show your own rank
      !ranktext @user     - Show rank for mentioned user
    
    Note: Shows combined XP if user has merged accounts.
    """
    member = member or ctx.author
    
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        from xp_bot.database import get_combined_xp, get_main_user_id
        
        xp = await get_combined_xp(db, ctx.guild.id, member.id)
        
        # Get rank by counting users with more COMBINED XP
        async with db.execute("""
            SELECT DISTINCT 
                COALESCE(a.main_user_id, ux.user_id) as effective_user_id,
                SUM(ux.xp) as total_xp
            FROM user_xp ux
            LEFT JOIN user_aliases a ON a.guild_id = ux.guild_id AND a.alt_user_id = ux.user_id
            WHERE ux.guild_id = ?
            GROUP BY effective_user_id
            HAVING SUM(ux.xp) > ?
        """, (ctx.guild.id, xp)) as cur:
            rank = await cur.fetchall()
            rank = len(rank) + 1

    lvl = level_from_total_xp(xp)
    current_level_xp = total_xp_for_level(lvl)
    into = xp - current_level_xp
    nxt = xp_to_next(lvl)

    await ctx.reply(
        f"**{member.display_name}**\n"
        f"Rank: **#{rank}**\n"
        f"Level: **{lvl}**\n"
        f"XP: **{xp:,}**\n"
        f"Progress: **{into:,}/{nxt:,}**"
    )

@commands.command()
async def lastmsg(ctx: commands.Context, user: Optional[str] = None, channel: Optional[discord.TextChannel] = None):
    """Check when a user last sent a message in a channel.
    
    Usage:
      !lastmsg - Your last message in current channel
      !lastmsg @User - User's last message in current channel
      !lastmsg 123456789 - User's last message by ID in current channel
      !lastmsg @User #channel - User's last message in specific channel
    """
    # Parse the user argument
    member = None
    user_id = None
    user_display = None
    
    if user is None:
        member = ctx.author
        user_id = ctx.author.id
        user_display = ctx.author.display_name
    else:
        # Try to convert user mention or ID to Member
        try:
            # Remove mention formatting if present
            user_id_str = user.strip('<@!>').strip('<@>')
            user_id = int(user_id_str)
            member = ctx.guild.get_member(user_id)
            
            if member is None:
                # User not in server, but we can still check their data
                user_display = f"User {user_id}"
            else:
                user_display = member.display_name
        except ValueError:
            await ctx.reply(f"Invalid user format. Use @mention or user ID.")
            return
    
    # Default to current channel if no channel specified
    if channel is None:
        channel = ctx.channel
    
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        last_message_at = await get_last_message(db, ctx.guild.id, channel.id, user_id)
    
    if not last_message_at:
        left_note = " (user has left the server)" if member is None and user_id != ctx.author.id else ""
        await ctx.reply(f"No recorded message from **{user_display}** in {channel.mention}{left_note}.")
        return
    
    # Parse the ISO timestamp
    try:
        last_time = datetime.fromisoformat(last_message_at)
        # Convert to Discord timestamp for relative time display
        timestamp = int(last_time.timestamp())
        left_note = " *(user has left the server)*" if member is None and user_id != ctx.author.id else ""
        await ctx.reply(
            f"**{user_display}** last messaged in {channel.mention} <t:{timestamp}:R> (<t:{timestamp}:f>){left_note}"
        )
    except Exception as e:
        await ctx.reply(f"Error parsing timestamp: {e}")

@commands.command()
async def statstext(ctx: commands.Context, user_input: Optional[str] = None):
    """
    Show detailed statistics about a user's server activity (text format).
    
    Usage:
      !statstext          - Show your own stats
      !statstext @user    - Show stats for mentioned user
      !statstext 12345    - Show stats for user ID
    """
    # Determine which user to check
    user = None
    user_id = None
    
    if user_input is None:
        # No argument provided, use command author
        user = ctx.author
        user_id = ctx.author.id
    else:
        # Try to parse user_input as a user mention, ID, or member
        user_input_stripped = user_input.strip('<@!>').strip('<@>')
        
        try:
            user_id = int(user_input_stripped)
            # Try to get as a guild member first
            try:
                user = await ctx.guild.fetch_member(user_id)
            except (discord.NotFound, discord.HTTPException):
                # Not in guild, try to fetch as a user
                try:
                    user = await ctx.bot.fetch_user(user_id)
                except (discord.NotFound, discord.HTTPException):
                    # Can't fetch user, but we can still try to get stats
                    pass
        except ValueError:
            await ctx.reply(f"❌ Invalid user ID or mention: {user_input}")
            return
    
    # Send a "processing" message since this might take a moment
    processing_msg = await ctx.reply("📊 Gathering statistics, please wait...")
    
    try:
        # Gather statistics from archives
        stats = await gather_user_stats(ctx.guild.id, user_id)
        
        if stats is None:
            await processing_msg.edit(content=f"❌ No message data found for this user.")
            return
        
        # Get username for display
        if user:
            username = user.display_name if isinstance(user, discord.Member) else user.name
        else:
            username = f"User {user_id}"
        
        # Format and send statistics
        stats_message = format_stats_message(stats, username)
        activity_chart = create_activity_chart(stats['hourly_distribution'], stats['daily_distribution'])
        
        # Send as two messages if combined would be too long
        full_message = stats_message + "\n\n" + activity_chart
        
        if len(full_message) <= 2000:
            await processing_msg.edit(content=full_message)
        else:
            # Send in two parts
            await processing_msg.edit(content=stats_message)
            await ctx.send(activity_chart)
    
    except Exception as e:
        await processing_msg.edit(content=f"❌ Error gathering statistics: {e}")
        print(f"Error in stats command: {e}")
        import traceback
        traceback.print_exc()

@commands.command()
async def stats(ctx: commands.Context, user_input: Optional[str] = None):
    """
    Show detailed statistics about a user's server activity with a graphical card.
    
    Usage:
      !stats          - Show your own stats
      !stats @user    - Show stats for mentioned user
      !stats 12345    - Show stats for user ID
    """
    # Determine which user to check
    user = None
    user_id = None
    
    if user_input is None:
        # No argument provided, use command author
        user = ctx.author
        user_id = ctx.author.id
    else:
        # Try to parse user_input as a user mention, ID, or member
        user_input_stripped = user_input.strip('<@!>').strip('<@>')
        
        try:
            user_id = int(user_input_stripped)
            # Try to get as a guild member first
            try:
                user = await ctx.guild.fetch_member(user_id)
            except (discord.NotFound, discord.HTTPException):
                # Not in guild, try to fetch as a user
                try:
                    user = await ctx.bot.fetch_user(user_id)
                except (discord.NotFound, discord.HTTPException):
                    # Can't fetch user, but we can still try to get stats
                    pass
        except ValueError:
            await ctx.reply(f"❌ Invalid user ID or mention: {user_input}")
            return
    
    # Send a "processing" message since this might take a moment
    processing_msg = await ctx.reply("📊 Gathering statistics, please wait...")
    
    try:
        # Gather statistics from archives
        stats = await gather_user_stats(ctx.guild.id, user_id)
        
        if stats is None:
            await processing_msg.edit(content=f"❌ No message data found for this user.")
            return
        
        # Get username and avatar for display
        if user:
            username = user.display_name if isinstance(user, discord.Member) else user.name
            avatar_url = user.display_avatar.url
            avatar_image = await download_avatar(avatar_url)
        else:
            username = f"User {user_id}"
            avatar_image = None
        
        # Generate stats card
        try:
            card_buffer = create_stats_card(
                username=username,
                avatar_image=avatar_image,
                first_message_date=stats['first_message_date'],
                total_messages=stats['total_messages'],
                edited_messages=stats['edited_messages'],
                days_active=stats['days_since_join'],
                avg_messages_per_day=stats['avg_messages_per_day'],
                most_active_hour=stats['most_active_hour'],
                most_active_day=stats['most_active_day'],
                most_active_month=stats['most_active_month'],
                top_channels=stats['top_channels'],
                yearly_distribution=stats['yearly_distribution'],
                hourly_distribution=stats['hourly_distribution'],
                daily_distribution=stats['daily_distribution'],
                voice_stats=stats.get('voice_stats'),
            )
            
            # Send as file
            file = discord.File(fp=card_buffer, filename="stats.png")
            await processing_msg.delete()
            await ctx.reply(file=file)
            
        except Exception as e:
            # Fallback to text if image generation fails
            print(f"[stats_card] Failed to generate image: {e}")
            import traceback
            traceback.print_exc()
            
            stats_message = format_stats_message(stats, username)
            await processing_msg.edit(content=stats_message)
    
    except Exception as e:
        await processing_msg.edit(content=f"❌ Error gathering statistics: {e}")
        print(f"Error in stats command: {e}")
        import traceback
        traceback.print_exc()

@commands.command()
async def channelstats(ctx: commands.Context):
    """
    Show detailed statistics about all channels in the server.
    Displays a pie chart and breakdown of message activity per channel.
    
    Usage:
      !channelstats
    """
    # Send a "processing" message since this might take a moment
    processing_msg = await ctx.reply("📊 Gathering channel statistics, please wait...")
    
    try:
        # Gather statistics from archives
        stats = await gather_channel_stats(ctx.guild.id)
        
        if stats is None:
            await processing_msg.edit(content=f"❌ No channel data found for this server.")
            return
        
        # Generate channel stats card with pie chart
        try:
            card_buffer = create_channel_stats_card(
                guild_name=ctx.guild.name,
                total_messages=stats['total_messages'],
                top_channels=stats['top_channels'],
                channels_data=stats['channels']
            )
            
            # Send as file
            file = discord.File(fp=card_buffer, filename="channel_stats.png")
            await processing_msg.delete()
            await ctx.reply(file=file)
            
        except Exception as e:
            # Fallback to text if image generation fails
            print(f"[channel_stats_card] Failed to generate image: {e}")
            import traceback
            traceback.print_exc()
            
            stats_message = format_channel_stats_message(stats, ctx.guild.name)
            await processing_msg.edit(content=stats_message)
    
    except Exception as e:
        await processing_msg.edit(content=f"❌ Error gathering channel statistics: {e}")
        print(f"Error in channelstats command: {e}")
        import traceback
        traceback.print_exc()

@commands.command()
async def channelstatstext(ctx: commands.Context):
    """
    Show detailed statistics about all channels in the server (text format).
    
    Usage:
      !channelstatstext
    """
    # Send a "processing" message since this might take a moment
    processing_msg = await ctx.reply("📊 Gathering channel statistics, please wait...")
    
    try:
        # Gather statistics from archives
        stats = await gather_channel_stats(ctx.guild.id)
        
        if stats is None:
            await processing_msg.edit(content=f"❌ No channel data found for this server.")
            return
        
        stats_message = format_channel_stats_message(stats, ctx.guild.name)
        await processing_msg.edit(content=stats_message)
    
    except Exception as e:
        await processing_msg.edit(content=f"❌ Error gathering channel statistics: {e}")
        print(f"Error in channelstatstext command: {e}")
        import traceback
        traceback.print_exc()

@commands.command()
async def channelinfo(ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
    """
    Show detailed statistics for a specific channel with user contribution breakdown.
    Displays a pie chart showing who contributes the most to the channel.
    
    Usage:
      !channelinfo              - Stats for current channel
      !channelinfo #general     - Stats for mentioned channel
    """
    # Default to current channel if not specified
    if channel is None:
        channel = ctx.channel
    
    # Send a "processing" message since this might take a moment
    processing_msg = await ctx.reply(f"📊 Gathering statistics for #{channel.name}, please wait...")
    
    try:
        # Gather statistics from archives
        stats = await gather_single_channel_stats(ctx.guild.id, channel.id)
        
        if stats is None:
            await processing_msg.edit(content=f"❌ No data found for #{channel.name}.")
            return
        
        # Generate channel stats card with pie chart
        try:
            card_buffer = await create_single_channel_stats_card(
                channel_name=stats['channel_name'],
                total_messages=stats['total_messages'],
                unique_users=stats['unique_users'],
                user_contributions=stats['user_contributions'],
                first_message=stats['first_message'],
                last_message=stats['last_message'],
                days_active=stats['days_active'],
                avg_messages_per_day=stats['avg_messages_per_day'],
                messages_by_year=stats['messages_by_year'],
                edited_messages=stats['edited_messages'],
                bot=ctx.bot,
                guild=ctx.guild
            )
            
            # Send as file
            file = discord.File(fp=card_buffer, filename=f"{channel.name}_stats.png")
            await processing_msg.delete()
            await ctx.reply(file=file)
            
        except Exception as e:
            # Fallback to text if image generation fails
            print(f"[single_channel_stats_card] Failed to generate image: {e}")
            import traceback
            traceback.print_exc()
            
            # Format text message
            lines = [
                f"**Statistics for #{stats['channel_name']}**",
                "",
                f"**Total Messages:** {stats['total_messages']:,}",
                f"**Unique Users:** {stats['unique_users']}",
                f"**Days Active:** {stats['days_active']:,} days",
                f"**Avg Messages/Day:** {stats['avg_messages_per_day']:.1f}",
                f"**Edited Messages:** {stats['edited_messages']:,}",
                "",
                "**Top 10 Contributors:**"
            ]
            
            for i, (user_id, count) in enumerate(stats['user_contributions'][:10], 1):
                pct = (count / stats['total_messages']) * 100
                try:
                    member = ctx.guild.get_member(user_id)
                    name = member.display_name if member else f"User {user_id}"
                except:
                    name = f"User {user_id}"
                lines.append(f"{i}. **{name}** — {count:,} messages ({pct:.1f}%)")
            
            await processing_msg.edit(content="\n".join(lines))
    
    except Exception as e:
        await processing_msg.edit(content=f"❌ Error gathering channel statistics: {e}")
        print(f"Error in channelinfo command: {e}")
        import traceback
        traceback.print_exc()

@commands.command()
async def wordstats(ctx: commands.Context, channel: Optional[discord.TextChannel] = None, *words: str):
    """
    Track how many times specific word(s) appear in a channel with user breakdown.
    Shows who said the word(s) the most with a pie chart.
    Can also use a counter name to track the words that counter is tracking.
    
    Usage:
      !wordstats hello              - Track "hello" in current channel
      !wordstats #general hello     - Track "hello" in #general
      !wordstats hello world        - Track both "hello" and "world" in current channel
      !wordstats #general hello world - Track both words in #general
      !wordstats counter:mycount    - Use words from counter "mycount" in current channel
      !wordstats #general counter:mycount - Use counter words in #general
    """
    # Parse arguments - check if first arg is a channel or a word/counter
    if channel is not None and not isinstance(channel, discord.TextChannel):
        # First argument wasn't a channel, it's a word or counter name
        search_words = [channel] + list(words)
        channel = ctx.channel
    elif channel is None:
        # No channel specified, first word should be in words
        if not words:
            await ctx.reply("❌ Please specify at least one word to track or a counter name.\nUsage: `!wordstats [#channel] <word1> [word2] ...` or `!wordstats [#channel] counter:<name>`")
            return
        search_words = list(words)
        channel = ctx.channel
    else:
        # Channel was specified correctly
        if not words:
            await ctx.reply("❌ Please specify at least one word to track or a counter name.\nUsage: `!wordstats [#channel] <word1> [word2] ...` or `!wordstats [#channel] counter:<name>`")
            return
        search_words = list(words)
    
    # Check if we're using a counter name (format: "counter:name")
    counter_name = None
    if len(search_words) == 1 and search_words[0].startswith("counter:"):
        counter_name = search_words[0][8:]  # Remove "counter:" prefix
        
        # Get words from the counter
        guild_counters = word_counter_manager.get_guild_counters(ctx.guild.id)
        if counter_name not in guild_counters:
            await ctx.reply(f"❌ Counter `{counter_name}` not found. Use `!listcounters` to see available counters.")
            return
        
        search_words = guild_counters[counter_name]["words"]
        if not search_words:
            await ctx.reply(f"❌ Counter `{counter_name}` has no words to track.")
            return
    
    # Format words for display
    words_display = ", ".join([f'"{word}"' for word in search_words])
    counter_suffix = f" (from counter: {counter_name})" if counter_name else ""
    
    # Send a "processing" message
    processing_msg = await ctx.reply(f"📊 Tracking {words_display} in #{channel.name}{counter_suffix}, please wait...")
    
    try:
        # Gather statistics from archives
        stats = await gather_word_stats(ctx.guild.id, channel.id, search_words)
        
        if stats is None:
            await processing_msg.edit(content=f"❌ No usage found for {words_display} in #{channel.name}.")
            return
        
        # Generate word stats card with pie chart
        try:
            card_buffer = await create_word_stats_card(
                channel_name=stats['channel_name'],
                searched_words=stats['searched_words'],
                total_occurrences=stats['total_occurrences'],
                total_messages_with_word=stats['total_messages_with_word'],
                top_users=stats['top_users'],
                user_message_count=stats['user_message_count'],
                first_usage=stats['first_usage'],
                last_usage=stats['last_usage'],
                usage_by_year=stats['usage_by_year'],
                bot=ctx.bot,
                guild=ctx.guild
            )
            
            # Send as file
            word_filename = "_".join(search_words[:3])  # Use first 3 words for filename
            if len(word_filename) > 30:
                word_filename = word_filename[:30]
            file = discord.File(fp=card_buffer, filename=f"word_stats_{word_filename}.png")
            await processing_msg.delete()
            await ctx.reply(file=file)
            
        except Exception as e:
            # Fallback to text if image generation fails
            print(f"[word_stats_card] Failed to generate image: {e}")
            import traceback
            traceback.print_exc()
            
            # Format text message
            lines = [
                f"**Word Usage Statistics for #{stats['channel_name']}**",
                f"**Tracking:** {words_display}",
                "",
                f"**Total Uses:** {stats['total_occurrences']:,}",
                f"**Messages:** {stats['total_messages_with_word']:,}",
                "",
                "**Top 10 Users:**"
            ]
            
            for i, (user_id, count) in enumerate(stats['top_users'][:10], 1):
                pct = (count / stats['total_occurrences']) * 100
                msg_count = stats['user_message_count'].get(user_id, 0)
                try:
                    member = ctx.guild.get_member(user_id)
                    name = member.display_name if member else f"User {user_id}"
                except:
                    name = f"User {user_id}"
                lines.append(f"{i}. **{name}** — {count:,} uses ({pct:.1f}%) • {msg_count} messages")
            
            await processing_msg.edit(content="\n".join(lines))
    
    except Exception as e:
        await processing_msg.edit(content=f"❌ Error gathering word statistics: {e}")
        print(f"Error in wordstats command: {e}")
        import traceback
        traceback.print_exc()

def setup(bot: commands.Bot):
    """Add commands to the bot."""
    bot.add_command(rank)
    bot.add_command(ranktext)
    bot.add_command(leaderboard)
    bot.add_command(leaderboardtext)
    bot.add_command(lastmsg)
    bot.add_command(stats)
    bot.add_command(statstext)
    bot.add_command(channelstats)
    bot.add_command(channelstatstext)
    bot.add_command(channelinfo)
    bot.add_command(wordstats)
