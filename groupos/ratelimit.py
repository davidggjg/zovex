#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ratelimit — לא לחרוג ממה שטלגרם מרשה.

## המספרים, מהתיעוד הרשמי של טלגרם

    צ'אט יחיד    הודעה אחת בשנייה
    קבוצה        20 הודעות בדקה
    שידור כולל   ~30 הודעות בשנייה

נמדד אצלנו: עיבוד הודעה לוקח 0.087ms, כלומר 11,500 בשנייה. הבוט מהיר
פי 380 ממה שמותר לו לענות. **הצוואר הוא כאן, לא בקוד.**

## למה שומר ולא ניסיון-וטעייה

אפשר לשלוח עד שטלגרם מחזירה FloodWait ואז להמתין. זה עובד ורע: FloodWait
נספר לרעת הבוט, וחריגה חוזרת מובילה להגבלה ארוכה. עדיף לא לחרוג מלכתחילה.

## Token bucket ולא חלון קבוע

חלון קבוע מאפשר להגניב 20 הודעות בסוף דקה ו-20 בתחילת הבאה — 40 בשתי
שניות, וטלגרם תחסום. דלי אסימונים מתמלא ברציפות, ולכן אין את החור הזה.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

# מהתיעוד של טלגרם. שמרניים בכוונה — עדיף לאבד שבריר מהתקרה מאשר להיחסם.
PER_CHAT_PER_SEC = 1.0
PER_GROUP_PER_MIN = 20
GLOBAL_PER_SEC = 28.0        # 30 רשמית; שני אחוזים מרווח


@dataclass
class _Bucket:
    capacity: float
    refill_per_sec: float
    tokens: float = field(default=0.0)
    updated: float = field(default_factory=time.monotonic)

    def __post_init__(self):
        self.tokens = self.capacity

    def take(self, n: float = 1.0) -> float:
        """מחזיר כמה שניות להמתין. 0 = אפשר לשלוח עכשיו."""
        now = time.monotonic()
        self.tokens = min(self.capacity,
                          self.tokens + (now - self.updated) * self.refill_per_sec)
        self.updated = now
        if self.tokens >= n:
            self.tokens -= n
            return 0.0
        return (n - self.tokens) / self.refill_per_sec


class RateGuard:
    """שער יחיד לכל שליחה. אין דרך לעקוף אותו בטעות — ‎send()‎ עובר דרכו."""

    def __init__(self):
        self._chat: dict[int, _Bucket] = {}
        self._group: dict[int, _Bucket] = {}
        self._global = _Bucket(GLOBAL_PER_SEC, GLOBAL_PER_SEC)
        self._lock = asyncio.Lock()
        self._flood_until: dict[int, float] = {}
        self.waited_total = 0.0
        self.calls = 0

    def _for_chat(self, chat_id: int) -> _Bucket:
        b = self._chat.get(chat_id)
        if b is None:
            b = self._chat[chat_id] = _Bucket(PER_CHAT_PER_SEC, PER_CHAT_PER_SEC)
        return b

    def _for_group(self, chat_id: int) -> _Bucket:
        b = self._group.get(chat_id)
        if b is None:
            b = self._group[chat_id] = _Bucket(PER_GROUP_PER_MIN,
                                               PER_GROUP_PER_MIN / 60.0)
        return b

    def delay_for(self, chat_id: int, is_group: bool = True) -> float:
        """כמה להמתין לפני שליחה לצ'אט הזה, בלי לצרוך אסימון."""
        now = time.monotonic()
        waits = [max(0.0, self._flood_until.get(chat_id, 0.0) - now)]
        for b, n in ((self._for_chat(chat_id), 1.0), (self._global, 1.0)):
            waits.append(_peek(b, n))
        if is_group:
            waits.append(_peek(self._for_group(chat_id), 1.0))
        return max(waits)

    async def acquire(self, chat_id: int, is_group: bool = True) -> float:
        """ממתין כמה שצריך ואז מאשר. מחזיר כמה זמן המתין."""
        waited = 0.0
        while True:
            async with self._lock:
                now = time.monotonic()
                fw = max(0.0, self._flood_until.get(chat_id, 0.0) - now)
                if fw <= 0:
                    d1 = self._for_chat(chat_id).take()
                    d2 = self._for_group(chat_id).take() if is_group else 0.0
                    d3 = self._global.take()
                    delay = max(d1, d2, d3)
                    if delay <= 0:
                        self.calls += 1
                        self.waited_total += waited
                        return waited
                    # לא היה מספיק — מחזירים את מה שנלקח כדי לא "לשרוף"
                    self._for_chat(chat_id).tokens += 1.0
                    if is_group:
                        self._for_group(chat_id).tokens += 1.0
                    self._global.tokens += 1.0
                else:
                    delay = fw
            await asyncio.sleep(min(delay, 5.0))
            waited += min(delay, 5.0)

    def note_flood_wait(self, chat_id: int, seconds: float) -> None:
        """טלגרם החזירה FloodWait. מכבדים אותה במלואה ועוד שנייה."""
        self._flood_until[chat_id] = time.monotonic() + seconds + 1.0

    def stats(self) -> dict:
        return {
            "calls": self.calls,
            "waited_total_sec": round(self.waited_total, 2),
            "avg_wait_ms": round(1000 * self.waited_total / self.calls, 1) if self.calls else 0.0,
            "chats_tracked": len(self._chat),
            "in_flood_wait": sum(1 for t in self._flood_until.values()
                                 if t > time.monotonic()),
        }


def _peek(b: _Bucket, n: float) -> float:
    """כמה להמתין, בלי לצרוך — לתצוגה ולהחלטות תזמון."""
    now = time.monotonic()
    tokens = min(b.capacity, b.tokens + (now - b.updated) * b.refill_per_sec)
    return 0.0 if tokens >= n else (n - tokens) / b.refill_per_sec
