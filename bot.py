# bot.py
"""
Main entrypoint for AuctionBot.
- Reads BOT_TOKEN from environment (.env) and strips spaces/newlines to avoid invalid token errors.
- Initializes DB via database.init_db() which will try Postgres then fallback to local SQLite.
- Provides commands for config (server, role, channels, secret, misc), emoji management,
  auction management (open, end, undo last, reset), and db_retry.
- Handles interactions from buttons and modals (bid buttons & custom modal).
- Ensures panel message is edited instead of creating new messages on each bid.
"""

import os
import sys
import traceback
import asyncio
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

_RAW_BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_TOKEN = _RAW_BOT_TOKEN.strip() if isinstance(_RAW_BOT_TOKEN, str) else ""

if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN not set in environment. Set BOT_TOKEN in .env as BOT_TOKEN.")
    sys.exit(1)

# For debugging, only show length
print(f"INFO: BOT_TOKEN length = {len(BOT_TOKEN)}")
if any(c in _RAW_BOT_TOKEN for c in [" ", "\n", "\r"]):
    print("WARNING: BOT_TOKEN contained whitespace/newlines — they were stripped. Ensure exact token copy.")

# Import project modules (database wrapper will attempt Postgres -> local)
import database
from config import DEFAULT_COMMISSION, DEFAULT_CURRENCY, COOLDOWN_SECONDS, DEFAULT_AUCTION_DURATION_MIN, DEFAULT_MIN_INCREMENT
from auctions import AuctionView, build_auction_embed, handle_bid, end_current_auction
from bids import parse_amount, fmt_amount
import emojis

# Intents
intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = False
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree  # use bot's built-in CommandTree

# -------------------------
# Helper to initialize DB
# -------------------------
async def _init_db_with_logging():
    try:
        await database.init_db()
    except Exception as e:
        print("ERROR during database.init_db():", e)
        traceback.print_exc()

# -------------------------
# on_ready
# -------------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    # init DB
    await _init_db_with_logging()

    # If server_id set, leave other guilds
    try:
        server_id = await database.get_setting("server_id")
        if server_id:
            sid = int(server_id)
            for g in list(bot.guilds):
                if g.id != sid:
                    try:
                        await g.leave()
                        print(f"Left guild {g.id} (not allowed).")
                    except Exception:
                        pass
    except Exception as e:
        print("Warning while checking server_id:", e)

    # restore active auctions by editing existing panel messages if possible
    try:
        active = await database.get_active_auction()
        if active:
            panel_msg = await database.get_setting(f"panel_msg_{active['id']}")
            panel_ch = await database.get_setting(f"panel_channel_{active['id']}")
            currency = await database.get_setting("currency_name") or DEFAULT_CURRENCY
            if panel_ch and panel_msg:
                try:
                    ch = bot.get_channel(int(panel_ch))
                    if ch:
                        msg = None
                        try:
                            msg = await ch.fetch_message(int(panel_msg))
                        except Exception:
                            msg = None
                        embed = build_auction_embed(active, currency_name=currency)
                        view = AuctionView(active["id"])
                        if msg:
                            try:
                                await msg.edit(embed=embed, view=view)
                            except Exception:
                                new_msg = await ch.send(embed=embed, view=view)
                                await database.set_setting(f"panel_msg_{active['id']}", str(new_msg.id))
                        else:
                            new_msg = await ch.send(embed=embed, view=view)
                            await database.set_setting(f"panel_msg_{active['id']}", str(new_msg.id))
                except Exception as e:
                    print("Failed to restore auction panel:", e)
    except Exception as e:
        print("Warning while restoring auction:", e)

    # sync commands
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
@app_commands.describe(secret="Secret code (optional for exclusive actions)")
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

