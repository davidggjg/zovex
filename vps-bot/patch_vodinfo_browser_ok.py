#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · ‎/vodinfo‎ לא אומר "הדפדפן לא יכול" על קובץ MP4.
#
# ## מה נמדד
#
# "החממה" — כל שלוש העונות, כל פרק שנבדק — היא DivX/XviD בתוך מכולת
# MP4, 624x352, קול MP3. נבדק ישירות מול השרת החי עם ffprobe על
# ההתחלה והסוף של הקבצים, ועם חיפוש חתימת XviD/DivX ב-18 פרקים.
#
# דפדפנים אינם מפענחים MPEG-4 Part 2. התוצאה אצל הצופה: תמונה שבורה
# או שחורה, ובלי קול — בדיוק מה שדווח.
#
# ## הבאג
#
# ל-‎/vodinfo‎ **יש** בדיקת וידאו, והיא עובדת: ‎video_ok‎ יוצא False
# והוא בוחר ‎kind="hls"‎. אבל המסלול של MP4 אינו מחזיר את השדה
# ‎browser_ok‎ בכלל — הוא מוחזר רק במסלול של מכולה שאינה MP4.
#
# והאתר בודק בדיוק את השדה הזה:
#
#     if (!d || d.browser_ok !== false) return;    // CustomVideoPlayer.jsx
#
# ‎undefined !== false‎ הוא true, ולכן הנגן מסיק "הכול בסדר" וממשיך
# לנסות לנגן קובץ שהדפדפן אינו יכול לפענח. הזיהוי המהיר מת, ונשארת
# רק רשת הביטחון של 25 שניות.
#
# ## התיקון
#
# שורה אחת: המסלול של MP4 מחזיר גם ‎browser_ok‎, שהוא בדיוק התנאי
# שכבר מחושב שם — קול תקין **וגם** וידאו תקין.
#
#   python3 patch_vodinfo_browser_ok.py            # מחיל
#   python3 patch_vodinfo_browser_ok.py --revert
# ─────────────────────────────────────────────────────────────────────────────
import io, os, py_compile, shutil, sys

F = "/opt/zovex-bot/main.py"
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if args:
    F = args[0]
REVERT = "--revert" in sys.argv
BAK = F + ".before_vodinfo_browser_ok"

OLD = '''    return {"audio": info["audio"], "audio_ok": info["audio_ok"],
            "video": info["video"], "video_ok": info["video_ok"],  # [fix_vh_video]'''
NEW = '''    return {"audio": info["audio"], "audio_ok": info["audio_ok"],
            "video": info["video"], "video_ok": info["video_ok"],  # [fix_vh_video]
            # [vodinfo_browser_ok] השדה הזה הוחזר רק במסלול של מכולה
            # שאינה MP4, והאתר בודק בדיוק אותו:
            #     if (!d || d.browser_ok !== false) return;
            # undefined אינו false, ולכן DivX/XviD בתוך MP4 — "החממה",
            # כל שלוש העונות — נראה לנגן כקובץ תקין, והזיהוי המהיר לא
            # פעל. נשארה רק רשת הביטחון של 25 שניות.
            "browser_ok": bool(info["audio_ok"] and info["video_ok"]),'''

if REVERT:
    if os.path.exists(BAK):
        shutil.copy2(BAK, F)
        print("✅ שוחזר מ-%s" % BAK)
    else:
        s = io.open(F, encoding="utf-8").read()
        if NEW not in s:
            print("לא מותקן, אין מה להסיר.")
            sys.exit(0)
        io.open(F, "w", encoding="utf-8").write(s.replace(NEW, OLD))
        print("✅ הוסר")
    sys.exit(0)

s = io.open(F, encoding="utf-8").read()
if "[vodinfo_browser_ok]" in s:
    print("✅ כבר מותקן.")
    sys.exit(0)
if s.count(OLD) != 1:
    sys.exit("❌ העוגן מופיע %d פעמים — לא נוגעים בקובץ" % s.count(OLD))
shutil.copy2(F, BAK)
io.open(F, "w", encoding="utf-8").write(s.replace(OLD, NEW, 1))
try:
    py_compile.compile(F, doraise=True)
except Exception as e:
    shutil.copy2(BAK, F)
    sys.exit("❌ הקובץ לא מתקמפל — שוחזר. %s" % e)
print("✅ הוחל. גיבוי: %s" % BAK)
print("   נדרש restart ל-zovex-bot כדי שייכנס לתוקף.")
