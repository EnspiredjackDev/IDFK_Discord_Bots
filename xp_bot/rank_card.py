"""Rank card image generation."""
import io
from pathlib import Path
from typing import Optional
import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# Try to find system fonts or use default
def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Get a font with fallback options."""
    font_paths = [
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/TTF/DejaVuSans.ttf",
        # Windows
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        # Mac
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    
    for font_path in font_paths:
        try:
            return ImageFont.truetype(font_path, size)
        except:
            continue
    
    # Fallback to default
    return ImageFont.load_default()

async def download_avatar(url: str) -> Optional[Image.Image]:
    """Download and return avatar image."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception as e:
        print(f"Failed to download avatar: {e}")
    return None

def create_circle_mask(size: int) -> Image.Image:
    """Create a circular mask."""
    mask = Image.new('L', (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)
    return mask

def create_rank_card(
    username: str,
    discriminator: str,
    level: int,
    rank: int,
    current_xp: int,
    needed_xp: int,
    total_xp: int,
    avatar_image: Optional[Image.Image] = None,
    status_color: str = "gray"  # gray, green, yellow, red
) -> io.BytesIO:
    """
    Create a rank card image similar to MEE6.
    
    Args:
        username: User's display name
        discriminator: User discriminator (or display tag)
        level: Current level
        rank: Server rank position
        current_xp: XP progress into current level
        needed_xp: XP needed for next level
        total_xp: Total XP
        avatar_image: PIL Image of avatar (will be downloaded if None)
        status_color: Status indicator color
    
    Returns:
        BytesIO buffer containing PNG image
    """
    # Card dimensions (2x scale for higher quality)
    scale = 2
    width, height = 934 * scale, 250 * scale
    
    # Colors
    bg_color = (35, 39, 42)  # Dark gray background
    card_bg = (47, 49, 54)   # Slightly lighter card background
    text_color = (255, 255, 255)
    subtext_color = (185, 187, 190)
    progress_bg = (79, 84, 92)
    progress_fill = (114, 137, 218)  # Discord blurple
    rank_color = (255, 255, 255)
    level_color = (255, 107, 107)  # Red/pink
    
    status_colors = {
        "green": (67, 181, 129),    # Online
        "yellow": (250, 166, 26),   # Idle
        "red": (240, 71, 71),       # DND
        "gray": (116, 127, 141)     # Offline
    }
    
    # Create base image
    img = Image.new('RGB', (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    
    # Draw card background with rounded corners
    card_margin = 12 * scale
    card_rect = [card_margin, card_margin, width - card_margin, height - card_margin]
    
    # Simple rounded rectangle (draw multiple circles and rectangles)
    radius = 15 * scale
    draw.rectangle([card_rect[0] + radius, card_rect[1], card_rect[2] - radius, card_rect[3]], fill=card_bg)
    draw.rectangle([card_rect[0], card_rect[1] + radius, card_rect[2], card_rect[3] - radius], fill=card_bg)
    
    # Corners
    draw.ellipse([card_rect[0], card_rect[1], card_rect[0] + radius * 2, card_rect[1] + radius * 2], fill=card_bg)
    draw.ellipse([card_rect[2] - radius * 2, card_rect[1], card_rect[2], card_rect[1] + radius * 2], fill=card_bg)
    draw.ellipse([card_rect[0], card_rect[3] - radius * 2, card_rect[0] + radius * 2, card_rect[3]], fill=card_bg)
    draw.ellipse([card_rect[2] - radius * 2, card_rect[3] - radius * 2, card_rect[2], card_rect[3]], fill=card_bg)
    
    # Avatar
    avatar_size = 160 * scale
    avatar_x = 50 * scale
    avatar_y = (height - avatar_size) // 2
    
    if avatar_image:
        # Resize avatar
        avatar_image = avatar_image.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
        
        # Create circular mask
        mask = create_circle_mask(avatar_size)
        
        # Apply mask to avatar
        output = Image.new('RGBA', (avatar_size, avatar_size), (0, 0, 0, 0))
        output.paste(avatar_image, (0, 0))
        output.putalpha(mask)
        
        # Paste onto card
        img.paste(output, (avatar_x, avatar_y), output)
        
        # Status indicator
        status_size = 40 * scale
        status_x = avatar_x + avatar_size - status_size + 5 * scale
        status_y = avatar_y + avatar_size - status_size + 5 * scale
        
        # Draw status circle with border
        border_size = 6 * scale
        draw.ellipse(
            [status_x - border_size, status_y - border_size, 
             status_x + status_size + border_size, status_y + status_size + border_size],
            fill=card_bg
        )
        draw.ellipse(
            [status_x, status_y, status_x + status_size, status_y + status_size],
            fill=status_colors.get(status_color, status_colors["gray"])
        )
    else:
        # Draw placeholder circle
        draw.ellipse(
            [avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size],
            fill=progress_bg
        )
    
    # Fonts (scaled)
    font_large = get_font(50 * scale, bold=True)
    font_medium = get_font(36 * scale, bold=True)
    font_small = get_font(28 * scale)
    font_tiny = get_font(20 * scale)
    
    # Username
    username_x = avatar_x + avatar_size + 40 * scale
    username_y = 50 * scale
    draw.text((username_x, username_y), username, font=font_medium, fill=text_color)
    
    # Total XP under username
    total_text = f"{total_xp:,} XP"
    draw.text((username_x, username_y + 45 * scale), total_text, font=font_tiny, fill=subtext_color)
    
    # Rank (top right)
    rank_text = f"#{rank}"
    rank_label = "RANK"
    rank_x = width - 280 * scale
    rank_y = 40 * scale
    
    # Get text sizes for centering
    try:
        rank_label_bbox = draw.textbbox((0, 0), rank_label, font=font_tiny)
        rank_label_width = rank_label_bbox[2] - rank_label_bbox[0]
    except:
        rank_label_width = len(rank_label) * 12 * scale
    
    try:
        rank_bbox = draw.textbbox((0, 0), rank_text, font=font_large)
        rank_width = rank_bbox[2] - rank_bbox[0]
    except:
        rank_width = len(rank_text) * 30 * scale
    
    # Center label and number together
    rank_center = rank_x + 70 * scale
    draw.text((rank_center - rank_label_width // 2, rank_y), rank_label, font=font_tiny, fill=subtext_color)
    draw.text((rank_center - rank_width // 2, rank_y + 25 * scale), rank_text, font=font_large, fill=rank_color)
    
    # Level (top right, next to rank)
    level_text = str(level)
    level_label = "LEVEL"
    level_x = width - 140 * scale
    level_y = 40 * scale
    
    # Get text sizes for centering
    try:
        level_label_bbox = draw.textbbox((0, 0), level_label, font=font_tiny)
        level_label_width = level_label_bbox[2] - level_label_bbox[0]
    except:
        level_label_width = len(level_label) * 12 * scale
    
    try:
        level_bbox = draw.textbbox((0, 0), level_text, font=font_large)
        level_width = level_bbox[2] - level_bbox[0]
    except:
        level_width = len(level_text) * 30 * scale
    
    # Center label and number together
    level_center = level_x + 60 * scale
    draw.text((level_center - level_label_width // 2, level_y), level_label, font=font_tiny, fill=subtext_color)
    draw.text((level_center - level_width // 2, level_y + 25 * scale), level_text, font=font_large, fill=level_color)
    
    # Progress bar
    bar_x = username_x
    bar_y = height - 70 * scale
    bar_width = width - bar_x - 50 * scale
    bar_height = 35 * scale
    bar_radius = bar_height // 2
    
    # Background bar (rounded)
    draw.rounded_rectangle(
        [bar_x, bar_y, bar_x + bar_width, bar_y + bar_height],
        radius=bar_radius,
        fill=progress_bg
    )
    
    # Progress fill
    progress_ratio = current_xp / needed_xp if needed_xp > 0 else 0
    fill_width = int(bar_width * progress_ratio)
    
    if fill_width > bar_radius * 2:
        draw.rounded_rectangle(
            [bar_x, bar_y, bar_x + fill_width, bar_y + bar_height],
            radius=bar_radius,
            fill=progress_fill
        )
    
    # XP text on progress bar
    xp_text = f"{current_xp} / {needed_xp} XP"
    try:
        xp_bbox = draw.textbbox((0, 0), xp_text, font=font_small)
        xp_width = xp_bbox[2] - xp_bbox[0]
    except:
        xp_width = len(xp_text) * 15 * scale
    
    xp_x = bar_x + (bar_width - xp_width) // 2
    xp_y = bar_y + 3 * scale
    draw.text((xp_x, xp_y), xp_text, font=font_small, fill=text_color)
    
    # Convert to bytes
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    
    return buffer
