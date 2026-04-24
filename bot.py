"""Main bot file - event handlers and startup."""
import time
import random
from datetime import datetime, timezone
import discord
from discord.ext import commands
import aiosqlite

from xp_bot.config import (
    TOKEN, DB_PATH, XP_MIN, XP_MAX, COOLDOWN_SECONDS,
    LIVE_ARCHIVE_ENABLED, ARCHIVE_COMMAND_MESSAGES, ARCHIVE_BOT_MESSAGES,
    DB_TIMEOUT, HATE_SPEECH_DETECTION_ENABLED, HATE_SPEECH_THRESHOLD
)
from xp_bot.database import init_db, get_xp, add_xp, update_last_message
from xp_bot.leveling import level_from_total_xp
from xp_bot.archiving import archive_path, msg_to_archive_dict, append_jsonl
from xp_bot.word_counter import word_counter_manager
from xp_bot import commands_user
from xp_bot import commands_admin
from xp_bot import commands_archive
from xp_bot import commands_counters
from xp_bot import commands_semantic
from xp_bot import commands_random_video
from xp_bot import commands_image
from xp_bot import commands_giveaway
from xp_bot import commands_voice
from xp_bot import commands_voting
from xp_bot.semantic import index_message, detect_hate_speech
from xp_bot.commands_random_video import video_config
from xp_bot import voice_tracking

# Bot setup
INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.members = True
INTENTS.messages = True
INTENTS.presences = True 

bot = commands.Bot(command_prefix="!", intents=INTENTS, help_command=None)  # Remove default help

# In-memory cooldown for live messages
cooldowns: dict[tuple[int, int], float] = {}

# Flag to track if commands are already setup
_commands_setup = False

# ----------------------------
# Event handlers
# ----------------------------
@bot.event
async def on_ready():
    """Initialize bot when ready."""
    global _commands_setup
    await init_db(DB_PATH)
    print(f"Logged in as {bot.user} (id={bot.user.id})")
    
    # Setup and sync commands once
    if not _commands_setup:
        print("[bot] Setting up commands...")
        await setup_commands()
        
        try:
            synced = await bot.tree.sync()
            print(f"[slash] Synced {len(synced)} slash command(s) globally")
        except Exception as e:
            print(f"[slash] Failed to sync commands: {e}")
        
        _commands_setup = True
        print("[bot] Bot is ready!")

