# AuctionBot v2.0 Enhanced 🎯

بوت مزادات ديسكورد احترافي مع ميزات متقدمة ونظام مراقبة تلقائي.

Professional Discord Auction Bot with advanced features and automatic monitoring.

---

## ✨ Features / الميزات

### العربية:
- 🎯 **نظام مزادات كامل**: فتح، إدارة، وإنهاء المزادات
- 💰 **أزرار مزايدة سريعة**: +1K, +100K, +500K + مزايدة مخصصة
- ⏱️ **عد تنازلي تلقائي**: عند عدم النشاط لمدة 30 ثانية
- 🔥 **رسائل ترويجية**: لتشجيع المزايدة (قابلة للتخصيص)
- 📊 **تقارير مفصلة**: سجل كامل لكل مزاد
- 🎨 **إيموجي مخصصة**: دعم إيموجي السيرفر و Unicode
- 🔒 **نظام صلاحيات**: رتب، أسرار، وصلاحيات متعددة
- 💾 **قاعدة بيانات مزدوجة**: PostgreSQL مع احتياطي SQLite
- 🐛 **أوامر Debug**: لتشخيص المشاكل وعرض الحالة
- ⚡ **أداء محسّن**: معالجة أخطاء شاملة وإعادة محاولة تلقائية

### English:
- 🎯 **Complete auction system**: Open, manage, and end auctions
- 💰 **Quick bid buttons**: +1K, +100K, +500K + custom bid
- ⏱️ **Automatic countdown**: After 30 seconds of inactivity
- 🔥 **Promotional messages**: To encourage bidding (customizable)
- 📊 **Detailed reports**: Complete log for every auction
- 🎨 **Custom emojis**: Server emoji & Unicode support
- 🔒 **Permission system**: Roles, secrets, and multiple permissions
- 💾 **Dual database**: PostgreSQL with SQLite fallback
- 🐛 **Debug commands**: For diagnostics and status display
- ⚡ **Optimized performance**: Comprehensive error handling and auto-retry

---

## 📋 Requirements / المتطلبات

- Python 3.10 or higher
- Discord Bot Token
- (Optional) PostgreSQL database

---

## 🚀 Installation / التثبيت

### 1. Clone the repository:
```bash
git clone <your-repo-url>
cd AuctionBot1
```

### 2. Install dependencies:
```bash
pip install -r requirements.txt
```

### 3. Create `.env` file:
```env
BOT_TOKEN=your_discord_bot_token_here

# Optional: PostgreSQL connection
DATABASE_URL=postgresql://user:password@host:port/database

# Optional: Bot configuration
DEFAULT_COMMISSION=20
DEFAULT_CURRENCY=Credits
COOLDOWN_SECONDS=2
DEBUG_MODE=False
```

### 4. Run the bot:
```bash
python bot.py
```

---

## ⚙️ Configuration / الإعدادات

### Initial Setup Commands / أوامر الإعداد الأولية:

#### 1. Set server restriction:
```
/config_set_server
```
لتحديد السيرفر المسموح للبوت بالعمل فيه

#### 2. Set auction role:
```
/config_set_role role:@YourRole
```
لتحديد الرتبة المطلوبة للمزايدة

#### 3. Set channels:
```
/config_set_channels auction_channel:#auction log_channel:#logs
```
لتحديد قناة المزاد وقناة السجلات

#### 4. Set commission & currency:
```
/config_set_misc commission:20 currency:Credits
```
لتحديد نسبة العمولة واسم العملة

#### 5. (Optional) Set secret code:
```
/config_set_secret secret:your_secret_code
```
لتحديد رمز سري للإجراءات الحساسة

---

## 🎯 Usage / الاستخدام

### Opening an Auction / فتح مزاد:

```
/auction_open start_bid:250k min_increment:50k duration_minutes:5
```

**Parameters:**
- `start_bid`: Starting bid amount (supports: 250k, 2.5m, 1000000)
- `min_increment`: Minimum bid increase
- `duration_minutes`: Auction duration (1-1440 minutes)
- `secret`: (Optional) Secret code if required

### Bidding / المزايدة:

Users can bid using the interactive panel buttons:
- **+1K**: Increase by 1,000
- **+100K**: Increase by 100,000
- **+500K**: Increase by 500,000
- **Custom**: Enter custom amount

### Managing Auctions / إدارة المزادات:

```
/auction_end          # إنهاء المزاد يدوياً
/auction_undo_last    # حذف آخر مزايدة
```

---

## 🐛 Debug Commands / أوامر التشخيص

### Check bot status:
```
/debug_status
```
Shows: uptime, database status, guild count, active auction

### Check auction details:
```
/debug_auction
```
Shows: detailed auction info, bids, timing, panel status

### Retry PostgreSQL:
```
/db_retry
```
Attempts to reconnect to PostgreSQL if using fallback

---

## 🎨 Emoji Customization / تخصيص الإيموجي

### Set custom emoji:
```
/emoji_set name:fire emoji:🔥
/emoji_set name:custom emoji:<:customname:123456789>
```

### List all emojis:
```
/emoji_list
```

**Default Emojis:**
- `fire` 🔥
- `money` 💰
- `trophy` 🏆
- `celebrate` 🎉
- `crown` 👑
- `rocket` 🚀
- And more...

---

## 📊 Database / قاعدة البيانات

### PostgreSQL (Recommended):
Set `DATABASE_URL` in `.env`:
```
DATABASE_URL=postgresql://user:password@host:port/database
```

### SQLite (Automatic Fallback):
If PostgreSQL connection fails, bot automatically uses local SQLite database (`local_db.sqlite`).

