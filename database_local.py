# database_local.py
"""
Local SQLite implementation used as fallback when remote PostgreSQL is unavailable.
Provides same function names/signatures as database.py expects.
Uses aiosqlite (async).
"""

import aiosqlite
import asyncio
import time
from typing import Optional, Dict, Any, List

_db_path = "local_db.sqlite"
_conn: Optional[aiosqlite.Connection] = None
_lock = asyncio.Lock()

async def init_db():
    global _conn
    if _conn:
        return
    _conn = await aiosqlite.connect(_db_path)
    _conn.row_factory = aiosqlite.Row
    # use WAL for safer concurrency
    await _conn.execute("PRAGMA journal_mode=WAL;")
    await _create_tables()
    await _conn.commit()

async def _create_tables():
    global _conn
    if _conn is None:
        await init_db()
    async with _lock:
        await _conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );""")
        await _conn.execute("""
        CREATE TABLE IF NOT EXISTS auctions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_by INTEGER NOT NULL,
            start_bid INTEGER NOT NULL,
            min_increment INTEGER NOT NULL,
            status TEXT NOT NULL,
            started_at INTEGER NOT NULL,
            ends_at INTEGER NOT NULL,
            ended_at INTEGER,
            final_price INTEGER,
            winner_id INTEGER
        );""")
        await _conn.execute("""
        CREATE TABLE IF NOT EXISTS bids (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            auction_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            FOREIGN KEY (auction_id) REFERENCES auctions(id) ON DELETE CASCADE
        );""")
        await _conn.commit()

# Settings
async def set_setting(key: str, value: str):
    global _conn
    await init_db()
    async with _lock:
        # SQLite doesn't have "excluded" shorthand in upsert for older versions, but recent versions support it.
        await _conn.execute("""
        INSERT INTO settings(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value;
        """, (key, value))
        await _conn.commit()

async def get_setting(key: str) -> Optional[str]:
    global _conn
    await init_db()
    async with _lock:
        cur = await _conn.execute("SELECT value FROM settings WHERE key = ?;", (key,))
        row = await cur.fetchone()
        return row["value"] if row else None

async def all_settings() -> Dict[str, str]:
    global _conn
    await init_db()
    async with _lock:
        cur = await _conn.execute("SELECT key, value FROM settings;")
        rows = await cur.fetchall()
        return {r["key"]: r["value"] for r in rows}

# Auctions
async def create_auction(started_by: int, start_bid: int, min_increment: int, ends_at: int) -> Dict[str, Any]:
    global _conn
    await init_db()
    ts = int(time.time())
    async with _lock:
        await _conn.execute("""
        INSERT INTO auctions (started_by, start_bid, min_increment, status, started_at, ends_at)
        VALUES (?, ?, ?, 'OPEN', ?, ?);
        """, (started_by, start_bid, min_increment, ts, ends_at))
        await _conn.commit()
        cur = await _conn.execute("SELECT * FROM auctions ORDER BY id DESC LIMIT 1;")
        r = await cur.fetchone()
        return dict(r)

async def get_active_auction() -> Optional[Dict[str, Any]]:
    global _conn
    await init_db()
    async with _lock:
        cur = await _conn.execute("SELECT * FROM auctions WHERE status = 'OPEN' ORDER BY started_at DESC LIMIT 1;")
        row = await cur.fetchone()
        return dict(row) if row else None

async def end_auction(auction_id: int, final_price: int = None, winner_id: int = None):
    global _conn
    await init_db()
    async with _lock:
        await _conn.execute("""
        UPDATE auctions
        SET status = 'ENDED', final_price = ?, winner_id = ?, ended_at = ?
        WHERE id = ?;
        """, (final_price, winner_id, int(time.time()), auction_id))
        await _conn.commit()

# Bids
async def add_bid(auction_id: int, user_id: int, amount: int) -> Dict[str, Any]:
    global _conn
    await init_db()
    async with _lock:
        await _conn.execute("""
        INSERT INTO bids (auction_id, user_id, amount, created_at)
        VALUES (?, ?, ?, ?);
        """, (auction_id, user_id, amount, int(time.time())))
        await _conn.commit()
        cur = await _conn.execute("SELECT * FROM bids ORDER BY id DESC LIMIT 1;")
        r = await cur.fetchone()
        return dict(r)

async def get_bids_for_auction(auction_id: int) -> List[Dict[str, Any]]:
    global _conn
    await init_db()
    async with _lock:
        cur = await _conn.execute("SELECT * FROM bids WHERE auction_id = ? ORDER BY amount DESC, created_at ASC;", (auction_id,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

async def get_last_bid_by_user(auction_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    global _conn
    await init_db()
    async with _lock:
        cur = await _conn.execute("SELECT * FROM bids WHERE auction_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT 1;", (auction_id, user_id))
        row = await cur.fetchone()
        return dict(row) if row else None

async def undo_last_bid(auction_id: int) -> Optional[Dict[str, Any]]:
    global _conn
    await init_db()
    async with _lock:
        cur = await _conn.execute("SELECT * FROM bids WHERE auction_id = ? ORDER BY created_at DESC LIMIT 1;", (auction_id,))
        row = await cur.fetchone()
        if not row:
            return None
        bid = dict(row)
        await _conn.execute("DELETE FROM bids WHERE id = ?;", (bid["id"],))
        await _conn.commit()
        return bid

async def close_db():
    global _conn
    if _conn:
        await _conn.close()
        _conn = None