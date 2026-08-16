"""שכבת נתונים — SQLite (קל, בלי שרת נפרד). משותף בין הבוט לדשבורד.

טבלאות
------
· channels   — ערוצי תוכן שספקים חיברו (ממתין/מאושר/נדחה).
· content    — אינדקס תוכן מהערוצים המחוברים (שם → הודעה לשליחה).
· users      — מי דיבר עם הבוט (לסטטיסטיקות ולדשבורד).
· requests   — היסטוריית בקשות תוכן (מה חיפשו, אם נמצא).
"""
import time

import aiosqlite

from .config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    chat_id      INTEGER PRIMARY KEY,
    title        TEXT,
    username     TEXT,
    owner_id     INTEGER,
    owner_name   TEXT,
    status       TEXT DEFAULT 'pending',   -- pending | approved | rejected
    added_at     REAL,
    approved_at  REAL,
    item_count   INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS content (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER,
    message_id  INTEGER,
    name        TEXT,
    norm        TEXT,                       -- שם מנורמל לחיפוש
    added_at    REAL,
    UNIQUE(chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_content_norm ON content(norm);
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    name        TEXT,
    first_seen  REAL,
    last_seen   REAL,
    requests    INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    query       TEXT,
    found       INTEGER,
    at          REAL
);
"""


async def init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


# ── ערוצים ────────────────────────────────────────────────────────────────────
async def add_pending_channel(chat_id, title, username, owner_id, owner_name):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO channels (chat_id, title, username, owner_id, owner_name, status, added_at)
               VALUES (?,?,?,?,?, 'pending', ?)
               ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title,
                   username=excluded.username, owner_id=excluded.owner_id,
                   owner_name=excluded.owner_name""",
            (chat_id, title, username, owner_id, owner_name, time.time()))
        await db.commit()


async def set_channel_status(chat_id, status):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE channels SET status=?, approved_at=? WHERE chat_id=?",
            (status, time.time() if status == "approved" else None, chat_id))
        await db.commit()


async def get_channel(chat_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM channels WHERE chat_id=?", (chat_id,))
        return await cur.fetchone()


async def is_approved(chat_id) -> bool:
    ch = await get_channel(chat_id)
    return bool(ch) and ch["status"] == "approved"


async def list_channels(status=None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if status:
            cur = await db.execute("SELECT * FROM channels WHERE status=? ORDER BY added_at DESC", (status,))
        else:
            cur = await db.execute("SELECT * FROM channels ORDER BY added_at DESC")
        return await cur.fetchall()


# ── תוכן ─────────────────────────────────────────────────────────────────────
async def index_content(chat_id, message_id, name, norm):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR IGNORE INTO content (chat_id, message_id, name, norm, added_at)
               VALUES (?,?,?,?,?)""",
            (chat_id, message_id, name, norm, time.time()))
        await db.execute("UPDATE channels SET item_count=item_count+1 WHERE chat_id=?", (chat_id,))
        await db.commit()


async def search_content(tokens: list[str], limit=8):
    """מחזיר תוכן מערוצים *מאושרים בלבד* שמכיל את כל המילים."""
    if not tokens:
        return []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        where = " AND ".join(["c.norm LIKE ?"] * len(tokens))
        cur = await db.execute(
            f"""SELECT c.name, c.chat_id, c.message_id FROM content c
                JOIN channels ch ON ch.chat_id=c.chat_id
                WHERE ch.status='approved' AND {where}
                ORDER BY c.added_at DESC LIMIT ?""",
            [f"%{t}%" for t in tokens] + [limit])
        return await cur.fetchall()


# ── משתמשים ובקשות ───────────────────────────────────────────────────────────
async def touch_user(user_id, name):
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO users (user_id, name, first_seen, last_seen, requests)
               VALUES (?,?,?,?,0)
               ON CONFLICT(user_id) DO UPDATE SET last_seen=?, name=excluded.name""",
            (user_id, name, now, now, now))
        await db.commit()


async def log_request(user_id, query, found):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO requests (user_id, query, found, at) VALUES (?,?,?,?)",
                         (user_id, query, 1 if found else 0, time.time()))
        await db.execute("UPDATE users SET requests=requests+1 WHERE user_id=?", (user_id,))
        await db.commit()


async def stats():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        out = {}
        for key, q in (
            ("channels_approved", "SELECT COUNT(*) n FROM channels WHERE status='approved'"),
            ("channels_pending", "SELECT COUNT(*) n FROM channels WHERE status='pending'"),
            ("content", "SELECT COUNT(*) n FROM content"),
            ("users", "SELECT COUNT(*) n FROM users"),
            ("requests", "SELECT COUNT(*) n FROM requests"),
        ):
            cur = await db.execute(q)
            out[key] = (await cur.fetchone())["n"]
        return out