### Tables:
- `settings`: Bot configuration
- `auctions`: Auction records
- `bids`: Bid history

---

## 🔒 Permissions / الصلاحيات

### Required Bot Permissions:
- Send Messages
- Embed Links
- Read Message History
- Add Reactions
- Manage Messages
- View Channel

### User Permissions:
1. **Auction Participant**: Needs assigned role
2. **Auction Manager**: Needs role OR admin permissions
3. **Configuration**: Needs "Manage Server" or "Manage Roles"

---

## 🛡️ Security Features / ميزات الأمان

- ✅ Server restriction (single guild lock)
- ✅ Role-based access control
- ✅ Secret code protection
- ✅ Permission validation
- ✅ Rate limiting (cooldowns)
- ✅ Input validation & sanitization

---

## ⚡ Performance Optimizations / تحسينات الأداء

- Async/await throughout
- Connection pooling (PostgreSQL)
- WAL mode (SQLite)
- Emoji caching
- Automatic database fallback
- Retry logic with exponential backoff
- Panel update batching

---

## 🔧 Troubleshooting / حل المشاكل

### Problem: Bot not responding
**Solution:**
1. Check `/debug_status` for bot status
2. Verify bot has required permissions
3. Check console for errors

### Problem: Cannot open auction
**Solution:**
1. Verify role is configured: `/config_show`
2. Check channel permissions: `/debug_status`
3. Ensure no active auction exists

### Problem: Database connection issues
**Solution:**
1. Check `DATABASE_URL` format
2. Try `/db_retry` to reconnect
3. Bot will auto-fallback to SQLite

### Problem: Emojis not showing
**Solution:**
1. Verify emoji format: `<:name:id>` for server emojis
2. Check bot can access the emoji (same server or nitro)
3. Use `/emoji_list` to see configured emojis

---

## 📝 Configuration File / ملف الإعدادات

All settings are stored in the database. View with:
```
/config_show
```

**Key Settings:**
- `server_id`: Restricted server ID
- `role_id`: Auction participant role
- `auction_channel_ids`: Comma-separated channel IDs
- `log_channel_id`: Log channel ID
- `commission`: Commission percentage
- `currency_name`: Display currency name
- `secret_code`: Admin secret code

---

## 🔄 Update Guide / دليل التحديث

### From Previous Version:

1. Backup your database:
```bash
# For SQLite
cp local_db.sqlite local_db.sqlite.backup

# For PostgreSQL
pg_dump yourdb > backup.sql
```

2. Replace all files except `.env`

3. Install new dependencies:
```bash
pip install -r requirements.txt --upgrade
```

4. Restart the bot:
```bash
python bot.py
```

5. Verify with `/debug_status`

---

## 📚 API Reference / مرجع API

### Main Functions:

**auctions.py:**
- `handle_bid()`: Process user bid
- `monitor_auction()`: Monitor auction activity
- `build_auction_embed()`: Create auction display
- `end_current_auction()`: Finalize auction

**database.py:**
- `init_db()`: Initialize connection
- `create_auction()`: Create new auction
- `add_bid()`: Record bid
- `get_active_auction()`: Get current auction

**security.py:**
- `has_auction_role()`: Check user role
- `check_bot_permissions()`: Verify permissions
- `can_open_auction()`: Validate auction opening

**bids.py:**
- `parse_amount()`: Parse bid strings
- `fmt_amount()`: Format display
- `validate_amount()`: Validate bid

---

## 🌟 Advanced Features / ميزات متقدمة

### Promotional System:
Customizable Arabic messages sent during inactivity to encourage bidding.

**Templates in `auctions.py`:**
```python
PROMO_TEMPLATES = [
    "{fire} **زيد أكثر وولعها!** {mention} دفع **{amount}**!",
    # Add your own templates...
]
```

### Countdown System:
3-second countdown before auction ends (after 30s inactivity).

### Automatic Monitoring:
Background tasks monitor auctions and trigger finalization automatically.

### Database Fallback:
Seamless switch between PostgreSQL and SQLite without data loss.

---

## 🤝 Contributing / المساهمة

Contributions welcome! Please:
1. Fork the repository
2. Create feature branch
3. Commit changes
4. Push to branch
5. Open Pull Request

---

## 📄 License / الترخيص

[Specify your license here]

---

## 📞 Support / الدعم

For issues or questions:
- Open an issue on GitHub
- Contact: [Your contact info]

---

## 🎉 Credits / الشكر

Developed by [Your Name]

Special thanks to:
- discord.py community
- Contributors and testers

---

## 📋 Changelog / سجل التغييرات

### v2.0 Enhanced (Current)
- ✅ Fixed missing imports (time, traceback)
- ✅ Fixed `auction_undo_last` command
- ✅ Added comprehensive error handling
- ✅ Added debug commands
- ✅ Added permission validation
- ✅ Improved database connection handling
- ✅ Enhanced emoji system with caching
- ✅ Better logging and monitoring
- ✅ Improved documentation

### v1.0 (Original)
- Basic auction functionality
- Button-based bidding
- Simple monitoring

---

## 🔮 Roadmap / خطة المستقبل

- [ ] Anti-snipe feature (time extension)
- [ ] Multiple simultaneous auctions
- [ ] Bid history per user
- [ ] Statistics dashboard
- [ ] Web interface
- [ ] API endpoints
- [ ] Auction templates
- [ ] Scheduled auctions

---

**Made with ❤️ for the Arabic Discord community**

**صُنع بحب ❤️ لمجتمع ديسكورد العربي**
