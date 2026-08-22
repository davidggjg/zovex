"""טלאי כירורגי ל-main.py החי: מתקן את ההתחלה האיטית של סרט "קר" (~105ש').

הבאג: כשהבריכה המהירה (media-bands) לא מוכנה, הבקשה נפלה למסלול הבוטים —
שלמשיכת זנב (moov בסוף קובץ ענק) נמדד ב-105 שניות (4 בוטים × 25ש' timeout).
התיקון: לבנות את החיבורים המהירים סינכרונית בפעם הראשונה (~5ש') ולהשתמש
במסלול המהיר, שיודע לקפוץ ישר לאופסט הגבוה.

    /opt/zovex-bot/venv/bin/python3 patch_cold_start.py           # דו"ח
    /opt/zovex-bot/venv/bin/python3 patch_cold_start.py --apply   # מחיל
"""
import argparse
import py_compile
import shutil
import time
from pathlib import Path

TARGET = Path("/opt/zovex-bot/main.py")

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

OLD = '''        sessions, gen = await get_media_session_pool_gen(
            bot["client"], bot["name"], dc_id, STREAM_MEDIA_CONNS, block=False)
        if not sessions:
            return None            # עוד נבנית ברקע — מגישים במסלול הבוטים'''

NEW = '''        sessions, gen = await get_media_session_pool_gen(
            bot["client"], bot["name"], dc_id, STREAM_MEDIA_CONNS, block=False)
        if not sessions:
            # קר: הבריכה עוד לא מוכנה. הגרסה הקודמת נפלה כאן למסלול הבוטים —
            # אבל למשיכת *זנב* (moov בסוף קובץ ענק) המסלול הזה נמדד ב-105 שניות
            # (4 בוטים × 25ש' timeout). לכן בונים את החיבורים המהירים כאן ועכשיו
            # (~5ש') ומשתמשים במסלול המהיר, שיודע לקפוץ ישר לאופסט הגבוה.
            sessions, gen = await get_media_session_pool_gen(
                bot["client"], bot["name"], dc_id, STREAM_MEDIA_CONNS, block=True)
        if not sessions:
            return None            # גם הבנייה נכשלה — נופלים למסלול הבוטים'''


def main():
    if not TARGET.exists():
        print(f"❌ לא נמצא {TARGET}")
        return 1
    src = TARGET.read_text(encoding="utf-8")

    if "גם הבנייה נכשלה" in src or "block=True)\n        if not sessions:\n            return None" in src:
        print("✅ הטלאי כבר מוחל. אין מה לעשות.")
        return 0
    if OLD not in src:
        print("❌ לא נמצא הקטע המדויק (ה-main.py החי שונה).")
        print("   שלח לי:  grep -n 'block=False' /opt/zovex-bot/main.py")
        return 1

    print("נמצא העוגן. הטלאי יבנה את החיבורים המהירים סינכרונית במקרה קר.")
    if not args.apply:
        print("\nהרצה יבשה — לא שונה כלום. להחלה: --apply")
        return 0

    patched = src.replace(OLD, NEW, 1)
    backup = TARGET.with_suffix(f".py.bak.{int(time.time())}")
    shutil.copy2(TARGET, backup)
    TARGET.write_text(patched, encoding="utf-8")
    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(backup, TARGET)
        print(f"❌ קומפילציה נכשלה — שוחזר. שגיאה:\n{e}")
        return 1
    print(f"✅ הוחל. גיבוי: {backup.name}")
    print("   להפעלה: systemctl restart zovex-bot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
