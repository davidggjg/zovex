#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""moderation — אזהרות, השתקות, חסימות. ההחלטה, לא הביצוע.

## למה ההחלטה נפרדת מהביצוע

הפונקציות כאן מחזירות **מה צריך לקרות**, ולא קוראות לטלגרם. כך:

  • אפשר לבדוק את כל מדיניות האזהרות בלי קבוצה אמיתית
  • הסימולטור יוכל להריץ הודעה ולהראות מה היה קורה, בלי לעשות את זה
  • אותה החלטה מגיעה מפקודה, מכפתור בפאנל או מזיהוי אוטומטי

## מדיניות האזהרות

לכל קבוצה סולם משלה. ברירת המחדל:

    3 אזהרות → השתקה לשעה
    5 אזהרות → השתקה ליום
    7 אזהרות → חסימה

הסולם נשמר כמחרוזת בהגדרות, ולכן מנהל יכול לשנות אותו בלי קוד.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

DEFAULT_POLICY = "3:mute:3600,5:mute:86400,7:ban:0"

KIND_LABEL = {
    "mute": "השתקה",
    "ban": "חסימה",
    "kick": "הרחקה",
    "warn": "אזהרה",
}


@dataclass(frozen=True)
class Outcome:
    """מה צריך לקרות. המתאם מבצע; כאן רק מחליטים."""
    kind: str                       # warn | mute | ban | kick | none
    user_id: int
    reason: str = ""
    duration: Optional[int] = None  # שניות; None = לצמיתות
    warns: int = 0
    threshold_hit: bool = False
    note: str = ""

    @property
    def label(self) -> str:
        base = KIND_LABEL.get(self.kind, self.kind)
        if self.duration:
            return f"{base} ל-{_human(self.duration)}"
        return base


def _human(sec: int) -> str:
    if sec < 3600:
        return f"{sec // 60} דקות"
    if sec < 86400:
        h = sec // 3600
        return "שעה" if h == 1 else f"{h} שעות"
    d = sec // 86400
    return "יום" if d == 1 else f"{d} ימים"


def parse_policy(raw: str) -> list[tuple[int, str, Optional[int]]]:
    """'3:mute:3600,7:ban:0' → [(3,'mute',3600), (7,'ban',None)]"""
    out = []
    for part in (raw or "").split(","):
        bits = part.strip().split(":")
        if len(bits) != 3:
            continue
        try:
            n, kind, dur = int(bits[0]), bits[1].strip(), int(bits[2])
        except ValueError:
            continue
        if kind in ("mute", "ban", "kick"):
            out.append((n, kind, dur or None))
    return sorted(out)


def format_policy(policy: list[tuple[int, str, Optional[int]]]) -> str:
    return " · ".join(
        f"{n} → {KIND_LABEL.get(k, k)}" + (f" ל-{_human(d)}" if d else "")
        for n, k, d in policy)


