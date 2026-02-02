# auctions.py
import discord
from discord.ui import View, Button, Modal, TextInput
from bids import parse_amount, fmt_amount
from config import DEFAULT_MIN_INCREMENT, COOLDOWN_SECONDS, DEFAULT_AUCTION_DURATION_MIN
from database import create_auction, get_active_auction, add_bid, get_bids_for_auction, get_last_bid_by_user, end_auction
from logs import log_bid, log_auction_end
from database import get_setting
import asyncio
import time

# in-memory cooldowns map {user_id: last_ts}
USER_COOLDOWNS: dict[int, float] = {}
COOLDOWN = COOLDOWN_SECONDS

# Helper to fetch config values (role id etc) from DB
async def get_server_setting(key: str, fallback=None):
    v = await get_setting(key)
    if v is None:
        return fallback
    return v

def build_auction_embed(auction: dict, top_bid: dict | None = None, bids_count: int = 0, currency_name: str = "Credits") -> discord.Embed:
    highest = top_bid['amount'] if top_bid else auction.get("start_bid", 0)
    highest_user = top_bid['user_id'] if top_bid else None
    embed = discord.Embed(title="Auction Panel", color=0x2F3136)
    embed.add_field(name="Status", value=auction.get("status", "UNKNOWN"), inline=True)
    embed.add_field(name="Highest Bid", value=f"{fmt_amount(highest)} {currency_name}", inline=True)
    embed.add_field(name="Bids", value=str(bids_count), inline=True)
    time_left = max(0, int(auction.get("ends_at", 0) - time.time()))
    embed.add_field(name="Time left (s)", value=str(time_left), inline=True)
    if highest_user:
        embed.set_footer(text=f"Highest by: <@{highest_user}>")
    else:
        embed.set_footer(text=f"Starting bid: {fmt_amount(auction.get('start_bid', 0))} {currency_name}")
    return embed

class BidModal(Modal, title="Place custom bid"):
    amount = TextInput(label="Amount (e.g. 250k / 2.5m / 1,000,000)", placeholder="250k")

    def __init__(self, auction_id: int):
        super().__init__()
        self.auction_id = auction_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = parse_amount(self.amount.value)
        except Exception:
            await interaction.response.send_message("Invalid amount format. Examples: 250k / 2.5m", ephemeral=True)
            return
        await handle_bid(interaction, self.auction_id, amt)

class AuctionView(View):
    def __init__(self, auction_id: int):
        super().__init__(timeout=None)
        self.auction_id = auction_id
        # add buttons
        self.add_item(Button(label="+1K", custom_id=f"bid_1k_{auction_id}"))
        self.add_item(Button(label="+100K", custom_id=f"bid_100k_{auction_id}"))
        self.add_item(Button(label="+500K", custom_id=f"bid_500k_{auction_id}"))
        self.add_item(Button(label="Custom", custom_id=f"bid_custom_{auction_id}"))

async def handle_bid(interaction: discord.Interaction, auction_id: int, amount: int):
    user = interaction.user

    # cooldown
    now = time.time()
    last = USER_COOLDOWNS.get(user.id, 0)
    if now - last < COOLDOWN:
        await interaction.response.send_message("انتظر شوية قبل المزايدة مرة ثانية.", ephemeral=True)
        return
    USER_COOLDOWNS[user.id] = now

    # check active auction
    auction = await get_active_auction()
    if not auction or auction.get("id") != auction_id or auction.get("status") != "OPEN":
        await interaction.response.send_message("هذا المزاد ليس نشطًا الآن.", ephemeral=True)
        return

    # get role id from settings
    role_id = await get_server_setting("role_id")
    if role_id is None:
        await interaction.response.send_message("رتبة الرواد لم يتم ضبطها بعد من الإدارة.", ephemeral=True)
        return
    role_id = int(role_id)

    # role check
    member = interaction.user
    if not any(r.id == role_id for r in getattr(member, "roles", [])):
        await interaction.response.send_message("ما عندك رتبة رواد المزاد علشان تدخل المزايدة.", ephemeral=True)
        return

    # highest bid
    bids = await get_bids_for_auction(auction_id)
    highest = bids[0] if bids else None
    highest_amount = highest["amount"] if highest else auction.get("start_bid", 0)
    highest_user = highest["user_id"] if highest else None

    # prevent self-bidding
    if highest_user == user.id:
        await interaction.response.send_message("أنت بالفعل أعلى مزايد 👑", ephemeral=True)
        return

    if amount <= highest_amount:
        await interaction.response.send_message(f"المبلغ لازم يكون أكبر من أعلى مزايدة حالية ({fmt_amount(highest_amount)}).", ephemeral=True)
        return

    # min increment (from auction record)
    min_inc = auction.get("min_increment") or DEFAULT_MIN_INCREMENT
    if amount - highest_amount < min_inc:
        await interaction.response.send_message(f"لازم تزيد على الأقل {fmt_amount(min_inc)} عن أعلى مزايدة.", ephemeral=True)
        return

    # add bid
    bid = await add_bid(auction_id, user.id, amount)
    # log
    await log_bid(interaction.client, user, amount, auction_id)

    # update panel: send a refreshed embed to auction channel (we rely on channel configured)
    ch_id = await get_server_setting("auction_channel_id")
    currency = await get_server_setting("currency_name") or "Credits"
    if ch_id:
        channel = interaction.client.get_channel(int(ch_id))
        if channel:
            top_bids = await get_bids_for_auction(auction_id)
            embed = build_auction_embed(auction, top_bid=top_bids[0] if top_bids else None, bids_count=len(top_bids), currency_name=currency)
            view = AuctionView(auction_id)
            # we send a new panel message (can be improved later to edit message)
            await channel.send(embed=embed, view=view)

    await interaction.response.send_message(f"المزايدة قُبلت: {fmt_amount(amount)} {currency}", ephemeral=True)

# Admin helper to end auction and log
async def end_current_auction(client: discord.Client):
    auction = await get_active_auction()
    if not auction:
        return None
    bids = await get_bids_for_auction(auction["id"])
    winner = bids[0] if bids else None
    final_price = winner["amount"] if winner else auction.get("start_bid")
    winner_id = winner["user_id"] if winner else None
    await end_auction(auction["id"], final_price, winner_id)
    await log_auction_end(client, auction, bids)
    return {"auction": auction, "winner": winner, "top_bids": bids}
