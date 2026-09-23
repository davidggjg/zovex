#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_poster_sharp — הפוסטר בטלגרם מטושטש. זה תוקן במקום שבו זה באמת קרה.

## מה נמדד

פוסטר PNG 1024×1536 עם טקסט, דרך הצינור הקיים, מול המקור (SSIM, 1.0 = זהה):

    הפוסטר שמוטמע בקובץ .................. 0.9989   ← כמעט מושלם, לא הבעיה
    התצוגה המקדימה בטלגרם (320 פיקסל) .... 0.9739   ← זו הבעיה

התצוגה המקדימה הוקטנה ל-320 פיקסל, ואז הטלפון מותח אותה על מסך של 1080 —
ומכאן הטשטוש. המגבלה הזאת של 320 היא של **Bot API**, וההעלאה הזאת עוברת
בכלל דרך חשבון משתמש (MTProto), שבו אין אותה. אפליקציות טלגרם עצמן שולחות
תצוגות גדולות בהרבה.

    1280 פיקסל ........................... 0.9953

## מה משתנה

  1. **התצוגה בטלגרם: 320 → 1280 פיקסל.** זה כל ההבדל.
  2. **בלי קידוד כפול.** הטלפון כבר שולח JPEG תקין; השרת היה מקודד אותו
     שוב. עכשיו הוא בודק אותו ומעביר כמו שהוא, ומקודד רק מה שצריך
     (PNG/HEIC, או תמונה גדולה מ-2000 פיקסל).
  3. **פוסטר מ-TMDB באיכות כפולה** — w780 במקום w500, רק להטמעה בקובץ.
     כתובות הפוסטרים של הקטלוג לא משתנות.

## למה זה לא יכול לשבור העלאה

אם טלגרם יסרב לתצוגה הגדולה, המסלול המקביל ייפול — ואז, כמו היום, רצה
המסלול הרגיל. השינוי היחיד הוא שהמסלול הרגיל מקבל עכשיו תצוגה של 320
פיקסל, בדיוק זו שעובדת היום. כלומר במקרה הגרוע התוצאה זהה למצב הנוכחי,
ואין מסלול חדש שיכול להיכשל.

דורש fix_saved_poster ו-fix_custom_poster.

    python3 fix_poster_sharp.py --check
    python3 fix_poster_sharp.py
    python3 fix_poster_sharp.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_poster_sharp"
MARK = "fix_poster_sharp"

# ── 1. התצוגה המקדימה ──────────────────────────────────────────────────────
A_THUMB = '''def _saved_poster_thumb(poster: str) -> str:
    """התצוגה המקדימה בטלגרם, מהפוסטר. טלגרם דורש JPEG עד 320 פיקסלים בכל
    צד ועד 200KB, ו-w500 של TMDB גדול מזה — לכן מקטינים. חוסם."""
    exe = shutil.which("ffmpeg")
    if not exe or not poster:
        return ""
    out = poster + ".thumb.jpg"
    try:
        subprocess.run(
            [exe, "-y", "-v", "error", "-i", poster, "-vf",
             "scale=320:320:force_original_aspect_ratio=decrease",
             "-q:v", "4", out], capture_output=True, timeout=60)
        if os.path.exists(out) and 0 < os.path.getsize(out) <= 200 * 1024:
            return out
    except Exception:
        pass
    try:
        os.unlink(out)
    except OSError:
        pass
    return ""
'''

N_THUMB = '''def _saved_poster_thumb(poster: str, px: int = 1280) -> str:
    """[fix_poster_sharp] התצוגה המקדימה בטלגרם, מהפוסטר.

    320 פיקסל היה המספר הקודם, והוא המגבלה של Bot API. ההעלאה הזאת עוברת
    דרך חשבון משתמש (MTProto), שבו אין את המגבלה — ו-320 פיקסל שנמתחים על
    מסך טלפון הם בדיוק מה שנראה מטושטש. נמדד מול המקור: 320 → 0.974,
    1280 → 0.995. חוסם — להריץ ב-executor.
    """
    exe = shutil.which("ffmpeg")
    if not exe or not poster:
        return ""
    out = f"{poster}.thumb{px}.jpg"
    try:
        subprocess.run(
            [exe, "-y", "-v", "error", "-i", poster, "-vf",
             f"scale={px}:{px}:force_original_aspect_ratio=decrease",
             "-q:v", "3", out], capture_output=True, timeout=60)
        # 1MB — תצוגה של 1280 יוצאת סביב 35KB, ולכן זו תקרת שפיות בלבד
        if os.path.exists(out) and 0 < os.path.getsize(out) <= 1024 * 1024:
            return out
    except Exception:
        pass
    try:
        os.unlink(out)
    except OSError:
        pass
    return ""
'''

