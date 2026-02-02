# Changelog

All notable changes to AuctionBot will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [2.0.0] - Enhanced Version - 2024

### 🔥 Major Changes

#### Fixed Critical Bugs
- **[CRITICAL]** Fixed missing `import time` in `auctions.py` - caused bot to crash
- **[CRITICAL]** Fixed missing `import traceback` in `auctions.py` - prevented error logging
- **[CRITICAL]** Fixed `auction_undo_last` command - was calling invalid function
- **[BUG]** Fixed panel message not being created on auction open
- **[BUG]** Fixed monitor task not starting automatically
- **[BUG]** Fixed database connection not retrying on failure

#### Added Features
- ✅ **Debug Commands**: Added `/debug_status` and `/debug_auction` for diagnostics
- ✅ **Permission Validation**: Bot now checks its own permissions before creating panels
- ✅ **Better Error Messages**: Clear, actionable error messages in Arabic and English
- ✅ **Database Status**: Added connection status tracking and manual retry command
- ✅ **Emoji Caching**: Implemented caching for faster emoji lookups
- ✅ **Comprehensive Logging**: Detailed logs for all operations (when DEBUG_MODE=True)

#### Improved Functionality
- 🔧 **Database Layer**: Complete rewrite with better error handling and fallback logic
- 🔧 **Security Module**: Enhanced with multiple permission checks and validation
- 🔧 **Emoji System**: Better support for Discord custom emojis with validation
- 🔧 **Bid Processing**: More robust parsing and validation
- 🔧 **Panel Updates**: Optimized update logic with rate limiting
- 🔧 **Monitor System**: More reliable auction monitoring with better state management

---

## [2.0.0] - Detailed Changes by File

### `config.py`
**Added:**
- More configuration constants
- Color codes for embeds
- Feature flags (ENABLE_PROMO_MESSAGES, etc.)
- Validation limits (MIN_BID_AMOUNT, MAX_BID_AMOUNT)
- Arabic error message templates
- Debug and logging flags

**Changed:**
- Better organization with sections
- Added docstrings
- Exported key constants via __all__

### `bids.py`
**Added:**
- Custom exceptions: `BidParseError`, `BidValidationError`
- `validate_amount()` function for range checking
- `parse_and_validate()` for combined operation
- `compare_amounts()` for displaying differences
- `calculate_commission()` utility function
- Support for 't' suffix (trillions)
- Self-test functionality

**Improved:**
- Better error messages
- More robust parsing
- Negative number handling
- Edge case handling

### `security.py`
**Added:**
- `check_bot_permissions()` - validates bot permissions in channel
- `get_auction_channels()` - retrieves configured channels
- `validate_channel_for_auction()` - comprehensive channel validation
- `can_open_auction()` - checks if user can open auctions
- `can_manage_auction()` - checks if user can manage auctions
- `rate_limit_check()` placeholder for future rate limiting
- Decorator functions (for future use)

**Improved:**
- All functions now return tuples with error messages
- Better permission checks
- More detailed validation
- Debug logging

### `emojis.py`
**Added:**
- Caching system for emoji lookups
- `clear_cache()` function
- `bulk_set_emojis()` for batch updates
- `is_discord_emoji()` validator
- `extract_emoji_id()` utility
- `format_with_emojis()` template formatter
- More default emojis (crown, chart, coin, etc.)

**Improved:**
- Async-first design
- Better error handling
- Cache initialization on first use
- Emoji name validation

### `database_local.py`
**Added:**
- Custom `DatabaseError` exception
- `_execute_with_retry()` for automatic retries
- WAL mode and cache size optimization
- Foreign key support
- Indexes for better query performance
- `delete_setting()` function
- `get_auction_by_id()` function
- `get_recent_auctions()` function
- `get_bid_count()` function
- `get_user_bid_stats()` function
- `vacuum_db()` for maintenance

**Improved:**
- Connection management with lock
- Better error handling and logging
- Timestamps in settings table
- Comprehensive docstrings

### `database.py`
**Added:**
- `DatabaseConnectionError` exception
- `_is_valid_postgres_url()` validation
- Connection retry logic with backoff
- `_create_postgres_tables()` helper
- `get_connection_status()` for diagnostics
- `retry_postgres_connection()` manual retry
- Better connection attempt tracking

