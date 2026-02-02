# bot.py
"""
Main entrypoint for AuctionBot.
Handles Discord connection, command registration, and interaction routing.
Includes comprehensive error handling and debugging capabilities.

Version: 2.0 Enhanced
"""

import os
import sys
import traceback
import asyncio
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import time

# Load environment variables
load_dotenv()

# Get and sanitize bot token
_RAW_BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_TOKEN = _RAW_BOT_TOKEN.strip() if isinstance(_RAW_BOT_TOKEN, str) else ""

if not BOT_TOKEN:
    print("=" * 60)
    print("ERROR: BOT_TOKEN not set in environment")
    print("Please set BOT_TOKEN in your .env file")
    print("=" * 60)
    sys.exit(1)

# Validate token format
if any(c in _RAW_BOT_TOKEN for c in [" ", "\n", "\r", "\t"]):
    print("WARNING: BOT_TOKEN contained whitespace characters - they were stripped")
    print("Please ensure you copy the exact token from Discord Developer Portal")

print(f"INFO: Bot token loaded (length: {len(BOT_TOKEN)} characters)")

# Import project modules
import database
import security
import emojis
from auctions import (
    AuctionView, build_auction_embed, handle_bid, 
    end_current_auction, _post_or_update_panel,
    BidModal, cancel_auction_monitor
)
from bids import parse_amount, fmt_amount, validate_amount, BidParseError
from logs import log_error, log_command_usage, log_auction_start
from config import (
    DEFAULT_COMMISSION, DEFAULT_CURRENCY, DEFAULT_MIN_INCREMENT,
    DEFAULT_AUCTION_DURATION_MIN, DEFAULT_START_BID,
    COLOR_SUCCESS, COLOR_ERROR, COLOR_INFO, COLOR_WARNING,
    DEBUG_MODE, MIN_AUCTION_DURATION, MAX_AUCTION_DURATION
)

# Setup Discord intents
intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = False  # Not needed for slash commands
intents.members = True  # Needed for role checks

# Create bot instance
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Global state
_bot_ready = False
_startup_time = None


# ==================== HELPER FUNCTIONS ====================

async def safe_send_error(interaction: discord.Interaction, message: str):
    """Safely send error message to user."""
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except Exception as e:
        if DEBUG_MODE:
            print(f"Failed to send error message: {e}")


async def log_command(command_name: str, interaction: discord.Interaction, success: bool):
    """Log command usage if enabled."""
    try:
        await log_command_usage(bot, command_name, interaction.user, success)
    except Exception as e:
        if DEBUG_MODE:
            print(f"Failed to log command: {e}")


# ==================== EVENT HANDLERS ====================

