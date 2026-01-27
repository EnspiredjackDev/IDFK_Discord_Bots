"""Semantic search and embedding indexing for messages."""
import json
import asyncio
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
import aiosqlite

from xp_bot.config import DB_PATH, DB_TIMEOUT

# Paths
CHROMA_DB_PATH = Path(__file__).parent.parent / "chroma_db"
ARCHIVE_PATH = Path(__file__).parent.parent / "archives"

# Global instances (initialized once)
_model: Optional[SentenceTransformer] = None
_client: Optional[chromadb.Client] = None
_collection: Optional[chromadb.Collection] = None
_hate_speech_model = None
_hate_speech_tokenizer = None

# Model name - lightweight and fast
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
HATE_SPEECH_MODEL = "cardiffnlp/twitter-roberta-base-hate-multiclass-latest"

# Message grouping settings
MESSAGE_GROUP_TIME_WINDOW = 300  # 5 minutes in seconds
MESSAGE_GROUP_MIN_LENGTH = 20    # Minimum chars to index a message group

# Live message buffer for grouping (guild_id -> user_id -> message_data)
_live_message_buffer: Dict[int, Dict[int, Dict]] = {}


def init_semantic():
    """Initialize the embedding model and ChromaDB client."""
    global _model, _client, _collection
    
    if _model is None:
        print(f"Loading embedding model: {MODEL_NAME}...")
        _model = SentenceTransformer(MODEL_NAME)
        print("Embedding model loaded.")
    
    if _client is None:
        print(f"Initializing ChromaDB at {CHROMA_DB_PATH}...")
        CHROMA_DB_PATH.mkdir(exist_ok=True)
        _client = chromadb.PersistentClient(
            path=str(CHROMA_DB_PATH),
            settings=Settings(anonymized_telemetry=False)
        )
        _collection = _client.get_or_create_collection(
            name="discord_messages",
            metadata={"hnsw:space": "cosine"}
        )
        print(f"ChromaDB initialized. Collection size: {_collection.count()}")
    
    return _model, _collection


def get_semantic():
    """Get initialized model and collection, initializing if needed."""
    if _model is None or _collection is None:
        return init_semantic()
    return _model, _collection


async def index_message(
    message_id: str,
    content: str,
    user_id: int,
    username: str,
    channel_id: int,
    channel_name: str,
    guild_id: int,
    timestamp: str
):
    """
    Index a single message into ChromaDB with smart grouping.
    Messages from the same user within 5 minutes are grouped for better context.
    
    Args:
        message_id: Unique message ID
        content: Message content
        user_id: User ID
        username: Username
        channel_id: Channel ID
        channel_name: Channel name
        guild_id: Guild ID
        timestamp: ISO format timestamp
    """
    # Skip empty messages
    if not content or not content.strip():
        return
    
    global _live_message_buffer
    
    # Initialize buffer for this guild if needed
    if guild_id not in _live_message_buffer:
        _live_message_buffer[guild_id] = {}
    
    # Parse timestamp
    try:
        msg_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except:
        msg_time = datetime.utcnow()
    
    # Check if we have a buffered group for this user
    buffer_key = (user_id, channel_id)
    if buffer_key in _live_message_buffer[guild_id]:
        buffered = _live_message_buffer[guild_id][buffer_key]
        time_diff = (msg_time - buffered["last_time"]).total_seconds()
        
        # If within time window, add to buffer
        if time_diff <= MESSAGE_GROUP_TIME_WINDOW:
            buffered["content"] += "\n" + content
            buffered["message_ids"].append(message_id)
            buffered["last_time"] = msg_time
            
            # If buffer gets long enough, index it
            if len(buffered["content"]) >= 200:  # Index at 200 chars for live messages
                await _flush_message_buffer(guild_id, buffer_key)
            return
        else:
            # Time window expired, flush old buffer and start new one
            await _flush_message_buffer(guild_id, buffer_key)
    
    # Start new buffer for this user/channel
    _live_message_buffer[guild_id][buffer_key] = {
        "id": f"{message_id}_group",
        "content": content,
        "user_id": user_id,
        "username": username,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "guild_id": guild_id,
        "timestamp": timestamp,
        "message_ids": [message_id],
        "last_time": msg_time
    }


