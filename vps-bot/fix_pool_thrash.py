#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_pool_thrash — עוצר את סחרור בניית הסשנים מול טלגרם.

## מה נמדד, ולא מה שיערתי

catch_slow_open תפס את היומן **בדיוק בזמן** שפתיחות נתקעו. ב-7 שניות:

    258×  Connected! Production DC (media)
    250×  Connecting...
    233×  Disconnected
    231×  Session stopped

כ-35 סשנים של טלגרם נפתחים ונסגרים **בכל שנייה**. הבריכות אמורות לחיות
30 דקות (MEDIA_SESSION_TTL=1800) ובפועל נבנות מחדש בלי הפסקה.

השרשרת מופיעה ביומן במלואה:

    חלון ... נכשל: TimeoutError
    media bands (bot_6) 3 timeouts רצופים — מרענן חיבורים
    media pool ל-bot_12 רוענן (4 חיבורים טריים)
    Close exception: ConnectionResetError [Errno 104] Connection reset by peer

## למה זו לולאה שמזינה את עצמה

חלון עושה timeout ← הבריכה מופלת ← נבנים 4 חיבורים ← טלגרם מאפס חיבורים
(Connection reset by peer) כי נפתחים יותר מדי ← עוד timeouts ← עוד הפלות.

הסף להפלה הוא `BAND_TIMEOUT_LIMIT=2` בחלון של 600 שניות — כלומר **שני**
timeouts בעשר דקות מפילים בריכה שלמה. תחת עומס זה רעש רגיל, לא עדות
למוות. עם 21 בוטים על 2 מרכזי נתונים יש 42 בריכות, וכל אחת מהן יכולה
להיכנס לזה בנפרד. אין שום מעצור על **קצב** הבנייה מחדש, ולכן ברגע
שמתחילים — זה רק מתגבר.

זה מסביר כל תסמין: מתחיל קטן ומתגבר (הלולאה מזינה את עצמה), ריסט מאפס
(בריכות טריות), שישי (יותר צופים ← יותר חלונות ← חוצה את הסף), הפתיחה
איטית אבל ההזרמה תקינה (הבריכה נהרסת מתחת לבקשה), ו-CPU במנוחה (הכל
המתנה לרשת).

## התיקון

תקרה על קצב ההפלה לכל (בוט, DC): אחרי הפלה, אותה בריכה לא תופל שוב
במשך POOL_DROP_COOLDOWN שניות (ברירת מחדל 120).

הנימוק הוא לא "פחות הפלות זה טוב" אלא סיבתי: אם בריכה נבנתה זה עתה
ועדיין יש timeouts, הבעיה **אינה** החיבורים שלנו — הם טריים. בנייה נוספת
לא יכולה לעזור, והיא כן מוסיפה עוד חיבורים למה שכבר מציף את טלגרם. מי
שחוסם את עצמו לא נרפא בכך שינסה חזק יותר.

בריכה שבאמת מתה עדיין מתרפאת — תוך שתי דקות לכל היותר, במקום מיידית
ובמחיר סחרור. 42 בריכות × הפלה אחת ל-120 שניות = לכל היותר 0.35 בנייה
בשנייה, מול 35 שנמדדו. פי 100 פחות.

הנתון נשאר מדיד: כל דילוג נרשם ליומן, כך שאפשר לראות כמה סחרור נמנע.

    python3 fix_pool_thrash.py --check
    python3 fix_pool_thrash.py
    python3 fix_pool_thrash.py --revert
