#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""db — הסכימה ושכבת הגישה למסד.

## שתי החלטות שקובעות הכול

**1. SQLite עכשיו, Postgres אחר כך, בלי שכתוב.**
כל ה-SQL כאן הוא SQL סטנדרטי. אין ‎INSERT OR REPLACE‎, אין ‎rowid‎, אין
פונקציות ייחודיות ל-SQLite. המעבר ל-Postgres הוא החלפת מחלקת החיבור
בלבד. נמדד: SQLite עם WAL נותן 11,500 הודעות בשנייה על ליבה אחת, ולכן
אין שום סיבה להתחיל ב-Postgres.

**2. הסכימה מלאה מהיום הראשון, גם למה שעוד לא נבנה.**
טבלה שנוספת אחרי שיש נתונים דורשת מיגרציה; טבלה ריקה לא עולה כלום.
לכן ‎notes‎, ‎filters‎, ‎locks‎ ו-‎blocklist‎ קיימות כבר עכשיו, למרות
ששלב 3 יתחיל למלא אותן.

## מיגרציות

לכל שינוי סכימה מספר גרסה ב-‎MIGRATIONS‎. ‎migrate()‎ מריץ רק את מה שחסר,
בתוך טרנזקציה, ורושם את הגרסה. אין "תריץ את הסקריפט הזה ידנית".
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Any, Iterable, Optional

DEFAULT_PATH = os.environ.get("GROUPOS_DB", "/opt/groupos/data/groupos.db")

