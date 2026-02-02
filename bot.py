# bot.py
"""
الملف الرئيسي لتشغيل البوت.
تأكد من أن باقي الملفات (database.py, auctions.py, ...) موجودة في نفس المجلد.
غير .env بقيمك ثم شغل: python bot.py
"""

import discord
from discord.ext import commands
from discord import app_commands
import traceback
import asyncio

from config import BOT_TOKEN, DEFAULT_COMMISSION, DEFAULT_CURRENCY, COOLDOWN_SECONDS
from database import init_db, set_setting, get_setting, all_settings, create_auction, get_active_auction
from auctions import AuctionView, build_auction_embed, handle_bid, end_current_auction
from bids import parse_amount, fmt_amount
from config import DEFAULT_AUCTION_DURATION_MIN, DEFAULT_MIN_INCREMENT

# Intents
intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = False
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Use the built-in tree attached to the bot (avoid creating a new CommandTree)
tree = bot.tree

# --- Helper: get allowed server id (from DB) ---
async def get_allowed_server_id() -> int | None:
    v = await get_setting("server_id")
    return int(v) if v else None

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    # init DB connection and ensure tables
    await init_db()

    # If server_id is set in settings, leave other guilds
    server_id = await get_allowed_server_id()
    if server_id:
        for g in list(bot.guilds):
            if g.id != server_id:
                try:
                    await g.leave()
                    print(f"Left guild {g.id} because not allowed.")
                except Exception as e:
                    print("Failed to leave guild:", e)

    # restore active auction panel if any
    active = await get_active_auction()
    if active:
        ch_id = await get_setting("auction_channel_id")
        currency = await get_setting("currency_name") or DEFAULT_CURRENCY
        if ch_id:
            try:
                ch = bot.get_channel(int(ch_id))
                if ch:
                    embed = build_auction_embed(active, currency_name=currency)
                    view = AuctionView(active["id"])
                    await ch.send(embed=embed, view=view)
            except Exception as e:
                print("Failed to restore auction panel:", e)

    # sync commands: prefer guild sync if allowed server is set (faster dev feedback)
    try:
        if server_id:
            guild_obj = discord.Object(id=server_id)
            await tree.sync(guild=guild_obj)
            print(f"Commands synced to guild {server_id}.")
        else:
            # global sync (may take time to propagate)
            await tree.sync()
            print("Commands synced globally.")
    except Exception as e:
        print("Failed to sync commands:", e)

# -------------------------
# CONFIG COMMANDS (English names, Arabic descriptions)
# -------------------------

@tree.command(name="config_set_server", description="تعيين السيرفر المسموح لتشغيل البوت (Set allowed server).")
@app_commands.describe(secret="Secret code (for exclusive actions, optional)")
async def config_set_server(interaction: discord.Interaction, secret: str = ""):
    if interaction.guild is None:
        await interaction.response.send_message("Execute this command in the server you want to allow.", ephemeral=True)
        return
    # require Manage Server or correct secret (if secret already set)
    current_secret = await get_setting("secret_code") or ""
    if not interaction.user.guild_permissions.manage_guild and (secret != current_secret):
        await interaction.response.send_message("You need Manage Server permission or the correct secret.", ephemeral=True)
        return
    await set_setting("server_id", str(interaction.guild.id))
    await set_setting("guild_name", interaction.guild.name)
    try:
        await tree.sync(guild=interaction.guild)
    except Exception:
        pass
    await interaction.response.send_message(f"تم تعيين السيرفر المسموح: {interaction.guild.name}", ephemeral=True)

