#!/usr/bin/env python3
"""fix_custom_poster — פוסטר שבחרת בעצמך, מוטמע בקובץ במקום זה של TMDB.

## הבקשה

"לפעמים אני רוצה לשים פוסטר בלעדי שיצרתי וערכתי — אין צורך שה-API יזהה."

## מה נעשה

1. **נתיב חדש** ‎/panel/saved-upload/poster?job=…‎ — האפליקציה שולחת אליו את
   התמונה אחרי begin ולפני finish. אותו קוד העלאה, אותה הגנת ניחוש.
2. **השרת מנרמל** את התמונה ל-JPEG (עד 1500 פיקסלים בצד, בלי הגדלה).
   עטיפה ב-MP4 חייבת להיות JPEG או PNG, ותמונה שלא נפתחת נדחית כבר כאן —
   לא מתגלה רק אחרי שהסרט כולו עלה.
3. **ב-_saved_send:** יש פוסטר שלך — הוא מוטמע, ו-TMDB לא נשאל בכלל. אין —
   הכל כמו קודם (fix_saved_poster).
4. **פוסטר שלך מחליף עטיפה קיימת.** האוטומטי לא נוגע בקובץ שכבר יש בו
   עטיפה; כשבחרת תמונה במפורש, זה בדיוק מה שביקשת. ההחלפה ממפה ‎0:V‎ —
   וידאו שאינו עטיפה — כך שהעטיפה הישנה נשארת בחוץ וכל השאר (סרט, קול,
   כתוביות, גופנים) עובר כמו שהוא. אותן בדיקות לפני ההחלפה: מספר רצועות
   וידאו וקול ומשך זהים למקור, אחרת המקור נשאר.

דורש fix_saved_poster.

    python3 fix_custom_poster.py --check
    python3 fix_custom_poster.py
    python3 fix_custom_poster.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_custom_poster"
MARK = "fix_custom_poster"

# ── הנתיב החדש, לפני נתיב הסטטוס ────────────────────────────────────────────
A_ROUTE = '@api.get("/panel/saved-upload/status")\n'
N_ROUTE = '''# ── [fix_custom_poster] פוסטר שבחרת בעצמך ──────────────────────────────────
# ראה fix_custom_poster.py. נשלח אחרי begin ולפני finish, ונשמר ליד הקובץ
# הזמני. _saved_send מעדיף אותו על פני TMDB ומוחק אותו בסוף.
SAVED_POSTER_MAX = 15 * 1024 * 1024


def _saved_normalize_poster(src: str, dest: str) -> bool:
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


@api.post("/panel/saved-upload/poster")
async def saved_upload_poster(request: Request, job: str = ""):
    _check_upload_code(request, request.headers.get("x-upload-code", ""))
    j = _saved_jobs.get(job)
    if not j or "path" not in j:
        raise HTTPException(status_code=404, detail="משימה לא נמצאה")
    if j.get("stage") != "receiving":
        raise HTTPException(status_code=409,
                            detail="הסרטון כבר בדרך לטלגרם — מאוחר מדי לפוסטר")
    if int(request.headers.get("content-length") or 0) > SAVED_POSTER_MAX:
        raise HTTPException(status_code=413, detail="התמונה גדולה מ-15MB")
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > SAVED_POSTER_MAX:
            raise HTTPException(status_code=413, detail="התמונה גדולה מ-15MB")
    if not data:
        raise HTTPException(status_code=400, detail="התקבלה תמונה ריקה")
    # job הוא מפתח קיים ב-_saved_jobs (hex שהשרת יצר), ולכן בטוח כשם קובץ
    SAVED_TMP_DIR.mkdir(parents=True, exist_ok=True)
    src = SAVED_TMP_DIR / f"{job}.mine.src"
    dest = SAVED_TMP_DIR / f"{job}.mine.jpg"
    src.write_bytes(bytes(data))
    try:
        ok = await asyncio.get_running_loop().run_in_executor(
            None, _saved_normalize_poster, str(src), str(dest))
    finally:
        src.unlink(missing_ok=True)
    if not ok:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400,
                            detail="לא הצלחתי לקרוא את התמונה — נסה JPG או PNG")
    j["custom_poster"] = str(dest)
    log.info("poster: פוסטר משלך למשימה %s (%d KB)", job, len(data) // 1024)
    return {"ok": True}


@api.get("/panel/saved-upload/status")
'''

# ── _saved_embed_cover: החלפת עטיפה קיימת כשביקשו במפורש ──────────────────
A_SIG = "def _saved_embed_cover(path: pathlib.Path, poster: str) -> bool:\n"
N_SIG = ("def _saved_embed_cover(path: pathlib.Path, poster: str,\n"
         "                       replace: bool = False) -> bool:\n")

A_HAS = '''        if any((s.get("disposition") or {}).get("attached_pic") for s in streams):
            return False                   # כבר יש עטיפה — לא נוגעים בה
        n_video = sum(1 for s in streams if s.get("codec_type") == "video")
'''
N_HAS = '''        has_cover = any((s.get("disposition") or {}).get("attached_pic")
                        for s in streams)
        if has_cover and not replace:
            return False                   # כבר יש עטיפה — לא נוגעים בה
        # [fix_custom_poster] רק וידאו שאינו עטיפה. עטיפה קיימת שמוחלפת לא
        # נספרת — היא בדיוק מה שיוצא מהקובץ.
        n_video = sum(1 for s in streams if s.get("codec_type") == "video"
                      and not (s.get("disposition") or {}).get("attached_pic"))
'''

A_MKV = '''            cmd = [exe, "-v", "error", "-y", "-i", str(path), "-map", "0",
                   "-c", "copy", "-attach", poster,
'''
N_MKV = '''            # [fix_custom_poster] בהחלפה: ‎0:V‎ = וידאו שאינו עטיפה. ב-MKV
            # עטיפה היא קובץ מצורף שמופיע כווידאו, וגופנים נשארים ב-‎0:t‎.
            keep = (["-map", "0:V", "-map", "0:a?", "-map", "0:s?", "-map", "0:t?"]
                    if has_cover else ["-map", "0"])
            cmd = [exe, "-v", "error", "-y", "-i", str(path), *keep,
                   "-c", "copy", "-attach", poster,
'''

A_MP4 = '''                   "-map", "0:v", "-map", "0:a?", "-map", "0:s?", "-map", "1",
'''
N_MP4 = '''                   "-map", "0:V", "-map", "0:a?", "-map", "0:s?", "-map", "1",
'''

# ── _saved_send: פוסטר שלך קודם ─────────────────────────────────────────────
A_SEND = '''            _poster = await _saved_find_poster(job_id, caption, filename)
            if _poster:
                _pl = asyncio.get_running_loop()
                if await _pl.run_in_executor(None, _saved_embed_cover, path, _poster):
'''
N_SEND = '''            # [fix_custom_poster] פוסטר שבחרת קודם; רק בלעדיו — TMDB
            _mine = job.get("custom_poster") or ""
            if _mine and not os.path.exists(_mine):
                _mine = ""
            _poster = _mine or await _saved_find_poster(job_id, caption, filename)
            if _poster:
                _pl = asyncio.get_running_loop()
                if await _pl.run_in_executor(None, _saved_embed_cover, path, _poster,
                                             bool(_mine)):
'''

# ── הנתיב הפנימי לא יוצא בסטטוס הפומבי ────────────────────────────────────
A_PUB = '''    return {k: v for k, v in job.items() if k not in ("parts", "path")}
'''
N_PUB = '''    return {k: v for k, v in job.items()
            if k not in ("parts", "path", "custom_poster")}
'''

# (שם, עוגן, חדש, הפונקציה שבה העוגן חייב לשבת — None = רמת המודול)
EDITS = [
    ("חתימת ההטמעה", A_SIG, N_SIG, None),
    ("זיהוי עטיפה קיימת", A_HAS, N_HAS, "_saved_embed_cover"),
    ("מיפוי MKV", A_MKV, N_MKV, "_saved_embed_cover"),
    ("מיפוי MP4", A_MP4, N_MP4, "_saved_embed_cover"),
    ("בחירת הפוסטר", A_SEND, N_SEND, "_saved_send"),
    ("סטטוס פומבי", A_PUB, N_PUB, "_saved_public"),
    ("נתיב הפוסטר", A_ROUTE, N_ROUTE, None),
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
    for f in ("saved_upload_poster", "_saved_normalize_poster",
              "_saved_embed_cover", "_saved_send", "saved_upload_status"):
        assert names.count(f) == 1, f"{f} חסרה או כפולה"
    emb = fn_source(s, "_saved_embed_cover")
    assert "replace: bool = False" in emb and "if has_cover and not replace" in emb
    assert '"0:v"' not in emb, "נשאר מיפוי 0:v שמכניס עטיפה ישנה"
    send = fn_source(s, "_saved_send")
    assert "_mine or await _saved_find_poster" in send
    # הנתיב נרשם לפני הסטטוס, ואחרי ש-_saved_jobs ו-_check_upload_code הוגדרו
    assert s.index('"/panel/saved-upload/poster"') < s.index('"/panel/saved-upload/status"')
    assert s.index("def _check_upload_code") < s.index('"/panel/saved-upload/poster"')


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
    if "fix_saved_poster" not in s:
        print("❌ חסר fix_saved_poster — הרץ אותו קודם")
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
    print("שינוי: בהעלאה מהטלפון — פוסטר שבחרת מוטמע במקום זה של TMDB")
    if arg == "--check":
        print("--check: שום דבר לא נכתב.")
        return 0
    if not os.path.exists(BAK):
        shutil.copyfile(PATH, BAK)
    tmp = PATH + ".tmp_custom_poster"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, PATH)
    print(f"✓ הוחל · גיבוי: {BAK}")
    print("  הרץ:  systemctl restart zovex-bot")
    print("  לביטול:  python3 fix_custom_poster.py --revert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
