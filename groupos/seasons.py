#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""seasons — לזהות עונה ופרק בתוך שורת טקסט חופשית.

## הבקשה שמאחורי המודול

"יש סדרות שיש להן כמה עונות. שזה יקלוט את מספר העונה, יסדר לפי זה,
ואז יתן לבן אדם כפתורים — תבחר עונה 1, 2, 3 — ואז ישלח לו את
הפרקים של העונה."

זה נכון יותר מלשלוח מאתיים הודעות: אדם שביקש סדרה רוצה עונה אחת,
והשאר הוא רעש שמציף לו את הצ'אט.

## למה ניחוש מהטקסט ולא שדה

כי אף אחד לא ימלא שדה. ההודעות כבר קיימות, והן כבר כתובות בצורה
קבועה למדי — "עונה 2 פרק 7", "S02E07", "ע2 פ7". הניחוש מצליח ברוב
המוחלט, וכשהוא נכשל הפריט נופל ל"ללא עונה" ונשלח כרגיל. כישלון
כאן הוא חזרה להתנהגות הישנה, לא שבירה.

## סדר

העונות מוצגות לפי מספר, והפרקים בתוך עונה לפי מספר הפרק כשהוא
ידוע — ואחרת לפי סדר ההוספה. מנהל שהעלה פרק מאוחר אינו רוצה שהוא
יישב בסוף רק מפני שהועלה אחרון.
"""
from __future__ import annotations

import re
from typing import Any, Optional

NO_SEASON = 0           # "לא זוהתה עונה" — נשלח תמיד, בלי כפתור

# ‎S02E07‎ · ‎s2e7‎ — הצורה הלועזית, והיא גם החד-משמעית ביותר
_RX_SXXEYY = re.compile(r"\bs\s*(\d{1,2})\s*e\s*(\d{1,3})\b", re.I)
# "עונה 2" · "עונה2" · "ע2" — והעברית היא הנפוצה כאן
_RX_HE_SEASON = re.compile(r"(?:עונה|ע')\s*(\d{1,2})\b")
_RX_HE_SEASON_SHORT = re.compile(r"\bע\s*(\d{1,2})\b")
_RX_HE_EP = re.compile(r"(?:פרק|פ'|\bפ)\s*(\d{1,3})\b")
_RX_EN_SEASON = re.compile(r"\bseason\s*(\d{1,2})\b", re.I)
_RX_EN_EP = re.compile(r"\bepisode\s*(\d{1,3})\b", re.I)


def season_of(text: str) -> int:
    """מספר העונה, או ‎0‎ אם לא זוהתה.

    ‎SxxEyy‎ קודם: הוא חד-משמעי, ובמחרוזת כמו ‎"S02E07 1080p"‎ כל
    ניסיון אחר היה לוקח את ‎1080‎."""
    t = text or ""
    m = _RX_SXXEYY.search(t)
    if m:
        return int(m.group(1))
    for rx in (_RX_HE_SEASON, _RX_EN_SEASON, _RX_HE_SEASON_SHORT):
        m = rx.search(t)
        if m:
            return int(m.group(1))
    return NO_SEASON


def episode_of(text: str) -> int:
    """מספר הפרק, או ‎0‎. משמש למיון בתוך עונה בלבד."""
    t = text or ""
    m = _RX_SXXEYY.search(t)
    if m:
        return int(m.group(2))
    for rx in (_RX_HE_EP, _RX_EN_EP):
        m = rx.search(t)
        if m:
            return int(m.group(1))
    return 0


def _text_of(item: Any) -> str:
    if isinstance(item, dict):
        return item.get("content") or ""
    return getattr(item, "content", "") or str(item)


def split(items: list) -> dict[int, list]:
    """‎{מספר עונה: פריטים}‎, כל עונה ממוינת לפי מספר הפרק.

    הסדר בתוך עונה נשמר יציב כשאין מספרי פרק: ‎sorted‎ יציב, ולכן
    פריטים בלי מספר נשארים בסדר שבו המנהל שמר אותם."""
    out: dict[int, list] = {}
    for i, it in enumerate(items):
        out.setdefault(season_of(_text_of(it)), []).append((i, it))
    return {s: [it for _i, it in sorted(
                v, key=lambda p: (episode_of(_text_of(p[1])) or 10 ** 6,
                                  p[0]))]
            for s, v in out.items()}


def seasons_of(items: list) -> list[int]:
    """מספרי העונות שיש בהן פריטים, ממוינים. ‎0‎ אינו עונה."""
    return sorted(s for s in split(items) if s != NO_SEASON)


def multi_season(items: list) -> bool:
    """האם בכלל יש כאן יותר מעונה אחת — התנאי להצגת כפתורים.

    עונה אחת אינה בחירה. להציג כפתור יחיד "עונה 1" זה להוסיף לחיצה
    שלא עושה כלום."""
    return len(seasons_of(items)) > 1


def pick(items: list, season: int) -> list:
    """פריטי עונה אחת, ואיתם מה שלא שויך לאף עונה.

    הפריטים חסרי העונה נשלחים עם כל בחירה בכוונה: שם הם בדרך כלל
    הכרזה, כרזה או קישור לסדרה כולה — לא פרק של עונה אחרת."""
    parts = split(items)
    return parts.get(NO_SEASON, []) + parts.get(season, [])
