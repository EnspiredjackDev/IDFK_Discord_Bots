"""Channel statistics card image generation."""
import io
import math
from typing import Optional, List, Tuple, Dict
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

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

def generate_colors(n: int) -> List[Tuple[int, int, int]]:
    """Generate n visually distinct colors."""
    colors = [
        (88, 101, 242),   # Discord blurple
        (87, 242, 135),   # Green
        (254, 231, 92),   # Yellow
        (235, 69, 158),   # Pink
        (255, 115, 77),   # Orange
        (116, 127, 141),  # Gray
        (153, 170, 181),  # Light gray
        (67, 181, 129),   # Teal
        (250, 166, 26),   # Gold
        (240, 71, 71),    # Red
    ]
    
    # If we need more colors, generate them using HSV
    if n > len(colors):
        for i in range(len(colors), n):
            hue = (i * 137.5) % 360  # Golden angle for distribution
            saturation = 0.7
            value = 0.9
            
            # Convert HSV to RGB
            h = hue / 60
            c = value * saturation
            x = c * (1 - abs(h % 2 - 1))
            m = value - c
            
            if 0 <= h < 1:
                r, g, b = c, x, 0
            elif 1 <= h < 2:
                r, g, b = x, c, 0
            elif 2 <= h < 3:
                r, g, b = 0, c, x
            elif 3 <= h < 4:
                r, g, b = 0, x, c
            elif 4 <= h < 5:
                r, g, b = x, 0, c
            else:
                r, g, b = c, 0, x
            
            colors.append((int((r + m) * 255), int((g + m) * 255), int((b + m) * 255)))
    
    return colors[:n]

