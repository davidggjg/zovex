#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evidence — מה הבוט ראה, לפני שהוא מחק את זה.

## הבקשה שמאחורי המודול

"אני רוצה לראות על מה הוא העיף אנשים — לפעמים אני רוצה להיות בטוח
שהוא לא מעיף סתם."

בקשה נכונה, וחשובה יותר מרוב התכונות כאן: בוט שמעניש בלי שאפשר
לבדוק אותו הוא בוט שמאמינים לו או מכבים אותו, ואין דרך שלישית.

הבעיה: עד כה היומן רשם **שהודעה נמחקה ושמשתמש הועף**, ואת הסיבה
במילה אחת — ‎lock.photo‎, ‎spam.adult_ad‎. ההודעה עצמה כבר לא קיימת,
כי הבוט מחק אותה. כלומר בדיוק מה שהמנהל רוצה לראות הוא הדבר היחיד
שלא נשמר.

## מה נשמר

צילום של ההודעה ברגע שלפני המחיקה: הטקסט או הכיתוב, סוג המדיה,
‎file_id‎ שלה, הסיבה, הציון והפעולה. ‎file_id‎ נשאר תקף אצל טלגרם גם
אחרי שההודעה נמחקה מהצ'אט, ולכן אפשר **לשלוח למנהל את התמונה
עצמה** בפרטי — לא תיאור שלה.

## מה לא נשמר

כל השאר. אין כאן העתק של הקבוצה: נשמרות רק הודעות שהבוט **פעל
עליהן**. הודעה שעברה בשלום אינה נכתבת לשום מקום, וזה ההבדל בין יומן
אכיפה לבין ציתות.

## למה יש תפוגה

ראיה בת חצי שנה אינה ראיה, היא מאגר. ‎prune‎ מוחק מעל גיל שנקבע
(ברירת מחדל 30 יום) ומעל תקרה לכל קבוצה, ורץ בתחזוקה היומית.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

MAX_TEXT = 1000          # יותר מזה אינו עוזר להחליט, רק תופס מקום
KEEP_DAYS = 30
KEEP_ROWS = 500          # לכל קבוצה


@dataclass(frozen=True)
class Item:
    id: int
    chat_id: int
    user_id: int
    ts: float
    action: str
    reason: str
    risk: float
    text: str
    media_kind: str
    media_id: str
    name: str

    @property
    def has_media(self) -> bool:
        return bool(self.media_id)

    def preview(self, limit: int = 40) -> str:
        """שורה אחת לרשימה. מדיה בלי כיתוב מתוארת ולא נשארת ריקה."""
        t = " ".join((self.text or "").split())
        if t:
            return t[:limit] + ("…" if len(t) > limit else "")
        return f"[{self.media_kind}]" if self.media_kind else "—"


class Evidence:
    def __init__(self, db):
        self.db = db

    def add(self, chat_id: int, user_id: int, *, action: str,
            reason: str = "", risk: float = 0.0, text: str = "",
            media_kind: str = "", media_id: str = "", name: str = "",
            message_id: Optional[int] = None,
            now: Optional[float] = None) -> int:
        """שומר צילום של ההודעה. מחזיר מזהה, או 0 בכישלון.

        **לא זורק.** כישלון בשמירת ראיה אינו סיבה לא לאכוף: עדיף
        אכיפה בלי תיעוד מאשר ספאם שנשאר בגלל שגיאת כתיבה."""
        try:
            return self.db.run(
                """INSERT INTO evidence
                   (chat_id,user_id,ts,action,reason,risk,text,media_kind,
                    media_id,name,message_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (chat_id, user_id, now if now is not None else time.time(),
                 action, (reason or "")[:200], float(risk),
                 (text or "")[:MAX_TEXT], media_kind or "", media_id or "",
                 (name or "")[:64], message_id)) or 0
        except Exception:
            return 0

    def _row(self, r: Any) -> Item:
        return Item(r["id"], r["chat_id"], r["user_id"], r["ts"], r["action"],
                    r["reason"] or "", r["risk"] or 0.0, r["text"] or "",
                    r["media_kind"] or "", r["media_id"] or "",
                    r["name"] or "")

    def recent(self, chat_id: int, limit: int = 10,
               offset: int = 0) -> list[Item]:
        return [self._row(r) for r in self.db.q(
            """SELECT * FROM evidence WHERE chat_id=?
               ORDER BY ts DESC LIMIT ? OFFSET ?""",
            (chat_id, limit, offset))]

    def for_user(self, chat_id: int, user_id: int,
                 limit: int = 10) -> list[Item]:
        """כל המקרים של אותו אדם. זה מה שמבדיל טעות אחת מדפוס."""
        return [self._row(r) for r in self.db.q(
            """SELECT * FROM evidence WHERE chat_id=? AND user_id=?
               ORDER BY ts DESC LIMIT ?""", (chat_id, user_id, limit))]

    def get(self, chat_id: int, ev_id: int) -> Optional[Item]:
        r = self.db.one("SELECT * FROM evidence WHERE chat_id=? AND id=?",
                        (chat_id, ev_id))
        return self._row(r) if r else None

    def count(self, chat_id: int) -> int:
        r = self.db.one("SELECT COUNT(*) c FROM evidence WHERE chat_id=?",
                        (chat_id,))
        return r["c"] if r else 0

    def count_user(self, chat_id: int, user_id: int) -> int:
        r = self.db.one(
            "SELECT COUNT(*) c FROM evidence WHERE chat_id=? AND user_id=?",
            (chat_id, user_id))
        return r["c"] if r else 0

    def prune(self, *, days: int = KEEP_DAYS, rows: int = KEEP_ROWS,
              now: Optional[float] = None) -> int:
        """מוחק ישן ועודף. מחזיר כמה נמחקו.

        שני כללים ולא אחד: גיל, כדי שראיה לא תהפוך למאגר, ותקרה לכל
        קבוצה, כדי שקבוצה אחת שמוצפת לא תתפח על חשבון כל השאר."""
        t = now if now is not None else time.time()
        gone = self.db.change("DELETE FROM evidence WHERE ts < ?",
                              (t - days * 86400,))
        for r in self.db.q("""SELECT chat_id, COUNT(*) c FROM evidence
                              GROUP BY chat_id HAVING c > ?""", (rows,)):
            gone += self.db.change(
                """DELETE FROM evidence WHERE chat_id=? AND id NOT IN
                   (SELECT id FROM evidence WHERE chat_id=?
                    ORDER BY ts DESC LIMIT ?)""",
                (r["chat_id"], r["chat_id"], rows))
        return gone