@bot.event
async def on_message(message: discord.Message):
    """Handle new messages - archive and award XP."""
    # Only process guild messages
    if not message.guild:
        return

    # ---- Scammer/Spammer Detection (@everyone + images) ----
    if not message.author.bot and message.mention_everyone:
        # Check if message has any attachments that are images
        has_images = any(
            attachment.content_type and attachment.content_type.startswith('image/')
            for attachment in message.attachments
        )
        
        if has_images:
            try:
                # Store user info before banning
                username = str(message.author)
                user_id = message.author.id
                
                # Ban the user
                await message.guild.ban(
                    message.author,
                    reason="Automatic ban: @everyone mention with image attachments (likely scammer/spammer)",
                    delete_message_seconds=86400  # Delete messages from last 24 hours
                )
                
                # Announce in the channel
                await message.channel.send(
                    f"⚠️ **Security Alert**: User `{username}` (ID: {user_id}) has been automatically banned for posting @everyone with image attachments. This behavior is typically associated with scammers/spammers."
                )
                
                print(f"[security] Auto-banned user {username} ({user_id}) for @everyone + images")
                return  # Stop processing this message
                
            except discord.Forbidden:
                print(f"[security] Failed to ban {message.author} - insufficient permissions")
                await message.channel.send(
                    f"⚠️ **Security Warning**: User {message.author.mention} posted @everyone with images (potential scammer/spammer), but I lack permission to ban them."
                )
            except Exception as e:
                print(f"[security] Error during auto-ban: {e}")

    # ---- Vote reminders (check before processing other things) ----
    await commands_voting.check_and_send_reminder(message, bot)

    # ---- Word counters (check before processing commands) ----
    if not message.author.bot and message.content:
        triggered = word_counter_manager.check_message(message.guild.id, message.content)
        for counter_name, new_count in triggered:
            try:
                await message.channel.send(f"Total **{counter_name}** count: {new_count}")
            except Exception as e:
                print(f"[counter] Failed to send count message: {e}")

    # ---- Live archive (JSONL) ----
    if LIVE_ARCHIVE_ENABLED:
        if (not ARCHIVE_BOT_MESSAGES) and message.author.bot:
            pass
        else:
            # Optionally skip command messages like !rank, !leaderboard, etc.
            prefixes = await bot.get_prefix(message)
            if isinstance(prefixes, str):
                prefixes = [prefixes]
            is_command = any(message.content.startswith(p) for p in prefixes)

            if is_command and not ARCHIVE_COMMAND_MESSAGES:
                pass
            else:
                try:
                    append_jsonl(
                        archive_path(message.guild.id, message.channel.id),
                        msg_to_archive_dict(message)
                    )
                except Exception as e:
                    # Don't crash the bot if disk has issues; just log
                    print(f"[archive] Failed to write message {message.id}: {e}")

    # ---- Leveling (skip bots) ----
    if message.author.bot:
        await bot.process_commands(message)
        return

    # ---- Track last message timestamp ----
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        await update_last_message(
            db, 
            message.guild.id, 
            message.channel.id, 
            message.author.id,
            message.created_at.replace(tzinfo=timezone.utc).isoformat()
        )
        await db.commit()

    # ---- Semantic indexing (index message for semantic search) ----
    if message.content and message.content.strip():
        try:
            await index_message(
                message_id=str(message.id),
                content=message.content,
                user_id=message.author.id,
                username=message.author.display_name,
                channel_id=message.channel.id,
                channel_name=message.channel.name,
                guild_id=message.guild.id,
                timestamp=message.created_at.replace(tzinfo=timezone.utc).isoformat()
            )
        except Exception as e:
            # Don't crash if indexing fails
            print(f"[semantic] Failed to index message {message.id}: {e}")
        
        # ---- Hate speech detection ----
        if HATE_SPEECH_DETECTION_ENABLED:
            try:
                hate_result = await detect_hate_speech(message.content, threshold=HATE_SPEECH_THRESHOLD)
                if hate_result:
                    confidence, hate_type = hate_result
                    confidence_pct = int(confidence * 100)
                    
                    # Map hate types to display messages
                    type_messages = {
                        "sexism": "sexist",
                        "racism": "racist",
                        "disability": "ableist/discriminatory",
                        "sexual_orientation": "homophobic",
                        "religion": "religiously discriminatory",
                        "other": "hateful"
                    }
                    
                    display_msg = type_messages.get(hate_type, hate_type)
                    
                    # Send warning message
                    await message.channel.send(
                        f"⚠️ **Content Warning**: This message appears to be {display_msg} "
                        f"(confidence: {confidence_pct}%)"
                    )
                    
                    print(f"[hate-speech] Detected {hate_type} content in message {message.id} "
                          f"from {message.author} ({confidence_pct}%)")
            except Exception as e:
                # Don't crash if hate detection fails
                print(f"[hate-speech] Failed to analyze message {message.id}: {e}")
            # Don't crash if toxicity detection fails
            print(f"[toxicity] Failed to analyze message {message.id}: {e}")

    key = (message.guild.id, message.author.id)
    now = time.time()
    last = cooldowns.get(key, 0)

    if now - last < COOLDOWN_SECONDS:
        await bot.process_commands(message)
        return

    cooldowns[key] = now
    gain = random.randint(XP_MIN, XP_MAX)

    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        old_xp = await get_xp(db, message.guild.id, message.author.id)
        old_level = level_from_total_xp(old_xp)

        _, new_xp = await add_xp(db, message.guild.id, message.author.id, gain)
        new_level = level_from_total_xp(new_xp)

        await db.commit()

    if new_level > old_level:
        await message.channel.send(f"🎉 {message.author.mention} leveled up to **{new_level}**!")

    await bot.process_commands(message)

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    """Archive message edits."""
    if not after.guild or not LIVE_ARCHIVE_ENABLED:
        return
    if (not ARCHIVE_BOT_MESSAGES) and after.author.bot:
        return

    event = {
        "event": "edit",
        "id": after.id,
        "channel_id": after.channel.id,
        "guild_id": after.guild.id,
        "author_id": after.author.id,
        "created_at": after.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "edited_at": (after.edited_at.replace(tzinfo=timezone.utc).isoformat() if after.edited_at else None),
        "before_content": before.content,
        "after_content": after.content,
    }
    try:
        append_jsonl(archive_path(after.guild.id, after.channel.id), event)
    except Exception as e:
        print(f"[archive] Failed to write edit event {after.id}: {e}")

