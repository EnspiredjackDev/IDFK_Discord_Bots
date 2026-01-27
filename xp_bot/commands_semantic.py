"""Commands for semantic search and sentiment analysis."""
import discord
from discord.ext import commands
from typing import Optional

from xp_bot.semantic import (
    semantic_search,
    get_user_sentiment_scores,
    index_archives,
    get_collection_stats,
    init_semantic
)
from xp_bot.database import get_main_user_id
import aiosqlite
from xp_bot.config import DB_PATH, DB_TIMEOUT


@commands.command(name="semantic_search", aliases=["semsearch", "search"])
async def semantic_search_cmd(ctx: commands.Context, *, query: str):
    """
    Search messages by meaning/sentiment, not just keywords.
    
    Usage:
        !semantic_search <query>
        !search who talked about being sad
        !search enterprising business ideas
    
    This uses AI embeddings to find messages that match the meaning of your query,
    even if they don't use the exact same words.
    """
    await ctx.typing()
    
    try:
        results = await semantic_search(
            query=query,
            guild_id=ctx.guild.id,
            n_results=10
        )
        
        if not results:
            await ctx.reply("No matching messages found.")
            return
        
        # Format results
        embed = discord.Embed(
            title=f"🔍 Semantic Search Results",
            description=f"Query: *{query}*",
            color=discord.Color.blue()
        )
        
        for i, result in enumerate(results[:5], 1):
            timestamp = result.get("timestamp", "Unknown time")
            similarity = (1.0 - result["distance"]) * 100 if result.get("distance") else 0
            
            # Check if this is a grouped message
            msg_count = result.get("message_count", 1)
            is_grouped = result.get("is_grouped", False)
            group_note = f" ({msg_count} messages)" if is_grouped and msg_count > 1 else ""
            
            field_value = (
                f"**{result['username']}** in #{result['channel_name']}{group_note}\n"
                f"*{timestamp}*\n"
                f"```{result['content'][:200]}```\n"
                f"Similarity: {similarity:.1f}%"
            )
            
            embed.add_field(
                name=f"Result {i}",
                value=field_value,
                inline=False
            )
        
        if len(results) > 5:
            embed.set_footer(text=f"Showing 5 of {len(results)} results")
        
        await ctx.reply(embed=embed)
    
    except Exception as e:
        await ctx.reply(f"Error during search: {e}")


@commands.command(name="user_sentiment", aliases=["usersentiment", "sentiment", "trait"])
async def user_sentiment_cmd(ctx: commands.Context, *, trait: str):
    """
    Find users who exhibit a certain trait or sentiment the most.
    
    Usage:
        !user_sentiment <trait description>
        !sentiment who is the most racist
        !trait most enterprising and business-minded
        !sentiment funniest and makes jokes
    
    This analyzes all messages and ranks users by how much their messages
    match the described trait using AI semantic analysis.
    """
    await ctx.typing()
    
    try:
        rankings = await get_user_sentiment_scores(
            guild_id=ctx.guild.id,
            trait_query=trait,
            top_n=10
        )
        
        if not rankings:
            await ctx.reply("No results found. Make sure messages are indexed first.")
            return
        
        # Resolve user aliases
        async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
            resolved_rankings = []
            for user_id, username, count, score in rankings:
                main_id = await get_main_user_id(db, ctx.guild.id, user_id)
                # Try to get member for current name
                member = ctx.guild.get_member(main_id)
                display_name = member.display_name if member else username
                resolved_rankings.append((main_id, display_name, count, score))
        
        # Format results
        embed = discord.Embed(
            title=f"📊 User Sentiment Analysis",
            description=f"Trait: *{trait}*",
            color=discord.Color.gold()
        )
        
        leaderboard = []
        for i, (user_id, display_name, count, score) in enumerate(resolved_rankings, 1):
            medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
            leaderboard.append(
                f"{medal} **{display_name}** - {score*100:.1f}% match ({count} messages)"
            )
        
        embed.add_field(
            name="Top Users",
            value="\n".join(leaderboard),
            inline=False
        )
        
        embed.set_footer(text="Based on semantic similarity of messages to the trait")
        
        await ctx.reply(embed=embed)
    
    except Exception as e:
        await ctx.reply(f"Error analyzing sentiment: {e}")


