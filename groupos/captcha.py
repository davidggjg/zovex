#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""captcha — אימות שהנכנס אנושי.

## למה זה עובד בכלל

CAPTCHA בטלגרם לא בודקת "האם אתה רובוט". היא בודקת **האם מישהו כאן
בכלל**. חשבון ספאם נכנס ל-200 קבוצות בדקה ויוצא; הוא לא עוצר ללחוץ
כפתור בכל אחת. די בכך כדי לעצור את רוב הפשיטות.

לכן הסוג שנבחר כברירת מחדל הוא כפתור אחד: הוא עוצר ספאם אוטומטי,
ולא מייאש אדם אמיתי. חשבון שבאמת מנוהל בידי אדם יעבור בשתי שניות.

## שלושה סוגים

    button   כפתור אחד. ברירת המחדל
    math     תרגיל חיבור קצר — נגד בוטים שלוחצים כפתורים
    emoji    בחירת אימוג'י מבוקש מתוך כמה

## איך זה נאכף

הנכנס מושתק מיד, ומקבל הודעה עם כפתורים. עמידה באתגר מחזירה את
ההרשאות. כישלון או פקיעה — לפי מה שהמנהל בחר.

**ההשתקה קודמת להודעה.** אם ההודעה נכשלת ברשת, עדיף משתמש מושתק
שמנהל ישחרר מאשר ספאמר שנכנס בלי שנבדק.

## למה המצב בזיכרון

אתגר חי הוא נתון של דקה. הענישה — שהיא מה שצריך לשרוד אתחול — נשמרת
במסד דרך ‎moderation‎. אתחול באמצע אתגר משחרר את הממתינים, וזה הכיוון
הנכון לטעות בו.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Optional

KINDS = ("button", "math", "emoji")
FAIL_ACTIONS = ("kick", "mute", "ban", "none")

DEFAULT_TIMEOUT = 120        # שניות
DEFAULT_TRIES = 3

EMOJIS = ("🍎", "🚗", "⭐", "🐱", "🌳", "⚽", "🎈", "🔑", "🎵", "☂️")
EMOJI_NAMES = {
    "🍎": "apple", "🚗": "car", "⭐": "star", "🐱": "cat", "🌳": "tree",
    "⚽": "ball", "🎈": "balloon", "🔑": "key", "🎵": "note", "☂️": "umbrella",
}


@dataclass
class Challenge:
    chat_id: int
    user_id: int
    kind: str
    answer: str
    choices: list[str] = field(default_factory=list)
    prompt: str = ""
    tries: int = DEFAULT_TRIES
    deadline: float = 0.0
    message_id: Optional[int] = None

    def expired(self, now: Optional[float] = None) -> bool:
        return (now if now is not None else time.time()) >= self.deadline


def build(chat_id: int, user_id: int, kind: str = "button", *,
          timeout: int = DEFAULT_TIMEOUT, tries: int = DEFAULT_TRIES,
          now: Optional[float] = None) -> Challenge:
    """בונה אתגר. טהור — אפשר לבדוק בלי בוט ובלי רשת."""
    t = (now if now is not None else time.time()) + max(10, timeout)
    if kind == "math":
        a, b = random.randint(2, 9), random.randint(2, 9)
        right = a + b
        opts = {right}
        while len(opts) < 4:
            opts.add(max(1, right + random.randint(-4, 4)))
        choices = [str(c) for c in sorted(opts)]
        return Challenge(chat_id, user_id, kind, str(right), choices,
                         f"{a} + {b} = ?", tries, t)
    if kind == "emoji":
        picks = random.sample(EMOJIS, 4)
        right = random.choice(picks)
        return Challenge(chat_id, user_id, kind, right, list(picks),
                         EMOJI_NAMES[right], tries, t)
    return Challenge(chat_id, user_id, "button", "ok", ["ok"], "", tries, t)


class Pending:
    """האתגרים הפתוחים. מפתח: ‎(chat_id, user_id)‎."""

    def __init__(self):
        self._live: dict[tuple[int, int], Challenge] = {}

    def add(self, ch: Challenge) -> None:
        self._live[(ch.chat_id, ch.user_id)] = ch

    def get(self, chat_id: int, user_id: int) -> Optional[Challenge]:
        return self._live.get((chat_id, user_id))

    def drop(self, chat_id: int, user_id: int) -> Optional[Challenge]:
        return self._live.pop((chat_id, user_id), None)

    def waiting(self, chat_id: int, user_id: int) -> bool:
        return (chat_id, user_id) in self._live

    def answer(self, chat_id: int, user_id: int, given: str) -> str:
        """‎'ok'‎ · ‎'retry'‎ · ‎'fail'‎ · ‎'gone'‎."""
        ch = self._live.get((chat_id, user_id))
        if ch is None:
            return "gone"
        if given == ch.answer:
            self._live.pop((chat_id, user_id), None)
            return "ok"
        ch.tries -= 1
        if ch.tries <= 0:
            self._live.pop((chat_id, user_id), None)
            return "fail"
        return "retry"

    def expired(self, now: Optional[float] = None) -> list[Challenge]:
        t = now if now is not None else time.time()
        out = [c for c in self._live.values() if c.expired(t)]
        for c in out:
            self._live.pop((c.chat_id, c.user_id), None)
        return out

    def count(self, chat_id: Optional[int] = None) -> int:
        if chat_id is None:
            return len(self._live)
        return sum(1 for c, _ in self._live if c == chat_id)
