#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reports — דיווח שיש לו מצב, ולא רק התראה שנעלמת.

## מה היה חסר

‎/report‎ עשה שני דברים: רשם ביומן ושלח למנהלים בפרטי. שניהם נכונים
ושניהם חד-כיווניים. מה שלא היה אפשר לדעת:

* מה כבר טופל ומה תלוי ועומד.
* מי טיפל, ומתי.
* האם כבר דווח על ההודעה הזאת — או שאנחנו מסתכלים על הדיווח השביעי
  על אותו דבר.

התראה בפרטי גם נקברת: מנהל שראה אותה בשלוש בלילה ולא פעל, שכח. אין
רשימה לחזור אליה.

## המפתח הלוגי הוא ההודעה, לא הדיווח

חמישה חברים שמדווחים על אותה הודעה אינם חמישה דיווחים. הם **דיווח
אחד עם חמישה מדווחים**, וזה הבדל מעשי: חמישה מדווחים הם אות חזק יותר
מאחד, אבל חמש התראות זהות בפרטי הן רעש שמסתיר את השאר.

לכן דיווח על הודעה שיש לה כבר דיווח פתוח מצטרף אליו. המונה עולה, ומי
שמדווח נרשם ב-‎report_voters‎ — טבלה ולא מונה, כדי שאותו אדם שמדווח
שוב לא ייספר פעמיים, ושאפשר יהיה לדעת מי הם.

## דיווח על הודעה שנמחקה

‎msg_id‎ יכול להיות ‎None‎ — למשל כשמדווחים על משתמש בלי להשיב להודעה.
במקרה כזה אין איחוד, כי אין על מה לאחד; כל דיווח עומד בזכות עצמו.
זה מכוון: איחוד לפי ‎target_id‎ בלבד היה מאחד דיווחים על **דברים
שונים** שאותו אדם עשה.

## שלושה מצבים ולא שניים

‎open‎ · ‎handled‎ · ‎dismissed‎. "נדחה" אינו "טופל": דיווח שווא ודיווח
שהוביל לענישה הם שני דברים, וחשוב שאפשר יהיה לראות את היחס ביניהם —
מדווח שכל דיווחיו נדחו הוא עצמו בעיה.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

OPEN = "open"
HANDLED = "handled"
DISMISSED = "dismissed"
STATUSES = (OPEN, HANDLED, DISMISSED)

# תקרה לאורך הסיבה, כדי שדיווח לא יהפוך למאמר בהתראה של המנהל.
REASON_MAX = 300


@dataclass(frozen=True)
class Report:
    id: int
    chat_id: int
    msg_id: Optional[int]
    target_id: int
    reason: str
    status: str
    count: int
    handled_by: Optional[int]
    handled_at: Optional[float]
    note: Optional[str]
    created_at: float

    @property
    def is_open(self) -> bool:
        return self.status == OPEN


def _row(r) -> Report:
    return Report(r["id"], r["chat_id"], r["msg_id"], r["target_id"],
                  r["reason"], r["status"], r["count"], r["handled_by"],
                  r["handled_at"], r["note"], r["created_at"])


