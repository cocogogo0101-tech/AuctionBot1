# auctions.py
import discord
from discord.ui import View, Button, Modal, TextInput
from bids import parse_amount, fmt_amount
import database
from config import DEFAULT_MIN_INCREMENT, COOLDOWN_SECONDS
import asyncio
import time
import random
from typing import Optional, Dict, Any, List
from logs import log_auction_end
import emojis

# In-memory trackers
USER_COOLDOWNS: Dict[int, float] = {}
AUCTION_MONITORS: Dict[int, asyncio.Task] = {}

# Promo templates with placeholders for emojis and mention/amount
PROMO_TEMPLATES = [
    "{fire} **زيد أكثر وولعها** {mention} دفع **{amount}**! مين يكسر الرقم؟",
    "{spark} يا ليل يا عين! {mention} رافع السعر لـ **{amount}** — حان وقت البطل الجاي! {fire}",
    "{trophy} المزاد شغال، من هو البطل التالي؟ {mention} دفعة **{amount}** — ورّنا همتك!",
    "{celebrate} حدّث التحدّي: {mention} دافع **{amount}** — تقدر تكسرها؟",
    "{alarm} 📢 اعلان: {mention} وصل للسعر **{amount}** — مين عنده الجرأة؟"
]

# Timings
COUNTDOWN_SECONDS = 3
INACTIVITY_THRESHOLD = 30   # seconds of inactivity before starting countdown
PROMO_MIN_INTERVAL = 45     # seconds min between promos

# ----- EMBED BUILDER -----
def build_auction_embed(auction: dict, top_bid: Optional[dict] = None, bids_count: int = 0, currency_name: str = "Credits", countdown: Optional[int] = None) -> discord.Embed:
    highest = top_bid['amount'] if top_bid else auction.get("start_bid", 0)
    highest_user = top_bid['user_id'] if top_bid else None
    embed = discord.Embed(title="🎯 Auction Panel", color=0x2F3136)
    embed.add_field(name="Status", value=auction.get("status", "UNKNOWN"), inline=True)
    embed.add_field(name="Highest Bid", value=f"{fmt_amount(highest)} {currency_name}", inline=True)
    embed.add_field(name="Bids", value=str(bids_count), inline=True)
    time_left = max(0, int(auction.get("ends_at", 0) - time.time()))
    embed.add_field(name="Time left (s)", value=str(time_left), inline=True)
    if countdown is not None and countdown > 0:
        embed.add_field(name="Countdown", value=f"⏱️ {countdown}s", inline=True)
    if highest_user:
        embed.set_footer(text=f"Highest by: <@{highest_user}>")
    else:
        embed.set_footer(text=f"Starting bid: {fmt_amount(auction.get('start_bid', 0))} {currency_name}")
    return embed

# ----- MODAL (Custom Bid) -----
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
        await handle_bid(interaction, self.auction_id, amount=amt)

# ----- VIEW (Buttons) -----
class AuctionView(View):
    def __init__(self, auction_id: int):
        super().__init__(timeout=None)
        self.auction_id = auction_id
        self.add_item(Button(label="+1K", custom_id=f"bid_1k_{auction_id}"))
        self.add_item(Button(label="+100K", custom_id=f"bid_100k_{auction_id}"))
        self.add_item(Button(label="+500K", custom_id=f"bid_500k_{auction_id}"))
        self.add_item(Button(label="Custom", custom_id=f"bid_custom_{auction_id}"))

# ----- Helpers to manage panel message -----
async def _get_panel_message(bot_client: discord.Client, auction_id: int) -> Optional[discord.Message]:
    ch_id = await database.get_setting(f"panel_channel_{auction_id}")
    msg_id = await database.get_setting(f"panel_msg_{auction_id}")
    if not ch_id or not msg_id:
        return None
    try:
        ch = bot_client.get_channel(int(ch_id))
        if not ch:
            return None
        msg = await ch.fetch_message(int(msg_id))
        return msg
    except Exception:
        return None

async def _post_or_update_panel(bot_client: discord.Client, auction: dict) -> Optional[discord.Message]:
    auction_id = auction["id"]
    bids = await database.get_bids_for_auction(auction_id)
    top_bid = bids[0] if bids else None
    bids_count = len(bids)
    currency = await database.get_setting("currency_name") or "Credits"

    # pick channel: panel_channel_{id} if set, else first from auction_channel_ids
    ch_id = await database.get_setting(f"panel_channel_{auction_id}")
    ch = None
    if ch_id:
        ch = bot_client.get_channel(int(ch_id))
    else:
        cfg = await database.get_setting("auction_channel_ids") or ""
        ids = [s for s in cfg.split(",") if s]
        for cid in ids:
            try:
                c = bot_client.get_channel(int(cid))
                if c:
                    ch = c
                    break
            except Exception:
                continue
    if not ch:
        return None

    embed = build_auction_embed(auction, top_bid=top_bid, bids_count=bids_count, currency_name=currency)
    view = AuctionView(auction_id)

    msg = await _get_panel_message(bot_client, auction_id)
    if msg:
        try:
            await msg.edit(embed=embed, view=view)
            return msg
        except Exception:
            try:
                new_msg = await ch.send(embed=embed, view=view)
                await database.set_setting(f"panel_msg_{auction_id}", str(new_msg.id))
                await database.set_setting(f"panel_channel_{auction_id}", str(ch.id))
                return new_msg
            except Exception:
                return None
    else:
        try:
            new_msg = await ch.send(embed=embed, view=view)
            await database.set_setting(f"panel_msg_{auction_id}", str(new_msg.id))
            await database.set_setting(f"panel_channel_{auction_id}", str(ch.id))
            return new_msg
        except Exception:
            return None

