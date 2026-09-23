#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""permissions — מי רשאי לעשות מה.

## למה זה מודול נפרד ולא ‎if user.is_admin‎

שלושה דברים שנשברים כשההרשאה נבדקת בתוך הפקודה:

  1. **אין דרך לשנות מדיניות בלי לגעת בקוד.** "מנחה יכול להשתיק אבל לא
     לחסום" הופך לעריכה בשלושה קבצים.
  2. **קל לשכוח.** פקודה חדשה שנכתבת בלי הבדיקה היא חור אבטחה שקט.
  3. **אי אפשר להסביר סירוב.** המשתמש מקבל "אין לך הרשאה" בלי לדעת איזו.

לכן: כל פקודה מצהירה איזו הרשאה היא דורשת, ונקודה אחת בודקת.

## ההיררכיה

    owner        בעל הקבוצה. אי אפשר לפגוע בו, והוא לא ניתן להורדה מהבוט.
    super_admin  כל מה שבעלים, חוץ מפעולות הרסניות על עצמו
    admin        ניהול מלא של הקבוצה
    moderator    השתקה, אזהרה, מחיקה — בלי חסימה ובלי שינוי הגדרות
    helper       מחיקה ואזהרה בלבד
    member       כלום

## כלל הדירוג

פעולת ניהול על משתמש אחר מותרת רק כשדירוג המבצע **גבוה** משל היעד.
זה מה שמונע ממנהל להשתיק מנהל אחר, ומונע מהבוט לנסות לחסום את בעל
הקבוצה — פעולה שטלגרם ממילא תדחה, אבל עדיף לדעת את זה לפני הבקשה.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# דירוג. מספר גבוה = סמכות גבוהה. הערכים מרווחים כדי לאפשר תפקידים
# מותאמים ביניהם בלי לשנות את הקיימים.
RANK: dict[str, int] = {
    "member": 0,
    "helper": 20,
    "moderator": 40,
    "bot_manager": 50,
    "admin": 60,
    "super_admin": 80,
    "owner": 100,
}

# ההרשאה הנדרשת לכל פעולה, והדירוג המינימלי שמקבל אותה כברירת מחדל.
# כל קבוצה יכולה לדרוס דרך role_grants בלי לגעת כאן.
PERMISSIONS: dict[str, int] = {
    # מודרציה
    "msg.delete":      RANK["helper"],
    "user.warn":       RANK["helper"],
    "user.unwarn":     RANK["moderator"],
    "user.mute":       RANK["moderator"],
    "user.unmute":     RANK["moderator"],
    "user.kick":       RANK["moderator"],
    "user.ban":        RANK["admin"],
    "user.unban":      RANK["admin"],
    "chat.purge":      RANK["moderator"],
    "chat.pin":        RANK["moderator"],
    # השבתת קבוצה משתיקה את כולם בבת אחת, ולכן היא לא ביד של מנחה
    "chat.lockdown":   RANK["admin"],
    # דיבור בשם הבוט הוא דיבור בשם הקבוצה. ההודעה נראית רשמית, ולכן
    # ההרשאה גבוהה ממחיקה — טעות כאן נראית כמו הודעה של ההנהלה.
    "chat.say":        RANK["admin"],
    # תוכן
    "notes.read":      RANK["member"],
    "notes.write":     RANK["moderator"],
    "filters.write":   RANK["admin"],
    "locks.write":     RANK["admin"],
    "blocklist.write": RANK["admin"],
    "rules.write":     RANK["admin"],
    "welcome.write":   RANK["admin"],
    # מערכת
    "settings.read":   RANK["moderator"],
    "settings.write":  RANK["admin"],
    "roles.assign":    RANK["super_admin"],
    "audit.read":      RANK["admin"],
    "chat.export":     RANK["super_admin"],
    "chat.import":     RANK["owner"],
    "chat.reset":      RANK["owner"],
    "broadcast.send":  RANK["owner"],
    "emergency.toggle": RANK["admin"],
}


@dataclass(frozen=True)
class Decision:
    """תשובה שאפשר להציג למשתמש, לא רק True/False."""
    allowed: bool
    reason: str = ""
    permission: str = ""
    role: str = ""

    def __bool__(self) -> bool:
        return self.allowed