class Reports:
    def __init__(self, db):
        self.db = db

    # ── יצירה ─────────────────────────────────────────────────────────────
    def add(self, chat_id: int, reporter_id: int, target_id: int,
            msg_id: Optional[int] = None, reason: str = "",
            now: Optional[float] = None) -> tuple[Report, bool]:
        """מוסיף דיווח, או מצטרף לקיים.

        מחזיר ‎(דיווח, חדש?)‎. ‎חדש=False‎ פירושו שההודעה הזאת כבר דווחה
        ויש דיווח פתוח עליה — וזה מה שמאפשר לקורא להחליט אם לשלוח
        התראה נוספת למנהלים או לא.
        """
        t = now if now is not None else time.time()
        reason = (reason or "").strip()[:REASON_MAX]

        if msg_id is not None:
            cur = self.db.one(
                """SELECT * FROM reports
                   WHERE chat_id=? AND msg_id=? AND status=?""",
                (chat_id, msg_id, OPEN))
            if cur:
                # מדווח חדש מעלה את המונה; אותו מדווח פעמיים לא —
                # ON CONFLICT DO NOTHING מבטיח את זה, והמונה נגזר
                # מספירת השורות ולא מ-count+1, כדי שלא יתפצל ממנה.
                self.db.run(
                    """INSERT INTO report_voters (report_id,user_id,at)
                       VALUES (?,?,?) ON CONFLICT DO NOTHING""",
                    (cur["id"], reporter_id, t))
                fresh = self.db.one(
                    "SELECT COUNT(*) c FROM report_voters WHERE report_id=?",
                    (cur["id"],))
                self.db.run("UPDATE reports SET count=? WHERE id=?",
                            (fresh["c"] if fresh else 1, cur["id"]))
                # סיבה נוספת לא דורסת את הראשונה אלא מצטרפת, כי שתי
                # סיבות שונות על אותה הודעה הן מידע ולא כפילות.
                if reason and reason not in (cur["reason"] or ""):
                    joined = ((cur["reason"] or "") + " · " + reason).strip(" ·")
                    self.db.run("UPDATE reports SET reason=? WHERE id=?",
                                (joined[:REASON_MAX], cur["id"]))
                return self.get(chat_id, cur["id"]), False

        rid = self.db.run(
            """INSERT INTO reports
               (chat_id,msg_id,target_id,reason,status,count,created_at)
               VALUES (?,?,?,?,?,1,?)""",
            (chat_id, msg_id, target_id, reason, OPEN, t))
        self.db.run("""INSERT INTO report_voters (report_id,user_id,at)
                       VALUES (?,?,?) ON CONFLICT DO NOTHING""",
                    (rid, reporter_id, t))
        return self.get(chat_id, rid), True

    # ── קריאה ─────────────────────────────────────────────────────────────
    def get(self, chat_id: int, rid: int) -> Optional[Report]:
        r = self.db.one("SELECT * FROM reports WHERE chat_id=? AND id=?",
                        (chat_id, rid))
        return _row(r) if r else None

    def list(self, chat_id: int, status: Optional[str] = OPEN,
             limit: int = 20) -> list[Report]:
        """‎status=None‎ מחזיר הכל, כדי שאפשר יהיה לראות גם היסטוריה."""
        if status is None:
            rows = self.db.q(
                """SELECT * FROM reports WHERE chat_id=?
                   ORDER BY created_at DESC LIMIT ?""", (chat_id, limit))
        else:
            rows = self.db.q(
                """SELECT * FROM reports WHERE chat_id=? AND status=?
                   ORDER BY created_at DESC LIMIT ?""",
                (chat_id, status, limit))
        return [_row(r) for r in rows]

    def voters(self, rid: int) -> list[int]:
        return [r["user_id"] for r in self.db.q(
            "SELECT user_id FROM report_voters WHERE report_id=? ORDER BY at",
            (rid,))]

    def counts(self, chat_id: int) -> dict:
        out = {s: 0 for s in STATUSES}
        for r in self.db.q("""SELECT status, COUNT(*) c FROM reports
                              WHERE chat_id=? GROUP BY status""", (chat_id,)):
            out[r["status"]] = r["c"]
        return out

    def open_count(self, chat_id: int) -> int:
        return self.counts(chat_id)[OPEN]

    # ── סגירה ─────────────────────────────────────────────────────────────
    def _close(self, chat_id: int, rid: int, status: str, by: int,
               note: str = "", now: Optional[float] = None) -> Optional[Report]:
        t = now if now is not None else time.time()
        # WHERE על status=open ולא רק על id: שני מנהלים שסוגרים את אותו
        # דיווח בו-זמנית — הראשון קובע, והשני מקבל None ויֵדע לומר
        # "כבר טופל" במקום לדרוס את מי שטיפל.
        n = self.db.change(
            """UPDATE reports SET status=?, handled_by=?, handled_at=?, note=?
               WHERE chat_id=? AND id=? AND status=?""",
            (status, by, t, (note or "").strip()[:REASON_MAX] or None,
             chat_id, rid, OPEN))
        return self.get(chat_id, rid) if n else None

    def resolve(self, chat_id: int, rid: int, by: int, note: str = "",
                now: Optional[float] = None) -> Optional[Report]:
        return self._close(chat_id, rid, HANDLED, by, note, now)

    def dismiss(self, chat_id: int, rid: int, by: int, note: str = "",
                now: Optional[float] = None) -> Optional[Report]:
        return self._close(chat_id, rid, DISMISSED, by, note, now)

    def reopen(self, chat_id: int, rid: int) -> Optional[Report]:
        n = self.db.change(
            """UPDATE reports SET status=?, handled_by=NULL, handled_at=NULL
               WHERE chat_id=? AND id=? AND status<>?""",
            (OPEN, chat_id, rid, OPEN))
        return self.get(chat_id, rid) if n else None

    # ── ניקוי ─────────────────────────────────────────────────────────────
    KEEP_CLOSED_DAYS = 30

    def prune(self, chat_id: Optional[int] = None,
              now: Optional[float] = None) -> int:
        """מוחק דיווחים סגורים ישנים. פתוחים **אינם** נמחקים לעולם.

        דיווח פתוח שנעלם מעצמו הוא בדיוק מה שהמערכת הזאת באה למנוע.
        """
        t = now if now is not None else time.time()
        cut = t - self.KEEP_CLOSED_DAYS * 86400
        if chat_id is None:
            n = self.db.change(
                """DELETE FROM reports
                   WHERE status<>? AND COALESCE(handled_at, created_at)<?""",
                (OPEN, cut))
        else:
            n = self.db.change(
                """DELETE FROM reports WHERE chat_id=? AND status<>?
                   AND COALESCE(handled_at, created_at)<?""",
                (chat_id, OPEN, cut))
        # שורות הצבעה שאיבדו את הדיווח שלהן
        self.db.change("""DELETE FROM report_voters WHERE report_id NOT IN
                          (SELECT id FROM reports)""")
        return n

    # ── אות למדיניות ──────────────────────────────────────────────────────
    def reporter_credibility(self, chat_id: int, user_id: int) -> float:
        """0–1: איזה חלק מהדיווחים של האדם הזה הוביל לטיפול.

        מוחזר 0.5 כשאין די נתונים (פחות משלושה דיווחים סגורים), כי
        מדווח חדש אינו אמור להיחשב לא-אמין — ולא אמור להיחשב אמין.
        """
        r = self.db.one(
            """SELECT
                 SUM(CASE WHEN r.status=? THEN 1 ELSE 0 END) ok,
                 SUM(CASE WHEN r.status=? THEN 1 ELSE 0 END) no
               FROM reports r JOIN report_voters v ON v.report_id=r.id
               WHERE r.chat_id=? AND v.user_id=?""",
            (HANDLED, DISMISSED, chat_id, user_id))
        ok = (r["ok"] or 0) if r else 0
        no = (r["no"] or 0) if r else 0
        if ok + no < 3:
            return 0.5
        return round(ok / (ok + no), 3)
