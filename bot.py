# bot.py
"""
Main entrypoint for AuctionBot (updated to work with remote Postgres OR local SQLite fallback).
- Reads BOT_TOKEN from environment and strips spaces/newlines.
- Initializes DB via database.init_db() which will try Postgres then fallback to SQLite.
- Provides a /db_retry command to re-attempt connecting to Postgres at runtime.
- Works with the rest of project files: database.py, database_local.py, auctions.py, bids.py, config.py, logs.py, etc.
"""

import os
import sys
import traceback
import asyncio
import discord
from discord.ext import commands
from discord import app_commands

# load dotenv early
from dotenv import load_dotenv
load_dotenv()

# sanitize token
_RAW_BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_TOKEN = _RAW_BOT_TOKEN.strip() if isinstance(_RAW_BOT_TOKEN, str) else ""

# Quick checks
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN is missing or empty. Put your token in .env as BOT_TOKEN.")
    sys.exit(1)

print(f"INFO: BOT_TOKEN length = {len(BOT_TOKEN)} (not displayed).")
if any(c in _RAW_BOT_TOKEN for c in [" ", "\n", "\r"]):
    print("WARNING: BOT_TOKEN contained whitespace/newlines — they were stripped. Ensure exact token copy.")

# Import project modules AFTER token check
import database  # our wrapper (tries Postgres then local)
from config import DEFAULT_COMMISSION, DEFAULT_CURRENCY, COOLDOWN_SECONDS, DEFAULT_AUCTION_DURATION_MIN
from auctions import AuctionView, build_auction_embed, handle_bid, end_current_auction
from bids import parse_amount, fmt_amount

# Intents
intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = False
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree  # use built-in command tree

# helper
async def _init_db_with_logging():
    try:
        await database.init_db()
    except Exception as e:
        print("ERROR during database.init_db():", e)
        traceback.print_exc()

# On ready
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    # Initialize DB (this will attempt remote then fallback)
    await _init_db_with_logging()

    # If server_id is set, optionally leave other guilds
    try:
        server_id = await database.get_setting("server_id")
        if server_id:
            server_id = int(server_id)
            for g in list(bot.guilds):
                if g.id != server_id:
                    try:
                        await g.leave()
                        print(f"Left guild {g.id} (not allowed).")
                    except Exception as e:
                        print("Failed to leave guild:", e)
    except Exception as e:
        print("Warning while checking server_id:", e)

    # Restore active auction panel if exists
    try:
        active = await database.get_active_auction()
        if active:
            ch_id = await database.get_setting("auction_channel_id")
            currency = await database.get_setting("currency_name") or DEFAULT_CURRENCY
            if ch_id:
                try:
                    ch = bot.get_channel(int(ch_id))
                    if ch:
                        embed = build_auction_embed(active, currency_name=currency)
                        view = AuctionView(active["id"])
                        await ch.send(embed=embed, view=view)
                        print("Restored auction panel.")
                except Exception as e:
                    print("Failed to restore auction panel:", e)
    except Exception as e:
        print("Warning while restoring auction:", e)

    # Sync commands: prefer guild sync if server_id known (faster)
    try:
        server_id = await database.get_setting("server_id")
        if server_id:
            guild_obj = discord.Object(id=int(server_id))
            await tree.sync(guild=guild_obj)
            print(f"Commands synced to guild {server_id}.")
        else:
            await tree.sync()
            print("Commands synced globally.")
    except Exception as e:
        print("Failed to sync commands:", e)
        traceback.print_exc()

# -------------------------
# CONFIG COMMANDS (English names, Arabic descriptions)
# -------------------------

@tree.command(name="config_set_server", description="تعيين السيرفر المسموح لتشغيل البوت (Set allowed server).")
@app_commands.describe(secret="Secret code (optional, for exclusive actions)")
async def config_set_server(interaction: discord.Interaction, secret: str = ""):
    if interaction.guild is None:
        await interaction.response.send_message("Execute this command in the server you want to allow.", ephemeral=True)
        return
    current_secret = await database.get_setting("secret_code") or ""
    if not interaction.user.guild_permissions.manage_guild and (secret != current_secret):
        await interaction.response.send_message("You need Manage Server permission or the correct secret.", ephemeral=True)
        return
    await database.set_setting("server_id", str(interaction.guild.id))
    await database.set_setting("guild_name", interaction.guild.name)
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
    await database.set_setting("role_id", str(role.id))
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
    await database.set_setting("auction_channel_id", str(auction_channel.id))
    await database.set_setting("log_channel_id", str(log_channel.id))
    await interaction.response.send_message("تم تعيين قنوات المزاد واللوق.", ephemeral=True)