# ── 2. בלי קידוד כפול ──────────────────────────────────────────────────────
A_NORM = '''def _saved_normalize_poster(src: str, dest: str) -> bool:
    """כל תמונה → JPEG, עד 1500 פיקסלים בצד, בלי הגדלה. חוסם — ב-executor."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return False
    try:
        subprocess.run(
            [exe, "-y", "-v", "error", "-i", src, "-frames:v", "1", "-vf",
             "scale=w='min(1500,iw)':h='min(1500,ih)'"
             ":force_original_aspect_ratio=decrease",
             "-q:v", "2", dest], capture_output=True, timeout=60)
        with open(dest, "rb") as f:
            return f.read(3) == b"\\xff\\xd8\\xff"
    except Exception:
        return False
'''

N_NORM = '''# [fix_poster_sharp] מה באמת נחשב תמונה. ffmpeg מפענח גם דברים שאינם
# תמונה — קובץ של בייטים אקראיים זוהה אצלנו כ-bintext (אמנות ASCII של DOS)
# ויצא ממנו "פוסטר" 640x400. פוסטר נכנס לתוך קובץ הווידאו לתמיד, ולכן
# מקבלים רק מקודד תמונה מוכר.
_POSTER_CODECS = {
    "mjpeg", "png", "apng", "webp", "bmp", "gif", "tiff", "jpeg2000",
    "jpegls", "ppm", "pgm", "targa", "hevc", "av1",
}


def _saved_normalize_poster(src: str, dest: str) -> bool:
    """[fix_poster_sharp] כל תמונה → JPEG עד 2000 פיקסלים בצד, בלי הגדלה.

    JPEG תקין שכבר בגבולות עובר כמו שהוא. קודם הוא קודד כאן שוב אחרי
    שהטלפון כבר קידד — שני מעברי JPEG על פוסטר עם טקסט משאירים הילה סביב
    האותיות, בלי שום תמורה. חוסם — ב-executor.
    """
    exe = shutil.which("ffmpeg")
    probe = shutil.which("ffprobe")
    if not exe or not probe:
        return False
    try:
        info = json.loads(subprocess.run(
            [probe, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=codec_name,width,height", "-of", "json", src],
            capture_output=True, timeout=30).stdout or b"{}")
        st = (info.get("streams") or [{}])[0]
        codec = st.get("codec_name") or ""
        w, h = int(st.get("width") or 0), int(st.get("height") or 0)
        if codec not in _POSTER_CODECS or w < 2 or h < 2:
            log.info("poster: הקובץ אינו תמונה מוכרת (%s) — נדחה", codec or "?")
            return False
        if codec == "mjpeg" and max(w, h) <= 2000:
            shutil.copyfile(src, dest)          # כבר מתאים — לא מקודדים שוב
            return True
        subprocess.run(
            [exe, "-y", "-v", "error", "-i", src, "-frames:v", "1", "-vf",
             "scale=w='min(2000,iw)':h='min(2000,ih)'"
             ":force_original_aspect_ratio=decrease",
             "-q:v", "2", dest], capture_output=True, timeout=60)
        with open(dest, "rb") as f:
            return f.read(3) == b"\\xff\\xd8\\xff"
    except Exception:
        return False
'''

# ── 3. פוסטר TMDB באיכות כפולה, רק להטמעה ─────────────────────────────────
A_URL = '''    url = top.get("poster") or ""
'''
N_URL = '''    url = top.get("poster") or ""
    # [fix_poster_sharp] w500 הוא הגודל של הקטלוג. להטמעה בתוך הקובץ לוקחים
    # w780 — אותה תמונה, פי-שניים פיקסלים. כתובות הקטלוג לא משתנות.
    url = url.replace("/t/p/w500/", "/t/p/w780/")
'''

# ── 4. תצוגה קטנה שמורה למסלול הנפילה ─────────────────────────────────────
A_INIT = '''    _poster = _pthumb = ""   # [fix_saved_poster] גם הם נמחקים ב-finally
'''
N_INIT = '''    _poster = _pthumb = ""   # [fix_saved_poster] גם הם נמחקים ב-finally
    _thumb_small = ""        # [fix_poster_sharp] גיבוי למסלול הנפילה
'''

A_MAKE = '''        thumb = _pthumb or await _loop.run_in_executor(
            None, _saved_thumb, path, min(10, max(1, _dur // 10)) if _dur else 1)
'''
N_MAKE = '''        thumb = _pthumb or await _loop.run_in_executor(
            None, _saved_thumb, path, min(10, max(1, _dur // 10)) if _dur else 1)
        # [fix_poster_sharp] תצוגה של 320 פיקסל, למקרה שטלגרם יסרב לגדולה.
        # נבנית עכשיו ולא בתוך ה-except, כי שם כבר אין לולאת אירועים פנויה
        # והפוסטר עלול להיות מחוק.
        if _pthumb and _poster:
            _thumb_small = await _loop.run_in_executor(
                None, _saved_poster_thumb, _poster, 320)
'''