@bot.event
async def on_ready():
    """Called when bot is fully connected and ready."""
    global _bot_ready, _startup_time
    
    print("=" * 60)
    print(f"Bot logged in as: {bot.user} (ID: {bot.user.id})")
    print("=" * 60)
    
    _startup_time = time.time()
    
    # Initialize database
    try:
        print("Initializing database...")
        await database.init_db()
        print("✓ Database initialized successfully")
    except Exception as e:
        print(f"✗ Database initialization failed: {e}")
        traceback.print_exc()
        # Continue anyway - bot might still work with fallback
    
    # Check and enforce server restriction
    try:
        server_id_str = await database.get_setting("server_id")
        if server_id_str:
            allowed_server_id = int(server_id_str)
            
            # Leave unauthorized guilds
            for guild in list(bot.guilds):
                if guild.id != allowed_server_id:
                    print(f"Leaving unauthorized guild: {guild.name} (ID: {guild.id})")
                    try:
                        await guild.leave()
                    except Exception as e:
                        print(f"Failed to leave guild {guild.id}: {e}")
            
            print(f"✓ Server restriction active: {allowed_server_id}")
        else:
            print("ℹ No server restriction configured")
    
    except Exception as e:
        print(f"Warning while checking server restriction: {e}")
    
    # Restore active auction panels
    try:
        active_auction = await database.get_active_auction()
        if active_auction:
            auction_id = active_auction['id']
            print(f"Found active auction: #{auction_id}")
            
            # Try to restore panel message
            panel_msg_id_str = await database.get_setting(f"panel_msg_{auction_id}")
            panel_ch_id_str = await database.get_setting(f"panel_channel_{auction_id}")
            
            if panel_ch_id_str and panel_msg_id_str:
                try:
                    channel = bot.get_channel(int(panel_ch_id_str))
                    if channel:
                        try:
                            msg = await channel.fetch_message(int(panel_msg_id_str))
                            # Update the existing message with current state
                            bids = await database.get_bids_for_auction(auction_id)
                            embed = await build_auction_embed(
                                active_auction,
                                top_bid=bids[0] if bids else None,
                                bids_count=len(bids)
                            )
                            view = AuctionView(auction_id)
                            await msg.edit(embed=embed, view=view)
                            print(f"✓ Restored auction panel message")
                        except discord.NotFound:
                            # Message deleted, create new one
                            await _post_or_update_panel(bot, active_auction)
                            print(f"✓ Created new auction panel message")
                    else:
                        print(f"⚠ Panel channel not found, will create new panel on first bid")
                except Exception as e:
                    print(f"Failed to restore auction panel: {e}")
            else:
                # No panel set yet, will be created on first bid
                print(f"ℹ No panel message set for active auction")
    
    except Exception as e:
        print(f"Warning while restoring auction: {e}")
    
    # Sync commands
    try:
        server_id_str = await database.get_setting("server_id")
        if server_id_str:
            guild_obj = discord.Object(id=int(server_id_str))
            synced = await tree.sync(guild=guild_obj)
            print(f"✓ Synced {len(synced)} commands to guild {server_id_str}")
        else:
            synced = await tree.sync()
            print(f"✓ Synced {len(synced)} commands globally")
    except Exception as e:
        print(f"✗ Failed to sync commands: {e}")
        traceback.print_exc()
    
    _bot_ready = True
    print("=" * 60)
    print("Bot is ready and operational!")
    print("=" * 60)


@bot.event
async def on_error(event, *args, **kwargs):
    """Handle bot errors."""
    print(f"Error in event {event}:")
    traceback.print_exc()


@bot.event
async def on_interaction(interaction: discord.Interaction):
    """
    Handle all interactions (buttons, modals, commands).
    Routes button clicks to appropriate handlers.
    """
    try:
        # Check if this is a component interaction (button/modal)
        if interaction.type == discord.InteractionType.component:
            data = getattr(interaction, "data", {}) or {}
            custom_id = data.get("custom_id", "")
            
            if custom_id.startswith("bid_"):
                # Parse custom_id: bid_TYPE_AUCTIONID
                parts = custom_id.split("_")
                if len(parts) >= 3:
                    bid_type = parts[1]
                    auction_id = int(parts[2])
                    
                    if bid_type == "1k":
                        await handle_bid(interaction, auction_id, increment=1_000)
                        return
                    elif bid_type == "100k":
                        await handle_bid(interaction, auction_id, increment=100_000)
                        return
                    elif bid_type == "500k":
                        await handle_bid(interaction, auction_id, increment=500_000)
                        return
                    elif bid_type == "custom":
                        # Show modal for custom amount
                        modal = BidModal(auction_id)
                        await interaction.response.send_modal(modal)
                        return
    
    except Exception as e:
        if DEBUG_MODE:
            print(f"Error handling interaction: {e}")
            traceback.print_exc()
        
        try:
            await safe_send_error(interaction, "حدث خطأ أثناء معالجة طلبك.")
        except Exception:
            pass


# ==================== CONFIGURATION COMMANDS ====================

