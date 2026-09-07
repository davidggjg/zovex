#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מפנה את המשיכה הפנימית של /vh/ אל שרת ה-Go במקום אל הפייתון.

## הבעיה שנמדדה

מקטע HLS של 10 שניות לקח **12 עד 27 שניות** לייצר. הנגן לא יכול לעמוד
בקצב כזה: הוא מקבל את המקטע הראשון, מציג את אורך הסרט, ואז נתקע על 0:00
בהמתנה לשני. זה בדיוק מה שנראה באתר על ונסדיי אחרי החיבור.

## למה

`_vf_local_url` מחזיר `http://127.0.0.1:{PORT}/stream/...` — כלומר כל
מקטע מושך את הבייטים דרך **הפייתון**. נמדד באותו שרת, אותו קובץ, 4MB:

    פייתון (8000)  3.98 שניות
    Go     (8099)  0.73 שניות     ← פי 5.5

הצינור מושך ~6.5MB לכל מקטע, ולכן ההפרש הזה הוא כמעט כל זמן ההמתנה.

## מה משתנה

רק היעד של המשיכה הפנימית. החתימה זהה (`_stream_sig` על אותם
chat/msg/exp), ולכן הקישור עובר כמו שהוא — נבדק בייצור: אותו md5 בדיוק
משני השרתים.

הכתובת נקבעת מ-`VODFIX_SRC_PORT`. **בלי המשתנה שום דבר לא משתנה** —
ברירת המחדל נשארת PORT, בדיוק כמו היום. כלומר החלת הפאץ' לבדה בטוחה,
וההפעלה היא בהוספת שורה ל-.env.

    python3 fix_vodfix_source.py --check    # לא נוגע בכלום
    python3 fix_vodfix_source.py            # מחיל, עם גיבוי
    python3 fix_vodfix_source.py --revert    # מחזיר
"""
import datetime, glob, os, pathlib, shutil, sys

TARGET = pathlib.Path("/opt/zovex-bot/main.py")

OLD = '''    return f"http://127.0.0.1:{PORT}/stream/{chat}/{msg}{q}"'''

NEW = '''    # שרת ה-Go (8099) מגיש את אותם בייטים פי 5.5 מהר מהפייתון — נמדד על
    # אותו קובץ: 4MB ב-0.73 שניות מול 3.98. כל מקטע HLS מושך ~6.5MB, ולכן
    # ההפרש הזה הוא כמעט כל זמן ההמתנה של הנגן. החתימה זהה בשני השרתים,
    # ולכן הקישור עובר כמו שהוא.
    #
    # בלי VODFIX_SRC_PORT ההתנהגות נשארת בדיוק כפי שהייתה.
    _src_port = int(os.environ.get("VODFIX_SRC_PORT", PORT))
    return f"http://127.0.0.1:{_src_port}/stream/{chat}/{msg}{q}"'''


def _fail(m):
    print(f"❌ {m}")
    sys.exit(1)


def main():
    if not TARGET.exists():
        _fail(f"{TARGET} לא נמצא")
    src = TARGET.read_text(encoding="utf-8")

    if "--revert" in sys.argv:
        baks = sorted(glob.glob(str(TARGET) + ".bak-vodsrc-*"))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], TARGET)
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}")
        return

    if "VODFIX_SRC_PORT" in src:
        print("✓ הפאץ' כבר מוחל. לא שונה כלום.")
        return
    n = src.count(OLD)
    if n != 1:
        _fail(f"נמצאו {n} התאמות ל-_vf_local_url, ציפינו ל-1. "
              "ייתכן שהקובץ שונה — לא נוגעים.")

    out = src.replace(OLD, NEW)
    try:
        compile(out, str(TARGET), "exec")
    except SyntaxError as e:
        _fail(f"התוצאה לא עוברת קומפילציה: {e}")

    if "--check" in sys.argv:
        print("✓ הפאץ' מתאים לקובץ ועובר קומפילציה. לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-vodsrc-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print(f"✓ הוחל. גיבוי: {os.path.basename(bak)}")
    print()
    print("להפעלה בפועל צריך גם:")
    print("  echo 'VODFIX_SRC_PORT=8099' >> /opt/zovex-bot/.env")
    print("  systemctl restart zovex-bot")
    print()
    print("לכיבוי בלי לגעת בקוד: להסיר את השורה מ-.env ולהפעיל מחדש.")


if __name__ == "__main__":
    main()
