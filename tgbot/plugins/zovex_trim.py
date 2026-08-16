"""גוזם את פאנל העזרה של LEX — משאיר רק את המודולים שצריך לקבוצת סרטים.

למה ככה ולא מוחקים פלאגינים
---------------------------
הפאנל מחובר לפלאגינים; מחיקת קובץ פלאגין עלולה לשבור ייבוא. במקום זה עורכים
רק את הרשימה המרכזית `HELP_CATEGORIES` בזמן ריצה — הכפתורים המיותרים נעלמים
מהפאנל, הפלאגינים נשארים טעונים (קלים, לא מזיקים), ושום דבר לא נשבר.
להוסיף/להסיר מודול = לשנות את KEEP כאן ולבנות מחדש. הפיך לגמרי.
"""
from loguru import logger

from src.core.plugin import Plugin, register

# המודולים שיישארו בפאנל. כל השאר (AI, TTS, תרומות, captcha, פדרציות,
# חיבורים, פילטרים, עיצוב, הערות, דוחות, נושאים וכו') נעלמים מהתצוגה.
KEEP = {
    "about",       # אודות
    "admin",       # ניהול אדמינים
    "bans",        # חסימות/גירוש
    "locks",       # מנעולים — מי יכול לשלוח בקבוצה (מה שביקשת)
    "purges",      # מחיקה מרובה
    "greetings",   # הודעות פתיחה/וֶלקאם
    "rules",       # חוקי הקבוצה
    "languages",   # שפה
    "antiflood",   # הגנת הצפה/ספאם
    "pin",         # הצמדת הודעות
    "impexp",      # גיבוי ושחזור הגדרות
    "misc",        # שונות (מזהה, מידע וכו')
}


class ZovexTrimPlugin(Plugin):
    name = "zovex_trim"
    priority = 999          # רץ אחרון, אחרי ש-help.py כבר נטען

    async def setup(self, client, ctx) -> None:
        try:
            from src.plugins import help as help_mod
            before = len(help_mod.HELP_CATEGORIES)
            help_mod.HELP_CATEGORIES = [
                c for c in help_mod.HELP_CATEGORIES if c[0] in KEEP
            ]
            logger.info(
                f"ZOVEX trim: פאנל צומצם מ-{before} ל-{len(help_mod.HELP_CATEGORIES)} מודולים"
            )
        except Exception as e:
            logger.error(f"ZOVEX trim נכשל (הפאנל נשאר מלא): {e}")


register(ZovexTrimPlugin())
logger.info("ZOVEX Trim Plugin registered.")
