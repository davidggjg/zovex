#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""templates — משתנים בהודעות, ותגובה אקראית מתוך כמה.

## למה זה מודול ולא פונקציה קטנה

Welcome, Goodbye, Rules, Notes, Filters, CAPTCHA והתראות — כולם צריכים
את אותם משתנים. כשכל אחד מהם ממלא אותם בעצמו, ‎{user}‎ עובד בברכה ולא
בפילטר, ואף אחד לא יודע למה.

## למה ‎str.format‎ לא מתאים

הודעה שמנהל כותב היא קלט של משתמש. ‎"{0.__class__}"‎ ב-‎format‎ נותן
גישה לאובייקטים, ו-‎{‎ בודד מפיל אותה בחריגה. כאן: החלפה מילולית של
שמות מוכרים בלבד. מה שלא מוכר נשאר כפי שנכתב — מנהל שכתב ‎{smile}‎
יראה ‎{smile}‎, ולא שגיאה ולא הודעה ריקה.

## בריחת HTML

הבוט שולח ב-HTML. שם משתמש שמכיל ‎<‎ היה שובר את ההודעה כולה, ובמקרה
הגרוע מזריק תגיות. ערכי המשתנים עוברים בריחה; מה שהמנהל כתב בעצמו לא —
הוא מותר לעצב.
"""
from __future__ import annotations

import html
import random
import re
import time
from typing import Any, Optional

# מה שמותר להופיע בהודעה. הרשימה הזאת היא גם התיעוד וגם האכיפה.
VARIABLES = (
    "user", "username", "mention", "user_id", "first", "last",
    "chat", "chat_id", "count", "rules",
    "warnings", "reason", "date", "time", "language", "risk",
)

_RX = re.compile(r"\{(" + "|".join(VARIABLES) + r")\}")

SPLIT = "|||"        # מפריד בין כמה נוסחים של אותה הודעה


def esc(v: Any) -> str:
    return html.escape(str(v if v is not None else ""), quote=False)


def mention(user_id: int, name: str) -> str:
    """קישור לפרופיל. עובד גם למי שאין לו username."""
    return f'<a href="tg://user?id={user_id}">{esc(name)}</a>'


def render(text: str, ctx: dict) -> str:
    """ממלא משתנים. מה שלא מוכר נשאר כפי שנכתב."""
    if not text:
        return ""

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in ctx:
            return m.group(0)
        val = ctx[key]
        # mention כבר מכיל HTML שאנחנו בנינו, ולכן אינו עובר בריחה שנייה
        return val if key == "mention" else esc(val)

    return _RX.sub(sub, text)


def context(*, user_id: int = 0, first: str = "", last: str = "",
            username: str = "", chat_title: str = "", chat_id: int = 0,
            count: int = 0, warnings: int = 0, reason: str = "",
            language: str = "", risk: str = "", rules: str = "",
            when: Optional[float] = None) -> dict:
    """ההקשר הסטנדרטי. כל מי שמרנדר הודעה בונה אותו מכאן."""
    t = time.localtime(when if when is not None else time.time())
    full = (first + (" " + last if last else "")).strip() or str(user_id)
    return {
        "user": full,
        "first": first,
        "last": last,
        "username": ("@" + username) if username else full,
        "mention": mention(user_id, full),
        "user_id": user_id,
        "chat": chat_title,
        "chat_id": chat_id,
        "count": count,
        "warnings": warnings,
        "reason": reason,
        "language": language,
        "risk": risk,
        "rules": rules,
        "date": time.strftime("%d/%m/%Y", t),
        "time": time.strftime("%H:%M", t),
    }


def pick(text: str) -> str:
    """בוחר נוסח אחד מתוך כמה שמופרדים ב-|||.

    ברכה זהה מילה במילה לכל נכנס קוראת כמו מכונה. שלושה נוסחים
    מספיקים כדי שזה ייראה אנושי, ולכן זה מנגנון של שורה אחת ולא מודול."""
    parts = [p.strip() for p in text.split(SPLIT) if p.strip()]
    return random.choice(parts) if parts else text


def render_pick(text: str, ctx: dict) -> str:
    return render(pick(text), ctx)


def used(text: str) -> set[str]:
    """אילו משתנים מופיעים בטקסט. משמש לתצוגה מקדימה ולבדיקות."""
    return set(_RX.findall(text or ""))
