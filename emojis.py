# emojis.py
"""
Emoji manager for AuctionBot.
Stores custom emoji mappings in database and provides fallbacks.
Supports both Discord custom emojis (<:name:id>) and Unicode emojis.
Includes caching for better performance.
"""

from typing import Dict, Optional
import database
import re
import asyncio
from config import DEBUG_MODE

# Default emoji mappings (fallbacks)
DEFAULT_EMOJI_MAP: Dict[str, str] = {
    "fire": "🔥",
    "money": "💰",
    "bid": "🔼",
    "celebrate": "🎉",
    "trophy": "🏆",
    "spark": "✨",
    "alarm": "⏳",
    "winner": "🏁",
    "info": "ℹ️",
    "crown": "👑",
    "chart": "📈",
    "coin": "🪙",
    "gem": "💎",
    "star": "⭐",
    "rocket": "🚀",
    "tada": "🎊",
    "bell": "🔔",
    "hourglass": "⌛",
    "checkmark": "✅",
    "cross": "❌",
    "warning": "⚠️",
    "gavel": "⚖️",
    "hammer": "🔨",
}

# In-memory cache for emoji lookups
_emoji_cache: Dict[str, str] = {}
_cache_initialized: bool = False
_cache_lock = asyncio.Lock()


async def _initialize_cache():
    """
    Initialize emoji cache from database.
    Called automatically on first use.
    """
    global _emoji_cache, _cache_initialized
    
    async with _cache_lock:
        if _cache_initialized:
            return
        
        try:
            all_settings = await database.all_settings()
            for key, value in all_settings.items():
                if key.startswith("emoji_"):
                    name = key[len("emoji_"):]
                    _emoji_cache[name] = value
            
            _cache_initialized = True
            
            if DEBUG_MODE:
                print(f"Emoji cache initialized with {len(_emoji_cache)} custom emojis")
        
        except Exception as e:
            if DEBUG_MODE:
                print(f"Failed to initialize emoji cache: {e}")
            _cache_initialized = True  # Mark as initialized to prevent retry loops


async def clear_cache():
    """
    Clear the emoji cache.
    Useful after bulk emoji updates.
    """
    global _emoji_cache, _cache_initialized
    
    async with _cache_lock:
        _emoji_cache.clear()
        _cache_initialized = False
    
    if DEBUG_MODE:
        print("Emoji cache cleared")


async def get_emoji(name: str, fallback: str = "") -> str:
    """
    Get emoji by name.
    Returns custom emoji from database, or default emoji, or fallback.
    
    Args:
        name: Emoji key name (e.g., "fire", "celebrate")
        fallback: String to return if emoji not found
        
    Returns:
        Emoji string (can be Unicode emoji or Discord format <:name:id>)
        
    Examples:
        >>> await get_emoji("fire")
        "🔥"
        >>> await get_emoji("custom")
        "<:custom:123456789>"
        >>> await get_emoji("nonexistent", "❓")
        "❓"
    """
    if not name:
        return fallback
    
    # Ensure cache is initialized
    if not _cache_initialized:
        await _initialize_cache()
    
    # Normalize name
    name = name.strip().lower()
    
    # Check cache first (custom emojis from DB)
    if name in _emoji_cache:
        return _emoji_cache[name]
    
    # Try database directly (in case cache missed it)
    try:
        db_value = await database.get_setting(f"emoji_{name}")
        if db_value:
            # Update cache
            _emoji_cache[name] = db_value
            return db_value
    except Exception as e:
        if DEBUG_MODE:
            print(f"Error fetching emoji '{name}' from database: {e}")
    
    # Check default emoji map
    if name in DEFAULT_EMOJI_MAP:
        return DEFAULT_EMOJI_MAP[name]
    
    # Return fallback
    return fallback


async def set_emoji(name: str, emoji_str: str, update_cache: bool = True) -> bool:
    """
    Set or update an emoji mapping.
    
    Args:
        name: Emoji key name
        emoji_str: Emoji string (Unicode or Discord format)
        update_cache: Whether to update cache immediately
        
    Returns:
        True if successful, False otherwise
        
    Raises:
        ValueError: If name or emoji_str is invalid
    """
    if not name:
        raise ValueError("Emoji name cannot be empty")
    
    if not emoji_str:
        raise ValueError("Emoji string cannot be empty")
    
    # Normalize name
    name = name.strip().lower()
    emoji_str = emoji_str.strip()
    
    # Validate name (alphanumeric and underscores only)
    if not re.match(r'^[a-z0-9_]+$', name):
        raise ValueError("Emoji name must contain only lowercase letters, numbers, and underscores")
    
    try:
        # Save to database
        await database.set_setting(f"emoji_{name}", emoji_str)
        
        # Update cache if requested
        if update_cache:
            _emoji_cache[name] = emoji_str
        
        if DEBUG_MODE:
            print(f"Emoji '{name}' set to: {emoji_str}")
        
        return True
    
    except Exception as e:
        if DEBUG_MODE:
            print(f"Failed to set emoji '{name}': {e}")
        return False


