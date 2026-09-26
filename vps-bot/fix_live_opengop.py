#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_live_opengop — ערוץ בלי IDR נתקע בדפדפן ומנגן ב-VLC. זו הסיבה.

## מה נמדד

ספורט 5 פלוס דווח כלא מתנגן, בעוד "אותו קישור בדיוק ב-VLC כן פועל".
הקישור נבדק מקצה לקצה והכול בו תקין:

    הפלייליסט ........ HTTP 200, 516 בתים, 1.04 שניות
    הסגמנט ........... HTTP 200, 3,053,684 בתים, 1.94 שניות
    ffprobe .......... h264 High 1920x1080 · aac LC 48kHz stereo

כלומר לא הספק, לא הריליי, ולא הקודק. ואז נסרקו יחידות ה-NAL עצמן,
בחמישה סגמנטים רצופים:

    סגמנט 32532 ... slices=224  SPS=7  IDR=0
    סגמנט 32533 ... slices=224  SPS=7  IDR=0
    סגמנט 32534 ... slices=224  SPS=7  IDR=0
    סגמנט 32535 ... slices=224  SPS=7  IDR=0
    סגמנט 32536 ... slices=224  SPS=7  IDR=0

**אפס IDR.** לשם השוואה, ספורט 5 גולד מאותו ספק ומאותו פורט מחזיר
IDR=2 בכל סגמנט, וכך גם 5max, 5STARS, 5LIVE, ספורט 5, ספורט 6, One1
וכל 13 הערוצים האחרים שנדגמו. הערוץ הזה הוא היחיד.

## למה זה בדיוק ההבדל בין VLC לדפדפן

MSE — המנוע שמאחורי Shaka ו-video.js — מחייב IDR כדי להתחיל להזרים
לבאפר. זרם open-GOP מכיל I-slices ונקודות התאוששות (SPS כל ~0.6 שניות),
אבל אף NAL מסוג 5. MSE לא יתחיל, ולא יזרוק שגיאה: ה-manifest נטען
"בהצלחה" ואף פריים לא מגיע — הצופה רואה 0:00 לנצח. VLC ו-ffmpeg סלחנים
ומתחילים מנקודת התאוששות, ולכן בדיקה שם מטעה.

זה אינו חדש למערכת: ההערה ב-CustomVideoPlayer.jsx ליד startNative כבר
מתארת בדיוק את זה ונוקבת בספורט 5 סטארס. הנפילה לנגן נייטיב עוזרת
באנדרואיד ובספארי, אבל בכרום שולחני אין HLS נייטיב כלל — ונגן הגיבוי
video.js רץ גם הוא על MSE. ולכן שם אין שום מסלול שעובד.

## למה /hls-relay/_fix כפי שהוא לא היה פותר

‎_hls_codec_args‎ מחליט לפי קודק הווידאו בלבד:

    if not codec or codec == "h264":
        return ["-c:v", "copy"] + aud

הערוץ **הוא** h264 תקין, ולכן הוא היה מקבל ‎-c:v copy‎ — והעתקה אינה
מייצרת IDR. כלומר גם לו היינו מנתבים אותו ל-_fix, הוא היה ממשיך
להיתקע. הבדיקה הייתה על השאלה הלא נכונה.

## מה משתנה

נוספת בדיקה שלישית לצד השתיים הקיימות (קודק הווידאו, תקינות הקול):
**האם יש בזרם IDR בכלל.** אם אין — הווידאו מקודד מחדש עם IDR כפוי כל
ארבע שניות, בדיוק בגבול הסגמנט. אם יש — ‎-c:v copy‎ כמו קודם, אפס עומס.

הסריקה היא על יחידות ה-NAL עצמן ולא על דיווח של ffprobe, כי ‎key_frame‎
של ffprobe דולק גם על I-slice שאינו IDR: בסגמנט הנבדק הוא החזיר 7
"מפתחות" בזמן שמספר ה-IDR האמיתי הוא אפס.

## למה זה לא יכול לשבור משהו

* ערוץ עם IDR מקבל בדיוק את מה שקיבל עד היום — ‎-c:v copy‎.
* ספק או כשל בבדיקה מוחזר כ"יש IDR", כלומר ההתנהגות הקיימת. אין מצב
  שבו תקלה בבדיקה מפעילה קידוד מחדש בלי סיבה.