def create_channel_stats_card(
    guild_name: str,
    total_messages: int,
    top_channels: List[Tuple[str, int]],
    channels_data: Dict[str, dict]
) -> io.BytesIO:
    """
    Create a channel statistics card with pie chart.
    
    Returns:
        BytesIO buffer containing PNG image
    """
    # Card dimensions (2x scale for higher quality)
    scale = 2
    width, height = 1400 * scale, 1300 * scale
    
    # Colors
    bg_color = (35, 39, 42)  # Dark gray background
    card_bg = (47, 49, 54)   # Slightly lighter card background
    text_color = (255, 255, 255)
    subtext_color = (185, 187, 190)
    accent_color = (114, 137, 218)  # Discord blurple
    
    # Create base image
    img = Image.new('RGB', (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    
    # Draw card background with rounded corners
    card_margin = 12 * scale
    card_rect = [card_margin, card_margin, width - card_margin, height - card_margin]
    
    radius = 15 * scale
    draw.rectangle([card_rect[0] + radius, card_rect[1], card_rect[2] - radius, card_rect[3]], fill=card_bg)
    draw.rectangle([card_rect[0], card_rect[1] + radius, card_rect[2], card_rect[3] - radius], fill=card_bg)
    
    # Corners
    draw.ellipse([card_rect[0], card_rect[1], card_rect[0] + radius * 2, card_rect[1] + radius * 2], fill=card_bg)
    draw.ellipse([card_rect[2] - radius * 2, card_rect[1], card_rect[2], card_rect[1] + radius * 2], fill=card_bg)
    draw.ellipse([card_rect[0], card_rect[3] - radius * 2, card_rect[0] + radius * 2, card_rect[3]], fill=card_bg)
    draw.ellipse([card_rect[2] - radius * 2, card_rect[3] - radius * 2, card_rect[2], card_rect[3]], fill=card_bg)
    
    # Fonts
    font_title = get_font(52 * scale, bold=True)
    font_large = get_font(42 * scale, bold=True)
    font_medium = get_font(32 * scale, bold=True)
    font_normal = get_font(28 * scale)
    font_small = get_font(24 * scale)
    font_tiny = get_font(20 * scale)
    
    # Title
    title_x = 50 * scale
    title_y = 40 * scale
    draw.text((title_x, title_y), guild_name, font=font_title, fill=text_color)
    draw.text((title_x, title_y + 65 * scale), "Channel Activity Statistics", font=font_normal, fill=subtext_color)
    
    # Total stats
    stats_y = title_y + 130 * scale
    draw.text((title_x, stats_y), "Total Messages", font=font_small, fill=subtext_color)
    draw.text((title_x, stats_y + 30 * scale), f"{total_messages:,}", font=font_large, fill=accent_color)
    
    draw.text((title_x + 350 * scale, stats_y), "Total Channels", font=font_small, fill=subtext_color)
    draw.text((title_x + 350 * scale, stats_y + 30 * scale), f"{len(channels_data)}", font=font_large, fill=accent_color)
    
    # Pie chart section
    pie_y = stats_y + 120 * scale
    pie_center_x = 400 * scale
    pie_center_y = pie_y + 280 * scale
    pie_radius = 240 * scale
    
    # Draw pie chart title
    draw.text((title_x, pie_y), "Message Distribution", font=font_medium, fill=text_color)
    
    # Prepare data for pie chart (top 10 channels + "Others")
    display_channels = top_channels[:10]
    channel_colors = generate_colors(len(display_channels) + 1)
    
    # Calculate "Others" if there are more than 10 channels
    others_count = sum(count for _, count in top_channels[10:]) if len(top_channels) > 10 else 0
    if others_count > 0:
        display_channels.append(("Others", others_count))
    
    # Draw pie chart
    start_angle = -90  # Start from top
    
    for i, (channel, count) in enumerate(display_channels):
        percentage = (count / total_messages) * 100
        slice_angle = (count / total_messages) * 360
        end_angle = start_angle + slice_angle
        
        # Draw pie slice
        draw.pieslice(
            [pie_center_x - pie_radius, pie_center_y - pie_radius,
             pie_center_x + pie_radius, pie_center_y + pie_radius],
            start=start_angle,
            end=end_angle,
            fill=channel_colors[i],
            outline=card_bg,
            width=3 * scale
        )
        
        start_angle = end_angle
    
    # Legend (right side of pie chart)
    legend_x = pie_center_x + pie_radius + 60 * scale
    legend_y = pie_y + 50 * scale
    legend_item_height = 45 * scale
    
    for i, (channel, count) in enumerate(display_channels):
        percentage = (count / total_messages) * 100
        
        # Color box
        box_size = 20 * scale
        draw.rectangle(
            [legend_x, legend_y + i * legend_item_height,
             legend_x + box_size, legend_y + i * legend_item_height + box_size],
            fill=channel_colors[i]
        )
        
        # Channel name and stats
        text_x = legend_x + box_size + 15 * scale
        channel_display = f"#{channel}" if channel != "Others" else channel
        if len(channel_display) > 20:
            channel_display = channel_display[:20] + "..."
        
        draw.text((text_x, legend_y + i * legend_item_height - 2 * scale), channel_display, font=font_small, fill=text_color)
        draw.text((text_x, legend_y + i * legend_item_height + 22 * scale), 
                  f"{count:,} ({percentage:.1f}%)", font=font_tiny, fill=subtext_color)
    
    # Detailed channel list at bottom
    list_y = pie_y + 600 * scale
    draw.text((title_x, list_y), "Top Channels by Activity", font=font_medium, fill=text_color)
    list_y += 45 * scale
    
    # Two columns for channel details
    col1_x = title_x
    col2_x = width // 2 + 20 * scale
    
    for i, (channel, count) in enumerate(top_channels[:10], 1):
        channel_data = channels_data[channel]
        percentage = (count / total_messages) * 100
        
        # Determine column
        if i <= 5:
            x = col1_x
            y = list_y + (i - 1) * 65 * scale
        else:
            x = col2_x
            y = list_y + (i - 6) * 65 * scale
        
        # Channel name with rank
        channel_display = f"{i}. #{channel[:18]}"
        draw.text((x, y), channel_display, font=font_normal, fill=text_color)
        
        # Stats line
        stats_text = f"{count:,} msgs ({percentage:.1f}%) • {channel_data['unique_users']} users"
        draw.text((x, y + 30 * scale), stats_text, font=font_tiny, fill=subtext_color)
    
    # Convert to bytes
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    
    return buffer
