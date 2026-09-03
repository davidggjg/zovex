#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
העלאה בחלקים מקבילים, במקום זרם אחד ארוך.

המדידה: 3GB ב-56 דקות, כלומר 958KB/שנ׳ — 7.7 מגהביט. זה לא נראה כמו קו
שנגמר לו הרוחב אלא כמו חיבור TCP בודד שאינו ממלא אותו: החלון מוגבל בהשהיה
ובאיבוד חבילות, וזרם אחד מתייצב הרבה מתחת ליכולת הקו. זו בדיוק הסיבה שמנהלי
הורדות ו-S3 multipart פותחים כמה חיבורים.

בדיקה מהשרת שלי לא יכלה לגלות את זה — מרכז נתונים, השהיה נמוכה, בלי איבוד —
ולכן המסקנה הקודמת ש"מקבילית לא תעזור" נבעה מנקודת מבט לא נכונה.

הזרימה כאן:

    begin  → מוקצה קובץ בגודל הסופי ומזהה משימה
    part   → כל חלק נכתב ישירות למקומו בקובץ, בכמה חיבורים במקביל
    finish → כשכל החלקים הגיעו, מתחילה ההעלאה לטלגרם

הכתיבה היא os.pwrite לפי היסט מוחלט, ולכן חלקים מקבילים אינם דורסים זה את זה
ואין מצביע קובץ משותף. כל כתיבה עוברת ל-thread נפרד: השרת מזרים וידאו לצופים
באותה לולאת אירועים, וכתיבה חוסמת בתוכה עוצרת את כולם.

נלווה לזה חידוש: המשימה יודעת אילו חלקים כבר הגיעו, ולכן חיבור שנפל באמצע
מחייב לשלוח מחדש רק את החלקים החסרים ולא את הקובץ כולו — מה שקובע כשמדובר
בשעה של העלאה ברשת סלולרית.

המסלול הישן /panel/saved-upload נשאר כפי שהוא, כדי שגרסת אפליקציה ישנה
תמשיך לעבוד.

דורש ש-fix_saved_limits.py כבר הוחל (משם מגיעות בדיקות הגודל והדיסק).

    python3 fix_saved_parallel.py          # מחיל
    python3 fix_saved_parallel.py --undo   # מחזיר
