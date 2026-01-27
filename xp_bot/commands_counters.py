"""Admin commands for word counter management."""
from typing import Optional
import discord
from discord.ext import commands

from xp_bot.word_counter import word_counter_manager

def is_admin():
    """Check if user is an administrator."""
    async def predicate(ctx: commands.Context):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)

@commands.command()
@is_admin()
async def counter_create(ctx: commands.Context, counter_name: str, *words: str):
    """
    Create a new word counter.
    
    Usage:
      !counter_create mycount word1 word2 "phrase with spaces"
    
    The counter will track all specified words/phrases (case-insensitive).
    When detected, the bot will announce the new count.
    """
    if not words:
        await ctx.reply("Please provide at least one word to track.\nUsage: `!counter_create <name> <word1> [word2] ...`")
        return
    
    if len(counter_name) > 32:
        await ctx.reply("Counter name must be 32 characters or less.")
        return
    
    success = word_counter_manager.create_counter(ctx.guild.id, counter_name, list(words))
    
    if success:
        words_list = ", ".join(f"`{w}`" for w in words)
        await ctx.reply(
            f"✅ Created counter **{counter_name}**\n"
            f"Tracking: {words_list}\n"
            f"Current count: **0**"
        )
    else:
        await ctx.reply(f"❌ Counter **{counter_name}** already exists.")

@commands.command()
@is_admin()
async def counter_delete(ctx: commands.Context, counter_name: str):
    """
    Delete a word counter.
    
    Usage:
      !counter_delete mycount
    """
    success = word_counter_manager.delete_counter(ctx.guild.id, counter_name)
    
    if success:
        await ctx.reply(f"✅ Deleted counter **{counter_name}**")
    else:
        await ctx.reply(f"❌ Counter **{counter_name}** not found.")

@commands.command()
@is_admin()
async def counter_rename(ctx: commands.Context, old_name: str, new_name: str):
    """
    Rename a word counter.
    
    Usage:
      !counter_rename oldname newname
    
    The counter keeps its tracked words and count.
    """
    if len(new_name) > 32:
        await ctx.reply("❌ Counter name must be 32 characters or less.")
        return
    
    success = word_counter_manager.rename_counter(ctx.guild.id, old_name, new_name)
    
    if success:
        await ctx.reply(f"✅ Renamed counter **{old_name}** → **{new_name}**")
    else:
        # Check which error occurred
        guild_counters = word_counter_manager.get_guild_counters(ctx.guild.id)
        if old_name not in guild_counters:
            await ctx.reply(f"❌ Counter **{old_name}** not found.")
        elif new_name in guild_counters:
            await ctx.reply(f"❌ Counter **{new_name}** already exists.")
        else:
            await ctx.reply(f"❌ Failed to rename counter.")

@commands.command()
@is_admin()
async def counter_add_words(ctx: commands.Context, counter_name: str, *words: str):
    """
    Add words to an existing counter.
    
    Usage:
      !counter_add_words mycount newword1 newword2
    """
    if not words:
        await ctx.reply("Please provide at least one word to add.")
        return
    
    success = word_counter_manager.add_words(ctx.guild.id, counter_name, list(words))
    
    if success:
        words_list = ", ".join(f"`{w}`" for w in words)
        await ctx.reply(f"✅ Added to **{counter_name}**: {words_list}")
    else:
        await ctx.reply(f"❌ Counter **{counter_name}** not found.")

@commands.command()
@is_admin()
async def counter_remove_words(ctx: commands.Context, counter_name: str, *words: str):
    """
    Remove words from a counter.
    
    Usage:
      !counter_remove_words mycount word1 word2
    """
    if not words:
        await ctx.reply("Please provide at least one word to remove.")
        return
    
    success = word_counter_manager.remove_words(ctx.guild.id, counter_name, list(words))
    
    if success:
        words_list = ", ".join(f"`{w}`" for w in words)
        await ctx.reply(f"✅ Removed from **{counter_name}**: {words_list}")
    else:
        await ctx.reply(f"❌ Counter **{counter_name}** not found.")

@commands.command()
@is_admin()
async def counter_set(ctx: commands.Context, counter_name: str, count: int):
    """
    Set a counter to a specific value.
    
    Usage:
      !counter_set mycount 100
    """
    success = word_counter_manager.set_count(ctx.guild.id, counter_name, count)
    
    if success:
        await ctx.reply(f"✅ Set **{counter_name}** to **{count}**")
    else:
        await ctx.reply(f"❌ Counter **{counter_name}** not found.")

@commands.command()
async def counters(ctx: commands.Context):
    """
    List all word counters with their current counts and tracked words.
    
    Usage:
      !counters
    """
    guild_counters = word_counter_manager.get_guild_counters(ctx.guild.id)
    
    if not guild_counters:
        await ctx.reply("No word counters configured for this server.")
        return
    
    lines = ["**Word Counters:**\n"]
    
    for counter_name, data in sorted(guild_counters.items()):
        count = data["count"]
        words = data["words"]
        words_preview = ", ".join(f"`{w}`" for w in words[:3])
        if len(words) > 3:
            words_preview += f" *(+{len(words) - 3} more)*"
        
        lines.append(f"**{counter_name}**: {count}")
        lines.append(f"  └ Tracking: {words_preview}")
    
    await ctx.reply("\n".join(lines))

@commands.command()
async def counter_info(ctx: commands.Context, counter_name: str):
    """
    Show detailed info about a specific counter.
    
    Usage:
      !counter_info mycount
    """
    guild_counters = word_counter_manager.get_guild_counters(ctx.guild.id)
    
    if counter_name not in guild_counters:
        await ctx.reply(f"❌ Counter **{counter_name}** not found.")
        return
    
    data = guild_counters[counter_name]
    count = data["count"]
    words = data["words"]
    
    embed = discord.Embed(
        title=f"Counter: {counter_name}",
        color=discord.Color.blue()
    )
    
    embed.add_field(name="Count", value=f"**{count}**", inline=True)
    embed.add_field(name="Words Tracked", value=f"**{len(words)}**", inline=True)
    
    words_list = "\n".join(f"• `{w}`" for w in sorted(words))
    if len(words_list) > 1024:
        words_list = words_list[:1020] + "..."
    
    embed.add_field(name="Tracked Words/Phrases", value=words_list or "*None*", inline=False)
    
    await ctx.reply(embed=embed)

def setup(bot: commands.Bot):
    """Add word counter commands to the bot."""
    bot.add_command(counter_create)
    bot.add_command(counter_delete)
    bot.add_command(counter_rename)
    bot.add_command(counter_add_words)
    bot.add_command(counter_remove_words)
    bot.add_command(counter_set)
    bot.add_command(counters)
    bot.add_command(counter_info)
