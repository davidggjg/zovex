#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""locks — מה מותר לשלוח בקבוצה.

## למה זה מודול טהור

אין כאן שורה אחת שיודעת מה זה aiogram. הקלט הוא תיאור הודעה כמילון,
הפלט הוא החלטה. כך אפשר לבדוק 30 סוגי נעילה בלי קבוצה, בלי בוט ובלי רשת.

## סדר העדיפויות

נעילה מנצחת רשימת חסימה, ורשימת חסימה מנצחת פילטר. הסיבה: נעילה היא
כלל גורף שהמנהל הגדיר במפורש, ופילטר הוא תגובה. אם שניהם מתאימים,
מה שהמנהל אסר גובר על מה שהוא רצה להשיב.

## פעולות

    off          הנעילה כבויה
    delete       מוחקים את ההודעה
    warn         מוחקים ומוסיפים אזהרה
    mute         מוחקים ומשתיקים
    kick         מוחקים ומעיפים
    ban          מוחקים וחוסמים
    tmute        השתקה זמנית
    tban         חסימה זמנית
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

ACTIONS = ("off", "delete", "warn", "mute", "kick", "ban", "tmute", "tban")

# סוגי נעילה. המפתח הוא מה שנשמר במסד, והערך הוא הקבוצה שאליה הוא שייך.
# **השמות אינם כאן.** הם מפתחות תרגום ‎lock.<מפתח>‎ ב-i18n, כי הבוט הזה
# לא מיועד לדוברי עברית בלבד — ושם קשיח בקוד הוא בדיוק מה שנועל שפה.
LOCK_TYPES: dict[str, str] = {
    # מדיה
    "photo": "media", "video": "media", "gif": "media", "sticker": "media",
    "premium_sticker": "media", "audio": "media", "voice": "media",
    "video_note": "media", "document": "media", "album": "media",
    # קישורים והפניות
    "url": "links", "invite": "links", "mention": "links", "forward": "links",
    "email": "links", "phone": "links",
    # אינטראקציה
    "command": "interaction", "bot": "interaction", "button": "interaction",
    "poll": "interaction", "game": "interaction", "contact": "interaction",
    "location": "interaction", "anonchannel": "interaction",
    # טקסט
    "hashtag": "text", "cashtag": "text", "cjk": "text", "cyrillic": "text",
    "arabic": "text", "emoji_only": "text", "caps": "text", "long": "text",
}

GROUPS = ("media", "links", "interaction", "text")

# ── זיהוי ─────────────────────────────────────────────────────────────────
_RX_URL = re.compile(
    r"(?:https?://|www\.)\S+|\b[a-z0-9-]+\.(?:com|net|org|il|ru|io|me|tk|ml|xyz|info|co)\b",
    re.I)
_RX_INVITE = re.compile(r"(?:t\.me/(?:joinchat/|\+)|telegram\.me/joinchat/)\S+", re.I)
_RX_MENTION = re.compile(r"@[A-Za-z][A-Za-z0-9_]{4,}")
_RX_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")
_RX_PHONE = re.compile(r"(?:\+?\d[\d\-\s().]{7,}\d)")
_RX_HASHTAG = re.compile(r"#\w+")
_RX_CASHTAG = re.compile(r"\$[A-Z]{2,10}\b")
_RX_CJK = re.compile(r"[぀-ヿ一-鿿가-힯]")
_RX_CYR = re.compile(r"[Ѐ-ӿ]")
_RX_ARABIC = re.compile(r"[؀-ۿ]")
_RX_EMOJI = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]")

CAPS_MIN_LEN = 12        # מתחת לזה "צעקה" היא סתם קיצור
CAPS_RATIO = 0.7
LONG_CHARS = 1500


@dataclass(frozen=True)
class Hit:
    """מה נורה. ‎lock‎ הוא מפתח — מי שמציג אותו מתרגם אותו לשפה שלו."""
    lock: str
    action: str
    duration: Optional[int] = None

    @property
    def key(self) -> str:
        return f"lock.{self.lock}"