@tree.command(
    name="config_set_server",
    description="تعيين السيرفر المسموح لتشغيل البوت (Restrict bot to this server)"
)
@app_commands.describe(secret="Secret code (optional for exclusive actions)")
async def config_set_server(interaction: discord.Interaction, secret: str = ""):
    """Set allowed server for bot operation."""
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Execute this command in the server you want to allow.",
            ephemeral=True
        )
        return
    
    # Check permissions
    current_secret = await database.get_setting("secret_code") or ""
    has_permission = (
        interaction.user.guild_permissions.manage_guild or
        (secret and secret == current_secret)
    )
    
    if not has_permission:
        await interaction.response.send_message(
            "❌ You need Manage Server permission or the correct secret code.",
            ephemeral=True
        )
        return
    
    try:
        # Set server
        await database.set_setting("server_id", str(interaction.guild.id))
        await database.set_setting("guild_name", interaction.guild.name)
        
        # Sync commands to this guild
        try:
            await tree.sync(guild=interaction.guild)
        except Exception as e:
            if DEBUG_MODE:
                print(f"Failed to sync after setting server: {e}")
        
        await interaction.response.send_message(
            f"✅ تم تعيين السيرفر المسموح: **{interaction.guild.name}**\n"
            f"Guild ID: `{interaction.guild.id}`",
            ephemeral=True
        )
        await log_command("config_set_server", interaction, True)
    
    except Exception as e:
        await safe_send_error(interaction, f"❌ Error: {str(e)}")
        await log_command("config_set_server", interaction, False)


@tree.command(
    name="config_set_role",
    description="تعيين رتبة 'رواد المزاد' (Set role for auction participation)"
)
@app_commands.describe(role="Role that can participate in auctions")
async def config_set_role(interaction: discord.Interaction, role: discord.Role):
    """Set auction participant role."""
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Execute this command in the server.",
            ephemeral=True
        )
        return
    
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message(
            "❌ You need Manage Roles permission.",
            ephemeral=True
        )
        return
    
    try:
        await database.set_setting("role_id", str(role.id))
        await interaction.response.send_message(
            f"✅ تم تعيين رتبة الرواد: {role.mention}\n"
            f"Role ID: `{role.id}`",
            ephemeral=True
        )
        await log_command("config_set_role", interaction, True)
    
    except Exception as e:
        await safe_send_error(interaction, f"❌ Error: {str(e)}")
        await log_command("config_set_role", interaction, False)


@tree.command(
    name="config_set_channels",
    description="تعيين قنوات المزاد واللوق (Set auction and log channels)"
)
@app_commands.describe(
    auction_channel="Channel for auction panel",
    log_channel="Channel for logs"
)
async def config_set_channels(
    interaction: discord.Interaction,
    auction_channel: discord.TextChannel,
    log_channel: discord.TextChannel
):
    """Set auction and log channels."""
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Execute this command in the server.",
            ephemeral=True
        )
        return
    
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message(
            "❌ You need Manage Channels permission.",
            ephemeral=True
        )
        return
    
    try:
        # Check bot permissions in auction channel
        has_perms, missing = await security.check_bot_permissions(auction_channel)
        if not has_perms:
            await interaction.response.send_message(
                f"⚠️ Warning: Bot is missing permissions in {auction_channel.mention}:\n"
                f"- {', '.join(missing)}\n\n"
                f"Please grant these permissions before opening auctions.",
                ephemeral=True
            )
            # Continue anyway - let admin fix permissions
        
        # Set channels
        await database.set_setting("auction_channel_ids", str(auction_channel.id))
        await database.set_setting("log_channel_id", str(log_channel.id))
        
        await interaction.response.send_message(
            f"✅ Channels configured:\n"
            f"🎯 Auction: {auction_channel.mention}\n"
            f"📋 Log: {log_channel.mention}",
            ephemeral=True
        )
        await log_command("config_set_channels", interaction, True)
    
    except Exception as e:
        await safe_send_error(interaction, f"❌ Error: {str(e)}")
        await log_command("config_set_channels", interaction, False)


