#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# מרחיב את חלון המקטעים בערוצים חיים, ומיישר נקודות מפתח בפרופיל ההמרה.
#
# ## התסמין
#
# ערוץ חי מנגן, נתקע לכחצי דקה, ממשיך, ונתקע שוב. **רק בערוצים שעוברים
# המרה אצלנו** — אצל הספק אותו קישור רץ חלק.
#
# ## הסיבה
#
# נגני HLS סטנדרטיים מתחילים לנגן שלושה מקטעים *אחורה* מקצה השידור. זו
# הגדרת liveSyncDurationCount של hls.js, ברירת מחדל 3, והתיעוד שלהם אומר
# במפורש שהקטנתה "צפויה לגרום לתקיעות". אנחנו מגישים:
#
#     -hls_time 4  -hls_list_size 6  -hls_flags delete_segments
#
# חלון של 6 מקטעים, 24 שניות, ומה שיוצא ממנו נמחק מהדיסק מיד. הנגן יושב
# 3 מקטעים אחורה, ולכן המרווח בפועל הוא **3 מקטעים = 12 שניות**. כל שיהוק
# — רשת, עומס רגעי, ffmpeg שמפגר — והנגן מבקש מקטע שכבר נמחק, מקבל 404,
# נתקע, ומאתחל לקצה השידור. משך התקיעה הוא בסדר גודל של החלון, ומכאן חצי
# הדקה.
#
# המפרט של אפל קובע שרשימה חיה **חייבת** להכיל לפחות 6 מקטעים, ו**מומלץ**
# שתכסה 15 דקות. אנחנו יושבים בדיוק על המינימום המוחלט, בלי שום מרווח.
#
# ## שני השינויים
#
# 1. החלון עולה מ-6 ל-12 מקטעים (48 שניות), דרך HLS_FIX_LIST_SIZE.
#    המרווח בפועל עולה מ-12 ל-36 שניות. העלות היא מקום ב-/tmp בלבד —
#    לא מעבד ולא רוחב פס, ו-delete_segments עדיין חוסם את הגידול.
#
# 2. פרופיל ההמרה הראשי מקבל יישור נקודות מפתח לגבול המקטע. שני
#    הפרופילים האחרים בקובץ (_OPENGOP_VARGS ו-HLS_FIX_SAFE_ARGS) כבר
#    עושים את זה עם force_key_frames; הראשי נשאר עם ‎-g 48‎ בלבד, וזה
#    48 *פריימים* ולא 4 שניות — ב-25fps זה 1.92 שניות וב-30fps 1.6.
#    התוצאה היא מקטעים באורכים לא אחידים, והנגן מתקשה להעריך את הבאפר
#    שלו. מי שתיקן את הפרופילים האחרים לא העתיק לכאן.
#
# ## בטיחות
#
# התאמה מדויקת או סירוב. אם הקובץ החי נראה אחרת — לא נוגע בכלום ואומר
# את זה. גיבוי לפני כל כתיבה, ובדיקת קומפילציה אחרי.
#
#   python3 patch_live_window.py [נתיב ל-main.py]
#   python3 patch_live_window.py --revert
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

MARK = "HLS_FIX_LIST_SIZE"

# ── 1. חלון המקטעים ─────────────────────────────────────────────────────────
OLD_WIN = '''            "-f", "hls", "-hls_time", "4", "-hls_list_size", "6",'''
NEW_WIN = '''            "-f", "hls", "-hls_time", "4",
            # [fix_live_window] החלון היה 6 מקטעים, 24 שניות, עם
            # delete_segments. נגן HLS יושב שלושה מקטעים אחורה מקצה
            # השידור (liveSyncDurationCount=3 ב-hls.js), ולכן המרווח
            # בפועל היה 12 שניות בלבד — וכל שיהוק גרם לו לבקש מקטע
            # שכבר נמחק, לקבל 404, ולהתאתחל. זו התקיעה של חצי דקה
            # שדווחה, והיא הופיעה רק בערוצים שעוברים המרה.
            #
            # המפרט של אפל דורש 6 מקטעים כמינימום וממליץ על 15 דקות.
            # ישבנו בדיוק על המינימום. העלות של חלון רחב יותר היא מקום
            # ב-/tmp בלבד, ו-delete_segments עדיין חוסם את הגידול.
            "-hls_list_size", str(HLS_FIX_LIST_SIZE),'''

