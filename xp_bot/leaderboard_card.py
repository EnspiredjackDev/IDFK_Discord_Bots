"""Leaderboard image generation."""
import io
import math
from typing import List, Tuple, Optional
import aiohttp
from PIL import Image, ImageDraw, ImageFont

from xp_bot.rank_card import get_font, download_avatar, create_circle_mask

async def download_avatars_batch(avatar_urls: List[str]) -> List[Optional[Image.Image]]:
    """Download multiple avatars in parallel."""
    avatars = []
    for url in avatar_urls:
        avatar = await download_avatar(url)
        avatars.append(avatar)
    return avatars

def draw_progress_circle(draw: ImageDraw.Draw, center_x: int, center_y: int, radius: int, 
                        progress: float, bg_color: tuple, fill_color: tuple, width: int):
    """Draw a filled circular progress indicator."""
    # Draw background filled circle
    draw.ellipse(
        [center_x - radius, center_y - radius, center_x + radius, center_y + radius],
        fill=bg_color
    )
    
    # Draw progress as a filled pie slice (starts at top, goes clockwise)
    if progress > 0:
        # Calculate angle (0 = top, goes clockwise)
        end_angle = -90 + (360 * progress)
        draw.pieslice(
            [center_x - radius, center_y - radius, center_x + radius, center_y + radius],
            start=-90, end=end_angle, fill=fill_color
        )

def create_leaderboard_card(
    entries: List[Tuple[int, str, str, int, int, Optional[Image.Image], float]],
    guild_name: str = "Server"
) -> io.BytesIO:
    """
    Create a leaderboard image.
    
    Args:
        entries: List of (rank, username, discriminator, level, xp, avatar_image, progress_ratio)
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
    font_tiny = get_font(18 * scale)
    
    # Header
    header_y = card_margin + 20 * scale
    title_text = f"{guild_name} Leaderboard"
    draw.text((width // 2 - 200 * scale, header_y), title_text, font=font_title, fill=text_color)
    
    # Draw entries
    entry_y = header_y + header_height
    
    for rank, username, discriminator, level, xp, avatar_image, progress in entries:
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
        
        # Truncate long usernames
        if len(username) > 20:
            username = username[:17] + "..."
        
        draw.text((username_x, username_y), username, font=font_medium, fill=text_color)
        
        # XP
        xp_text = f"{xp:,} XP"
        draw.text((username_x, username_y + 35 * scale), xp_text, font=font_tiny, fill=subtext_color)
        
        # Progress circle near level (draw first so level text is on top)
        progress_circle_size = 50 * scale
        progress_circle_x = entry_rect[2] - 70 * scale
        progress_circle_y = entry_rect[1] + (entry_height - 10 * scale - progress_circle_size) // 2
        progress_radius = progress_circle_size // 2
        progress_center_x = progress_circle_x + progress_radius
        progress_center_y = progress_circle_y + progress_radius
        
        # Draw progress circle with more visible colors
        draw_progress_circle(
            draw, progress_center_x, progress_center_y, progress_radius,
            progress, (60, 63, 70), (88, 101, 242), 6 * scale  # Brighter blurple
        )
        
        # Draw percentage in center
        # percent_text = f"{int(progress * 100)}%"
        # try:
        #     percent_bbox = draw.textbbox((0, 0), percent_text, font=font_tiny)
        #     percent_width = percent_bbox[2] - percent_bbox[0]
        #     percent_height = percent_bbox[3] - percent_bbox[1]
        # Draw progress circle with more visible colors
        draw_progress_circle(
            draw, progress_center_x, progress_center_y, progress_radius,
            progress, (60, 63, 70), (88, 101, 242), 6 * scale  # Brighter blurple
        )
        
        # Level (right side) - drawn after circle so it appears on top
        level_text = f"Level {level}"
        try:
            level_bbox = draw.textbbox((0, 0), level_text, font=font_medium)
            level_width = level_bbox[2] - level_bbox[0]
        except:
            level_width = len(level_text) * 20 * scale
        
        level_x = entry_rect[2] - level_width - 95 * scale
        level_y = entry_rect[1] + (entry_height - 10 * scale) // 2 - 12 * scale
        draw.text((level_x, level_y), level_text, font=font_medium, fill=(255, 107, 107))
        
        entry_y += entry_height
    
    # Convert to bytes
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    
    return buffer