ואחריו:  systemctl restart zovex-bot
"""
import argparse, ast, os, shutil, sys
from pathlib import Path

MAIN = Path(os.environ.get("ZOVEX_MAIN", "/opt/zovex-bot/main.py"))
BAK = MAIN.with_name(MAIN.name + ".bak_poolthrash")
MARK = "_pool_dropped_at"

OLD_DECL = "_media_building: set = set()\n"
NEW_DECL = '''_media_building: set = set()

# ── תקרה על קצב הפלת בריכות ──────────────────────────────────────────────────
# נמדד ביומן: 250 חיבורי טלגרם נפתחו ונסגרו ב-7 שניות, בזמן שבריכה אמורה
# לחיות 30 דקות. הסיבה היא לולאת משוב — timeout מפיל בריכה, ההפלה בונה
# חיבורים חדשים, טלגרם מאפס אותם (Connection reset by peer), וזה מייצר עוד
# timeouts. הסף להפלה הוא שני timeouts בעשר דקות, שתחת עומס הוא רעש רגיל.
#
# אם בריכה נבנתה זה עתה ועדיין יש timeouts, הבעיה אינה החיבורים שלנו — הם
# טריים — ובנייה נוספת רק מוסיפה למה שכבר מציף. בריכה מתה באמת עדיין
# מתרפאת, לכל היותר אחרי הזמן הזה.
_pool_dropped_at: dict = {}          # (bot, dc) -> מתי הופלה לאחרונה
POOL_DROP_COOLDOWN = int(os.environ.get("POOL_DROP_COOLDOWN", "120"))
_pool_drop_skipped = 0               # נמדד, כדי לדעת כמה סחרור נמנע
'''

OLD_BODY = '''    key = (owner, dc_id)
    async with _media_lock(key):
        ent = _media_sessions.get(key)
        if ent is None or (gen is not None and ent["gen"] != gen):
            return
        _media_sessions.pop(key, None)
    asyncio.create_task(_retire_pool(ent["pool"]))
'''

NEW_BODY = '''    global _pool_drop_skipped
    key = (owner, dc_id)
    # ראה fix_pool_thrash.py: בריכה שהופלה לפני רגע לא תופל שוב. בנייה
    # חוזרת על חיבורים טריים לא יכולה לתקן כלום, והיא המנוע של הסחרור.
    _since = time.time() - _pool_dropped_at.get(key, 0.0)
    if _since < POOL_DROP_COOLDOWN:
        _pool_drop_skipped += 1
        if _pool_drop_skipped % 20 == 1:
            log.warning("בריכה %s/%s הופלה לפני %.0fש — מדלג על הפלה נוספת "
                        "(נמנעו %d עד כה)", owner, dc_id, _since,
                        _pool_drop_skipped)
        return
    async with _media_lock(key):
        ent = _media_sessions.get(key)
        if ent is None or (gen is not None and ent["gen"] != gen):
            return
        _media_sessions.pop(key, None)
    _pool_dropped_at[key] = time.time()
    asyncio.create_task(_retire_pool(ent["pool"]))
'''


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def validate(src: str, patched: bool = True) -> None:
    """חייב להתקמפל, ו-drop_media_sessions חייבת לשרוד. ב-revert משחזרים
    מקור שאין בו את הסימון, ולכן שם בודקים רק קומפילציה ושמות."""
    compile(src, str(MAIN), "exec")
    names = [n.name for n in ast.walk(ast.parse(src))
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if "drop_media_sessions" not in names:
        sys.exit("אימות נכשל: drop_media_sessions נעלמה — לא כותב.")
    if not patched:
        return
    for needle in ("_pool_dropped_at", "POOL_DROP_COOLDOWN", "_pool_drop_skipped"):
        if needle not in src:
            sys.exit(f"אימות נכשל: {needle} לא נמצא — לא כותב.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    if not MAIN.exists():
        sys.exit(f"לא נמצא {MAIN}. הגדר ZOVEX_MAIN אם הנתיב שונה.")
    src = MAIN.read_text(encoding="utf-8")

    if a.revert:
        if not BAK.exists():
            sys.exit(f"אין גיבוי ב-{BAK}")
        orig = BAK.read_text(encoding="utf-8")
        validate(orig, patched=False)
        atomic_write(MAIN, orig)
        print(f"✓ שוחזר מ-{BAK} (בית-בית)")
        print("  הרץ: systemctl restart zovex-bot")
        return

    if MARK in src:
        print("כבר מותקן. אין מה לעשות.")
        return

    # time ו-log נדרשים להזרקה. בודקים ולא מניחים.
    for needle in ("import time", "log ="):
        if needle not in src:
            sys.exit(f"לא מצאתי '{needle}' ב-main.py — ההזרקה תלויה בו, לא כותב.")

    for label, old in (("הצהרת המשתנים", OLD_DECL), ("גוף drop_media_sessions", OLD_BODY)):
        n = src.count(old)
        if n != 1:
            sys.exit(f"העוגן '{label}' נמצא {n} פעמים (ציפיתי 1) — "
                     "הקוד בשרת שונה ממה שציפיתי. לא כותב.")

    new = src.replace(OLD_DECL, NEW_DECL, 1).replace(OLD_BODY, NEW_BODY, 1)
    validate(new)

    print("תקרה: הפלת בריכה אחת לכל היותר כל "
          f"{os.environ.get('POOL_DROP_COOLDOWN', '120')} שניות לכל (בוט, DC)")
    print("נמדד לפני התיקון: ~35 סשנים נפתחים ונסגרים בשנייה")
    print("צפוי אחרי: לכל היותר ~0.35 בשנייה (42 בריכות / 120ש)")
    if a.check:
        print("--check: שום דבר לא נכתב. היעד:", MAIN)
        return

    shutil.copy2(MAIN, BAK)
    atomic_write(MAIN, new)
    if MARK not in MAIN.read_text(encoding="utf-8"):
        shutil.copy2(BAK, MAIN)
        sys.exit("הכתיבה לא אומתה — שוחזר.")
    print(f"✓ הוחל · גיבוי: {BAK}")
    print("  הרץ עכשיו: systemctl restart zovex-bot")
    print("  לביטול:    python3 fix_pool_thrash.py --revert")
    print()
    print("  לאימות אחרי כמה דקות — אמור לרדת דרמטית:")
    print("    journalctl -u zovex-bot --since '5 min ago' | grep -c Connecting")


if __name__ == "__main__":
    main()