@tree.command(
    name="config_set_secret",
    description="تعيين الرمز السري (Set secret code for admin actions)"
)
@app_commands.describe(secret="Secret code string")
async def config_set_secret(interaction: discord.Interaction, secret: str):
    """Set secret code."""
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Run in server.",
            ephemeral=True
        )
        return
    
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(
            "❌ You need Manage Server permission.",
            ephemeral=True
        )
        return
    
    try:
        await database.set_setting("secret_code", secret)
        await interaction.response.send_message(
            "✅ Secret code updated successfully.",
            ephemeral=True
        )
        await log_command("config_set_secret", interaction, True)
    
    except Exception as e:
        await safe_send_error(interaction, f"❌ Error: {str(e)}")
        await log_command("config_set_secret", interaction, False)


@tree.command(
    name="config_set_misc",
    description="تعيين العمولة واسم العملة (Set commission and currency)"
)
@app_commands.describe(
    commission="Commission percent (e.g. 20 for 20%)",
    currency="Currency name (e.g. Credits)"
)
async def config_set_misc(
    interaction: discord.Interaction,
    commission: int,
    currency: str
):
    """Set commission and currency."""
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Run in server.",
            ephemeral=True
        )
        return
    
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(
            "❌ You need Manage Server permission.",
            ephemeral=True
        )
        return
    
    # Validate commission
    if commission < 0 or commission > 100:
        await interaction.response.send_message(
            "❌ Commission must be between 0 and 100.",
            ephemeral=True
        )
        return
    
    try:
        await database.set_setting("commission", str(commission))
        await database.set_setting("currency_name", currency)
        
        await interaction.response.send_message(
            f"✅ Configuration updated:\n"
            f"💰 Commission: {commission}%\n"
            f"🪙 Currency: {currency}",
            ephemeral=True
        )
        await log_command("config_set_misc", interaction, True)
    
    except Exception as e:
        await safe_send_error(interaction, f"❌ Error: {str(e)}")
        await log_command("config_set_misc", interaction, False)


@tree.command(
    name="config_show",
    description="عرض إعدادات البوت الحالية (Show current bot configuration)"
)
async def config_show(interaction: discord.Interaction):
    """Show current configuration."""
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Run in server.",
            ephemeral=True
        )
        return
    
    try:
        settings = await database.all_settings()
        
        if not settings:
            await interaction.response.send_message(
                "ℹ️ No settings configured yet.",
                ephemeral=True
            )
            return
        
        # Filter out sensitive/internal settings
        display_settings = {
            k: v for k, v in settings.items()
            if not k.startswith(("panel_", "last_bid_", "promo_", "secret_", "emoji_"))
        }
        
        embed = discord.Embed(
            title="⚙️ Bot Configuration",
            color=COLOR_INFO,
            timestamp=discord.utils.utcnow()
        )
        
        for key, value in sorted(display_settings.items()):
            # Truncate long values
            display_value = value if len(value) < 100 else value[:97] + "..."
            embed.add_field(name=key, value=f"`{display_value}`", inline=False)
        
        embed.set_footer(text=f"Total settings: {len(display_settings)}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    except Exception as e:
        await safe_send_error(interaction, f"❌ Error: {str(e)}")


# ==================== EMOJI COMMANDS ====================

@tree.command(
    name="emoji_set",
    description="Set a custom emoji (server emoji or unicode)"
)
@app_commands.describe(
    name="Emoji key name (e.g. fire, celebrate)",
    emoji="Emoji string (<:name:id> or unicode like 🔥)"
)
async def emoji_set(interaction: discord.Interaction, name: str, emoji: str):
    """Set custom emoji."""
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Run in server.",
            ephemeral=True
        )
        return
    
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(
            "❌ You need Manage Server permission.",
            ephemeral=True
        )
        return
    
    try:
        await emojis.set_emoji(name, emoji)
        await interaction.response.send_message(
            f"✅ Emoji set: `{name}` → {emoji}",
            ephemeral=True
        )
        await log_command("emoji_set", interaction, True)
    
    except ValueError as e:
        await safe_send_error(interaction, f"❌ {str(e)}")
        await log_command("emoji_set", interaction, False)
    
    except Exception as e:
        await safe_send_error(interaction, f"❌ Error: {str(e)}")
        await log_command("emoji_set", interaction, False)


