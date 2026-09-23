#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scheduler — הודעות שנשלחות מעצמן.

## למה לא cron

cron הוא תהליך של המערכת; כאן מדובר בהודעות של קבוצות, שמנהל מוסיף
ומוחק מתוך טלגרם. שמירה במסד פירושה שהן שורדות אתחול, שאפשר לראות
אותן, ושמחיקת קבוצה מוחקת גם אותן.

## ‎next_run‎ מחושב מראש

הלולאה שולפת ‎WHERE enabled=1 AND next_run <= now‎ עם אינדקס. החלופה
— לעבור על כל השורות ולחשב לכל אחת מתי הפעם הבאה — עולה יותר ככל
שיש יותר תזמונים, וזה בדיוק הכיוון הלא נכון.

## למה לא לצבור ריצות שהוחמצו

שירות שהיה כבוי יומיים לא צריך לירות שישים הודעות ברגע שהוא עולה.
‎catch_up=False‎ מקדם את ‎next_run‎ קדימה עד שהוא בעתיד, ומוותר על
מה שהוחמץ. זו התנהגות נכונה להודעות ולא לתורי עבודה.

## אזורי זמן

הזמן נשמר כשעה מקומית של הקבוצה (‎tz_offset‎ בדקות), והחישוב נעשה
ב-UTC. קבוצה בישראל שקבעה 20:00 תקבל 20:00 שלה גם אחרי מעבר שעון —
כי ההיסט נקרא בכל חישוב מחדש ולא מוקפא ביצירה.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional

KINDS = ("once", "daily", "weekly", "monthly", "every")

MIN_INTERVAL = 300          # חמש דקות. מתחת לזה זה ספאם ולא תזמון
MAX_PER_CHAT = 50

_RX_TIME = re.compile(r"^(\d{1,2}):(\d{2})$")
_RX_EVERY = re.compile(r"^(\d+)([mhd])$", re.I)
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class Spec:
    kind: str
    hour: int = 0
    minute: int = 0
    weekday: int = -1        # 0=שני … 6=ראשון
    day: int = 0             # ביום בחודש
    seconds: int = 0         # ל-‎every‎
    at: float = 0.0          # ל-‎once‎


def parse_spec(raw: str, *, now: Optional[float] = None,
               tz_offset: int = 0) -> Optional[Spec]:
    """‎'daily 20:00'‎ · ‎'weekly sun 09:30'‎ · ‎'every 2h'‎ · ‎'20:00'‎.

    ניסוח שאינו מובן מחזיר ‎None‎ ולא זורק: מנהל שהקליד לא נכון צריך
    לקבל הסבר, לא שירות שנפל."""
    parts = (raw or "").strip().lower().split()
    if not parts:
        return None
    head = parts[0]

    if _RX_TIME.match(head):          # קיצור: שעה בלבד = יומי
        parts = ["daily"] + parts
        head = "daily"

    if head == "every" and len(parts) > 1:
        m = _RX_EVERY.match(parts[1])
        if not m:
            return None
        n, unit = int(m.group(1)), m.group(2).lower()
        secs = n * {"m": 60, "h": 3600, "d": 86400}[unit]
        if secs < MIN_INTERVAL:
            return None
        return Spec("every", seconds=secs)

    if head in ("daily", "once") and len(parts) > 1:
        m = _RX_TIME.match(parts[1])
        if not m:
            return None
        h, mi = int(m.group(1)), int(m.group(2))
        if not (0 <= h < 24 and 0 <= mi < 60):
            return None
        return Spec(head, h, mi)

    if head == "weekly" and len(parts) > 2:
        if parts[1][:3] not in DAYS:
            return None
        m = _RX_TIME.match(parts[2])
        if not m:
            return None
        return Spec("weekly", int(m.group(1)), int(m.group(2)),
                    weekday=DAYS.index(parts[1][:3]))

    if head == "monthly" and len(parts) > 2:
        if not parts[1].isdigit():
            return None
        d = int(parts[1])
        m = _RX_TIME.match(parts[2])
        if not m or not 1 <= d <= 28:
            # מעל 28 אין בכל חודש. "ה-31 בפברואר" הוא באג שקט.
            return None
        return Spec("monthly", int(m.group(1)), int(m.group(2)), day=d)

    return None