* התשובה נשמרת במטמון לשש שעות, כמו בדיקת הקול שלידה, ולכן הבדיקה
  רצה פעם אחת לערוץ ולא בכל בקשה.
* הקול נקבע בנפרד כמו קודם ואינו מושפע.
* אין נגיעה במסלול הרגיל ‎/hls-relay/<host>/<path>‎.

## מה זה לא מתקן

ה-502 שמחזירים כרגע ערוצי ‎_fix‎ הוא באג נפרד ולא נגוע כאן; הוא נחקר
דרך ‎hls_fix_probe.py‎. גם ניתוב הערוץ עצמו אל ‎_fix‎ אינו חלק מהפאץ'
— הוא נעשה בקטלוג, ומצוין בסוף הריצה.

    python3 fix_live_opengop.py --check
    python3 fix_live_opengop.py
    python3 fix_live_opengop.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_live_opengop"
MARK = "fix_live_opengop"

A_HEAD = '''async def _hls_codec_args(host: str, path: str, src: str):
    """הארגומנטים שקובעים איך לטפל בזרמים. copy כברירת מחדל."""
'''

N_HEAD = '''# [fix_live_opengop]
# זרם open-GOP: יש בו I-slices ונקודות התאוששות, אבל אף NAL מסוג 5 (IDR).
# MSE — המנוע של Shaka ושל video.js — מחייב IDR כדי להתחיל להזרים, ולכן
# הוא נתקע על 0:00 **בלי לזרוק שגיאה**, בעוד VLC ו-ffmpeg מנגנים.
# נמדד בספורט 5 פלוס: חמישה סגמנטים רצופים, 224 slices ו-7 SPS בכל אחד,
# IDR=0 בכולם. באותו ספק ובאותו פורט, 5gold מחזיר IDR=2 לסגמנט.
_hls_idr_cache: dict = {}
_HLS_IDR_TTL = 6 * 3600
# ארבע שניות = אורך הסגמנט ב-_hls_fix_start, כדי שכל סגמנט יתחיל ב-IDR.
_HLS_IDR_SEC = 4
_OPENGOP_VARGS = [
    "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
    "-profile:v", "main", "-pix_fmt", "yuv420p",
    "-g", "96", "-keyint_min", "48", "-sc_threshold", "0",
    # forced-idr הופך את נקודות המפתח ל-IDR אמיתיים ולא ל-I-slices בלבד.
    # בלעדיו x264 יכול לייצר שוב בדיוק את הבעיה שאנחנו מתקנים.
    "-forced-idr", "1",
    "-force_key_frames", f"expr:gte(t,n_forced*{_HLS_IDR_SEC})",
    "-b:v", "2500k", "-maxrate", "3000k", "-bufsize", "5000k",
    "-vf", "scale=min(1280\\,iw):-2",
]


def _h264_has_idr(data: bytes) -> bool:
    """האם יש בזרם Annex B יחידת NAL מסוג 5.

    נפרד מהבדיקה שמריצה ffmpeg כדי שאפשר יהיה לבדוק אותו לבדו.
    מחזיר True גם כשלא נמצאו slices בכלל — "לא יודע" נחשב תקין, כדי
    שספק לא יפעיל קידוד מחדש.
    """
    idr = slices = 0
    i = 0
    while True:
        j = data.find(b"\\x00\\x00\\x01", i)
        if j < 0 or j + 3 >= len(data):
            break
        t = data[j + 3] & 0x1F
        if t == 5:
            idr += 1
        if t in (1, 5):
            slices += 1
        i = j + 3
    if not slices:
        return True                 # לא הצלחנו לקרוא — לא משנים התנהגות
    return idr > 0


def _hls_probe_no_idr(src: str) -> bool:
    """מושך שמונה שניות של וידאו וסורק את יחידות ה-NAL.

    לא משתמשים ב-key_frame של ffprobe: הוא דולק גם על I-slice שאינו
    IDR. בסגמנט שנבדק הוא החזיר 7 "מפתחות" בזמן שה-IDR האמיתי הוא אפס.
    ריצה חוסמת, ולכן נקראת דרך run_in_executor כמו הבדיקות שלידה.
    """
    try:
        import subprocess
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-v", "error", "-t", "8",
             "-i", src, "-map", "0:v:0", "-c", "copy", "-f", "h264", "-"],
            capture_output=True, timeout=60)
        return not _h264_has_idr(r.stdout or b"")
    except Exception:
        return False                # ספק — מתנהגים כמו קודם


async def _hls_no_idr(host: str, path: str, src: str) -> bool:
    """האם הערוץ הזה open-GOP. נשמר במטמון כמו בדיקת הקול שלידה."""
    key = f"{host}/{path}"
    now = time.time()
    ent = _hls_idr_cache.get(key)
    if ent is None or now - ent[0] > _HLS_IDR_TTL:
        loop = asyncio.get_running_loop()
        bad = await loop.run_in_executor(None, _hls_probe_no_idr, src)
        _hls_idr_cache[key] = (now, bad)
        ent = _hls_idr_cache[key]
        log.info("hls_codec: %s → %s", key,
                 "אין IDR (open-GOP), מקודד וידאו מחדש" if bad
                 else "יש IDR, copy")
    return ent[1]


async def _hls_codec_args(host: str, path: str, src: str):
    """הארגומנטים שקובעים איך לטפל בזרמים. copy כברירת מחדל."""
'''

