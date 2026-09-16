#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_media_session_leak — בוט שמוקם מחדש משאיר בריכת media מתה שממשיכה לפנג.

מה שנמדד ב-whystuck.py על 30 דקות חיות:

    1,080×  💀 "Send exception: RuntimeError unable to perform operation
            on <TCPTransport closed=True>"   — 16.6% מכל היומן
    36 בדקה, קבוע, לאורך כל חצי השעה
    95×     ffmpeg של ערוץ חי מת → מפעיל מחדש → הנגן קופא

השורש, אחרי מעקב בקוד: pool_health_loop מזהה בוט מת וקורא ל-_revive_bot,
שבונה **לקוח חדש**. אבל בריכות ה-media של הבוט (חיבור פר-DC, ב-
_media_sessions) שייכות ללקוח **הישן** שמת — ו-_revive_bot לא נוגע בהן.
הן נשארות ב-_media_sessions, ומשימת ה-ping של כל אחת ממשיכה לכתוב לשקע
הסגור כל 5 שניות. זה בדיוק מה ש-_force_down מתאר על ה-session הראשי
("משימת ה-ping כותבת לשקע המת... ומייצרת את שורות Send exception"), רק
ששם זה תוקן ובבריכות ה-media לא.

כל סבב בריאות שמרים בוט מוסיף עוד בריכת-זומבי. לאורך שעות מצטברות
עשרות, ומשימות ה-ping שלהן חונקות את לולאת האירועים — מה שמעכב את
הפינג של Pyrogram, מפיל עוד חיבורים, ומרעיב את ffmpeg של הערוצים החיים
(שמוזן מהשרת עצמו). ריסט מנקה את _media_sessions ולכן "מתקן" — עד
שהמחזור מתחיל שוב. זה מסביר גם את התכנים שנתקעים באתר וגם את השידורים.

התיקון: אחרי הרמת בוט מוצלחת, מפילים את כל בריכות ה-media של אותו בוט
דרך drop_media_sessions — פונקציה קיימת ומוכחת, שמוציאה את הבריכה
וקוראת _stop_pool → sess.stop() על כל חיבור, כלומר הורגת את משימת
ה-ping. יש grace (_retire_pool ישן MEDIA_SESSION_GRACE לפני הסגירה),
ולכן משיכה חיה שרצה ברגע ההרמה לא נקטעת — וממילא הבוט הוכרז מת, אז אף
צופה לא מושך ממנו בהצלחה.

    python3 fix_media_session_leak.py --check
    python3 fix_media_session_leak.py
    python3 fix_media_session_leak.py --revert
ואחריו:  systemctl restart zovex-bot
"""
import argparse, ast, os, shutil, sys
from pathlib import Path

MAIN = Path(os.environ.get("ZOVEX_MAIN", "/opt/zovex-bot/main.py"))
BAK = MAIN.with_name(MAIN.name + ".bak_medialeak")
MARK = "# [fix_media_session_leak]"

# העוגן: הניקוי הקיים של _bot_msg_cache ב-_revive_bot, מיד אחרי הרמה
# מוצלחת. מוסיפים אחריו את ניקוי בריכות ה-media של אותו בוט.
ANCHOR = """        for k in [k for k in _bot_msg_cache if k[0] == name]:
            _bot_msg_cache.pop(k, None)
"""

INSERT = """        # """ + MARK + """
        # בריכות ה-media של הבוט שייכות ללקוח שמת — משימות ה-ping שלהן
        # ממשיכות לירות על שקעים סגורים (36 "Send exception" בדקה, נמדד).
        # drop_media_sessions מוציאה ועוצרת כל אחת (sess.stop → הורג ping).
        for _o, _dc in [k for k in list(_media_sessions) if k[0] == name]:
            try:
                await drop_media_sessions(_o, _dc)
            except Exception:
                pass
"""


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True); raise


def validate(src: str) -> None:
    """הקוד חייב להתקמפל, ו-_revive_bot חייבת עדיין להתקיים בדיוק פעם אחת."""
    compile(src, str(MAIN), "exec")
    tree = ast.parse(src)
    names = [n.name for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for need in ("_revive_bot", "drop_media_sessions"):
        if names.count(need) < 1:
            sys.exit(f"אימות נכשל: {need} נעלמה מהקוד — לא כותב.")


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
        validate(orig)
        atomic_write(MAIN, orig)
        print(f"✓ שוחזר מ-{BAK} (בית-בית)")
        print("  הרץ: systemctl restart zovex-bot")
        return

    if MARK in src:
        print("כבר מותקן (המצאתי את הסימון). אין מה לעשות.")
        return

    n = src.count(ANCHOR)
    if n != 1:
        sys.exit(f"עוגן נמצא {n} פעמים (ציפיתי 1) — הקוד השתנה, לא כותב.")

    new_src = src.replace(ANCHOR, ANCHOR + INSERT)
    if new_src == src or MARK not in new_src:
        sys.exit("ההוספה לא נתפסה — לא כותב.")
    validate(new_src)

    added = new_src.count("\n") - src.count("\n")
    print(f"עוגן: 1 · שורות שיתווספו: {added} · הסימון: {MARK}")
    print("─" * 60)
    print(INSERT.rstrip())
    print("─" * 60)
    if a.check:
        print("--check: שום דבר לא נכתב. היעד:", MAIN)
        return

    shutil.copy2(MAIN, BAK)
    atomic_write(MAIN, new_src)
    # אימות שהקובץ הכתוב תקין, אחרת מחזירים מיד
    if MARK not in MAIN.read_text(encoding="utf-8"):
        shutil.copy2(BAK, MAIN)
        sys.exit("הכתיבה לא אומתה — שוחזר. לא נגעתי.")
    print(f"✓ הוחל · גיבוי: {BAK}")
    print("  הרץ עכשיו: systemctl restart zovex-bot")
    print("  לביטול:    python3 fix_media_session_leak.py --revert")


if __name__ == "__main__":
    main()
