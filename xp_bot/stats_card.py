"""Stats card image generation."""
import io
from typing import Optional, Dict
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import aiohttp

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

def create_stats_card(
    username: str,
    avatar_image: Optional[Image.Image],
    first_message_date: datetime,
    total_messages: int,
    edited_messages: int,
    days_active: int,
    avg_messages_per_day: float,
    most_active_hour: int,
    most_active_day: int,
    most_active_month: int,
    top_channels: list,
    yearly_distribution: Dict[int, int],
    hourly_distribution: Dict[int, int],
    daily_distribution: Dict[int, int],
) -> io.BytesIO:
    """
    Create a statistics card image.
    
    Returns:
        BytesIO buffer containing PNG image
    """
    # Card dimensions (2x scale for higher quality)
    scale = 2
    width, height = 1200 * scale, 1500 * scale
    
    # Colors
    bg_color = (35, 39, 42)  # Dark gray background
    card_bg = (47, 49, 54)   # Slightly lighter card background
    text_color = (255, 255, 255)
    subtext_color = (185, 187, 190)
    accent_color = (114, 137, 218)  # Discord blurple
    chart_bg = (79, 84, 92)
    chart_fill = (88, 101, 242)  # Slightly different blue for charts
    
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    month_names = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    
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
    font_title = get_font(48 * scale, bold=True)
    font_large = get_font(42 * scale, bold=True)
    font_medium = get_font(32 * scale, bold=True)
    font_normal = get_font(28 * scale)
    font_small = get_font(24 * scale)
    font_tiny = get_font(20 * scale)
    
    # Avatar (top left)
    avatar_size = 120 * scale
    avatar_x = 50 * scale
    avatar_y = 50 * scale
    
    if avatar_image:
        avatar_image = avatar_image.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
        mask = create_circle_mask(avatar_size)
        output = Image.new('RGBA', (avatar_size, avatar_size), (0, 0, 0, 0))
        output.paste(avatar_image, (0, 0))
        output.putalpha(mask)
        img.paste(output, (avatar_x, avatar_y), output)
    else:
        draw.ellipse([avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size], fill=chart_bg)
    
    # Username and title
    username_x = avatar_x + avatar_size + 30 * scale
    username_y = avatar_y + 10 * scale
    draw.text((username_x, username_y), username, font=font_title, fill=text_color)
    draw.text((username_x, username_y + 60 * scale), "Activity Statistics", font=font_small, fill=subtext_color)
    
    # Main stats section
    stats_y = avatar_y + avatar_size + 40 * scale
    left_col_x = 50 * scale
    right_col_x = width // 2 + 30 * scale
    
    # Left column stats
    y_offset = stats_y
    line_height = 50 * scale
    
    # First message date
    first_msg_str = first_message_date.strftime('%B %d, %Y')
    draw.text((left_col_x, y_offset), "First Message", font=font_small, fill=subtext_color)
    y_offset += 30 * scale
    draw.text((left_col_x, y_offset), first_msg_str, font=font_normal, fill=text_color)
    y_offset += line_height
    
    # Total messages
    draw.text((left_col_x, y_offset), "Total Messages", font=font_small, fill=subtext_color)
    y_offset += 30 * scale
    draw.text((left_col_x, y_offset), f"{total_messages:,}", font=font_large, fill=accent_color)
    y_offset += line_height + 10 * scale
    
    # Edited messages
    edit_pct = (edited_messages / total_messages * 100) if total_messages > 0 else 0
    draw.text((left_col_x, y_offset), "Edited Messages", font=font_small, fill=subtext_color)
    y_offset += 30 * scale
    draw.text((left_col_x, y_offset), f"{edited_messages:,} ({edit_pct:.1f}%)", font=font_normal, fill=text_color)
    y_offset += line_height
    
    # Days active
    draw.text((left_col_x, y_offset), "Days Active", font=font_small, fill=subtext_color)
    y_offset += 30 * scale
    draw.text((left_col_x, y_offset), f"{days_active:,} days", font=font_normal, fill=text_color)
    y_offset += line_height
    
    # Average messages per day
    draw.text((left_col_x, y_offset), "Avg Messages/Day", font=font_small, fill=subtext_color)
    y_offset += 30 * scale
    draw.text((left_col_x, y_offset), f"{avg_messages_per_day:.1f}", font=font_normal, fill=text_color)
    
    # Right column - Most active times
    y_offset = stats_y
    draw.text((right_col_x, y_offset), "Most Active Times", font=font_medium, fill=text_color)
    y_offset += 50 * scale
    
    # Most active hour
    draw.text((right_col_x, y_offset), f"Hour: {most_active_hour:02d}:00-{most_active_hour:02d}:59", font=font_normal, fill=subtext_color)
    y_offset += 40 * scale
    
    # Most active day
    draw.text((right_col_x, y_offset), f"Day: {day_names[most_active_day]}", font=font_normal, fill=subtext_color)
    y_offset += 40 * scale
    
    # Most active month
    draw.text((right_col_x, y_offset), f"Month: {month_names[most_active_month]}", font=font_normal, fill=subtext_color)
    y_offset += 60 * scale
    
    # Top channels
    draw.text((right_col_x, y_offset), "Top Channels", font=font_medium, fill=text_color)
    y_offset += 40 * scale
    
    for i, (channel, count) in enumerate(top_channels[:5], 1):
        pct = (count / total_messages * 100) if total_messages > 0 else 0
        channel_text = f"{i}. #{channel[:18]}"
        draw.text((right_col_x, y_offset), channel_text, font=font_small, fill=subtext_color)
        draw.text((right_col_x + 280 * scale, y_offset), f"{count:,} ({pct:.1f}%)", font=font_small, fill=text_color)
        y_offset += 32 * scale
    
    # Hourly activity chart
    chart_y = stats_y + 480 * scale
    draw.text((left_col_x, chart_y), "Hourly Activity (24h)", font=font_medium, fill=text_color)
    chart_y += 50 * scale
    
    chart_width = width - 100 * scale
    chart_height = 180 * scale
    chart_x = left_col_x
    
    # Draw hourly chart background
    draw.rectangle([chart_x, chart_y, chart_x + chart_width, chart_y + chart_height], fill=chart_bg)
    
    # Draw hourly bars with values
    max_hourly = max(hourly_distribution.values()) if hourly_distribution else 1
    bar_width = chart_width / 24
    
    for hour in range(24):
        count = hourly_distribution.get(hour, 0)
        if count > 0:
            # Use logarithmic-like scaling for better visual distinction
            # This makes smaller values more visible while still showing relative differences
            normalized = count / max_hourly
            # Apply a power function to enhance differences (0.6 makes small values more visible)
            scaled_height = normalized ** 0.6
            bar_height = scaled_height * (chart_height - 10 * scale)
            
            bar_x = chart_x + hour * bar_width + 2
            bar_y = chart_y + chart_height - bar_height - 5 * scale
            
            # Draw bar with gradient effect (darker at top)
            draw.rectangle([bar_x, bar_y, bar_x + bar_width - 4, chart_y + chart_height - 5 * scale], fill=chart_fill)
            
            # Draw value label on top of significant bars
            if count >= max_hourly * 0.3:  # Only show labels for bars that are at least 30% of max
                label = str(count) if count < 1000 else f"{count//1000}k"
                try:
                    label_bbox = draw.textbbox((0, 0), label, font=font_tiny)
                    label_width = label_bbox[2] - label_bbox[0]
                except:
                    label_width = len(label) * 10 * scale
                
                label_x = bar_x + (bar_width - 4 - label_width) / 2
                label_y = bar_y - 18 * scale
                draw.text((label_x, label_y), label, font=font_tiny, fill=text_color)
    
    # Hour labels at bottom (outside the chart)
    for hour in [0, 4, 8, 12, 16, 20]:
        label_x = chart_x + hour * bar_width
        draw.text((label_x, chart_y + chart_height + 8 * scale), f"{hour:02d}", font=font_tiny, fill=subtext_color)
    
    # Weekly activity chart
    chart_y += chart_height + 60 * scale
    draw.text((left_col_x, chart_y), "Weekly Activity", font=font_medium, fill=text_color)
    chart_y += 50 * scale
    
    chart_height = 180 * scale
    draw.rectangle([chart_x, chart_y, chart_x + chart_width, chart_y + chart_height], fill=chart_bg)
    
    # Draw daily bars with values
    max_daily = max(daily_distribution.values()) if daily_distribution else 1
    bar_width = chart_width / 7
    
    for day in range(7):
        count = daily_distribution.get(day, 0)
        if count > 0:
            # Use same scaling approach as hourly
            normalized = count / max_daily
            scaled_height = normalized ** 0.6
            bar_height = scaled_height * (chart_height - 10 * scale)
            
            bar_x = chart_x + day * bar_width + 10 * scale
            bar_y = chart_y + chart_height - bar_height - 5 * scale
            draw.rectangle([bar_x, bar_y, bar_x + bar_width - 20 * scale, chart_y + chart_height - 5 * scale], fill=chart_fill)
            
            # Draw value label on bars
            label = str(count) if count < 1000 else f"{count//1000}k"
            try:
                label_bbox = draw.textbbox((0, 0), label, font=font_small)
                label_width = label_bbox[2] - label_bbox[0]
            except:
                label_width = len(label) * 12 * scale
            
            label_x = bar_x + (bar_width - 20 * scale - label_width) / 2
            label_y = bar_y - 25 * scale
            draw.text((label_x, label_y), label, font=font_small, fill=text_color)
        
        # Day labels at bottom (outside the chart)
        label_x = chart_x + day * bar_width + bar_width / 2 - 25 * scale
        draw.text((label_x, chart_y + chart_height + 8 * scale), day_names[day], font=font_small, fill=subtext_color)
    
    # Yearly activity (if multiple years) - use multi-column layout to prevent overflow
    if len(yearly_distribution) > 1:
        chart_y += chart_height + 60 * scale
        draw.text((left_col_x, chart_y), "Activity by Year", font=font_medium, fill=text_color)
        chart_y += 40 * scale
        
        sorted_years = sorted(yearly_distribution.keys())
        
        # Calculate if we need multiple columns (more than 4 years)
        years_per_column = 4
        num_columns = (len(sorted_years) + years_per_column - 1) // years_per_column
        column_width = (width - 100 * scale) // num_columns
        
        for idx, year in enumerate(sorted_years):
            count = yearly_distribution[year]
            
            # Determine which column this year goes in
            col = idx // years_per_column
            row = idx % years_per_column
            
            year_x = left_col_x + col * column_width
            year_y = chart_y + row * 35 * scale
            
            draw.text((year_x, year_y), f"{year}:", font=font_normal, fill=subtext_color)
            draw.text((year_x + 120 * scale, year_y), f"{count:,} messages", font=font_normal, fill=text_color)
    
    # Convert to bytes
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    
    return buffer