# ----- Promo sending (creative) -----
async def _send_promo_if_needed(bot_client: discord.Client, auction: dict):
    auction_id = auction["id"]
    last_promo = await database.get_setting(f"promo_ts_{auction_id}")
    last_promo_ts = float(last_promo) if last_promo else 0
    now = time.time()
    if now - last_promo_ts < PROMO_MIN_INTERVAL:
        return
    bids = await database.get_bids_for_auction(auction_id)
    top_bid = bids[0] if bids else None
    amount_text = fmt_amount(top_bid["amount"]) if top_bid else fmt_amount(auction["start_bid"])
    mention = f"<@{top_bid['user_id']}>" if top_bid else "@here"
    # fetch emojis
    fire_e = await emojis.get_emoji("fire")
    spark_e = await emojis.get_emoji("spark")
    trophy_e = await emojis.get_emoji("trophy")
    celebrate_e = await emojis.get_emoji("celebrate")
    alarm_e = await emojis.get_emoji("alarm")
    template = random.choice(PROMO_TEMPLATES)
    text = template.format(
        fire=fire_e,
        spark=spark_e,
        trophy=trophy_e,
        celebrate=celebrate_e,
        alarm=alarm_e,
        mention=mention,
        amount=amount_text
    )
    ch_id = await database.get_setting(f"panel_channel_{auction_id}") or (await database.get_setting("auction_channel_ids") or "").split(",")[0]
    if not ch_id:
        return
    try:
        ch = bot_client.get_channel(int(ch_id))
        if ch:
            # use markdown bold and mention style for excitement
            await ch.send(text)
            await database.set_setting(f"promo_ts_{auction_id}", str(now))
    except Exception:
        return

# ----- Monitor: inactivity -> countdown -> finalize -----
async def monitor_auction(bot_client: discord.Client, auction_id: int):
    try:
        while True:
            auction = await database.get_active_auction()
            if not auction or auction.get("id") != auction_id or auction.get("status") != "OPEN":
                break
            last_ts_val = await database.get_setting(f"last_bid_ts_{auction_id}")
            last_ts = float(last_ts_val) if last_ts_val else float(auction.get("started_at", time.time()))
            now = time.time()
            idle = now - last_ts
            if idle >= INACTIVITY_THRESHOLD:
                # start countdown
                for sec in range(COUNTDOWN_SECONDS, 0, -1):
                    auction = await database.get_active_auction()
                    if not auction or auction.get("id") != auction_id or auction.get("status") != "OPEN":
                        return
                    latest_ts = float(await database.get_setting(f"last_bid_ts_{auction_id}") or last_ts)
                    if latest_ts > last_ts:
                        # interrupted by new bid
                        break
                    # update panel with countdown
                    msg = await _get_panel_message(bot_client, auction_id)
                    if msg:
                        top_bids = await database.get_bids_for_auction(auction_id)
                        embed = build_auction_embed(auction, top_bid=top_bids[0] if top_bids else None, bids_count=len(top_bids), currency_name=(await database.get_setting("currency_name") or "Credits"), countdown=sec)
                        try:
                            await msg.edit(embed=embed)
                        except Exception:
                            pass
                    # send a short countdown (only when countdown starts)
                    try:
                        if sec <= 3:
                            ch_id = await database.get_setting(f"panel_channel_{auction_id}")
                            if ch_id:
                                ch = bot_client.get_channel(int(ch_id))
                                if ch:
                                    await ch.send(f"⏳ العدّ التنازلي: {sec}...")
                    except Exception:
                        pass
                    await asyncio.sleep(1)
                # after countdown, recheck
                latest_ts = float(await database.get_setting(f"last_bid_ts_{auction_id}") or last_ts)
                if latest_ts <= last_ts:
                    # finalize
                    await _finalize_auction(bot_client, auction_id)
                    return
                # else continue monitoring
            else:
                # if idle half threshold, maybe trigger promo
                if idle >= (INACTIVITY_THRESHOLD / 2):
                    await _send_promo_if_needed(bot_client, auction)
                await asyncio.sleep(2)
    except asyncio.CancelledError:
        return
    except Exception:
        traceback.print_exc()
        return