**Improved:**
- Automatic fallback to local on any error
- Per-operation error handling
- Connection pooling configuration
- Timeout settings
- All operations wrapped with try-catch

### `logs.py`
**Added:**
- `log_auction_start()` function
- `log_bid()` function (optional)
- `log_error()` function
- `log_command_usage()` function
- Medal emojis for top 3 bids (🥇🥈🥉)
- Duration calculation
- Commission display
- Unique bidders count

**Improved:**
- Rich embed formatting
- Better field organization
- Emoji integration
- Error handling
- Configurable max bids display

### `auctions.py`
**Fixed:**
- ✅ Added missing `import time`
- ✅ Added missing `import traceback`
- ✅ Fixed `_post_or_update_panel()` to handle missing channels
- ✅ Fixed monitor task lifecycle
- ✅ Fixed countdown interruption logic

**Added:**
- Permission checks before posting panels
- Error logging integration
- Better cooldown management
- Panel update delay (PANEL_UPDATE_DELAY)
- `cancel_auction_monitor()` function
- Comprehensive docstrings
- DEBUG_MODE logging throughout

**Improved:**
- Embed builder with more fields
- Modal with better validation
- Button labels and styles
- Promo message formatting
- Monitor task error handling
- Finalization process
- Panel deletion after auction ends

### `bot.py`
**Fixed:**
- ✅ Fixed `auction_undo_last` - now correctly calls `_post_or_update_panel()`
- ✅ Fixed interaction handling for buttons and modals
- ✅ Fixed command syncing

**Added:**
- `/debug_status` command - shows bot status
- `/debug_auction` command - shows auction details
- `/db_retry` command - retry PostgreSQL connection
- `/emoji_set` and `/emoji_list` commands
- Global state tracking (_bot_ready, _startup_time)
- Comprehensive startup logging
- Active auction restoration on startup
- Permission validation before auction open
- Duration validation
- Better error messages
- Command usage logging

**Improved:**
- Token validation and sanitization
- Error handling throughout
- Deferred responses for slow operations
- User feedback for all actions
- Admin permission checks
- Emoji integration in messages

---

## [1.0.0] - Original Version

### Initial Release
- Basic auction functionality
- Button-based bidding system
- Simple countdown mechanism
- PostgreSQL/SQLite dual database
- Basic admin commands
- Arabic promotional messages

---

## Migration Guide: v1.0 → v2.0

### For Existing Installations:

1. **Backup your database** (IMPORTANT!)
   ```bash
   # SQLite
   cp local_db.sqlite local_db.sqlite.backup
   
   # PostgreSQL
   pg_dump yourdb > backup.sql
   ```

2. **Replace all code files** except `.env`
   - Keep your existing `.env` file
   - All settings are preserved in database

3. **Update dependencies**
   ```bash
   pip install -r requirements.txt --upgrade
   ```

4. **Restart the bot**
   ```bash
   python bot.py
   ```

5. **Verify operation**
   ```
   /debug_status
   ```

### No Database Migration Required
- All database operations are backward compatible
- Existing auctions and bids will work as-is
- New features are additive only

### Configuration Changes
No changes required to existing configuration. New features:
- Set `DEBUG_MODE=True` in `.env` for detailed logging
- Use new emoji customization commands
- Try new debug commands for troubleshooting

---

## Known Issues

### Current Version (2.0.0)
None known. Please report issues on GitHub.

---

## Future Planned Changes

### v2.1 (Planned)
- [ ] Anti-snipe feature (auto-extend on last-second bids)
- [ ] Auction history command for users
- [ ] Personal bid statistics
- [ ] Auction templates

### v3.0 (Planned)
- [ ] Multiple simultaneous auctions
- [ ] Web dashboard
- [ ] REST API
- [ ] Advanced analytics

---

## Credits

### Contributors
- [Your Name] - Main Developer

### Special Thanks
- discord.py community
- Beta testers
- Arabic Discord community

---

**Last Updated:** 2024
**Version:** 2.0.0 Enhanced