class Moderation:
    def __init__(self, db, audit):
        self.db = db
        self.audit = audit

    def policy(self, chat_id: int) -> list[tuple[int, str, Optional[int]]]:
        return parse_policy(self.db.get(chat_id, "warn_policy", DEFAULT_POLICY))

    def warn_count(self, chat_id: int, user_id: int) -> int:
        r = self.db.one("""SELECT COUNT(*) c FROM warnings
                           WHERE chat_id=? AND user_id=? AND revoked_at IS NULL""",
                        (chat_id, user_id))
        return r["c"] if r else 0

    # ── אזהרה ──────────────────────────────────────────────────────────────
    def warn(self, chat_id: int, user_id: int, by: Optional[int],
             reason: str = "", source: str = "command") -> Outcome:
        """מוסיף אזהרה ומחזיר מה צריך לקרות בעקבותיה."""
        self.db.run("""INSERT INTO warnings (chat_id,user_id,by_id,reason,ts)
                       VALUES (?,?,?,?,?)""",
                    (chat_id, user_id, by, reason or None, time.time()))
        n = self.warn_count(chat_id, user_id)
        self.db.run("""INSERT INTO members (chat_id,user_id,warns,last_msg)
                       VALUES (?,?,?,0)
                       ON CONFLICT (chat_id,user_id) DO UPDATE SET warns=?""",
                    (chat_id, user_id, n, n))
        self.audit.log(chat_id, "user.warn", actor_id=by, target_id=user_id,
                       reason=reason, after=n, source=source, severity="low")

        for need, kind, dur in self.policy(chat_id):
            if n == need:
                self.audit.log(chat_id, f"policy.{kind}", actor_id=by,
                               target_id=user_id,
                               reason=f"הגיע ל-{n} אזהרות", after=dur,
                               source="policy", severity="medium")
                return Outcome(kind, user_id, f"{n} אזהרות", dur, n, True)
        return Outcome("warn", user_id, reason, None, n, False)

    def unwarn(self, chat_id: int, user_id: int, by: Optional[int]) -> int:
        """מבטל את האזהרה האחרונה. מחזיר כמה נשארו."""
        r = self.db.one("""SELECT id FROM warnings
                           WHERE chat_id=? AND user_id=? AND revoked_at IS NULL
                           ORDER BY ts DESC LIMIT 1""", (chat_id, user_id))
        if r:
            self.db.run("UPDATE warnings SET revoked_at=? WHERE id=?",
                        (time.time(), r["id"]))
        n = self.warn_count(chat_id, user_id)
        self.db.run("UPDATE members SET warns=? WHERE chat_id=? AND user_id=?",
                    (n, chat_id, user_id))
        self.audit.log(chat_id, "user.unwarn", actor_id=by, target_id=user_id,
                       after=n, severity="info")
        return n

    def reset_warns(self, chat_id: int, user_id: int, by: Optional[int]) -> None:
        self.db.run("""UPDATE warnings SET revoked_at=?
                       WHERE chat_id=? AND user_id=? AND revoked_at IS NULL""",
                    (time.time(), chat_id, user_id))
        self.db.run("UPDATE members SET warns=0 WHERE chat_id=? AND user_id=?",
                    (chat_id, user_id))
        self.audit.log(chat_id, "user.warns_reset", actor_id=by,
                       target_id=user_id, severity="info")

    def history(self, chat_id: int, user_id: int) -> list[dict]:
        return [dict(r) for r in self.db.q(
            """SELECT * FROM warnings WHERE chat_id=? AND user_id=?
               ORDER BY ts DESC LIMIT 20""", (chat_id, user_id))]

    # ── ענישות ─────────────────────────────────────────────────────────────
    def record(self, chat_id: int, user_id: int, kind: str,
               by: Optional[int], reason: str = "",
               duration: Optional[int] = None,
               source: str = "command") -> int:
        exp = time.time() + duration if duration else None
        sid = self.db.run(
            """INSERT INTO sanctions (chat_id,user_id,kind,by_id,reason,ts,expires_at)
               VALUES (?,?,?,?,?,?,?)""",
            (chat_id, user_id, kind, by, reason or None, time.time(), exp))
        self.audit.log(chat_id, f"user.{kind}", actor_id=by, target_id=user_id,
                       reason=reason, after=duration, source=source,
                       severity="high" if kind == "ban" else "medium")
        return sid

    def lift(self, chat_id: int, user_id: int, kind: str,
             by: Optional[int]) -> bool:
        cur = self.db.conn.execute(
            """UPDATE sanctions SET lifted_at=?
               WHERE chat_id=? AND user_id=? AND kind=? AND lifted_at IS NULL""",
            (time.time(), chat_id, user_id, kind))
        if cur.rowcount:
            self.audit.log(chat_id, f"user.un{kind}", actor_id=by,
                           target_id=user_id, severity="info")
        return bool(cur.rowcount)

    def active(self, chat_id: int, user_id: int) -> list[dict]:
        now = time.time()
        return [dict(r) for r in self.db.q(
            """SELECT * FROM sanctions
               WHERE chat_id=? AND user_id=? AND lifted_at IS NULL
                 AND (expires_at IS NULL OR expires_at > ?)""",
            (chat_id, user_id, now))]

    def expired(self, limit: int = 100) -> list[dict]:
        """ענישות שפג תוקפן וצריך לשחרר. המתאם קורא לזה מדי דקה."""
        return [dict(r) for r in self.db.q(
            """SELECT * FROM sanctions
               WHERE lifted_at IS NULL AND expires_at IS NOT NULL
                 AND expires_at <= ? LIMIT ?""", (time.time(), limit))]
