# security.py
"""
Security utilities for AuctionBot.
Handles permission checks, role validation, and guild restrictions.
"""

import discord
from typing import Optional, List, Tuple
import database
from config import REQUIRED_BOT_PERMISSIONS, DEBUG_MODE


async def is_allowed_guild(guild: Optional[discord.Guild]) -> bool:
    """
    Check if bot is allowed to operate in this guild.
    
    Args:
        guild: Discord guild object
        
    Returns:
        True if allowed, False otherwise
    """
    if guild is None:
        return False
    
    server_id = await database.get_setting("server_id")
    if not server_id:
        # No restriction set, allow all guilds
        return True
    
    try:
        allowed_id = int(server_id)
        return allowed_id == guild.id
    except (ValueError, TypeError):
        if DEBUG_MODE:
            print(f"ERROR: Invalid server_id in database: {server_id}")
        return False


async def has_auction_role(member: Optional[discord.Member]) -> Tuple[bool, str]:
    """
    Check if member has the auction role.
    
    Args:
        member: Discord member object
        
    Returns:
        Tuple of (has_role, error_message)
    """
    if member is None:
        return False, "Invalid member"
    
    role_id_str = await database.get_setting("role_id")
    if not role_id_str:
        return False, "Auction role not configured by admin"
    
    try:
        role_id = int(role_id_str)
    except (ValueError, TypeError):
        return False, "Invalid role configuration"
    
    # Check if member has the role
    has_role = any(r.id == role_id for r in getattr(member, "roles", []))
    
    if not has_role:
        # Try to get role mention for error message
        role = discord.utils.get(member.guild.roles, id=role_id)
        role_mention = role.mention if role else f"<@&{role_id}>"
        return False, f"You need the {role_mention} role to participate in auctions"
    
    return True, ""


async def has_admin_permissions(member: Optional[discord.Member]) -> bool:
    """
    Check if member has admin permissions (Manage Guild or Manage Roles).
    
    Args:
        member: Discord member object
        
    Returns:
        True if has permissions, False otherwise
    """
    if member is None:
        return False
    
    perms = getattr(member, "guild_permissions", None)
    if perms is None:
        return False
    
    return perms.manage_guild or perms.manage_roles


