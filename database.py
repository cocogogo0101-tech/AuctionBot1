# database.py
"""
Database wrapper with automatic fallback from PostgreSQL to SQLite.
Attempts to connect to remote Postgres first, falls back to local SQLite on failure.
All database operations go through this module for consistency.
"""

import os
import traceback
import importlib
import time
import asyncio
from typing import Optional, Dict, Any, List
from config import DEBUG_MODE, DB_RETRY_ATTEMPTS, DB_RETRY_DELAY

# Get DATABASE_URL from environment
DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()

# Connection state
_pool = None  # asyncpg connection pool
_using_local = False
_local_module = None
_connection_attempts = 0
_last_connection_attempt = 0
_lock = asyncio.Lock()


class DatabaseConnectionError(Exception):
    """Raised when database connection fails."""
    pass


def _is_valid_postgres_url(url: str) -> bool:
    """
    Validate PostgreSQL connection URL format.
    
    Args:
        url: Database URL string
        
    Returns:
        True if valid, False otherwise
    """
    if not url:
        return False
    
    # Must start with postgresql:// or postgres://
    if not (url.startswith("postgresql://") or url.startswith("postgres://")):
        return False
    
    # Basic sanity check: should contain @ and / for host and database
    if "@" not in url or url.count("/") < 3:
        return False
    
    return True


async def _try_connect_postgres() -> bool:
    """
    Attempt to connect to PostgreSQL.
    
    Returns:
        True if successful, False otherwise
    """
    global _pool, _using_local, _connection_attempts, _last_connection_attempt
    
    # Check if we should even try
    current_time = time.time()
    if _connection_attempts >= 3 and (current_time - _last_connection_attempt) < 300:
        # Don't retry too often after multiple failures (wait 5 minutes)
        if DEBUG_MODE:
            print("Too many recent connection attempts, skipping Postgres connection")
        return False
    
    _last_connection_attempt = current_time
    _connection_attempts += 1
    
    # Try to import asyncpg
    try:
        import asyncpg
    except ImportError as e:
        if DEBUG_MODE:
            print(f"asyncpg not available: {e}")
        return False
    
    # Validate URL
    if not _is_valid_postgres_url(DATABASE_URL):
        if DEBUG_MODE:
            print("DATABASE_URL is invalid or not set")
        return False
    
    # Attempt connection with retries
    for attempt in range(DB_RETRY_ATTEMPTS):
        try:
            if DEBUG_MODE:
                print(f"Attempting Postgres connection (attempt {attempt + 1}/{DB_RETRY_ATTEMPTS})...")
            
            # Create connection pool
            _pool = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=1,
                max_size=10,
                command_timeout=60,
                timeout=30
            )
            
            # Test connection and create tables
            async with _pool.acquire() as conn:
                # Test query
                await conn.fetchval("SELECT 1")
                
                # Create tables
                await _create_postgres_tables(conn)
            
            if DEBUG_MODE:
                print("✓ Successfully connected to PostgreSQL")
            
            _connection_attempts = 0  # Reset counter on success
            _using_local = False
            return True
        
        except Exception as e:
            if DEBUG_MODE:
                print(f"Postgres connection attempt {attempt + 1} failed: {e}")
            
            if attempt < DB_RETRY_ATTEMPTS - 1:
                await asyncio.sleep(DB_RETRY_DELAY)
            else:
                if DEBUG_MODE:
                    print("All Postgres connection attempts failed")
                    traceback.print_exc()
    
    return False


async def _create_postgres_tables(conn):
    """
    Create tables in PostgreSQL.
    
    Args:
        conn: asyncpg connection
    """
    # Settings table
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW())::BIGINT
    );
    """)
    
    # Auctions table
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS auctions (
        id BIGSERIAL PRIMARY KEY,
        started_by BIGINT NOT NULL,
        start_bid BIGINT NOT NULL,
        min_increment BIGINT NOT NULL,
        status TEXT NOT NULL DEFAULT 'OPEN',
        started_at BIGINT NOT NULL,
        ends_at BIGINT NOT NULL,
        ended_at BIGINT,
        final_price BIGINT,
        winner_id BIGINT,
        created_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW())::BIGINT
    );
    """)
    
    # Create index
    await conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_auctions_status ON auctions(status);
    """)
    
    # Bids table
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS bids (
        id BIGSERIAL PRIMARY KEY,
        auction_id BIGINT NOT NULL REFERENCES auctions(id) ON DELETE CASCADE,
        user_id BIGINT NOT NULL,
        amount BIGINT NOT NULL,
        created_at BIGINT NOT NULL
    );
    """)
    
    # Create indexes
    await conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_bids_auction ON bids(auction_id);
    """)
    
    await conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_bids_amount ON bids(auction_id, amount DESC);
    """)


async def _init_local():
    """
    Initialize local SQLite database.
    """
    global _local_module
    
    if _local_module is None:
        _local_module = importlib.import_module("database_local")
    
    await _local_module.init_db()
    
    if DEBUG_MODE:
        print("✓ Using local SQLite database")


