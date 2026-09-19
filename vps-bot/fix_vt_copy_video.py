#!/usr/bin/env python3
"""fix_vt_copy_video — ‎/vt יעתיק וידאו תקין במקום לקודד אותו מחדש.

## הבעיה

קורליין הוא MKV · h264 · **ac3**. הווידאו תקין לחלוטין לדפדפן; רק רצועת
הקול היא כזו שאף דפדפן לא מפענח (Dolby הוסר מ-Chromium מטעמי רישוי).

יש לנו שני מסלולי תיקון, ושניהם לא מתאימים לקובץ הזה:

    /vh   מעתיק וידאו וממיר רק קול  ← בדיוק מה שצריך
          אבל נכשל: הוא בונה את נקודות החיתוך מה-moov של MP4, ולכן
          מחזיר 415 על MKV. נמדד על הקובץ הזה: {"detail":"אין ftyp"}.

    /vt   מקודד מחדש **גם את הווידאו** ב-libx264
          עובד — ומבזבז מעבד על וידאו שלא צריך שום שינוי, בתקרה של שני
          צופים במקביל (VT_MAX_CONCURRENT).

כלומר הקובץ נופל בין הכיסאות: המסלול הזול מסרב לו, והמסלול היקר מטפל בו.

## ככה בדיוק מסווגים את זה בעולם

ל-Jellyfin יש שלוש מדרגות, והשמות שלהן מתארים מדויק את מה שחסר לנו:

    Remux          מחליף מכולה, מעתיק וידאו **וגם** קול
    Direct Stream  מעתיק וידאו, ממיר **רק** את הקול   ← זה המקרה שלנו
    Transcode      מקודד מחדש את הווידאו

‎/vh שלנו הוא Direct Stream, אבל רק לקלט MP4. ‎/vt הוא Transcode. מה
שחסר הוא Direct Stream לקלט MKV — וזה בדיוק מה שהפאצ' הזה מוסיף, בלי
נתיב חדש: ‎/vt שואל פעם אחת מה יש בקובץ, ומעתיק אם מותר.

## התנאי להעתקה

    codec_name == h264   ו-   pix_fmt == yuv420p

שניהם נדרשים. yuv420p10le ו-yuv422p הם h264 לכל דבר ודפדפנים לא מנגנים
אותם, ולכן בדיקת הקודק לבדה הייתה שולחת לצופה זרם שלא ינוגן. כל השאר —
HEVC, mpeg4/xvid של AVI, עומק 10 סיביות — ממשיכים לקידוד המלא, מילה
במילה כמו קודם: הענף הזה נבנה מהטקסט המקורי שנמצא בקובץ, ולא נכתב מחדש.

## מה זה משנה בפועל

וידאו שמועתק לא נוגע במקודד בכלל. המעבד יורד מקידוד מלא לכמעט אפס, וזה
גם מה שהופך את התקרה `VT_MAX_CONCURRENT=2` לבעיה מיותרת — אפשר להעלות
אותה ב-.env אחרי שרואים את העומס האמיתי.

    python3 fix_vt_copy_video.py --check
    python3 fix_vt_copy_video.py
    python3 fix_vt_copy_video.py --revert
"""
import ast
import os
import re
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_vt_copy_video"
MARK = "_vt_video_args"

# ── עוגן 1: הפונקציה החדשה נכנסת לפני _vt_start ─────────────────────────
A_START = "async def _vt_start(chat_id: int, message_id: int):"

HELPER = '''async def _vt_video_args(src: str) -> list:
    """‎-c:v copy כשהווידאו כבר תקין לדפדפן, אחרת קידוד מלא.

    ראה fix_vt_copy_video.py. זו ההבחנה שב-Jellyfin נקראת Direct Stream
    מול Transcode: קובץ MKV עם h264 תקין צריך שנמיר לו רק את הקול.
    """
    try:
        p = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,pix_fmt",
            "-of", "default=nw=1:nk=1", src,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(p.communicate(), timeout=60)
        f = out.decode("utf-8", "replace").split()
    except Exception as e:
        # ffprobe חסר, קלט איטי, כל דבר — נופלים לקידוד המלא. הוא עובד
        # על הכול, ולכן זו הבחירה הבטוחה כשאין ידיעה.
        log.warning("vt: ffprobe נכשל (%s) — מקודד מחדש", e)
        f = []
    if len(f) >= 2 and f[0] == "h264" and f[1] == "yuv420p":
        log.info("vt: %s — וידאו מועתק כמו שהוא", f[0])
        return ["-c:v", "copy"]
    if f:
        log.info("vt: %s/%s — מקודד וידאו מחדש", f[0], f[1] if len(f) > 1 else "?")
    return [
__ENCODE__    ]


'''

