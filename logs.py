# logs.py
"""
Logging utilities for auction events.
Creates detailed embeds for auction completion and other events.
"""

import discord
from typing import List, Dict, Any, Optional
import database
from bids import fmt_amount, calculate_commission
from config import (
    DEFAULT_CURRENCY, COLOR_AUCTION_ENDED, COLOR_INFO,
    MAX_BID_HISTORY_DISPLAY, DEBUG_MODE
)
import emojis


async def _get_log_channel(client: discord.Client) -> Optional[discord.TextChannel]:
    """
    Get the configured log channel.
    
    Args:
        client: Discord client
        
    Returns:
        TextChannel object or None if not configured
    """
    ch_id_str = await database.get_setting("log_channel_id")
    
    if not ch_id_str:
        if DEBUG_MODE:
            print("Log channel not configured")
        return None
    
    try:
        ch_id = int(ch_id_str)
        channel = client.get_channel(ch_id)
        
        if channel is None:
            if DEBUG_MODE:
                print(f"Log channel {ch_id} not found")
        
        return channel
    
    except (ValueError, TypeError) as e:
        if DEBUG_MODE:
            print(f"Invalid log channel ID: {ch_id_str} - {e}")
        return None


async def log_auction_end(client: discord.Client, auction: Dict[str, Any], 
                         bids: List[Dict[str, Any]]):
    """
    Log auction completion with detailed statistics.
    
    Args:
        client: Discord client
        auction: Auction data dictionary
        bids: List of bid dictionaries
    """
    channel = await _get_log_channel(client)
    if channel is None:
        if DEBUG_MODE:
            print("Cannot log auction end - no log channel")
        return
    
    try:
        # Get currency and commission
        currency = await database.get_setting("currency_name") or DEFAULT_CURRENCY
        commission_pct = int(await database.get_setting("commission") or "20")
        
        # Get emojis
        trophy_emoji = await emojis.get_emoji("trophy", "🏆")
        money_emoji = await emojis.get_emoji("money", "💰")
        chart_emoji = await emojis.get_emoji("chart", "📈")
        crown_emoji = await emojis.get_emoji("crown", "👑")
        
        # Create main embed
        embed = discord.Embed(
            title=f"{trophy_emoji} Auction #{auction.get('id')} - Completed",
            color=COLOR_AUCTION_ENDED,
            timestamp=discord.utils.utcnow()
        )
        
        # Basic info
        final_price = auction.get('final_price') or 0
        winner_id = auction.get('winner_id')
        
        embed.add_field(
            name="Status",
            value=f"✅ {auction.get('status', 'ENDED')}",
            inline=True
        )
        
        embed.add_field(
            name=f"{money_emoji} Final Price",
            value=f"**{fmt_amount(final_price)} {currency}**",
            inline=True
        )
        
        if winner_id:
            embed.add_field(
                name=f"{crown_emoji} Winner",
                value=f"<@{winner_id}>",
                inline=True
            )
        else:
            embed.add_field(
                name="Winner",
                value="No bids placed",
                inline=True
            )
        
        # Auction details
        start_bid = auction.get('start_bid', 0)
        min_increment = auction.get('min_increment', 0)
        
        embed.add_field(
            name="Starting Bid",
            value=f"{fmt_amount(start_bid)} {currency}",
            inline=True
        )
        
        embed.add_field(
            name="Min Increment",
            value=f"{fmt_amount(min_increment)} {currency}",
            inline=True
        )
        
        # Statistics
        total_bids = len(bids)
        unique_bidders = len(set(b['user_id'] for b in bids)) if bids else 0
        
        embed.add_field(
            name=f"{chart_emoji} Total Bids",
            value=str(total_bids),
            inline=True
        )
        
        embed.add_field(
            name="Unique Bidders",
            value=str(unique_bidders),
            inline=True
        )
        
        # Calculate bid sum and commission
        if bids:
            bid_sum = sum(b["amount"] for b in bids)
            commission_amount = calculate_commission(final_price, commission_pct)
            
            embed.add_field(
                name="Total Bid Volume",
                value=f"{fmt_amount(bid_sum)} {currency}",
                inline=True
            )
            
            embed.add_field(
                name=f"Commission ({commission_pct}%)",
                value=f"{fmt_amount(commission_amount)} {currency}",
                inline=True
            )
        
        # Time information
        started_at = auction.get('started_at', 0)
        ended_at = auction.get('ended_at', 0)
        
        if started_at and ended_at:
            duration_seconds = ended_at - started_at
            duration_minutes = duration_seconds // 60
            duration_seconds_remainder = duration_seconds % 60
            
            embed.add_field(
                name="Duration",
                value=f"{duration_minutes}m {duration_seconds_remainder}s",
                inline=True
            )
        
        # Top bids section
        if bids:
            top_bids = bids[:MAX_BID_HISTORY_DISPLAY]
            bid_list = []
            
            for i, bid in enumerate(top_bids, start=1):
                user_id = bid['user_id']
                amount = bid['amount']
                
                # Add medal emojis for top 3
                if i == 1:
                    prefix = "🥇"
                elif i == 2:
                    prefix = "🥈"
                elif i == 3:
                    prefix = "🥉"
                else:
                    prefix = f"`{i}.`"
                
                bid_list.append(f"{prefix} <@{user_id}> — **{fmt_amount(amount)} {currency}**")
            
            embed.add_field(
                name=f"Top {len(top_bids)} Bids",
                value="\n".join(bid_list),
                inline=False
            )
            
            if len(bids) > MAX_BID_HISTORY_DISPLAY:
                embed.add_field(
                    name="Note",
                    value=f"*Showing top {MAX_BID_HISTORY_DISPLAY} of {len(bids)} total bids*",
                    inline=False
                )
        else:
            embed.add_field(
                name="Bids",
                value="*No bids were placed*",
                inline=False
            )
        
        # Footer
        started_by = auction.get('started_by')
        if started_by:
            embed.set_footer(text=f"Auction started by user ID: {started_by}")
        
        # Send the embed
        await channel.send(embed=embed)
        
        if DEBUG_MODE:
            print(f"Auction #{auction.get('id')} logged successfully")
    
    except Exception as e:
        if DEBUG_MODE:
            print(f"Error logging auction end: {e}")
            import traceback
            traceback.print_exc()


