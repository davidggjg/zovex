#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""disabling — כיבוי פקודות בקבוצה מסוימת.

## למה זה קיים ב-Rose וצריך להיות גם כאן

קבוצה של אלף איש שבה כל אחד יכול לכתוב ‎/rules‎ מתמלאת ב-‎/rules‎.
לפעמים רוצים שפקודה תעבוד רק למנהלים, ולפעמים שלא תעבוד כלל.

## מה **אסור** לכבות

פקודות שהן הדרך חזרה: ‎/start‎, ‎/help‎ ו-‎/settings‎. קבוצה שכיבתה את
‎/settings‎ בטעות הייתה נשארת בלי דרך להדליק אותו בחזרה — וזה סוג
התקלה שאין ממנה יציאה מלבד להסיר את הבוט.

## שתי רמות

    disabled      הפקודה לא עובדת לאף אחד מלבד מנהלים
    deleted       מי שכתב אותה — ההודעה שלו נמחקת

מנהלים תמיד פטורים. פקודה שמנהל אינו יכול להריץ אינה "מכובה", היא
שבורה.
"""
from __future__ import annotations

from typing import Iterable

# הדרך חזרה. אלה לעולם לא ניתנות לכיבוי.
PROTECTED = frozenset({"start", "help", "settings", "enable", "disabled"})

KEY = "disabled_cmds"
DEL_KEY = "disabled_del"


def _load(db, chat_id: int, key: str) -> set[str]:
    raw = db.get(chat_id, key, "") or ""
    return {c for c in raw.replace(",", " ").split() if c}


def _save(db, chat_id: int, key: str, names: Iterable[str],
          by=None) -> None:
    db.set(chat_id, key, ",".join(sorted(set(names))), by)


def disabled(db, chat_id: int) -> set[str]:
    return _load(db, chat_id, KEY)


def disable(db, chat_id: int, name: str, by=None) -> bool:
    name = (name or "").strip().lstrip("/").lower()
    if not name or name in PROTECTED:
        return False
    cur = disabled(db, chat_id)
    cur.add(name)
    _save(db, chat_id, KEY, cur, by)
    return True


def enable(db, chat_id: int, name: str, by=None) -> bool:
    name = (name or "").strip().lstrip("/").lower()
    cur = disabled(db, chat_id)
    if name == "all":
        _save(db, chat_id, KEY, (), by)
        return True
    if name not in cur:
        return False
    cur.discard(name)
    _save(db, chat_id, KEY, cur, by)
    return True


def is_disabled(db, chat_id: int, name: str) -> bool:
    return (name or "").lower() in disabled(db, chat_id)


def delete_mode(db, chat_id: int) -> bool:
    """האם למחוק את ההודעה של מי שכתב פקודה מכובה."""
    return db.get(chat_id, DEL_KEY, "0") == "1"
