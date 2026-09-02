#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מתקן שני דברים בהעלאה ל"הודעות שמורות".

① אורך הווידאו נרשם 0:00 והתצוגה המקדימה שחורה.

   השרת קורא ל-send_video בלי duration/width/height. Pyrogram אינו בודק את
   הקובץ בעצמו — מה שלא נמסר לו נשלח כאפס, וטלגרם שומר בדיוק את מה שאמרו לו.
   הקובץ עצמו תקין לגמרי (לוחצים פליי והווידאו שם), אבל המטא־דאטה שבהודעה
   היא אפסים, וכל דבר שיקרא אותה בהמשך יקבל אפס.

   האורך והמידות מגיעים עכשיו מהאפליקציה, שיודעת אותם מבורר הגלריה. אם הם
   חסרים — למשל בקשה שנשלחה מגרסה ישנה של האפליקציה — השרת מנסה להוציא אותם
   מהקובץ עם ffprobe. אם ffprobe אינו מותקן, מתנהגים כמו קודם ולא נכשלים.
   באותה הזדמנות נוצרת גם תמונה ממוזערת עם ffmpeg, כי בלעדיה טלגרם מציג
   ריבוע שחור.

② קליטת הקובץ כותבת לדיסק בתוך לולאת האירועים.

   כל נתח שמגיע נכתב מיד, כלומר קריאת מערכת אחת לכל ~64KB. בזמן שהשרת מזרים
   וידאו לצופים זו אותה לולאה יחידה שמשרתת את כולם, וכל כתיבה כזאת עוצרת
   אותה לרגע. חיץ של מגה־בייט מצמצם את זה פי כמה־עשרות: הכתיבה לזיכרון היא
   העתקה בלבד, וקריאת המערכת קורית פעם למגה־בייט. זה גם מיטיב עם ההעלאה
   עצמה, שנתקעת פחות כשהשרת עסוק.

    python3 fix_saved_video_meta.py          # מחיל
    python3 fix_saved_video_meta.py --undo   # מחזיר
"""
import datetime, glob, os, pathlib, py_compile, shutil, sys, tempfile

TARGET = pathlib.Path("/opt/zovex-bot/main.py")

# ─────────────────────────────────────────────────────────────────────────────
# כל החלפה היא (ישן, חדש). הישן חייב להופיע בדיוק פעם אחת — אחרת עוצרים בלי
# לגעת בקובץ. זו ההגנה שתפסה בעבר תיקון שנכתב מול קוד מנוחש ולא מול הקוד
# האמיתי, ולכן היא נשמרת גם כאן.
# ─────────────────────────────────────────────────────────────────────────────

IMPORTS_OLD = "import asyncio, hmac, os, pathlib, re, time, uuid\n"
IMPORTS_NEW = "import asyncio, hmac, os, pathlib, re, shutil, subprocess, time, uuid\n"

HELPERS_OLD = '''async def _saved_send(job_id: str, path: pathlib.Path, filename: str, caption: str):
    """שלב ②: מעלה מהשרת לטלגרם, ומוחק את הקובץ הזמני בכל מקרה."""
    job = _saved_jobs[job_id]
    try:
'''

HELPERS_NEW = '''def _saved_probe(path):
    """אורך ומידות מהקובץ עצמו. חוסם — להריץ רק בתוך executor.

    גיבוי בלבד: הערכים מגיעים מהאפליקציה. אם ffprobe אינו מותקן מחזירים
    מילון ריק, וההעלאה ממשיכה בדיוק כמו קודם.
    """
    exe = shutil.which("ffprobe")
    if not exe:
        return {}
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height:format=duration", "-of", "default=nw=1:nk=1",
             str(path)],
            capture_output=True, text=True, timeout=90).stdout.split()
        w, h, d = int(float(out[0])), int(float(out[1])), int(float(out[2]))
        return {"width": w, "height": h, "duration": d}
    except Exception:
        return {}


def _saved_thumb(path, when):
    """תמונה ממוזערת. בלעדיה טלגרם מציג ריבוע שחור. חוסם — בתוך executor."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return ""
    out = pathlib.Path(str(path) + ".thumb.jpg")
    try:
        subprocess.run(
            [exe, "-y", "-v", "error", "-ss", str(max(0, int(when))), "-i",
             str(path), "-frames:v", "1", "-vf", "scale=320:-2", str(out)],
            capture_output=True, timeout=120)
        if out.exists() and out.stat().st_size > 0:
            return str(out)
    except Exception:
        pass
    try:
        out.unlink(missing_ok=True)
    except Exception:
        pass
    return ""


async def _saved_send(job_id: str, path: pathlib.Path, filename: str, caption: str):
    """שלב ②: מעלה מהשרת לטלגרם, ומוחק את הקובץ הזמני בכל מקרה."""
    job = _saved_jobs[job_id]
    thumb = ""          # מוגדר לפני try כדי שגם ה-finally יוכל למחוק אותו
    try:
'''

SEND_OLD = '''        await bot["client"].send_video(
            "me", str(path), caption=caption or filename,
            file_name=filename, progress=_progress)
