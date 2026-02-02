# auctions.py
"""
Auction management module.
Handles auction panel, bidding logic, monitoring, and finalization.
Includes automatic countdown system and promotional messages.
"""

import discord
from discord.ui import View, Button, Modal, TextInput
import database
import security
import emojis
from bids import parse_amount, fmt_amount, validate_amount, BidParseError
from config import (
    DEFAULT_MIN_INCREMENT, COOLDOWN_SECONDS, COUNTDOWN_SECONDS,
    INACTIVITY_THRESHOLD, PROMO_MIN_INTERVAL, DEFAULT_CURRENCY,
    COLOR_AUCTION_ACTIVE, ENABLE_PROMO_MESSAGES, ENABLE_COUNTDOWN_MESSAGES,
    DEBUG_MODE, PANEL_UPDATE_DELAY
)
from logs import log_auction_end, log_error
import asyncio
import time
import random
import traceback
from typing import Optional, Dict, Any, List

# ==================== GLOBAL STATE ====================
# In-memory trackers for cooldowns and monitors
USER_COOLDOWNS: Dict[int, float] = {}
AUCTION_MONITORS: Dict[int, asyncio.Task] = {}

# ==================== PROMO TEMPLATES ====================
# Arabic promotional messages with emoji placeholders
PROMO_TEMPLATES = [
    "{fire} **زيد أكثر وولعها!** {mention} دفع **{amount}**! مين يكسر الرقم؟",
    "{spark} يا ليل يا عين! {mention} رافع السعر لـ **{amount}** — حان وقت البطل الجاي! {fire}",
    "{trophy} المزاد شغال، من هو البطل التالي؟ {mention} دفعة **{amount}** — ورّنا همتك!",
    "{celebrate} حدّث التحدّي: {mention} دافع **{amount}** — تقدر تكسرها؟",
    "{alarm} 📢 إعلان: {mention} وصل للسعر **{amount}** — مين عنده الجرأة؟",
    "{rocket} {mention} طلع بقوة! **{amount}** — مين الجاي؟",
    "{crown} {mention} متصدر بـ **{amount}**! تحدّاه! {fire}",
]


# ==================== EMBED BUILDER ====================

async def build_auction_embed(
    auction: Dict[str, Any],
    top_bid: Optional[Dict[str, Any]] = None,
    bids_count: int = 0,
    countdown: Optional[int] = None
) -> discord.Embed:
    """
    Build the auction panel embed with current state.
    
    Args:
        auction: Auction data dictionary
        top_bid: Highest bid dictionary (optional)
        bids_count: Total number of bids
        countdown: Countdown seconds (optional)
        
    Returns:
        Discord Embed object
    """
    # Get currency name
    currency_name = await database.get_setting("currency_name") or DEFAULT_CURRENCY
    
    # Get emojis
    trophy_emoji = await emojis.get_emoji("trophy", "🎯")
    money_emoji = await emojis.get_emoji("money", "💰")
    chart_emoji = await emojis.get_emoji("chart", "📊")
    alarm_emoji = await emojis.get_emoji("alarm", "⏳")
    
    # Determine highest bid
    highest = top_bid['amount'] if top_bid else auction.get("start_bid", 0)
    highest_user = top_bid['user_id'] if top_bid else None
    
    # Create embed
    embed = discord.Embed(
        title=f"{trophy_emoji} Auction Panel - #{auction.get('id')}",
        color=COLOR_AUCTION_ACTIVE,
        timestamp=discord.utils.utcnow()
    )
    
    # Status field
    status = auction.get("status", "UNKNOWN")
    status_emoji = "🟢" if status == "OPEN" else "🔴"
    embed.add_field(
        name="Status",
        value=f"{status_emoji} {status}",
        inline=True
    )
    
    # Highest bid field
    embed.add_field(
        name=f"{money_emoji} Highest Bid",
        value=f"**{fmt_amount(highest)} {currency_name}**",
        inline=True
    )
    
    # Bids count field
    embed.add_field(
        name=f"{chart_emoji} Total Bids",
        value=f"**{bids_count}**",
        inline=True
    )
    
    # Time left field
    time_left = max(0, int(auction.get("ends_at", 0) - time.time()))
    minutes = time_left // 60
    seconds = time_left % 60
    embed.add_field(
        name=f"{alarm_emoji} Time Left",
        value=f"**{minutes}m {seconds}s**",
        inline=True
    )
    
    # Countdown field (if active)
    if countdown is not None and countdown > 0:
        embed.add_field(
            name="⏱️ Countdown",
            value=f"**{countdown}s**",
            inline=True
        )
    
    # Min increment info
    min_inc = auction.get("min_increment", DEFAULT_MIN_INCREMENT)
    embed.add_field(
        name="Min Increment",
        value=f"{fmt_amount(min_inc)} {currency_name}",
        inline=True
    )
    
    # Footer with highest bidder
    if highest_user:
        crown_emoji = await emojis.get_emoji("crown", "👑")
        embed.set_footer(text=f"{crown_emoji} Highest: User ID {highest_user}")
    else:
        embed.set_footer(text=f"Starting bid: {fmt_amount(auction.get('start_bid', 0))} {currency_name}")
    
    return embed