@commands.command(name="user_trait", aliases=["usertrait"])
async def user_trait_cmd(ctx: commands.Context, user: discord.Member, *, trait: str):
    """
    Analyze a specific user's messages for a trait.
    
    Usage:
        !user_trait @user <trait>
        !usertrait @john how racist they are
        !user_trait @jane business-minded and enterprising
    
    Shows messages from the user that best match the trait.
    """
    await ctx.typing()
    
    try:
        # Resolve to main account
        async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
            main_id = await get_main_user_id(db, ctx.guild.id, user.id)
        
        results = await semantic_search(
            query=trait,
            guild_id=ctx.guild.id,
            user_id=main_id,
            n_results=5
        )
        
        if not results:
            await ctx.reply(f"No matching messages found for {user.display_name}.")
            return
        
        # Format results
        embed = discord.Embed(
            title=f"🔍 Trait Analysis: {user.display_name}",
            description=f"Trait: *{trait}*",
            color=discord.Color.purple()
        )
        
        for i, result in enumerate(results, 1):
            timestamp = result.get("timestamp", "Unknown time")
            similarity = (1.0 - result["distance"]) * 100 if result.get("distance") else 0
            
            field_value = (
                f"In #{result['channel_name']} • *{timestamp}*\n"
                f"```{result['content'][:200]}```\n"
                f"Match: {similarity:.1f}%"
            )
            
            embed.add_field(
                name=f"Example {i}",
                value=field_value,
                inline=False
            )
        
        await ctx.reply(embed=embed)
    
    except Exception as e:
        await ctx.reply(f"Error analyzing user trait: {e}")


@commands.command(name="index_messages", aliases=["indexmsgs"])
@commands.has_permissions(administrator=True)
async def index_messages_cmd(ctx: commands.Context):
    """
    [ADMIN] Index all archived messages for semantic search.
    
    Usage:
        !index_messages
    
    This processes all archived messages and creates embeddings for semantic search.
    This may take a while for large archives. Only needs to be run once.
    New messages are indexed automatically.
    """
    await ctx.reply("🔄 Starting message indexing... This may take a while.")
    
    # Initialize model first
    try:
        init_semantic()
    except Exception as e:
        await ctx.reply(f"❌ Error initializing: {e}")
        return
    
    # Progress callback
    last_update = [0]  # Use list to allow modification in nested function
    async def progress(msg: str):
        # Only send updates every 1000 messages to avoid spam
        if "complete" in msg.lower() or last_update[0] % 1000 == 0:
            try:
                await ctx.send(f"📊 {msg}")
            except:
                pass
        last_update[0] += 1
    
    try:
        total = await index_archives(ctx.guild.id, progress_callback=progress)
        stats = get_collection_stats(ctx.guild.id)
        
        embed = discord.Embed(
            title="✅ Indexing Complete",
            description=f"Indexed {total} new messages",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Total Indexed",
            value=f"{stats['total_messages']} messages",
            inline=False
        )
        embed.set_footer(text="Semantic search is now available!")
        
        await ctx.reply(embed=embed)
    
    except Exception as e:
        await ctx.reply(f"❌ Error during indexing: {e}")


@commands.command(name="index_stats", aliases=["indexstats"])
async def index_stats_cmd(ctx: commands.Context):
    """
    Show statistics about indexed messages.
    
    Usage:
        !index_stats
    
    Shows how many messages are indexed for semantic search.
    """
    try:
        stats = get_collection_stats(ctx.guild.id)
        
        embed = discord.Embed(
            title="📊 Semantic Search Statistics",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Indexed Messages",
            value=f"{stats['total_messages']:,}",
            inline=False
        )
        embed.set_footer(text="Use !index_messages to index more")
        
        await ctx.reply(embed=embed)
    
    except Exception as e:
        await ctx.reply(f"Error getting stats: {e}")


def setup(bot: commands.Bot):
    """Register semantic search commands."""
    bot.add_command(semantic_search_cmd)
    bot.add_command(user_sentiment_cmd)
    bot.add_command(user_trait_cmd)
    bot.add_command(index_messages_cmd)
    bot.add_command(index_stats_cmd)
