#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מתקן את חותמת הזמן השלילית במקטע הראשון של מסלול תיקון-הקול (/vh).

## מה נתפס

באפליקציה, ונסדיי: לוחצים הפעל, מנגן כשתי שניות **בלי קול**, נתקע, חוזר
ל-0:00 וטוען בלי סוף. שתי השניות הן הקובץ המקורי (ec-3, ה-WebView משמיט
את הקול); אחרי 3.5 שניות הבדיקה מזהה שאין קול, והנגן עובר ל-/vh — ושם
הוא נתקע.

## למה

נמדד ישירות על המקטעים שהשרת מגיש (ונסדיי ע1 פ2, ‎-1003936100530/8966),
מתוך פענוח חבילות ה-MPEG-TS:

    s0.ts    H.264  PTS ראשון       0.000
             AAC    PTS ראשון   95443.696      ←
    s1.ts    H.264  PTS ראשון      13.890
             AAC    PTS ראשון      13.870      ← תקין
    s2.ts    ...                               ← תקין

‎95443.696 אינו מספר אקראי: ‎2**33 / 90000 = 95443.717. שדה ה-PTS ב-MPEG-TS
הוא 33 סיביות **בלי סימן**, ולכן חותמת שלילית קטנה נכתבת כערך ענק ממש
מתחת לתקרה. כלומר: החותמת האמיתית של החבילה הראשונה היא בערך ‎-0.02
שניות.

מאיפה השלילי? מקודד ה-AAC מכניס priming (‎1024 דגימות ≈ 21ms) לפני הדגימה
הראשונה. עם `-copyts` החותמות נשמרות כמו שהן, ו-`-avoid_negative_ts
disabled` אומר למאחד במפורש: אל תתקן, כתוב מה שיש. אז הוא כתב מינוס — והוא
נעטף.

בשביל הנגן זה נראה כך: הווידאו ב-0, הקול ב-95,443. הוא לא יכול ליישר
ביניהם, מחכה לאודיו שלעולם לא יגיע לציר, ונשאר בטעינה. בדיוק מה שדוד
ראה. זה חל על **כל** פריט שעובר את מסלול תיקון-הקול, לא רק ונסדיי —
פשוט רק שם משתמשים בו.

זה לא נצפה באתר כי המקטע פגום רק בהתחלה, ו-Chrome במחשב סלחן יותר
מ-WebView של אנדרואיד.

## התיקון

`-avoid_negative_ts make_non_negative` — מזיז את **כל** הרצועות באותו
דלתא, ורק כשיש חותמת שלילית. יחס הזמן בין קול לתמונה נשמר.

נמדד לפני ולאחרי, על אותו קלט:

    disabled            H.264  0.000    AAC  95443.696
    make_non_negative   H.264  0.083    AAC      0.062

ולגבי החשש שזה יזיז גם את שאר המקטעים ויקלקל את החיבור ביניהם — נבדק
במפורש: s1 ו-s2 יצאו **זהים בייט-בבייט** בשני המצבים. אין שם חותמת
שלילית, ולכן אין מה להזיז. הפאץ' נוגע במקטע הראשון בלבד.

    python3 fix_vh_negative_ts.py --check     # לא נוגע בכלום
    python3 fix_vh_negative_ts.py             # מחיל, עם גיבוי
    python3 fix_vh_negative_ts.py --revert    # מחזיר
"""
import datetime, glob, os, pathlib, shutil, sys

TARGET = pathlib.Path("/opt/zovex-bot/main.py")

OLD = '''        # -copyts שומר את חותמות הזמן המקוריות, ולכן הסגמנטים מתחברים
        # ברצף אצל הנגן. תוספת -output_ts_offset כאן הייתה מוסיפה את ההיסט
        # פעם שנייה ומזיזה כל סגמנט קדימה פי שתיים.
        "-copyts", "-avoid_negative_ts", "disabled",'''

NEW = '''        # -copyts שומר את חותמות הזמן המקוריות, ולכן הסגמנטים מתחברים
        # ברצף אצל הנגן. תוספת -output_ts_offset כאן הייתה מוסיפה את ההיסט
        # פעם שנייה ומזיזה כל סגמנט קדימה פי שתיים.
        #
        # make_non_negative ולא disabled: מקודד ה-AAC מוסיף priming של
        # ~21ms, ולכן החבילה הראשונה של המקטע הראשון יוצאת עם חותמת זמן
        # שלילית. שדה ה-PTS ב-MPEG-TS הוא 33 סיביות בלי סימן, אז המינוס
        # נעטף ונכתב כ-95443.696 (‎2**33/90000). הנגן ראה וידאו ב-0 וקול
        # ב-95,443, לא הצליח ליישר, ונתקע בטעינה אחרי כשתי שניות — כך
        # נראתה התקלה בונסדיי באפליקציה.
        #
        # make_non_negative מזיז את כל הרצועות באותו דלתא ורק כשיש חותמת
        # שלילית, ולכן יחס קול/תמונה נשמר. נמדד: s1 ו-s2 יוצאים זהים
        # בייט-בבייט לפני ואחרי — רק המקטע הראשון משתנה.
        "-copyts", "-avoid_negative_ts", "make_non_negative",'''

MARK = '"-avoid_negative_ts", "make_non_negative"'


def _fail(m):
    print(f"❌ {m}")
    sys.exit(1)


def main():
    if not TARGET.exists():
        _fail(f"{TARGET} לא נמצא")
    src = TARGET.read_text(encoding="utf-8")

    if "--revert" in sys.argv:
        baks = sorted(glob.glob(str(TARGET) + ".bak-vhts-*"))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], TARGET)
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}")
        print("   צריך: systemctl restart zovex-bot")
        return

    if MARK in src:
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

    bak = f"{TARGET}.bak-vhts-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print(f"✓ הוחל. גיבוי: {os.path.basename(bak)}")
    print("   צריך: systemctl restart zovex-bot")
    print("   ואז:  python3 check_vh_ts.py    כדי לוודא שהחותמות תקינות")


if __name__ == "__main__":
    main()
