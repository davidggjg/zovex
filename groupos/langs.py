#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lang — תרגום מלא לכל שפה, קובץ לשפה.

## למה תיקייה ולא עוד מילון ב-‎locales.py‎

‎locales.EXTRA‎ נבנה לכיסוי חלקי: ‎CORE‎ בלבד, והשאר נופל לאנגלית
ביודעין. הדרישה השתנתה — "מי שבוחר שפה יקבל 100% בשפה הזאת" — וכיסוי
מלא הוא כ-900 מחרוזות לכל שפה. תשע מאות שורות כפול שמונה שפות בקובץ
אחד הוא קובץ שאי אפשר לפתוח, ושינוי קטן בו מייצר הבדל ענק.

קובץ לשפה: מי שמתקן ניסוח ברוסית נוגע ב-‎ru.py‎ ותו לא, והקובץ שלו
נקרא לבד. ‎merge‎ מחבר הכול למבנה שה-‎i18n‎ כבר מכיר, ולכן המנגנון
עצמו לא השתנה.

## מה נבדק אוטומטית

‎test_locales‎ דורש משלוש בדיקות לעבור לכל שפה: כיסוי מלא מול
אנגלית, **אותם מצייני מקום** בדיוק (‎{name}‎, ‎{n}‎), ואותם תגי HTML.
מציין מקום שאבד בתרגום אינו שגיאת ניסוח — הוא הודעה שבורה אצל
המשתמש, ולכן הוא נכשל בבדיקה ולא מתגלה בשטח.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil

#: שפות שיש להן קובץ תרגום מלא בתיקייה הזאת
FULL: tuple[str, ...] = ("ar", "ru", "es", "pt", "fr", "de", "tr", "id")


def merge(extra: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    """מוסיף על ‎EXTRA‎ את מה שיש בקבצי השפה. הקובץ גובר.

    הקובץ גובר בכוונה: ‎EXTRA‎ הוא הכיסוי הישן והחלקי, והקובץ המלא
    הוא מה שנכתב אחריו ובמתכוון."""
    for name in FULL:
        try:
            mod = importlib.import_module(f"lang_{name}")
        except ImportError as e:
            # **לא בשקט.** קובץ שפה שלא נטען פירושו ממשק שחוזר
            # לאנגלית, וזה נראה בדיוק כמו "לא תרגמנו עדיין" — כך
            # נעלמת תקלת התקנה אמיתית. פעם אחת ליד עליית השירות.
            logging.getLogger("groupos").warning(
                "קובץ שפה lang_%s לא נטען: %s", name, e)
            continue
        table = getattr(mod, "STRINGS", None)
        if not isinstance(table, dict):
            logging.getLogger("groupos").warning(
                "lang_%s קיים אבל אין בו STRINGS", name)
            continue
        extra.setdefault(name, {}).update(table)
    return extra
