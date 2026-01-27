"""Commands for random video posting from configured folders."""
import os
import random
import json
from pathlib import Path
from typing import Dict, Optional

import discord
from discord.ext import commands

# Path to store video command configuration
CONFIG_FILE = "video_commands.json"

# Supported video extensions
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v'}

class VideoCommandConfig:
    """Manages video command configuration."""
    
    def __init__(self, config_file: str = CONFIG_FILE):
        self.config_file = config_file
        self.commands: Dict[int, Dict[str, str]] = {}  # guild_id -> {command_name: folder_path}
        self.load()
    
    def load(self):
        """Load configuration from JSON file."""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    # Convert string keys back to integers for guild_ids
                    self.commands = {int(k): v for k, v in data.items()}
            except Exception as e:
                print(f"[video_commands] Error loading config: {e}")
                self.commands = {}
        else:
            self.commands = {}
    
    def save(self):
        """Save configuration to JSON file."""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.commands, f, indent=2)
        except Exception as e:
            print(f"[video_commands] Error saving config: {e}")
    
    def add_command(self, guild_id: int, command_name: str, folder_path: str):
        """Add a new video command."""
        if guild_id not in self.commands:
            self.commands[guild_id] = {}
        self.commands[guild_id][command_name] = folder_path
        self.save()
    
    def remove_command(self, guild_id: int, command_name: str) -> bool:
        """Remove a video command. Returns True if removed, False if not found."""
        if guild_id in self.commands and command_name in self.commands[guild_id]:
            del self.commands[guild_id][command_name]
            if not self.commands[guild_id]:  # Clean up empty guild entries
                del self.commands[guild_id]
            self.save()
            return True
        return False
    
    def get_folder(self, guild_id: int, command_name: str) -> Optional[str]:
        """Get the folder path for a command."""
        return self.commands.get(guild_id, {}).get(command_name)
    
    def list_commands(self, guild_id: int) -> Dict[str, str]:
        """List all commands for a guild."""
        return self.commands.get(guild_id, {}).copy()
    
    def get_command_guild(self, command_name: str) -> Optional[int]:
        """Get the guild_id that owns a command, or None if not found."""
        for guild_id, commands_dict in self.commands.items():
            if command_name in commands_dict:
                return guild_id
        return None

# Global config instance
video_config = VideoCommandConfig()

def get_random_video(folder_path: str) -> Optional[Path]:
    """Get a random video file from the specified folder."""
    try:
        folder = Path(folder_path)
        if not folder.exists() or not folder.is_dir():
            return None
        
        # Find all video files
        video_files = [
            f for f in folder.iterdir() 
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
        ]
        
        if not video_files:
            return None
        
        return random.choice(video_files)
    except Exception as e:
        print(f"[video_commands] Error finding video: {e}")
        return None

def create_video_command(bot: commands.Bot, command_name: str, guild_id: int):
    """Dynamically create a video command."""
    
    @commands.command(name=command_name)
    @commands.guild_only()
    async def dynamic_video_command(ctx: commands.Context):
        """Post a random video from the configured folder."""
        if ctx.guild.id != guild_id:
            return  # Only work in the guild this command was created for
        
        folder_path = video_config.get_folder(ctx.guild.id, command_name)
        if not folder_path:
            await ctx.reply(f"❌ Command `{command_name}` is not configured properly.")
            return
        
        video_file = get_random_video(folder_path)
        if not video_file:
            await ctx.reply(f"❌ No videos found in the configured folder for `{command_name}`.")
            return
        
        # Check file size (Discord limit is 25MB for most servers, 50MB for boosted)
        file_size_mb = video_file.stat().st_size / (1024 * 1024)
        if file_size_mb > 25:
            await ctx.reply(f"❌ Selected video `{video_file.name}` is too large ({file_size_mb:.1f}MB). Discord limit is 25MB.")
            return
        
        try:
            await ctx.reply(file=discord.File(video_file))
        except discord.HTTPException as e:
            await ctx.reply(f"❌ Failed to upload video: {e}")
    
    # Set the docstring for help
    dynamic_video_command.help = f"Post a random video from the configured folder."
    
    bot.add_command(dynamic_video_command)