'''

SEND_NEW = '''        # המטא־דאטה שנשלחת לטלגרם. בלעדיה ההודעה מציגה 0:00 ותצוגה מקדימה
        # שחורה — טלגרם שומר בדיוק את מה שנמסר לו, ולא בודק את הקובץ.
        meta = dict(job.get("meta") or {})
        _loop = asyncio.get_running_loop()
        if not all(meta.get(k) for k in ("duration", "width", "height")):
            for k, v in (await _loop.run_in_executor(
                    None, _saved_probe, path)).items():
                if not meta.get(k):
                    meta[k] = v
        _dur = int(meta.get("duration") or 0)
        thumb = await _loop.run_in_executor(
            None, _saved_thumb, path, min(10, max(1, _dur // 10)) if _dur else 1)

        await bot["client"].send_video(
            "me", str(path), caption=caption or filename,
            file_name=filename, duration=_dur,
            width=int(meta.get("width") or 0),
            height=int(meta.get("height") or 0),
            thumb=thumb or None, supports_streaming=True,
            progress=_progress)
'''

CLEANUP_OLD = '''    finally:
        # נמחק גם בכישלון: אחרת כל ניסיון שנפל משאיר גיגה־בייטים על הדיסק.
        try:
            path.unlink(missing_ok=True)
        except Exception as e:
            log.warning("מחיקת קובץ זמני נכשלה: %s", e)
'''

CLEANUP_NEW = '''    finally:
        # נמחק גם בכישלון: אחרת כל ניסיון שנפל משאיר גיגה־בייטים על הדיסק.
        try:
            path.unlink(missing_ok=True)
            if thumb:
                pathlib.Path(thumb).unlink(missing_ok=True)
        except Exception as e:
            log.warning("מחיקת קובץ זמני נכשלה: %s", e)
'''

QUERY_OLD = '''    qp = request.query_params
    raw_name = unquote(qp.get("name") or "video.mp4")
    caption = unquote(qp.get("caption") or "")
'''

QUERY_NEW = '''    qp = request.query_params
    raw_name = unquote(qp.get("name") or "video.mp4")
    caption = unquote(qp.get("caption") or "")

    # אורך ומידות מהאפליקציה, שיודעת אותם מבורר הגלריה. ערך לא סביר נזרק
    # ומטופל כחסר, ואז השרת ינסה להוציא אותו מהקובץ בעצמו.
    def _qint(key, cap):
        try:
            v = int(float(qp.get(key) or 0))
        except (TypeError, ValueError):
            return 0
        return v if 0 < v <= cap else 0
    meta = {"duration": _qint("duration", 86400),
            "width": _qint("width", 16384),
            "height": _qint("height", 16384)}
'''

JOB_OLD = '''    _saved_jobs[job_id] = {"stage": "receiving", "pct": 0, "received": 0,
                           "total": declared, "name": safe, "started": time.time()}
'''

JOB_NEW = '''    _saved_jobs[job_id] = {"stage": "receiving", "pct": 0, "received": 0,
                           "total": declared, "name": safe, "started": time.time(),
                           "meta": meta}
'''

# חיץ בקליטה: כתיבה לכל נתח היא קריאת מערכת בתוך לולאת האירועים שמשרתת גם
# את כל הצופים. עם חיץ של מגה־בייט הכתיבה היא העתקה לזיכרון, וקריאת המערכת
# קורית פעם למגה־בייט במקום פעם ל-64KB.
BUF_OLD = '''        with path.open("wb") as f:
'''

BUF_NEW = '''        with path.open("wb", buffering=1024 * 1024) as f:
'''

EDITS = [
    ("שורת הייבוא", IMPORTS_OLD, IMPORTS_NEW),
    ("פונקציות העזר", HELPERS_OLD, HELPERS_NEW),
    ("הקריאה ל-send_video", SEND_OLD, SEND_NEW),
    ("מחיקת הקבצים הזמניים", CLEANUP_OLD, CLEANUP_NEW),
    ("קריאת פרמטרי המטא־דאטה", QUERY_OLD, QUERY_NEW),
    ("רשומת המשימה", JOB_OLD, JOB_NEW),
    ("חיץ הכתיבה", BUF_OLD, BUF_NEW),
]

DONE_MARK = "def _saved_probe("


def _fail(msg):
    print("❌ " + msg)
    print("   לא שונה כלום.")
    sys.exit(1)


def apply_edits(src):
    """מחיל את כל ההחלפות, ונכשל אם נקודת עיגון כלשהי אינה יחידה."""
    for label, old, new in EDITS:
        n = src.count(old)
        if n != 1:
            _fail(f"{label}: נקודת העיגון נמצאה {n} פעמים (ציפינו לאחת)")
        src = src.replace(old, new, 1)
    return src


def undo():
    baks = sorted(glob.glob(str(TARGET) + ".bak-vidmeta-*"))
    if not baks:
        _fail("לא נמצא גיבוי")
    shutil.copy2(baks[-1], TARGET)
    print(f"↩️  שוחזר מ-{os.path.basename(baks[-1])}")
    print("   הרץ:  systemctl restart zovex-bot")


def main():
    if not TARGET.exists():
        _fail(f"לא נמצא {TARGET}")
    src = TARGET.read_text(encoding="utf-8")

    if DONE_MARK in src:
        print("✓ כבר מוחל. אין מה לעשות.")
        return
    if "/panel/saved-upload" not in src:
        _fail("add_saved_upload.py לא הוחל — הרץ אותו קודם")

    out = apply_edits(src)

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as t:
        t.write(out)
        tmp = t.name
    try:
        py_compile.compile(tmp, doraise=True)
    except py_compile.PyCompileError as e:
        os.unlink(tmp)
        _fail(f"הקוד המתוקן לא מתקמפל: {e}")
    os.unlink(tmp)

    bak = f"{TARGET}.bak-vidmeta-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")

    print("✅ הוחל.")
    print(f"   גיבוי: {os.path.basename(bak)}")
    print()
    for name in ("ffprobe", "ffmpeg"):
        have = shutil.which(name)
        print(f"   {name}: {'יש — ' + have if have else 'אין (לא חובה)'}")
    print()
    print("   הרץ:   systemctl restart zovex-bot")
    print("   נסיגה: python3 fix_saved_video_meta.py --undo")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
