#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""antiflood — הצפה, חזרתיות והצטרפות המונית.

## למה לא "X הודעות ב-Y שניות" ותו לא

זה תופס ילד שמתלהב ומפספס ספאמר. ספאמר שולח שש הודעות בדקה — מתחת
לכל סף — אבל כולן אותו טקסט, או כולן מכילות את אותו קישור. לכן כאן
שלושה אותות נפרדים:

    rate        קצב — יותר מדי הודעות בחלון
    repeat      חזרתיות — אותה הודעה שוב ושוב
    mention     הצפת תיוגים בהודעה אחת או בכמה

## למה הכול בזיכרון

חלון של 20 שניות אינו נתון היסטורי. כתיבתו למסד בכל הודעה הייתה
מוסיפה כתיבה לדיסק לכל הודעה בקבוצה — המחיר היקר ביותר במערכת הזאת —
עבור מידע שיימחק בעוד 20 שניות. מה שכן צריך לשרוד אתחול הוא **הענישה**,
והיא נשמרת במסד דרך ‎moderation‎.

## הצטרפות המונית

‎join‎ נספר בנפרד מהודעות, כי פשיטה מתחילה בהצטרפות ולא בכתיבה.
הסף שם נמוך בכוונה: 10 הצטרפויות ב-30 שניות הן חריגות בקבוצה רגילה
ונורמליות בפשיטה.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

# ברירות מחדל. כל אחת ניתנת לדריסה פר-קבוצה דרך settings.
RATE_MSGS = 8           # הודעות
RATE_WINDOW = 10.0      # בשניות
REPEAT_COUNT = 4        # אותה הודעה, כמה פעמים
REPEAT_WINDOW = 60.0
MENTION_MAX = 8         # תיוגים בהודעה אחת
JOIN_COUNT = 10         # הצטרפויות
JOIN_WINDOW = 30.0

MAX_TRACKED = 5000      # תקרת משתמשים במעקב, שלא נדלוף זיכרון


@dataclass(frozen=True)
class Flood:
    kind: str           # rate | repeat | mention
    count: int
    limit: int


class AntiFlood:
    def __init__(self):
        self._msgs: dict[tuple[int, int], deque] = {}
        self._texts: dict[tuple[int, int], deque] = {}
        self._joins: dict[int, deque] = {}

    # ── הודעות ────────────────────────────────────────────────────────────
    def note(self, chat_id: int, user_id: int, text: str = "",
             mentions: int = 0, *, now: Optional[float] = None,
             rate: int = RATE_MSGS, window: float = RATE_WINDOW,
             repeat: int = REPEAT_COUNT,
             mention_max: int = MENTION_MAX) -> Optional[Flood]:
        """רושם הודעה ומחזיר הצפה אם נמצאה."""
        t = now if now is not None else time.monotonic()
        key = (chat_id, user_id)

        if mention_max and mentions > mention_max:
            return Flood("mention", mentions, mention_max)

        q = self._msgs.setdefault(key, deque())
        q.append(t)
        while q and t - q[0] > window:
            q.popleft()
        self._evict()
        if rate and len(q) > rate:
            q.clear()               # אחרי זיהוי מתחילים מדידה מחדש
            return Flood("rate", rate + 1, rate)

        if repeat and text:
            sig = " ".join(text.lower().split())[:200]
            r = self._texts.setdefault(key, deque())
            r.append((t, sig))
            while r and t - r[0][0] > REPEAT_WINDOW:
                r.popleft()
            same = sum(1 for _, s in r if s == sig)
            if same >= repeat:
                r.clear()
                return Flood("repeat", same, repeat)
        return None

    # ── הצטרפויות ─────────────────────────────────────────────────────────
    def join(self, chat_id: int, *, now: Optional[float] = None,
             count: int = JOIN_COUNT,
             window: float = JOIN_WINDOW) -> Optional[Flood]:
        t = now if now is not None else time.monotonic()
        q = self._joins.setdefault(chat_id, deque())
        q.append(t)
        while q and t - q[0] > window:
            q.popleft()
        if count and len(q) >= count:
            return Flood("raid", len(q), count)
        return None

    def forget(self, chat_id: int, user_id: int) -> None:
        self._msgs.pop((chat_id, user_id), None)
        self._texts.pop((chat_id, user_id), None)

    def _evict(self) -> None:
        """תקרת זיכרון. קבוצה עם 100 אלף חברים לא אמורה להפיל את התהליך."""
        if len(self._msgs) <= MAX_TRACKED:
            return
        for k in list(self._msgs)[:len(self._msgs) - MAX_TRACKED]:
            self._msgs.pop(k, None)
            self._texts.pop(k, None)

    def stats(self) -> dict:
        return {"users": len(self._msgs), "chats": len(self._joins)}
