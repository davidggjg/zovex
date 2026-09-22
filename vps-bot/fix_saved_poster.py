#!/usr/bin/env python3
"""fix_saved_poster — הפוסטר מוטמע בתוך קובץ הווידאו, ומשמש גם כתצוגה המקדימה.

## הבקשה

בהעלאה מהטלפון (טלפון → שרת → טלגרם) הפוסטר של הסרט יוטמע ממש בתוך
הקובץ, ולא רק "יודבק" כתמונה בטלגרם כמו שבוטים אחרים עושים.

## מה נעשה, בסדר הזה

1. **זיהוי** — אותו recognize_media שקורא את הכיתוב (fix_upload_read_caption).
2. **רק כשהזיהוי ודאי.** פוסטר שגוי שמוטמע בקובץ נשאר בו לתמיד ועובר עם
   כל העברה. לכן: השנה מהכיתוב תואמת לתוצאה, או שהשם שחיפשנו הוא בדיוק
   שם התוצאה. בספק — בלי פוסטר, ונשארים עם פריים מהסרט כמו היום.
3. **הטמעה בלי קידוד מחדש** (‎-c copy), כך שהאיכות לא נוגעת ושזה לוקח שניות:
   - MP4 — הפוסטר נכתב כ-covr במטא־דאטה. נבדק: 2 רצועות trak לפני ואחרי,
     כלומר הנגן לא רואה רצועה נוספת. ובונוס: ה-moov עובר לתחילת הקובץ, אז
     הוא גם נפתח מהר יותר בסטרימינג.
   - MKV — קובץ מצורף (Attachments), גם הוא לא רצועה: TrackEntry נשאר 2.
     גופנים של כתוביות שכבר מצורפים לא נוגעים — המטא־דאטה מכוונת רק לקובץ
     החדש.
4. **תצוגה מקדימה בטלגרם** מהפוסטר, מוקטן לגבולות של טלגרם (320px, 200KB).

## למה זה לא שובר ניגון

נבדק לפני הכתיבה: גם עם פוסטר של 2000×3000 — גדול פי שש מסרט ב-720p —
ffmpeg בוחר את הסרט ולא את העטיפה, ב-MKV וב-MP4. ושני המקומות היחידים
בשרת שממפים זרמים לוקחים ‎0:v:0 בלבד.

כל כישלון בדרך — אין זיהוי, אין מקום בדיסק, ffmpeg נכשל, התוצאה לא
תואמת במשך — משאיר את הקובץ המקורי כמו שהוא וממשיך להעלאה הרגילה.

    python3 fix_saved_poster.py --check
    python3 fix_saved_poster.py
    python3 fix_saved_poster.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_saved_poster"
MARK = "fix_saved_poster"

HELPERS = '''# ── [fix_saved_poster] פוסטר מוטמע בקובץ ─────────────────────────────────
# ראה fix_saved_poster.py. כל פונקציה כאן נכשלת "בשקט" — מחזירה ריק/False
# ומשאירה את ההעלאה בדיוק כמו שהייתה בלי הפאץ'.
_POSTER_MIN_FREE = 512 * 1024 * 1024


async def _saved_find_poster(job_id: str, caption: str, filename: str) -> str:
    """פוסטר מ-TMDB — רק כשהזיהוי חד-משמעי.

    פוסטר שגוי שמוטמע בתוך הקובץ נשאר בו לתמיד ועובר עם כל העברה, ולכן
    בספק לא מטמיעים כלום. "חד-משמעי" = השנה מהכיתוב תואמת לתוצאה, או
    שהשם שחיפשנו הוא בדיוק שם התוצאה.
    """
    try:
        q, opts, year, _tr = await recognize_media(caption or "", filename or "")
    except Exception as e:
        log.warning("poster: זיהוי נכשל: %s", e)
        return ""
    if not opts:
        return ""
    top = opts[0]
    names = {_norm_title(top.get(k) or "") for k in ("title", "original", "en_title")}
    names.discard("")
    sure = bool(year and str(top.get("year") or "") == str(year)) or \\
        (_norm_title(q or "") in names)
    url = top.get("poster") or ""
    if not sure or not url:
        log.info("poster: %s — הזיהוי לא ודאי (%s ↔ %s %s), בלי פוסטר",
                 filename, q, top.get("title"), top.get("year"))
        return ""
    try:
        async with httpx.AsyncClient(timeout=20) as cx:
            r = await cx.get(url)
        if r.status_code != 200 or r.content[:3] != b"\\xff\\xd8\\xff":
            return ""
        dest = SAVED_TMP_DIR / f"{job_id}.poster.jpg"
        dest.write_bytes(r.content)
        log.info("poster: %s ← %s (%s)", filename, top.get("title"), top.get("year"))
        return str(dest)
    except Exception as e:
        log.warning("poster: הורדת הפוסטר נכשלה: %s", e)
        return ""


def _saved_probe_streams(probe: str, path: str) -> dict:
    out = subprocess.run(
        [probe, "-v", "error", "-show_entries",
         "stream=codec_type:stream_disposition=attached_pic:format=duration",
         "-of", "json", path],
        capture_output=True, timeout=120).stdout
    return json.loads(out or b"{}")


def _saved_embed_cover(path: pathlib.Path, poster: str) -> bool:
    """מטמיע את הפוסטר כעטיפה בתוך הקובץ, בלי לקודד מחדש. חוסם — ב-executor.

    MP4: covr במטא־דאטה, לא רצועה. MKV: קובץ מצורף, לא רצועה. כל כישלון
    משאיר את המקור כמו שהוא.
    """
    exe, probe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    ext = path.suffix.lower()
    if not exe or not probe or ext not in (".mp4", ".m4v", ".mov", ".mkv"):
        return False
    tmp = path.with_name(path.name + ".cover" + ext)
    try:
        size = path.stat().st_size
        if shutil.disk_usage(path.parent).free < size + _POSTER_MIN_FREE:
            log.warning("poster: אין מקום לעותק של %s — בלי הטמעה", path.name)
            return False
        info = _saved_probe_streams(probe, str(path))
        streams = info.get("streams") or []
        if any((s.get("disposition") or {}).get("attached_pic") for s in streams):
            return False                   # כבר יש עטיפה — לא נוגעים בה
        n_video = sum(1 for s in streams if s.get("codec_type") == "video")
        n_audio = sum(1 for s in streams if s.get("codec_type") == "audio")
        n_att = sum(1 for s in streams if s.get("codec_type") == "attachment")
        dur0 = float((info.get("format") or {}).get("duration") or 0)
        if ext == ".mkv":
            # המטא־דאטה מכוונת לקובץ המצורף החדש בלבד (t:N). ‎-metadata:s:t
            # בלי מספר היה דורס גם את הגופנים של הכתוביות, שכבר מצורפים.
            cmd = [exe, "-v", "error", "-y", "-i", str(path), "-map", "0",
                   "-c", "copy", "-attach", poster,
                   f"-metadata:s:t:{n_att}", "mimetype=image/jpeg",
                   f"-metadata:s:t:{n_att}", "filename=cover.jpg", str(tmp)]
        else:
            cmd = [exe, "-v", "error", "-y", "-i", str(path), "-i", poster,
                   "-map", "0:v", "-map", "0:a?", "-map", "0:s?", "-map", "1",
                   "-c", "copy", f"-disposition:v:{n_video}", "attached_pic",
                   "-movflags", "+faststart", str(tmp)]
        r = subprocess.run(cmd, capture_output=True, timeout=1800)
        if r.returncode != 0 or not tmp.exists():
            log.warning("poster: ffmpeg נכשל על %s: %s", path.name,
                        (r.stderr or b"")[-200:].decode("utf-8", "replace"))
            return False
        # לא מחליפים את המקור עד שמוכח שלא אבד בו כלום
        after = _saved_probe_streams(probe, str(tmp))
        st2 = after.get("streams") or []
        v2 = sum(1 for s in st2 if s.get("codec_type") == "video"
                 and not (s.get("disposition") or {}).get("attached_pic"))
        a2 = sum(1 for s in st2 if s.get("codec_type") == "audio")
        dur2 = float((after.get("format") or {}).get("duration") or 0)
        if v2 != n_video or a2 != n_audio or tmp.stat().st_size < size * 0.99 \\
                or (dur0 and abs(dur2 - dur0) > 1.5):
            log.warning("poster: התוצאה של %s לא תואמת למקור — לא מחליפים "
                        "(וידאו %s→%s, קול %s→%s, משך %.1f→%.1f)",
                        path.name, n_video, v2, n_audio, a2, dur0, dur2)
            return False
        os.replace(tmp, path)
        return True
    except Exception as e:
        log.warning("poster: הטמעה נכשלה על %s: %s", path.name, e)
        return False
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _saved_poster_thumb(poster: str) -> str:
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


async def _saved_send('''

A1 = "async def _saved_send("

A2 = '''    thumb = ""          # מוגדר לפני try כדי שגם ה-finally יוכל למחוק אותו
'''
N2 = '''    thumb = ""          # מוגדר לפני try כדי שגם ה-finally יוכל למחוק אותו
    _poster = _pthumb = ""   # [fix_saved_poster] גם הם נמחקים ב-finally
'''

A3 = '''        total = path.stat().st_size
        job.update(stage="telegram", pct=0, sent=0, total=total,
'''
N3 = '''        # [fix_saved_poster] פוסטר מוטמע בתוך הקובץ, ותצוגה מקדימה ממנו.
        # לפני שמודדים את הגודל, כי ההטמעה משנה אותו. כל כישלון כאן משאיר
        # את ההעלאה בדיוק כמו קודם: פריים מהסרט.
        try:
            _poster = await _saved_find_poster(job_id, caption, filename)
            if _poster:
                _pl = asyncio.get_running_loop()
                if await _pl.run_in_executor(None, _saved_embed_cover, path, _poster):
                    job["poster"] = "embedded"
                _pthumb = await _pl.run_in_executor(None, _saved_poster_thumb, _poster)
        except Exception as _pe:
            log.warning("poster: %s", _pe)
        total = path.stat().st_size
        job.update(stage="telegram", pct=0, sent=0, total=total,
'''

A4 = '''        thumb = await _loop.run_in_executor(
            None, _saved_thumb, path, min(10, max(1, _dur // 10)) if _dur else 1)
'''
N4 = '''        # [fix_saved_poster] הפוסטר קודם; בלעדיו — פריים מהסרט, כמו תמיד
        thumb = _pthumb or await _loop.run_in_executor(
            None, _saved_thumb, path, min(10, max(1, _dur // 10)) if _dur else 1)
'''

A5 = '''            if thumb:
                pathlib.Path(thumb).unlink(missing_ok=True)
'''
N5 = '''            if thumb:
                pathlib.Path(thumb).unlink(missing_ok=True)
            for _f in (_poster, _pthumb):      # [fix_saved_poster]
                if _f:
                    pathlib.Path(_f).unlink(missing_ok=True)
'''

EDITS = [("התצוגה המקדימה", A4, N4), ("משתני הניקוי", A2, N2),
         ("שלב הפוסטר", A3, N3), ("ניקוי", A5, N5)]


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
    for f in ("_saved_find_poster", "_saved_embed_cover", "_saved_poster_thumb",
              "_saved_probe_streams", "_saved_send"):
        assert names.count(f) == 1, f"{f} חסרה או כפולה"
    body = fn_source(s, "_saved_send")
    for piece in ("_saved_find_poster(job_id, caption, filename)",
                  "_saved_embed_cover, path, _poster",
                  "thumb = _pthumb or await",
                  "for _f in (_poster, _pthumb):"):
        assert piece in body, f"חסר ב-_saved_send: {piece}"
    # הפוסטר נמדד לפני הגודל שנשלח לטלגרם — ההטמעה משנה אותו
    assert body.index("_saved_find_poster") < body.index("total = path.stat().st_size"), \
        "הגודל נמדד לפני ההטמעה"


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
    if "return q, opts, year, is_trailer" not in s:
        print("❌ חסר recognize_media החדש — הרץ קודם fix_upload_read_caption.py")
        return 1
    if s.count(A1) != 1:
        print(f"❌ _saved_send נמצאה {s.count(A1)} פעמים (ציפיתי 1). לא נוגע.")
        return 1
    out = s.replace(A1, HELPERS, 1)
    for name, a, b in EDITS:
        body = fn_source(out, "_saved_send")
        if out.count(a) != 1 or body is None or a.rstrip("\n") not in body:
            print(f"❌ העוגן '{name}' לא נמצא פעם אחת בתוך _saved_send. לא נוגע.")
            return 1
        out = out.replace(a, b, 1)
    try:
        validate(out)
    except Exception as e:
        print(f"❌ התוצאה לא תקינה ({e}) — לא נכתב כלום.")
        return 1
    print(f"יעד:   {PATH}")
    print("שינוי: בהעלאה מהטלפון — פוסטר מוטמע בקובץ ותצוגה מקדימה ממנו")
    if arg == "--check":
        print("--check: שום דבר לא נכתב.")
        return 0
    if not os.path.exists(BAK):
        shutil.copyfile(PATH, BAK)
    tmp = PATH + ".tmp_poster"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, PATH)
    print(f"✓ הוחל · גיבוי: {BAK}")
    print("  הרץ:  systemctl restart zovex-bot")
    print("  לביטול:  python3 fix_saved_poster.py --revert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
