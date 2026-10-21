#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit — מי עשה מה, על מי, מתי, ולמה.

## למה זה לא "עוד לוג"

יומן רגיל עונה על "מה קרה". היומן הזה צריך לענות על שלוש שאלות נוספות:

  **למה זה נמחק?** — משתמש שמתלונן. בלי ‎reason‎ ו-‎source‎ אין תשובה.
  **מי שינה את ההגדרה?** — ‎before_val‎ ו-‎after_val‎, אחרת אי אפשר לדעת.
  **איך מחזירים אחורה?** — ‎before_val‎ הוא מה שמאפשר Rollback אמיתי.

לכן כל רשומה נושאת מצב לפני ואחרי, ולא רק את שם הפעולה.

## Severity

לא קישוט. ההתראות למנהלים מסוננות לפיה, ובלעדיה או שמציפים אותם או
שמפספסים raid.

    info      פעולה שגרתית
    low       עבירה קלה, טופלה
    medium    חשד שדורש עין
    high      איום ממשי
    critical  raid פעיל, או פעולה הרסנית
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

SEVERITIES = ("info", "low", "medium", "high", "critical")

# מאיפה הגיעה הפעולה. חשוב להפריד אוטומטי מידני — אחרת אי אפשר לדעת
# אם המערכת עובדת או שמנהל עושה הכול בידיים.
SOURCES = ("command", "button", "automation", "policy", "ai", "system", "api")


class Audit:
    def __init__(self, db):
        self.db = db

    def log(self, chat_id: int, action: str, *,
            actor_id: Optional[int] = None,
            actor_kind: str = "user",
            target_id: Optional[int] = None,
            reason: Optional[str] = None,
            before: Any = None,
            after: Any = None,
            source: str = "command",
            severity: str = "info") -> int:
        if severity not in SEVERITIES:
            severity = "info"
        if source not in SOURCES:
            source = "command"
        return self.db.run(
            """INSERT INTO audit_log
               (ts,chat_id,actor_id,actor_kind,action,target_id,reason,
                before_val,after_val,source,severity)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (time.time(), chat_id, actor_id, actor_kind, action, target_id,
             reason, _enc(before), _enc(after), source, severity))

    # ── קריאה ──────────────────────────────────────────────────────────────
    def recent(self, chat_id: int, limit: int = 50,
               min_severity: Optional[str] = None) -> list[dict]:
        sql = "SELECT * FROM audit_log WHERE chat_id=?"
        args: list = [chat_id]
        if min_severity in SEVERITIES:
            keep = SEVERITIES[SEVERITIES.index(min_severity):]
            sql += " AND severity IN (%s)" % ",".join("?" * len(keep))
            args += list(keep)
        sql += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.db.q(sql, args)]

    def for_user(self, chat_id: int, user_id: int, limit: int = 50) -> list[dict]:
        """כל מה שנעשה על המשתמש — הבסיס למסך החקירה."""
        return [dict(r) for r in self.db.q(
            """SELECT * FROM audit_log WHERE chat_id=? AND target_id=?
               ORDER BY ts DESC LIMIT ?""", (chat_id, user_id, limit))]

    def by_actor(self, chat_id: int, actor_id: int, limit: int = 50) -> list[dict]:
        """מה מנהל מסוים עשה — לביקורת על המנהלים עצמם."""
        return [dict(r) for r in self.db.q(
            """SELECT * FROM audit_log WHERE chat_id=? AND actor_id=?
               ORDER BY ts DESC LIMIT ?""", (chat_id, actor_id, limit))]

    def prune(self, older_than_days: int = 90) -> int:
        """מדיניות מחיקה. נמדד: 49 בייט להודעה — בלי זה הדיסק נגמר."""
        cutoff = time.time() - older_than_days * 86400
        cur = self.db.conn.execute(
            "DELETE FROM audit_log WHERE ts < ? AND severity IN ('info','low')",
            (cutoff,))
        return cur.rowcount


def _enc(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(v)