@bot.event
async def on_message_delete(message: discord.Message):
    """Archive message deletions."""
    if not message.guild or not LIVE_ARCHIVE_ENABLED:
        return
    # author can be None sometimes depending on cache; handle safely
    author_id = message.author.id if message.author else None

    event = {
        "event": "delete",
        "id": message.id,
        "channel_id": message.channel.id,
        "guild_id": message.guild.id,
        "author_id": author_id,
        "deleted_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        append_jsonl(archive_path(message.guild.id, message.channel.id), event)
    except Exception as e:
        print(f"[archive] Failed to write delete event {message.id}: {e}")

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    """Track voice channel joins, leaves, and moves."""
    guild_id = member.guild.id
    user_id = member.id
    
    # User left voice completely
    if before.channel is not None and after.channel is None:
        try:
            duration, old_level, new_level = await voice_tracking.user_left_voice(guild_id, user_id)
            print(f"[voice] {member.name} left {before.channel.name} (duration: {duration}s)")
            
            # Check for level up
            if new_level > old_level:
                # Try to send level up message in a text channel
                # Look for a general/chat channel, or use the first available text channel
                text_channel = None
                for channel in member.guild.text_channels:
                    if channel.name.lower() in ['general', 'chat', 'bot-commands', 'leveling']:
                        text_channel = channel
                        break
                
                if not text_channel and member.guild.text_channels:
                    text_channel = member.guild.text_channels[0]
                
                if text_channel:
                    try:
                        await text_channel.send(
                            f"{member.mention} leveled up to **{new_level}** from voice time!"
                        )
                    except Exception as e:
                        print(f"[voice] Failed to send level up message: {e}")
        except Exception as e:
            print(f"[voice] Error tracking leave: {e}")
    
    # User joined voice
    elif before.channel is None and after.channel is not None:
        try:
            await voice_tracking.user_joined_voice(guild_id, user_id, after.channel.id)
            print(f"[voice] {member.name} joined {after.channel.name}")
        except Exception as e:
            print(f"[voice] Error tracking join: {e}")
    
    # User moved between channels
    elif before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
        try:
            await voice_tracking.user_moved_voice(guild_id, user_id, before.channel.id, after.channel.id)
            print(f"[voice] {member.name} moved from {before.channel.name} to {after.channel.name}")
        except Exception as e:
            print(f"[voice] Error tracking move: {e}")


# ----------------------------
# Help Command (Programmatic)
# ----------------------------
# Command categories - just add your command name here to categorize it
COMMAND_CATEGORIES = {
    "rank": {"category": "🏆 XP & Ranking", "admin": False},
    "ranktext": {"category": "🏆 XP & Ranking", "admin": False},
    "leaderboard": {"category": "🏆 XP & Ranking", "admin": False},
    "leaderboardtext": {"category": "🏆 XP & Ranking", "admin": False},
    "deletes": {"category": "📜 Message Archive", "admin": False},
    "showdelete": {"category": "📜 Message Archive", "admin": False},
    "edits": {"category": "📜 Message Archive", "admin": False},
    "counters": {"category": "🔢 Word Counters", "admin": False},
    "counter_info": {"category": "🔢 Word Counters", "admin": False},
    "lastmsg": {"category": "📊 User Stats", "admin": False},
    "stats": {"category": "📊 User Stats", "admin": False},
    "statstext": {"category": "📊 User Stats", "admin": False},
    "channelstats": {"category": "📊 Channel Stats", "admin": False},
    "channelstatstext": {"category": "📊 Channel Stats", "admin": False},
    "channelinfo": {"category": "📊 Channel Stats", "admin": False},
    "wordstats": {"category": "📊 Channel Stats", "admin": False},
    "import_channel": {"category": "⚙️ Admin - Import", "admin": True},
    "import_server": {"category": "⚙️ Admin - Import", "admin": True},
    "import_status": {"category": "⚙️ Admin - Import", "admin": True},
    "import_progress": {"category": "⚙️ Admin - Import", "admin": True},
    "import_stop": {"category": "⚙️ Admin - Import", "admin": True},
    "import_lastmsg": {"category": "⚙️ Admin - Import", "admin": True},
    "counter_create": {"category": "⚙️ Admin - Counters", "admin": True},
    "counter_delete": {"category": "⚙️ Admin - Counters", "admin": True},
    "counter_rename": {"category": "⚙️ Admin - Counters", "admin": True},
    "counter_add_words": {"category": "⚙️ Admin - Counters", "admin": True},
    "counter_remove_words": {"category": "⚙️ Admin - Counters", "admin": True},
    "counter_set": {"category": "⚙️ Admin - Counters", "admin": True},
    "setxp": {"category": "⚙️ Admin - XP Management", "admin": True},
    "addxp": {"category": "⚙️ Admin - XP Management", "admin": True},
    "setlevel": {"category": "⚙️ Admin - XP Management", "admin": True},
    "mergeuser": {"category": "⚙️ Admin - XP Management", "admin": True},
    "unmergeuser": {"category": "⚙️ Admin - XP Management", "admin": True},
    "listmerged": {"category": "⚙️ Admin - XP Management", "admin": True},
    "clear": {"category": "⚙️ Admin - Moderation", "admin": True},
    "semantic_search": {"category": "🔍 Semantic Search", "admin": False},
    "user_sentiment": {"category": "🔍 Semantic Search", "admin": False},
    "user_trait": {"category": "🔍 Semantic Search", "admin": False},
    "index_stats": {"category": "🔍 Semantic Search", "admin": False},
    "index_messages": {"category": "⚙️ Admin - Semantic", "admin": True},
    "video_list": {"category": "🎬 Random Videos", "admin": False},
    "video_info": {"category": "🎬 Random Videos", "admin": False},
    "video_add": {"category": "⚙️ Admin - Video Commands", "admin": True},
    "video_remove": {"category": "⚙️ Admin - Video Commands", "admin": True},
    "pixel": {"category": "🖼️ Image Analysis", "admin": False},
    "voicestats": {"category": "Voice Statistics", "admin": False},
    "vcstats": {"category": "Voice Statistics", "admin": False},
    "voiceleaderboard": {"category": "Voice Statistics", "admin": False},
    "voiceleaderboardtext": {"category": "Voice Statistics", "admin": False},
    "whoisinvc": {"category": "Voice Statistics", "admin": False},
    "giveaway": {"category": "⚙️ Admin - Giveaways", "admin": True},
    "giveaway_end": {"category": "⚙️ Admin - Giveaways", "admin": True},
    "giveaway_list": {"category": "⚙️ Admin - Giveaways", "admin": True},
    "vote": {"category": "📊 Voting", "admin": False},
    "endvote": {"category": "📊 Voting", "admin": False},
}

def get_command_signature(cmd: commands.Command) -> str:
    """Generate a command signature from its parameters."""
    params = []
    for param_name, param in cmd.clean_params.items():
        if param.default is param.empty:
            # Required parameter
            params.append(f"<{param_name}>")
        else:
            # Optional parameter
            params.append(f"[{param_name}]")
    
    sig = f"!{cmd.name}"
    if params:
        sig += " " + " ".join(params)
    return sig

def get_short_help(cmd: commands.Command) -> str:
    """Get the first line of the command's docstring."""
    if not cmd.help:
        return "No description available"
    return cmd.help.split('\n')[0].strip()

@bot.command(name="help")
async def bot_help(ctx: commands.Context, *, command_name: str = None):
    """
    Show help information for all commands or a specific command.
    
    Usage:
      !help - Show all available commands
      !help admin - Show admin commands (requires admin permissions)
      !help <command> - Show detailed help for a specific command
    
    Examples:
      !help
      !help admin
      !help rank
      !help import_channel
    """
    is_admin_user = ctx.author.guild_permissions.administrator
    
    if command_name:
        command_name = command_name.lower().replace("!", "")
        
        # Special case: !help admin shows all admin commands
        if command_name == "admin":
            if not is_admin_user:
                await ctx.reply("🔒 You need administrator permissions to view admin commands.")
                return
            
            # Show all admin commands
            embed = discord.Embed(
                title="📚 Admin Commands",
                description="Here are all admin commands. Use `!help <command>` for detailed information.",
                color=discord.Color.gold()
            )
            
            # Group admin commands by category
            categories = {}
            for cmd in bot.commands:
                if cmd.name == "help":
                    continue
                
                cmd_meta = COMMAND_CATEGORIES.get(cmd.name, {"category": "Other", "admin": False})
                
                # Only show admin commands
                if not cmd_meta.get("admin", False):
                    continue
                
                category = cmd_meta.get("category", "Other")
                if category not in categories:
                    categories[category] = []
                
                sig = get_command_signature(cmd)
                short_help = get_short_help(cmd)
                categories[category].append(f"**{sig}** - {short_help}")
            
            # Add categories to embed
            category_order = [
                "⚙️ Admin - Import",
                "⚙️ Admin - Giveaways",
                "⚙️ Admin - XP Management",
                "⚙️ Admin - Counters",
                "⚙️ Admin - Video Commands",
                "⚙️ Admin - Semantic",
                "⚙️ Admin - Moderation",
                "Other"
            ]
            
            for category in category_order:
                if category in categories:
                    embed.add_field(
                        name=category,
                        value="\n".join(categories[category]),
                        inline=False
                    )
            # Add giveaway slash commands section
            giveaway_commands = [
                "**/giveaway create** - Create a new giveaway with a form",
                "**/giveaway end** `<message_id>` - End a giveaway early",
                "**/giveaway list** - List all active giveaways"
            ]
            embed.add_field(
                name="🎁 Giveaways (Slash Commands)",
                value="\n".join(giveaway_commands),
                inline=False
            )
            
            embed.set_footer(text="🔒 All commands require administrator permissions")
            await ctx.reply(embed=embed)
            return
        
        # Show detailed help for a specific command
        cmd = bot.get_command(command_name)
        
        if not cmd:
            await ctx.reply(f"Command `{command_name}` not found. Use `!help` to see all available commands.")
            return
        
        # Check if command is admin-only and user has permission
        cmd_meta = COMMAND_CATEGORIES.get(cmd.name, {})
        if cmd_meta.get("admin", False) and not is_admin_user:
            await ctx.reply(f"Command `{command_name}` not found. Use `!help` to see all available commands.")
            return
        
        # Build detailed help embed
        embed = discord.Embed(
            title=f"📖 Command: {get_command_signature(cmd)}",
            description=cmd.help or "No description available",
            color=discord.Color.gold() if cmd_meta.get("admin", False) else discord.Color.blue()
        )
        
        if cmd_meta.get("admin", False):
            embed.set_footer(text="🔒 Admin only command")
        
        await ctx.reply(embed=embed)
    else:
        # Show overview of NON-ADMIN commands only
        embed = discord.Embed(
            title="📚 Bot Commands Help",
            description="Here are all available commands. Use `!help <command>` for detailed information about a specific command.",
            color=discord.Color.blue()
        )
        
        # Group commands by category (exclude admin commands)
        categories = {}
        dynamic_videos = []  # Track dynamic video commands separately
        
        for cmd in bot.commands:
            if cmd.name == "help":
                continue  # Skip the help command itself in the list
            
            cmd_meta = COMMAND_CATEGORIES.get(cmd.name, {"category": "Other", "admin": False})
            
            # Skip admin commands - they're only shown with !help admin
            if cmd_meta.get("admin", False):
                continue
            
            # Check if this is a dynamic video command (not in COMMAND_CATEGORIES)
            if cmd.name not in COMMAND_CATEGORIES and hasattr(cmd.callback, '__name__') and cmd.callback.__name__ == 'dynamic_video_command':
                # Only show video commands that belong to the current guild
                command_guild = video_config.get_command_guild(cmd.name)
                if command_guild and command_guild == ctx.guild.id:
                    sig = get_command_signature(cmd)
                    short_help = get_short_help(cmd)
                    dynamic_videos.append(f"**{sig}** - {short_help}")
                continue
            
            category = cmd_meta.get("category", "Other")
            if category not in categories:
                categories[category] = []
            
            sig = get_command_signature(cmd)
            short_help = get_short_help(cmd)
            categories[category].append(f"**{sig}** - {short_help}")
        
        # Add dynamic video commands to the Random Videos category
        if dynamic_videos:
            if "🎬 Random Videos" not in categories:
                categories["🎬 Random Videos"] = []
            categories["🎬 Random Videos"].extend(dynamic_videos)
        
        # Add categories to embed in a specific order
        category_order = [
            "XP & Ranking",
            "User Stats",
            "Channel Stats",
            "Message Archive",
            "Word Counters",
            "Voting",
            "Semantic Search",
            "Random Videos",
            "Image Analysis",
            "Voice Statistics",
            "Other"
        ]
        
        for category in category_order:
            if category in categories:
                embed.add_field(
                    name=category,
                    value="\n".join(categories[category]),
                    inline=False
                )
        
        # Add giveaway slash commands section for admins
        if is_admin_user:
            giveaway_commands = [
                "**/giveaway create** - Create a new giveaway with a form",
                "**/giveaway end** `<message_id>` - End a giveaway early",
                "**/giveaway list** - List all active giveaways"
            ]
            embed.add_field(
                name="🎁 Giveaways (Slash Commands)",
                value="\n".join(giveaway_commands),
                inline=False
            )
        
        # Add footer with admin hint
        footer_text = "💡 Tip: Use !help <command> for more details"
        if is_admin_user:
            footer_text += " • Use !help admin for admin commands"
        embed.set_footer(text=footer_text)
        
        await ctx.reply(embed=embed)

# ----------------------------
# Setup commands
# ----------------------------
async def setup_commands():
    """Setup all bot commands."""
    commands_user.setup(bot)
    commands_admin.setup(bot)
    commands_archive.setup(bot)
    commands_counters.setup(bot)
    commands_semantic.setup(bot)
    commands_random_video.setup(bot)
    commands_image.setup(bot)
    commands_voice.setup(bot)
    commands_voting.setup(bot)
    await commands_giveaway.setup(bot)

# ----------------------------
# Start bot
# ----------------------------
async def main():
    """Main bot startup."""
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("Set DISCORD_TOKEN environment variable.")
    import asyncio
    asyncio.run(main())
