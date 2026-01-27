"""Admin commands for import management."""
from typing import Optional
import discord
from discord.ext import commands
import aiosqlite
import json
from pathlib import Path
from collections import defaultdict

from xp_bot.config import DB_PATH, DB_TIMEOUT
from xp_bot.database import get_import_cursor, update_last_message, get_xp, set_xp
from xp_bot.archiving import archive_path
from xp_bot import importer
from xp_bot.importer import import_text_channel, ImportStats
from xp_bot.leveling import level_from_total_xp, total_xp_for_level

def is_admin():
    """Check if user is an administrator."""
    async def predicate(ctx: commands.Context):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)

@commands.command()
@is_admin()
async def import_stop(ctx: commands.Context):
    """
    Request import to stop gracefully at the next safe point.
    
    Usage:
      !import_stop
    """
    importer.IMPORT_STOP_REQUESTED = True
    await ctx.reply("🛑 Import stop requested. I'll stop at the next safe point.")

@commands.command()
@is_admin()
async def import_status(ctx: commands.Context):
    """
    Show which channels have import cursors saved.
    
    Usage:
      !import_status
    
    Displays the last processed message ID for each channel.
    """
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        async with db.execute("""
            SELECT channel_id, last_message_id, updated_at
            FROM import_state
            WHERE guild_id=?
            ORDER BY updated_at DESC
            LIMIT 20
        """, (ctx.guild.id,)) as cur:
            rows = await cur.fetchall()

    if not rows:
        await ctx.reply("No import state saved yet.")
        return

    lines = []
    for channel_id, last_message_id, updated_at in rows:
        ch = ctx.guild.get_channel(int(channel_id))
        name = f"#{ch.name}" if isinstance(ch, discord.TextChannel) else f"Channel {channel_id}"
        lines.append(f"- {name}: last_id={last_message_id} (updated {updated_at})")
    await ctx.reply("**Import cursors (latest 20):**\n" + "\n".join(lines))