async def _switch_to_local(reason: str = "Unknown error"):
    """
    Switch to local database after Postgres failure.
    
    Args:
        reason: Reason for switching
    """
    global _using_local, _pool
    
    if DEBUG_MODE:
        print(f"Switching to local database: {reason}")
    
    _using_local = True
    
    # Close Postgres pool if exists
    if _pool is not None:
        try:
            await _pool.close()
        except Exception:
            pass
        _pool = None
    
    await _init_local()


async def init_db():
    """
    Initialize database connection.
    Tries PostgreSQL first, falls back to SQLite on failure.
    """
    global _using_local
    
    async with _lock:
        # If already using local, just ensure it's initialized
        if _using_local:
            await _init_local()
            return
        
        # If already connected to Postgres, return
        if _pool is not None:
            return
        
        # Try Postgres
        postgres_ok = await _try_connect_postgres()
        
        if not postgres_ok:
            # Fall back to local
            await _switch_to_local("Postgres connection failed")


async def retry_postgres_connection():
    """
    Manually retry PostgreSQL connection.
    Useful for reconnecting after network issues.
    
    Returns:
        True if connection successful, False otherwise
    """
    global _using_local, _connection_attempts
    
    # Reset connection attempts to allow retry
    _connection_attempts = 0
    
    success = await _try_connect_postgres()
    
    if not success:
        await _switch_to_local("Retry failed")
    
    return success


# ==================== WRAPPER FUNCTIONS ====================
# All functions below wrap either Postgres or local operations

async def _execute_postgres(func, *args, **kwargs):
    """
    Execute a Postgres operation with error handling.
    Switches to local on persistent errors.
    """
    global _pool, _using_local
    
    if _pool is None:
        await _switch_to_local("No Postgres pool")
        raise DatabaseConnectionError("Switched to local database")
    
    try:
        async with _pool.acquire() as conn:
            return await func(conn, *args, **kwargs)
    
    except Exception as e:
        if DEBUG_MODE:
            print(f"Postgres operation failed: {e}")
            traceback.print_exc()
        
        # Switch to local for future operations
        await _switch_to_local(f"Postgres error: {e}")
        raise DatabaseConnectionError("Operation failed, switched to local") from e


# ==================== SETTINGS ====================

async def set_setting(key: str, value: str):
    """Set or update a setting."""
    if not _using_local and _pool is not None:
        try:
            async def _set(conn):
                await conn.execute("""
                INSERT INTO settings (key, value, updated_at) 
                VALUES ($1, $2, EXTRACT(EPOCH FROM NOW())::BIGINT)
                ON CONFLICT (key) DO UPDATE SET 
                    value = EXCLUDED.value,
                    updated_at = EXTRACT(EPOCH FROM NOW())::BIGINT;
                """, key, value)
            
            await _execute_postgres(_set)
            return
        except DatabaseConnectionError:
            pass  # Will use local below
    
    await _init_local()
    await _local_module.set_setting(key, value)


async def get_setting(key: str) -> Optional[str]:
    """Get a setting value."""
    if not _using_local and _pool is not None:
        try:
            async def _get(conn):
                row = await conn.fetchrow("SELECT value FROM settings WHERE key = $1;", key)
                return row["value"] if row else None
            
            return await _execute_postgres(_get)
        except DatabaseConnectionError:
            pass
    
    await _init_local()
    return await _local_module.get_setting(key)


async def all_settings() -> Dict[str, str]:
    """Get all settings."""
    if not _using_local and _pool is not None:
        try:
            async def _get_all(conn):
                rows = await conn.fetch("SELECT key, value FROM settings;")
                return {r["key"]: r["value"] for r in rows}
            
            return await _execute_postgres(_get_all)
        except DatabaseConnectionError:
            pass
    
    await _init_local()
    return await _local_module.all_settings()


# ==================== AUCTIONS ====================

async def create_auction(started_by: int, start_bid: int, 
                        min_increment: int, ends_at: int) -> Dict[str, Any]:
    """Create a new auction."""
    if not _using_local and _pool is not None:
        try:
            async def _create(conn):
                row = await conn.fetchrow("""
                INSERT INTO auctions (started_by, start_bid, min_increment, status, started_at, ends_at)
                VALUES ($1, $2, $3, 'OPEN', EXTRACT(EPOCH FROM NOW())::BIGINT, $4)
                RETURNING *;
                """, started_by, start_bid, min_increment, ends_at)
                return dict(row)
            
            return await _execute_postgres(_create)
        except DatabaseConnectionError:
            pass
    
    await _init_local()
    return await _local_module.create_auction(started_by, start_bid, min_increment, ends_at)


async def get_active_auction() -> Optional[Dict[str, Any]]:
    """Get the currently active auction."""
    if not _using_local and _pool is not None:
        try:
            async def _get(conn):
                row = await conn.fetchrow("""
                SELECT * FROM auctions
                WHERE status = 'OPEN'
                ORDER BY started_at DESC
                LIMIT 1;
                """)
                return dict(row) if row else None
            
            return await _execute_postgres(_get)
        except DatabaseConnectionError:
            pass
    
    await _init_local()
    return await _local_module.get_active_auction()