@tree.command(
    name="emoji_list",
    description="List all configured emojis"
)
async def emoji_list(interaction: discord.Interaction):
    """List all emojis."""
    try:
        emoji_map = await emojis.list_emojis()
        
        if not emoji_map:
            await interaction.response.send_message(
                "ℹ️ No emojis configured.",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title="📝 Emoji Configuration",
            color=COLOR_INFO,
            timestamp=discord.utils.utcnow()
        )
        
        lines = [f"**{k}**: {v}" for k, v in sorted(emoji_map.items())]
        
        # Split into chunks if too long
        chunk_size = 20
        for i in range(0, len(lines), chunk_size):
            chunk = lines[i:i + chunk_size]
            embed.add_field(
                name=f"Emojis ({i+1}-{min(i+chunk_size, len(lines))})",
                value="\n".join(chunk),
                inline=False
            )
        
        embed.set_footer(text=f"Total: {len(emoji_map)} emojis")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    except Exception as e:
        await safe_send_error(interaction, f"❌ Error: {str(e)}")


# ==================== AUCTION MANAGEMENT COMMANDS ====================

@tree.command(
    name="auction_open",
    description="فتح مزاد جديد (Open new auction)"
)
@app_commands.describe(
    start_bid="Starting bid amount (e.g. 250k, 2.5m)",
    min_increment="Minimum bid increment (e.g. 50k)",
    duration_minutes="Auction duration in minutes",
    secret="Secret code (optional)"
)
async def auction_open(
    interaction: discord.Interaction,
    start_bid: str,
    min_increment: str,
    duration_minutes: int = DEFAULT_AUCTION_DURATION_MIN,
    secret: str = ""
):
    """Open a new auction."""
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Run in server.",
            ephemeral=True
        )
        return
    
    # Check guild restriction
    if not await security.is_allowed_guild(interaction.guild):
        await interaction.response.send_message(
            "❌ This bot is restricted to a specific server.",
            ephemeral=True
        )
        return
    
    # Check permission
    can_open, error_msg = await security.can_open_auction(interaction.user, secret)
    if not can_open:
        await interaction.response.send_message(
            f"❌ {error_msg}",
            ephemeral=True
        )
        return
    
    # Check for existing active auction
    active = await database.get_active_auction()
    if active:
        await interaction.response.send_message(
            f"❌ يوجد بالفعل مزاد نشط (Auction #{active['id']}).",
            ephemeral=True
        )
        return
    
    # Validate duration
    if duration_minutes < MIN_AUCTION_DURATION:
        await interaction.response.send_message(
            f"❌ Duration must be at least {MIN_AUCTION_DURATION} minute(s).",
            ephemeral=True
        )
        return
    
    if duration_minutes > MAX_AUCTION_DURATION:
        await interaction.response.send_message(
            f"❌ Duration cannot exceed {MAX_AUCTION_DURATION} minutes (24 hours).",
            ephemeral=True
        )
        return
    
    # Parse amounts
    try:
        sb = parse_amount(start_bid)
        mi = parse_amount(min_increment)
    except BidParseError as e:
        await interaction.response.send_message(
            f"❌ Invalid format: {str(e)}",
            ephemeral=True
        )
        return
    
    # Validate amounts
    is_valid_sb, error_sb = validate_amount(sb)
    if not is_valid_sb:
        await interaction.response.send_message(
            f"❌ Starting bid error: {error_sb}",
            ephemeral=True
        )
        return
    
    is_valid_mi, error_mi = validate_amount(mi)
    if not is_valid_mi:
        await interaction.response.send_message(
            f"❌ Min increment error: {error_mi}",
            ephemeral=True
        )
        return
    
    # Defer response as this might take time
    await interaction.response.defer(ephemeral=True)
    
    try:
        # Create auction
        ends_at = int(time.time() + duration_minutes * 60)
        auction = await database.create_auction(
            interaction.user.id,
            sb,
            mi,
            ends_at
        )
        
        auction_id = auction["id"]
        
        if DEBUG_MODE:
            print(f"Created auction {auction_id}")
        
        # Get auction channel
        channels_str = await database.get_setting("auction_channel_ids") or ""
        channel_ids = [s.strip() for s in channels_str.split(",") if s.strip()]
        
        if not channel_ids:
            await interaction.followup.send(
                "⚠️ Auction created but no auction channel configured!\n"
                f"Use `/config_set_channels` to set one.",
                ephemeral=True
            )
            return
        
        # Get first channel
        channel = None
        for cid_str in channel_ids:
            try:
                channel = bot.get_channel(int(cid_str))
                if channel:
                    break
            except (ValueError, TypeError):
                continue
        
        if not channel:
            await interaction.followup.send(
                "❌ Auction created but configured channel not found!",
                ephemeral=True
            )
            return
        
        # Check bot permissions
        has_perms, missing = await security.check_bot_permissions(channel)
        if not has_perms:
            await interaction.followup.send(
                f"❌ Bot is missing permissions in {channel.mention}:\n"
                f"- {', '.join(missing)}\n\n"
                f"Please grant these permissions and try `/auction_open` again.",
                ephemeral=True
            )
            # Cancel the auction
            await database.end_auction(auction_id, 0, None)
            return
        
        # Post panel
        msg = await _post_or_update_panel(bot, auction)
        
        if not msg:
            await interaction.followup.send(
                "⚠️ Auction created but failed to post panel message.",
                ephemeral=True
            )
            return
        
        # Log auction start
        try:
            await log_auction_start(bot, auction)
        except Exception as e:
            if DEBUG_MODE:
                print(f"Failed to log auction start: {e}")
        
        # Send success message
        currency = await database.get_setting("currency_name") or DEFAULT_CURRENCY
        await interaction.followup.send(
            f"✅ **Auction opened successfully!**\n\n"
            f"🎯 Auction ID: `{auction_id}`\n"
            f"💰 Starting Bid: **{fmt_amount(sb)} {currency}**\n"
            f"📈 Min Increment: **{fmt_amount(mi)} {currency}**\n"
            f"⏱️ Duration: **{duration_minutes} minutes**\n"
            f"📍 Channel: {channel.mention}",
            ephemeral=True
        )
        
        await log_command("auction_open", interaction, True)
    
    except Exception as e:
        if DEBUG_MODE:
            print(f"Error in auction_open: {e}")
            traceback.print_exc()
        
        await interaction.followup.send(
            f"❌ Error opening auction: {str(e)}",
            ephemeral=True
        )
        await log_command("auction_open", interaction, False)