A_BRANCH = '''    if not codec or codec == "h264":
        return ["-c:v", "copy"] + aud
'''

N_BRANCH = '''    if not codec or codec == "h264":
        # [fix_live_opengop]
        # h264 תקין אינו מספיק: זרם בלי IDR הוא h264 לכל דבר, ו-copy
        # משמר אותו כמו שהוא — כלומר משמר גם את התקיעה בדפדפן.
        if await _hls_no_idr(host, path, src):
            return list(_OPENGOP_VARGS) + aud
        return ["-c:v", "copy"] + aud
'''

EDITS = [("כותרת _hls_codec_args", A_HEAD, N_HEAD),
         ("ענף ה-copy", A_BRANCH, N_BRANCH)]


def fn_source(src, name):
    for n in ast.walk(ast.parse(src)):
        if getattr(n, "name", "") == name and isinstance(
                n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ast.get_source_segment(src, n)
    return None


def code_only(fn: str) -> str:
    """הקוד בלי התיעוד והערות — כדי שהסבר לא ייתפס כתנאי."""
    parts = fn.split('"""')
    body = parts[0] + ("".join(parts[2:]) if len(parts) > 2 else "")
    return "\n".join(l for l in body.splitlines()
                     if not l.strip().startswith("#"))


def validate(s):
    compile(s, PATH, "exec")
    names = [n.name for n in ast.walk(ast.parse(s))
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for f in ("_hls_codec_args", "_hls_no_idr", "_hls_probe_no_idr",
              "_h264_has_idr", "_hls_audio_args"):
        assert names.count(f) == 1, f"{f} חסרה או כפולה"

    ca = code_only(fn_source(s, "_hls_codec_args"))
    assert "await _hls_no_idr(host, path, src)" in ca, "הבדיקה לא נקראת"
    assert '-c:v", "copy"' in ca, "ענף ה-copy נעלם"
    # הבדיקה חייבת לשבת בתוך ענף ה-h264 ולפני ה-copy שלו
    assert ca.index("_hls_no_idr") < ca.index('"-c:v", "copy"'), \
        "הבדיקה אחרי ה-copy — לא תרוץ לעולם"
    assert ca.index('codec == "h264"') < ca.index("_hls_no_idr"), \
        "הבדיקה מחוץ לענף ה-h264"
    assert "libx264" in s, "ארגומנטי הקידוד חסרים"

    # ── בדיקת התנהגות על הפונקציות שנכתבו ──────────────────────────────
    ns = {}
    for f in ("_h264_has_idr", "_hls_probe_no_idr"):
        exec(fn_source(s, f), ns)
    has_idr, probe = ns["_h264_has_idr"], ns["_hls_probe_no_idr"]

    def nal(t, n=1):
        return (b"\x00\x00\x01" + bytes([t]) + b"\xaa" * 8) * n

    # 1. זרם עם IDR — תקין
    assert has_idr(nal(7) + nal(8) + nal(5) + nal(1, 30)) is True

    # 2. זרם open-GOP: SPS ו-slices, אבל אף NAL 5. זה המקרה שנמדד.
    assert has_idr(nal(7, 7) + nal(6, 448) + nal(9, 224) + nal(1, 224)) is False

    # 3. ריק / בלי slices — "לא יודע", ולכן תקין. ספק לא מפעיל קידוד.
    assert has_idr(b"") is True
    assert has_idr(nal(7) + nal(8) + nal(6, 5)) is True

    # 4. NAL בסוף הבאפר בלי בתים אחריו אינו מפיל
    assert has_idr(nal(5) + b"\x00\x00\x01") is True

    # 5. הבדיקה המלאה: ffmpeg שמחזיר open-GOP ⇒ True (צריך קידוד מחדש)
    import subprocess as _sp

    class _R:
        def __init__(self, out): self.stdout = out

    real = _sp.run
    try:
        _sp.run = lambda *a, **k: _R(nal(7, 3) + nal(1, 50))
        assert probe("x") is True, "open-GOP לא זוהה"
        _sp.run = lambda *a, **k: _R(nal(5) + nal(1, 50))
        assert probe("x") is False, "זרם תקין סומן בטעות"
        _sp.run = lambda *a, **k: _R(b"")
        assert probe("x") is False, "פלט ריק הפעיל קידוד מחדש"

        def _boom(*a, **k):
            raise OSError("ffmpeg לא קיים")
        _sp.run = _boom
        assert probe("x") is False, "כשל בבדיקה הפעיל קידוד מחדש"
    finally:
        _sp.run = real

    # 6. הארגומנטים עצמם — מורצים ונבדקים, לא מחופשים כטקסט. הביטוי
    #    בנוי מ-f-string, ולכן חיפוש "n_forced*4" במקור היה נכשל גם כשהוא
    #    נכון — זה נתפס כאן בבדיקה.
    tree = ast.parse(s)
    av = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in (
                "_HLS_IDR_SEC", "_OPENGOP_VARGS"):
            exec(ast.get_source_segment(s, n), av)
    args = av.get("_OPENGOP_VARGS")
    assert args, "_OPENGOP_VARGS לא נמצא"
    assert "libx264" in args, "לא מקודדים מחדש"
    assert args[args.index("-forced-idr") + 1] == "1", \
        "בלי forced-idr ייווצרו שוב I-slices ולא IDR"
    # 4 שניות = אורך הסגמנט ב-_hls_fix_start (hls_time 4), כדי שכל
    # סגמנט יתחיל בנקודה שממנה MSE יכול להתחיל.
    assert args[args.index("-force_key_frames") + 1] == \
        "expr:gte(t,n_forced*4)", args[args.index("-force_key_frames") + 1]
    return True


def main():
    if not os.path.exists(PATH):
        sys.exit(f"לא נמצא {PATH}")
    src = open(PATH, encoding="utf-8").read()

    if "--revert" in sys.argv:
        if not os.path.exists(BAK):
            sys.exit(f"אין גיבוי ב-{BAK}")
        shutil.copy2(BAK, PATH)
        print(f"✓ שוחזר מ-{BAK}")
        return

    if MARK in src:
        print("כבר מותקן.")
        return

    out = src
    for label, a, n in EDITS:
        if out.count(a) != 1:
            sys.exit(f"✗ העוגן '{label}' נמצא {out.count(a)} פעמים — לא נוגע בכלום.")
        out = out.replace(a, n)

    validate(out)
    print("✓ כל הבדיקות עברו")

    if "--check" in sys.argv:
        print("--check: שום דבר לא נכתב.")
        return

    shutil.copy2(PATH, BAK)
    with open(PATH, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(f"✓ הוחל. גיבוי: {BAK}")
    print()
    print("הפאץ' משנה את ההחלטה בתוך /hls-relay/_fix בלבד. כדי שערוץ")
    print("open-GOP יגיע לשם, הכתובת שלו בקטלוג צריכה לעבור מ-")
    print("  /hls-relay/<ספק>/...   ל-   /hls-relay/_fix/<ספק>/...")
    print("זה נעשה בפאנל, בשדה הקישור של הערוץ.")


if __name__ == "__main__":
    main()
