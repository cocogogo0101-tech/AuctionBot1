# logs.py
import discord
from bids import fmt_amount
from database import get_setting
from config import DEFAULT_CURRENCY

async def _get_log_channel(client: discord.Client) -> discord.TextChannel | None:
    ch_id = await get_setting("log_channel_id")
    if ch_id is None:
        return None
    try:
        ch = client.get_channel(int(ch_id))
        return ch
    except Exception:
        return None

async def log_bid(client: discord.Client, user: discord.User, amount: int, auction_id: int):
    ch = await _get_log_channel(client)
    currency = await get_setting("currency_name") or DEFAULT_CURRENCY
    if ch is None:
        return
    embed = discord.Embed(title="New Bid", color=0x00FF00)
    embed.add_field(name="User", value=f"{user} ({user.id})", inline=True)
    embed.add_field(name="Amount", value=f"{fmt_amount(amount)} {currency}", inline=True)
    embed.add_field(name="Auction ID", value=str(auction_id), inline=True)
    await ch.send(embed=embed)

async def log_auction_end(client: discord.Client, auction: dict, top_bids: list):
    ch = await _get_log_channel(client)
    currency = await get_setting("currency_name") or DEFAULT_CURRENCY
    if ch is None:
        return
    embed = discord.Embed(title="Auction Ended", color=0xFFAA00)
    embed.add_field(name="Auction ID", value=str(auction.get("id")), inline=True)
    embed.add_field(name="Final Price", value=f"{fmt_amount(auction.get('final_price') or 0)} {currency}", inline=True)
    winner = auction.get("winner_id") or "N/A"
    embed.add_field(name="Winner", value=str(winner), inline=True)
    desc = ""
    for i, b in enumerate(top_bids[:3], start=1):
        desc += f"{i}. <@{b['user_id']}> — {fmt_amount(b['amount'])}\n"
    if desc:
        embed.add_field(name="Top bids", value=desc, inline=False)
    await ch.send(embed=embed)
