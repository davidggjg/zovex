#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""allowlist — החרגות. מי ומה פטור מהכללים.

## למה זה נחוץ

נעילת קישורים בלי החרגות היא נעילה שמכבים אחרי יום. תמיד יש דומיין
אחד שמותר — אתר הקהילה, ערוץ ההודעות, טופס ההרשמה — ותמיד יש משתמש
אחד שצריך לשלוח אותו.

## שלושה תחומים

    user      מזהה משתמש שפטור מנעילות, מחסימות ומהצפה
    domain    דומיין שמותר גם כשקישורים נעולים
    bot       בוט שמותר גם כשבוטים נעולים

## מה שלא נמצא כאן

החרגה לפי תפקיד אינה כאן — היא כבר קיימת ב-‎permissions‎: מנהל ומנחה
פטורים מהכול ממילא. שכפול הכלל הזה לכאן היה יוצר שני מקומות שקובעים
אותו דבר, ואחד מהם היה נשכח.
"""
from __future__ import annotations

SCOPES = ("user", "domain", "bot")


class Allowlist:
    def __init__(self, db):
        self.db = db

    def add(self, chat_id: int, scope: str, value: str) -> bool:
        value = (value or "").strip().lower().lstrip("@")
        if scope not in SCOPES or not value:
            return False
        if scope == "domain":
            value = value.replace("https://", "").replace("http://", "")
            value = value.split("/")[0].lstrip(".")
        self.db.run("""INSERT INTO allowlist (chat_id,scope,value)
                       VALUES (?,?,?)
                       ON CONFLICT (chat_id,scope,value) DO NOTHING""",
                    (chat_id, scope, value))
        return True

    def remove(self, chat_id: int, scope: str, value: str) -> int:
        return self.db.change(
            "DELETE FROM allowlist WHERE chat_id=? AND scope=? AND value=?",
            (chat_id, scope, (value or "").strip().lower().lstrip("@")))

    def all(self, chat_id: int) -> list[tuple[str, str]]:
        return [(r["scope"], r["value"]) for r in self.db.q(
            "SELECT scope,value FROM allowlist WHERE chat_id=? ORDER BY scope,value",
            (chat_id,))]

    def values(self, chat_id: int, scope: str) -> set[str]:
        return {r["value"] for r in self.db.q(
            "SELECT value FROM allowlist WHERE chat_id=? AND scope=?",
            (chat_id, scope))}

    def has_user(self, chat_id: int, user_id: int) -> bool:
        return str(user_id) in self.values(chat_id, "user")

    def domains_ok(self, chat_id: int, found: set[str]) -> bool:
        """האם **כל** הדומיינים בהודעה מותרים.

        'כל' ולא 'לפחות אחד': הודעה עם קישור מותר וקישור אסום היא
        הודעה עם קישור אסור. אחרת ההחרגה הופכת לדרך לעקוף את הנעילה."""
        if not found:
            return False
        ok = self.values(chat_id, "domain")
        if not ok:
            return False
        return all(any(d == a or d.endswith("." + a) for a in ok) for d in found)
