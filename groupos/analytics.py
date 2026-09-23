#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""analytics — מה קרה בקבוצה, לפי טווח.

## למה זה לא רק ‎COUNT(*)‎

מספר לבדו אינו אומר כלום. "42 פעולות" הוא הרבה או מעט? לכן כל מדד
מוחזר עם **השוואה לתקופה הקודמת באותו אורך**, וזה מה שהופך מספר
לידיעה: 42 מול 8 אתמול הוא אירוע; 42 מול 45 הוא יום רגיל.

## מאיפה הנתונים

מהיומן ומטבלת החברים — שתיהן נכתבות ממילא. אין טבלת מדדים נפרדת,
ולכן אין מה לתחזק, אין מה לסנכרן, ואין מצב שבו הדוח והיומן חלוקים.

## מה **לא** נספר

תוכן הודעות. הספירה היא של אירועים, לא של מה שאנשים כתבו.
"""
from __future__ import annotations

import time
from typing import Optional

RANGES = {"today": 86400, "week": 7 * 86400, "month": 30 * 86400,
          "year": 365 * 86400}

# הפעולות שמעניין לספור, ומפתח התרגום שלהן.
TRACKED = (
    ("user.ban", "an.bans"),
    ("user.kick", "an.kicks"),
    ("mute", "an.mutes"),
    ("user.warn", "an.warns"),
    ("lock.triggered", "an.locks"),
    ("blocklist.hit", "an.blocked"),
    ("blocklist.evaded", "an.evaded"),
    ("flood.rate", "an.flood"),
    ("captcha.failed", "an.captcha_fail"),
    ("ai.action", "an.ai"),
    ("user.report", "an.reports"),
    ("raid.detected", "an.raids"),
)


def _count(db, chat_id: int, action: str, since: float,
           until: Optional[float] = None) -> int:
    q = "SELECT COUNT(*) c FROM audit_log WHERE chat_id=? AND action=? AND ts>?"
    args = [chat_id, action, since]
    if until is not None:
        q += " AND ts<=?"
        args.append(until)
    r = db.one(q, tuple(args))
    return r["c"] if r else 0


def _delta(now: int, before: int) -> Optional[int]:
    """שינוי באחוזים. ‎None‎ כשאין ממה להשוות — עדיף מ-0% מטעה."""
    if before == 0:
        return None if now == 0 else 100
    return round(100 * (now - before) / before)


def report(db, chat_id: int, span: str = "today",
           now: Optional[float] = None) -> dict:
    """‎{מפתח: (עכשיו, שינוי באחוזים)}‎ ועוד כמה מספרי מצב."""
    t = now if now is not None else time.time()
    width = RANGES.get(span, RANGES["today"])
    cur_from = t - width
    prev_from = t - 2 * width

    rows = {}
    for action, label in TRACKED:
        c = _count(db, chat_id, action, cur_from)
        p = _count(db, chat_id, action, prev_from, cur_from)
        if c or p:
            rows[label] = (c, _delta(c, p))

    def one(sql, args):
        r = db.one(sql, args)
        return (r["c"] if r else 0)

    members = one("SELECT COUNT(*) c FROM members WHERE chat_id=?", (chat_id,))
    joined = one("""SELECT COUNT(*) c FROM members
                    WHERE chat_id=? AND joined_at>?""", (chat_id, cur_from))
    joined_p = one("""SELECT COUNT(*) c FROM members
                      WHERE chat_id=? AND joined_at>? AND joined_at<=?""",
                   (chat_id, prev_from, cur_from))
    active = one("""SELECT COUNT(*) c FROM members
                    WHERE chat_id=? AND last_msg>?""", (chat_id, cur_from))
    active_p = one("""SELECT COUNT(*) c FROM members
                      WHERE chat_id=? AND last_msg>? AND last_msg<=?""",
                   (chat_id, prev_from, cur_from))
    return {
        "span": span,
        "members": members,
        "joined": (joined, _delta(joined, joined_p)),
        "active": (active, _delta(active, active_p)),
        "actions": rows,
        "total": sum(v[0] for v in rows.values()),
    }


def busiest_hours(db, chat_id: int, days: int = 7,
                  now: Optional[float] = None) -> list[tuple[int, int]]:
    """‎[(שעה, כמה)]‎ — מתי הקבוצה ערה. שימושי לתזמון הודעות."""
    t = now if now is not None else time.time()
    rows = db.q("""SELECT ts FROM audit_log WHERE chat_id=? AND ts>?""",
                (chat_id, t - days * 86400))
    hours: dict[int, int] = {}
    for r in rows:
        h = time.localtime(r["ts"]).tm_hour
        hours[h] = hours.get(h, 0) + 1
    return sorted(hours.items(), key=lambda kv: -kv[1])[:5]


def top_offenders(db, chat_id: int, span: str = "week",
                  limit: int = 5,
                  now: Optional[float] = None) -> list[tuple[int, int]]:
    """מי נתפס הכי הרבה. נתון ניהולי, לא ציון ציבורי."""
    t = now if now is not None else time.time()
    since = t - RANGES.get(span, RANGES["week"])
    return [(r["target_id"], r["c"]) for r in db.q(
        """SELECT target_id, COUNT(*) c FROM audit_log
           WHERE chat_id=? AND ts>? AND target_id IS NOT NULL
             AND severity IN ('medium','high','critical')
           GROUP BY target_id ORDER BY c DESC LIMIT ?""",
        (chat_id, since, limit))]
