"""Giveaway commands - create and manage giveaways."""
import asyncio
from datetime import datetime, timezone, timedelta
import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiosqlite
from typing import Optional

from xp_bot.config import DB_PATH, DB_TIMEOUT


class GiveawayButton(discord.ui.View):
    """Button view for entering giveaways."""
    
    def __init__(self, giveaway_id: int):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
    
    @discord.ui.button(label="🎉 Enter Giveaway", style=discord.ButtonStyle.primary, custom_id="giveaway_enter")
    async def enter_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle giveaway entry."""
        async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
            # Check if giveaway exists and is active
            async with db.execute(
                "SELECT ended, title, description, end_time FROM giveaways WHERE id = ?",
                (self.giveaway_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    await interaction.response.send_message("❌ This giveaway no longer exists.", ephemeral=True)
                    return
                ended, title, description, end_time = row
                if ended == 1:
                    await interaction.response.send_message("❌ This giveaway has already ended.", ephemeral=True)
                    return
            
            # Check if user already entered
            async with db.execute(
                "SELECT 1 FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
                (self.giveaway_id, interaction.user.id)
            ) as cursor:
                already_entered = await cursor.fetchone()
            
            if already_entered:
                await interaction.response.send_message("❌ You've already entered this giveaway!", ephemeral=True)
                return
            
            # Add entry
            await db.execute(
                "INSERT INTO giveaway_entries (giveaway_id, user_id) VALUES (?, ?)",
                (self.giveaway_id, interaction.user.id)
            )
            await db.commit()
            
            # Get entry count
            async with db.execute(
                "SELECT COUNT(*) FROM giveaway_entries WHERE giveaway_id = ?",
                (self.giveaway_id,)
            ) as cursor:
                count = (await cursor.fetchone())[0]
        
        # Update the message embed with new entry count
        try:
            end_dt = datetime.fromisoformat(end_time)
            updated_embed = format_giveaway_embed(title, description, end_dt, count)
            await interaction.message.edit(embed=updated_embed)
        except Exception:
            pass  # If we can't update, that's okay
        
        await interaction.response.send_message(f"✅ You've entered the giveaway! (Total entries: {count})", ephemeral=True)


async def parse_duration(duration_str: str) -> Optional[timedelta]:
    """
    Parse a duration string like '1h', '30m', '2d', '1d 12h' into a timedelta.
    
    Supported units: s (seconds), m (minutes), h (hours), d (days), w (weeks)
    """
    duration_str = duration_str.lower().strip()
    parts = duration_str.split()
    
    total_seconds = 0
    
    try:
        for part in parts:
            # Extract number and unit
            num_str = ""
            unit = ""
            for char in part:
                if char.isdigit() or char == '.':
                    num_str += char
                else:
                    unit += char
            
            if not num_str:
                return None
            
            value = float(num_str)
            
            if unit == 's':
                total_seconds += value
            elif unit == 'm':
                total_seconds += value * 60
            elif unit == 'h':
                total_seconds += value * 3600
            elif unit == 'd':
                total_seconds += value * 86400
            elif unit == 'w':
                total_seconds += value * 604800
            else:
                return None
        
        if total_seconds <= 0:
            return None
        
        return timedelta(seconds=total_seconds)
    
    except (ValueError, AttributeError):
        return None


def format_giveaway_embed(title: str, description: str, end_time: datetime, entries_count: int = 0) -> discord.Embed:
    """Create a formatted embed for a giveaway."""
    embed = discord.Embed(
        title=f"🎉 {title}",
        description=description,
        color=discord.Color.gold(),
        timestamp=end_time
    )
    embed.add_field(name="Ends", value=f"<t:{int(end_time.timestamp())}:R>", inline=True)
    embed.add_field(name="Entries", value=str(entries_count), inline=True)
    embed.set_footer(text="Ends at")
    return embed


@tasks.loop(seconds=30)
async def check_giveaways(bot: commands.Bot):
    """Background task to check for ended giveaways."""
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        now = datetime.now(timezone.utc)
        
        # Find all active giveaways that have ended
        async with db.execute(
            "SELECT id, guild_id, channel_id, message_id, title, num_winners FROM giveaways WHERE ended = 0 AND end_time <= ?",
            (now.isoformat(),)
        ) as cursor:
            ended_giveaways = await cursor.fetchall()
        
        for giveaway_id, guild_id, channel_id, message_id, title, num_winners in ended_giveaways:
            try:
                # Get all entries
                async with db.execute(
                    "SELECT user_id FROM giveaway_entries WHERE giveaway_id = ? ORDER BY RANDOM()",
                    (giveaway_id,)
                ) as cursor:
                    entries = await cursor.fetchall()
                
                # Get the channel and message
                guild = bot.get_guild(guild_id)
                if not guild:
                    continue
                
                channel = guild.get_channel(channel_id)
                if not channel:
                    continue
                
                try:
                    message = await channel.fetch_message(message_id)
                except discord.NotFound:
                    # Message was deleted
                    await db.execute("UPDATE giveaways SET ended = 1 WHERE id = ?", (giveaway_id,))
                    await db.commit()
                    continue
                
                # Pick winners
                if entries:
                    # Get valid winners up to num_winners
                    winners = []
                    for entry in entries:
                        member = guild.get_member(entry[0])
                        if member:
                            winners.append(member)
                            if len(winners) >= num_winners:
                                break
                    
                    if winners:
                        # Update the embed
                        embed = message.embeds[0] if message.embeds else discord.Embed(title=title)
                        embed.color = discord.Color.green()
                        embed.clear_fields()
                        
                        winner_text = "\n".join([f"🏆 {winner.mention}" for winner in winners])
                        embed.add_field(
                            name=f"Winner{'s' if len(winners) > 1 else ''}", 
                            value=winner_text, 
                            inline=False
                        )
                        embed.add_field(name="Entries", value=str(len(entries)), inline=True)
                        embed.set_footer(text="Giveaway Ended")
                        
                        # Remove the button
                        await message.edit(embed=embed, view=None)
                        
                        # Announce winners
                        if len(winners) == 1:
                            await channel.send(f"🎊 Congratulations {winners[0].mention}! You won **{title}**!")
                        else:
                            winner_mentions = ", ".join([w.mention for w in winners])
                            await channel.send(f"🎊 Congratulations {winner_mentions}! You won **{title}**!")
                        
                        # Store first winner in database (legacy support)
                        await db.execute(
                            "UPDATE giveaways SET ended = 1, winner_id = ? WHERE id = ?",
                            (winners[0].id, giveaway_id)
                        )
                    else:
                        # No valid winners
                        embed = message.embeds[0] if message.embeds else discord.Embed(title=title)
                        embed.color = discord.Color.red()
                        embed.clear_fields()
                        embed.add_field(name="Winners", value="No valid winners (all participants left)", inline=False)
                        embed.set_footer(text="Giveaway Ended")
                        
                        await message.edit(embed=embed, view=None)
                        await channel.send(f"❌ Giveaway **{title}** ended with no valid winners.")
                        
                        await db.execute("UPDATE giveaways SET ended = 1 WHERE id = ?", (giveaway_id,))
                else:
                    # No entries
                    embed = message.embeds[0] if message.embeds else discord.Embed(title=title)
                    embed.color = discord.Color.red()
                    embed.clear_fields()
                    embed.add_field(name="Winner", value="No entries", inline=False)
                    embed.set_footer(text="Giveaway Ended")
                    
                    await message.edit(embed=embed, view=None)
                    await channel.send(f"❌ Giveaway **{title}** ended with no entries.")
                    
                    await db.execute("UPDATE giveaways SET ended = 1 WHERE id = ?", (giveaway_id,))
                
                await db.commit()
            
            except Exception as e:
                print(f"[giveaway] Error ending giveaway {giveaway_id}: {e}")


@check_giveaways.before_loop
async def before_check_giveaways():
    """Wait for the bot to be ready before starting the giveaway checker."""
    await check_giveaways.bot.wait_until_ready()


class GiveawayModal(discord.ui.Modal, title="Create Giveaway"):
    """Modal for giveaway creation."""
    
    giveaway_title = discord.ui.TextInput(
        label="Title",
        placeholder="Discord Nitro",
        max_length=256,
        required=True
    )
    
    duration = discord.ui.TextInput(
        label="Duration",
        placeholder="1d 12h (or 30m, 2d, 1w, etc.)",
        max_length=50,
        required=True
    )
    
    num_winners = discord.ui.TextInput(
        label="Number of Winners",
        placeholder="1",
        max_length=3,
        required=False,
        default="1"
    )
    
    channel_id = discord.ui.TextInput(
        label="Channel ID",
        placeholder="Right-click channel > Copy ID",
        max_length=20,
        required=True
    )
    
    description = discord.ui.TextInput(
        label="Description",
        placeholder="Win 1 month of Discord Nitro!",
        style=discord.TextStyle.paragraph,
        max_length=2048,
        required=True
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle form submission."""
        # Parse duration
        duration = await parse_duration(self.duration.value)
        if not duration:
            await interaction.response.send_message(
                "❌ Invalid duration format. Use formats like: `30m`, `1h`, `2d`, `1d 12h`\n"
                "Supported units: s=seconds, m=minutes, h=hours, d=days, w=weeks",
                ephemeral=True
            )
            return
        
        # Parse number of winners
        try:
            num_winners = int(self.num_winners.value) if self.num_winners.value.strip() else 1
            if num_winners < 1 or num_winners > 100:
                await interaction.response.send_message(
                    "❌ Number of winners must be between 1 and 100.",
                    ephemeral=True
                )
                return
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid number of winners. Must be a number.",
                ephemeral=True
            )
            return
        
        # Get channel
        try:
            channel_id = int(self.channel_id.value)
            target_channel = interaction.guild.get_channel(channel_id)
            if not target_channel:
                await interaction.response.send_message("❌ Channel not found.", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("❌ Invalid channel ID.", ephemeral=True)
            return
        
        # Check permissions
        if not target_channel.permissions_for(interaction.guild.me).send_messages:
            await interaction.response.send_message(
                f"❌ I don't have permission to send messages in {target_channel.mention}.",
                ephemeral=True
            )
            return
        
        if not target_channel.permissions_for(interaction.guild.me).embed_links:
            await interaction.response.send_message(
                f"❌ I don't have permission to embed links in {target_channel.mention}.",
                ephemeral=True
            )
            return
        
        # Calculate end time
        end_time = datetime.now(timezone.utc) + duration
        
        # Create embed
        embed = format_giveaway_embed(self.giveaway_title.value, self.description.value, end_time, 0)
        
        # Create button view
        view = GiveawayButton(0)  # Temporary ID
        
        # Post giveaway
        await interaction.response.defer(ephemeral=True)
        giveaway_msg = await target_channel.send(embed=embed, view=view)
        
        # Store in database
        async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
            await db.execute(
                """
                INSERT INTO giveaways (guild_id, channel_id, message_id, title, description, end_time, ended, num_winners)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (interaction.guild.id, target_channel.id, giveaway_msg.id, self.giveaway_title.value, 
                 self.description.value, end_time.isoformat(), num_winners)
            )
            await db.commit()
            
            # Get the giveaway ID
            async with db.execute("SELECT last_insert_rowid()") as cursor:
                giveaway_id = (await cursor.fetchone())[0]
        
        # Update the view with the correct ID and re-edit
        view = GiveawayButton(giveaway_id)
        await giveaway_msg.edit(view=view)
        
        await interaction.followup.send(f"✅ Giveaway created in {target_channel.mention}!", ephemeral=True)


class GiveawayCog(commands.Cog):
    """Giveaway commands using slash commands."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    giveaway_group = app_commands.Group(name="giveaway", description="Manage giveaways")
    
    @giveaway_group.command(name="create", description="Create a new giveaway")
    @app_commands.default_permissions(administrator=True)
    async def create_giveaway(self, interaction: discord.Interaction):
        """Create a new giveaway with a form."""
        await interaction.response.send_modal(GiveawayModal())
    
    @giveaway_group.command(name="end", description="End a giveaway early")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(message_id="The message ID of the giveaway")
    async def end_giveaway(self, interaction: discord.Interaction, message_id: str):
        """Manually end a giveaway early."""
        try:
            msg_id = int(message_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid message ID.", ephemeral=True)
            return
        
        async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
            # Check if giveaway exists
            async with db.execute(
                "SELECT id, channel_id, ended FROM giveaways WHERE message_id = ? AND guild_id = ?",
                (msg_id, interaction.guild.id)
            ) as cursor:
                row = await cursor.fetchone()
            
            if not row:
                await interaction.response.send_message("❌ Giveaway not found.", ephemeral=True)
                return
            
            giveaway_id, channel_id, ended = row
            
            if ended:
                await interaction.response.send_message("❌ This giveaway has already ended.", ephemeral=True)
                return
            
            # Update end time to now
            now = datetime.now(timezone.utc)
            await db.execute(
                "UPDATE giveaways SET end_time = ? WHERE id = ?",
                (now.isoformat(), giveaway_id)
            )
            await db.commit()
        
        await interaction.response.send_message("✅ Giveaway will end shortly.", ephemeral=True)
    
    @giveaway_group.command(name="list", description="List all active giveaways")
    @app_commands.default_permissions(administrator=True)
    async def list_giveaways(self, interaction: discord.Interaction):
        """List all active giveaways in the server."""
        async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
            async with db.execute(
                """
                SELECT title, channel_id, message_id, end_time 
                FROM giveaways 
                WHERE guild_id = ? AND ended = 0
                ORDER BY end_time ASC
                """,
                (interaction.guild.id,)
            ) as cursor:
                giveaways = await cursor.fetchall()
        
        if not giveaways:
            await interaction.response.send_message("No active giveaways.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="📋 Active Giveaways",
            color=discord.Color.gold()
        )
        
        for title, channel_id, message_id, end_time in giveaways:
            channel = interaction.guild.get_channel(channel_id)
            channel_mention = channel.mention if channel else f"<#{channel_id}>"
            end_dt = datetime.fromisoformat(end_time)
            
            embed.add_field(
                name=title,
                value=f"Channel: {channel_mention}\nEnds: <t:{int(end_dt.timestamp())}:R>\nMessage ID: `{message_id}`",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    """Register giveaway commands."""
    # Add the cog
    await bot.add_cog(GiveawayCog(bot))
    
    # Store bot reference and start the background task immediately
    check_giveaways.bot = bot
    if not check_giveaways.is_running():
        check_giveaways.start(bot)
        print("[giveaway] Background task started")
    
    print("[giveaway] Slash commands registered")
