# security.py
import discord
from typing import Optional
import database

async def is_allowed_guild(guild: Optional[discord.Guild]) -> bool:
    """
    Returns True if bot is allowed to operate in this guild (server_id configured in DB) or setting not set.
    """
    if guild is None:
        return False
    server_id = await database.get_setting("server_id")
    if not server_id:
        return True
    try:
        return int(server_id) == guild.id
    except Exception:
        return False

def has_auction_role(member: Optional[discord.Member], role_id: int) -> bool:
    if member is None or role_id is None:
        return False
    return any(r.id == role_id for r in getattr(member, "roles", []))

def verify_secret(provided: str, actual: str) -> bool:
    return provided == actual