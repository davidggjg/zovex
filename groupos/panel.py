#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""panel — מסכי הניהול בצ'אט הפרטי.

## הבקשה שמאחורי המודול

"אני לא אוהב שצריך לשלוח פקודות בתוך הקבוצה בשביל לנעול אותה."

צודק. Rose בנויה סביב פקודות, וזה מציף את הקבוצה בהודעות ניהול שכל
החברים רואים. כאן: הניהול בפרטי, והקבוצה נשארת נקייה.

## למה המודול הזה לא מכיר את aiogram

כל מסך מחזיר ‎Screen(text, rows)‎ — טקסט ורשימת שורות כפתורים כנתונים
פשוטים. המתאם הופך אותם למקלדת של טלגרם. כך אפשר לבדוק את כל עץ
הניווט בלי בוט: שכל כפתור מוביל למסך קיים, שאין מסך ללא חזרה, ושאף
מזהה כפתור אינו חורג מ-64 בייט — המגבלה של טלגרם, שנשברת בשקט.

## מבנה מזהה הכפתור

    g:<chat_id>:<מסך>:<ארגומנט>

‎chat_id‎ נישא בכל לחיצה כי לצ'אט הפרטי אין הקשר של קבוצה. זה גם מה
שמאפשר לנהל עשר קבוצות מאותו חלון בלי "להתחבר" לאחת מהן.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from locks import ACTIONS, GROUPS, LOCK_TYPES
from moderation import format_policy, parse_policy

CB_MAX = 64          # מגבלת טלגרם למזהה כפתור, בבייטים

ACTION_LABEL = {
    "off": "כבוי", "delete": "מחיקה", "warn": "אזהרה", "mute": "השתקה",
    "kick": "הרחקה", "ban": "חסימה", "tmute": "השתקה זמנית",
    "tban": "חסימה זמנית",
}
# מחזור הלחיצות על נעילה. לא כל שמונה הפעולות — ארבע שמכסות כמעט הכול,
# והשאר נגישות מהמסך המפורט. תפריט עם שמונה אפשרויות לכל נעילה הוא
# בדיוק סוג העומס שהפאנל הזה נועד למנוע.
CYCLE = ("off", "delete", "warn", "mute", "ban")


@dataclass
class Screen:
    text: str
    rows: list[list[tuple[str, str]]] = field(default_factory=list)

    def all_callbacks(self) -> list[str]:
        return [cb for row in self.rows for _, cb in row]


def cb(chat_id: int, screen: str, arg: str = "") -> str:
    s = f"g:{chat_id}:{screen}" + (f":{arg}" if arg else "")
    if len(s.encode()) > CB_MAX:
        raise ValueError(f"מזהה כפתור ארוך מדי ({len(s.encode())}): {s}")
    return s


def parse_cb(data: str) -> Optional[tuple[int, str, str]]:
    parts = data.split(":", 3)
    if len(parts) < 3 or parts[0] != "g":
        return None
    try:
        chat_id = int(parts[1])
    except ValueError:
        return None
    return chat_id, parts[2], (parts[3] if len(parts) > 3 else "")


# ── המסכים ────────────────────────────────────────────────────────────────
def home(groups: list[tuple[int, str]]) -> Screen:
    """רשימת הקבוצות שהמשתמש מנהל."""
    if not groups:
        return Screen(
            "<b>GroupOS</b>\n\n"
            "עוד לא ראיתי אותך מנהל באף קבוצה.\n\n"
            "הוסף אותי לקבוצה, תן לי הרשאות ניהול, ושלח שם הודעה אחת — "
            "ואז חזור לכאן.")
    rows = [[(f"👥 {title[:28]}", cb(cid, "main"))] for cid, title in groups]
    return Screen(
        f"<b>GroupOS</b>\n\nהקבוצות שלך ({len(groups)}):\n"
        "בחר קבוצה כדי לנהל אותה מכאן, בלי לשלוח פקודות בקבוצה עצמה.",
        rows)


def main_menu(chat_id: int, title: str, stats: dict) -> Screen:
    txt = (f"<b>{title}</b>\n\n"
           f"חברים במעקב: {stats.get('members', 0)}\n"
           f"נעילות פעילות: {stats.get('locks', 0)}\n"
           f"אזהרות פתוחות: {stats.get('warns', 0)}\n"
           f"פעולות היום: {stats.get('actions_today', 0)}")
    rows = [
        [("🔒 נעילות", cb(chat_id, "locks")),
         ("⚠️ אזהרות", cb(chat_id, "warns"))],
        [("📋 יומן", cb(chat_id, "audit")),
         ("⚙️ הגדרות", cb(chat_id, "settings"))],
        [("↩︎ לרשימת הקבוצות", "g:0:home")],
    ]
    return Screen(txt, rows)