async def _flush_message_buffer(guild_id: int, buffer_key: Tuple[int, int]):
    """Flush a buffered message group to the database."""
    global _live_message_buffer
    
    if guild_id not in _live_message_buffer:
        return
    if buffer_key not in _live_message_buffer[guild_id]:
        return
    
    buffered = _live_message_buffer[guild_id].pop(buffer_key)
    
    # Only index if meets minimum length
    if len(buffered["content"]) < MESSAGE_GROUP_MIN_LENGTH:
        return
    
    # Get model and collection
    model, collection = get_semantic()
    
    # Generate embedding
    loop = asyncio.get_event_loop()
    embedding = await loop.run_in_executor(None, model.encode, buffered["content"])
    
    # Store in ChromaDB
    collection.add(
        ids=[buffered["id"]],
        embeddings=[embedding.tolist()],
        metadatas=[{
            "user_id": str(buffered["user_id"]),
            "username": buffered["username"],
            "channel_id": str(buffered["channel_id"]),
            "channel_name": buffered["channel_name"],
            "guild_id": str(buffered["guild_id"]),
            "timestamp": buffered["timestamp"],
            "content": buffered["content"][:1000],
            "message_count": str(len(buffered["message_ids"])),
            "is_grouped": "true"
        }]
    )


async def index_messages_batch(messages: List[Dict]):
    """
    Index multiple messages in a batch, grouping consecutive messages
    from the same user within a time window for better context.
    
    Args:
        messages: List of message dicts with keys: id, content, user_id, username, 
                  channel_id, channel_name, guild_id, timestamp
    """
    if not messages:
        return
    
    # Filter out empty messages
    messages = [m for m in messages if m.get("content", "").strip()]
    if not messages:
        return
    
    # Sort by timestamp to ensure chronological order
    messages.sort(key=lambda m: m.get("timestamp", ""))
    
    # Group consecutive messages from same user within time window
    grouped_messages = []
    current_group = None
    
    for msg in messages:
        user_id = msg["user_id"]
        timestamp_str = msg.get("timestamp", "")
        
        try:
            # Parse timestamp
            if timestamp_str:
                msg_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            else:
                msg_time = None
        except:
            msg_time = None
        
        # Check if we should group with current group
        should_group = False
        if current_group and msg_time:
            same_user = current_group["user_id"] == user_id
            same_channel = current_group["channel_id"] == msg["channel_id"]
            
            if same_user and same_channel and current_group.get("last_time"):
                time_diff = (msg_time - current_group["last_time"]).total_seconds()
                should_group = time_diff <= MESSAGE_GROUP_TIME_WINDOW
        
        if should_group:
            # Add to current group
            current_group["content"] += "\n" + msg["content"]
            current_group["message_ids"].append(str(msg["id"]))
            current_group["last_time"] = msg_time
        else:
            # Save previous group if it exists and meets minimum length
            if current_group and len(current_group["content"]) >= MESSAGE_GROUP_MIN_LENGTH:
                grouped_messages.append(current_group)
            
            # Start new group
            current_group = {
                "id": f"{msg['id']}_group",  # Use first message ID as base
                "content": msg["content"],
                "user_id": user_id,
                "username": msg.get("username", "Unknown"),
                "channel_id": msg["channel_id"],
                "channel_name": msg.get("channel_name", "unknown"),
                "guild_id": msg["guild_id"],
                "timestamp": timestamp_str,
                "message_ids": [str(msg["id"])],
                "last_time": msg_time
            }
    
    # Don't forget the last group
    if current_group and len(current_group["content"]) >= MESSAGE_GROUP_MIN_LENGTH:
        grouped_messages.append(current_group)
    
    if not grouped_messages:
        return
    
    model, collection = get_semantic()
    
    # Generate embeddings in batch (much faster)
    contents = [m["content"] for m in grouped_messages]
    loop = asyncio.get_event_loop()
    embeddings = await loop.run_in_executor(None, model.encode, contents)
    
    # Prepare data
    ids = [m["id"] for m in grouped_messages]
    metadatas = [
        {
            "user_id": str(m["user_id"]),
            "username": m["username"],
            "channel_id": str(m["channel_id"]),
            "channel_name": m["channel_name"],
            "guild_id": str(m["guild_id"]),
            "timestamp": m["timestamp"],
            "content": m["content"][:1000],  # Store more content since it's grouped
            "message_count": str(len(m["message_ids"])),  # Track how many messages were grouped
            "is_grouped": "true"
        }
        for m in grouped_messages
    ]
    
    # Add to collection
    collection.add(
        ids=ids,
        embeddings=embeddings.tolist(),
        metadatas=metadatas
    )