async def delete_emoji(name: str, update_cache: bool = True) -> bool:
    """
    Delete a custom emoji mapping.
    Note: This doesn't affect default emojis.
    
    Args:
        name: Emoji key name to delete
        update_cache: Whether to update cache immediately
        
    Returns:
        True if successful, False otherwise
    """
    if not name:
        return False
    
    name = name.strip().lower()
    
    try:
        # Delete from database by setting empty value
        await database.set_setting(f"emoji_{name}", "")
        
        # Remove from cache if present
        if update_cache and name in _emoji_cache:
            del _emoji_cache[name]
        
        if DEBUG_MODE:
            print(f"Emoji '{name}' deleted")
        
        return True
    
    except Exception as e:
        if DEBUG_MODE:
            print(f"Failed to delete emoji '{name}': {e}")
        return False


async def list_emojis(include_defaults: bool = True) -> Dict[str, str]:
    """
    List all emoji mappings.
    
    Args:
        include_defaults: Whether to include default emojis
        
    Returns:
        Dictionary mapping emoji names to emoji strings
    """
    result = {}
    
    # Add defaults first if requested
    if include_defaults:
        result.update(DEFAULT_EMOJI_MAP)
    
    # Ensure cache is initialized
    if not _cache_initialized:
        await _initialize_cache()
    
    # Add custom emojis (will override defaults if same name)
    result.update(_emoji_cache)
    
    # Also check database directly for any missed entries
    try:
        all_settings = await database.all_settings()
        for key, value in all_settings.items():
            if key.startswith("emoji_") and value:  # Skip empty values (deleted emojis)
                name = key[len("emoji_"):]
                if name not in result:  # Only add if not already present
                    result[name] = value
    except Exception as e:
        if DEBUG_MODE:
            print(f"Error listing emojis from database: {e}")
    
    return result


async def bulk_set_emojis(emoji_dict: Dict[str, str]) -> int:
    """
    Set multiple emojis at once.
    
    Args:
        emoji_dict: Dictionary mapping emoji names to emoji strings
        
    Returns:
        Number of emojis successfully set
    """
    count = 0
    
    for name, emoji_str in emoji_dict.items():
        try:
            if await set_emoji(name, emoji_str, update_cache=False):
                count += 1
        except Exception as e:
            if DEBUG_MODE:
                print(f"Failed to set emoji '{name}' in bulk operation: {e}")
    
    # Clear and reinitialize cache after bulk update
    await clear_cache()
    await _initialize_cache()
    
    if DEBUG_MODE:
        print(f"Bulk emoji update: {count}/{len(emoji_dict)} successful")
    
    return count


def is_discord_emoji(emoji_str: str) -> bool:
    """
    Check if string is a Discord custom emoji format.
    
    Args:
        emoji_str: String to check
        
    Returns:
        True if Discord custom emoji format, False otherwise
        
    Examples:
        >>> is_discord_emoji("<:fire:123456789>")
        True
        >>> is_discord_emoji("🔥")
        False
    """
    # Discord emoji format: <:name:id> or <a:name:id> for animated
    pattern = r'^<a?:[a-zA-Z0-9_]+:\d+>$'
    return bool(re.match(pattern, emoji_str))


def extract_emoji_id(emoji_str: str) -> Optional[int]:
    """
    Extract emoji ID from Discord custom emoji string.
    
    Args:
        emoji_str: Discord emoji string
        
    Returns:
        Emoji ID as integer, or None if invalid
        
    Examples:
        >>> extract_emoji_id("<:fire:123456789>")
        123456789
        >>> extract_emoji_id("🔥")
        None
    """
    if not is_discord_emoji(emoji_str):
        return None
    
    match = re.search(r':(\d+)>', emoji_str)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    
    return None


async def format_with_emojis(template: str, **kwargs) -> str:
    """
    Format a template string with emoji replacements.
    
    Args:
        template: String with emoji placeholders like {fire}, {celebrate}
        **kwargs: Additional format arguments
        
    Returns:
        Formatted string with emojis
        
    Examples:
        >>> await format_with_emojis("{fire} Hot! {celebrate}", user="John")
        "🔥 Hot! 🎉"
    """
    # Find all emoji placeholders
    emoji_pattern = r'\{([a-z_]+)\}'
    matches = re.findall(emoji_pattern, template)
    
    # Get all emojis
    emoji_values = {}
    for match in matches:
        if match not in emoji_values:  # Avoid duplicate lookups
            emoji_values[match] = await get_emoji(match)
    
    # Combine with other kwargs
    format_dict = {**emoji_values, **kwargs}
    
    try:
        return template.format(**format_dict)
    except KeyError as e:
        if DEBUG_MODE:
            print(f"Warning: Missing format key in template: {e}")
        return template  # Return original if formatting fails
