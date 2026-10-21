#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""grouphours — שעות פתיחה וסגירה קבועות של הקבוצה.

## מה זה

"אני רוצה שהקבוצה תהיה סגורה בלילה." לוח שבועי, יום־יום, עם שעת
פתיחה ושעת סגירה לכל יום בנפרד — כי יום שישי אינו יום שלישי.

## הייצוג

שורה אחת לכל יום, מופרדת בפסיקים, בדיוק כמו ‎policy_rules‎:

    sun=08:00-23:00, mon=08:00-23:00, fri=off, sat=closed

    ‎off‎      אין כלל ליום הזה — הקבוצה פתוחה כרגיל
    ‎closed‎   סגור כל היום
    ‎HH:MM-HH:MM‎  פתוח בטווח, סגור מחוצה לו

שעת סגירה **קטנה** משעת הפתיחה פירושה חציית חצות: ‎22:00-02:00‎ הוא
פתוח מעשר בלילה עד שתיים. זה הניסוח הטבעי, ובלי התמיכה הזאת כל
קבוצת לילה הייתה צריכה לפצל את היום לשתי שורות.

## למה טהור

שום שורה כאן אינה יודעת מה זה טלגרם או מסד. הקלט הוא טקסט ושעה,
הפלט הוא ‎True/False‎ ומתי המעבר הבא — ולכן אפשר לבדוק שבוע שלם
בלולאה אחת, ולא להמתין ליום שלישי בשתיים בלילה.

## שבת

נעילת שבת אינה כאן אלא ב-‎zmanim‎: היא נגזרת מזמנים שזזים בכל שבוע,
והלוח הזה הוא קבוע. כששניהם פעילים — **הסוגר מנצח**. קבוצה שננעלה
לשבת לא תיפתח ביום שבת בשמונה בבוקר רק מפני שכך כתוב בלוח.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")   # 0=שני, כמו tm_wday
DAY_KEY = {d: f"day.{d}" for d in DAYS}

_RX = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")

CLOSED = "closed"
OFF = "off"


@dataclass(frozen=True)
class Day:
    """‎open_min‎/‎close_min‎ בדקות מחצות. ‎mode‎ הוא ‎range‎ · ‎closed‎ · ‎off‎."""
    mode: str = OFF
    open_min: int = 0
    close_min: int = 0

    @property
    def wraps(self) -> bool:
        return self.mode == "range" and self.close_min <= self.open_min


def _mins(h: str, m: str) -> Optional[int]:
    hh, mm = int(h), int(m)
    if not (0 <= hh < 24 and 0 <= mm < 60):
        return None
    return hh * 60 + mm


def parse(raw: str) -> dict[str, Day]:
    """טקסט → לוח. יום עם ניסוח שגוי מדלג ולא מפיל את השאר.

    שורה אחת שגויה לא אמורה להשאיר קבוצה סגורה לנצח."""
    out: dict[str, Day] = {}
    for chunk in (raw or "").replace("\n", ",").split(","):
        chunk = chunk.strip().lower()
        if not chunk or "=" not in chunk:
            continue
        day, _, val = chunk.partition("=")
        day = day.strip()[:3]
        val = val.strip()
        if day not in DAYS:
            continue
        if val in (CLOSED, OFF):
            out[day] = Day(val)
            continue
        m = _RX.match(val)
        if not m:
            continue
        a = _mins(m.group(1), m.group(2))
        b = _mins(m.group(3), m.group(4))
        if a is None or b is None:
            continue
        out[day] = Day("range", a, b)
    return out


def format_sched(sched: dict[str, Day]) -> str:
    bits = []
    for d in DAYS:
        day = sched.get(d)
        if day is None or day.mode == OFF:
            continue
        if day.mode == CLOSED:
            bits.append(f"{d}={CLOSED}")
        else:
            bits.append(f"{d}={day.open_min // 60:02d}:{day.open_min % 60:02d}"
                        f"-{day.close_min // 60:02d}:{day.close_min % 60:02d}")
    return ", ".join(bits)


def set_day(raw: str, day: str, value: str) -> str:
    """מחזיר לוח חדש עם יום אחד שהוחלף. ‎off‎ מסיר את היום מהלוח."""
    sched = parse(raw)
    one = parse(f"{day}={value}")
    if day in one:
        sched[day] = one[day]
    return format_sched(sched)


def _local(ts: float, tz_offset: int) -> tuple[int, int]:
    """‎(יום בשבוע לפי DAYS, דקות מחצות)‎ בשעון הקבוצה."""
    lt = time.gmtime(ts + tz_offset * 60)
    return lt.tm_wday, lt.tm_hour * 60 + lt.tm_min


def _open_at(sched: dict[str, Day], wday: int, mins: int) -> bool:
    today = sched.get(DAYS[wday], Day(OFF))
    # זליגה מאתמול: ‎22:00-02:00‎ של אתמול עדיין פתוח בשתיים בלילה
    y = sched.get(DAYS[(wday - 1) % 7], Day(OFF))
    if y.wraps and mins < y.close_min:
        return True
    if today.mode == OFF:
        return True
    if today.mode == CLOSED:
        return False
    if today.wraps:
        return mins >= today.open_min
    return today.open_min <= mins < today.close_min


def is_open(raw: str, *, now: Optional[float] = None,
            tz_offset: int = 0) -> bool:
    """האם הקבוצה אמורה להיות פתוחה עכשיו. לוח ריק = תמיד פתוחה."""
    sched = parse(raw)
    if not sched:
        return True
    wday, mins = _local(now if now is not None else time.time(), tz_offset)
    return _open_at(sched, wday, mins)


def next_change(raw: str, *, now: Optional[float] = None,
                tz_offset: int = 0) -> Optional[tuple[float, bool]]:
    """‎(מתי, האם ייפתח)‎ — המעבר הבא, או ‎None‎ אם אין מעבר בשבוע.

    נבדק בצעדי דקה על פני שבוע. שבוע הוא 10,080 בדיקות של השוואת
    מספרים — זול לאין ערוך מלנסות לנסח את כל מקרי הקצה של חציית
    חצות בנוסחה אחת, שבה כל באג מתגלה פעם בשבוע בשתיים בלילה."""
    sched = parse(raw)
    if not sched:
        return None
    t = now if now is not None else time.time()
    wday, mins = _local(t, tz_offset)
    state = _open_at(sched, wday, mins)
    for step in range(1, 7 * 24 * 60 + 1):
        m = mins + step
        w = (wday + m // (24 * 60)) % 7
        cur = _open_at(sched, w, m % (24 * 60))
        if cur != state:
            return (t + step * 60 - (t % 60), cur)
    return None


def describe(raw: str, labels: Optional[dict[str, str]] = None,
             closed_word: str = "closed") -> str:
    """לוח כטקסט לקריאה, שורה ליום. ‎labels‎ מתרגם את שמות הימים."""
    sched = parse(raw)
    lines = []
    for d in DAYS:
        day = sched.get(d)
        if day is None or day.mode == OFF:
            continue
        name = (labels or {}).get(d, d)
        if day.mode == CLOSED:
            lines.append(f"{name}: {closed_word}")
        else:
            lines.append(
                f"{name}: {day.open_min // 60:02d}:{day.open_min % 60:02d}"
                f"–{day.close_min // 60:02d}:{day.close_min % 60:02d}")
    return "\n".join(lines)