async def get_auction_by_id(auction_id: int) -> Optional[Dict[str, Any]]:
    """Get auction by ID."""
    if not _using_local and _pool is not None:
        try:
            async def _get(conn):
                row = await conn.fetchrow("SELECT * FROM auctions WHERE id = $1;", auction_id)
                return dict(row) if row else None
            
            return await _execute_postgres(_get)
        except DatabaseConnectionError:
            pass
    
    await _init_local()
    return await _local_module.get_auction_by_id(auction_id)


async def end_auction(auction_id: int, final_price: int = None, winner_id: int = None):
    """End an auction."""
    if not _using_local and _pool is not None:
        try:
            async def _end(conn):
                await conn.execute("""
                UPDATE auctions
                SET status = 'ENDED', 
                    final_price = $2, 
                    winner_id = $3, 
                    ended_at = EXTRACT(EPOCH FROM NOW())::BIGINT
                WHERE id = $1;
                """, auction_id, final_price, winner_id)
            
            await _execute_postgres(_end)
            return
        except DatabaseConnectionError:
            pass
    
    await _init_local()
    await _local_module.end_auction(auction_id, final_price, winner_id)


# ==================== BIDS ====================

async def add_bid(auction_id: int, user_id: int, amount: int) -> Dict[str, Any]:
    """Add a new bid."""
    if not _using_local and _pool is not None:
        try:
            async def _add(conn):
                row = await conn.fetchrow("""
                INSERT INTO bids (auction_id, user_id, amount, created_at)
                VALUES ($1, $2, $3, EXTRACT(EPOCH FROM NOW())::BIGINT)
                RETURNING *;
                """, auction_id, user_id, amount)
                return dict(row)
            
            return await _execute_postgres(_add)
        except DatabaseConnectionError:
            pass
    
    await _init_local()
    return await _local_module.add_bid(auction_id, user_id, amount)


async def get_bids_for_auction(auction_id: int) -> List[Dict[str, Any]]:
    """Get all bids for an auction."""
    if not _using_local and _pool is not None:
        try:
            async def _get(conn):
                rows = await conn.fetch("""
                SELECT * FROM bids 
                WHERE auction_id = $1 
                ORDER BY amount DESC, created_at ASC;
                """, auction_id)
                return [dict(r) for r in rows]
            
            return await _execute_postgres(_get)
        except DatabaseConnectionError:
            pass
    
    await _init_local()
    return await _local_module.get_bids_for_auction(auction_id)


async def get_last_bid_by_user(auction_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    """Get last bid by a specific user."""
    if not _using_local and _pool is not None:
        try:
            async def _get(conn):
                row = await conn.fetchrow("""
                SELECT * FROM bids 
                WHERE auction_id = $1 AND user_id = $2 
                ORDER BY created_at DESC 
                LIMIT 1;
                """, auction_id, user_id)
                return dict(row) if row else None
            
            return await _execute_postgres(_get)
        except DatabaseConnectionError:
            pass
    
    await _init_local()
    return await _local_module.get_last_bid_by_user(auction_id, user_id)


async def undo_last_bid(auction_id: int) -> Optional[Dict[str, Any]]:
    """Remove the last bid from an auction."""
    if not _using_local and _pool is not None:
        try:
            async def _undo(conn):
                # Get last bid
                row = await conn.fetchrow("""
                SELECT * FROM bids 
                WHERE auction_id = $1 
                ORDER BY created_at DESC 
                LIMIT 1;
                """, auction_id)
                
                if not row:
                    return None
                
                bid = dict(row)
                
                # Delete it
                await conn.execute("DELETE FROM bids WHERE id = $1;", bid["id"])
                
                return bid
            
            return await _execute_postgres(_undo)
        except DatabaseConnectionError:
            pass
    
    await _init_local()
    return await _local_module.undo_last_bid(auction_id)


# ==================== UTILITY ====================

async def get_connection_status() -> Dict[str, Any]:
    """
    Get current database connection status.
    Useful for debugging.
    
    Returns:
        Dictionary with connection info
    """
    return {
        "using_local": _using_local,
        "postgres_pool_active": _pool is not None,
        "connection_attempts": _connection_attempts,
        "database_url_configured": bool(DATABASE_URL),
    }


async def close_db():
    """Close database connections."""
    global _pool, _local_module
    
    # Close Postgres pool
    if _pool is not None:
        try:
            await _pool.close()
            if DEBUG_MODE:
                print("Postgres connection closed")
        except Exception as e:
            if DEBUG_MODE:
                print(f"Error closing Postgres: {e}")
        finally:
            _pool = None
    
    # Close local if used
    if _local_module:
        try:
            await _local_module.close_db()
        except Exception as e:
            if DEBUG_MODE:
                print(f"Error closing local DB: {e}")