# ── 2. יישור נקודות מפתח בפרופיל הראשי ─────────────────────────────────────
OLD_KEY = '''    return [
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-profile:v", "main", "-pix_fmt", "yuv420p",
        "-g", "48", "-sc_threshold", "0",'''
NEW_KEY = '''    return [
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-profile:v", "main", "-pix_fmt", "yuv420p",
        # [fix_live_window] יישור נקודות מפתח לגבול המקטע.
        #
        # כאן היה ‎-g 48‎ בלבד, וזה 48 *פריימים* ולא 4 שניות: ב-25fps
        # 1.92 שניות, ב-30fps 1.6. מקטע יכול להיחתך רק בנקודת מפתח,
        # ולכן האורכים יצאו לא אחידים והנגן התקשה להעריך את הבאפר שלו.
        #
        # שני הפרופילים האחרים בקובץ — _OPENGOP_VARGS ו-
        # HLS_FIX_SAFE_ARGS — כבר עושים את זה נכון. מי שתיקן אותם לא
        # העתיק לכאן, וזה הפרופיל שרץ ברוב ההמרות.
        "-g", "96", "-keyint_min", "48", "-sc_threshold", "0",
        "-forced-idr", "1",
        "-force_key_frames", f"expr:gte(t,n_forced*{_HLS_IDR_SEC})",'''

# ── 3. ההגדרה עצמה ──────────────────────────────────────────────────────────
OLD_CFG = '''HLS_FIX_MAX = int(os.environ.get("HLS_FIX_MAX", "8"))'''
NEW_CFG = '''HLS_FIX_MAX = int(os.environ.get("HLS_FIX_MAX", "8"))
# [fix_live_window] כמה מקטעים ברשימה החיה. ראה את ההסבר ליד
# ‎-hls_list_size‎. 12 מקטעים של 4 שניות הם חלון של 48 שניות, כלומר
# מרווח של 36 שניות לנגן שיושב שלושה מקטעים אחורה.
HLS_FIX_LIST_SIZE = int(os.environ.get("HLS_FIX_LIST_SIZE", "12"))'''

PAIRS = [(OLD_CFG, NEW_CFG), (OLD_WIN, NEW_WIN), (OLD_KEY, NEW_KEY)]


def main():
    try:
        s = io.open(P, encoding="utf-8").read()
    except OSError as e:
        sys.exit(f"❌ לא נפתח {P}: {e}")

    if REVERT:
        bak = sorted(
            (f for f in os.listdir(os.path.dirname(P) or ".")
             if f.startswith("main_before_livewindow_")), reverse=True)
        if not bak:
            sys.exit("❌ אין גיבוי לשחזר")
        src = os.path.join(os.path.dirname(P) or ".", bak[0])
        shutil.copy(src, P)
        print(f"✓ שוחזר מ-{src}")
        return

    if MARK in s:
        print("✓ כבר מתוקן — מדלג")
        return

    for i, (old, _) in enumerate(PAIRS, 1):
        n = s.count(old)
        if n != 1:
            sys.exit(
                f"❌ קטע {i} מתוך {len(PAIRS)} לא נמצא בדיוק פעם אחת "
                f"({n} התאמות) ב-{P}.\n"
                f"   לא נגעתי בכלום. הקובץ החי שונה ממה שציפיתי —\n"
                f"   שלח לי את הפלט ואתאים את הטלאי.")

    bak = f"{os.path.dirname(P) or '.'}/main_before_livewindow_" \
          f"{time.strftime('%Y%m%d-%H%M%S')}.py"
    shutil.copy(P, bak)

    out = s
    for old, new in PAIRS:
        out = out.replace(old, new, 1)
    io.open(P, "w", encoding="utf-8").write(out)

    try:
        py_compile.compile(P, doraise=True)
    except Exception as e:
        shutil.copy(bak, P)
        sys.exit(f"❌ לא עובר קומפילציה — שוחזר.\n   {e}")

    print(f"✓ הוחל ({len(PAIRS)} קטעים). גיבוי: {bak}")
    print("  חלון: 6 → 12 מקטעים (24 → 48 שניות)")
    print("  נקודות מפתח בפרופיל הראשי: מיושרות ל-4 שניות")


if __name__ == "__main__":
    main()
