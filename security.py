# security.py
import discord
from database import get_setting

async def is_allowed_guild(guild: discord.Guild) -> bool:
    """
    Check if the bot is configured to operate in this guild.
    The allowed server ID is stored in settings table under key 'server_id'.
    If not set yet, allow (so admins can configure).
    """
    try:
        server_id = await get_setting("server_id")
        if server_id is None:
            return True
        return int(server_id) == guild.id
    except Exception:
        return False

def has_auction_role(member: discord.Member, role_id: int) -> bool:
    if member is None:
        return False
    return any(r.id == role_id for r in member.roles)

def verify_secret(provided: str, actual: str) -> bool:
    return provided == actual
