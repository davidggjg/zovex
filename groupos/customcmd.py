#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""customcmd — פקודות שהמנהל מגדיר, ‎/<שם>‎ עם תשובה משלו.

## למה זה לא filters

‎filters‎ מגיב למילה שמופיעה בתוך הודעה. פקודה היא **קריאה מפורשת**:
מי שכותב ‎/rules‎ ביקש את החוקים, ומי שכתב "מה החוקים כאן" לא בהכרח.
שתי מערכות ולא שדה נוסף, כי ההתנגשויות שלהן שונות לגמרי — פקודה
מתנגשת עם פקודות המערכת, ופילטר מתנגש עם טקסט חופשי.

## ולמה זה לא Notes — כאן ההפרדה דקה, ולכן נאמרת במפורש

צורת הנתונים כמעט זהה: טקסט, אולי מדיה, אולי כפתורים, פר-קבוצה. מה
שמפריד הוא **מרחב השמות**. ל-‎#שם‎ אין מרחב שמות של מערכת, ולכן הערה לא
יכולה לדרוס דבר. ל-‎/שם‎ יש, וזו כל הסיבה שהמודול הזה קיים בנפרד: הוא
מחזיק את ההגנה שלמטה. בנוסף ‎/‎ מופיע בהשלמה האוטומטית של טלגרם —
פקודה של הקבוצה נגלית למי שלא ידע שהיא קיימת, והערה לא.

## ההגנה שאי אפשר לדלג עליה

פקודה מותאמת שנקראת ‎ban‎ הייתה מחליפה את ‎/ban‎, וזו לא "התנגשות
מוזרה" אלא **השתלטות**: כל מי שיכול להגדיר פקודה היה יכול לנטרל את
האכיפה, או גרוע מזה — לגרום ל-‎/ban‎ להחזיר טקסט ידידותי בזמן שאף
אחד לא נחסם.

לכן ‎RESERVED‎ נגזר מ-‎panel.COMMANDS‎ ולא נכתב ביד. רשימה שנכתבת ביד
מתיישנת בפקודה הבאה שנוסיף, ואף אחד לא שם לב עד שמישהו משתלט על
אותה פקודה. הבדיקה מאמתת שהגזירה אכן קורית, ולא רק שהרשימה קיימת.

## שמות

אותיות, ספרות וקו תחתון, 2–32 תווים, ללא תלות ברישיות. טלגרם עצמה
מגבילה פקודות לזה, ושם עם רווח או עם אמוג'י פשוט לא היה נקרא לעולם —
כלומר פקודה שנוצרת ולא עובדת, וזה גרוע משגיאה.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional

NAME_RE = re.compile(r"^[a-z0-9_]{2,32}$")
CONTENT_MAX = 4000        # מתחת לתקרת ההודעה של טלגרם, עם מרווח לתגיות
MAX_PER_CHAT = 200        # תקרה לקבוצה, כדי שהעזרה לא תהפוך לבלתי קריאה


def _reserved() -> frozenset:
    """שמות שאסור לתפוס — נגזר מפקודות המערכת בזמן ריצה.

    ייבוא מקומי ולא ברמת המודול: ‎panel‎ מייבא ‎i18n‎, וייבוא מעגלי
    כאן היה שובר את שניהם. הנזק מייבוא בתוך פונקציה הוא אפסי, כי היא
    נקראת רק בהגדרת פקודה — לא בכל הודעה.
    """
    try:
        import panel
        return frozenset(n.lower() for n, _ in panel.COMMANDS)
    except Exception:
        # אם הגזירה נכשלה — עדיף לחסום את הכל מלאפשר השתלטות בשקט.
        return frozenset()


def normalize(name: str) -> str:
    return (name or "").strip().lstrip("/").split("@")[0].lower()


def check_name(name: str) -> Optional[str]:
    """‎None‎ = תקין. אחרת מפתח שגיאה ל-i18n."""
    n = normalize(name)
    if not NAME_RE.match(n):
        return "cc.bad_name"
    if n in _reserved():
        return "cc.reserved"
    return None


