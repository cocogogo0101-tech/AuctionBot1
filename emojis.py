# emojis.py
"""
Emoji manager: store per-key emoji (server custom emoji string or plain unicode)
in the database under settings keys: emoji_{name}
Provides async helpers to get/set/list emojis with fallback to default map.
"""

from typing import Dict, Optional
import database

# defaults (fallbacks) — you can change/add keys freely
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
}

async def get_emoji(name: str) -> str:
    if not name:
        return ""
    try:
        v = await database.get_setting(f"emoji_{name}")
    except Exception:
        v = None
    if v:
        return v
    return DEFAULT_EMOJI_MAP.get(name, "")

async def set_emoji(name: str, emoji_str: str) -> None:
    if not name:
        raise ValueError("name required")
    await database.set_setting(f"emoji_{name}", emoji_str)

async def list_emojis() -> Dict[str, str]:
    out = {}
    try:
        all_settings = await database.all_settings()
    except Exception:
        all_settings = {}
    for k, v in all_settings.items():
        if k.startswith("emoji_"):
            name = k[len("emoji_"):]
            out[name] = v
    for k, v in DEFAULT_EMOJI_MAP.items():
        if k not in out:
            out[k] = v
    return out