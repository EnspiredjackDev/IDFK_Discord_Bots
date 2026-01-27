"""Single channel statistics card image generation."""
import io
import math
from typing import Optional, List, Tuple, Dict
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import discord

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
        (67, 181, 129),   # Teal
        (250, 166, 26),   # Gold
        (240, 71, 71),    # Red
        (153, 170, 181),  # Light gray
        (116, 127, 141),  # Gray
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

async def create_single_channel_stats_card(
    channel_name: str,
    total_messages: int,
    unique_users: int,
    user_contributions: List[Tuple[int, int]],
    first_message: datetime,
    last_message: datetime,
    days_active: int,
    avg_messages_per_day: float,
    messages_by_year: Dict[int, int],
    edited_messages: int,
    bot: discord.Client,
    guild: discord.Guild
) -> io.BytesIO:
    """
    Create a single channel statistics card with user contribution pie chart.
    
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
    channel_display = f"#{channel_name}"
    draw.text((title_x, title_y), channel_display, font=font_title, fill=text_color)
    draw.text((title_x, title_y + 65 * scale), "Channel Statistics", font=font_normal, fill=subtext_color)
    
    # Stats section - Left column
    stats_y = title_y + 140 * scale
    left_col_x = title_x
    right_col_x = width // 2 - 50 * scale
    
    y_offset = stats_y
    line_height = 70 * scale
    
    # Total messages
    draw.text((left_col_x, y_offset), "Total Messages", font=font_small, fill=subtext_color)
    draw.text((left_col_x, y_offset + 28 * scale), f"{total_messages:,}", font=font_large, fill=accent_color)
    
    # Unique users
    draw.text((right_col_x, y_offset), "Unique Users", font=font_small, fill=subtext_color)
    draw.text((right_col_x, y_offset + 28 * scale), f"{unique_users}", font=font_large, fill=accent_color)
    
    y_offset += line_height + 10 * scale
    
    # First message
    first_msg_str = first_message.strftime('%B %d, %Y') if first_message else "Unknown"
    draw.text((left_col_x, y_offset), "First Message", font=font_small, fill=subtext_color)
    draw.text((left_col_x, y_offset + 28 * scale), first_msg_str, font=font_normal, fill=text_color)
    
    # Days active
    draw.text((right_col_x, y_offset), "Days Active", font=font_small, fill=subtext_color)
    draw.text((right_col_x, y_offset + 28 * scale), f"{days_active:,} days", font=font_normal, fill=text_color)
    
    y_offset += line_height
    
    # Avg messages per day
    draw.text((left_col_x, y_offset), "Avg Messages/Day", font=font_small, fill=subtext_color)
    draw.text((left_col_x, y_offset + 28 * scale), f"{avg_messages_per_day:.1f}", font=font_normal, fill=text_color)
    
    # Edited messages
    edit_pct = (edited_messages / total_messages * 100) if total_messages > 0 else 0
    draw.text((right_col_x, y_offset), "Edited Messages", font=font_small, fill=subtext_color)
    draw.text((right_col_x, y_offset + 28 * scale), f"{edited_messages:,} ({edit_pct:.1f}%)", font=font_normal, fill=text_color)
    
    # Pie chart section
    pie_y = y_offset + 100 * scale
    pie_center_x = 380 * scale
    pie_center_y = pie_y + 280 * scale
    pie_radius = 240 * scale
    
    # Draw pie chart title
    draw.text((left_col_x, pie_y), "Top Contributors", font=font_medium, fill=text_color)
    
    # Prepare data for pie chart (top 10 users + "Others")
    display_users = user_contributions[:10]
    user_colors = generate_colors(len(display_users) + 1)
    
    # Calculate "Others" if there are more than 10 users
    others_count = sum(count for _, count in user_contributions[10:]) if len(user_contributions) > 10 else 0
    if others_count > 0:
        display_users.append((None, others_count))  # None represents "Others"
    
    # Fetch user names
    user_names = {}
    for user_id, _ in display_users:
        if user_id is not None:
            try:
                member = guild.get_member(user_id)
                if member:
                    user_names[user_id] = member.display_name
                else:
                    # Try to fetch as user
                    try:
                        user = await bot.fetch_user(user_id)
                        user_names[user_id] = user.name
                    except:
                        user_names[user_id] = f"User {user_id}"
            except:
                user_names[user_id] = f"User {user_id}"
    
    # Draw pie chart
    start_angle = -90  # Start from top
    
    for i, (user_id, count) in enumerate(display_users):
        percentage = (count / total_messages) * 100
        slice_angle = (count / total_messages) * 360
        end_angle = start_angle + slice_angle
        
        # Draw pie slice
        draw.pieslice(
            [pie_center_x - pie_radius, pie_center_y - pie_radius,
             pie_center_x + pie_radius, pie_center_y + pie_radius],
            start=start_angle,
            end=end_angle,
            fill=user_colors[i],
            outline=card_bg,
            width=3 * scale
        )
        
        start_angle = end_angle
    
    # Legend (right side of pie chart)
    legend_x = pie_center_x + pie_radius + 60 * scale
    legend_y = pie_y + 50 * scale
    legend_item_height = 45 * scale
    
    for i, (user_id, count) in enumerate(display_users):
        percentage = (count / total_messages) * 100
        
        # Color box
        box_size = 20 * scale
        draw.rectangle(
            [legend_x, legend_y + i * legend_item_height,
             legend_x + box_size, legend_y + i * legend_item_height + box_size],
            fill=user_colors[i]
        )
        
        # User name and stats
        text_x = legend_x + box_size + 15 * scale
        user_display = user_names.get(user_id, "Others") if user_id is not None else "Others"
        if len(user_display) > 18:
            user_display = user_display[:18] + "..."
        
        draw.text((text_x, legend_y + i * legend_item_height - 2 * scale), user_display, font=font_small, fill=text_color)
        draw.text((text_x, legend_y + i * legend_item_height + 22 * scale), 
                  f"{count:,} ({percentage:.1f}%)", font=font_tiny, fill=subtext_color)
    
    # Activity by year at bottom (if multiple years)
    if len(messages_by_year) > 1:
        year_y = pie_y + 620 * scale
        draw.text((left_col_x, year_y), "Activity by Year", font=font_medium, fill=text_color)
        year_y += 40 * scale
        
        sorted_years = sorted(messages_by_year.keys())
        
        # Multi-column layout
        years_per_column = 4
        num_columns = (len(sorted_years) + years_per_column - 1) // years_per_column
        column_width = (width - 100 * scale) // num_columns
        
        for idx, year in enumerate(sorted_years):
            count = messages_by_year[year]
            
            col = idx // years_per_column
            row = idx % years_per_column
            
            year_x = left_col_x + col * column_width
            y = year_y + row * 35 * scale
            
            draw.text((year_x, y), f"{year}:", font=font_normal, fill=subtext_color)
            draw.text((year_x + 120 * scale, y), f"{count:,} messages", font=font_normal, fill=text_color)
    
    # Convert to bytes
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    
    return buffer
