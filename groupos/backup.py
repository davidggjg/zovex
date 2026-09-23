#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backup — ייצוא וייבוא של הגדרות הקבוצה.

## למה זה לא "נחמד שיהיה"

מנהל שהקים קבוצה שנייה לא אמור להגדיר 32 נעילות, 40 ביטויים חסומים
ו-15 פילטרים מחדש. וקבוצה שאיבדה הגדרות בטעות צריכה דרך חזרה.

## מה לא נכנס לייצוא

**מזהי משתמשים, אזהרות וענישות לא נכנסים.** קובץ הגדרות עובר בצ'אט,
נשמר בענן ומועבר הלאה; היסטוריית משמעת של אנשים אינה אמורה לנסוע
ככה. מה שנכנס הוא **תצורה**: הגדרות, נעילות, חסומים, פילטרים, הערות,
חוקים וברכות.

## מפתחות שלא מיוצאים

‎lockdown‎ ו-‎emergency‎ הם **מצב רגעי** ולא תצורה. ייבוא שהיה מדליק
מצב חירום בקבוצה אחרת הוא בדיוק סוג ההפתעה שאסור שתקרה מקובץ.

## גרסה

הקובץ נושא ‎version‎. ייבוא של גרסה שאינה מוכרת נדחה במקום לנחש —
ניחוש על תצורת אבטחה הוא דרך להשבית קבוצה בשקט.
"""
from __future__ import annotations

import json
import time
from typing import Any

FORMAT_VERSION = 1

# מצב רגעי, לא תצורה. לא מיוצא ולא מיובא.
VOLATILE = {"lockdown", "emergency", "_emergency_before"}


def export(db, chat_id: int) -> dict:
    settings = {r["key"]: r["value"] for r in db.q(
        "SELECT key,value FROM settings WHERE chat_id=?", (chat_id,))
        if r["key"] not in VOLATILE}
    return {
        "version": FORMAT_VERSION,
        "exported_at": time.time(),
        "settings": settings,
        "locks": [dict(r) for r in db.q(
            "SELECT lock_type,action,duration FROM locks WHERE chat_id=?",
            (chat_id,))],
        "blocklist": [dict(r) for r in db.q(
            "SELECT pattern,kind,action FROM blocklist WHERE chat_id=?",
            (chat_id,))],
        "filters": [dict(r) for r in db.q(
            """SELECT trigger,match_kind,action,content FROM filters
               WHERE chat_id=?""", (chat_id,))],
        "notes": [dict(r) for r in db.q(
            """SELECT name,content,buttons,visibility FROM notes
               WHERE chat_id=?""", (chat_id,))],
        "allowlist": [dict(r) for r in db.q(
            "SELECT scope,value FROM allowlist WHERE chat_id=?", (chat_id,))],
    }


def dumps(db, chat_id: int) -> str:
    return json.dumps(export(db, chat_id), ensure_ascii=False, indent=1)


def counts(data: dict) -> dict[str, int]:
    return {k: len(data.get(k) or [])
            for k in ("locks", "blocklist", "filters", "notes", "allowlist")}


class ImportError_(ValueError):
    pass


def parse(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as e:
        raise ImportError_("bad_json") from e
    if not isinstance(data, dict):
        raise ImportError_("bad_json")
    if data.get("version") != FORMAT_VERSION:
        raise ImportError_("bad_version")
    return data


def apply(db, chat_id: int, data: dict, by: Any = None, *,
          replace: bool = False) -> dict[str, int]:
    """מייבא. ‎replace‎ מוחק קודם; אחרת מוסיף על הקיים.

    ברירת המחדל היא **הוספה**. ייבוא שמוחק בשקט הגדרות קיימות הוא
    פעולה הרסנית, והרסנית דורשת בקשה מפורשת."""
    parts = counts(data)
    if replace:
        for table in ("locks", "blocklist", "filters", "notes", "allowlist"):
            db.change(f"DELETE FROM {table} WHERE chat_id=?", (chat_id,))

    for k, v in (data.get("settings") or {}).items():
        if k in VOLATILE:
            continue
        db.set(chat_id, str(k), str(v), by)

    now = time.time()
    for r in data.get("locks") or []:
        db.run("""INSERT INTO locks (chat_id,lock_type,action,duration)
                  VALUES (?,?,?,?)
                  ON CONFLICT (chat_id,lock_type) DO UPDATE SET
                    action=excluded.action, duration=excluded.duration""",
               (chat_id, r.get("lock_type"), r.get("action", "delete"),
                r.get("duration")))
    for r in data.get("blocklist") or []:
        db.run("""INSERT INTO blocklist (chat_id,pattern,kind,action,created_at)
                  VALUES (?,?,?,?,?)""",
               (chat_id, r.get("pattern"), r.get("kind", "word"),
                r.get("action", "delete"), now))
    for r in data.get("filters") or []:
        db.run("""INSERT INTO filters
                  (chat_id,trigger,match_kind,action,content,created_at)
                  VALUES (?,?,?,?,?,?)""",
               (chat_id, r.get("trigger"), r.get("match_kind", "word"),
                r.get("action", "reply"), r.get("content"), now))
    for r in data.get("notes") or []:
        db.run("""INSERT INTO notes
                  (chat_id,name,content,buttons,visibility,created_by,created_at)
                  VALUES (?,?,?,?,?,?,?)
                  ON CONFLICT (chat_id,name) DO UPDATE SET
                    content=excluded.content, buttons=excluded.buttons""",
               (chat_id, r.get("name"), r.get("content", ""),
                r.get("buttons", ""), r.get("visibility", "public"), by, now))
    for r in data.get("allowlist") or []:
        db.run("""INSERT INTO allowlist (chat_id,scope,value) VALUES (?,?,?)
                  ON CONFLICT (chat_id,scope,value) DO NOTHING""",
               (chat_id, r.get("scope"), r.get("value")))
    return parts
