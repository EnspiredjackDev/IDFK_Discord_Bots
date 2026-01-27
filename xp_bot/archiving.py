"""Message archiving functionality."""
import json
from datetime import timezone
from pathlib import Path
import discord

def archive_path(guild_id: int, channel_id: int) -> Path:
    """Get the path to the archive file for a channel."""
    base = Path("archives") / str(guild_id)
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{channel_id}.jsonl"

def msg_to_archive_dict(msg: discord.Message) -> dict:
    """Convert a Discord message to a dictionary for archiving."""
    ref = None
    if msg.reference and isinstance(msg.reference.resolved, discord.Message):
        ref = msg.reference.resolved.id
    elif msg.reference:
        # reference may not be resolved; keep the id if present
        ref = getattr(msg.reference, "message_id", None)

    return {
        "id": msg.id,
        "channel_id": msg.channel.id,
        "channel_name": getattr(msg.channel, "name", None),
        "guild_id": msg.guild.id if msg.guild else None,
        "author_id": msg.author.id,
        "author_name": str(msg.author),
        "author_display_name": getattr(msg.author, "display_name", str(msg.author)),
        "created_at": msg.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "edited_at": (msg.edited_at.replace(tzinfo=timezone.utc).isoformat() if msg.edited_at else None),
        "content": msg.content,
        "reference_message_id": ref,
        "mentions_user_ids": [u.id for u in msg.mentions],
        "mentions_role_ids": [r.id for r in msg.role_mentions],
        "mentions_everyone": bool(msg.mention_everyone),
        "pinned": bool(msg.pinned),
        "tts": bool(msg.tts),
        "type": str(msg.type),
    }

def append_jsonl(path: Path, obj: dict):
    """Append a JSON object as a new line to a JSONL file."""
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
