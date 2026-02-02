# database_local.py
"""
Local SQLite implementation used as fallback when remote PostgreSQL is unavailable.
Provides async database operations using aiosqlite.
Includes connection pooling, error handling, and automatic retry logic.
"""

import aiosqlite
import asyncio
import time
import traceback
from typing import Optional, Dict, Any, List
from config import DEBUG_MODE, DB_RETRY_ATTEMPTS, DB_RETRY_DELAY

# Database configuration
_db_path = "local_db.sqlite"
_conn: Optional[aiosqlite.Connection] = None
_lock = asyncio.Lock()
_init_in_progress = False


class DatabaseError(Exception):
    """Custom exception for database errors."""
    pass


async def init_db():
    """
    Initialize the local SQLite database.
    Creates tables if they don't exist and enables WAL mode for better concurrency.
    
    Raises:
        DatabaseError: If initialization fails
    """
    global _conn, _init_in_progress
    
    # Prevent multiple simultaneous initializations
    async with _lock:
        if _init_in_progress:
            # Wait for other initialization to complete
            while _init_in_progress:
                await asyncio.sleep(0.1)
            return
        
        if _conn:
            return
        
        _init_in_progress = True
    
    try:
        if DEBUG_MODE:
            print(f"Initializing local SQLite database at {_db_path}")
        
        _conn = await aiosqlite.connect(_db_path)
        _conn.row_factory = aiosqlite.Row
        
        # Enable WAL mode for better concurrency
        await _conn.execute("PRAGMA journal_mode=WAL;")
        
        # Increase cache size for better performance
        await _conn.execute("PRAGMA cache_size=10000;")
        
        # Enable foreign keys
        await _conn.execute("PRAGMA foreign_keys=ON;")
        
        # Create tables
        await _create_tables()
        
        await _conn.commit()
        
        if DEBUG_MODE:
            print("Local database initialized successfully")
    
    except Exception as e:
        if DEBUG_MODE:
            print(f"Failed to initialize local database: {e}")
            traceback.print_exc()
        raise DatabaseError(f"Database initialization failed: {e}")
    
    finally:
        _init_in_progress = False


async def _create_tables():
    """
    Create all required tables if they don't exist.
    """
    global _conn
    
    if _conn is None:
        await init_db()
    
    async with _lock:
        # Settings table
        await _conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at INTEGER DEFAULT (strftime('%s', 'now'))
        );
        """)
        
        # Auctions table
        await _conn.execute("""
        CREATE TABLE IF NOT EXISTS auctions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_by INTEGER NOT NULL,
            start_bid INTEGER NOT NULL,
            min_increment INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            started_at INTEGER NOT NULL,
            ends_at INTEGER NOT NULL,
            ended_at INTEGER,
            final_price INTEGER,
            winner_id INTEGER,
            created_at INTEGER DEFAULT (strftime('%s', 'now'))
        );
        """)
        
        # Create index on auction status
        await _conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_auctions_status 
        ON auctions(status);
        """)
        
        # Bids table
        await _conn.execute("""
        CREATE TABLE IF NOT EXISTS bids (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            auction_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            FOREIGN KEY (auction_id) REFERENCES auctions(id) ON DELETE CASCADE
        );
        """)
        
        # Create indexes for better query performance
        await _conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bids_auction 
        ON bids(auction_id);
        """)
        
        await _conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bids_amount 
        ON bids(auction_id, amount DESC);
        """)
        
        await _conn.commit()