# ----- Finalize: end auction, announce winner, send log, cleanup -----
async def _finalize_auction(bot_client: discord.Client, auction_id: int):
    auction = await database.get_active_auction()
    if not auction or auction.get("id") != auction_id:
        return
    bids = await database.get_bids_for_auction(auction_id)
    winner = bids[0] if bids else None
    final_price = winner["amount"] if winner else auction.get("start_bid")
    winner_id = winner["user_id"] if winner else None
    # mark as ended
    await database.end_auction(auction_id, final_price, winner_id)
    panel_ch_id = await database.get_setting(f"panel_channel_{auction_id}")
    panel_msg_id = await database.get_setting(f"panel_msg_{auction_id}")
    currency = await database.get_setting("currency_name") or "Credits"
    ch = None
    if panel_ch_id:
        try:
            ch = bot_client.get_channel(int(panel_ch_id))
        except Exception:
            ch = None
    if ch:
        # winner announce (rich markdown)
        if winner:
            await ch.send(f"🏁 **Auction Ended!** Winner: <@{winner_id}> with **{fmt_amount(final_price)} {currency}**. Congratulations! {await emojis.get_emoji('celebrate')}")
        else:
            await ch.send(f"🏁 **Auction Ended!** No bids were placed. Item unsold.")
        # final log
        await log_auction_end(bot_client, auction, bids)
        # delete panel message (if any)
        if panel_msg_id:
            try:
                msg = await ch.fetch_message(int(panel_msg_id))
                await msg.delete()
            except Exception:
                pass
    # cleanup settings
    try:
        await database.set_setting(f"panel_msg_{auction_id}", "")
        await database.set_setting(f"panel_channel_{auction_id}", "")
        await database.set_setting(f"last_bid_ts_{auction_id}", "")
        await database.set_setting(f"promo_ts_{auction_id}", "")
    except Exception:
        pass

# ----- Public handle_bid (used by bot on button/modal) -----
async def handle_bid(interaction: discord.Interaction, auction_id: int, amount: Optional[int] = None, increment: Optional[int] = None):
    user = interaction.user
    now = time.time()

    # cooldown
    last = USER_COOLDOWNS.get(user.id, 0)
    if now - last < COOLDOWN_SECONDS:
        await interaction.response.send_message("انتظر شوية قبل المزايدة مرة ثانية.", ephemeral=True)
        return
    USER_COOLDOWNS[user.id] = now

    # ensure auction active
    auction = await database.get_active_auction()
    if not auction or auction.get("id") != auction_id or auction.get("status") != "OPEN":
        await interaction.response.send_message("هذا المزاد ليس نشطًا الآن.", ephemeral=True)
        return

    # role check
    role_id = await database.get_setting("role_id")
    if not role_id:
        await interaction.response.send_message("رتبة الرواد لم يتم ضبطها بعد من الإدارة.", ephemeral=True)
        return
    role_id = int(role_id)
    if not any(r.id == role_id for r in getattr(user, "roles", [])):
        await interaction.response.send_message("ما عندك رتبة رواد المزاد. تقدر تقدم على طلب الرتبة من https://discord.com/channels/1467024562091720885/1467445614617821302", ephemeral=True)
        return

    # highest bid
    bids = await database.get_bids_for_auction(auction_id)
    highest = bids[0] if bids else None
    highest_amount = highest["amount"] if highest else auction.get("start_bid", 0)
    highest_user = highest["user_id"] if highest else None

    # compute new amount
    if increment is not None:
        new_amount = highest_amount + increment
    elif amount is not None:
        new_amount = amount
    else:
        await interaction.response.send_message("No amount provided.", ephemeral=True)
        return

    # prevent self-bid
    if highest_user == user.id:
        await interaction.response.send_message("أنت بالفعل أعلى مزايد 👑", ephemeral=True)
        return

    # min increment check
    min_inc = auction.get("min_increment") or DEFAULT_MIN_INCREMENT
    if new_amount - highest_amount < min_inc:
        await interaction.response.send_message(f"لازم تزيد على الأقل {fmt_amount(min_inc)} عن أعلى مزايدة.", ephemeral=True)
        return

    # write bid
    bid = await database.add_bid(auction_id, user.id, new_amount)
    # update last bid timestamp in settings
    await database.set_setting(f"last_bid_ts_{auction_id}", str(time.time()))

    # update panel (edit message)
    await _post_or_update_panel(interaction.client, auction)

    currency = await database.get_setting("currency_name") or "Credits"
    # ephemeral confirm
    await interaction.response.send_message(f"المزايدة قُبلت: **{fmt_amount(new_amount)} {currency}**", ephemeral=True)

    # ensure monitor running
    if auction_id not in AUCTION_MONITORS or (AUCTION_MONITORS[auction_id] and AUCTION_MONITORS[auction_id].done()):
        try:
            task = asyncio.create_task(monitor_auction(interaction.client, auction_id))
            AUCTION_MONITORS[auction_id] = task
        except Exception:
            pass

# ----- End current auction helper for admin command -----
async def end_current_auction(bot_client: discord.Client):
    auction = await database.get_active_auction()
    if not auction:
        return None
    await _finalize_auction(bot_client, auction["id"])
    return True