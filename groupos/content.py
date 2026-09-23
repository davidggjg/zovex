#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""content — Notes, Filters, Rules, Welcome ו-Goodbye.

## למה הארבעה יחד

כולם אותו דבר מבחינת נתונים: **טקסט שמור, אולי מדיה, אולי כפתורים,
שנשלח בתגובה לאירוע.** ההבדל היחיד הוא מה מפעיל אותם — פקודה, מילה,
כניסה לקבוצה או יציאה ממנה. פיצול לארבעה מודולים היה משכפל את אותו
קוד ארבע פעמים, ואז ‎{user}‎ היה עובד בברכה ולא בפילטר.

## כפתורים

נשמרים כטקסט בשורה אחת לכפתור:

    כותרת|https://example.com

הסיבה שזה טקסט ולא JSON: המנהל כותב את זה בטלגרם, ובטלגרם אין עורך
JSON. מה שלא נפרס נזרק בשקט — כפתור שבור לא אמור למנוע מהערה להישלח.

## למה ‎Filter‎ בודק מילה ולא ‎in‎

‎"היי"‎ בתוך ‎"היינו"‎ אינו אותה מילה. פילטר שנורה על כל הופעה הוא
פילטר שמנהלים מכבים אחרי יומיים. ברירת המחדל היא מילה שלמה, ומי
שרוצה אחרת מבקש ‎substring‎ במפורש.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional

import blocklist as _bl

MATCH_KINDS = ("word", "substring", "regex", "starts")
FILTER_ACTIONS = ("reply", "delete", "warn", "mute", "kick", "ban",
                  "delete_reply")
VISIBILITY = ("public", "admin")

# הגדרות שהן "תוכן של הקבוצה" ולא התנהגות. נשמרות ב-settings.
RULES_KEY = "rules"
WELCOME_KEY = "welcome"
GOODBYE_KEY = "goodbye"


# ── כפתורים ───────────────────────────────────────────────────────────────
def parse_buttons(raw: str) -> list[list[tuple[str, str]]]:
    """‎'כותרת|url'‎ בכל שורה. שתי כותרות בשורה מופרדות ב-‎&&‎."""
    rows: list[list[tuple[str, str]]] = []
    for line in (raw or "").splitlines():
        row: list[tuple[str, str]] = []
        for cell in line.split("&&"):
            if "|" not in cell:
                continue
            label, url = cell.split("|", 1)
            label, url = label.strip(), url.strip()
            # רק http/https. ‎javascript:‎ ו-‎tg://‎ בידי משתמש הם וקטור.
            if label and re.match(r"^https?://\S+$", url):
                row.append((label[:64], url))
        if row:
            rows.append(row[:3])
    return rows[:8]


def format_buttons(rows: list[list[tuple[str, str]]]) -> str:
    return "\n".join(" && ".join(f"{t}|{u}" for t, u in row) for row in rows)


# ── Notes ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Note:
    name: str
    content: str
    media_id: Optional[str]
    media_kind: Optional[str]
    buttons: str
    visibility: str


def clean_name(name: str) -> str:
    """שם הערה. בלי ‎#‎ מוביל, בלי רווחים, אותיות קטנות."""
    return re.sub(r"\s+", "_", (name or "").strip().lstrip("#/")).lower()[:64]