def detect(msg: dict) -> set[str]:
    """אילו סוגי נעילה ההודעה הזאת מפעילה. עצמאי מהגדרות הקבוצה.

    ‎msg‎ הוא מילון פשוט כדי שהמודול יישאר נקי מטלגרם. השדות שנקראים:
    text, caption, entities, media_kind, is_forward, via_bot, has_buttons,
    is_premium_sticker, media_group_id, sender_chat.
    """
    out: set[str] = set()
    text = (msg.get("text") or "") + " " + (msg.get("caption") or "")
    text = text.strip()

    kind = msg.get("media_kind")
    if kind in ("photo", "video", "gif", "sticker", "audio", "voice",
                "video_note", "document", "poll", "game", "contact", "location"):
        out.add(kind)
    if kind == "sticker" and msg.get("is_premium_sticker"):
        out.add("premium_sticker")
    if msg.get("media_group_id"):
        out.add("album")

    if msg.get("is_forward"):
        out.add("forward")
    if msg.get("via_bot"):
        out.add("bot")
    if msg.get("has_buttons"):
        out.add("button")
    if msg.get("sender_chat"):
        out.add("anonchannel")

    if text:
        if _RX_INVITE.search(text):
            out.add("invite")
            out.add("url")          # קישור הזמנה הוא גם קישור
        elif _RX_URL.search(text):
            out.add("url")
        if _RX_MENTION.search(text):
            out.add("mention")
        if _RX_EMAIL.search(text):
            out.add("email")
        if _RX_PHONE.search(text):
            out.add("phone")
        if _RX_HASHTAG.search(text):
            out.add("hashtag")
        if _RX_CASHTAG.search(text):
            out.add("cashtag")
        if _RX_CJK.search(text):
            out.add("cjk")
        if _RX_CYR.search(text):
            out.add("cyrillic")
        if _RX_ARABIC.search(text):
            out.add("arabic")
        if text.startswith("/"):
            out.add("command")
        if len(text) > LONG_CHARS:
            out.add("long")

        letters = [c for c in text if c.isalpha()]
        if len(letters) >= CAPS_MIN_LEN:
            upper = sum(1 for c in letters if c.isupper())
            # עברית אינה מבחינה בין גדולות לקטנות, ולכן טקסט עברי לעולם
            # לא ייחשב צעקה — וזה נכון.
            if upper / len(letters) >= CAPS_RATIO:
                out.add("caps")

        stripped = _RX_EMOJI.sub("", text).strip()
        if not stripped and _RX_EMOJI.search(text):
            out.add("emoji_only")

    return out


class Locks:
    def __init__(self, db):
        self.db = db

    def get_all(self, chat_id: int) -> dict[str, tuple[str, Optional[int]]]:
        return {r["lock_type"]: (r["action"], r["duration"])
                for r in self.db.q(
                    "SELECT lock_type,action,duration FROM locks WHERE chat_id=?",
                    (chat_id,))}

    def set(self, chat_id: int, lock: str, action: str,
            duration: Optional[int] = None) -> None:
        if lock not in LOCK_TYPES:
            raise ValueError(f"סוג נעילה לא מוכר: {lock}")
        if action not in ACTIONS:
            raise ValueError(f"פעולה לא מוכרת: {action}")
        if action == "off":
            self.db.change("DELETE FROM locks WHERE chat_id=? AND lock_type=?",
                        (chat_id, lock))
            return
        self.db.run("""INSERT INTO locks (chat_id,lock_type,action,duration)
                       VALUES (?,?,?,?)
                       ON CONFLICT (chat_id,lock_type) DO UPDATE SET
                         action=excluded.action, duration=excluded.duration""",
                    (chat_id, lock, action, duration))

    def check(self, chat_id: int, msg: dict) -> Optional[Hit]:
        """הנעילה החמורה ביותר שההודעה מפעילה, או None.

        כשהודעה מפעילה כמה נעילות בוחרים את החמורה. אחרת קישור-הזמנה
        שנעול ב-ban היה מטופל כ-delete רק כי 'url' נבדק קודם.
        """
        active = self.get_all(chat_id)
        if not active:
            return None
        fired = detect(msg) & set(active)
        if not fired:
            return None
        best = max(fired, key=lambda l: ACTIONS.index(active[l][0]))
        action, dur = active[best]
        return Hit(best, action, dur)

    def by_group(self, chat_id: int) -> dict[str, list[tuple[str, str]]]:
        """לתצוגה בפאנל: {קבוצה: [(מפתח, פעולה)]}. השם מתורגם בתצוגה."""
        active = self.get_all(chat_id)
        out: dict[str, list] = {g: [] for g in GROUPS}
        for key, grp in LOCK_TYPES.items():
            out[grp].append((key, active.get(key, ("off", None))[0]))
        return out

    def set_many(self, chat_id: int, action: str,
                 only: Optional[set[str]] = None) -> int:
        """נעילה או פתיחה של כל הסוגים בבת אחת. מחזיר כמה שונו.

        ‎/lockall‎ ו-‎/unlockall‎ הן הפקודות שמנהל מחפש כשמתחיל ספאם,
        ולחיצה על 32 כפתורים בזה אחר זה אינה תשובה."""
        keys = [k for k in LOCK_TYPES if only is None or k in only]
        for k in keys:
            self.set(chat_id, k, action)
        return len(keys)