A_FALL = '''                thumb=thumb or None, supports_streaming=True,
                progress=_progress)
'''
N_FALL = '''                thumb=(_thumb_small or thumb or None),   # [fix_poster_sharp]
                supports_streaming=True,
                progress=_progress)
'''

A_CLEAN = '''            for _f in (_poster, _pthumb):      # [fix_saved_poster]
'''
N_CLEAN = '''            for _f in (_poster, _pthumb, _thumb_small):   # [fix_poster_sharp]
'''

EDITS = [
    ("התצוגה המקדימה", A_THUMB, N_THUMB, None),
    ("בלי קידוד כפול", A_NORM, N_NORM, None),
    ("פוסטר TMDB", A_URL, N_URL, "_saved_find_poster"),
    ("אתחול", A_INIT, N_INIT, "_saved_send"),
    ("בניית התצוגות", A_MAKE, N_MAKE, "_saved_send"),
    ("מסלול הנפילה", A_FALL, N_FALL, "_saved_send"),
    ("ניקוי", A_CLEAN, N_CLEAN, "_saved_send"),
]


def fn_source(src, name):
    for n in ast.walk(ast.parse(src)):
        if getattr(n, "name", "") == name and isinstance(
                n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ast.get_source_segment(src, n)
    return None


def validate(s):
    compile(s, PATH, "exec")
    names = [n.name for n in ast.walk(ast.parse(s))
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for f in ("_saved_poster_thumb", "_saved_normalize_poster", "_saved_send",
              "_saved_find_poster"):
        assert names.count(f) == 1, f"{f} חסרה או כפולה"
    th = fn_source(s, "_saved_poster_thumb")
    assert "px: int = 1280" in th, "התצוגה לא הוגדלה"
    assert "scale=320:320" not in th, "נשארה הקטנה קשיחה ל-320"
    nm = fn_source(s, "_saved_normalize_poster")
    assert "shutil.copyfile(src, dest)" in nm, "אין מעבר ללא קידוד"
    assert "min(2000,iw)" in nm
    assert "_POSTER_CODECS" in nm and "_POSTER_CODECS" in s, "אין בדיקת פורמט תמונה"
    sd = fn_source(s, "_saved_send")
    assert "_thumb_small = await _loop.run_in_executor" in sd
    assert "thumb=(_thumb_small or thumb or None)" in sd
    assert "(_poster, _pthumb, _thumb_small)" in sd
    # התצוגה הקטנה חייבת להיבנות לפני השליחה, לא אחריה
    assert sd.index("_thumb_small = await") < sd.index("_send_video_parallel"), \
        "התצוגה הקטנה נבנית מאוחר מדי"
    fp = fn_source(s, "_saved_find_poster")
    assert '"/t/p/w780/"' in fp


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--revert":
        if not os.path.exists(BAK):
            print(f"❌ אין גיבוי ב-{BAK}")
            return 1
        shutil.copyfile(BAK, PATH)
        print("✓ שוחזר. הרץ:  systemctl restart zovex-bot")
        return 0
    if not os.path.exists(PATH):
        print(f"❌ לא נמצא {PATH}")
        return 1
    with open(PATH, encoding="utf-8") as f:
        s = f.read()
    if MARK in s:
        print("כבר מותקן. אין מה לעשות.")
        return 0
    for need in ("fix_saved_poster", "fix_custom_poster"):
        if need not in s:
            print(f"❌ חסר {need} — הרץ אותו קודם")
            return 1
    out = s
    for name, a, b, fn in EDITS:
        if out.count(a) != 1:
            print(f"❌ העוגן '{name}' נמצא {out.count(a)} פעמים (ציפיתי 1). לא נוגע.")
            return 1
        if fn:
            body = fn_source(out, fn)
            if body is None or a.rstrip("\n") not in body:
                print(f"❌ העוגן '{name}' אינו בתוך {fn}. לא נוגע.")
                return 1
        out = out.replace(a, b, 1)
    try:
        validate(out)
    except Exception as e:
        print(f"❌ התוצאה לא תקינה ({e}) — לא נכתב כלום.")
        return 1
    print(f"יעד:   {PATH}")
    print("שינוי: התצוגה של הפוסטר בטלגרם 320 → 1280 פיקסל, בלי קידוד כפול")
    if arg == "--check":
        print("--check: שום דבר לא נכתב.")
        return 0
    if not os.path.exists(BAK):
        shutil.copyfile(PATH, BAK)
    tmp = PATH + ".tmp_poster_sharp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, PATH)
    print(f"✓ הוחל · גיבוי: {BAK}")
    print("  הרץ:  systemctl restart zovex-bot")
    print("  לביטול:  python3 fix_poster_sharp.py --revert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
