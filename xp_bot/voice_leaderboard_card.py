"""Voice leaderboard image generation."""
import io
from typing import List, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont

from xp_bot.rank_card import get_font, download_avatar, create_circle_mask

def format_duration_short(seconds: int) -> str:
    """Format duration in a compact way for display."""
    if seconds < 60:
        return f"{seconds}s"
    
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    
    hours = minutes // 60
    minutes = minutes % 60
    
    if hours < 24:
        return f"{hours}h {minutes}m"
    
    days = hours // 24
    hours = hours % 24
    
    return f"{days}d {hours}h"

async def download_avatars_batch(avatar_urls: List[str]) -> List[Optional[Image.Image]]:
    """Download multiple avatars in parallel."""
    avatars = []
    for url in avatar_urls:
        avatar = await download_avatar(url)
        avatars.append(avatar)
    return avatars

def create_voice_leaderboard_card(
    entries: List[Tuple[int, str, int, Optional[Image.Image]]],
    guild_name: str = "Server"
) -> io.BytesIO:
    """
    Create a voice time leaderboard image.
    
    Args:
        entries: List of (rank, username, total_seconds, avatar_image)
        guild_name: Name of the guild/server
    
    Returns:
        BytesIO buffer containing PNG image
    """
    # Card dimensions (2x scale for higher quality)
    scale = 2
    width = 934 * scale
    entry_height = 90 * scale
    header_height = 80 * scale
    padding = 20 * scale
    height = header_height + (len(entries) * entry_height) + padding * 2
    
    # Colors
    bg_color = (35, 39, 42)
    card_bg = (47, 49, 54)
    entry_bg = (54, 57, 63)
    text_color = (255, 255, 255)
    subtext_color = (185, 187, 190)
    gold_color = (255, 215, 0)
    silver_color = (192, 192, 192)
    bronze_color = (205, 127, 50)
    voice_accent = (88, 101, 242)  # Purple for voice
    
    # Create base image
    img = Image.new('RGB', (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    
    # Draw card background
    card_margin = 12 * scale
    radius = 15 * scale
    card_rect = [card_margin, card_margin, width - card_margin, height - card_margin]
    
    # Background with rounded corners
    draw.rectangle([card_rect[0] + radius, card_rect[1], card_rect[2] - radius, card_rect[3]], fill=card_bg)
    draw.rectangle([card_rect[0], card_rect[1] + radius, card_rect[2], card_rect[3] - radius], fill=card_bg)
    draw.ellipse([card_rect[0], card_rect[1], card_rect[0] + radius * 2, card_rect[1] + radius * 2], fill=card_bg)
    draw.ellipse([card_rect[2] - radius * 2, card_rect[1], card_rect[2], card_rect[1] + radius * 2], fill=card_bg)
    draw.ellipse([card_rect[0], card_rect[3] - radius * 2, card_rect[0] + radius * 2, card_rect[3]], fill=card_bg)
    draw.ellipse([card_rect[2] - radius * 2, card_rect[3] - radius * 2, card_rect[2], card_rect[3]], fill=card_bg)
    
    # Fonts (scaled)
    font_title = get_font(40 * scale, bold=True)
    font_large = get_font(32 * scale, bold=True)
    font_medium = get_font(28 * scale, bold=True)
    font_small = get_font(22 * scale)
    
    # Header
    header_y = card_margin + 20 * scale
    title_text = f"{guild_name} Voice Leaderboard"
    draw.text((width // 2 - 250 * scale, header_y), title_text, font=font_title, fill=text_color)
    
    # Draw entries
    entry_y = header_y + header_height
    
    for rank, username, total_seconds, avatar_image in entries:
        # Entry background
        entry_rect = [
            card_margin + 15 * scale,
            entry_y,
            width - card_margin - 15 * scale,
            entry_y + entry_height - 10 * scale
        ]
        
        # Slight rounded rectangle for entry
        entry_radius = 10 * scale
        draw.rectangle([entry_rect[0] + entry_radius, entry_rect[1], entry_rect[2] - entry_radius, entry_rect[3]], fill=entry_bg)
        draw.rectangle([entry_rect[0], entry_rect[1] + entry_radius, entry_rect[2], entry_rect[3] - entry_radius], fill=entry_bg)
        draw.ellipse([entry_rect[0], entry_rect[1], entry_rect[0] + entry_radius * 2, entry_rect[1] + entry_radius * 2], fill=entry_bg)
        draw.ellipse([entry_rect[2] - entry_radius * 2, entry_rect[1], entry_rect[2], entry_rect[1] + entry_radius * 2], fill=entry_bg)
        draw.ellipse([entry_rect[0], entry_rect[3] - entry_radius * 2, entry_rect[0] + entry_radius * 2, entry_rect[3]], fill=entry_bg)
        draw.ellipse([entry_rect[2] - entry_radius * 2, entry_rect[3] - entry_radius * 2, entry_rect[2], entry_rect[3]], fill=entry_bg)
        
        # Rank number with medal colors
        rank_x = entry_rect[0] + 20 * scale
        rank_y = entry_rect[1] + (entry_height - 10 * scale) // 2 - 15 * scale
        
        rank_color = text_color
        if rank == 1:
            rank_color = gold_color
        elif rank == 2:
            rank_color = silver_color
        elif rank == 3:
            rank_color = bronze_color
        
        rank_text = f"#{rank}"
        draw.text((rank_x, rank_y), rank_text, font=font_large, fill=rank_color)
        
        # Avatar
        avatar_size = 60 * scale
        avatar_x = rank_x + 80 * scale
        avatar_y = entry_rect[1] + (entry_height - 10 * scale - avatar_size) // 2
        
        if avatar_image:
            avatar_image = avatar_image.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
            mask = create_circle_mask(avatar_size)
            output = Image.new('RGBA', (avatar_size, avatar_size), (0, 0, 0, 0))
            output.paste(avatar_image, (0, 0))
            output.putalpha(mask)
            img.paste(output, (avatar_x, avatar_y), output)
        else:
            draw.ellipse([avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size], fill=(79, 84, 92))
        
        # Username
        username_x = avatar_x + avatar_size + 20 * scale
        username_y = entry_rect[1] + 15 * scale
        draw.text((username_x, username_y), username, font=font_medium, fill=text_color)
        
        # Voice time
        time_str = format_duration_short(total_seconds)
        time_y = username_y + 35 * scale
        draw.text((username_x, time_y), f"Time: {time_str}", font=font_small, fill=voice_accent)
        
        # Calculate percentage of #1's time
        if rank > 1 and len(entries) > 0:
            top_time = entries[0][2]  # First entry's time
            if top_time > 0:
                percent = (total_seconds / top_time) * 100
                percent_text = f"{percent:.0f}% of #1"
                # Position on the right side
                percent_x = entry_rect[2] - 150 * scale
                draw.text((percent_x, time_y), percent_text, font=font_small, fill=subtext_color)
        
        entry_y += entry_height
    
    # Convert to BytesIO
    buffer = io.BytesIO()
    # Resize down to original dimensions for final output (anti-aliasing)
    img = img.resize((width // scale, height // scale), Image.Resampling.LANCZOS)
    img.save(buffer, format='PNG', optimize=True)
    buffer.seek(0)
    
    return buffer