class Notes:
    def __init__(self, db):
        self.db = db

    def save(self, chat_id: int, name: str, content: str, *,
             media_id: Optional[str] = None, media_kind: Optional[str] = None,
             buttons: str = "", visibility: str = "public",
             by: Optional[int] = None) -> bool:
        name = clean_name(name)
        if not name or (not content.strip() and not media_id):
            return False
        if visibility not in VISIBILITY:
            visibility = "public"
        self.db.run("""INSERT INTO notes
                       (chat_id,name,content,media_id,media_kind,buttons,
                        visibility,created_by,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)
                       ON CONFLICT (chat_id,name) DO UPDATE SET
                         content=excluded.content, media_id=excluded.media_id,
                         media_kind=excluded.media_kind,
                         buttons=excluded.buttons,
                         visibility=excluded.visibility""",
                    (chat_id, name, content, media_id, media_kind, buttons,
                     visibility, by, time.time()))
        return True

    def get(self, chat_id: int, name: str) -> Optional[Note]:
        r = self.db.one("""SELECT name,content,media_id,media_kind,buttons,
                                  visibility FROM notes
                           WHERE chat_id=? AND name=?""",
                        (chat_id, clean_name(name)))
        return Note(r["name"], r["content"], r["media_id"], r["media_kind"],
                    r["buttons"] or "", r["visibility"]) if r else None

    def names(self, chat_id: int, include_admin: bool = False) -> list[str]:
        q = "SELECT name FROM notes WHERE chat_id=?"
        if not include_admin:
            q += " AND visibility='public'"
        return [r["name"] for r in self.db.q(q + " ORDER BY name", (chat_id,))]

    def delete(self, chat_id: int, name: str) -> int:
        return self.db.change("DELETE FROM notes WHERE chat_id=? AND name=?",
                              (chat_id, clean_name(name)))

    def clear(self, chat_id: int) -> int:
        return self.db.change("DELETE FROM notes WHERE chat_id=?", (chat_id,))


# ── Filters ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FilterHit:
    trigger: str
    action: str
    content: str


class Filters:
    def __init__(self, db):
        self.db = db

    def all(self, chat_id: int) -> list[dict]:
        return [dict(r) for r in self.db.q(
            """SELECT id,trigger,match_kind,action,content FROM filters
               WHERE chat_id=? AND enabled=1 ORDER BY id""", (chat_id,))]

    def add(self, chat_id: int, trigger: str, content: str, *,
            match_kind: str = "word", action: str = "reply") -> bool:
        trigger = (trigger or "").strip().lower()
        if not trigger or match_kind not in MATCH_KINDS:
            return False
        if action not in FILTER_ACTIONS:
            return False
        if match_kind == "regex":
            try:
                re.compile(trigger)
            except re.error:
                return False
        self.db.run("DELETE FROM filters WHERE chat_id=? AND trigger=?",
                    (chat_id, trigger))
        self.db.run("""INSERT INTO filters
                       (chat_id,trigger,match_kind,action,content,created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (chat_id, trigger, match_kind, action, content, time.time()))
        return True

    def remove(self, chat_id: int, trigger: str) -> int:
        return self.db.change(
            "DELETE FROM filters WHERE chat_id=? AND trigger=?",
            (chat_id, (trigger or "").strip().lower()))

    def triggers(self, chat_id: int) -> list[str]:
        return [r["trigger"] for r in self.db.q(
            "SELECT trigger FROM filters WHERE chat_id=? ORDER BY trigger",
            (chat_id,))]

    def check(self, chat_id: int, text: str) -> Optional[FilterHit]:
        return match_filters(text, self.all(chat_id))


def match_filters(text: str, rules: list[dict]) -> Optional[FilterHit]:
    """הפילטר הראשון שמתאים. טהור, כדי שאפשר לבדוק בלי מסד."""
    if not text or not rules:
        return None
    low = text.lower()
    norm = _bl.normalize(text)
    for r in rules:
        trg, kind = r["trigger"], r.get("match_kind", "word")
        hit = False
        if kind == "regex":
            try:
                hit = re.search(trg, text, re.I) is not None
            except re.error:
                hit = False
        elif kind == "substring":
            hit = trg in low
        elif kind == "starts":
            hit = low.startswith(trg)
        else:
            p = re.escape(_bl.normalize(trg))
            hit = bool(p) and re.search(r"(?<!\w)" + p + r"(?!\w)", norm)
        if hit:
            return FilterHit(trg, r.get("action", "reply"), r.get("content") or "")
    return None
