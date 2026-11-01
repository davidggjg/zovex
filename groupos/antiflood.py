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
        # מי דיבר בקבוצה לאחרונה — הבסיס למדידה יחסית.
        self._room: dict[int, deque] = {}

    # ── הודעות ────────────────────────────────────────────────────────────
    # ── כמה זה "יותר מדי" **בקבוצה הזאת** ────────────────────────────
    #
    # סף קבוע לא יכול לשרת גם מאגר שבו אדם אחד מעלה עונה שלמה, גם
    # קבוצת דיבורים שבה עשרה אנשים כותבים בבת אחת, וגם קבוצה שקטה
    # שבה עשר הודעות ברצף הן באמת חריגה. אותו מספר הוא במקום אחד
    # הגיוני ובמקום אחר עונש על שימוש רגיל.
    #
    # לכן הסף נמדד **יחסית לחדר**: כמה אנשים *אחרים* דיברו כאן
    # באותו חלון. בשיחה ערה הסף עולה, כי עשר הודעות בתוך שיחה של
    # שישה אנשים הן שיחה; באותה קבוצה כשאיש אינו מדבר, אותן עשר
    # הודעות הן מונולוג.
    #
    # נספרים **אחרים בלבד**, בכוונה: אחרת ספאמר היה מרים לעצמו את
    # הסף בעצם ההצפה.
    BUSY_CAP = 6            # מעבר לשישה דוברים אין תוספת
    BUSY_STEP = 0.5         # כל דובר נוסף מרחיב את הסף בחצי

    def _limit(self, chat_id: int, user_id: int, t: float,
               window: float, rate: int, media: bool) -> int:
        log = self._room.setdefault(chat_id, deque())
        log.append((t, user_id))
        while log and t - log[0][0] > window:
            log.popleft()
        if len(log) > 400:          # תקרה, שלא יגדל בלי גבול
            while len(log) > 400:
                log.popleft()
        others = len({u for _ts, u in log if u != user_id})
        factor = 1.0 + min(others, self.BUSY_CAP) * self.BUSY_STEP
        if media:
            factor *= self.MEDIA_FACTOR
        return max(rate, int(rate * factor))

    # העלאת תוכן אינה הצפה.
    #
    # בקבוצת סדרות אדם מעלה עונה שלמה ברצף — "פרק 19", "פרק 37" —
    # וחוצה שמונה הודעות בעשר שניות בלי מאמץ. הוא הושתק על כך
    # שעשה בדיוק את מה שהקבוצה קיימת בשבילו.
    #
    # הצפה אמיתית במדיה היא **אותו קובץ שוב ושוב**, וזה נתפס במקום
    # אחר (טביעת אצבע של המדיה וזיהוי חזרתיות). מה שנשאר כאן הוא
    # ספירת נפח גולמית, ולה מגיע מרווח אחר כשמדובר בקבצים.
    # שש ולא שלוש: מאגר מעלה עונה שלמה ברצף, ארבעים פרקים אינם
    # מספר חריג שם. הצפת מדיה אמיתית נתפסת ממילא על **התוכן** —
    # בדיקת התמונה, וטביעת האצבע שתופסת את אותו קובץ שחוזר. ספירת
    # הנפח כאן היא רשת ביטחון אחרונה, ולא השורה הראשונה.
    MEDIA_FACTOR = 6

    def note(self, chat_id: int, user_id: int, text: str = "",
             mentions: int = 0, *, now: Optional[float] = None,
             rate: int = RATE_MSGS, window: float = RATE_WINDOW,
             repeat: int = REPEAT_COUNT,
             mention_max: int = MENTION_MAX,
             media: bool = False) -> Optional[Flood]:
        """רושם הודעה ומחזיר הצפה אם נמצאה.

        ‎media‎ מסמן הודעה שנושאת קובץ. היא נספרת כרגיל, אבל הסף
        שלה גבוה פי שלושה — העלאה ברצף אינה אותו דבר כמו מאה
        שורות טקסט."""
        t = now if now is not None else time.monotonic()
        key = (chat_id, user_id)

        if mention_max and mentions > mention_max:
            return Flood("mention", mentions, mention_max)

        q = self._msgs.setdefault(key, deque())
        q.append(t)
        while q and t - q[0] > window:
            q.popleft()
        self._evict()
        limit = self._limit(chat_id, user_id, t, window, rate, media)
        if rate and len(q) > limit:
            q.clear()               # אחרי זיהוי מתחילים מדידה מחדש
            return Flood("rate", limit + 1, limit)

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