async def semantic_search(
    query: str,
    guild_id: int,
    n_results: int = 100,
    user_id: Optional[int] = None,
    channel_id: Optional[int] = None
) -> List[Dict]:
    """
    Search for messages semantically similar to the query.
    
    Args:
        query: Search query
        guild_id: Guild ID to filter by
        n_results: Number of results to return
        user_id: Optional user ID filter
        channel_id: Optional channel ID filter
    
    Returns:
        List of dicts with keys: message_id, content, user_id, username, 
        channel_id, channel_name, timestamp, distance
    """
    model, collection = get_semantic()
    
    # Generate query embedding
    loop = asyncio.get_event_loop()
    query_embedding = await loop.run_in_executor(None, model.encode, query)
    
    # Build where filter
    where_filter = {"guild_id": str(guild_id)}
    if user_id:
        where_filter["user_id"] = str(user_id)
    if channel_id:
        where_filter["channel_id"] = str(channel_id)
    
    # Query ChromaDB
    results = collection.query(
        query_embeddings=[query_embedding.tolist()],
        n_results=n_results,
        where=where_filter
    )
    
    # Format results
    if not results["ids"] or not results["ids"][0]:
        return []
    
    formatted = []
    for i, msg_id in enumerate(results["ids"][0]):
        metadata = results["metadatas"][0][i]
        distance = results["distances"][0][i] if results.get("distances") else None
        
        formatted.append({
            "message_id": msg_id,
            "content": metadata["content"],
            "user_id": int(metadata["user_id"]),
            "username": metadata["username"],
            "channel_id": int(metadata["channel_id"]),
            "channel_name": metadata["channel_name"],
            "timestamp": metadata["timestamp"],
            "distance": distance,
            "message_count": int(metadata.get("message_count", "1")),
            "is_grouped": metadata.get("is_grouped") == "true"
        })
    
    return formatted


async def get_user_sentiment_scores(
    guild_id: int,
    trait_query: str,
    top_n: int = 10
) -> List[Tuple[int, str, int, float]]:
    """
    Get users ranked by how much their messages match a trait/sentiment.
    
    Args:
        guild_id: Guild ID
        trait_query: Description of trait (e.g., "racist", "enterprising", "funny")
        top_n: Number of top users to return
    
    Returns:
        List of tuples: (user_id, username, message_count, avg_similarity)
    """
    # Get many results to aggregate by user
    results = await semantic_search(
        query=trait_query,
        guild_id=guild_id,
        n_results=500
    )
    
    # Aggregate by user
    user_scores: Dict[int, List[float]] = {}
    user_names: Dict[int, str] = {}
    
    for result in results:
        user_id = result["user_id"]
        username = result["username"]
        # Lower distance = more similar
        # Convert to similarity score (1 - normalized distance)
        similarity = 1.0 - (result["distance"] if result["distance"] else 0.5)
        
        if user_id not in user_scores:
            user_scores[user_id] = []
            user_names[user_id] = username
        
        user_scores[user_id].append(similarity)
    
    # Calculate weighted score that considers both similarity and message count
    # This prevents users with 1 high-scoring message from ranking above users with many messages
    user_rankings = []
    for user_id, scores in user_scores.items():
        avg_score = sum(scores) / len(scores)
        message_count = len(scores)
        
        # Apply logarithmic bonus for message count
        # 1 message = 0% bonus, 10 messages = ~10% bonus, 100 messages = ~20% bonus
        import math
        message_bonus = math.log10(message_count + 1) * 0.1  # 10% per order of magnitude
        
        # Weighted score = base similarity + bonus (capped at 15% to not overpower similarity)
        weighted_score = avg_score * (1 + min(message_bonus, 0.15))
        
        user_rankings.append((
            user_id,
            user_names[user_id],
            message_count,
            weighted_score  # Use weighted score for sorting
        ))
    
    # Sort by weighted score descending
    user_rankings.sort(key=lambda x: x[3], reverse=True)
    
    return user_rankings[:top_n]


