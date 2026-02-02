# database.py
import asyncpg
from config import DATABASE_URL
from typing import Optional, Any, Dict, List

_pool: Optional[asyncpg.Pool] = None

async def init_db():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    await _create_tables()
    return _pool

async def _create_tables():
    """
    Create tables: settings, auctions, bids
    """
    global _pool
    if _pool is None:
        return
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

# Settings helpers
async def set_setting(key: str, value: str):
    global _pool
    async with _pool.acquire() as con:
        await con.execute("""
        INSERT INTO settings("key", "value") VALUES ($1, $2)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
        """, key, value)

async def get_setting(key: str) -> Optional[str]:
    global _pool
    async with _pool.acquire() as con:
        row = await con.fetchrow("SELECT value FROM settings WHERE key = $1;", key)
        return row["value"] if row else None

async def all_settings() -> Dict[str, str]:
    global _pool
    out: Dict[str, str] = {}
    async with _pool.acquire() as con:
        rows = await con.fetch("SELECT key, value FROM settings;")
        for r in rows:
            out[r["key"]] = r["value"]
    return out

# Auction helpers
async def create_auction(started_by: int, start_bid: int, min_increment: int, ends_at: int) -> Dict[str, Any]:
    global _pool
    async with _pool.acquire() as con:
        row = await con.fetchrow("""
        INSERT INTO auctions (started_by, start_bid, min_increment, status, started_at, ends_at)
        VALUES ($1, $2, $3, 'OPEN', EXTRACT(EPOCH FROM NOW())::BIGINT, $4)
        RETURNING *;
        """, started_by, start_bid, min_increment, ends_at)
        return dict(row)

async def get_active_auction() -> Optional[Dict[str, Any]]:
    global _pool
    async with _pool.acquire() as con:
        row = await con.fetchrow("""
        SELECT * FROM auctions
        WHERE status = 'OPEN'
        ORDER BY started_at DESC
        LIMIT 1;
        """)
        return dict(row) if row else None

async def end_auction(auction_id: int, final_price: int = None, winner_id: int = None):
    global _pool
    async with _pool.acquire() as con:
        await con.execute("""
        UPDATE auctions
        SET status = 'ENDED', final_price = $2, winner_id = $3, ended_at = EXTRACT(EPOCH FROM NOW())::BIGINT
        WHERE id = $1;
        """, auction_id, final_price, winner_id)

# Bids
async def add_bid(auction_id: int, user_id: int, amount: int) -> Dict[str, Any]:
    global _pool
    async with _pool.acquire() as con:
        row = await con.fetchrow("""
        INSERT INTO bids (auction_id, user_id, amount, created_at)
        VALUES ($1, $2, $3, EXTRACT(EPOCH FROM NOW())::BIGINT)
        RETURNING *;
        """, auction_id, user_id, amount)
        return dict(row)

async def get_bids_for_auction(auction_id: int) -> List[Dict[str, Any]]:
    global _pool
    async with _pool.acquire() as con:
        rows = await con.fetch("""
        SELECT * FROM bids WHERE auction_id = $1 ORDER BY amount DESC, created_at ASC;
        """, auction_id)
        return [dict(r) for r in rows]

async def get_last_bid_by_user(auction_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    global _pool
    async with _pool.acquire() as con:
        row = await con.fetchrow("""
        SELECT * FROM bids WHERE auction_id = $1 AND user_id = $2 ORDER BY created_at DESC LIMIT 1;
        """, auction_id, user_id)
        return dict(row) if row else None

async def undo_last_bid(auction_id: int) -> Optional[Dict[str, Any]]:
    global _pool
    async with _pool.acquire() as con:
        async with con.transaction():
            row = await con.fetchrow("""
            SELECT * FROM bids WHERE auction_id = $1 ORDER BY created_at DESC LIMIT 1;
            """, auction_id)
            if not row:
                return None
            bid = dict(row)
            await con.execute("DELETE FROM bids WHERE id = $1;", bid["id"])
            return bid