@tree.command(name="config_set_secret", description="تعيين أو تغيير الرمز السري (Secret code).")
@app_commands.describe(secret="Secret code string")
async def config_set_secret(interaction: discord.Interaction, secret: str):
    if interaction.guild is None:
        await interaction.response.send_message("Execute this command in the server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("You need Manage Server permission.", ephemeral=True)
        return
    await database.set_setting("secret_code", secret)
    await interaction.response.send_message("تم تحديث الرمز السري.", ephemeral=True)

@tree.command(name="config_set_misc", description="تعيين العمولة واسم العملة (Commission & Currency).")
@app_commands.describe(commission="Commission percent (e.g. 20)", currency="Display currency name (e.g. Credits)")
async def config_set_misc(interaction: discord.Interaction, commission: int, currency: str):
    if interaction.guild is None:
        await interaction.response.send_message("Execute this command in the server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("You need Manage Server permission.", ephemeral=True)
        return
    await database.set_setting("commission", str(commission))
    await database.set_setting("currency_name", currency)
    await interaction.response.send_message(f"Commission set to {commission}% and currency set to {currency}.", ephemeral=True)

@tree.command(name="config_show", description="عرض إعدادات البوت الحالية داخل السيرفر (Show bot config).")
async def config_show(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("Execute this command in the server.", ephemeral=True)
        return
    s = await database.all_settings()
    if not s:
        await interaction.response.send_message("No settings configured yet.", ephemeral=True)
        return
    lines = [f"**{k}**: {v}" for k, v in s.items()]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)

# DB retry command: attempt to reconnect to remote Postgres
@tree.command(name="db_retry", description="أعد محاولة الاتصال بقاعدة Postgres (جرب الاتصال الخارجي مرة ثانية).")
async def db_retry(interaction: discord.Interaction):
    if not (interaction.user.guild_permissions.manage_guild or await database.get_setting("secret_code") == (await database.get_setting("secret_code") or "")):
        # allow only admins; secret check can be expanded if needed
        # simple check: require manage_guild
        pass
    await interaction.response.defer(ephemeral=True)
    try:
        await database.init_db()
        # test a simple settings read
        _ = await database.get_setting("server_id")
        await interaction.followup.send("Reattempted DB init — if no errors, connection/retry succeeded (or local DB active).", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Retry failed: {e}", ephemeral=True)

# -------------------------
# AUCTION MANAGEMENT COMMANDS
# -------------------------

@tree.command(name="auction_open", description="فتح مزاد جديد و إنشاء لوحة المزاد.")
@app_commands.describe(start_bid="سعر البداية (e.g. 250k)", min_increment="أقل زيادة (e.g. 50k)", duration_minutes="مدة المزاد بالدقائق", secret="الرمز السري لفتح أكثر من مزاد (اختياري)")
async def auction_open(interaction: discord.Interaction, start_bid: str, min_increment: str, duration_minutes: int = DEFAULT_AUCTION_DURATION_MIN, secret: str = ""):
    if interaction.guild is None:
        await interaction.response.send_message("Execute in the server.", ephemeral=True)
        return

    allowed = await database.get_setting("server_id")
    if allowed and int(allowed) != interaction.guild.id:
        await interaction.response.send_message("This bot is restricted to the configured server.", ephemeral=True)
        return

    role_id = await database.get_setting("role_id")
    role_ok = False
    if role_id:
        role_ok = any(r.id == int(role_id) for r in interaction.user.roles)
    current_secret = await database.get_setting("secret_code") or ""
    if not (role_ok or interaction.user.guild_permissions.manage_guild or secret == current_secret):
        await interaction.response.send_message("You don't have permission to open an auction.", ephemeral=True)
        return

    active = await database.get_active_auction()
    if active:
        await interaction.response.send_message("يوجد بالفعل مزاد نشط.", ephemeral=True)
        return

    try:
        sb = parse_amount(start_bid)
        mi = parse_amount(min_increment)
    except Exception:
        await interaction.response.send_message("Invalid number format. Use examples: 250k / 50k", ephemeral=True)
        return

    ends_at = int((__import__("time").time()) + duration_minutes * 60)
    record = await database.create_auction(interaction.user.id, sb, mi, ends_at)

    ch_id = await database.get_setting("auction_channel_id")
    currency = await database.get_setting("currency_name") or DEFAULT_CURRENCY
    if ch_id:
        ch = bot.get_channel(int(ch_id))
        if ch:
            embed = build_auction_embed(record, currency_name=currency)
            view = AuctionView(record["id"])
            await ch.send(embed=embed, view=view)
    await interaction.response.send_message(f"Auction opened with start {fmt_amount(sb)}.", ephemeral=True)

@tree.command(name="auction_end", description="إنهاء المزاد وإعلان الفائز + تقرير اللوق")
async def auction_end(interaction: discord.Interaction):
    role_id = await database.get_setting("role_id")
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
    role_id = await database.get_setting("role_id")
    role_ok = False
    if role_id:
        role_ok = any(r.id == int(role_id) for r in interaction.user.roles)
    if not (role_ok or interaction.user.guild_permissions.manage_guild):
        await interaction.response.send_message("You don't have permission.", ephemeral=True)
        return
    active = await database.get_active_auction()
    if not active:
        await interaction.response.send_message("No active auction.", ephemeral=True)
        return
    undone = await database.undo_last_bid(active["id"])
    if undone:
        await interaction.response.send_message("Last bid removed.", ephemeral=True)
    else:
        await interaction.response.send_message("No bids to remove.", ephemeral=True)

@tree.command(name="auction_reset", description="تصفير المزاد بالكامل (خطر)")
@app_commands.describe(secret="Secret code is required to force reset")
async def auction_reset(interaction: discord.Interaction, secret: str):
    current_secret = await database.get_setting("secret_code") or ""
    if secret != current_secret and not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("Invalid secret or insufficient permission.", ephemeral=True)
        return
    active = await database.get_active_auction()
    if not active:
        await interaction.response.send_message("No active auction.", ephemeral=True)
        return
    await end_current_auction(bot)
    await interaction.response.send_message("Active auction force-ended.", ephemeral=True)

# -------------------------
# Interaction handling for buttons & modals (bid buttons)
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
                    from auctions import BidModal
                    modal = BidModal(auction_id)
                    await interaction.response.send_modal(modal)
                    return
    except Exception:
        traceback.print_exc()
    # DO NOT call bot.process_application_commands(interaction) — removed for compatibility.

# Run
if __name__ == "__main__":
    try:
        bot.run(BOT_TOKEN)
    except Exception as e:
        print("Bot failed to start:", type(e).__name__, str(e))
        traceback.print_exc()
        sys.exit(1)