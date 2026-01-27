"""Word counter system for tracking specific words/phrases."""
import json
from pathlib import Path
from typing import Dict, List, Set

COUNTERS_FILE = Path("word_counters.json")

class WordCounterManager:
    """Manages word counters for guilds."""
    
    def __init__(self):
        self.counters: Dict[int, Dict[str, dict]] = {}
        self.load()
    
    def load(self):
        """Load counters from file."""
        if COUNTERS_FILE.exists():
            with COUNTERS_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
                # Convert string keys back to ints
                self.counters = {int(k): v for k, v in data.items()}
        else:
            self.counters = {}
    
    def save(self):
        """Save counters to file."""
        with COUNTERS_FILE.open("w", encoding="utf-8") as f:
            json.dump(self.counters, f, indent=2, ensure_ascii=False)
    
    def get_guild_counters(self, guild_id: int) -> Dict[str, dict]:
        """Get all counters for a guild."""
        return self.counters.get(guild_id, {})
    
    def create_counter(self, guild_id: int, counter_name: str, words: List[str]) -> bool:
        """
        Create a new counter.
        
        Args:
            guild_id: Guild ID
            counter_name: Name of the counter
            words: List of words/phrases to track
        
        Returns:
            True if created, False if already exists
        """
        if guild_id not in self.counters:
            self.counters[guild_id] = {}
        
        if counter_name in self.counters[guild_id]:
            return False
        
        self.counters[guild_id][counter_name] = {
            "words": [w.lower() for w in words],  # Store lowercase for matching
            "count": 0
        }
        self.save()
        return True
    
    def delete_counter(self, guild_id: int, counter_name: str) -> bool:
        """Delete a counter."""
        if guild_id not in self.counters:
            return False
        
        if counter_name not in self.counters[guild_id]:
            return False
        
        del self.counters[guild_id][counter_name]
        self.save()
        return True
    
    def rename_counter(self, guild_id: int, old_name: str, new_name: str) -> bool:
        """
        Rename a counter.
        
        Args:
            guild_id: Guild ID
            old_name: Current counter name
            new_name: New counter name
        
        Returns:
            True if renamed, False if old_name doesn't exist or new_name already exists
        """
        if guild_id not in self.counters:
            return False
        
        if old_name not in self.counters[guild_id]:
            return False
        
        if new_name in self.counters[guild_id]:
            return False
        
        # Move the counter data to the new name
        self.counters[guild_id][new_name] = self.counters[guild_id][old_name]
        del self.counters[guild_id][old_name]
        self.save()
        return True
    
    def add_words(self, guild_id: int, counter_name: str, words: List[str]) -> bool:
        """Add words to an existing counter."""
        if guild_id not in self.counters or counter_name not in self.counters[guild_id]:
            return False
        
        existing_words = set(self.counters[guild_id][counter_name]["words"])
        for word in words:
            existing_words.add(word.lower())
        
        self.counters[guild_id][counter_name]["words"] = list(existing_words)
        self.save()
        return True
    
    def remove_words(self, guild_id: int, counter_name: str, words: List[str]) -> bool:
        """Remove words from a counter."""
        if guild_id not in self.counters or counter_name not in self.counters[guild_id]:
            return False
        
        existing_words = set(self.counters[guild_id][counter_name]["words"])
        for word in words:
            existing_words.discard(word.lower())
        
        self.counters[guild_id][counter_name]["words"] = list(existing_words)
        self.save()
        return True
    
    def increment_counter(self, guild_id: int, counter_name: str) -> int:
        """Increment a counter and return new count."""
        if guild_id not in self.counters or counter_name not in self.counters[guild_id]:
            return 0
        
        self.counters[guild_id][counter_name]["count"] += 1
        new_count = self.counters[guild_id][counter_name]["count"]
        self.save()
        return new_count
    
    def set_count(self, guild_id: int, counter_name: str, count: int) -> bool:
        """Set a counter to a specific value."""
        if guild_id not in self.counters or counter_name not in self.counters[guild_id]:
            return False
        
        self.counters[guild_id][counter_name]["count"] = count
        self.save()
        return True
    
    def check_message(self, guild_id: int, message_content: str) -> List[tuple]:
        """
        Check if message contains any tracked words and count all occurrences.
        
        Returns:
            List of (counter_name, new_count) tuples for counters that were triggered
        """
        if guild_id not in self.counters:
            return []
        
        message_lower = message_content.lower()
        triggered = []
        
        for counter_name, counter_data in self.counters[guild_id].items():
            total_occurrences = 0
            # Count all occurrences of all tracked words in this message
            for word in counter_data["words"]:
                total_occurrences += message_lower.count(word)
            
            # Increment counter by the total number of occurrences found
            if total_occurrences > 0:
                if guild_id in self.counters and counter_name in self.counters[guild_id]:
                    self.counters[guild_id][counter_name]["count"] += total_occurrences
                    new_count = self.counters[guild_id][counter_name]["count"]
                    self.save()
                    triggered.append((counter_name, new_count))
        
        return triggered

# Global instance
word_counter_manager = WordCounterManager()