def format_spec(sp: Spec) -> str:
    if sp.kind == "every":
        n = sp.seconds
        unit = "d" if n % 86400 == 0 else ("h" if n % 3600 == 0 else "m")
        div = {"d": 86400, "h": 3600, "m": 60}[unit]
        return f"every {n // div}{unit}"
    t = f"{sp.hour:02d}:{sp.minute:02d}"
    if sp.kind == "weekly":
        return f"weekly {DAYS[sp.weekday]} {t}"
    if sp.kind == "monthly":
        return f"monthly {sp.day} {t}"
    return f"{sp.kind} {t}"


def next_run(sp: Spec, *, after: Optional[float] = None,
             tz_offset: int = 0) -> float:
    """מתי הפעם הבאה, כחותם זמן UTC.

    ‎tz_offset‎ בדקות נקרא בכל חישוב מחדש ולא מוקפא ביצירה, ולכן
    מעבר שעון קיץ אינו מזיז את השעה שהמנהל קבע."""
    t = after if after is not None else time.time()
    if sp.kind == "every":
        return t + sp.seconds
    off = tz_offset * 60
    local = t + off
    day0 = local - (local % 86400)
    target = day0 + sp.hour * 3600 + sp.minute * 60

    if sp.kind in ("once", "daily"):
        while target <= local:
            target += 86400
    elif sp.kind == "weekly":
        # 0 = שני, לפי ‎time.gmtime().tm_wday‎
        while target <= local or time.gmtime(target).tm_wday != sp.weekday:
            target += 86400
    elif sp.kind == "monthly":
        while target <= local or time.gmtime(target).tm_mday != sp.day:
            target += 86400
    return target - off


class Scheduler:
    def __init__(self, db):
        self.db = db

    def tz(self, chat_id: int) -> int:
        try:
            return int(self.db.get(chat_id, "tz_offset", "0") or 0)
        except (TypeError, ValueError):
            return 0

    def add(self, chat_id: int, raw_spec: str, content: str, *,
            name: str = "", buttons: str = "",
            by: Optional[int] = None,
            now: Optional[float] = None) -> Optional[int]:
        sp = parse_spec(raw_spec)
        if sp is None or not content.strip():
            return None
        if len(self.all(chat_id)) >= MAX_PER_CHAT:
            return None
        t = now if now is not None else time.time()
        nxt = next_run(sp, after=t, tz_offset=self.tz(chat_id))
        return self.db.run(
            """INSERT INTO schedules
               (chat_id,name,kind,spec,content,buttons,next_run,created_by,
                created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (chat_id, name[:40], sp.kind, format_spec(sp), content, buttons,
             nxt, by, t))

    def all(self, chat_id: int) -> list[dict]:
        return [dict(r) for r in self.db.q(
            """SELECT id,name,kind,spec,content,next_run,runs,enabled
               FROM schedules WHERE chat_id=? ORDER BY next_run""",
            (chat_id,))]

    def remove(self, chat_id: int, sched_id: int) -> int:
        return self.db.change("DELETE FROM schedules WHERE chat_id=? AND id=?",
                              (chat_id, sched_id))

    def due(self, now: Optional[float] = None, limit: int = 20) -> list[dict]:
        t = now if now is not None else time.time()
        return [dict(r) for r in self.db.q(
            """SELECT * FROM schedules WHERE enabled=1 AND next_run<=?
               ORDER BY next_run LIMIT ?""", (t, limit))]

    def mark_ran(self, row: dict, now: Optional[float] = None) -> None:
        """מקדם לפעם הבאה. ‎once‎ מכבה את עצמו.

        הקידום הוא עד שהוא בעתיד, ולכן שירות שהיה כבוי יומיים שולח
        הודעה אחת ולא שישים."""
        t = now if now is not None else time.time()
        if row["kind"] == "once":
            self.db.run("""UPDATE schedules SET enabled=0, last_run=?,
                           runs=runs+1 WHERE id=?""", (t, row["id"]))
            return
        sp = parse_spec(row["spec"])
        if sp is None:
            self.db.run("UPDATE schedules SET enabled=0 WHERE id=?",
                        (row["id"],))
            return
        nxt = next_run(sp, after=t, tz_offset=self.tz(row["chat_id"]))
        guard = 0
        while nxt <= t and guard < 1000:
            nxt = next_run(sp, after=nxt, tz_offset=self.tz(row["chat_id"]))
            guard += 1
        self.db.run("""UPDATE schedules SET next_run=?, last_run=?, runs=runs+1
                       WHERE id=?""", (nxt, t, row["id"]))