# ── עוגן 2: חישוב הארגומנטים לפני בניית הרשימה ──────────────────────────
A_SRC = """        src = _vf_local_url(chat_id, message_id)
        args = [
"""
N_SRC = """        src = _vf_local_url(chat_id, message_id)
        _vt_vargs = await _vt_video_args(src)
        args = [
"""

# ── עוגן 3: שורות הווידאו עצמן, נתפסות כטקסט ולא נכתבות מחדש ────────────
# הבריחה ב-scale=min(1280\\,iw) עוברת שלוש שכבות (מקור הפאצ' → main.py →
# ffmpeg). לכן לא מקלידים אותה שוב: תופסים את הטקסט המקורי ומשתמשים בו
# כמו שהוא גם בענף הקידוד של הפונקציה החדשה.
#
# החיפוש מוגבל לגוף _vt_start בלבד. ניסיון ראשון חיפש בכל הקובץ ותפס את
# ‎_hls_codec_args של הערוצים החיים, שיש בו libx264 משלו — כלומר היה
# משנה את הערוצים החיים במקום את ה-VOD. מגבלת התחום היא מה שמונע את זה.
RE_VARGS = re.compile(
    r'( *"-c:v", "libx264".*?\n)( *"-c:a", "aac", "-ac", "2", "-b:a", "128k",\n)',
    re.S)


def vt_region(s):
    """(התחלה, סוף) של גוף _vt_start, או None."""
    i = s.find(A_START)
    if i < 0:
        return None
    j = i + len(A_START)
    # עד ההגדרה הבאה ברמת המודול.
    m = re.compile(r"\n(?:async def |def |@)", re.M).search(s, j)
    return (i, m.start() if m else len(s))


def validate(s, encode_block):
    compile(s, PATH, "exec")
    tree = ast.parse(s)
    names = {n.name for n in ast.walk(tree)
             if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))}
    assert "_vt_video_args" in names, "הפונקציה לא נוצרה"
    assert "_vt_start" in names, "_vt_start נעלמה"
    # הענף היקר חייב לשרוד מילה במילה — כולל הבריחה של scale. בדיוק פעם
    # אחת: הועבר לפונקציה החדשה, ולא נשאר עותק בפקודה עצמה.
    #
    # לא סופרים "libx264" בכל הקובץ: לערוצים החיים יש libx264 משלהם
    # ב-_hls_codec_args, וספירה גלובלית הייתה נכשלת תמיד.
    assert s.count(encode_block) == 1, "ארגומנטי הקידוד לא נשמרו בדיוק פעם אחת"
    assert "*_vt_vargs," in s, "הארגומנטים לא חוברו לפקודה"
    # הערוצים החיים לא נגעו בהם.
    assert "_hls_codec_args" in s, "_hls_codec_args נעלמה"


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

    if "_vt_start" not in s:
        print("❌ ‎/vt לא קיים ב-main.py. הרץ קודם fix_vod_transcode.py.")
        return 1

    reg = vt_region(s)
    if reg is None:
        print("❌ לא מצאתי את גוף _vt_start.")
        return 1
    lo, hi = reg
    hits = RE_VARGS.findall(s[lo:hi])
    if len(hits) != 1:
        print(f"❌ ארגומנטי הווידאו של /vt נמצאו {len(hits)} פעמים (ציפיתי 1).")
        print("   main.py שונה ממה שציפיתי — לא נוגע בכלום.")
        return 1
    encode_block, audio_line = hits[0]

    for name, anchor in (("_vt_start", A_START), ("בניית args", A_SRC)):
        n = s.count(anchor)
        if n != 1:
            print(f"❌ העוגן '{name}' נמצא {n} פעמים (ציפיתי 1).")
            return 1

    indent = " " * (len(encode_block) - len(encode_block.lstrip(" ")))
    helper = HELPER.replace("__ENCODE__", encode_block)
    # ההחלפה מתבצעת רק בתוך התחום של _vt_start, מאותה סיבה בדיוק.
    body = RE_VARGS.sub(lambda m: f"{indent}*_vt_vargs,\n{m.group(2)}",
                        s[lo:hi], count=1)
    out = s[:lo] + body + s[hi:]
    out = out.replace(A_SRC, N_SRC, 1)
    out = out.replace(A_START, helper + A_START, 1)

    try:
        validate(out, encode_block)
    except Exception as e:
        print(f"❌ התוצאה לא תקינה ({e}) — לא נכתב כלום.")
        return 1

    print(f"יעד:   {PATH}")
    print("שינוי: /vt יעתיק וידאו h264/yuv420p במקום לקודד אותו מחדש")
    if arg == "--check":
        print("--check: שום דבר לא נכתב.")
        return 0

    if not os.path.exists(BAK):
        shutil.copyfile(PATH, BAK)
    tmp = PATH + ".tmp_vtcv"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, PATH)
    print(f"✓ הוחל · גיבוי: {BAK}")
    print("  הרץ:  systemctl restart zovex-bot")
    print("  לביטול:  python3 fix_vt_copy_video.py --revert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