@tree.command(
    name="auction_end",
    description="إنهاء المزاد الحالي (End current auction)"
)
async def auction_end(interaction: discord.Interaction):
    """Manually end current auction."""
    # Check permission
    can_manage, error_msg = await security.can_manage_auction(interaction.user)
    if not can_manage:
        await interaction.response.send_message(
            f"❌ {error_msg}",
            ephemeral=True
        )
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        result = await end_current_auction(bot)
        
        if result is None:
            await interaction.followup.send(
                "ℹ️ No active auction to end.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "✅ Auction ended and logged successfully.",
                ephemeral=True
            )
            await log_command("auction_end", interaction, True)
    
    except Exception as e:
        await interaction.followup.send(
            f"❌ Error ending auction: {str(e)}",
            ephemeral=True
        )
        await log_command("auction_end", interaction, False)


@tree.command(
    name="auction_undo_last",
    description="حذف آخر مزايدة (Remove last bid - admin only)"
)
async def auction_undo_last(interaction: discord.Interaction):
    """Undo last bid."""
    # Check permission
    can_manage, error_msg = await security.can_manage_auction(interaction.user)
    if not can_manage:
        await interaction.response.send_message(
            f"❌ {error_msg}",
            ephemeral=True
        )
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        active = await database.get_active_auction()
        if not active:
            await interaction.followup.send(
                "❌ No active auction.",
                ephemeral=True
            )
            return
        
        auction_id = active["id"]
        
        # Undo last bid
        undone = await database.undo_last_bid(auction_id)
        
        if undone:
            # Update panel
            await asyncio.sleep(PANEL_UPDATE_DELAY)
            await _post_or_update_panel(bot, active)
            
            currency = await database.get_setting("currency_name") or DEFAULT_CURRENCY
            await interaction.followup.send(
                f"✅ Last bid removed:\n"
                f"User: <@{undone['user_id']}>\n"
                f"Amount: {fmt_amount(undone['amount'])} {currency}",
                ephemeral=True
            )
            await log_command("auction_undo_last", interaction, True)
        else:
            await interaction.followup.send(
                "ℹ️ No bids to remove.",
                ephemeral=True
            )
    
    except Exception as e:
        await interaction.followup.send(
            f"❌ Error: {str(e)}",
            ephemeral=True
        )
        await log_command("auction_undo_last", interaction, False)