def locks_groups(chat_id: int, counts: dict[str, int]) -> Screen:
    txt = ("<b>נעילות</b>\n\n"
           "נעילה קובעת מה מותר לשלוח בקבוצה.\n"
           "לחיצה על סוג מחליפה את הפעולה שלו.")
    rows = [[(f"{g} ({counts.get(g, 0)})", cb(chat_id, "lockg", g))]
            for g in GROUPS]
    rows.append([("↩︎ חזרה", cb(chat_id, "main"))])
    return Screen(txt, rows)


def locks_in_group(chat_id: int, group: str,
                   items: list[tuple[str, str, str]]) -> Screen:
    """items: [(מפתח, שם, פעולה נוכחית)]"""
    txt = (f"<b>נעילות · {group}</b>\n\n"
           "לחיצה מחליפה: כבוי ← מחיקה ← אזהרה ← השתקה ← חסימה")
    rows = []
    for key, label, action in items:
        mark = "🔴" if action != "off" else "⚪"
        suffix = f" · {ACTION_LABEL[action]}" if action != "off" else ""
        rows.append([(f"{mark} {label}{suffix}", cb(chat_id, "lock", key))])
    rows.append([("↩︎ חזרה", cb(chat_id, "locks"))])
    return Screen(txt, rows)


def warns_screen(chat_id: int, policy_raw: str, top: list[tuple[int, str, int]]) -> Screen:
    pol = parse_policy(policy_raw)
    txt = ("<b>אזהרות</b>\n\n"
           f"המדיניות בקבוצה:\n{format_policy(pol) or 'אין מדיניות'}\n")
    if top:
        txt += "\nהכי הרבה אזהרות פתוחות:\n" + "\n".join(
            f"• {name} — {n}" for _, name, n in top)
    rows = [
        [("3 · 5 · 7", cb(chat_id, "wpol", "a")),
         ("2 · 4 · 6", cb(chat_id, "wpol", "b")),
         ("רק אזהרות", cb(chat_id, "wpol", "c"))],
        [("↩︎ חזרה", cb(chat_id, "main"))],
    ]
    return Screen(txt, rows)


WARN_PRESETS = {
    "a": "3:mute:3600,5:mute:86400,7:ban:0",
    "b": "2:mute:1800,4:mute:86400,6:ban:0",
    "c": "",
}


def audit_screen(chat_id: int, rows_data: list[dict], fmt_time) -> Screen:
    if not rows_data:
        txt = "<b>יומן</b>\n\nאין עדיין פעולות."
    else:
        txt = "<b>יומן · עשר אחרונות</b>\n\n" + "\n".join(
            f"<code>{fmt_time(r['ts'])}</code> {r['action']}"
            + (f" ← {r['target_id']}" if r["target_id"] else "")
            for r in rows_data)
    return Screen(txt, [[("↩︎ חזרה", cb(chat_id, "main"))]])


def settings_screen(chat_id: int, current: dict) -> Screen:
    clean = current.get("autoclean", "30")
    silent = current.get("silent", "1") == "1"
    txt = ("<b>הגדרות</b>\n\n"
           "<b>ניקוי אוטומטי</b> — אחרי כמה שניות למחוק את הפקודה ואת "
           "התשובה של הבוט מהקבוצה. זה מה ששומר על הקבוצה נקייה.\n\n"
           "<b>מצב שקט</b> — כשהוא פעיל, פעולה אוטומטית מוחקת בלי להודיע "
           "בקבוצה. הכל נרשם ביומן.")
    rows = [
        [("ניקוי: " + (f"{clean} שניות" if clean != "0" else "כבוי"),
          cb(chat_id, "clean"))],
        [("מצב שקט: " + ("פעיל" if silent else "כבוי"), cb(chat_id, "silent"))],
        [("↩︎ חזרה", cb(chat_id, "main"))],
    ]
    return Screen(txt, rows)


CLEAN_CYCLE = ("0", "10", "30", "60", "300")


def next_in_cycle(cycle: tuple, current: str) -> str:
    try:
        return cycle[(cycle.index(current) + 1) % len(cycle)]
    except ValueError:
        return cycle[0]