async def verify_secret(provided: str) -> Tuple[bool, str]:
    """
    Verify if provided secret matches the configured secret.
    
    Args:
        provided: Secret string to verify
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    actual = await database.get_setting("secret_code")
    
    if not actual:
        return False, "No secret code configured"
    
    if provided == actual:
        return True, ""
    
    return False, "Invalid secret code"


async def can_open_auction(member: Optional[discord.Member], 
                          secret: str = "") -> Tuple[bool, str]:
    """
    Check if member can open an auction.
    Member can open if they have: auction role, admin permissions, or valid secret.
    
    Args:
        member: Discord member object
        secret: Optional secret code
        
    Returns:
        Tuple of (can_open, error_message)
    """
    if member is None:
        return False, "Invalid member"
    
    # Check admin permissions first
    if await has_admin_permissions(member):
        return True, ""
    
    # Check auction role
    has_role, role_error = await has_auction_role(member)
    if has_role:
        return True, ""
    
    # Check secret if provided
    if secret:
        is_valid, secret_error = await verify_secret(secret)
        if is_valid:
            return True, ""
    
    # None of the checks passed
    return False, role_error or "No permission to open auction"


async def can_manage_auction(member: Optional[discord.Member],
                             secret: str = "") -> Tuple[bool, str]:
    """
    Check if member can manage auctions (end, undo, etc.).
    More strict than can_open_auction - requires admin or secret.
    
    Args:
        member: Discord member object
        secret: Optional secret code
        
    Returns:
        Tuple of (can_manage, error_message)
    """
    if member is None:
        return False, "Invalid member"
    
    # Check admin permissions
    if await has_admin_permissions(member):
        return True, ""
    
    # Check secret if provided
    if secret:
        is_valid, secret_error = await verify_secret(secret)
        if is_valid:
            return True, ""
    
    return False, "You need admin permissions or valid secret to manage auctions"


async def check_bot_permissions(channel: discord.TextChannel) -> Tuple[bool, List[str]]:
    """
    Check if bot has required permissions in a channel.
    
    Args:
        channel: Discord text channel
        
    Returns:
        Tuple of (has_all_permissions, list_of_missing_permissions)
    """
    if channel is None:
        return False, ["Invalid channel"]
    
    bot_member = channel.guild.me
    if bot_member is None:
        return False, ["Bot member not found"]
    
    permissions = channel.permissions_for(bot_member)
    missing = []
    
    # Check each required permission
    for perm_name in REQUIRED_BOT_PERMISSIONS:
        if not getattr(permissions, perm_name, False):
            # Convert snake_case to Title Case for display
            display_name = perm_name.replace("_", " ").title()
            missing.append(display_name)
    
    return len(missing) == 0, missing


async def get_auction_channels() -> List[int]:
    """
    Get list of configured auction channel IDs.
    
    Returns:
        List of channel IDs (integers)
    """
    channel_str = await database.get_setting("auction_channel_ids") or ""
    if not channel_str:
        return []
    
    channel_ids = []
    for ch_id in channel_str.split(","):
        ch_id = ch_id.strip()
        if ch_id:
            try:
                channel_ids.append(int(ch_id))
            except (ValueError, TypeError):
                if DEBUG_MODE:
                    print(f"WARNING: Invalid channel ID in config: {ch_id}")
                continue
    
    return channel_ids


async def validate_channel_for_auction(channel: discord.TextChannel) -> Tuple[bool, str]:
    """
    Validate if a channel can be used for auctions.
    Checks both configuration and bot permissions.
    
    Args:
        channel: Discord text channel
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if channel is None:
        return False, "Invalid channel"
    
    # Check if channel is configured
    auction_channels = await get_auction_channels()
    if auction_channels and channel.id not in auction_channels:
        return False, f"{channel.mention} is not configured as an auction channel"
    
    # Check bot permissions
    has_perms, missing = await check_bot_permissions(channel)
    if not has_perms:
        perms_list = ", ".join(missing)
        return False, f"Bot is missing permissions in {channel.mention}: {perms_list}"
    
    return True, ""


def is_bot_owner(user: discord.User) -> bool:
    """
    Check if user is the bot owner (for emergency commands).
    Currently not used, but kept for future features.
    
    Args:
        user: Discord user object
        
    Returns:
        True if owner, False otherwise
    """
    # Could be extended to check against env var BOT_OWNER_ID
    return False


async def rate_limit_check(user_id: int, action: str, limit: int = 10, 
                          window: int = 60) -> Tuple[bool, int]:
    """
    Check if user is rate limited for a specific action.
    Currently a placeholder for future implementation.
    
    Args:
        user_id: User ID to check
        action: Action name (e.g., "bid", "open_auction")
        limit: Maximum actions per window
        window: Time window in seconds
        
    Returns:
        Tuple of (is_allowed, remaining_count)
    """
    # TODO: Implement using Redis or in-memory cache
    # For now, always allow
    return True, limit


# ==================== PERMISSION DECORATORS ====================
# These could be used as decorators for commands in the future

def require_auction_role(func):
    """Decorator to require auction role for command execution."""
    async def wrapper(interaction: discord.Interaction, *args, **kwargs):
        has_role, error = await has_auction_role(interaction.user)
        if not has_role:
            await interaction.response.send_message(error, ephemeral=True)
            return
        return await func(interaction, *args, **kwargs)
    return wrapper


def require_admin(func):
    """Decorator to require admin permissions for command execution."""
    async def wrapper(interaction: discord.Interaction, *args, **kwargs):
        if not await has_admin_permissions(interaction.user):
            await interaction.response.send_message(
                "You need admin permissions to use this command",
                ephemeral=True
            )
            return
        return await func(interaction, *args, **kwargs)
    return wrapper