class Permissions:
    def __init__(self, db):
        self.db = db

    # ── תפקיד ──────────────────────────────────────────────────────────────
    def role_of(self, chat_id: int, user_id: int) -> str:
        r = self.db.one("SELECT role FROM members WHERE chat_id=? AND user_id=?",
                        (chat_id, user_id))
        return r["role"] if r else "member"

    def set_role(self, chat_id: int, user_id: int, role: str) -> None:
        if role not in RANK:
            raise ValueError(f"תפקיד לא מוכר: {role}")
        self.db.run("""INSERT INTO members (chat_id,user_id,role,last_msg)
                       VALUES (?,?,?,0)
                       ON CONFLICT (chat_id,user_id) DO UPDATE SET role=excluded.role""",
                    (chat_id, user_id, role))

    def rank_of(self, chat_id: int, user_id: int) -> int:
        return RANK.get(self.role_of(chat_id, user_id), 0)

    # ── הבדיקה ─────────────────────────────────────────────────────────────
    def check(self, chat_id: int, user_id: int, permission: str,
              target_id: Optional[int] = None) -> Decision:
        """האם ‎user_id‎ רשאי לבצע ‎permission‎, ואם יש יעד — גם עליו."""
        if permission not in PERMISSIONS:
            # פקודה שביקשה הרשאה שלא הוגדרה היא באג, ולא סיבה לאשר
            return Decision(False, f"הרשאה לא מוגדרת: {permission}", permission)

        role = self.role_of(chat_id, user_id)
        rank = RANK.get(role, 0)

        # דריסה מפורשת לקבוצה הזאת, אם קיימת
        r = self.db.one("""SELECT allowed FROM role_grants
                           WHERE chat_id=? AND role=? AND permission=?""",
                        (chat_id, role, permission))
        if r is not None:
            if not r["allowed"]:
                return Decision(False, "ההרשאה נשללה מהתפקיד הזה בקבוצה",
                                permission, role)
        elif rank < PERMISSIONS[permission]:
            need = _role_for_rank(PERMISSIONS[permission])
            return Decision(False, f"נדרש {need} ומעלה", permission, role)

        if target_id is not None:
            if target_id == user_id:
                # פעולה על עצמך מותרת רק כשהיא לא ענישה
                if permission.startswith(("user.ban", "user.kick", "user.mute")):
                    return Decision(False, "אי אפשר לבצע את זה על עצמך",
                                    permission, role)
            else:
                t_rank = self.rank_of(chat_id, target_id)
                if t_rank >= rank:
                    return Decision(False, "היעד בדירוג זהה או גבוה משלך",
                                    permission, role)
        return Decision(True, "", permission, role)

    def grant(self, chat_id: int, role: str, permission: str, allowed: bool = True) -> None:
        if permission not in PERMISSIONS:
            raise ValueError(f"הרשאה לא מוכרת: {permission}")
        if role not in RANK:
            raise ValueError(f"תפקיד לא מוכר: {role}")
        self.db.run("""INSERT INTO role_grants (chat_id,role,permission,allowed)
                       VALUES (?,?,?,?)
                       ON CONFLICT (chat_id,role,permission)
                       DO UPDATE SET allowed=excluded.allowed""",
                    (chat_id, role, permission, 1 if allowed else 0))

    def revoke_override(self, chat_id: int, role: str, permission: str) -> None:
        """מסיר דריסה ומחזיר את ברירת המחדל."""
        self.db.run("""DELETE FROM role_grants
                       WHERE chat_id=? AND role=? AND permission=?""",
                    (chat_id, role, permission))

    def list_for(self, chat_id: int, role: str) -> dict[str, bool]:
        """כל ההרשאות של תפקיד בקבוצה — לתצוגה במסך ההרשאות."""
        rank = RANK.get(role, 0)
        out = {p: rank >= need for p, need in PERMISSIONS.items()}
        for r in self.db.q("""SELECT permission,allowed FROM role_grants
                              WHERE chat_id=? AND role=?""", (chat_id, role)):
            out[r["permission"]] = bool(r["allowed"])
        return out


def _role_for_rank(rank: int) -> str:
    """שם התפקיד הנמוך ביותר שמגיע לדירוג — כדי להסביר סירוב בעברית."""
    best = "owner"
    for name, r in sorted(RANK.items(), key=lambda kv: kv[1]):
        if r >= rank:
            best = name
            break
    return best