@commands.command()
@is_admin()
async def import_progress(ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
    """
    Show import progress for a specific channel.
    
    Usage:
      !import_progress #general
      !import_progress (uses current channel)
    """
    channel = channel or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
    if not channel:
        await ctx.reply("Please specify a text channel, e.g. `!import_progress #general`.")
        return
    
    await ctx.reply(f"⏳ Checking progress for {channel.mention}...")
    
    try:
        async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
            last_id = await get_import_cursor(db, ctx.guild.id, channel.id)
        
        if last_id == 0:
            await ctx.reply(f"📊 {channel.mention} has not been imported yet (no cursor saved).")
            return
        
        # Get the latest message ID in the channel
        try:
            latest_msg = None
            async for msg in channel.history(limit=1, oldest_first=False):
                latest_msg = msg
                break
            
            if not latest_msg:
                await ctx.reply(f"📊 {channel.mention} appears to be empty or inaccessible.")
                return
            
            latest_id = latest_msg.id
            
            # Get the oldest message ID
            oldest_msg = None
            async for msg in channel.history(limit=1, oldest_first=True):
                oldest_msg = msg
                break
            
            if not oldest_msg:
                oldest_id = 0
            else:
                oldest_id = oldest_msg.id
            
            # Calculate approximate progress
            # Discord snowflake IDs are roughly chronological
            if latest_id == oldest_id:
                progress = 100.0
            else:
                progress = ((last_id - oldest_id) / (latest_id - oldest_id)) * 100
                progress = max(0, min(100, progress))  # Clamp to 0-100
            
            # Count archived messages if archive exists
            archive_file = archive_path(ctx.guild.id, channel.id)
            archived_count = 0
            if archive_file.exists():
                with archive_file.open("r", encoding="utf-8") as f:
                    archived_count = sum(1 for _ in f)
            
            await ctx.reply(
                f"📊 **Import Progress for {channel.mention}**\n"
                f"- Last processed message ID: `{last_id}`\n"
                f"- Latest message ID in channel: `{latest_id}`\n"
                f"- Oldest message ID in channel: `{oldest_id}`\n"
                f"- Estimated progress: **{progress:.1f}%**\n"
                f"- Messages archived: **{archived_count}**\n"
                f"- Status: {'✅ Complete' if last_id >= latest_id else '🔄 In progress'}"
            )
            
        except discord.Forbidden:
            await ctx.reply(f"I don't have permission to read {channel.mention}'s history.")
        except discord.HTTPException as e:
            await ctx.reply(f"Error checking channel: `{e}`")
            
    except Exception as e:
        await ctx.reply(f"Error checking import progress: `{e}`")

@commands.command()
@is_admin()
async def import_channel(
    ctx: commands.Context,
    channel: Optional[discord.TextChannel] = None,
    *,
    flags: str = ""
):
    """
    Import one channel.

    Usage:
      !import_channel #general
      !import_channel #general noresume
      !import_channel #general noarchive
      !import_channel #general noxp
      !import_channel #general dry
      !import_channel #general noxp noarchive

    Flags:
      noresume - Start from beginning instead of resuming
      noarchive - Don't save to JSONL archive files
      dry - Dry run (don't save XP or cursor, but still archives)
      noxp - Archive messages but don't award XP (useful for stats-only channels)
    """
    # Parse flags
    flags_lower = flags.lower()
    resume = "noresume" not in flags_lower
    archive = "noarchive" not in flags_lower
    dry_run = "dry" in flags_lower
    no_xp = "noxp" in flags_lower
    importer.IMPORT_STOP_REQUESTED = False

    channel = channel or (ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
    if not channel:
        await ctx.reply("Pick a text channel to import, e.g. `!import_channel #general`.")
        return

    await ctx.reply(
        f"📥 Importing {channel.mention} (resume={resume}, archive={archive}, dry_run={dry_run}, no_xp={no_xp})…"
    )

    try:
        stats = await import_text_channel(channel, DB_PATH, resume=resume, archive=archive, dry_run=dry_run, no_xp=no_xp)
        stopped = " (stopped early)" if importer.IMPORT_STOP_REQUESTED else ""
        await ctx.reply(
            f"✅ Done importing {channel.mention}{stopped}\n"
            f"- Messages seen: **{stats.messages_seen}**\n"
            f"- Messages archived: **{stats.messages_archived}**\n"
            f"- XP events: **{stats.xp_events}**\n"
            f"- XP awarded: **{stats.xp_total_awarded}**\n"
            f"- Users touched: **{stats.users_touched}**"
        )
    except discord.Forbidden:
        await ctx.reply("I don't have permission to read that channel's history.")
    except discord.HTTPException as e:
        await ctx.reply(f"HTTP error while importing: `{e}`")

@commands.command()
@is_admin()
async def import_server(
    ctx: commands.Context,
    *,
    flags: str = ""
):
    """
    Import ALL readable text channels in the server.

    Usage:
      !import_server
      !import_server noresume
      !import_server noarchive
      !import_server noxp
      !import_server dry
      !import_server noxp noarchive
    
    Flags:
      noresume - Start from beginning instead of resuming
      noarchive - Don't save to JSONL archive files
      dry - Dry run (don't save XP or cursor, but still archives)
      noxp - Archive all channels but don't award XP
    """
    # Parse flags
    flags_lower = flags.lower()
    resume = "noresume" not in flags_lower
    archive = "noarchive" not in flags_lower
    dry_run = "dry" in flags_lower
    no_xp = "noxp" in flags_lower
    importer.IMPORT_STOP_REQUESTED = False

    channels = [
        ch for ch in ctx.guild.text_channels
        if ch.permissions_for(ctx.guild.me).read_message_history and ch.permissions_for(ctx.guild.me).view_channel
    ]

    if not channels:
        await ctx.reply("No readable text channels found.")
        return

    await ctx.reply(
        f"📦 Importing **{len(channels)}** channels (resume={resume}, archive={archive}, dry_run={dry_run}, no_xp={no_xp})…"
    )

    grand = ImportStats()
    for idx, ch in enumerate(channels, start=1):
        if importer.IMPORT_STOP_REQUESTED:
            break

        await ctx.send(f"➡️ ({idx}/{len(channels)}) Importing {ch.mention}…")
        try:
            stats = await import_text_channel(ch, DB_PATH, resume=resume, archive=archive, dry_run=dry_run, no_xp=no_xp)
        except (discord.Forbidden, discord.HTTPException):
            continue

        grand.messages_seen += stats.messages_seen
        grand.messages_archived += stats.messages_archived
        grand.xp_events += stats.xp_events
        grand.xp_total_awarded += stats.xp_total_awarded
        # users_touched here is per-channel; for a true unique count you'd track a set across channels.
        grand.users_touched += stats.users_touched

    stopped = " (stopped early)" if importer.IMPORT_STOP_REQUESTED else ""
    await ctx.reply(
        f"✅ Server import complete{stopped}\n"
        f"- Total messages seen: **{grand.messages_seen}**\n"
        f"- Total messages archived: **{grand.messages_archived}**\n"
        f"- Total XP events: **{grand.xp_events}**\n"
        f"- Total XP awarded: **{grand.xp_total_awarded}**"
    )

@commands.command()
@is_admin()
async def import_lastmsg(ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
    """
    Import last message timestamps from archive files to the database.
    
    Usage:
      !import_lastmsg #general - Import for specific channel
      !import_lastmsg          - Import for all archived channels
    
    This populates the last_message data used by !lastmsg command.
    """
    await ctx.reply("⏳ Starting last message import from archives...")
    
    archives_base = Path("archives") / str(ctx.guild.id)
    if not archives_base.exists():
        await ctx.reply("❌ No archives folder found for this server.")
        return
    
    # Determine which channels to process
    if channel:
        archive_files = [archives_base / f"{channel.id}.jsonl"]
    else:
        archive_files = list(archives_base.glob("*.jsonl"))
    
    if not archive_files:
        await ctx.reply("❌ No archive files found.")
        return
    
    total_processed = 0
    total_users = 0
    channels_processed = 0
    
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        for archive_file in archive_files:
            if not archive_file.exists():
                continue
            
            channel_id = int(archive_file.stem)
            
            # Dictionary to track the latest message per user in this channel
            user_latest: dict[int, tuple[str, int]] = {}  # user_id -> (timestamp, message_id)
            
            try:
                with archive_file.open("r", encoding="utf-8") as f:
                    for line_num, line in enumerate(f, start=1):
                        try:
                            msg_data = json.loads(line.strip())
                            author_id = msg_data.get("author_id")
                            created_at = msg_data.get("created_at")
                            msg_id = msg_data.get("id")
                            
                            if not author_id or not created_at:
                                continue
                            
                            # Keep track of the latest message for each user
                            if author_id not in user_latest or msg_id > user_latest[author_id][1]:
                                user_latest[author_id] = (created_at, msg_id)
                            
                            total_processed += 1
                            
                        except json.JSONDecodeError:
                            continue
                        except Exception as e:
                            print(f"Error processing line {line_num} in {archive_file}: {e}")
                            continue
                
                # Now insert all the latest messages for this channel
                for user_id, (timestamp, _) in user_latest.items():
                    await update_last_message(db, ctx.guild.id, channel_id, user_id, timestamp)
                
                total_users += len(user_latest)
                channels_processed += 1
                await db.commit()
                
                # Progress update
                ch = ctx.guild.get_channel(channel_id)
                ch_name = f"#{ch.name}" if ch else f"Channel {channel_id}"
                if channel:  # Only send detailed update if processing single channel
                    await ctx.send(f"✅ {ch_name}: {len(user_latest)} users processed")
                
            except Exception as e:
                await ctx.send(f"⚠️ Error processing {archive_file.name}: {e}")
                continue
    
    await ctx.reply(
        f"✅ **Last message import complete!**\n"
        f"- Channels processed: **{channels_processed}**\n"
        f"- Messages scanned: **{total_processed:,}**\n"
        f"- Unique user-channel pairs: **{total_users:,}**"
    )

@commands.command()
@is_admin()
async def setxp(ctx: commands.Context, user_input: str, xp: int):
    """
    Set a user's XP to a specific value.
    
    Usage:
      !setxp @user 5000
      !setxp @user 0
      !setxp 123456789 5000 (set XP by user ID)
    """
    if xp < 0:
        await ctx.reply("❌ XP cannot be negative.")
        return
    
    # Parse user input
    user_input_stripped = user_input.strip('<@!>').strip('<@>')
    
    try:
        user_id = int(user_input_stripped)
        # Try to get user info
        try:
            user = await ctx.guild.fetch_member(user_id)
            display_name = user.display_name
        except (discord.NotFound, discord.HTTPException):
            # User has left, try to fetch as User
            try:
                user = await ctx.bot.fetch_user(user_id)
                display_name = user.name
            except (discord.NotFound, discord.HTTPException):
                # Can't fetch user, just use ID
                display_name = f"User {user_id}"
    except ValueError:
        await ctx.reply(f"❌ Invalid user ID or mention: {user_input}")
        return
    
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        old_xp = await get_xp(db, ctx.guild.id, user_id)
        await set_xp(db, ctx.guild.id, user_id, xp)
        await db.commit()
    
    old_level = level_from_total_xp(old_xp)
    new_level = level_from_total_xp(xp)
    
    await ctx.reply(
        f"✅ Set **{display_name}**'s XP to **{xp:,}** (Level **{new_level}**)\n"
        f"Previous: **{old_xp:,}** XP (Level **{old_level}**)",
        mention_author=False
    )

@commands.command()
@is_admin()
async def addxp(ctx: commands.Context, user_input: str, amount: int):
    """
    Add or remove XP from a user.
    
    Usage:
      !addxp @user 1000    (add 1000 XP)
      !addxp @user -500    (remove 500 XP)
      !addxp 123456789 1000 (add XP by user ID)
    """
    # Parse user input
    user_input_stripped = user_input.strip('<@!>').strip('<@>')
    
    try:
        user_id = int(user_input_stripped)
        # Try to get user info
        try:
            user = await ctx.guild.fetch_member(user_id)
            display_name = user.display_name
        except (discord.NotFound, discord.HTTPException):
            # User has left, try to fetch as User
            try:
                user = await ctx.bot.fetch_user(user_id)
                display_name = user.name
            except (discord.NotFound, discord.HTTPException):
                # Can't fetch user, just use ID
                display_name = f"User {user_id}"
    except ValueError:
        await ctx.reply(f"❌ Invalid user ID or mention: {user_input}")
        return
    
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        old_xp = await get_xp(db, ctx.guild.id, user_id)
        new_xp = max(0, old_xp + amount)  # Don't allow negative XP
        await set_xp(db, ctx.guild.id, user_id, new_xp)
        await db.commit()
    
    old_level = level_from_total_xp(old_xp)
    new_level = level_from_total_xp(new_xp)
    
    if amount >= 0:
        action = f"Added **{amount:,}** XP"
    else:
        action = f"Removed **{abs(amount):,}** XP"
    
    await ctx.reply(
        f"✅ {action} for **{display_name}**\n"
        f"New total: **{new_xp:,}** XP (Level **{new_level}**)\n"
        f"Previous: **{old_xp:,}** XP (Level **{old_level}**)",
        mention_author=False
    )

@commands.command()
@is_admin()
async def setlevel(ctx: commands.Context, user_input: str, level: int):
    """
    Set a user's level (sets XP to the minimum for that level).
    
    Usage:
      !setlevel @user 50
      !setlevel @user 1
      !setlevel 123456789 50 (set level by user ID)
    """
    if level < 0:
        await ctx.reply("❌ Level cannot be negative.")
        return
    
    # Parse user input
    user_input_stripped = user_input.strip('<@!>').strip('<@>')
    
    try:
        user_id = int(user_input_stripped)
        # Try to get user info
        try:
            user = await ctx.guild.fetch_member(user_id)
            display_name = user.display_name
        except (discord.NotFound, discord.HTTPException):
            # User has left, try to fetch as User
            try:
                user = await ctx.bot.fetch_user(user_id)
                display_name = user.name
            except (discord.NotFound, discord.HTTPException):
                # Can't fetch user, just use ID
                display_name = f"User {user_id}"
    except ValueError:
        await ctx.reply(f"❌ Invalid user ID or mention: {user_input}")
        return
    
    new_xp = total_xp_for_level(level)
    
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        old_xp = await get_xp(db, ctx.guild.id, user_id)
        await set_xp(db, ctx.guild.id, user_id, new_xp)
        await db.commit()
    
    old_level = level_from_total_xp(old_xp)
    
    await ctx.reply(
        f"✅ Set **{display_name}** to **Level {level}** (**{new_xp:,}** XP)\n"
        f"Previous: Level **{old_level}** (**{old_xp:,}** XP)",
        mention_author=False
    )

@commands.command()
@is_admin()
async def clear(ctx: commands.Context, amount: int):
    """
    Delete the last N messages in the current channel.
    
    Usage:
      !clear 10    - Deletes the last 10 messages
      !clear 50    - Deletes the last 50 messages
    
    Notes:
      - Maximum 100 messages at once (Discord limitation)
      - Cannot delete messages older than 14 days (Discord limitation)
      - Requires Administrator permission
    """
    if amount <= 0:
        error_msg = await ctx.send("❌ Amount must be a positive number.")
        await ctx.message.delete()
        await error_msg.delete(delay=5.0)
        return
    
    if amount > 100:
        error_msg = await ctx.send("❌ Can only delete up to 100 messages at once due to Discord limitations.")
        await ctx.message.delete()
        await error_msg.delete(delay=5.0)
        return
    
    if not isinstance(ctx.channel, discord.TextChannel):
        error_msg = await ctx.send("❌ This command can only be used in text channels.")
        await ctx.message.delete()
        await error_msg.delete(delay=5.0)
        return
    
    try:
        # Delete the specified number of messages (including the command message)
        deleted = await ctx.channel.purge(limit=amount + 1)
        
        # Send a confirmation message that auto-deletes
        confirmation = await ctx.send(f"✅ Deleted **{len(deleted) - 1}** message(s).")
        await confirmation.delete(delay=5.0)
        
    except discord.Forbidden:
        error_msg = await ctx.send("❌ I don't have permission to delete messages in this channel.")
        try:
            await ctx.message.delete()
        except:
            pass
        await error_msg.delete(delay=5.0)
    except discord.HTTPException as e:
        error_msg = await ctx.send(f"❌ Error deleting messages: `{e}`")
        try:
            await ctx.message.delete()
        except:
            pass
        await error_msg.delete(delay=5.0)

@commands.command()
@is_admin()
async def mergeuser(ctx: commands.Context, alt_account: str, main_account: str):
    """
    Merge an alt account into a main account for combined XP/stats tracking.
    
    Usage:
      !mergeuser @alt @main
      !mergeuser 123456789 987654321
    
    The alt account's XP will be combined with the main account's XP.
    All future stats will show the combined total.
    This is useful for tracking users with multiple accounts.
    """
    # Parse alt account
    alt_stripped = alt_account.strip('<@!>').strip('<@>')
    try:
        alt_id = int(alt_stripped)
    except ValueError:
        await ctx.reply(f"❌ Invalid alt account ID or mention: {alt_account}")
        return
    
    # Parse main account
    main_stripped = main_account.strip('<@!>').strip('<@>')
    try:
        main_id = int(main_stripped)
    except ValueError:
        await ctx.reply(f"❌ Invalid main account ID or mention: {main_account}")
        return
    
    # Prevent merging a user with themselves
    if alt_id == main_id:
        await ctx.reply("❌ Cannot merge a user with themselves.")
        return
    
    # Get user display names
    try:
        alt_user = await ctx.guild.fetch_member(alt_id)
        alt_name = alt_user.display_name
    except (discord.NotFound, discord.HTTPException):
        try:
            alt_user = await ctx.bot.fetch_user(alt_id)
            alt_name = alt_user.name
        except (discord.NotFound, discord.HTTPException):
            alt_name = f"User {alt_id}"
    
    try:
        main_user = await ctx.guild.fetch_member(main_id)
        main_name = main_user.display_name
    except (discord.NotFound, discord.HTTPException):
        try:
            main_user = await ctx.bot.fetch_user(main_id)
            main_name = main_user.name
        except (discord.NotFound, discord.HTTPException):
            main_name = f"User {main_id}"
    
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        # Check if alt is already merged elsewhere
        from xp_bot.database import get_main_user_id, set_user_alias, get_combined_xp
        existing_main = await get_main_user_id(db, ctx.guild.id, alt_id)
        if existing_main != alt_id:
            await ctx.reply(f"❌ **{alt_name}** is already merged into another account. Use `!unmergeuser @{alt_name}` first.")
            return
        
        # Check if main is an alt of someone else
        main_parent = await get_main_user_id(db, ctx.guild.id, main_id)
        if main_parent != main_id:
            await ctx.reply(f"❌ **{main_name}** is an alt account. Merge into their main account instead.")
            return
        
        # Get XP before merge
        alt_xp = await get_xp(db, ctx.guild.id, alt_id)
        main_xp_before = await get_combined_xp(db, ctx.guild.id, main_id)
        
        # Create the alias relationship
        await set_user_alias(db, ctx.guild.id, alt_id, main_id)
        await db.commit()
        
        # Get combined XP after merge
        combined_xp = await get_combined_xp(db, ctx.guild.id, main_id)
    
    from xp_bot.leveling import level_from_total_xp
    combined_level = level_from_total_xp(combined_xp)
    
    await ctx.reply(
        f"✅ **Merged accounts successfully!**\n"
        f"**Alt:** {alt_name} ({alt_xp:,} XP)\n"
        f"**Main:** {main_name}\n"
        f"**Combined XP:** {combined_xp:,} (Level {combined_level})\n\n"
        f"Stats and rankings will now show {main_name}'s combined total from both accounts."
    )

@commands.command()
@is_admin()
async def unmergeuser(ctx: commands.Context, alt_account: str):
    """
    Unmerge an alt account from its main account.
    
    Usage:
      !unmergeuser @alt
      !unmergeuser 123456789
    
    The accounts will be tracked separately again.
    """
    # Parse alt account
    alt_stripped = alt_account.strip('<@!>').strip('<@>')
    try:
        alt_id = int(alt_stripped)
    except ValueError:
        await ctx.reply(f"❌ Invalid account ID or mention: {alt_account}")
        return
    
    # Get user display name
    try:
        alt_user = await ctx.guild.fetch_member(alt_id)
        alt_name = alt_user.display_name
    except (discord.NotFound, discord.HTTPException):
        try:
            alt_user = await ctx.bot.fetch_user(alt_id)
            alt_name = alt_user.name
        except (discord.NotFound, discord.HTTPException):
            alt_name = f"User {alt_id}"
    
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        from xp_bot.database import get_main_user_id, remove_user_alias, get_xp
        
        # Check if this user is actually merged
        main_id = await get_main_user_id(db, ctx.guild.id, alt_id)
        if main_id == alt_id:
            await ctx.reply(f"❌ **{alt_name}** is not merged with any account.")
            return
        
        # Get main user info
        try:
            main_user = await ctx.guild.fetch_member(main_id)
            main_name = main_user.display_name
        except (discord.NotFound, discord.HTTPException):
            try:
                main_user = await ctx.bot.fetch_user(main_id)
                main_name = main_user.name
            except (discord.NotFound, discord.HTTPException):
                main_name = f"User {main_id}"
        
        # Get XP values
        alt_xp = await get_xp(db, ctx.guild.id, alt_id)
        
        # Remove the alias
        await remove_user_alias(db, ctx.guild.id, alt_id)
        await db.commit()
    
    await ctx.reply(
        f"✅ **Unmerged accounts successfully!**\n"
        f"**{alt_name}** is no longer merged with **{main_name}**.\n"
        f"They will now be tracked separately (Alt has {alt_xp:,} XP)."
    )

@commands.command()
@is_admin()
async def listmerged(ctx: commands.Context, user_input: str):
    """
    List all alt accounts merged with a main account.
    
    Usage:
      !listmerged @user
      !listmerged 123456789
    """
    # Parse user
    user_stripped = user_input.strip('<@!>').strip('<@>')
    try:
        user_id = int(user_stripped)
    except ValueError:
        await ctx.reply(f"❌ Invalid user ID or mention: {user_input}")
        return
    
    # Get user display name
    try:
        user = await ctx.guild.fetch_member(user_id)
        user_name = user.display_name
    except (discord.NotFound, discord.HTTPException):
        try:
            user = await ctx.bot.fetch_user(user_id)
            user_name = user.name
        except (discord.NotFound, discord.HTTPException):
            user_name = f"User {user_id}"
    
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        from xp_bot.database import get_main_user_id, get_user_aliases, get_xp, get_combined_xp
        
        # Check if this user is an alt
        main_id = await get_main_user_id(db, ctx.guild.id, user_id)
        if main_id != user_id:
            # This is an alt, get the main account info
            try:
                main_user = await ctx.guild.fetch_member(main_id)
                main_name = main_user.display_name
            except (discord.NotFound, discord.HTTPException):
                try:
                    main_user = await ctx.bot.fetch_user(main_id)
                    main_name = main_user.name
                except (discord.NotFound, discord.HTTPException):
                    main_name = f"User {main_id}"
            
            await ctx.reply(
                f"ℹ️ **{user_name}** is an alt account.\n"
                f"Main account: **{main_name}**\n"
                f"Use `!listmerged @{main_name}` to see all alts."
            )
            return
        
        # This is a main account, list all alts
        alts = await get_user_aliases(db, ctx.guild.id, user_id)
        
        if not alts:
            await ctx.reply(f"**{user_name}** has no merged alt accounts.")
            return
        
        # Build the response
        lines = [f"**Merged accounts for {user_name}:**\n"]
        
        main_xp = await get_xp(db, ctx.guild.id, user_id)
        from xp_bot.leveling import level_from_total_xp
        main_level = level_from_total_xp(main_xp)
        lines.append(f"**Main:** {user_name} - {main_xp:,} XP (Level {main_level})")
        
        total_alt_xp = 0
        for alt_id in alts:
            try:
                alt_user = await ctx.guild.fetch_member(alt_id)
                alt_name = alt_user.display_name
            except (discord.NotFound, discord.HTTPException):
                try:
                    alt_user = await ctx.bot.fetch_user(alt_id)
                    alt_name = alt_user.name
                except (discord.NotFound, discord.HTTPException):
                    alt_name = f"User {alt_id}"
            
            alt_xp = await get_xp(db, ctx.guild.id, alt_id)
            total_alt_xp += alt_xp
            alt_level = level_from_total_xp(alt_xp)
            lines.append(f"**Alt:** {alt_name} - {alt_xp:,} XP (Level {alt_level})")
        
        combined = main_xp + total_alt_xp
        combined_level = level_from_total_xp(combined)
        lines.append(f"\n**Combined Total:** {combined:,} XP (Level {combined_level})")
    
    await ctx.reply("\n".join(lines))

def setup(bot: commands.Bot):
    """Add admin commands to the bot."""
    bot.add_command(import_stop)
    bot.add_command(import_status)
    bot.add_command(import_progress)
    bot.add_command(import_channel)
    bot.add_command(import_server)
    bot.add_command(import_lastmsg)
    bot.add_command(setxp)
    bot.add_command(addxp)
    bot.add_command(setlevel)
    bot.add_command(clear)
    bot.add_command(mergeuser)
    bot.add_command(unmergeuser)
    bot.add_command(listmerged)
