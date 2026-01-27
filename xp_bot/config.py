"""Configuration settings for the bot."""
import os

# Bot configuration
TOKEN = os.getenv("DISCORD_TOKEN") 
DB_PATH = "levels.db"

# Live XP rules (normal chatting)
XP_MIN = 15
XP_MAX = 25
COOLDOWN_SECONDS = 60

# Import/backfill rules
IMPORT_XP_MIN = 15
IMPORT_XP_MAX = 25
IMPORT_COOLDOWN_SECONDS = 60  # MEE6-ish: only award once per minute per user during import

# Rate limit friendly pacing - Discord allows ~50 requests per second, but we go much slower to avoid 429s
IMPORT_SLEEP_EVERY = 25  # Sleep after every N messages to avoid rate limits
IMPORT_SLEEP_SECONDS = 2.0  # Sleep duration in seconds - gives Discord time to recover
IMPORT_BATCH_SIZE = 100  # Commit database changes every N messages

# Database settings
DB_TIMEOUT = 30.0  # Timeout in seconds for database operations (helps with concurrent access)

# Archive settings
LIVE_ARCHIVE_ENABLED = True
ARCHIVE_COMMAND_MESSAGES = False  # set True if you want to archive bot commands too
ARCHIVE_BOT_MESSAGES = False      # set True if you want bot messages archived

# Hate speech detection settings
HATE_SPEECH_DETECTION_ENABLED = False  # Set to True to enable automatic hate speech detection
HATE_SPEECH_THRESHOLD = 0.80  # Confidence threshold (0.0-1.0) for triggering warnings