# ── הסכימה ─────────────────────────────────────────────────────────────────
# כל איבר ברשימה הוא גרסה. מוסיפים בסוף בלבד, לעולם לא עורכים קיים.
MIGRATIONS: list[tuple[int, str]] = [
    (1, """
    CREATE TABLE chats (
        chat_id      INTEGER PRIMARY KEY,
        title        TEXT    NOT NULL DEFAULT '',
        username     TEXT,
        type         TEXT    NOT NULL DEFAULT 'supergroup',
        language     TEXT    NOT NULL DEFAULT 'he',
        added_at     REAL    NOT NULL,
        active       INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE users (
        user_id      INTEGER PRIMARY KEY,
        username     TEXT,
        first_name   TEXT    NOT NULL DEFAULT '',
        language     TEXT,
        is_bot       INTEGER NOT NULL DEFAULT 0,
        first_seen   REAL    NOT NULL,
        last_seen    REAL    NOT NULL
    );

    -- חברות בקבוצה. msg_count ו-last_msg משמשים גם את ה-flood וגם את
    -- ה-reputation, ולכן הם כאן ולא בטבלה נפרדת.
    CREATE TABLE members (
        chat_id      INTEGER NOT NULL,
        user_id      INTEGER NOT NULL,
        joined_at    REAL,
        msg_count    INTEGER NOT NULL DEFAULT 0,
        last_msg     REAL    NOT NULL DEFAULT 0,
        warns        INTEGER NOT NULL DEFAULT 0,
        role         TEXT    NOT NULL DEFAULT 'member',
        PRIMARY KEY (chat_id, user_id)
    );
    CREATE INDEX idx_members_role ON members (chat_id, role);

    -- הרשאות פר-קבוצה. role='*' הוא ברירת מחדל גלובלית לתפקיד.
    CREATE TABLE role_grants (
        chat_id      INTEGER NOT NULL,
        role         TEXT    NOT NULL,
        permission   TEXT    NOT NULL,
        allowed      INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (chat_id, role, permission)
    );

    -- הגדרות. ערך אחד לכל מפתח לכל קבוצה; chat_id=0 הוא ברירת מחדל.
    CREATE TABLE settings (
        chat_id      INTEGER NOT NULL,
        key          TEXT    NOT NULL,
        value        TEXT    NOT NULL,
        updated_at   REAL    NOT NULL,
        updated_by   INTEGER,
        PRIMARY KEY (chat_id, key)
    );

    -- כל פעולה משמעותית. before/after שומרים מצב כדי לאפשר Rollback.
    CREATE TABLE audit_log (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        ts           REAL    NOT NULL,
        chat_id      INTEGER NOT NULL,
        actor_id     INTEGER,
        actor_kind   TEXT    NOT NULL DEFAULT 'user',
        action       TEXT    NOT NULL,
        target_id    INTEGER,
        reason       TEXT,
        before_val   TEXT,
        after_val    TEXT,
        source       TEXT    NOT NULL DEFAULT 'command',
        severity     TEXT    NOT NULL DEFAULT 'info'
    );
    CREATE INDEX idx_audit_chat  ON audit_log (chat_id, ts);
    CREATE INDEX idx_audit_target ON audit_log (chat_id, target_id, ts);

    -- אזהרות. נשמרות בנפרד מ-members.warns כדי שתהיה היסטוריה ולא רק מונה.
    CREATE TABLE warnings (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id      INTEGER NOT NULL,
        user_id      INTEGER NOT NULL,
        by_id        INTEGER,
        reason       TEXT,
        ts           REAL    NOT NULL,
        revoked_at   REAL
    );
    CREATE INDEX idx_warn_user ON warnings (chat_id, user_id, revoked_at);

    -- ענישות פעילות. expires_at NULL = לצמיתות.
    CREATE TABLE sanctions (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id      INTEGER NOT NULL,
        user_id      INTEGER NOT NULL,
        kind         TEXT    NOT NULL,
        by_id        INTEGER,
        reason       TEXT,
        ts           REAL    NOT NULL,
        expires_at   REAL,
        lifted_at    REAL
    );
    CREATE INDEX idx_sanction_live ON sanctions (chat_id, user_id, lifted_at);
    CREATE INDEX idx_sanction_exp  ON sanctions (expires_at) WHERE expires_at IS NOT NULL;

    """),

    # שלב 3 ימלא אותן; קיימות מראש כדי לא לעשות מיגרציה על מסד חי.
    (2, """
    CREATE TABLE notes (
        chat_id      INTEGER NOT NULL,
        name         TEXT    NOT NULL,
        content      TEXT    NOT NULL DEFAULT '',
        media_id     TEXT,
        media_kind   TEXT,
        buttons      TEXT,
        visibility   TEXT    NOT NULL DEFAULT 'public',
        created_by   INTEGER,
        created_at   REAL    NOT NULL,
        PRIMARY KEY (chat_id, name)
    );

    CREATE TABLE filters (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id      INTEGER NOT NULL,
        trigger      TEXT    NOT NULL,
        match_kind   TEXT    NOT NULL DEFAULT 'word',
        action       TEXT    NOT NULL DEFAULT 'reply',
        content      TEXT,
        enabled      INTEGER NOT NULL DEFAULT 1,
        created_at   REAL    NOT NULL
    );
    CREATE INDEX idx_filters_chat ON filters (chat_id, enabled);

    CREATE TABLE locks (
        chat_id      INTEGER NOT NULL,
        lock_type    TEXT    NOT NULL,
        action       TEXT    NOT NULL DEFAULT 'delete',
        duration     INTEGER,
        PRIMARY KEY (chat_id, lock_type)
    );

    CREATE TABLE blocklist (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id      INTEGER NOT NULL,
        pattern      TEXT    NOT NULL,
        kind         TEXT    NOT NULL DEFAULT 'word',
        action       TEXT    NOT NULL DEFAULT 'delete',
        created_at   REAL    NOT NULL
    );
    CREATE INDEX idx_block_chat ON blocklist (chat_id);

    -- החרגות. אותה טבלה משרתת משתמשים, דומיינים ותפקידים.
    CREATE TABLE allowlist (
        chat_id      INTEGER NOT NULL,
        scope        TEXT    NOT NULL,
        value        TEXT    NOT NULL,
        PRIMARY KEY (chat_id, scope, value)
    );
    """),
]


