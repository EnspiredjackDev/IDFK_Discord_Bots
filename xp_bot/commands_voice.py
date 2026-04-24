"""Commands for voice channel statistics."""
import discord
from discord.ext import commands
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import aiosqlite

from xp_bot.voice_tracking import (
    get_user_voice_stats, 
    get_channel_stats, 
    format_duration,
    active_sessions
)
from xp_bot.voice_leaderboard_card import create_voice_leaderboard_card
from xp_bot.rank_card import download_avatar
from xp_bot.config import DB_PATH, DB_TIMEOUT


def setup(bot: commands.Bot):
    """Register voice statistics commands."""
    
    @bot.command(name="voicestats")
    async def voice_stats(ctx: commands.Context, member: discord.Member = None):
        """
        Show voice channel statistics for a user.
        
        Usage:
          !voicestats - Show your own voice stats
          !voicestats @user - Show voice stats for another user
        
        Examples:
          !voicestats
          !voicestats @JohnDoe
        """
        member = member or ctx.author
        guild_id = ctx.guild.id
        user_id = member.id
        
        # Get statistics
        stats = await get_user_voice_stats(guild_id, user_id)
        
        # Calculate potential XP earned from voice time
        from xp_bot.config import VOICE_XP_ENABLED, VOICE_XP_PER_MINUTE
        voice_xp_estimate = 0
        if VOICE_XP_ENABLED and stats["total_time"] > 0:
            voice_xp_estimate = int((stats["total_time"] / 60) * VOICE_XP_PER_MINUTE)
        
        # Create embed
        embed = discord.Embed(
            title=f"Voice Statistics for {member.display_name}",
            color=discord.Color.blue()
        )
        
        # Add basic stats
        embed.add_field(
            name="Total Time in Voice",
            value=format_duration(stats["total_time"]),
            inline=True
        )
        embed.add_field(
            name="Total Sessions",
            value=str(stats["sessions_count"]),
            inline=True
        )
        
        # Show estimated voice XP if enabled
        if VOICE_XP_ENABLED:
            embed.add_field(
                name="Est. Voice XP Earned",
                value=f"~{voice_xp_estimate:,} XP",
                inline=True
            )
        
        # Check if currently in voice
        is_in_voice = (guild_id, user_id) in active_sessions
        if is_in_voice:
            current_session = active_sessions[(guild_id, user_id)]
            channel = ctx.guild.get_channel(current_session["channel_id"])
            if channel:
                embed.add_field(
                    name="Currently In",
                    value=channel.name,
                    inline=True
                )
        
        # Favorite channel
        fav_channel_id, fav_time = stats["favorite_channel"]
        if fav_channel_id:
            channel = ctx.guild.get_channel(fav_channel_id)
            channel_name = channel.name if channel else f"Unknown Channel ({fav_channel_id})"
            embed.add_field(
                name="Favorite Channel",
                value=f"{channel_name}\n{format_duration(fav_time)}",
                inline=False
            )
        
        # Top companions
        if stats["top_companions"]:
            companions_text = []
            for i, (companion_id, time_spent) in enumerate(stats["top_companions"][:5], 1):
                companion = ctx.guild.get_member(companion_id)
                companion_name = companion.display_name if companion else f"Unknown User ({companion_id})"
                companions_text.append(f"{i}. {companion_name} - {format_duration(time_spent)}")
            
            embed.add_field(
                name="Top Voice Companions",
                value="\n".join(companions_text),
                inline=False
            )
        else:
            embed.add_field(
                name="Top Voice Companions",
                value="No data yet",
                inline=False
            )
        
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.reply(embed=embed)
    
    @bot.command(name="vcstats")
    async def vc_channel_stats(ctx: commands.Context, channel: discord.VoiceChannel = None):
        """
        Show statistics for a voice channel.
        
        Usage:
          !vcstats - Show stats for your current voice channel
          !vcstats <channel> - Show stats for a specific channel
        
        Examples:
          !vcstats
          !vcstats #General Voice
        """
        # If no channel specified, try to get the user's current voice channel
        if channel is None:
            if ctx.author.voice and ctx.author.voice.channel:
                channel = ctx.author.voice.channel
            else:
                await ctx.reply("You must specify a voice channel or be in one!")
                return
        
        guild_id = ctx.guild.id
        channel_id = channel.id
        
        # Get statistics
        stats = await get_channel_stats(guild_id, channel_id)
        
        # Create embed
        embed = discord.Embed(
            title=f"Voice Channel Statistics",
            description=f"**{channel.name}**",
            color=discord.Color.green()
        )
        
        # Add basic stats
        embed.add_field(
            name="Total Time Spent",
            value=format_duration(stats["total_time"]),
            inline=True
        )
        embed.add_field(
            name="Unique Users",
            value=str(stats["unique_users"]),
            inline=True
        )
        
        # Current occupants
        current_members = [m.display_name for m in channel.members]
        if current_members:
            embed.add_field(
                name=f"Current Members ({len(current_members)})",
                value=", ".join(current_members[:10]),
                inline=False
            )
        
        # Top users
        if stats["top_users"]:
            users_text = []
            for i, (user_id, time_spent) in enumerate(stats["top_users"][:10], 1):
                member = ctx.guild.get_member(user_id)
                member_name = member.display_name if member else f"Unknown User ({user_id})"
                users_text.append(f"{i}. {member_name} - {format_duration(time_spent)}")
            
            embed.add_field(
                name="Top Users",
                value="\n".join(users_text),
                inline=False
            )
        else:
            embed.add_field(
                name="Top Users",
                value="No data yet",
                inline=False
            )
        
        await ctx.reply(embed=embed)
    
    @bot.command(name="voiceleaderboard")
    async def voice_leaderboard(ctx: commands.Context, limit: int = 10):
        """
        Show the voice time leaderboard for the server.
        
        Usage:
          !voiceleaderboard [limit] - Show top users by voice time (default 10)
        
        Examples:
          !voiceleaderboard
          !voiceleaderboard 20
        """
        guild_id = ctx.guild.id
        limit = max(1, min(limit, 25))  # Clamp between 1 and 25
        
        # Send processing message
        processing_msg = await ctx.reply("Generating voice leaderboard...")
        
        # Query database for top users
        async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
            async with db.execute("""
                SELECT user_id, SUM(duration_seconds) as total_time
                FROM voice_sessions
                WHERE guild_id = ? AND duration_seconds IS NOT NULL
                GROUP BY user_id
                ORDER BY total_time DESC
                LIMIT ?
            """, (guild_id, limit)) as cur:
                rows = await cur.fetchall()
        
        if not rows:
            await processing_msg.edit(content="No voice data yet! Join a voice channel to start tracking.")
            return
        
        # Gather member data and avatars
        entries = []
        for rank, (user_id, total_time) in enumerate(rows, 1):
            member = ctx.guild.get_member(user_id)
            if member:
                username = member.display_name
                avatar_url = member.display_avatar.url
            else:
                try:
                    user = await ctx.bot.fetch_user(user_id)
                    username = user.name
                    avatar_url = user.display_avatar.url
                except:
                    username = f"User {user_id}"
                    avatar_url = None
            
            avatar_image = await download_avatar(avatar_url) if avatar_url else None
            entries.append((rank, username, int(total_time), avatar_image))
        
        # Generate leaderboard card
        try:
            card_buffer = create_voice_leaderboard_card(entries, ctx.guild.name)
            file = discord.File(fp=card_buffer, filename="voice_leaderboard.png")
            await processing_msg.delete()
            await ctx.reply(file=file)
        except Exception as e:
            print(f"[voice_leaderboard] Failed to generate card: {e}")
            import traceback
            traceback.print_exc()
            
            # Fallback to text
            embed = discord.Embed(
                title="Voice Time Leaderboard",
                description=f"Top {limit} users by total voice time",
                color=discord.Color.gold()
            )
            
            leaderboard_text = []
            for rank, username, total_time, _ in entries:
                medal = ""
                if rank == 1:
                    medal = "#1 "
                elif rank == 2:
                    medal = "#2 "
                elif rank == 3:
                    medal = "#3 "
                
                leaderboard_text.append(
                    f"{medal}**{rank}.** {username} - {format_duration(total_time)}"
                )
            
            embed.description += "\n\n" + "\n".join(leaderboard_text)
            await processing_msg.edit(content=None, embed=embed)
    
    @bot.command(name="voiceleaderboardtext")
    async def voice_leaderboard_text(ctx: commands.Context, limit: int = 10):
        """
        Show the voice time leaderboard in text format.
        
        Usage:
          !voiceleaderboardtext [limit] - Show top users by voice time (default 10)
        
        Examples:
          !voiceleaderboardtext
          !voiceleaderboardtext 20
        """
        guild_id = ctx.guild.id
        limit = max(1, min(limit, 50))  # Clamp between 1 and 50
        
        # Query database for top users
        async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
            async with db.execute("""
                SELECT user_id, SUM(duration_seconds) as total_time
                FROM voice_sessions
                WHERE guild_id = ? AND duration_seconds IS NOT NULL
                GROUP BY user_id
                ORDER BY total_time DESC
                LIMIT ?
            """, (guild_id, limit)) as cur:
                rows = await cur.fetchall()
        
        if not rows:
            await ctx.reply("No voice data yet! Join a voice channel to start tracking.")
            return
        
        # Create embed
        embed = discord.Embed(
            title="Voice Time Leaderboard",
            description=f"Top {limit} users by total voice time",
            color=discord.Color.gold()
        )
        
        leaderboard_text = []
        for i, (user_id, total_time) in enumerate(rows, 1):
            member = ctx.guild.get_member(user_id)
            member_name = member.display_name if member else f"Unknown User ({user_id})"
            
            # Add marker for top 3
            medal = ""
            if i == 1:
                medal = "#1 "
            elif i == 2:
                medal = "#2 "
            elif i == 3:
                medal = "#3 "
            
            leaderboard_text.append(
                f"{medal}**{i}.** {member_name} - {format_duration(total_time)}"
            )
        
        embed.description += "\n\n" + "\n".join(leaderboard_text)
        await ctx.reply(embed=embed)
    
    @bot.command(name="whoisinvc")
    async def who_is_in_vc(ctx: commands.Context):
        """
        Show who is currently in voice channels in the server.
        
        Usage:
          !whoisinvc - Show all users currently in voice channels
        
        Example:
          !whoisinvc
        """
        guild = ctx.guild
        
        # Get all voice channels with members
        voice_channels = []
        for channel in guild.voice_channels:
            if channel.members:
                voice_channels.append((channel, channel.members))
        
        if not voice_channels:
            await ctx.reply("No one is currently in any voice channels!")
            return
        
        # Create embed
        embed = discord.Embed(
            title="Current Voice Activity",
            description=f"Users in voice channels across {guild.name}",
            color=discord.Color.purple()
        )
        
        total_users = 0
        for channel, members in voice_channels:
            member_names = [m.display_name for m in members]
            total_users += len(members)
            
            embed.add_field(
                name=f"{channel.name} ({len(members)})",
                value=", ".join(member_names),
                inline=False
            )
        
        embed.set_footer(text=f"Total: {total_users} user(s) in {len(voice_channels)} channel(s)")
        await ctx.reply(embed=embed)
