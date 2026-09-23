#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""federation — חסימה משותפת בין קבוצות.

## מה זה פותר

מי שמנהל עשר קבוצות מכיר את זה: ספאמר נחסם בקבוצה אחת, ועובר לתשע
הבאות. פדרציה היא הסכם בין קבוצות — מי שנחסם בה נחסם בכולן.

## מה זה **לא**

זו אינה רשימת חסימות עולמית. פדרציה נוצרת בידי אדם, קבוצות מצטרפות
אליה **מרצון**, ומנהל הקבוצה יכול לעזוב בכל רגע. אין מנגנון שמחיל
חסימה על קבוצה שלא ביקשה.

## הרשאות, ולמה הן נפרדות

חסימה בפדרציה נוגעת לקבוצות של אנשים אחרים. לכן ‎fed_admins‎ הוא
מעגל נפרד מ-‎admin‎ של קבוצה: להיות מנהל בקבוצה אחת בפדרציה אינו
נותן להשבית משתמש בתשע האחרות. מי שמעניק את הסמכות הזאת הוא בעל
הפדרציה, במפורש.

## שחזור

ביטול חסימה בפדרציה מסיר אותה מהרשימה — אבל **אינו** משחרר
אוטומטית בכל הקבוצות. שחרור הוא פעולה שמנהל מקומי מבצע, כי ייתכן
שהוא חסם את אותו אדם גם מסיבה משלו.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Optional

ID_LEN = 10
MAX_CHATS = 200


