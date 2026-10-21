#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zmanim — נעילת הקבוצה בשבת ובחגים.

## מה הבעיה שזה פותר

קבוצה שומרת שבת נסגרת בכל שבוע באותה שעה — שעה שזזה בכל שבוע, לפי
העיר. מנהל שעושה את זה ידנית שוכח, מאחר, או נוסע. בוטים שעושים את
זה היום (שבת־בוט, שומר שבת וכו') עושים בדיוק שלושה דברים:

    1. מושכים זמני כניסת שבת ויציאתה לעיר שנבחרה
    2. נועלים את הקבוצה לפני הכניסה ופותחים אחרי היציאה
    3. שולחים הודעה מסודרת עם לוח הזמנים

כאן כל השלושה, וההודעות **ניתנות לעריכה** — כי מה שמתאים לקבוצת
ישיבה לא מתאים לקבוצת שכונה.

## מאיפה הזמנים

‎hebcal.com‎ — ה-API הציבורי והחינמי שכל הבוטים האלה מושכים ממנו.
בקשה אחת לעיר מחזירה את הכניסה, היציאה, שם הפרשה והחגים הקרובים.
אין מפתח, אין הרשמה, ויש מטמון כאן כדי שלא נבקש פעמיים לאותה קבוצה
באותו יום.

## למה המודול הזה לא מכיר טלגרם ולא מכיר רשת

החישוב כולו טהור: ‎parse_feed‎ מקבל מילון, ‎windows‎ מחזיר חלונות,
‎render‎ מחזיר טקסט. ההורדה היא פונקציה אחת שמוזרקת מבחוץ
(‎transport‎), בדיוק כמו ב-‎aiclient‎, ולכן אפשר לבדוק שבת שלמה בלי
רשת ובלי להמתין ליום שישי.

## מה נשמר כהגדרה

    shabbat            1/0 — האם התכונה פעילה
    shabbat_city       מפתח עיר מתוך ‎CITIES‎
    shabbat_before     דקות לפני הכניסה שבהן ננעל (ברירת מחדל 10)
    shabbat_after      דקות אחרי היציאה שבהן נפתח (ברירת מחדל 0)
    shabbat_notice     דקות לפני הנעילה שבהן נשלחת הודעת לוח הזמנים
    shabbat_msg_lock   תבנית הודעת הנעילה (ריק = ברירת המחדל המתורגמת)
    shabbat_msg_open   תבנית הודעת הפתיחה
    shabbat_msg_notice תבנית הודעת ההקדמה

## למה זה מוצע רק למי שבחר עברית

התכונה הזאת מיועדת לשומרי שבת. הצעה שלה לקבוצה בברזיל היא רעש
בתפריט. מי שבכל זאת רוצה — ‎/shabbat on‎ עובדת בכל שפה.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

API = "https://www.hebcal.com/shabbat"

# ── ערים ───────────────────────────────────────────────────────────────────
# ‎מפתח: (שם עברי, שם אנגלי, geonameid)‎. ה-geonameid הוא מה ש-hebcal
# מבין, והוא גם מה שקובע את אזור הזמן — ולכן אין כאן היסט שעה קפוא.
CITIES: dict[str, tuple[str, str, int]] = {
    "jerusalem":   ("ירושלים", "Jerusalem", 281184),
    "telaviv":     ("תל אביב", "Tel Aviv", 293397),
    "haifa":       ("חיפה", "Haifa", 294801),
    "beersheva":   ("באר שבע", "Beer Sheva", 295530),
    "ashdod":      ("אשדוד", "Ashdod", 295629),
    "netanya":     ("נתניה", "Netanya", 294071),
    "petahtikva":  ("פתח תקווה", "Petah Tikva", 293918),
    "rishon":      ("ראשון לציון", "Rishon LeZion", 293807),
    "bneibrak":    ("בני ברק", "Bnei Brak", 295514),
    "tiberias":    ("טבריה", "Tiberias", 293322),
    "tzfat":       ("צפת", "Safed", 293703),
    "eilat":       ("אילת", "Eilat", 295277),
    "newyork":     ("ניו יורק", "New York", 5128581),
    "losangeles":  ("לוס אנג'לס", "Los Angeles", 5368361),
    "london":      ("לונדון", "London", 2643743),
    "paris":       ("פריז", "Paris", 2988507),
    "toronto":     ("טורונטו", "Toronto", 6167865),
    "moscow":      ("מוסקבה", "Moscow", 524901),
    "buenosaires": ("בואנוס איירס", "Buenos Aires", 3435910),
    "melbourne":   ("מלבורן", "Melbourne", 2158177),
}

DEFAULT_CITY = "jerusalem"
DEFAULT_BEFORE = 10          # דקות לפני הכניסה
DEFAULT_AFTER = 0            # דקות אחרי היציאה
DEFAULT_NOTICE = 60          # דקות לפני הנעילה — הודעת ההקדמה

CACHE_TTL = 6 * 3600         # הזמנים לא זזים. שש שעות הן שמרנות, לא דיוק


def city_name(key: str, lang: str = "en") -> str:
    row = CITIES.get(key) or CITIES[DEFAULT_CITY]
    return row[0] if lang == "he" else row[1]


def cities(lang: str = "en") -> list[tuple[str, str]]:
    """‎[(מפתח, שם)]‎ לתצוגה בבורר. ישראל ראשונה — שם רוב המשתמשים."""
    return [(k, city_name(k, lang)) for k in CITIES]


# ── מה שחוזר מ-hebcal ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class Event:
    """אירוע אחד מהפיד. ‎kind‎ הוא ‎candles‎ · ‎havdalah‎ · ‎parashat‎ · ‎holiday‎."""
    kind: str
    title: str
    ts: float = 0.0          # UTC. אפס לאירוע ללא שעה (פרשה, יום חג)

    @property
    def dated(self) -> bool:
        return self.ts > 0


@dataclass(frozen=True)
class Window:
    """חלון נעילה אחד: מתי נסגר, מתי נפתח, ועל שם מה.

    ‎lock_at‎ ו-‎open_at‎ כבר כוללים את ההיסטים של הקבוצה; ‎candles‎
    ו-‎havdalah‎ הם הזמנים עצמם, כי זה מה שמופיע בהודעה."""
    candles: float
    havdalah: float
    lock_at: float
    open_at: float
    title: str = ""
    parasha: str = ""

    def active(self, now: float) -> bool:
        return self.lock_at <= now < self.open_at

    def upcoming(self, now: float) -> bool:
        return now < self.lock_at


def _ts(raw: Any) -> float:
    """‎'2026-10-23T17:42:00+03:00'‎ → חותם זמן. כישלון מחזיר 0.

    הפיד מחזיר שעה **עם היסט**, ולכן אין כאן ניחוש אזור זמן: עיר
    שעברה לשעון קיץ מחזירה היסט אחר, והחישוב נשאר נכון מעצמו."""
    if not isinstance(raw, str) or not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return 0.0


def parse_feed(payload: Any) -> list[Event]:
    """מילון של hebcal → אירועים. קלט פגום מחזיר רשימה ריקה.

    **לא זורק.** פיד שהשתנה או רשת שהחזירה HTML אינם סיבה להשאיר
    קבוצה נעולה או לחנוק את לולאת הרקע."""
    if isinstance(payload, (bytes, str)):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return []
    if not isinstance(payload, dict):
        return []
    out: list[Event] = []
    for it in payload.get("items") or []:
        if not isinstance(it, dict):
            continue
        cat = str(it.get("category") or "")
        title = str(it.get("title") or "")
        if cat in ("candles", "havdalah"):
            out.append(Event(cat, title, _ts(it.get("date"))))
        elif cat == "parashat":
            out.append(Event("parashat", str(it.get("hebrew") or title)))
        elif cat == "holiday":
            out.append(Event("holiday", str(it.get("hebrew") or title)))
    return out


def windows(events: list[Event], *, before: int = DEFAULT_BEFORE,
            after: int = DEFAULT_AFTER) -> list[Window]:
    """מזווג כניסה ליציאה. הזיווג הוא לפי סדר הזמן ולא לפי שם.

    חג שחל בסמוך לשבת מחזיר כניסה ויציאה **אחת** שמקיפה את שניהם רק
    אם הפיד כך החזיר; שני אירועים נפרדים נשארים נפרדים. אנחנו לא
    ממציאים הלכה — אנחנו קוראים זמנים.

    כניסה בלי יציאה (סוף הפיד) נזרקת: עדיף לא לנעול מאשר לנעול
    בלי לדעת מתי נפתח."""
    dated = sorted((e for e in events if e.dated and e.kind in
                    ("candles", "havdalah")), key=lambda e: e.ts)
    parasha = next((e.title for e in events if e.kind == "parashat"), "")
    holiday = next((e.title for e in events if e.kind == "holiday"), "")
    out: list[Window] = []
    i = 0
    while i < len(dated) - 1:
        if dated[i].kind != "candles":
            i += 1
            continue
        j = i + 1
        while j < len(dated) and dated[j].kind != "havdalah":
            j += 1
        if j >= len(dated):
            break
        c, h = dated[i].ts, dated[j].ts
        out.append(Window(c, h, c - before * 60, h + after * 60,
                          title=holiday or parasha, parasha=parasha))
        i = j + 1
    return out


def current(wins: list[Window], now: float) -> Optional[Window]:
    for w in wins:
        if w.active(now):
            return w
    return None


def next_window(wins: list[Window], now: float) -> Optional[Window]:
    for w in sorted(wins, key=lambda w: w.lock_at):
        if w.upcoming(now):
            return w
    return None


# ── הודעות ────────────────────────────────────────────────────────────────
# מה שמנהל יכול לכתוב בתבנית שלו. השמות באנגלית כי הם נכתבים בתוך
# טקסט בכל שפה, ושם משתנה שמתחלף בין שפות הוא תבנית שנשברת בתרגום.
VARS = ("city", "parasha", "candles", "havdalah", "lock", "open", "date")


def _clock(ts: float, tz_offset: int) -> str:
    if ts <= 0:
        return "--:--"
    lt = time.gmtime(ts + tz_offset * 60)
    return f"{lt.tm_hour:02d}:{lt.tm_min:02d}"


def _date(ts: float, tz_offset: int) -> str:
    if ts <= 0:
        return ""
    lt = time.gmtime(ts + tz_offset * 60)
    return f"{lt.tm_mday:02d}/{lt.tm_mon:02d}"


clock = _clock          # שמות ציבוריים: מי שמציג זמן לא אמור לגעת בפרטי
date = _date


def fill(template: str, w: Window, *, city: str = "", tz_offset: int = 0) -> str:
    """מציב את המשתנים בתבנית. משתנה לא מוכר נשאר כמו שהוא.

    ‎str.format‎ לא מתאים כאן: תבנית שנכתבה ביד מכילה ‎{‎ אקראי, וכל
    הודעת שבת של הקבוצה הייתה נופלת על ‎KeyError‎ ביום שישי אחר
    הצהריים — הרגע הכי גרוע לגלות באג."""
    vals = {
        "city": city,
        "parasha": w.parasha or w.title,
        "candles": _clock(w.candles, tz_offset),
        "havdalah": _clock(w.havdalah, tz_offset),
        "lock": _clock(w.lock_at, tz_offset),
        "open": _clock(w.open_at, tz_offset),
        "date": _date(w.candles, tz_offset),
    }
    out = template or ""
    for k, v in vals.items():
        out = out.replace("{" + k + "}", str(v))
    return out


# ── הורדה ─────────────────────────────────────────────────────────────────
def url_for(city: str, *, havdalah: int = 0, candle: int = 0) -> str:
    """‎b‎ ו-‎m‎ הם דקות הכניסה והיציאה המקובלות; אפס = ברירת המחדל של
    hebcal לאותה עיר, וזה מה שרוב הקבוצות מצפות לו."""
    gid = (CITIES.get(city) or CITIES[DEFAULT_CITY])[2]
    q = f"?cfg=json&geonameid={gid}&lg=he&M=on"
    if candle:
        q += f"&b={candle}"
    if havdalah:
        q += f"&m={havdalah}&M=off"
    return API + q


async def _urllib_transport(url: str, timeout: float) -> str:
    """ברירת המחדל. ‎urllib‎ ולא ‎aiohttp‎ כי זו בקשה אחת לשש שעות,
    והיא רצה בתהליכון כדי לא לחסום את הלולאה."""
    import asyncio
    import urllib.request

    def go() -> str:
        req = urllib.request.Request(url, headers={"User-Agent": "GroupOS"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")

    return await asyncio.to_thread(go)


class Zmanim:
    """מטמון סביב הפיד. ‎transport‎ מוזרק כדי שהבדיקות לא ייגעו ברשת."""

    def __init__(self, transport: Optional[Callable] = None,
                 ttl: int = CACHE_TTL):
        self.transport = transport or _urllib_transport
        self.ttl = ttl
        self._cache: dict[str, tuple[float, list[Event]]] = {}
        self.failures = 0

    async def events(self, city: str, *, now: Optional[float] = None,
                     timeout: float = 8.0) -> list[Event]:
        t = now if now is not None else time.time()
        hit = self._cache.get(city)
        if hit and t - hit[0] < self.ttl:
            return hit[1]
        try:
            raw = await self.transport(url_for(city), timeout)
        except Exception:                           # רשת. כל כישלון שווה
            self.failures += 1
            # מחזירים את המטמון הישן אם יש — זמנים מאתמול עדיפים על כלום
            return hit[1] if hit else []
        evs = parse_feed(raw)
        if not evs:
            self.failures += 1
            return hit[1] if hit else []
        self._cache[city] = (t, evs)
        return evs

    async def windows(self, city: str, *, before: int = DEFAULT_BEFORE,
                      after: int = DEFAULT_AFTER,
                      now: Optional[float] = None) -> list[Window]:
        return windows(await self.events(city, now=now),
                       before=before, after=after)
