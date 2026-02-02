# emojis.py
# Simple mapping and helper in case you want to replace with server custom emojis later.
EMOJI_MAP = {
    "fire": "🔥",
    "money": "💰",
    "bid": "🔼",
    "custom": "💠"
}

def get(name: str) -> str:
    return EMOJI_MAP.get(name, "")