"""
import datetime, glob, os, pathlib, py_compile, shutil, sys, tempfile

TARGET = pathlib.Path("/opt/zovex-bot/main.py")

ANCHOR_OLD = '''@api.get("/panel/saved-upload/status")
'''

ANCHOR_NEW = '''SAVED_PART_SIZE = 8 * 1024 * 1024     # גודל חלק. גם יחידת הניסיון־מחדש.


def _saved_new_job(total, safe, caption, meta):
    """מקצה קובץ בגודל הסופי ורושם משימה. מחזיר (job_id, path)."""
    SAVED_TMP_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for old in SAVED_TMP_DIR.glob("*"):
        try:
            if now - old.stat().st_mtime > SAVED_STALE_SEC:
                old.unlink()
                log.info("נמחקה שארית העלאה ישנה: %s", old.name)
        except Exception:
            pass
    job_id = uuid.uuid4().hex[:12]
    path = SAVED_TMP_DIR / f"{job_id}_{safe}"
    # הקצאה מראש: כל חלק נכתב להיסט שלו, ולכן הקובץ חייב להיות בגודלו הסופי
    # עוד לפני שהחלק האחרון הגיע.
    with path.open("wb") as f:
        f.truncate(total)
    _saved_jobs[job_id] = {
        "stage": "receiving", "pct": 0, "received": 0, "total": total,
        "name": safe, "caption": caption, "meta": meta,
        "started": time.time(), "path": str(path),
        "part_size": SAVED_PART_SIZE,
        "n_parts": max(1, -(-total // SAVED_PART_SIZE)),
        "parts": set(),
    }
    return job_id, path


def _saved_pwrite(path, offset, data):
    """כתיבה להיסט מוחלט. חוסמת — להריץ רק בתוך executor."""
    fd = os.open(str(path), os.O_WRONLY)
    try:
        written = 0
        while written < len(data):
            written += os.pwrite(fd, data[written:], offset + written)
        return written
    finally:
        os.close(fd)


def _saved_public(job):
    """רשומת המשימה בלי השדות הפנימיים — set אינו ניתן להמרה ל-JSON."""
    return {k: v for k, v in job.items() if k not in ("parts", "path")}


@api.post("/panel/saved-upload/begin")
async def saved_upload_begin(request: Request):
    body = await request.json()
    _check_upload_code(request, str(body.get("code") or ""))
    if _pick_userbot() is None:
        raise HTTPException(status_code=503,
                            detail="אין חשבון משתמש מחובר בשרת")

    total = int(body.get("size") or 0)
    if total <= 0:
        raise HTTPException(status_code=400, detail="חסר גודל הקובץ")

    _gb = 1073741824
    _max = await _saved_max_size()
    if _max and total > _max:
        raise HTTPException(status_code=413, detail=(
            f"הקובץ {total / _gb:.2f}GB, וטלגרם מגביל את החשבון הזה "
            f"ל-{_max / _gb:.2f}GB. חשבון Premium מגיע ל-3.91GB."))
    _free = _saved_free_disk()
    if _free and _free < total + 512 * 1024 * 1024:
        raise HTTPException(status_code=507, detail=(
            f"אין מספיק מקום בשרת: פנויים {_free / _gb:.1f}GB "
            f"והקובץ {total / _gb:.2f}GB"))

    raw_name = str(body.get("name") or "video.mp4")
    safe = re.sub(r"[^\\w.\\-]+", "_", raw_name)[-80:] or "video.mp4"

    def _int(key, cap):
        try:
            v = int(float(body.get(key) or 0))
        except (TypeError, ValueError):
            return 0
        return v if 0 < v <= cap else 0
    meta = {"duration": _int("duration", 86400),
            "width": _int("width", 16384),
            "height": _int("height", 16384)}

    job_id, _ = _saved_new_job(total, safe, str(body.get("caption") or ""), meta)
    _saved_prune_jobs()
    job = _saved_jobs[job_id]
    return {"ok": True, "job": job_id, "part_size": job["part_size"],
            "n_parts": job["n_parts"]}


@api.post("/panel/saved-upload/part")
async def saved_upload_part(request: Request, job: str = "", index: int = -1):
    _check_upload_code(request, request.headers.get("x-upload-code", ""))
    j = _saved_jobs.get(job)
    if not j or "path" not in j:
        raise HTTPException(status_code=404, detail="משימה לא נמצאה")
    if j.get("stage") not in ("receiving",):
        raise HTTPException(status_code=409, detail="המשימה כבר אינה בקליטה")
    if index < 0 or index >= j["n_parts"]:
        raise HTTPException(status_code=400, detail="מספר חלק שגוי")

    part_size = j["part_size"]
    offset = index * part_size
    expect = min(part_size, j["total"] - offset)
    path = pathlib.Path(j["path"])
    loop = asyncio.get_running_loop()

    got = 0
    try:
        async for chunk in request.stream():
            if not chunk:
                continue
            if got + len(chunk) > expect:
                raise HTTPException(status_code=400, detail="החלק ארוך מהצפוי")
            await loop.run_in_executor(
                None, _saved_pwrite, path, offset + got, chunk)
            got += len(chunk)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"קליטת החלק נכשלה: {e}")

    if got != expect:
        # חלק חלקי אינו נרשם, ולכן הוא פשוט יישלח שוב.
        raise HTTPException(status_code=400,
                            detail=f"התקבלו {got} בייטים מתוך {expect}")

    if index not in j["parts"]:
        j["parts"].add(index)
        j["received"] += got
        if j["total"]:
            j["pct"] = round(100 * j["received"] / j["total"], 1)
    return {"ok": True, "index": index, "received": j["received"],
            "parts_done": len(j["parts"]), "n_parts": j["n_parts"]}


@api.get("/panel/saved-upload/parts")
async def saved_upload_parts(job: str = ""):
    """אילו חלקים כבר הגיעו — כדי לשלוח מחדש רק את החסרים."""
    j = _saved_jobs.get(job)
    if not j or "parts" not in j:
        raise HTTPException(status_code=404, detail="משימה לא נמצאה")
    return {"ok": True, "n_parts": j["n_parts"],
            "missing": sorted(set(range(j["n_parts"])) - j["parts"]),
            "received": j["received"], "total": j["total"]}


@api.post("/panel/saved-upload/finish")
async def saved_upload_finish(request: Request, job: str = ""):
    _check_upload_code(request, request.headers.get("x-upload-code", ""))
    j = _saved_jobs.get(job)
    if not j or "path" not in j:
        raise HTTPException(status_code=404, detail="משימה לא נמצאה")
    missing = sorted(set(range(j["n_parts"])) - j["parts"])
    if missing:
        raise HTTPException(status_code=409, detail=(
            f"חסרים {len(missing)} חלקים מתוך {j['n_parts']}"))

    path = pathlib.Path(j["path"])
    size = path.stat().st_size if path.exists() else 0
    if size != j["total"]:
        path.unlink(missing_ok=True)
        _saved_jobs.pop(job, None)
        raise HTTPException(status_code=400, detail=(
            f"גודל הקובץ בשרת {size} במקום {j['total']}"))

    j.update(stage="queued", size=size, pct=100)
    _t = asyncio.create_task(
        _saved_send(job, path, j["name"], j.get("caption") or ""))
    _saved_tasks.add(_t)
    _t.add_done_callback(_saved_tasks.discard)
    return {"ok": True, "job": job, "size": size}


@api.get("/panel/saved-upload/status")
'''

# רשומת המשימה מכילה עכשיו set ו-path, ו-set אינו ניתן להמרה ל-JSON.
STATUS_OLD = '''    j = _saved_jobs.get(job)
    if not j:
        raise HTTPException(status_code=404, detail="משימה לא נמצאה")
    return j
'''

STATUS_NEW = '''    j = _saved_jobs.get(job)
    if not j:
        raise HTTPException(status_code=404, detail="משימה לא נמצאה")
    return _saved_public(j)
'''

EDITS = [
    ("נקודות הקצה של ההעלאה בחלקים", ANCHOR_OLD, ANCHOR_NEW),
    ("תשובת המצב", STATUS_OLD, STATUS_NEW),
]

DONE_MARK = "/panel/saved-upload/begin"


def _fail(msg):
    print("❌ " + msg)
    print("   לא שונה כלום.")
    sys.exit(1)


def apply_edits(src):
    for label, old, new in EDITS:
        n = src.count(old)
        if n != 1:
            _fail(f"{label}: נקודת העיגון נמצאה {n} פעמים (ציפינו לאחת)")
        src = src.replace(old, new, 1)
    return src


def undo():
    baks = sorted(glob.glob(str(TARGET) + ".bak-parallel-*"))
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
    for dep, why in (("/panel/saved-upload", "add_saved_upload.py לא הוחל"),
                     ("_saved_max_size", "fix_saved_limits.py לא הוחל — הרץ אותו קודם")):
        if dep not in src:
            _fail(why)

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

    bak = f"{TARGET}.bak-parallel-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print("✅ הוחל.")
    print(f"   גיבוי: {os.path.basename(bak)}")
    print()
    print("   הרץ:   systemctl restart zovex-bot")
    print("   נסיגה: python3 fix_saved_parallel.py --undo")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