@tree.command(name="config_set_channels", description="تعيين قنوات المزاد وروم اللوق (Set auction & log channels).")
@app_commands.describe(auction_channel="Channel for auction panel (single)", log_channel="Channel for logs")
async def config_set_channels(interaction: discord.Interaction, auction_channel: discord.TextChannel, log_channel: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Execute this command in the server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("You need Manage Channels permission.", ephemeral=True)
        return
    # set single auction channel (overwrites list) and log channel
    await database.set_setting("auction_channel_ids", str(auction_channel.id))
    await database.set_setting("log_channel_id", str(log_channel.id))
    await interaction.response.send_message("Set auction channel and log channel.", ephemeral=True)

@tree.command(name="config_add_channel", description="أضف قناة مزاد إلى القائمة (Add auction channel).")
@app_commands.describe(channel="Text channel to add")
async def config_add_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Run this in the server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("You need Manage Channels permission.", ephemeral=True)
        return
    val = await database.get_setting("auction_channel_ids") or ""
    ids = [s for s in val.split(",") if s]
    if str(channel.id) in ids:
        await interaction.response.send_message("This channel is already an auction channel.", ephemeral=True)
        return
    ids.append(str(channel.id))
    await database.set_setting("auction_channel_ids", ",".join(ids))
    await interaction.response.send_message(f"Added {channel.mention} to auction channels.", ephemeral=True)

@tree.command(name="config_remove_channel", description="أزل قناة من قائمة قنوات المزاد (Remove auction channel).")
@app_commands.describe(channel="Text channel to remove")
async def config_remove_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("Run this in the server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("You need Manage Channels permission.", ephemeral=True)
        return
    val = await database.get_setting("auction_channel_ids") or ""
    ids = [s for s in val.split(",") if s]
    if str(channel.id) not in ids:
        await interaction.response.send_message("Channel not in auction list.", ephemeral=True)
        return
    ids.remove(str(channel.id))
    await database.set_setting("auction_channel_ids", ",".join(ids))
    await interaction.response.send_message(f"Removed {channel.mention} from auction channels.", ephemeral=True)

@tree.command(name="config_list_channels", description="عرض قنوات المزاد المفعّلة (List auction channels).")
async def config_list_channels(interaction: discord.Interaction):
    val = await database.get_setting("auction_channel_ids") or ""
    ids = [s for s in val.split(",") if s]
    if not ids:
        await interaction.response.send_message("No auction channels configured.", ephemeral=True)
        return
    mentions = []
    for i in ids:
        try:
            mentions.append(f"<#{int(i)}>")
        except Exception:
            mentions.append(i)
    await interaction.response.send_message("Auction channels:\n" + "\n".join(mentions), ephemeral=True)

@tree.command(name="config_set_secret", description="تعيين الرمز السري (Set secret code).")
@app_commands.describe(secret="Secret code string")
async def config_set_secret(interaction: discord.Interaction, secret: str):
    if interaction.guild is None:
        await interaction.response.send_message("Run in server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("You need Manage Server permission.", ephemeral=True)
        return
    await database.set_setting("secret_code", secret)
    await interaction.response.send_message("Secret updated.", ephemeral=True)

@tree.command(name="config_set_misc", description="تعيين العمولة واسم العملة (Set commission & currency).")
@app_commands.describe(commission="Commission percent (e.g. 20)", currency="Display currency name (e.g. Credits)")
async def config_set_misc(interaction: discord.Interaction, commission: int, currency: str):
    if interaction.guild is None:
        await interaction.response.send_message("Run in server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("You need Manage Server permission.", ephemeral=True)
        return
    await database.set_setting("commission", str(commission))
    await database.set_setting("currency_name", currency)
    await interaction.response.send_message(f"Commission set to {commission}% and currency set to {currency}.", ephemeral=True)

@tree.command(name="config_show", description="عرض إعدادات البوت الحالية (Show bot config).")
async def config_show(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("Run in server.", ephemeral=True)
        return
    s = await database.all_settings()
    if not s:
        await interaction.response.send_message("No settings configured yet.", ephemeral=True)
        return
    lines = [f"**{k}**: {v}" for k, v in s.items()]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)

# Emoji commands
@tree.command(name="config_set_emoji", description="Set a named emoji (server custom or unicode).")
@app_commands.describe(name="Key name (e.g. fire, celebrate)", emoji="Emoji string or server emoji like <:name:id> or 🔥")
async def config_set_emoji(interaction: discord.Interaction, name: str, emoji: str):
    if interaction.guild is None:
        await interaction.response.send_message("Run in server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("You need Manage Server permission.", ephemeral=True)
        return
    name = name.strip().lower()
    if not name:
        await interaction.response.send_message("Invalid name.", ephemeral=True)
        return
    try:
        await emojis.set_emoji(name, emoji)
        await interaction.response.send_message(f"Emoji for '{name}' set to: {emoji}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Failed to set emoji: {e}", ephemeral=True)

@tree.command(name="config_list_emojis", description="List emoji keys and values.")
async def config_list_emojis(interaction: discord.Interaction):
    try:
        mapping = await emojis.list_emojis()
    except Exception as e:
        await interaction.response.send_message(f"Failed to list emojis: {e}", ephemeral=True)
        return
    lines = [f"**{k}**: {v}" for k, v in mapping.items()]
    await interaction.response.send_message("\n".join(lines) if lines else "No emojis configured.", ephemeral=True)

# -------------------------
# DB retry command
# -------------------------
@tree.command(name="db_retry", description="Retry connecting to remote Postgres.")
async def db_retry(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("Admins only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        await database.init_db()
        await interaction.followup.send("Reattempted DB init; check logs for details.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Retry failed: {e}", ephemeral=True)

# -------------------------
# AUCTION MANAGEMENT COMMANDS
# -------------------------
@tree.command(name="auction_open", description="فتح مزاد جديد و إنشاء لوحة المزاد.")
@app_commands.describe(start_bid="سعر البداية (e.g. 250k)", min_increment="أقل زيادة (e.g. 50k)", duration_minutes="مدة المزاد بالدقائق", secret="Secret code (optional)")
async def auction_open(interaction: discord.Interaction, start_bid: str, min_increment: str, duration_minutes: int = DEFAULT_AUCTION_DURATION_MIN, secret: str = ""):
    if interaction.guild is None:
        await interaction.response.send_message("Run in server.", ephemeral=True)
        return
    # check allowed guild
    allowed = await database.get_setting("server_id")
    if allowed and int(allowed) != interaction.guild.id:
        await interaction.response.send_message("This bot is restricted to the configured server.", ephemeral=True)
        return
    # permission: role or manage_guild or secret
    role_id = await database.get_setting("role_id")
    role_ok = False
    if role_id:
        role_ok = any(r.id == int(role_id) for r in interaction.user.roles)
    current_secret = await database.get_setting("secret_code") or ""
    if not (role_ok or interaction.user.guild_permissions.manage_guild or secret == current_secret):
        await interaction.response.send_message("You don't have permission to open an auction.", ephemeral=True)
        return
    # ensure no active auction
    active = await database.get_active_auction()
    if active:
        await interaction.response.send_message("يوجد بالفعل مزاد نشط.", ephemeral=True)
        return
    # parse amounts
    try:
        sb = parse_amount(start_bid)
        mi = parse_amount(min_increment)
    except Exception:
        await interaction.response.send_message("Invalid number format. Use: 250k / 50k", ephemeral=True)
        return
    ends_at = int(time.time() + duration_minutes * 60)
    record = await database.create_auction(interaction.user.id, sb, mi, ends_at)
    # post panel in chosen auction channel
    # choose first auction channel from list
    cfg = await database.get_setting("auction_channel_ids") or ""
    ids = [s for s in cfg.split(",") if s]
    ch = None
    if ids:
        try:
            ch = bot.get_channel(int(ids[0]))
        except Exception:
            ch = None
    if ch:
        embed = build_auction_embed(record, currency_name=(await database.get_setting("currency_name") or DEFAULT_CURRENCY))
        view = AuctionView(record["id"])
        msg = await ch.send(embed=embed, view=view)
        await database.set_setting(f"panel_msg_{record['id']}", str(msg.id))
        await database.set_setting(f"panel_channel_{record['id']}", str(ch.id))
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
        # update panel
        await asyncio.sleep(0.5)
        await (await auctions._post_or_update_panel(bot, active)) if 'auctions' in globals() else None
        await interaction.response.send_message("Last bid removed.", ephemeral=True)
    else:
        await interaction.response.send_message("No bids to remove.", ephemeral=True)

@tree.command(name="auction_reset", description="تصفير المزاد بالكامل (خطر)")
@app_commands.describe(secret="Secret code required")
async def auction_reset(interaction: discord.Interaction, secret: str):
    current_secret = await database.get_setting("secret_code") or ""
    if secret != current_secret and not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("Invalid secret or insufficient permission.", ephemeral=True)
        return
    active = await database.get_active_auction()
    if not active:
        await interaction.response.send_message("No active auction.", ephemeral=True)
        return
    # force end
    await end_current_auction(bot)
    await interaction.response.send_message("Active auction force-ended.", ephemeral=True)

# -------------------------
# Interaction handler for buttons & modals
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
                    await handle_bid(interaction, auction_id, increment=1_000)
                    return
                if typ == "100k":
                    await handle_bid(interaction, auction_id, increment=100_000)
                    return
                if typ == "500k":
                    await handle_bid(interaction, auction_id, increment=500_000)
                    return
                if typ == "custom":
                    from auctions import BidModal
                    modal = BidModal(auction_id)
                    await interaction.response.send_modal(modal)
                    return
    except Exception:
        traceback.print_exc()
    # do not call bot.process_application_commands

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    try:
        bot.run(BOT_TOKEN)
    except Exception as e:
        print("Bot failed to start:", type(e).__name__, str(e))
        traceback.print_exc()
        sys.exit(1)