# ==================== MODAL (Custom Bid) ====================

class BidModal(Modal, title="Place Custom Bid"):
    """Modal for entering custom bid amount."""
    
    amount = TextInput(
        label="Amount (e.g., 250k, 2.5m, 1000000)",
        placeholder="Enter amount: 250k",
        required=True,
        min_length=1,
        max_length=20
    )
    
    def __init__(self, auction_id: int):
        super().__init__()
        self.auction_id = auction_id
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission."""
        try:
            # Parse amount
            amt = parse_amount(self.amount.value)
            
            # Validate
            is_valid, error = validate_amount(amt)
            if not is_valid:
                await interaction.response.send_message(
                    f"❌ {error}",
                    ephemeral=True
                )
                return
            
            # Handle the bid
            await handle_bid(interaction, self.auction_id, amount=amt)
        
        except BidParseError as e:
            await interaction.response.send_message(
                f"❌ {str(e)}",
                ephemeral=True
            )
        except Exception as e:
            if DEBUG_MODE:
                print(f"Error in BidModal: {e}")
                traceback.print_exc()
            await interaction.response.send_message(
                "❌ An error occurred processing your bid.",
                ephemeral=True
            )


# ==================== VIEW (Buttons) ====================

class AuctionView(View):
    """Persistent view with auction bid buttons."""
    
    def __init__(self, auction_id: int):
        super().__init__(timeout=None)
        self.auction_id = auction_id
        
        # Add buttons
        self.add_item(Button(
            label="+1K",
            custom_id=f"bid_1k_{auction_id}",
            style=discord.ButtonStyle.primary
        ))
        self.add_item(Button(
            label="+100K",
            custom_id=f"bid_100k_{auction_id}",
            style=discord.ButtonStyle.primary
        ))
        self.add_item(Button(
            label="+500K",
            custom_id=f"bid_500k_{auction_id}",
            style=discord.ButtonStyle.primary
        ))
        self.add_item(Button(
            label="Custom",
            custom_id=f"bid_custom_{auction_id}",
            style=discord.ButtonStyle.secondary,
            emoji="✏️"
        ))


# ==================== PANEL MESSAGE MANAGEMENT ====================

async def _get_panel_message(
    bot_client: discord.Client,
    auction_id: int
) -> Optional[discord.Message]:
    """
    Retrieve the panel message for an auction.
    
    Args:
        bot_client: Discord client
        auction_id: Auction ID
        
    Returns:
        Message object or None if not found
    """
    ch_id_str = await database.get_setting(f"panel_channel_{auction_id}")
    msg_id_str = await database.get_setting(f"panel_msg_{auction_id}")
    
    if not ch_id_str or not msg_id_str:
        return None
    
    try:
        ch_id = int(ch_id_str)
        msg_id = int(msg_id_str)
        
        channel = bot_client.get_channel(ch_id)
        if not channel:
            if DEBUG_MODE:
                print(f"Panel channel {ch_id} not found")
            return None
        
        message = await channel.fetch_message(msg_id)
        return message
    
    except (ValueError, TypeError, discord.NotFound, discord.Forbidden) as e:
        if DEBUG_MODE:
            print(f"Failed to get panel message: {e}")
        return None


async def _post_or_update_panel(
    bot_client: discord.Client,
    auction: Dict[str, Any],
    countdown: Optional[int] = None
) -> Optional[discord.Message]:
    """
    Create or update the auction panel message.
    
    Args:
        bot_client: Discord client
        auction: Auction data dictionary
        countdown: Optional countdown seconds to display
        
    Returns:
        Message object or None if failed
    """
    auction_id = auction["id"]
    
    try:
        # Get bids
        bids = await database.get_bids_for_auction(auction_id)
        top_bid = bids[0] if bids else None
        bids_count = len(bids)
        
        # Build embed
        embed = await build_auction_embed(
            auction,
            top_bid=top_bid,
            bids_count=bids_count,
            countdown=countdown
        )
        
        # Build view
        view = AuctionView(auction_id)
        
        # Get channel
        ch_id_str = await database.get_setting(f"panel_channel_{auction_id}")
        channel = None
        
        if ch_id_str:
            try:
                channel = bot_client.get_channel(int(ch_id_str))
            except (ValueError, TypeError):
                pass
        
        # If no channel set, use first auction channel
        if not channel:
            channels_str = await database.get_setting("auction_channel_ids") or ""
            channel_ids = [s.strip() for s in channels_str.split(",") if s.strip()]
            
            for cid_str in channel_ids:
                try:
                    channel = bot_client.get_channel(int(cid_str))
                    if channel:
                        break
                except (ValueError, TypeError):
                    continue
        
        if not channel:
            if DEBUG_MODE:
                print("No channel available for auction panel")
            return None
        
        # Check bot permissions
        has_perms, missing = await security.check_bot_permissions(channel)
        if not has_perms:
            if DEBUG_MODE:
                print(f"Missing permissions in {channel.id}: {missing}")
            await log_error(
                bot_client,
                f"Missing permissions in auction channel: {', '.join(missing)}",
                f"Channel: {channel.mention}"
            )
            return None
        
        # Try to update existing message
        msg = await _get_panel_message(bot_client, auction_id)
        
        if msg:
            try:
                await msg.edit(embed=embed, view=view)
                return msg
            except (discord.NotFound, discord.Forbidden) as e:
                if DEBUG_MODE:
                    print(f"Failed to edit panel message: {e}")
                # Message deleted or no permission, create new one below
        
        # Create new message
        try:
            new_msg = await channel.send(embed=embed, view=view)
            await database.set_setting(f"panel_msg_{auction_id}", str(new_msg.id))
            await database.set_setting(f"panel_channel_{auction_id}", str(channel.id))
            return new_msg
        except discord.Forbidden as e:
            if DEBUG_MODE:
                print(f"No permission to send panel: {e}")
            await log_error(
                bot_client,
                "No permission to send auction panel",
                f"Channel: {channel.mention}"
            )
            return None
    
    except Exception as e:
        if DEBUG_MODE:
            print(f"Error in _post_or_update_panel: {e}")
            traceback.print_exc()
        return None


# ==================== PROMOTIONAL MESSAGES ====================

async def _send_promo_if_needed(
    bot_client: discord.Client,
    auction: Dict[str, Any]
):
    """
    Send promotional message if enough time has passed.
    
    Args:
        bot_client: Discord client
        auction: Auction data dictionary
    """
    if not ENABLE_PROMO_MESSAGES:
        return
    
    auction_id = auction["id"]
    
    # Check last promo time
    last_promo_str = await database.get_setting(f"promo_ts_{auction_id}")
    last_promo_ts = float(last_promo_str) if last_promo_str else 0
    now = time.time()
    
    if now - last_promo_ts < PROMO_MIN_INTERVAL:
        return  # Too soon
    
    try:
        # Get bids and currency
        bids = await database.get_bids_for_auction(auction_id)
        top_bid = bids[0] if bids else None
        currency = await database.get_setting("currency_name") or DEFAULT_CURRENCY
        
        # Format amount and mention
        amount_text = fmt_amount(top_bid["amount"]) if top_bid else fmt_amount(auction["start_bid"])
        mention = f"<@{top_bid['user_id']}>" if top_bid else "@here"
        
        # Choose random template
        template = random.choice(PROMO_TEMPLATES)
        
        # Get emojis
        fire_e = await emojis.get_emoji("fire", "🔥")
        spark_e = await emojis.get_emoji("spark", "✨")
        trophy_e = await emojis.get_emoji("trophy", "🏆")
        celebrate_e = await emojis.get_emoji("celebrate", "🎉")
        alarm_e = await emojis.get_emoji("alarm", "⏳")
        rocket_e = await emojis.get_emoji("rocket", "🚀")
        crown_e = await emojis.get_emoji("crown", "👑")
        
        # Format message
        message = template.format(
            fire=fire_e,
            spark=spark_e,
            trophy=trophy_e,
            celebrate=celebrate_e,
            alarm=alarm_e,
            rocket=rocket_e,
            crown=crown_e,
            mention=mention,
            amount=f"{amount_text} {currency}"
        )
        
        # Get channel
        ch_id_str = await database.get_setting(f"panel_channel_{auction_id}")
        if not ch_id_str:
            return
        
        channel = bot_client.get_channel(int(ch_id_str))
        if not channel:
            return
        
        # Send promo
        await channel.send(message)
        
        # Update last promo time
        await database.set_setting(f"promo_ts_{auction_id}", str(now))
        
        if DEBUG_MODE:
            print(f"Sent promo for auction {auction_id}")
    
    except Exception as e:
        if DEBUG_MODE:
            print(f"Error sending promo: {e}")


# ==================== AUCTION MONITORING ====================

async def monitor_auction(bot_client: discord.Client, auction_id: int):
    """
    Monitor auction for inactivity and trigger countdown/finalization.
    Runs as a background task.
    
    Args:
        bot_client: Discord client
        auction_id: Auction ID to monitor
    """
    try:
        if DEBUG_MODE:
            print(f"Started monitoring auction {auction_id}")
        
        while True:
            # Check if auction still active
            auction = await database.get_active_auction()
            if not auction or auction.get("id") != auction_id or auction.get("status") != "OPEN":
                if DEBUG_MODE:
                    print(f"Auction {auction_id} no longer active, stopping monitor")
                break
            
            # Get last bid timestamp
            last_ts_str = await database.get_setting(f"last_bid_ts_{auction_id}")
            if last_ts_str:
                last_ts = float(last_ts_str)
            else:
                last_ts = float(auction.get("started_at", time.time()))
            
            now = time.time()
            idle_time = now - last_ts
            
            # Check if inactivity threshold reached
            if idle_time >= INACTIVITY_THRESHOLD:
                if DEBUG_MODE:
                    print(f"Auction {auction_id} reached inactivity threshold, starting countdown")
                
                # Start countdown
                countdown_interrupted = False
                
                for sec in range(COUNTDOWN_SECONDS, 0, -1):
                    # Check if auction still active
                    auction = await database.get_active_auction()
                    if not auction or auction.get("id") != auction_id or auction.get("status") != "OPEN":
                        countdown_interrupted = True
                        break
                    
                    # Check if new bid placed
                    latest_ts_str = await database.get_setting(f"last_bid_ts_{auction_id}")
                    latest_ts = float(latest_ts_str) if latest_ts_str else last_ts
                    
                    if latest_ts > last_ts:
                        # New bid placed, restart monitoring
                        if DEBUG_MODE:
                            print(f"Auction {auction_id} countdown interrupted by new bid")
                        countdown_interrupted = True
                        break
                    
                    # Update panel with countdown
                    try:
                        await _post_or_update_panel(bot_client, auction, countdown=sec)
                    except Exception as e:
                        if DEBUG_MODE:
                            print(f"Error updating panel during countdown: {e}")
                    
                    # Send countdown message (optional)
                    if ENABLE_COUNTDOWN_MESSAGES and sec <= 3:
                        try:
                            ch_id_str = await database.get_setting(f"panel_channel_{auction_id}")
                            if ch_id_str:
                                channel = bot_client.get_channel(int(ch_id_str))
                                if channel:
                                    alarm_emoji = await emojis.get_emoji("alarm", "⏳")
                                    await channel.send(f"{alarm_emoji} **العدّ التنازلي: {sec}...**")
                        except Exception as e:
                            if DEBUG_MODE:
                                print(f"Error sending countdown message: {e}")
                    
                    await asyncio.sleep(1)
                
                # Check if countdown completed without interruption
                if not countdown_interrupted:
                    # Double-check no new bids
                    latest_ts_str = await database.get_setting(f"last_bid_ts_{auction_id}")
                    latest_ts = float(latest_ts_str) if latest_ts_str else last_ts
                    
                    if latest_ts <= last_ts:
                        # Finalize auction
                        if DEBUG_MODE:
                            print(f"Finalizing auction {auction_id}")
                        await _finalize_auction(bot_client, auction_id)
                        return
                    else:
                        if DEBUG_MODE:
                            print(f"Last-second bid detected, continuing monitoring")
            else:
                # Not inactive yet, check if we should send promo
                if idle_time >= (INACTIVITY_THRESHOLD / 2):
                    await _send_promo_if_needed(bot_client, auction)
                
                # Sleep before next check
                await asyncio.sleep(2)
    
    except asyncio.CancelledError:
        if DEBUG_MODE:
            print(f"Monitor for auction {auction_id} cancelled")
        return
    
    except Exception as e:
        if DEBUG_MODE:
            print(f"Error in monitor_auction: {e}")
            traceback.print_exc()
        await log_error(
            bot_client,
            f"Error monitoring auction {auction_id}: {str(e)}",
            "Monitor task crashed"
        )


# ==================== AUCTION FINALIZATION ====================

async def _finalize_auction(bot_client: discord.Client, auction_id: int):
    """
    Finalize auction: end it, announce winner, log results, cleanup.
    
    Args:
        bot_client: Discord client
        auction_id: Auction ID to finalize
    """
    try:
        # Get auction data
        auction = await database.get_active_auction()
        if not auction or auction.get("id") != auction_id:
            if DEBUG_MODE:
                print(f"Cannot finalize auction {auction_id} - not found or not active")
            return
        
        # Get bids
        bids = await database.get_bids_for_auction(auction_id)
        winner = bids[0] if bids else None
        
        # Calculate final price and winner
        final_price = winner["amount"] if winner else auction.get("start_bid")
        winner_id = winner["user_id"] if winner else None
        
        # Mark auction as ended in database
        await database.end_auction(auction_id, final_price, winner_id)
        
        if DEBUG_MODE:
            print(f"Auction {auction_id} ended - Winner: {winner_id}, Price: {final_price}")
        
        # Get panel channel
        panel_ch_id_str = await database.get_setting(f"panel_channel_{auction_id}")
        channel = None
        
        if panel_ch_id_str:
            try:
                channel = bot_client.get_channel(int(panel_ch_id_str))
            except (ValueError, TypeError):
                pass
        
        # Announce winner
        if channel:
            try:
                currency = await database.get_setting("currency_name") or DEFAULT_CURRENCY
                winner_emoji = await emojis.get_emoji("winner", "🏁")
                celebrate_emoji = await emojis.get_emoji("celebrate", "🎉")
                
                if winner:
                    announcement = (
                        f"{winner_emoji} **انتهى المزاد!**\n\n"
                        f"{celebrate_emoji} الفائز: <@{winner_id}>\n"
                        f"💰 المبلغ النهائي: **{fmt_amount(final_price)} {currency}**\n\n"
                        f"مبروك! {celebrate_emoji}"
                    )
                else:
                    announcement = (
                        f"{winner_emoji} **انتهى المزاد!**\n\n"
                        f"لم يتم تقديم أي مزايدات. السلعة لم تُباع."
                    )
                
                await channel.send(announcement)
            
            except Exception as e:
                if DEBUG_MODE:
                    print(f"Error announcing winner: {e}")
        
        # Log to log channel
        try:
            await log_auction_end(bot_client, auction, bids)
        except Exception as e:
            if DEBUG_MODE:
                print(f"Error logging auction end: {e}")
        
        # Delete panel message
        panel_msg_id_str = await database.get_setting(f"panel_msg_{auction_id}")
        if panel_msg_id_str and channel:
            try:
                msg = await channel.fetch_message(int(panel_msg_id_str))
                await msg.delete()
                if DEBUG_MODE:
                    print(f"Deleted panel message for auction {auction_id}")
            except (ValueError, TypeError, discord.NotFound, discord.Forbidden) as e:
                if DEBUG_MODE:
                    print(f"Could not delete panel message: {e}")
        
        # Cleanup settings
        try:
            await database.set_setting(f"panel_msg_{auction_id}", "")
            await database.set_setting(f"panel_channel_{auction_id}", "")
            await database.set_setting(f"last_bid_ts_{auction_id}", "")
            await database.set_setting(f"promo_ts_{auction_id}", "")
        except Exception as e:
            if DEBUG_MODE:
                print(f"Error cleaning up settings: {e}")
        
        # Remove monitor task
        if auction_id in AUCTION_MONITORS:
            try:
                AUCTION_MONITORS[auction_id].cancel()
                del AUCTION_MONITORS[auction_id]
            except Exception:
                pass
    
    except Exception as e:
        if DEBUG_MODE:
            print(f"Error in _finalize_auction: {e}")
            traceback.print_exc()
        await log_error(
            bot_client,
            f"Error finalizing auction {auction_id}: {str(e)}",
            "Finalization process failed"
        )


# ==================== PUBLIC BID HANDLER ====================

async def handle_bid(
    interaction: discord.Interaction,
    auction_id: int,
    amount: Optional[int] = None,
    increment: Optional[int] = None
):
    """
    Handle a bid from a user (via button or modal).
    
    Args:
        interaction: Discord interaction
        auction_id: Auction ID
        amount: Specific amount (for custom bids)
        increment: Amount to increment by (for quick bid buttons)
    """
    user = interaction.user
    now = time.time()
    
    try:
        # Cooldown check
        last_bid_time = USER_COOLDOWNS.get(user.id, 0)
        if now - last_bid_time < COOLDOWN_SECONDS:
            remaining = COOLDOWN_SECONDS - (now - last_bid_time)
            await interaction.response.send_message(
                f"⏰ انتظر {int(remaining)} ثانية قبل المزايدة مرة ثانية.",
                ephemeral=True
            )
            return
        
        # Update cooldown
        USER_COOLDOWNS[user.id] = now
        
        # Ensure auction is active
        auction = await database.get_active_auction()
        if not auction or auction.get("id") != auction_id or auction.get("status") != "OPEN":
            await interaction.response.send_message(
                "❌ هذا المزاد ليس نشطًا الآن.",
                ephemeral=True
            )
            return
        
        # Check role permission
        has_role, error_msg = await security.has_auction_role(user)
        if not has_role:
            # Get application link if available
            app_link = await database.get_setting("application_link") or \
                      "https://discord.com/channels/1467024562091720885/1467445614617821302"
            await interaction.response.send_message(
                f"❌ {error_msg}\n\nتقدر تقدم على طلب الرتبة من {app_link}",
                ephemeral=True
            )
            return
        
        # Get current highest bid
        bids = await database.get_bids_for_auction(auction_id)
        highest = bids[0] if bids else None
        highest_amount = highest["amount"] if highest else auction.get("start_bid", 0)
        highest_user = highest["user_id"] if highest else None
        
        # Calculate new bid amount
        if increment is not None:
            new_amount = highest_amount + increment
        elif amount is not None:
            new_amount = amount
        else:
            await interaction.response.send_message(
                "❌ No bid amount provided.",
                ephemeral=True
            )
            return
        
        # Prevent self-outbid
        if highest_user == user.id:
            crown_emoji = await emojis.get_emoji("crown", "👑")
            await interaction.response.send_message(
                f"{crown_emoji} أنت بالفعل أعلى مزايد!",
                ephemeral=True
            )
            return
        
        # Check minimum increment
        min_inc = auction.get("min_increment") or DEFAULT_MIN_INCREMENT
        if new_amount - highest_amount < min_inc:
            await interaction.response.send_message(
                f"❌ لازم تزيد على الأقل **{fmt_amount(min_inc)}** عن أعلى مزايدة.",
                ephemeral=True
            )
            return
        
        # Validate amount
        is_valid, error = validate_amount(new_amount)
        if not is_valid:
            await interaction.response.send_message(
                f"❌ {error}",
                ephemeral=True
            )
            return
        
        # Add bid to database
        bid = await database.add_bid(auction_id, user.id, new_amount)
        
        # Update last bid timestamp
        await database.set_setting(f"last_bid_ts_{auction_id}", str(time.time()))
        
        if DEBUG_MODE:
            print(f"Bid placed: User {user.id}, Amount {new_amount}, Auction {auction_id}")
        
        # Update panel (with small delay to avoid rate limits)
        await asyncio.sleep(PANEL_UPDATE_DELAY)
        await _post_or_update_panel(interaction.client, auction)
        
        # Send confirmation
        currency = await database.get_setting("currency_name") or DEFAULT_CURRENCY
        checkmark_emoji = await emojis.get_emoji("checkmark", "✅")
        await interaction.response.send_message(
            f"{checkmark_emoji} المزايدة قُبلت: **{fmt_amount(new_amount)} {currency}**",
            ephemeral=True
        )
        
        # Ensure monitor is running
        if auction_id not in AUCTION_MONITORS or AUCTION_MONITORS[auction_id].done():
            try:
                task = asyncio.create_task(monitor_auction(interaction.client, auction_id))
                AUCTION_MONITORS[auction_id] = task
                if DEBUG_MODE:
                    print(f"Started monitor task for auction {auction_id}")
            except Exception as e:
                if DEBUG_MODE:
                    print(f"Failed to start monitor: {e}")
    
    except Exception as e:
        if DEBUG_MODE:
            print(f"Error in handle_bid: {e}")
            traceback.print_exc()
        
        try:
            await interaction.response.send_message(
                "❌ حدث خطأ أثناء معالجة مزايدتك. الرجاء المحاولة مرة أخرى.",
                ephemeral=True
            )
        except discord.InteractionResponded:
            pass


# ==================== ADMIN FUNCTIONS ====================

async def end_current_auction(bot_client: discord.Client) -> Optional[bool]:
    """
    Manually end the current active auction.
    Used by admin commands.
    
    Args:
        bot_client: Discord client
        
    Returns:
        True if auction ended, None if no active auction
    """
    auction = await database.get_active_auction()
    if not auction:
        return None
    
    await _finalize_auction(bot_client, auction["id"])
    return True


async def cancel_auction_monitor(auction_id: int):
    """
    Cancel the monitor task for an auction.
    
    Args:
        auction_id: Auction ID
    """
    if auction_id in AUCTION_MONITORS:
        try:
            AUCTION_MONITORS[auction_id].cancel()
            del AUCTION_MONITORS[auction_id]
            if DEBUG_MODE:
                print(f"Cancelled monitor for auction {auction_id}")
        except Exception as e:
            if DEBUG_MODE:
                print(f"Error cancelling monitor: {e}")
