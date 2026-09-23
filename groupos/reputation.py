#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reputation — מי כבר הוכיח את עצמו, ומי רק הגיע.

## שני שימושים, אותו מספר

  1. **אות למדיניות.** ותיק עם 5000 נקודות ששולח קישור אינו אותו
     דבר כמו מי שנכנס לפני דקה ושולח קישור. הקישור זהה; ההקשר לא.
  2. **קהילה.** רמות וטבלת מובילים, כי קבוצה חיה על השתתפות ולא רק
     על אכיפה.

זה אותו מספר בכוונה. מערכת נקודות שמשמשת רק למשחק היא רעש, ומערכת
אמון שאינה נראית למשתמש היא ציון סמוי שאיש אינו מבין.

## למה יש צינון

בלי צינון XP, מי שכותב "כן" מאה פעמים מגיע לרמה 10. הצינון הוא
דקה: שתי הודעות באותה דקה נחשבות אחת. זה הופך את המדד ל**נוכחות
לאורך זמן** במקום ל**מספר הודעות**.

## אמון נופל מהר ועולה לאט

עבירה מורידה אמון ב-0.15; הודעה תקינה מעלה אותו ב-0.002. הא-סימטריה
מכוונת: לבנות אמון צריך לקחת שבועות, לאבד אותו — הודעה אחת. זה גם
מה שמונע מספאמר "לחמם" חשבון בחמש דקות של פטפוט.

## הרמה

    level = ⌊√(xp / 40)⌋

שורש ולא ליניארי: הרמות הראשונות מגיעות מהר ונותנות תחושת התקדמות,
והמאוחרות דורשות ממש להיות שם. 40 נקודות לרמה 1, 160 לרמה 2,
360 לרמה 3.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Optional

import policy

XP_PER_MESSAGE = 2
XP_COOLDOWN = 60.0          # שניות בין צבירות
TRUST_START = 0.5
TRUST_UP = 0.002
TRUST_DOWN = 0.15
LEVEL_BASE = 40


def level_of(xp: int) -> int:
    return int(math.sqrt(max(0, xp) / LEVEL_BASE))


def xp_for_level(level: int) -> int:
    return LEVEL_BASE * level * level


@dataclass(frozen=True)
class Rep:
    xp: int = 0
    trust: float = TRUST_START
    strikes: int = 0

    @property
    def level(self) -> int:
        return level_of(self.xp)

    @property
    def to_next(self) -> int:
        return max(0, xp_for_level(self.level + 1) - self.xp)


class Reputation:
    def __init__(self, db):
        self.db = db

    def get(self, chat_id: int, user_id: int) -> Rep:
        r = self.db.one("""SELECT xp,trust,strikes FROM reputation
                           WHERE chat_id=? AND user_id=?""",
                        (chat_id, user_id))
        return Rep(r["xp"], r["trust"], r["strikes"]) if r else Rep()

    def _ensure(self, chat_id: int, user_id: int) -> None:
        self.db.run("""INSERT INTO reputation (chat_id,user_id) VALUES (?,?)
                       ON CONFLICT DO NOTHING""", (chat_id, user_id))

    def on_message(self, chat_id: int, user_id: int,
                   now: Optional[float] = None) -> Optional[Rep]:
        """צובר XP אם עבר הצינון. מחזיר מצב חדש רק כשהרמה עלתה.

        החזרת ערך רק בעלייה ולא בכל הודעה היא מה שמאפשר להודיע על
        רמה חדשה בלי לבדוק את הרמה הקודמת בכל קריאה."""
        t = now if now is not None else time.time()
        self._ensure(chat_id, user_id)
        r = self.db.one("""SELECT xp,last_xp FROM reputation
                           WHERE chat_id=? AND user_id=?""", (chat_id, user_id))
        if r and t - (r["last_xp"] or 0) < XP_COOLDOWN:
            return None
        before = level_of(r["xp"] if r else 0)
        self.db.run("""UPDATE reputation
                       SET xp = xp + ?, last_xp = ?,
                           trust = MIN(1.0, trust + ?)
                       WHERE chat_id=? AND user_id=?""",
                    (XP_PER_MESSAGE, t, TRUST_UP, chat_id, user_id))
        new = self.get(chat_id, user_id)
        return new if new.level > before else None

    def penalize(self, chat_id: int, user_id: int, weight: float = 1.0) -> Rep:
        self._ensure(chat_id, user_id)
        self.db.run("""UPDATE reputation
                       SET trust = MAX(0.0, trust - ?), strikes = strikes + 1
                       WHERE chat_id=? AND user_id=?""",
                    (TRUST_DOWN * max(0.1, weight), chat_id, user_id))
        return self.get(chat_id, user_id)

    def reset(self, chat_id: int, user_id: int) -> None:
        self.db.change("DELETE FROM reputation WHERE chat_id=? AND user_id=?",
                       (chat_id, user_id))

    def top(self, chat_id: int, limit: int = 10) -> list[tuple[int, int, int]]:
        """‎[(user_id, xp, level)]‎ — לטבלת המובילים."""
        return [(r["user_id"], r["xp"], level_of(r["xp"])) for r in self.db.q(
            """SELECT user_id,xp FROM reputation WHERE chat_id=? AND xp>0
               ORDER BY xp DESC LIMIT ?""", (chat_id, limit))]

    def rank(self, chat_id: int, user_id: int) -> int:
        """המקום בטבלה. 0 = לא מדורג."""
        me = self.get(chat_id, user_id)
        if me.xp <= 0:
            return 0
        r = self.db.one("""SELECT COUNT(*) c FROM reputation
                           WHERE chat_id=? AND xp>?""", (chat_id, me.xp))
        return (r["c"] if r else 0) + 1

    # ── כאות למדיניות ─────────────────────────────────────────────────────
    def signal(self, chat_id: int, user_id: int) -> Optional[policy.Signal]:
        """אות **בשני הכיוונים**: חשד על אמון נמוך, הקלה על ותיקים.

        משקל שלילי מוריד את הציון הכולל, ולכן ותיק צריך יותר אותות
        אחרים כדי להגיע לאותה פעולה. זה בדיוק ההבדל בין "קישור" לבין
        "קישור ממי שנכנס לפני דקה"."""
        r = self.get(chat_id, user_id)
        if r.trust < 0.3:
            return policy.Signal("reputation", "low_trust",
                                 min(0.6, (0.3 - r.trust) * 2),
                                 f"trust {r.trust:.2f}")
        if r.level >= 3 and r.trust > 0.7:
            return policy.Signal("reputation", "trusted", 0.0,
                                 f"level {r.level}")
        return None

    def discount(self, chat_id: int, user_id: int) -> float:
        """מקדם הנחה לציון הסיכון, 0–0.5. ותיק אינו חסין — הוא סלחני.

        התקרה היא 0.5 בכוונה: ותיק ששולח פישינג עדיין עובר את הסף.
        הנחה ללא תקרה הייתה הופכת ותק לחסינות, וזה בדיוק מה שחשבון
        שנפרץ מנצל."""
        r = self.get(chat_id, user_id)
        if r.strikes:
            return 0.0
        return round(min(0.5, 0.1 * r.level * r.trust), 3)
