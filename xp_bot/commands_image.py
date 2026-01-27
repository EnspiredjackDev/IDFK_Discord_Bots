"""Bot commands for image analysis."""
import io
import discord
from discord.ext import commands
from PIL import Image
import aiohttp


async def get_image_info(url: str) -> tuple[int, int, int]:
    """
    Download an image and get its dimensions and pixel count.
    
    Args:
        url: The URL of the image to analyze
        
    Returns:
        Tuple of (width, height, total_pixels)
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise ValueError(f"Failed to download image: HTTP {response.status}")
            
            image_data = await response.read()
            
    # Open image with PIL
    image = Image.open(io.BytesIO(image_data))
    width, height = image.size
    total_pixels = width * height
    
    return width, height, total_pixels


@commands.command()
async def pixel(ctx: commands.Context):
    """
    Analyze the resolution and pixel count of images in a replied message.
    
    Usage:
      Reply to a message containing images and use !pixel
      
    Example:
      (Reply to a message with images) !pixel
    
    This command will:
    - Show the resolution (width x height) for each image
    - Display the total pixel count for each image
    - Show a grand total of all pixels if multiple images are present
    """
    # Check if the command is a reply
    if not ctx.message.reference:
        await ctx.reply("❌ Please reply to a message containing images to use this command!")
        return
    
    # Get the message being replied to
    try:
        replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
    except discord.NotFound:
        await ctx.reply("❌ Could not find the message you replied to.")
        return
    except discord.HTTPException as e:
        await ctx.reply(f"❌ Error fetching the message: {e}")
        return
    
    # Collect all images from the message
    images = []
    
    # Check attachments
    for attachment in replied_message.attachments:
        # Check if it's an image
        if attachment.content_type and attachment.content_type.startswith('image/'):
            images.append(attachment.url)
    
    # Check embeds for images
    for embed in replied_message.embeds:
        if embed.image and embed.image.url:
            images.append(embed.image.url)
        if embed.thumbnail and embed.thumbnail.url:
            images.append(embed.thumbnail.url)
    
    if not images:
        await ctx.reply("❌ The replied message doesn't contain any images!")
        return
    
    # Analyze each image
    results = []
    grand_total_pixels = 0
    
    async with ctx.typing():
        for idx, image_url in enumerate(images, 1):
            try:
                width, height, total_pixels = await get_image_info(image_url)
                results.append({
                    'number': idx,
                    'width': width,
                    'height': height,
                    'total_pixels': total_pixels
                })
                grand_total_pixels += total_pixels
            except Exception as e:
                results.append({
                    'number': idx,
                    'error': str(e)
                })
    
    # Build the response embed
    embed = discord.Embed(
        title="📐 Image Resolution Analysis",
        color=discord.Color.blue()
    )
    
    # Add information for each image
    for result in results:
        if 'error' in result:
            embed.add_field(
                name=f"Image {result['number']}",
                value=f"❌ Error: {result['error']}",
                inline=False
            )
        else:
            # Format pixel count with commas for readability
            pixel_formatted = f"{result['total_pixels']:,}"
            
            embed.add_field(
                name=f"Image {result['number']}",
                value=(
                    f"**Resolution:** {result['width']} × {result['height']}\n"
                    f"**Total Pixels:** {pixel_formatted}"
                ),
                inline=False
            )
    
    # Add grand total if multiple images
    if len([r for r in results if 'error' not in r]) > 1:
        embed.add_field(
            name="📊 Grand Total",
            value=f"**Total Pixels (all images):** {grand_total_pixels:,}",
            inline=False
        )
    
    embed.set_footer(text=f"Analyzed {len(images)} image(s)")
    
    await ctx.reply(embed=embed)


def setup(bot: commands.Bot):
    """Add commands to the bot."""
    bot.add_command(pixel)
