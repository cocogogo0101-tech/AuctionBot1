# logs.py
import discord
from bids import fmt_amount
import database
from config import DEFAULT_CURRENCY

async def _get_log_channel(client: discord.Client) -> discord.TextChannel | None:
    ch_id = await database.get_setting("log_channel_id")
    if ch_id:
        try:
            return client.get_channel(int(ch_id))
        except Exception:
            return None
    return None

async def log_auction_end(client: discord.Client, auction: dict, bids: list):
    ch = await _get_log_channel(client)
    currency = await database.get_setting("currency_name") or DEFAULT_CURRENCY
    if ch is None:
        return
    embed = discord.Embed(title=f"Auction #{auction.get('id')} Ended", color=0xFFAA00)
    embed.add_field(name="Status", value=auction.get("status"), inline=True)
    embed.add_field(name="Final Price", value=f"{fmt_amount(auction.get('final_price') or 0)} {currency}", inline=True)
    embed.add_field(name="Winner", value=f"<@{auction.get('winner_id')}>" if auction.get('winner_id') else "N/A", inline=True)

    total_bids = len(bids)
    sum_bids = sum(b["amount"] for b in bids) if bids else 0
    desc = ""
    for i, b in enumerate(bids[:10], start=1):
        desc += f"{i}. <@{b['user_id']}> — {fmt_amount(b['amount'])}\n"
    if desc:
        embed.add_field(name=f"Top {min(10, total_bids)} bids", value=desc, inline=False)
    embed.add_field(name="Total bids", value=str(total_bids), inline=True)
    embed.add_field(name="Sum of bids", value=f"{fmt_amount(sum_bids)} {currency}", inline=True)
    await ch.send(embed=embed)