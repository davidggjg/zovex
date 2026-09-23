#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""emergency — מצב חירום, ומרכז האבטחה שמציג מה פעיל.

## הבעיה שזה פותר

באמצע פשיטה מנהל לא פותח שבעה מסכים. הוא צריך לחיצה אחת שמפעילה את
הכול, ולחיצה אחת שמחזירה הכול — **בדיוק** למה שהיה לפני.

## למה "בדיוק למה שהיה"

מצב חירום שמשאיר את הקבוצה נעולה אחרי שהוא כבה הוא מצב חירום שמנהלים
מפחדים ללחוץ. לכן לפני ההפעלה נשמר צילום של כל הגדרה שעומדים לשנות,
והכיבוי משחזר ממנו. קבוצה שהייתה עם CAPTCHA פעילה מראש תישאר איתה;
קבוצה שלא — לא.

## הרכב המצב ניתן להגדרה

‎PRESET‎ הוא ברירת המחדל, לא חוק. כל קבוצה יכולה לדרוס כל מפתח דרך
‎settings‎, כי "חירום" בקבוצת תמיכה אינו "חירום" בקבוצת קריפטו.
"""
from __future__ import annotations

import json
from typing import Any

# ההגדרות שמצב חירום נוגע בהן, והערך שהן מקבלות.
PRESET: dict[str, str] = {
    "lockdown":       "0",    # לא משתיק את כולם — זו החלטה נפרדת
    "captcha":        "1",
    "captcha_kind":   "math",
    "antiraid":       "1",
    "flood":          "1",
    "flood_rate":     "4",
    "flood_window":   "10",
    "flood_repeat":   "2",
    "flood_mentions": "3",
    "flood_action":   "mute",
    "silent":         "0",    # בחירום רוצים לראות מה קורה
    "newuser_links":  "1",    # נכנס חדש לא שולח קישורים
}

SNAPSHOT_KEY = "_emergency_before"
STATE_KEY = "emergency"

# מה שמרכז האבטחה מציג. (מפתח הגדרה, ברירת מחדל, מפתח תרגום)
PROTECTIONS = (
    ("captcha",   "0", "sec.captcha"),
    ("flood",     "1", "sec.flood"),
    ("antiraid",  "1", "sec.antiraid"),
    ("reports",   "1", "sec.reports"),
    ("lockdown",  "0", "sec.lockdown"),
    ("emergency", "0", "sec.emergency"),
)


def preset_for(db, chat_id: int) -> dict[str, str]:
    """ההרכב של הקבוצה הזאת: ברירת המחדל עם הדריסות שלה."""
    out = dict(PRESET)
    raw = db.get(chat_id, "emergency_preset", "") or ""
    if raw:
        try:
            custom = json.loads(raw)
            if isinstance(custom, dict):
                out.update({str(k): str(v) for k, v in custom.items()})
        except (ValueError, TypeError):
            pass          # הרכב פגום אינו סיבה לא להפעיל חירום
    return out


def is_on(db, chat_id: int) -> bool:
    return db.get(chat_id, STATE_KEY, "0") == "1"


def enable(db, chat_id: int, by: Any = None) -> dict[str, str]:
    """מפעיל, ומחזיר את מה ששונה. שומר צילום לשחזור."""
    if is_on(db, chat_id):
        return {}
    preset = preset_for(db, chat_id)
    before = {k: (db.get(chat_id, k, None) or "") for k in preset}
    db.set(chat_id, SNAPSHOT_KEY, json.dumps(before), by)
    for k, v in preset.items():
        db.set(chat_id, k, v, by)
    db.set(chat_id, STATE_KEY, "1", by)
    return preset


def disable(db, chat_id: int, by: Any = None) -> bool:
    """מכבה ומשחזר בדיוק את מה שהיה. מפתח שלא היה קיים חוזר להיות לא קיים."""
    if not is_on(db, chat_id):
        return False
    raw = db.get(chat_id, SNAPSHOT_KEY, "") or "{}"
    try:
        before = json.loads(raw)
    except (ValueError, TypeError):
        before = {}
    for k in preset_for(db, chat_id):
        val = before.get(k, "")
        if val == "":
            db.unset(chat_id, k)
        else:
            db.set(chat_id, k, val, by)
    db.unset(chat_id, SNAPSHOT_KEY)
    db.set(chat_id, STATE_KEY, "0", by)
    return True


def status(db, chat_id: int) -> list[tuple[str, bool]]:
    """‎[(מפתח תרגום, פעיל)]‎ — מה מגן על הקבוצה הזאת עכשיו."""
    return [(label, db.get(chat_id, key, default) == "1")
            for key, default, label in PROTECTIONS]
