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
-- ── מודרציה (Rose-style) ──
CREATE TABLE IF NOT EXISTS chat_settings (
    chat_id     INTEGER PRIMARY KEY,
    welcome     TEXT,
    rules       TEXT,
    warn_limit  INTEGER DEFAULT 3,
    warn_action TEXT DEFAULT 'mute'         -- mute | ban | kick
);
CREATE TABLE IF NOT EXISTS warns (
    chat_id     INTEGER,
    user_id     INTEGER,
    count       INTEGER DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);
CREATE TABLE IF NOT EXISTS warn_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER, user_id INTEGER, reason TEXT, by_id INTEGER, at REAL
);
CREATE TABLE IF NOT EXISTS notes (
    chat_id     INTEGER, name TEXT, content TEXT, file_id TEXT, file_type TEXT,
    PRIMARY KEY (chat_id, name)
);
CREATE TABLE IF NOT EXISTS filters (
    chat_id     INTEGER, trigger TEXT, reply TEXT,
    PRIMARY KEY (chat_id, trigger)
);
"""


# ── הגדרות צ'אט ────────────────────────────────────────────────────────────────
async def get_settings(chat_id) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM chat_settings WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        return dict(row) if row else {"chat_id": chat_id, "welcome": None, "rules": None,
                                      "warn_limit": 3, "warn_action": "mute"}


async def set_setting(chat_id, field, value):
    if field not in ("welcome", "rules", "warn_limit", "warn_action"):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"""INSERT INTO chat_settings (chat_id, {field}) VALUES (?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET {field}=excluded.{field}""",
            (chat_id, value))
        await db.commit()


# ── אזהרות ────────────────────────────────────────────────────────────────────
async def add_warn(chat_id, user_id, reason, by_id) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO warns (chat_id, user_id, count) VALUES (?,?,1)
               ON CONFLICT(chat_id, user_id) DO UPDATE SET count=count+1""",
            (chat_id, user_id))
        await db.execute("INSERT INTO warn_log (chat_id,user_id,reason,by_id,at) VALUES (?,?,?,?,?)",
                         (chat_id, user_id, reason, by_id, time.time()))
        cur = await db.execute("SELECT count FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        await db.commit()
        return (await cur.fetchone())[0]


async def reset_warns(chat_id, user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        await db.commit()


async def get_warns(chat_id, user_id) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT count FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        row = await cur.fetchone()
        return row[0] if row else 0


# ── הערות ─────────────────────────────────────────────────────────────────────
async def save_note(chat_id, name, content, file_id=None, file_type=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO notes (chat_id,name,content,file_id,file_type) VALUES (?,?,?,?,?)
               ON CONFLICT(chat_id,name) DO UPDATE SET content=excluded.content,
                   file_id=excluded.file_id, file_type=excluded.file_type""",
            (chat_id, name.lower(), content, file_id, file_type))
        await db.commit()


async def get_note(chat_id, name):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM notes WHERE chat_id=? AND name=?", (chat_id, name.lower()))
        row = await cur.fetchone()
        return dict(row) if row else None


async def del_note(chat_id, name):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM notes WHERE chat_id=? AND name=?", (chat_id, name.lower()))
        await db.commit()


async def list_notes(chat_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT name FROM notes WHERE chat_id=? ORDER BY name", (chat_id,))
        return [r[0] for r in await cur.fetchall()]


# ── פילטרים (תגובה אוטומטית למילת-מפתח) ──────────────────────────────────────
async def add_filter(chat_id, trigger, reply):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO filters (chat_id, trigger, reply) VALUES (?,?,?)
               ON CONFLICT(chat_id, trigger) DO UPDATE SET reply=excluded.reply""",
            (chat_id, trigger.lower(), reply))
        await db.commit()


async def del_filter(chat_id, trigger):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM filters WHERE chat_id=? AND trigger=?",
                               (chat_id, trigger.lower()))
        await db.commit()
        return cur.rowcount > 0


async def list_filters(chat_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT trigger FROM filters WHERE chat_id=? ORDER BY trigger", (chat_id,))
        return [r[0] for r in await cur.fetchall()]


async def get_filters(chat_id):
    """כל הפילטרים של הצ'אט → [(trigger, reply), ...]."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT trigger, reply FROM filters WHERE chat_id=?", (chat_id,))
        return await cur.fetchall()


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