async def index_archives(guild_id: int, progress_callback=None):
    """
    Index all archived messages for a guild.
    
    Args:
        guild_id: Guild ID to index
        progress_callback: Optional async function to call with progress updates
    """
    guild_path = ARCHIVE_PATH / str(guild_id)
    if not guild_path.exists():
        return 0
    
    model, collection = get_semantic()
    total_indexed = 0
    batch_size = 100
    
    # Get existing indexed message IDs to avoid duplicates
    existing_ids = set()
    try:
        # Query all existing IDs for this guild (in batches)
        all_results = collection.get(
            where={"guild_id": str(guild_id)},
            include=[]
        )
        existing_ids = set(all_results["ids"]) if all_results["ids"] else set()
    except:
        pass
    
    # Load channel names from database
    channel_names = {}
    async with aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT) as db:
        # We don't have a channels table, so we'll use "unknown" or extract from archives
        pass
    
    # Process each channel archive
    for channel_file in guild_path.glob("*.jsonl"):
        channel_id = int(channel_file.stem)
        
        if progress_callback:
            await progress_callback(f"Indexing channel {channel_id}...")
        
        batch = []
        with open(channel_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                try:
                    msg = json.loads(line)
                    msg_id = str(msg.get("id", ""))
                    
                    # Skip if already indexed
                    if msg_id in existing_ids:
                        continue
                    
                    # Skip bot messages and empty content
                    if msg.get("bot") or not msg.get("content", "").strip():
                        continue
                    
                    batch.append({
                        "id": msg_id,
                        "content": msg["content"],
                        "user_id": msg.get("author_id", 0),
                        "username": msg.get("author_name", "Unknown"),
                        "channel_id": channel_id,
                        "channel_name": msg.get("channel_name", f"channel-{channel_id}"),
                        "guild_id": guild_id,
                        "timestamp": msg.get("timestamp", "")
                    })
                    
                    # Index in batches
                    if len(batch) >= batch_size:
                        await index_messages_batch(batch)
                        total_indexed += len(batch)
                        if progress_callback:
                            await progress_callback(f"Indexed {total_indexed} messages...")
                        batch = []
                
                except Exception as e:
                    print(f"Error processing message in {channel_file}:{line_num}: {e}")
                    continue
        
        # Index remaining batch
        if batch:
            await index_messages_batch(batch)
            total_indexed += len(batch)
    
    if progress_callback:
        await progress_callback(f"Indexing complete! Total: {total_indexed} messages")
    
    return total_indexed


def get_collection_stats(guild_id: Optional[int] = None) -> Dict:
    """Get statistics about the indexed messages."""
    _, collection = get_semantic()
    
    if guild_id:
        results = collection.get(
            where={"guild_id": str(guild_id)},
            include=[]
        )
        count = len(results["ids"]) if results["ids"] else 0
    else:
        count = collection.count()
    
    return {
        "total_messages": count,
        "guild_id": guild_id
    }


async def detect_hate_speech(content: str, threshold: float = 0.80) -> Optional[Tuple[float, str]]:
    """
    Detect if content contains hate speech using a pre-trained multi-class classifier.
    Returns actual confidence scores using softmax probabilities.
    
    Args:
        content: The message content to analyze
        threshold: Confidence threshold (0.0-1.0) to trigger detection (default 0.80)
    
    Returns:
        Tuple of (confidence, hate_type) if detected, None otherwise
        hate_type can be: "sexism", "racism", "disability", "sexual_orientation", "religion", or "other"
    """
    if not content or not content.strip():
        return None
    
    global _hate_speech_model, _hate_speech_tokenizer
    
    # Initialize hate speech model if needed
    if _hate_speech_model is None:
        try:
            import torch
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            
            print(f"[hate-speech] Loading hate speech model: {HATE_SPEECH_MODEL}...")
            print("[hate-speech] This may take a few minutes on first run (downloading model)...")
            
            _hate_speech_tokenizer = AutoTokenizer.from_pretrained(HATE_SPEECH_MODEL)
            _hate_speech_model = AutoModelForSequenceClassification.from_pretrained(HATE_SPEECH_MODEL)
            _hate_speech_model.eval()  # Set to evaluation mode
            
            print("[hate-speech] Hate speech detection model loaded successfully!")
        except Exception as e:
            print(f"[hate-speech] Failed to load hate speech model: {e}")
            # Set to False to prevent retrying every message
            _hate_speech_model = False
            return None
    
    # Check if model loading failed previously
    if _hate_speech_model is False:
        return None
    
    try:
        import torch
        
        # Tokenize input
        inputs = _hate_speech_tokenizer(content[:512], return_tensors="pt", truncation=True)
        
        # Get model predictions
        with torch.no_grad():
            logits = _hate_speech_model(**inputs).logits[0]
            probs = torch.softmax(logits, dim=-1)
        
        # Get predicted label and confidence
        pred_id = int(torch.argmax(probs))
        label = _hate_speech_model.config.id2label[pred_id]
        confidence = float(probs[pred_id])
        
        # Debug: print all classifications
        print(f"[hate-speech] '{content[:50]}...' -> {label} ({confidence:.1%})")
        
        # Skip if classified as "not_hate"
        if label == 'not_hate':
            return None
        
        # Check if above threshold
        if confidence >= threshold:
            return (confidence, label)
        
        return None
        
    except Exception as e:
        print(f"[hate-speech] Error analyzing content: {e}")
        return None