@tree.command(name="config_set_role", description="تعيين رتبة 'رواد المزاد' (Role for bidding).")
@app_commands.describe(role="Role that can participate in auctions")
async def config_set_role(interaction: discord.Interaction, role: discord.Role):
    if interaction.guild is None:
        await interaction.response.send_message("Execute this command in the server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("You need Manage Roles permission.", ephemeral=True)
        return
    await set_setting("role_id", str(role.id))
    await interaction.response.send_message(f"تم تعيين رتبة الرواد: {role.name}", ephemeral=True)

@tree.command(name="config_set_channels", description="تعيين رومات المزاد و روم اللوق (Auction & Log channels).")
@app_commands.describe(auction_channel="Channel for auction panel", log_channel="Channel for logs")
async def config_set_channels(interaction: discord.Interaction, auction_channel: discord.TextChannel, log_channel: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Execute this command in the server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("You need Manage Channels permission.", ephemeral=True)
        return
    await set_setting("auction_channel_id", str(auction_channel.id))
    await set_setting("log_channel_id", str(log_channel.id))
    await interaction.response.send_message(f"تم تعيين قنوات المزاد واللوق.", ephemeral=True)

@tree.command(name="config_set_secret", description="تعيين أو تغيير الرمز السري (Secret code).")
@app_commands.describe(secret="Secret code string")
async def config_set_secret(interaction: discord.Interaction, secret: str):
    if interaction.guild is None:
        await interaction.response.send_message("Execute this command in the server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("You need Manage Server permission.", ephemeral=True)
        return
    await set_setting("secret_code", secret)
    await interaction.response.send_message("تم تحديث الرمز السري.", ephemeral=True)

@tree.command(name="config_set_misc", description="تعيين العمولة واسم العملة (Commission & Currency).")
@app_commands.describe(commission="Commission percent (e.g. 20)", currency="Display currency name (e.g. Credits)")
async def config_set_misc(interaction: discord.Interaction, commission: int = DEFAULT_COMMISSION, currency: str = DEFAULT_CURRENCY):
    if interaction.guild is None:
        await interaction.response.send_message("Execute this command in the server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("You need Manage Server permission.", ephemeral=True)
        return
    await set_setting("commission", str(commission))
    await set_setting("currency_name", currency)
    await interaction.response.send_message(f"Commission set to {commission}% and currency set to {currency}.", ephemeral=True)

@tree.command(name="config_show", description="عرض إعدادات البوت الحالية داخل السيرفر (Show bot config).")
async def config_show(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("Execute this command in the server.", ephemeral=True)
        return
    s = await all_settings()
    if not s:
        await interaction.response.send_message("No settings configured yet.", ephemeral=True)
        return
    lines = []
    for k, v in s.items():
        lines.append(f"**{k}**: {v}")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)

# -------------------------
# AUCTION MANAGEMENT COMMANDS (English names, Arabic descriptions)
# -------------------------

@tree.command(name="auction_open", description="فتح مزاد جديد و إنشاء لوحة المزاد.")
@app_commands.describe(start_bid="سعر البداية (e.g. 250k)", min_increment="أقل زيادة (e.g. 50k)", duration_minutes="مدة المزاد بالدقائق", secret="الرمز السري لفتح أكثر من مزاد (اختياري)")
async def auction_open(interaction: discord.Interaction, start_bid: str, min_increment: str, duration_minutes: int = DEFAULT_AUCTION_DURATION_MIN, secret: str = ""):
    if interaction.guild is None:
        await interaction.response.send_message("Execute in the server.", ephemeral=True)
        return

    # check allowed guild configured
    allowed = await get_setting("server_id")
    if allowed and int(allowed) != interaction.guild.id:
        await interaction.response.send_message("This bot is restricted to the configured server.", ephemeral=True)
        return

    # permission: only members with role OR manage_guild OR secret can open
    role_id = await get_setting("role_id")
    role_ok = False
    if role_id:
        role_id = int(role_id)
        role_ok = any(r.id == role_id for r in interaction.user.roles)
    current_secret = await get_setting("secret_code") or ""
    if not (role_ok or interaction.user.guild_permissions.manage_guild or secret == current_secret):
        await interaction.response.send_message("You don't have permission to open an auction.", ephemeral=True)
        return

    # check if there's already an active auction
    active = await get_active_auction()
    if active:
        await interaction.response.send_message("يوجد بالفعل مزاد نشط.", ephemeral=True)
        return

    # parse amounts
    try:
        sb = parse_amount(start_bid)
        mi = parse_amount(min_increment)
    except Exception:
        await interaction.response.send_message("Invalid number format. Use examples: 250k / 50k", ephemeral=True)
        return

    ends_at = int((__import__("time").time()) + duration_minutes * 60)
    record = await create_auction(interaction.user.id, sb, mi, ends_at)

    # post panel in auction channel
    ch_id = await get_setting("auction_channel_id")
    currency = await get_setting("currency_name") or DEFAULT_CURRENCY
    if ch_id:
        ch = bot.get_channel(int(ch_id))
        if ch:
            embed = build_auction_embed(record, currency_name=currency)
            view = AuctionView(record["id"])
            await ch.send(embed=embed, view=view)
    await interaction.response.send_message(f"Auction opened with start {fmt_amount(sb)}.", ephemeral=True)

@tree.command(name="auction_end", description="إنهاء المزاد وإعلان الفائز + تقرير اللوق")
async def auction_end(interaction: discord.Interaction):
    role_id = await get_setting("role_id")
    role_ok = False
    if role_id:
        role_ok = any(r.id == int(role_id) for r in interaction.user.roles)
    if not (role_ok or interaction.user.guild_permissions.manage_guild):
        await interaction.response.send_message("You don't have permission.", ephemeral=True)
        return
    res = await end_current_auction(bot)
    if res is None:
        await interaction.response.send_message("No active auction found.", ephemeral=True)
    else:
        await interaction.response.send_message("Auction ended and logged.", ephemeral=True)

@tree.command(name="auction_undo_last", description="حذف آخر مزايدة (للإدارة فقط)")
async def auction_undo_last(interaction: discord.Interaction):
    role_id = await get_setting("role_id")
    role_ok = False
    if role_id:
        role_ok = any(r.id == int(role_id) for r in interaction.user.roles)
    if not (role_ok or interaction.user.guild_permissions.manage_guild):
        await interaction.response.send_message("You don't have permission.", ephemeral=True)
        return
    from database import get_active_auction as db_get_active, undo_last_bid
    active = await db_get_active()
    if not active:
        await interaction.response.send_message("No active auction.", ephemeral=True)
        return
    undone = await undo_last_bid(active["id"])
    if undone:
        await interaction.response.send_message("Last bid removed.", ephemeral=True)
    else:
        await interaction.response.send_message("No bids to remove.", ephemeral=True)

@tree.command(name="auction_reset", description="تصفير المزاد بالكامل (خطر)")
@app_commands.describe(secret="Secret code is required to force reset")
async def auction_reset(interaction: discord.Interaction, secret: str):
    current_secret = await get_setting("secret_code") or ""
    if secret != current_secret and not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("Invalid secret or insufficient permission.", ephemeral=True)
        return
    active = await get_active_auction()
    if not active:
        await interaction.response.send_message("No active auction.", ephemeral=True)
        return
    # force end with no winner
    await end_current_auction(bot)  # end_current_auction will mark and log
    await interaction.response.send_message("Active auction force-ended.", ephemeral=True)

# -------------------------
# Interaction handling for buttons & modals
# -------------------------
@bot.event
async def on_interaction(interaction: discord.Interaction):
    try:
        data = getattr(interaction, "data", {}) or {}
        cid = data.get("custom_id", "")
        if cid and cid.startswith("bid_"):
            parts = cid.split("_")
            if len(parts) >= 3:
                typ = parts[1]
                auction_id = int(parts[2])
                if typ == "1k":
                    await handle_bid(interaction, auction_id, 1_000)
                    return
                if typ == "100k":
                    await handle_bid(interaction, auction_id, 100_000)
                    return
                if typ == "500k":
                    await handle_bid(interaction, auction_id, 500_000)
                    return
                if typ == "custom":
                    # create modal from auctions module
                    from auctions import BidModal
                    modal = BidModal(auction_id)
                    await interaction.response.send_modal(modal)
                    return
    except Exception:
        traceback.print_exc()
    # fall back to processing other application commands
    await bot.process_application_commands(interaction)

# Run
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("BOT_TOKEN not set in environment. Exiting.")
    else:
        bot.run(BOT_TOKEN)