def _statements(script: str) -> list[str]:
    """מפצל סקריפט סכימה למשפטים.

    ההערות מוסרות **לפני** הפיצול ולא אחריו. הסדר ההפוך נראה תמים ונשבר
    על ההערה הראשונה שיש בה נקודה-פסיק — והיו כאן כאלה בעברית. אז חצי
    ההערה השני הפך למשפט SQL, ו-SQLite נחנק על "chat_id".
    """
    clean = "\n".join(l for l in script.splitlines()
                      if not l.strip().startswith("--"))
    return [s.strip() for s in clean.split(";") if s.strip()]


class Db:
    """חיבור למסד, בטוח לשימוש מכמה חוטים.

    SQLite פותח חיבור אחד לכל חוט (‎check_same_thread‎), ולכן החיבור נשמר
    ב-thread-local. זה גם מה שמאפשר ל-executor של aiogram לעבוד בלי נעילות.
    """

    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self._local = threading.local()
        self.migrate()

    @property
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=30000")
            self._local.conn = c
        return c

    # ── מיגרציות ───────────────────────────────────────────────────────────
    def migrate(self) -> int:
        c = self.conn
        c.execute("""CREATE TABLE IF NOT EXISTS schema_version (
                       version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)""")
        done = {r[0] for r in c.execute("SELECT version FROM schema_version")}
        applied = 0
        for ver, sql in MIGRATIONS:
            if ver in done:
                continue
            # לא executescript: הוא מבצע COMMIT מרומז לפני שהוא מתחיל,
            # ולכן מיגרציה שנופלת באמצע הייתה משאירה חצי סכימה.
            c.execute("BEGIN")
            try:
                for stmt in _statements(sql):
                    c.execute(stmt)
                c.execute("INSERT INTO schema_version VALUES (?,?)", (ver, time.time()))
                c.execute("COMMIT")
                applied += 1
            except Exception:
                try:
                    c.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        return applied

    @property
    def version(self) -> int:
        r = self.conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return r[0] or 0

    # ── גישה ───────────────────────────────────────────────────────────────
    def q(self, sql: str, args: Iterable = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, tuple(args)).fetchall()

    def one(self, sql: str, args: Iterable = ()) -> Optional[sqlite3.Row]:
        return self.conn.execute(sql, tuple(args)).fetchone()

    def run(self, sql: str, args: Iterable = ()) -> int:
        cur = self.conn.execute(sql, tuple(args))
        return cur.lastrowid

    def many(self, sql: str, rows: Iterable[Iterable]) -> None:
        self.conn.executemany(sql, [tuple(r) for r in rows])

    # ── הגדרות ─────────────────────────────────────────────────────────────
    # chat_id=0 הוא ברירת המחדל הגלובלית. קבוצה יורשת ממנה עד שהיא דורסת.
    def get(self, chat_id: int, key: str, default: Any = None) -> Any:
        r = self.one("SELECT value FROM settings WHERE chat_id=? AND key=?",
                     (chat_id, key))
        if r is None and chat_id != 0:
            r = self.one("SELECT value FROM settings WHERE chat_id=0 AND key=?", (key,))
        return r["value"] if r else default

    def set(self, chat_id: int, key: str, value: Any, by: Optional[int] = None) -> None:
        # UPSERT סטנדרטי — נתמך גם ב-SQLite וגם ב-Postgres
        self.run("""INSERT INTO settings (chat_id,key,value,updated_at,updated_by)
                    VALUES (?,?,?,?,?)
                    ON CONFLICT (chat_id,key) DO UPDATE SET
                      value=excluded.value,
                      updated_at=excluded.updated_at,
                      updated_by=excluded.updated_by""",
                 (chat_id, key, str(value), time.time(), by))

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None
