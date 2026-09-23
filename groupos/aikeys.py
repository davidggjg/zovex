#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aikeys — בריכת מפתחות לספקי AI, עם סבב וצינון.

## מה זה פותר

מכסה חינמית אינה "בלתי מוגבלת עד שהיא נגמרת". היא נגמרת **באמצע
הודעה**, מחזירה 429, ואם אין תוכנית — הפיצ'ר פשוט מפסיק לעבוד בלי
שאף אחד יידע. כאן: כמה מפתחות לספק, סבב ביניהם, וצינון למי שנחסם.

## הכלל שקובע איזה מפתח נבחר

**הכי פחות עמוס שאינו בצינון.** לא round-robin עיוור: מפתח שהחזיר
429 לפני שתי שניות לא צריך לקבל את הבקשה הבאה רק כי הגיע תורו.

## צינון

429 מצנן את המפתח. אם השרת אמר ‎Retry-After‎ — לפי מה שאמר; אחרת
צינון עולה: 30 שניות, אחר כך דקה, אחר כך שתיים, עד תקרה. שגיאת אימות
(401/403) מוציאה את המפתח **לגמרי** — מפתח שבוטל לא יתקן את עצמו,
וניסיון חוזר עליו הוא בזבוז של כל בקשה.

## מה לא נמצא כאן

אין כאן HTTP. המודול מחליט **איזה מפתח** ומקבל דיווח מה קרה; מי
ששולח את הבקשה הוא מודול אחר. כך אפשר לבדוק את כל התנהגות הסבב
והצינון בלי רשת ובלי מפתחות אמיתיים.

## סודיות

המפתח עצמו לעולם לא נכתב ליומן ולא מוחזר בסטטיסטיקה. ‎mask()‎ מחזיר
ארבעה תווים ראשונים ואחרונים, וזה מספיק כדי לדעת **איזה** מפתח נפל
בלי לחשוף אותו. הבריכה נטענת ממשתני סביבה בלבד — מפתח לעולם לא נכנס
למאגר ולא לקובץ שנמצא בגיט.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional

COOLDOWN_START = 30.0       # שניות, אחרי 429 ראשון
COOLDOWN_MAX = 900.0        # תקרת צינון — רבע שעה
DAY = 86400.0


def mask(key: str) -> str:
    """‎'AQ.Ab8R…bF3k'‎. מספיק לזיהוי, לא מספיק לשימוש."""
    k = (key or "").strip()
    if len(k) <= 10:
        return "…"
    return f"{k[:4]}…{k[-4:]}"


def split_keys(raw: str) -> list[str]:
    """מפריד לפי פסיק, נקודה-פסיק, רווח או שורה. בלי כפילויות.

    הפרדה סלחנית בכוונה: מי שמדביק חמישה מפתחות ל-‎.env‎ עושה את זה
    פעם אחת, ובחצי מהמקרים עם רווח או ירידת שורה באמצע."""
    out, seen = [], set()
    for tok in (raw or "").replace(",", "\n").replace(";", "\n").split():
        tok = tok.strip().strip('"\'')
        if tok and tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


@dataclass
class KeyState:
    key: str
    used: int = 0               # בקשות מאז האיפוס היומי
    errors: int = 0
    cooldown_until: float = 0.0
    cooldown_step: float = 0.0
    dead: bool = False          # 401/403 — לא חוזרים אליו
    last_used: float = 0.0

    @property
    def label(self) -> str:
        return mask(self.key)