def setup(bot: commands.Bot):
    """Set up video commands module."""
    
    # Load existing commands and register them
    for guild_id, commands_dict in video_config.commands.items():
        for command_name in commands_dict.keys():
            # Check if command already exists to avoid duplicates
            if not bot.get_command(command_name):
                create_video_command(bot, command_name, guild_id)
    
    @bot.command(name="video_add")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def video_add(ctx: commands.Context, command_name: str, *, folder_path: str):
        """
        Create a new random video command.
        
        Usage: !video_add <command_name> <folder_path>
        
        Examples:
          !video_add topgear /home/videos/topgear
          !video_add tonight /mnt/media/tonight_intros
        
        The command name should not include the ! prefix.
        The folder path must exist and contain video files.
        """
        # Validate command name
        if not command_name.isalnum() and '_' not in command_name:
            await ctx.reply("❌ Command name must be alphanumeric (underscores allowed).")
            return
        
        # Check if command already exists
        if bot.get_command(command_name):
            await ctx.reply(f"❌ Command `{command_name}` already exists!")
            return
        
        # Validate folder path
        folder = Path(folder_path)
        if not folder.exists():
            await ctx.reply(f"❌ Folder `{folder_path}` does not exist.")
            return
        
        if not folder.is_dir():
            await ctx.reply(f"❌ `{folder_path}` is not a directory.")
            return
        
        # Check for video files
        video_files = [
            f for f in folder.iterdir() 
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
        ]
        
        if not video_files:
            await ctx.reply(f"❌ No video files found in `{folder_path}`. Supported formats: {', '.join(VIDEO_EXTENSIONS)}")
            return
        
        # Add to config
        video_config.add_command(ctx.guild.id, command_name, str(folder_path))
        
        # Register the command
        create_video_command(bot, command_name, ctx.guild.id)
        
        await ctx.reply(
            f"✅ Created command `!{command_name}`!\n"
            f"📁 Folder: `{folder_path}`\n"
            f"🎬 Found {len(video_files)} video(s)"
        )
    
    @bot.command(name="video_remove")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def video_remove(ctx: commands.Context, command_name: str):
        """
        Remove a random video command.
        
        Usage: !video_remove <command_name>
        
        Example:
          !video_remove topgear
        """
        # Remove from config
        if not video_config.remove_command(ctx.guild.id, command_name):
            await ctx.reply(f"❌ Command `{command_name}` not found.")
            return
        
        # Remove from bot
        cmd = bot.get_command(command_name)
        if cmd:
            bot.remove_command(command_name)
        
        await ctx.reply(f"✅ Removed command `!{command_name}`")
    
    @bot.command(name="video_list")
    @commands.guild_only()
    async def video_list(ctx: commands.Context):
        """
        List all configured random video commands.
        
        Usage: !video_list
        """
        commands_dict = video_config.list_commands(ctx.guild.id)
        
        if not commands_dict:
            await ctx.reply("No random video commands configured. Use `!video_add` to create one!")
            return
        
        embed = discord.Embed(
            title="🎬 Random Video Commands",
            description="Here are all configured video commands:",
            color=discord.Color.purple()
        )
        
        for cmd_name, folder_path in commands_dict.items():
            # Count videos in folder
            try:
                folder = Path(folder_path)
                if folder.exists():
                    video_count = len([
                        f for f in folder.iterdir() 
                        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
                    ])
                    status = f"✅ {video_count} video(s)"
                else:
                    status = "❌ Folder not found"
            except:
                status = "❌ Error reading folder"
            
            embed.add_field(
                name=f"!{cmd_name}",
                value=f"📁 `{folder_path}`\n{status}",
                inline=False
            )
        
        await ctx.reply(embed=embed)
    
    @bot.command(name="video_info")
    @commands.guild_only()
    async def video_info(ctx: commands.Context, command_name: str):
        """
        Show detailed information about a video command.
        
        Usage: !video_info <command_name>
        
        Example:
          !video_info topgear
        """
        folder_path = video_config.get_folder(ctx.guild.id, command_name)
        
        if not folder_path:
            await ctx.reply(f"❌ Command `{command_name}` not found.")
            return
        
        folder = Path(folder_path)
        
        embed = discord.Embed(
            title=f"🎬 Command: !{command_name}",
            color=discord.Color.purple()
        )
        
        embed.add_field(name="📁 Folder", value=f"`{folder_path}`", inline=False)
        
        if not folder.exists():
            embed.add_field(name="Status", value="❌ Folder does not exist", inline=False)
            await ctx.reply(embed=embed)
            return
        
        try:
            video_files = [
                f for f in folder.iterdir() 
                if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
            ]
            
            embed.add_field(name="🎥 Video Count", value=str(len(video_files)), inline=True)
            
            if video_files:
                total_size = sum(f.stat().st_size for f in video_files)
                total_size_mb = total_size / (1024 * 1024)
                embed.add_field(name="💾 Total Size", value=f"{total_size_mb:.1f} MB", inline=True)
                
                # Show a sample of video names (up to 10)
                sample = video_files[:10]
                video_list = "\n".join(f"• {f.name}" for f in sample)
                if len(video_files) > 10:
                    video_list += f"\n... and {len(video_files) - 10} more"
                
                embed.add_field(name="📋 Videos", value=video_list, inline=False)
            
        except Exception as e:
            embed.add_field(name="Status", value=f"❌ Error: {e}", inline=False)
        
        await ctx.reply(embed=embed)