async def log_auction_start(client: discord.Client, auction: Dict[str, Any]):
    """
    Log auction start event.
    
    Args:
        client: Discord client
        auction: Auction data dictionary
    """
    channel = await _get_log_channel(client)
    if channel is None:
        return
    
    try:
        currency = await database.get_setting("currency_name") or DEFAULT_CURRENCY
        fire_emoji = await emojis.get_emoji("fire", "🔥")
        
        embed = discord.Embed(
            title=f"{fire_emoji} New Auction Started - #{auction.get('id')}",
            color=COLOR_INFO,
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(
            name="Starting Bid",
            value=f"{fmt_amount(auction.get('start_bid', 0))} {currency}",
            inline=True
        )
        
        embed.add_field(
            name="Min Increment",
            value=f"{fmt_amount(auction.get('min_increment', 0))} {currency}",
            inline=True
        )
        
        # Calculate duration
        ends_at = auction.get('ends_at', 0)
        started_at = auction.get('started_at', 0)
        duration_minutes = (ends_at - started_at) // 60
        
        embed.add_field(
            name="Duration",
            value=f"{duration_minutes} minutes",
            inline=True
        )
        
        started_by = auction.get('started_by')
        if started_by:
            embed.set_footer(text=f"Started by: {started_by}")
        
        await channel.send(embed=embed)
        
        if DEBUG_MODE:
            print(f"Auction #{auction.get('id')} start logged")
    
    except Exception as e:
        if DEBUG_MODE:
            print(f"Error logging auction start: {e}")


async def log_bid(client: discord.Client, auction_id: int, 
                 user_id: int, amount: int, is_highest: bool):
    """
    Log individual bid (optional - can be noisy).
    Not used by default to avoid spam.
    
    Args:
        client: Discord client
        auction_id: Auction ID
        user_id: Bidder's user ID
        amount: Bid amount
        is_highest: Whether this is now the highest bid
    """
    channel = await _get_log_channel(client)
    if channel is None:
        return
    
    try:
        currency = await database.get_setting("currency_name") or DEFAULT_CURRENCY
        bid_emoji = await emojis.get_emoji("bid", "🔼")
        
        status = "New Highest Bid!" if is_highest else "Bid Placed"
        
        embed = discord.Embed(
            title=f"{bid_emoji} {status}",
            description=f"<@{user_id}> bid **{fmt_amount(amount)} {currency}** on Auction #{auction_id}",
            color=COLOR_INFO,
            timestamp=discord.utils.utcnow()
        )
        
        await channel.send(embed=embed)
    
    except Exception as e:
        if DEBUG_MODE:
            print(f"Error logging bid: {e}")


async def log_error(client: discord.Client, error_msg: str, 
                   context: Optional[str] = None):
    """
    Log an error to the log channel.
    
    Args:
        client: Discord client
        error_msg: Error message
        context: Optional context information
    """
    channel = await _get_log_channel(client)
    if channel is None:
        if DEBUG_MODE:
            print(f"ERROR: {error_msg}")
            if context:
                print(f"Context: {context}")
        return
    
    try:
        warning_emoji = await emojis.get_emoji("warning", "⚠️")
        
        embed = discord.Embed(
            title=f"{warning_emoji} Error",
            description=error_msg,
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        
        if context:
            embed.add_field(name="Context", value=context, inline=False)
        
        await channel.send(embed=embed)
    
    except Exception as e:
        if DEBUG_MODE:
            print(f"Error logging error (meta!): {e}")


async def log_command_usage(client: discord.Client, command_name: str,
                           user: discord.User, success: bool):
    """
    Log admin command usage (optional).
    
    Args:
        client: Discord client
        command_name: Name of the command
        user: User who executed the command
        success: Whether command was successful
    """
    channel = await _get_log_channel(client)
    if channel is None:
        return
    
    try:
        status_emoji = "✅" if success else "❌"
        
        embed = discord.Embed(
            title=f"{status_emoji} Command: {command_name}",
            description=f"Executed by {user.mention}",
            color=discord.Color.green() if success else discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        
        await channel.send(embed=embed)
    
    except Exception as e:
        if DEBUG_MODE:
            print(f"Error logging command: {e}")