def new_id() -> str:
    """מזהה קצר וקריא. לא רץ, כדי שלא ינחשו פדרציות של אחרים."""
    return secrets.token_hex(ID_LEN // 2)


@dataclass(frozen=True)
class Fed:
    fed_id: str
    name: str
    owner_id: int


class Federations:
    def __init__(self, db):
        self.db = db

    # ── יצירה וחברות ──────────────────────────────────────────────────────
    def create(self, name: str, owner_id: int) -> Optional[Fed]:
        name = (name or "").strip()[:64]
        if not name:
            return None
        fid = new_id()
        self.db.run("""INSERT INTO federations (fed_id,name,owner_id,created_at)
                       VALUES (?,?,?,?)""", (fid, name, owner_id, time.time()))
        self.db.run("""INSERT INTO fed_admins (fed_id,user_id) VALUES (?,?)
                       ON CONFLICT DO NOTHING""", (fid, owner_id))
        return Fed(fid, name, owner_id)

    def get(self, fed_id: str) -> Optional[Fed]:
        r = self.db.one("SELECT * FROM federations WHERE fed_id=?",
                        ((fed_id or "").strip(),))
        return Fed(r["fed_id"], r["name"], r["owner_id"]) if r else None

    def owned_by(self, user_id: int) -> list[Fed]:
        return [Fed(r["fed_id"], r["name"], r["owner_id"]) for r in self.db.q(
            "SELECT * FROM federations WHERE owner_id=? ORDER BY name",
            (user_id,))]

    def join(self, fed_id: str, chat_id: int) -> bool:
        if self.get(fed_id) is None:
            return False
        if len(self.chats(fed_id)) >= MAX_CHATS:
            return False
        # קבוצה בפדרציה אחת בלבד. שתיים היו יוצרות שאלה שאין לה
        # תשובה טובה: איזו חסימה גוברת כשהן סותרות.
        self.db.change("DELETE FROM fed_chats WHERE chat_id=?", (chat_id,))
        self.db.run("""INSERT INTO fed_chats (fed_id,chat_id,joined_at)
                       VALUES (?,?,?)""", (fed_id, chat_id, time.time()))
        return True

    def leave(self, chat_id: int) -> int:
        return self.db.change("DELETE FROM fed_chats WHERE chat_id=?",
                              (chat_id,))

    def of_chat(self, chat_id: int) -> Optional[Fed]:
        r = self.db.one("SELECT fed_id FROM fed_chats WHERE chat_id=?",
                        (chat_id,))
        return self.get(r["fed_id"]) if r else None

    def chats(self, fed_id: str) -> list[int]:
        return [r["chat_id"] for r in self.db.q(
            "SELECT chat_id FROM fed_chats WHERE fed_id=?", (fed_id,))]

    # ── סמכות ─────────────────────────────────────────────────────────────
    def is_admin(self, fed_id: str, user_id: int) -> bool:
        return self.db.one(
            "SELECT 1 FROM fed_admins WHERE fed_id=? AND user_id=?",
            (fed_id, user_id)) is not None

    def add_admin(self, fed_id: str, user_id: int) -> bool:
        if self.get(fed_id) is None:
            return False
        self.db.run("""INSERT INTO fed_admins (fed_id,user_id) VALUES (?,?)
                       ON CONFLICT DO NOTHING""", (fed_id, user_id))
        return True

    def remove_admin(self, fed_id: str, user_id: int) -> int:
        f = self.get(fed_id)
        if f and f.owner_id == user_id:
            return 0            # בעלים אינו ניתן להסרה מהסמכות שלו
        return self.db.change(
            "DELETE FROM fed_admins WHERE fed_id=? AND user_id=?",
            (fed_id, user_id))

    def admins(self, fed_id: str) -> list[int]:
        return [r["user_id"] for r in self.db.q(
            "SELECT user_id FROM fed_admins WHERE fed_id=?", (fed_id,))]

    # ── חסימות ────────────────────────────────────────────────────────────
    def ban(self, fed_id: str, user_id: int, reason: str = "",
            by: Optional[int] = None) -> bool:
        if self.get(fed_id) is None:
            return False
        self.db.run("""INSERT INTO fed_bans (fed_id,user_id,reason,by_id,ts)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT (fed_id,user_id) DO UPDATE SET
                         reason=excluded.reason, by_id=excluded.by_id,
                         ts=excluded.ts""",
                    (fed_id, user_id, reason[:200], by, time.time()))
        return True

    def unban(self, fed_id: str, user_id: int) -> int:
        return self.db.change(
            "DELETE FROM fed_bans WHERE fed_id=? AND user_id=?",
            (fed_id, user_id))

    def is_banned(self, fed_id: str, user_id: int) -> Optional[dict]:
        r = self.db.one(
            "SELECT reason,by_id,ts FROM fed_bans WHERE fed_id=? AND user_id=?",
            (fed_id, user_id))
        return dict(r) if r else None

    def banned_here(self, chat_id: int, user_id: int) -> Optional[dict]:
        """האם המשתמש חסום בפדרציה של הקבוצה הזאת. שאילתה אחת."""
        r = self.db.one(
            """SELECT b.reason, b.ts, b.fed_id FROM fed_bans b
               JOIN fed_chats c ON c.fed_id = b.fed_id
               WHERE c.chat_id=? AND b.user_id=?""", (chat_id, user_id))
        return dict(r) if r else None

    def bans(self, fed_id: str, limit: int = 20) -> list[dict]:
        return [dict(r) for r in self.db.q(
            """SELECT user_id,reason,ts FROM fed_bans WHERE fed_id=?
               ORDER BY ts DESC LIMIT ?""", (fed_id, limit))]

    def count_bans(self, fed_id: str) -> int:
        r = self.db.one("SELECT COUNT(*) c FROM fed_bans WHERE fed_id=?",
                        (fed_id,))
        return r["c"] if r else 0

    def delete(self, fed_id: str, by: int) -> bool:
        """מחיקה מלאה. רק בעלים, ורק במפורש."""
        f = self.get(fed_id)
        if f is None or f.owner_id != by:
            return False
        for table in ("fed_bans", "fed_admins", "fed_chats"):
            self.db.change(f"DELETE FROM {table} WHERE fed_id=?", (fed_id,))
        self.db.change("DELETE FROM federations WHERE fed_id=?", (fed_id,))
        return True