@dataclass(frozen=True)
class Cmd:
    chat_id: int
    name: str
    content: str
    media_id: Optional[str]
    media_kind: Optional[str]
    buttons: Optional[str]
    admin_only: bool
    uses: int
    created_by: Optional[int]
    created_at: float


def _row(r) -> Cmd:
    return Cmd(r["chat_id"], r["name"], r["content"], r["media_id"],
               r["media_kind"], r["buttons"], bool(r["admin_only"]),
               r["uses"], r["created_by"], r["created_at"])


class CustomCmds:
    def __init__(self, db):
        self.db = db

    def set(self, chat_id: int, name: str, content: str,
            by: Optional[int] = None, buttons: Optional[str] = None,
            admin_only: bool = False, media_id: Optional[str] = None,
            media_kind: Optional[str] = None,
            now: Optional[float] = None) -> tuple[Optional[Cmd], Optional[str]]:
        """מוסיף או מעדכן. מחזיר ‎(פקודה, שגיאה)‎ — אחד מהם ‎None‎."""
        n = normalize(name)
        err = check_name(n)
        if err:
            return None, err
        content = (content or "").strip()
        # תמונה בלי כיתוב היא פקודה שלמה. הדרישה לתוכן היא דרישה
        # ל**משהו** שיישלח, ולא דווקא לטקסט.
        if not content and not media_id:
            return None, "cc.empty"
        if len(content) > CONTENT_MAX:
            return None, "cc.too_long"
        if self.count(chat_id) >= MAX_PER_CHAT and not self.get(chat_id, n):
            return None, "cc.too_many"
        t = now if now is not None else time.time()
        # שמירה על uses בעדכון: מנהל שמתקן ניסוח אינו מאפס את המונה.
        self.db.run(
            """INSERT INTO custom_cmds
               (chat_id,name,content,media_id,media_kind,buttons,admin_only,
                created_by,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(chat_id,name) DO UPDATE SET
                 content=excluded.content, media_id=excluded.media_id,
                 media_kind=excluded.media_kind, buttons=excluded.buttons,
                 admin_only=excluded.admin_only""",
            (chat_id, n, content, media_id, media_kind, buttons,
             1 if admin_only else 0, by, t))
        return self.get(chat_id, n), None

    def get(self, chat_id: int, name: str) -> Optional[Cmd]:
        r = self.db.one("SELECT * FROM custom_cmds WHERE chat_id=? AND name=?",
                        (chat_id, normalize(name)))
        return _row(r) if r else None

    def delete(self, chat_id: int, name: str) -> bool:
        return self.db.change(
            "DELETE FROM custom_cmds WHERE chat_id=? AND name=?",
            (chat_id, normalize(name))) > 0

    def list(self, chat_id: int) -> list[Cmd]:
        return [_row(r) for r in self.db.q(
            "SELECT * FROM custom_cmds WHERE chat_id=? ORDER BY name",
            (chat_id,))]

    def names(self, chat_id: int) -> list[str]:
        return [r["name"] for r in self.db.q(
            "SELECT name FROM custom_cmds WHERE chat_id=? ORDER BY name",
            (chat_id,))]

    def count(self, chat_id: int) -> int:
        r = self.db.one("SELECT COUNT(*) c FROM custom_cmds WHERE chat_id=?",
                        (chat_id,))
        return r["c"] if r else 0

    def bump(self, chat_id: int, name: str) -> None:
        self.db.run("""UPDATE custom_cmds SET uses = uses + 1
                       WHERE chat_id=? AND name=?""",
                    (chat_id, normalize(name)))

    def resolve(self, chat_id: int, text: str) -> Optional[Cmd]:
        """מחזיר פקודה מותאמת עבור טקסט הודעה, או ‎None‎.

        קורא רק את המילה הראשונה, ורק אם היא מתחילה ב-‎/‎. ‎/rules@BotName‎
        נחשב ‎rules‎, כי כך טלגרם שולחת פקודה בקבוצה שיש בה כמה בוטים —
        ובלי הקילוף הזה הפקודה פשוט לא הייתה נמצאת שם.
        """
        if not text:
            return None
        first = text.split(None, 1)[0]
        if not first.startswith("/"):
            return None
        n = normalize(first)
        if not n or n in _reserved():
            return None
        return self.get(chat_id, n)
