# database.py
"""
Database wrapper: tries to use asyncpg (Postgres) via DATABASE_URL.
On any connection error / runtime error it will switch to local SQLite (database_local.py).
Exports same async functions used by the bot.
"""

import os
import traceback
import importlib
import time
from typing import Optional, Dict, Any, List

DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()

_pool = None  # asyncpg pool
_using_local = False
_local_module = None

async def _try_connect_postgres():
    global _pool, _using_local
    try:
        import asyncpg
    except Exception as e:
        print("asyncpg import failed:", e)
        _using_local = True
        return False

    if not DATABASE_url_ok(DATABASE_URL):
        print("DATABASE_URL invalid or empty; will use local DB.")
        _using_local = True
        return False

    try:
        print("Attempting to connect to remote Postgres...")
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        # ensure tables exist
        async with _pool.acquire() as con:
            await con.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """)
            await con.execute("""
            CREATE TABLE IF NOT EXISTS auctions (
                id BIGSERIAL PRIMARY KEY,
                started_by BIGINT NOT NULL,
                start_bid BIGINT NOT NULL,
                min_increment BIGINT NOT NULL,
                status TEXT NOT NULL,
                started_at BIGINT NOT NULL,
                ends_at BIGINT NOT NULL,
                ended_at BIGINT,
                final_price BIGINT,
                winner_id BIGINT
            );
            """)
            await con.execute("""
            CREATE TABLE IF NOT EXISTS bids (
                id BIGSERIAL PRIMARY KEY,
                auction_id BIGINT NOT NULL REFERENCES auctions(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL,
                amount BIGINT NOT NULL,
                created_at BIGINT NOT NULL
            );
            """)
        print("Connected to Postgres and created/ensured tables.")
        _using_local = False
        return True
    except Exception as e:
        print("Failed to connect to Postgres; falling back to local. Exception:")
        traceback.print_exc()
        _using_local = True
        return False

def DATABASE_url_ok(dsn: str) -> bool:
    if not dsn:
        return False
    # Basic check: must start with postgresql://
    return dsn.startswith("postgresql://") or dsn.startswith("postgres://")

async def _init_local():
    global _local_module
    if _local_module is None:
        _local_module = importlib.import_module("database_local")
    await _local_module.init_db()

async def init_db():
    """
    Try to initialize Postgres; if fails, init local SQLite.
    """
    global _using_local
    if not _using_local:
        ok = await _try_connect_postgres()
        if ok:
            return
    print("Using local SQLite database.")
    await _init_local()
    _using_local = True

async def _switch_to_local_on_error(exc: Exception):
    global _using_local
    print("Switching to local DB due to exception:", exc)
    traceback.print_exc()
    _using_local = True
    await _init_local()

# ---- Settings ----
async def set_setting(key: str, value: str):
    if not _using_local and _pool is not None:
        try:
            async with _pool.acquire() as con:
                await con.execute("""
                INSERT INTO settings (key, value) VALUES ($1, $2)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
                """, key, value)
                return
        except Exception as e:
            await _switch_to_local_on_error(e)
    # local fallback
    await _init_local()
    return await _local_module.set_setting(key, value)

async def get_setting(key: str) -> Optional[str]:
    if not _using_local and _pool is not None:
        try:
            async with _pool.acquire() as con:
                row = await con.fetchrow("SELECT value FROM settings WHERE key = $1;", key)
                return row["value"] if row else None
        except Exception as e:
            await _switch_to_local_on_error(e)
    await _init_local()
    return await _local_module.get_setting(key)

async def all_settings() -> Dict[str, str]:
    if not _using_local and _pool is not None:
        try:
            async with _pool.acquire() as con:
                rows = await con.fetch("SELECT key, value FROM settings;")
                return {r["key"]: r["value"] for r in rows}
        except Exception as e:
            await _switch_to_local_on_error(e)
    await _init_local()
    return await _local_module.all_settings()

# ---- Auctions & Bids ----
async def create_auction(started_by: int, start_bid: int, min_increment: int, ends_at: int) -> Dict[str, Any]:
    if not _using_local and _pool is not None:
        try:
            async with _pool.acquire() as con:
                row = await con.fetchrow("""
                INSERT INTO auctions (started_by, start_bid, min_increment, status, started_at, ends_at)
                VALUES ($1, $2, $3, 'OPEN', EXTRACT(EPOCH FROM NOW())::BIGINT, $4)
                RETURNING *;
                """, started_by, start_bid, min_increment, ends_at)
                return dict(row)
        except Exception as e:
            await _switch_to_local_on_error(e)
    await _init_local()
    return await _local_module.create_auction(started_by, start_bid, min_increment, ends_at)

async def get_active_auction() -> Optional[Dict[str, Any]]:
    if not _using_local and _pool is not None:
        try:
            async with _pool.acquire() as con:
                row = await con.fetchrow("""
                SELECT * FROM auctions
                WHERE status = 'OPEN'
                ORDER BY started_at DESC
                LIMIT 1;
                """)
                return dict(row) if row else None
        except Exception as e:
            await _switch_to_local_on_error(e)
    await _init_local()
    return await _local_module.get_active_auction()

async def end_auction(auction_id: int, final_price: int = None, winner_id: int = None):
    if not _using_local and _pool is not None:
        try:
            async with _pool.acquire() as con:
                await con.execute("""
                UPDATE auctions
                SET status = 'ENDED', final_price = $2, winner_id = $3, ended_at = EXTRACT(EPOCH FROM NOW())::BIGINT
                WHERE id = $1;
                """, auction_id, final_price, winner_id)
                return
        except Exception as e:
            await _switch_to_local_on_error(e)
    await _init_local()
    return await _local_module.end_auction(auction_id, final_price, winner_id)

async def add_bid(auction_id: int, user_id: int, amount: int) -> Dict[str, Any]:
    if not _using_local and _pool is not None:
        try:
            async with _pool.acquire() as con:
                row = await con.fetchrow("""
                INSERT INTO bids (auction_id, user_id, amount, created_at)
                VALUES ($1, $2, $3, EXTRACT(EPOCH FROM NOW())::BIGINT)
                RETURNING *;
                """, auction_id, user_id, amount)
                return dict(row)
        except Exception as e:
            await _switch_to_local_on_error(e)
    await _init_local()
    return await _local_module.add_bid(auction_id, user_id, amount)

async def get_bids_for_auction(auction_id: int) -> List[Dict[str, Any]]:
    if not _using_local and _pool is not None:
        try:
            async with _pool.acquire() as con:
                rows = await con.fetch("""
                SELECT * FROM bids WHERE auction_id = $1 ORDER BY amount DESC, created_at ASC;
                """, auction_id)
                return [dict(r) for r in rows]
        except Exception as e:
            await _switch_to_local_on_error(e)
    await _init_local()
    return await _local_module.get_bids_for_auction(auction_id)

async def get_last_bid_by_user(auction_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    if not _using_local and _pool is not None:
        try:
            async with _pool.acquire() as con:
                row = await con.fetchrow("""
                SELECT * FROM bids WHERE auction_id = $1 AND user_id = $2 ORDER BY created_at DESC LIMIT 1;
                """, auction_id, user_id)
                return dict(row) if row else None
        except Exception as e:
            await _switch_to_local_on_error(e)
    await _init_local()
    return await _local_module.get_last_bid_by_user(auction_id, user_id)

async def undo_last_bid(auction_id: int) -> Optional[Dict[str, Any]]:
    if not _using_local and _pool is not None:
        try:
            async with _pool.acquire() as con:
                row = await con.fetchrow("""
                SELECT * FROM bids WHERE auction_id = $1 ORDER BY created_at DESC LIMIT 1;
                """, auction_id)
                if not row:
                    return None
                bid = dict(row)
                await con.execute("DELETE FROM bids WHERE id = $1;", bid["id"])
                return bid
        except Exception as e:
            await _switch_to_local_on_error(e)
    await _init_local()
    return await _local_module.undo_last_bid(auction_id)

async def close_db():
    global _pool, _local_module
    try:
        if _pool is not None:
            await _pool.close()
            _pool = None
    except Exception:
        pass
    if _local_module:
        try:
            await _local_module.close_db()
        except Exception:
            pass