async def _execute_with_retry(operation, *args, max_retries: int = DB_RETRY_ATTEMPTS):
    """
    Execute a database operation with automatic retry on failure.
    
    Args:
        operation: Async function to execute
        *args: Arguments for the operation
        max_retries: Maximum number of retry attempts
        
    Returns:
        Result of the operation
        
    Raises:
        DatabaseError: If all retries fail
    """
    last_error = None
    
    for attempt in range(max_retries):
        try:
            return await operation(*args)
        except Exception as e:
            last_error = e
            if DEBUG_MODE:
                print(f"Database operation failed (attempt {attempt + 1}/{max_retries}): {e}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(DB_RETRY_DELAY)
            else:
                if DEBUG_MODE:
                    traceback.print_exc()
    
    raise DatabaseError(f"Operation failed after {max_retries} attempts: {last_error}")


# ==================== SETTINGS ====================

async def set_setting(key: str, value: str):
    """
    Set or update a setting in the database.
    
    Args:
        key: Setting key
        value: Setting value
    """
    global _conn
    await init_db()
    
    async def _set():
        async with _lock:
            await _conn.execute("""
            INSERT INTO settings(key, value, updated_at) 
            VALUES (?, ?, strftime('%s', 'now'))
            ON CONFLICT(key) DO UPDATE SET 
                value=excluded.value,
                updated_at=strftime('%s', 'now');
            """, (key, value))
            await _conn.commit()
    
    await _execute_with_retry(_set)


async def get_setting(key: str) -> Optional[str]:
    """
    Get a setting value from the database.
    
    Args:
        key: Setting key
        
    Returns:
        Setting value or None if not found
    """
    global _conn
    await init_db()
    
    async def _get():
        async with _lock:
            cur = await _conn.execute(
                "SELECT value FROM settings WHERE key = ?;", 
                (key,)
            )
            row = await cur.fetchone()
            return row["value"] if row else None
    
    return await _execute_with_retry(_get)


async def all_settings() -> Dict[str, str]:
    """
    Get all settings from the database.
    
    Returns:
        Dictionary of all settings
    """
    global _conn
    await init_db()
    
    async def _get_all():
        async with _lock:
            cur = await _conn.execute("SELECT key, value FROM settings;")
            rows = await cur.fetchall()
            return {r["key"]: r["value"] for r in rows}
    
    return await _execute_with_retry(_get_all)


async def delete_setting(key: str) -> bool:
    """
    Delete a setting from the database.
    
    Args:
        key: Setting key to delete
        
    Returns:
        True if deleted, False if not found
    """
    global _conn
    await init_db()
    
    async def _delete():
        async with _lock:
            cur = await _conn.execute(
                "DELETE FROM settings WHERE key = ?;",
                (key,)
            )
            await _conn.commit()
            return cur.rowcount > 0
    
    return await _execute_with_retry(_delete)


# ==================== AUCTIONS ====================

async def create_auction(started_by: int, start_bid: int, 
                        min_increment: int, ends_at: int) -> Dict[str, Any]:
    """
    Create a new auction.
    
    Args:
        started_by: User ID who started the auction
        start_bid: Starting bid amount
        min_increment: Minimum bid increment
        ends_at: Unix timestamp when auction ends
        
    Returns:
        Dictionary containing auction data
    """
    global _conn
    await init_db()
    
    ts = int(time.time())
    
    async def _create():
        async with _lock:
            await _conn.execute("""
            INSERT INTO auctions (started_by, start_bid, min_increment, status, started_at, ends_at)
            VALUES (?, ?, ?, 'OPEN', ?, ?);
            """, (started_by, start_bid, min_increment, ts, ends_at))
            await _conn.commit()
            
            cur = await _conn.execute(
                "SELECT * FROM auctions ORDER BY id DESC LIMIT 1;"
            )
            row = await cur.fetchone()
            return dict(row)
    
    return await _execute_with_retry(_create)


async def get_active_auction() -> Optional[Dict[str, Any]]:
    """
    Get the currently active auction.
    
    Returns:
        Dictionary containing auction data, or None if no active auction
    """
    global _conn
    await init_db()
    
    async def _get():
        async with _lock:
            cur = await _conn.execute("""
            SELECT * FROM auctions 
            WHERE status = 'OPEN' 
            ORDER BY started_at DESC 
            LIMIT 1;
            """)
            row = await cur.fetchone()
            return dict(row) if row else None
    
    return await _execute_with_retry(_get)


async def get_auction_by_id(auction_id: int) -> Optional[Dict[str, Any]]:
    """
    Get auction by ID.
    
    Args:
        auction_id: Auction ID
        
    Returns:
        Dictionary containing auction data, or None if not found
    """
    global _conn
    await init_db()
    
    async def _get():
        async with _lock:
            cur = await _conn.execute(
                "SELECT * FROM auctions WHERE id = ?;",
                (auction_id,)
            )
            row = await cur.fetchone()
            return dict(row) if row else None
    
    return await _execute_with_retry(_get)


async def end_auction(auction_id: int, final_price: int = None, 
                     winner_id: int = None):
    """
    End an auction and record the final results.
    
    Args:
        auction_id: Auction ID to end
        final_price: Final winning bid amount
        winner_id: Winner's user ID
    """
    global _conn
    await init_db()
    
    async def _end():
        async with _lock:
            await _conn.execute("""
            UPDATE auctions
            SET status = 'ENDED', 
                final_price = ?, 
                winner_id = ?, 
                ended_at = strftime('%s', 'now')
            WHERE id = ?;
            """, (final_price, winner_id, auction_id))
            await _conn.commit()
    
    await _execute_with_retry(_end)


async def get_recent_auctions(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get recent auctions (for admin review).
    
    Args:
        limit: Maximum number of auctions to return
        
    Returns:
        List of auction dictionaries
    """
    global _conn
    await init_db()
    
    async def _get():
        async with _lock:
            cur = await _conn.execute("""
            SELECT * FROM auctions 
            ORDER BY started_at DESC 
            LIMIT ?;
            """, (limit,))
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
    
    return await _execute_with_retry(_get)


# ==================== BIDS ====================

async def add_bid(auction_id: int, user_id: int, amount: int) -> Dict[str, Any]:
    """
    Add a new bid to an auction.
    
    Args:
        auction_id: Auction ID
        user_id: Bidder's user ID
        amount: Bid amount
        
    Returns:
        Dictionary containing bid data
    """
    global _conn
    await init_db()
    
    ts = int(time.time())
    
    async def _add():
        async with _lock:
            await _conn.execute("""
            INSERT INTO bids (auction_id, user_id, amount, created_at)
            VALUES (?, ?, ?, ?);
            """, (auction_id, user_id, amount, ts))
            await _conn.commit()
            
            cur = await _conn.execute(
                "SELECT * FROM bids ORDER BY id DESC LIMIT 1;"
            )
            row = await cur.fetchone()
            return dict(row)
    
    return await _execute_with_retry(_add)


async def get_bids_for_auction(auction_id: int) -> List[Dict[str, Any]]:
    """
    Get all bids for an auction, ordered by amount (highest first).
    
    Args:
        auction_id: Auction ID
        
    Returns:
        List of bid dictionaries
    """
    global _conn
    await init_db()
    
    async def _get():
        async with _lock:
            cur = await _conn.execute("""
            SELECT * FROM bids 
            WHERE auction_id = ? 
            ORDER BY amount DESC, created_at ASC;
            """, (auction_id,))
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
    
    return await _execute_with_retry(_get)


async def get_last_bid_by_user(auction_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    """
    Get the last bid placed by a user in an auction.
    
    Args:
        auction_id: Auction ID
        user_id: User ID
        
    Returns:
        Dictionary containing bid data, or None if user hasn't bid
    """
    global _conn
    await init_db()
    
    async def _get():
        async with _lock:
            cur = await _conn.execute("""
            SELECT * FROM bids 
            WHERE auction_id = ? AND user_id = ? 
            ORDER BY created_at DESC 
            LIMIT 1;
            """, (auction_id, user_id))
            row = await cur.fetchone()
            return dict(row) if row else None
    
    return await _execute_with_retry(_get)


async def undo_last_bid(auction_id: int) -> Optional[Dict[str, Any]]:
    """
    Remove the last bid from an auction.
    Used by admins to correct mistakes.
    
    Args:
        auction_id: Auction ID
        
    Returns:
        Dictionary containing the removed bid, or None if no bids
    """
    global _conn
    await init_db()
    
    async def _undo():
        async with _lock:
            # Get last bid
            cur = await _conn.execute("""
            SELECT * FROM bids 
            WHERE auction_id = ? 
            ORDER BY created_at DESC 
            LIMIT 1;
            """, (auction_id,))
            row = await cur.fetchone()
            
            if not row:
                return None
            
            bid = dict(row)
            
            # Delete it
            await _conn.execute("DELETE FROM bids WHERE id = ?;", (bid["id"],))
            await _conn.commit()
            
            return bid
    
    return await _execute_with_retry(_undo)


async def get_bid_count(auction_id: int) -> int:
    """
    Get total number of bids for an auction.
    
    Args:
        auction_id: Auction ID
        
    Returns:
        Number of bids
    """
    global _conn
    await init_db()
    
    async def _count():
        async with _lock:
            cur = await _conn.execute(
                "SELECT COUNT(*) as count FROM bids WHERE auction_id = ?;",
                (auction_id,)
            )
            row = await cur.fetchone()
            return row["count"] if row else 0
    
    return await _execute_with_retry(_count)


async def get_user_bid_stats(user_id: int) -> Dict[str, Any]:
    """
    Get bidding statistics for a user.
    
    Args:
        user_id: User ID
        
    Returns:
        Dictionary with stats (total_bids, auctions_participated, total_spent)
    """
    global _conn
    await init_db()
    
    async def _stats():
        async with _lock:
            # Total bids
            cur = await _conn.execute(
                "SELECT COUNT(*) as count FROM bids WHERE user_id = ?;",
                (user_id,)
            )
            row = await cur.fetchone()
            total_bids = row["count"] if row else 0
            
            # Auctions participated
            cur = await _conn.execute(
                "SELECT COUNT(DISTINCT auction_id) as count FROM bids WHERE user_id = ?;",
                (user_id,)
            )
            row = await cur.fetchone()
            auctions = row["count"] if row else 0
            
            # Auctions won
            cur = await _conn.execute(
                "SELECT COUNT(*) as count FROM auctions WHERE winner_id = ?;",
                (user_id,)
            )
            row = await cur.fetchone()
            won = row["count"] if row else 0
            
            return {
                "total_bids": total_bids,
                "auctions_participated": auctions,
                "auctions_won": won,
            }
    
    return await _execute_with_retry(_stats)


# ==================== CLEANUP ====================

async def close_db():
    """
    Close the database connection.
    Should be called when bot is shutting down.
    """
    global _conn
    
    if _conn:
        try:
            await _conn.close()
            if DEBUG_MODE:
                print("Local database connection closed")
        except Exception as e:
            if DEBUG_MODE:
                print(f"Error closing database: {e}")
        finally:
            _conn = None


async def vacuum_db():
    """
    Optimize the database by running VACUUM.
    Should be run periodically to reclaim space.
    """
    global _conn
    await init_db()
    
    async with _lock:
        await _conn.execute("VACUUM;")
        if DEBUG_MODE:
            print("Database vacuumed")