class KeyPool:
    """בריכה של ספק אחד."""

    def __init__(self, name: str, keys: Iterable[str],
                 rpd: Optional[int] = None):
        self.name = name
        self.rpd = rpd          # תקרה יומית למפתח, אם ידועה
        self.keys = [KeyState(k) for k in keys]
        self._day = 0.0

    def __len__(self) -> int:
        return len(self.keys)

    # ── בחירה ─────────────────────────────────────────────────────────────
    def acquire(self, now: Optional[float] = None) -> Optional[str]:
        """המפתח הזמין הפחות עמוס, או ‎None‎ אם כולם חסומים."""
        t = now if now is not None else time.time()
        self._roll_day(t)
        live = [k for k in self.keys
                if not k.dead and k.cooldown_until <= t
                and (self.rpd is None or k.used < self.rpd)]
        if not live:
            return None
        pick = min(live, key=lambda k: (k.used, k.last_used))
        pick.used += 1
        pick.last_used = t
        return pick.key

    def _find(self, key: str) -> Optional[KeyState]:
        return next((k for k in self.keys if k.key == key), None)

    # ── דיווח ─────────────────────────────────────────────────────────────
    def ok(self, key: str) -> None:
        """הצלחה מאפסת את הצינון, לא רק מסירה אותו.

        בלי האיפוס, מפתח שנחסם פעם אחת היה נשאר עם צינון של רבע שעה
        לנצח — כל 429 עתידי היה מתחיל מהתקרה."""
        st = self._find(key)
        if st:
            st.cooldown_step = 0.0
            st.cooldown_until = 0.0

    def fail(self, key: str, *, status: Optional[int] = None,
             retry_after: Optional[float] = None,
             now: Optional[float] = None) -> float:
        """מדווח כישלון ומחזיר לכמה זמן המפתח מצונן."""
        t = now if now is not None else time.time()
        st = self._find(key)
        if st is None:
            return 0.0
        st.errors += 1
        if status in (401, 403):
            st.dead = True
            return 0.0
        if status is not None and status != 429 and status < 500:
            return 0.0          # שגיאת בקשה — לא אשמת המפתח
        if retry_after and retry_after > 0:
            wait = min(float(retry_after), COOLDOWN_MAX)
        else:
            step = st.cooldown_step * 2 if st.cooldown_step else COOLDOWN_START
            wait = min(step, COOLDOWN_MAX)
        st.cooldown_step = wait
        st.cooldown_until = t + wait
        return wait

    def revive(self, now: Optional[float] = None) -> int:
        """מחזיר מפתחות שסומנו מתים. ידני בלבד — אחרי החלפת מפתח."""
        n = sum(1 for k in self.keys if k.dead)
        for k in self.keys:
            k.dead = False
            k.cooldown_until = 0.0
            k.cooldown_step = 0.0
        return n

    def _roll_day(self, t: float) -> None:
        day = t // DAY
        if day != self._day:
            self._day = day
            for k in self.keys:
                k.used = 0

    # ── מצב ───────────────────────────────────────────────────────────────
    def available(self, now: Optional[float] = None) -> int:
        t = now if now is not None else time.time()
        return sum(1 for k in self.keys
                   if not k.dead and k.cooldown_until <= t
                   and (self.rpd is None or k.used < self.rpd))

    def stats(self, now: Optional[float] = None) -> dict:
        t = now if now is not None else time.time()
        return {
            "provider": self.name,
            "keys": len(self.keys),
            "available": self.available(t),
            "dead": sum(1 for k in self.keys if k.dead),
            "cooling": sum(1 for k in self.keys
                           if not k.dead and k.cooldown_until > t),
            "used_today": sum(k.used for k in self.keys),
            "budget": (self.rpd * len(self.keys)) if self.rpd else None,
            "detail": [{"key": k.label, "used": k.used, "errors": k.errors,
                        "dead": k.dead,
                        "cooling_for": max(0, round(k.cooldown_until - t))}
                       for k in self.keys],
        }


# מכסות חינמיות ידועות, לבקשות ליום למפתח. ‎None‎ = לא ידוע, ואז לא
# מגבילים מצדנו — עדיף לקבל 429 אמיתי מאשר לחסום בקשה שהייתה עוברת.
FREE_RPD = {"gemini": 1000, "groq": 14400}

ENV_VARS = {"gemini": "GROUPOS_GEMINI_KEYS", "groq": "GROUPOS_GROQ_KEYS"}


class Providers:
    """כל הבריכות יחד, עם סדר העדפה.

    הסדר אינו שרירותי: הראשון הוא מי שעונה מהר וזול יותר למשימות
    הקצרות, והשאר הם גיבוי. ‎pick()‎ יורד ברשימה עד שמוצא מפתח פנוי,
    וכך נפילה של ספק אחד אינה מפילה את הפיצ'ר."""

    ORDER = ("groq", "gemini")

    def __init__(self, pools: Optional[dict[str, KeyPool]] = None):
        self.pools: dict[str, KeyPool] = pools or {}

    @classmethod
    def from_env(cls, env: Optional[dict] = None) -> "Providers":
        src = env if env is not None else os.environ
        pools = {}
        for name, var in ENV_VARS.items():
            keys = split_keys(src.get(var, ""))
            if keys:
                pools[name] = KeyPool(name, keys, FREE_RPD.get(name))
        return cls(pools)

    def pick(self, prefer: Optional[str] = None,
             now: Optional[float] = None) -> Optional[tuple[str, str]]:
        """‎(ספק, מפתח)‎ — או ‎None‎ כשאין אף מפתח פנוי בשום ספק."""
        order = ([prefer] if prefer else []) + [p for p in self.ORDER
                                                if p != prefer]
        for name in order:
            pool = self.pools.get(name)
            if pool is None:
                continue
            key = pool.acquire(now)
            if key:
                return name, key
        return None

    def ok(self, provider: str, key: str) -> None:
        pool = self.pools.get(provider)
        if pool:
            pool.ok(key)

    def fail(self, provider: str, key: str, **kw) -> float:
        pool = self.pools.get(provider)
        return pool.fail(key, **kw) if pool else 0.0

    def ready(self, now: Optional[float] = None) -> bool:
        return any(p.available(now) for p in self.pools.values())

    def stats(self, now: Optional[float] = None) -> list[dict]:
        return [p.stats(now) for p in self.pools.values()]

    def budget(self) -> int:
        """כמה בקשות ליום הבריכה נותנת, לפי המכסות הידועות."""
        return sum((p.rpd or 0) * len(p) for p in self.pools.values())