# ==================== DEBUG COMMANDS ====================

@tree.command(
    name="debug_status",
    description="Show bot status and diagnostics (admin only)"
)
async def debug_status(interaction: discord.Interaction):
    """Show bot status."""
    if not await security.has_admin_permissions(interaction.user):
        await interaction.response.send_message(
            "❌ Admin only command.",
            ephemeral=True
        )
        return
    
    try:
        # Get database status
        db_status = await database.get_connection_status()
        
        # Get active auction
        active_auction = await database.get_active_auction()
        
        # Calculate uptime
        uptime_seconds = int(time.time() - _startup_time) if _startup_time else 0
        uptime_minutes = uptime_seconds // 60
        uptime_hours = uptime_minutes // 60
        
        embed = discord.Embed(
            title="🔧 Bot Status & Diagnostics",
            color=COLOR_INFO,
            timestamp=discord.utils.utcnow()
        )
        
        # Bot info
        embed.add_field(
            name="Bot Status",
            value=f"✅ Online\nUptime: {uptime_hours}h {uptime_minutes % 60}m",
            inline=True
        )
        
        # Database info
        db_type = "PostgreSQL" if not db_status["using_local"] else "SQLite (Local)"
        db_emoji = "🟢" if not db_status["using_local"] else "🟡"
        embed.add_field(
            name="Database",
            value=f"{db_emoji} {db_type}\nURL Configured: {db_status['database_url_configured']}",
            inline=True
        )
        
        # Guild info
        guilds_count = len(bot.guilds)
        embed.add_field(
            name="Guilds",
            value=f"{guilds_count} server(s)",
            inline=True
        )
        
        # Active auction info
        if active_auction:
            auction_id = active_auction['id']
            bids = await database.get_bids_for_auction(auction_id)
            embed.add_field(
                name="Active Auction",
                value=f"ID: {auction_id}\nBids: {len(bids)}\nStatus: {active_auction['status']}",
                inline=False
            )
        else:
            embed.add_field(
                name="Active Auction",
                value="None",
                inline=False
            )
        
        # Configuration
        server_id = await database.get_setting("server_id")
        role_id = await database.get_setting("role_id")
        channels = await database.get_setting("auction_channel_ids")
        
        config_status = "✅" if all([server_id, role_id, channels]) else "⚠️"
        embed.add_field(
            name="Configuration",
            value=f"{config_status} Server: {server_id or 'Not set'}\nRole: {role_id or 'Not set'}\nChannels: {'Set' if channels else 'Not set'}",
            inline=False
        )
        
        embed.set_footer(text=f"Debug Mode: {'ON' if DEBUG_MODE else 'OFF'}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    except Exception as e:
        await safe_send_error(interaction, f"❌ Error: {str(e)}")


@tree.command(
    name="debug_auction",
    description="Show detailed info about active auction (admin only)"
)
async def debug_auction(interaction: discord.Interaction):
    """Show detailed auction info."""
    if not await security.has_admin_permissions(interaction.user):
        await interaction.response.send_message(
            "❌ Admin only command.",
            ephemeral=True
        )
        return
    
    try:
        active = await database.get_active_auction()
        
        if not active:
            await interaction.response.send_message(
                "ℹ️ No active auction.",
                ephemeral=True
            )
            return
        
        auction_id = active['id']
        bids = await database.get_bids_for_auction(auction_id)
        currency = await database.get_setting("currency_name") or DEFAULT_CURRENCY
        
        embed = discord.Embed(
            title=f"🎯 Auction #{auction_id} - Debug Info",
            color=COLOR_INFO,
            timestamp=discord.utils.utcnow()
        )
        
        # Basic info
        embed.add_field(
            name="Status",
            value=active['status'],
            inline=True
        )
        
        embed.add_field(
            name="Started By",
            value=f"<@{active['started_by']}>",
            inline=True
        )
        
        embed.add_field(
            name="Start Bid",
            value=f"{fmt_amount(active['start_bid'])} {currency}",
            inline=True
        )
        
        embed.add_field(
            name="Min Increment",
            value=f"{fmt_amount(active['min_increment'])} {currency}",
            inline=True
        )
        
        # Timing
        started_at = active['started_at']
        ends_at = active['ends_at']
        now = int(time.time())
        
        duration = ends_at - started_at
        elapsed = now - started_at
        remaining = max(0, ends_at - now)
        
        embed.add_field(
            name="Timing",
            value=f"Duration: {duration // 60}m\nElapsed: {elapsed // 60}m\nRemaining: {remaining // 60}m",
            inline=True
        )
        
        # Bids info
        top_bid = bids[0] if bids else None
        unique_bidders = len(set(b['user_id'] for b in bids)) if bids else 0
        
        embed.add_field(
            name="Bids",
            value=f"Total: {len(bids)}\nUnique Bidders: {unique_bidders}",
            inline=True
        )
        
        if top_bid:
            embed.add_field(
                name="Highest Bid",
                value=f"<@{top_bid['user_id']}>\n{fmt_amount(top_bid['amount'])} {currency}",
                inline=False
            )
        
        # Panel info
        panel_ch = await database.get_setting(f"panel_channel_{auction_id}")
        panel_msg = await database.get_setting(f"panel_msg_{auction_id}")
        
        embed.add_field(
            name="Panel",
            value=f"Channel: {panel_ch or 'Not set'}\nMessage: {panel_msg or 'Not set'}",
            inline=False
        )
        
        # Last bid timestamp
        last_bid_ts = await database.get_setting(f"last_bid_ts_{auction_id}")
        if last_bid_ts:
            last_bid_time = int(time.time() - float(last_bid_ts))
            embed.add_field(
                name="Last Activity",
                value=f"{last_bid_time}s ago",
                inline=True
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    except Exception as e:
        await safe_send_error(interaction, f"❌ Error: {str(e)}")


@tree.command(
    name="db_retry",
    description="Retry PostgreSQL connection (admin only)"
)
async def db_retry(interaction: discord.Interaction):
    """Retry database connection."""
    if not await security.has_admin_permissions(interaction.user):
        await interaction.response.send_message(
            "❌ Admin only command.",
            ephemeral=True
        )
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        success = await database.retry_postgres_connection()
        
        if success:
            await interaction.followup.send(
                "✅ Successfully connected to PostgreSQL!",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "⚠️ PostgreSQL connection failed, using local SQLite.",
                ephemeral=True
            )
    
    except Exception as e:
        await interaction.followup.send(
            f"❌ Error: {str(e)}",
            ephemeral=True
        )


# ==================== RUN BOT ====================

if __name__ == "__main__":
    try:
        print("Starting AuctionBot...")
        print(f"Debug Mode: {'ON' if DEBUG_MODE else 'OFF'}")
        bot.run(BOT_TOKEN)
    
    except discord.LoginFailure:
        print("=" * 60)
        print("ERROR: Invalid bot token")
        print("Please check your BOT_TOKEN in the .env file")
        print("=" * 60)
        sys.exit(1)
    
    except Exception as e:
        print("=" * 60)
        print(f"FATAL ERROR: Bot failed to start")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {str(e)}")
        print("=" * 60)
        traceback.print_exc()
        sys.exit(1)
