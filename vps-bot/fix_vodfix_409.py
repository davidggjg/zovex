#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בונה את תוכנית המקטעים גם מבקשת מקטע, במקום לדחות ב-409.

## מה נתפס בייצור

הצופה פתח פרק, שמע קול כשתי שניות, והנגן נעצר יבש — בלי ספינר ובלי
שגיאה. המדידה הראתה:

    s1: 1.6 שניות      ← עובד
    s2: 0.002 שניות    ← 409 {"detail":"הרשימה עדיין לא נבנתה"}

שתי אלפיות שנייה זה מהיר מכדי שהשרת נגע בטלגרם או ב-ffmpeg. הבקשה נדחתה
לפני הכל.

## למה

`vodfix_playlist` בונה את תוכנית החיתוך ושומר אותה ב-`info["segments"]`,
בזיכרון התהליך. `vodfix_segment` רק **קורא** משם, ואם ריק — מחזיר 409.

לכן כל `systemctl restart zovex-bot` מוחק את התוכנית, וכל בקשת מקטע
נכשלת מיד. והנגן לא מבקש את הפלייליסט מחדש — הוא כבר אצלו — אז אין מי
שיחמם את המטמון. זה נשאר תקוע עד שמישהו יטען את הדף מאפס.

זה נתפס אחרי restart שאנחנו עצמנו עשינו, אבל זה יקרה בכל פריסה, בכל
עדכון, ובכל נפילה — תמיד באמצע צפייה של מישהו.

## התיקון

אותה בנייה בדיוק, גם בנתיב המקטע. `_vf_header_for` כבר ממוטמן, והמשיכה
היא של ה-moov בלבד — כמה מאות KB, פעם אחת לקובץ.

    python3 fix_vodfix_409.py --check     # לא נוגע בכלום
    python3 fix_vodfix_409.py             # מחיל, עם גיבוי
    python3 fix_vodfix_409.py --revert    # מחזיר
"""
import datetime, glob, os, pathlib, shutil, sys

TARGET = pathlib.Path("/opt/zovex-bot/main.py")

OLD = '''    info = await _vf_header_for(chat_id, message_id)
    segs = info["segments"]
    if not segs:
        raise HTTPException(409, "הרשימה עדיין לא נבנתה")'''

NEW = '''    info = await _vf_header_for(chat_id, message_id)
    # בונים את התוכנית אם היא חסרה, במקום לדחות.
    #
    # התוכנית נשמרת בזיכרון התהליך בלבד, ולכן כל restart מוחק אותה וכל
    # בקשת מקטע חזרה 409 — בזמן שהנגן כבר ניגן. הצופה ראה את הסרט נעצר
    # יבש, בלי ספינר ובלי שגיאה. נתפס בייצור: s1 ב-1.6 שניות, s2 ב-0.002.
    #
    # אי אפשר להסתמך על כך שנתיב הפלייליסט יחמם את המטמון: הנגן כבר
    # מחזיק את הפלייליסט ולא מבקש אותו שוב.
    if info["segments"] is None:
        moov = await _vf_fetch(_vf_local_url(chat_id, message_id),
                               info["moov_start"],
                               info["moov_start"] + info["moov_len"] - 1)
        plan, total = _mp4_segment_plan(moov, _VF_SEG_TARGET)
        info["segments"] = plan
        log.info("vodfix: %s/%s — נבנה מבקשת מקטע: %d סגמנטים, %.0f שניות",
                 chat_id, message_id, len(plan), total)
    segs = info["segments"]
    if not segs:
        raise HTTPException(415, "לא הצלחתי לחשב נקודות חיתוך")'''


def _fail(m):
    print(f"❌ {m}")
    sys.exit(1)


def main():
    if not TARGET.exists():
        _fail(f"{TARGET} לא נמצא")
    src = TARGET.read_text(encoding="utf-8")

    if "--revert" in sys.argv:
        baks = sorted(glob.glob(str(TARGET) + ".bak-vf409-*"))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], TARGET)
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}")
        return

    if "נבנה מבקשת מקטע" in src:
        print("✓ הפאץ' כבר מוחל. לא שונה כלום.")
        return
    n = src.count(OLD)
    if n != 1:
        _fail(f"נמצאו {n} התאמות, ציפינו ל-1. הקובץ שונה — לא נוגעים.")

    out = src.replace(OLD, NEW)
    try:
        compile(out, str(TARGET), "exec")
    except SyntaxError as e:
        _fail(f"התוצאה לא עוברת קומפילציה: {e}")

    if "--check" in sys.argv:
        print("✓ הפאץ' מתאים לקובץ ועובר קומפילציה. לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-vf409-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print(f"✓ הוחל. גיבוי: {os.path.basename(bak)}")
    print("   צריך: systemctl restart zovex-bot")


if __name__ == "__main__":
    main()
