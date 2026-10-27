#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# ‎Range: bytes=-N‎ הוחזר הפוך — ומכאן "לא ניתן לנגן מיקום זה".
#
# ## הבאג
#
#     start = int(start_str) if start_str else 0
#     end   = int(end_str)   if end_str   else file_size - 1
#
# על ‎bytes=-65536‎ (לפי RFC 7233: "65536 הבייטים **האחרונים**") הצד
# השמאלי ריק, ולכן ‎start=0‎ ו-‎end=65536‎ — כלומר הוחזרו 65KB
# ה**ראשונים**. ההפך הגמור ממה שהתבקש.
#
# ## למה זה שובר נגנים
#
# נמדד על קובץ חי מהקטלוג (הודעה 20213): המבנה הוא
#
#     ftyp → free → mdat
#
# בלי ‎moov‎ בהתחלה — כלומר טבלת האינדקס יושבת ב**סוף** הקובץ. כל נגן
# חייב להביא אותה לפני שהוא מנגן בייט אחד, והדרך לעשות זאת היא בדיוק
# ‎bytes=-N‎. הנגן ביקש את הזנב, קיבל את ההתחלה, לא מצא ‎moov‎, והכריז
# שהקובץ אינו נגיש.
#
# זה לא תלוי ברשת ולא בנגן מסוים: VLC, כרום, ספארי, ExoPlayer והסורק של
# גוגל כולם משתמשים בטווח סיומת. הקבצים שבהם ‎moov‎ בהתחלה עבדו, ולכן זה
# נראה אקראי — "חלק מהקישורים מתנגנים וחלק לא".
#
# ## התיקון
#
#   · ‎bytes=-N‎ → ‎(file_size - N, file_size - 1)‎, בהצמדה ל-0
#   · ‎bytes=X-‎ ו-‎bytes=X-Y‎ — בדיוק כמו קודם
#   · טווח שמתחיל אחרי סוף הקובץ מחזיר 416, כפי שה-RFC מחייב, במקום
#     טווח הפוך שמייצר תשובה פגומה
#   · בקשה מרובת-טווחים: נלקח הראשון במקום 416 — הקוד הקודם קרס על
#     הפסיק ודחה אותה לגמרי
#
#   python3 patch_suffix_range.py [נתיב ל-main.py]
#   python3 patch_suffix_range.py --revert
# ─────────────────────────────────────────────────────────────────────────────
import io
import os
import py_compile
import shutil
import sys
import time

P = "/opt/zovex-bot/main.py"
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if args:
    P = args[0]
REVERT = "--revert" in sys.argv
MARK = "suffix_range"

OLD = '''def parse_range(range_header: str, file_size: int) -> tuple[int, int]:
    try:
        _, ranges = range_header.split("=")
        start_str, end_str = ranges.split("-")
        start = int(start_str) if start_str else 0
        end   = int(end_str)   if end_str   else file_size - 1
        return start, min(end, file_size - 1)
    except Exception:
        raise HTTPException(status_code=416, detail="Invalid Range header")'''

NEW = '''def parse_range(range_header: str, file_size: int) -> tuple[int, int]:
    """[suffix_range] ‎bytes=-N‎ הוא "N הבייטים האחרונים", לא הראשונים.

    הקוד הקודם קרא ‎start_str‎ ריק כ-0 והחזיר את תחילת הקובץ. בקובץ שבו
    ‎moov‎ יושב בסוף (נמדד: ftyp → free → mdat, בלי moov בהתחלה) הנגן
    מבקש את הזנב כדי לקרוא את טבלת האינדקס, קיבל את ההתחלה, ולכן הכריז
    "לא ניתן לנגן מיקום זה". VLC, כרום, ספארי, ExoPlayer והסורק של גוגל
    כולם משתמשים בטווח סיומת.
    """
    try:
        _, ranges = range_header.split("=", 1)
        # בקשה מרובת-טווחים: הקוד הקודם קרס על הפסיק ודחה אותה ב-416.
        # מגישים את הראשון — תשובה חלקית תקינה עדיפה על סירוב.
        ranges = ranges.split(",")[0].strip()
        start_str, end_str = ranges.split("-")
        start_str, end_str = start_str.strip(), end_str.strip()
        if not start_str:
            n = int(end_str)                       # ‎bytes=-N‎
            if n <= 0:
                raise ValueError("אורך סיומת חייב להיות חיובי")
            start = max(0, file_size - n)
            end = file_size - 1
        else:
            start = int(start_str)
            end = int(end_str) if end_str else file_size - 1
    except Exception:
        raise HTTPException(status_code=416, detail="Invalid Range header")
    # טווח שמתחיל אחרי סוף הקובץ אינו ניתן למימוש. הקוד הקודם החזיר כאן
    # start > end והגיש תשובה פגומה במקום לומר זאת.
    if start >= file_size or start > end:
        raise HTTPException(status_code=416, detail="Range Not Satisfiable")
    return start, min(end, file_size - 1)'''


def main():
    d = os.path.dirname(P) or "."
    if REVERT:
        bak = sorted((f for f in os.listdir(d)
                      if f.startswith("main_before_suffixrange_")), reverse=True)
        if not bak:
            sys.exit("❌ אין גיבוי לשחזר")
        shutil.copy(os.path.join(d, bak[0]), P)
        print(f"✓ שוחזר מ-{bak[0]}")
        return

    try:
        s = io.open(P, encoding="utf-8").read()
    except OSError as e:
        sys.exit(f"❌ לא נפתח {P}: {e}")

    if MARK in s:
        print("✓ כבר מתוקן — מדלג")
        return
    if s.count(OLD) != 1:
        sys.exit(f"❌ הקטע לא נמצא בדיוק פעם אחת ({s.count(OLD)}). "
                 f"לא נגעתי בכלום — שלח לי את הפלט.")

    bak = f"{d}/main_before_suffixrange_{time.strftime('%Y%m%d-%H%M%S')}.py"
    shutil.copy(P, bak)
    io.open(P, "w", encoding="utf-8").write(s.replace(OLD, NEW, 1))

    try:
        py_compile.compile(P, doraise=True)
    except Exception as e:
        shutil.copy(bak, P)
        sys.exit(f"❌ לא עובר קומפילציה — שוחזר.\n   {e}")

    print(f"✓ הוחל. גיבוי: {bak}")
    print("  bytes=-N מחזיר עכשיו את סוף הקובץ")


if __name__ == "__main__":
    main()
