#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מוסיף העלאת וידאו מהאפליקציה אל "הודעות שמורות" בטלגרם, דרך היוזרבוט.

הזרימה:  טלפון ──①──▶ שרת (קובץ זמני) ──②──▶ יוזרבוט ──▶ הודעות שמורות
                            └──────③ מחיקה ─────────┘

למה דווקא יוזרבוט: ל"הודעות שמורות" של חשבון יכול לשלוח רק החשבון עצמו.
בוט — כל בוט — לא יכול. לכן נבחר מהפוּל חבר מסוג "user" ולא "bot", ואם אין
כזה הבקשה נדחית בהודעה ברורה במקום להיכשל בשקט.

למה קוד הכניסה נבדק כאן ולא באפליקציה: APK הוא קובץ ZIP, ו-`strings` מוציא
ממנו כל מחרוזת בשניות. הקודים הקיימים ('123456', 'ZovexAdmin2026') כבר
חשופים כך. לפאנל שמעלה קבצים לחשבון הפרטי זה לא מספיק — מי שמוציא את הקוד
מקבל גישה לדחוף קבצים לחשבון. כאן הקוד יושב במשתנה סביבה בשרת: ב-APK אין
סוד, ואפשר להחליף אותו בלי לבנות אפליקציה מחדש.

    export UPLOAD_PANEL_CODE="…"     # קוד הכניסה לפאנל
    export SAVED_UPLOAD_USER="…"     # אופציונלי: @שם המשתמש שאליו מעלים

    python3 add_saved_upload.py          # מחיל
    python3 add_saved_upload.py --undo   # מחזיר
"""
import datetime, glob, os, pathlib, py_compile, shutil, sys, tempfile

TARGET = pathlib.Path("/opt/zovex-bot/main.py")
ANCHOR = 'if __name__ == "__main__":'

BLOCK = '''
# ── העלאה ל"הודעות שמורות" מהאפליקציה ────────────────────────────────────────
# ראה add_saved_upload.py להסבר מלא. בקצרה: הטלפון מעלה לשרת, השרת מעלה
# לטלגרם דרך היוזרבוט, והקובץ הזמני נמחק בסיום — גם כשההעלאה נכשלת.
UPLOAD_PANEL_CODE = os.environ.get("UPLOAD_PANEL_CODE", "").strip()
SAVED_UPLOAD_USER = os.environ.get("SAVED_UPLOAD_USER", "").strip().lstrip("@").lower()
SAVED_TMP_DIR = DATA_DIR / "saved_uploads"
SAVED_JOB_TTL = 3600          # רשומת התקדמות נשמרת שעה אחרי הסיום
SAVED_STALE_SEC = 6 * 3600    # קובץ זמני ישן מזה — שריד מהעלאה שנפלה

_saved_jobs: dict = {}        # job_id -> {stage, pct, ...}
# החזקת הפניה חזקה למשימות הרקע. asyncio.create_task מחזיר משימה שאם אף אחד
# אינו מחזיק אליה הפניה, אספן הזבל רשאי לאסוף אותה באמצע הריצה — מלכודת
# מתועדת, ובהעלאה שנמשכת דקות היא בדיוק הדבר שיקרה.
_saved_tasks: set = set()


def _saved_prune_jobs():
    now = time.time()
    for k in [k for k, v in _saved_jobs.items()
              if v.get("done_at") and now - v["done_at"] > SAVED_JOB_TTL]:
        _saved_jobs.pop(k, None)


def _pick_userbot():
    """חבר פוּל מסוג user. בוט לא יכול לשלוח ל'הודעות שמורות' של חשבון."""
    users = [b for b in _stream_bots if b.get("kind") == "user"]
    if not users:
        return None
    if SAVED_UPLOAD_USER:
        for b in users:
            if (b.get("who") or "").lstrip("@").lower() == SAVED_UPLOAD_USER:
                return b
        return None           # ביקשו חשבון מסוים והוא לא בפוּל — לא מנחשים
    return users[0]


@api.post("/panel/entry-code")
async def panel_entry_code(req: Request):
    """אימות קוד הכניסה לפאנל. הקוד יושב כאן ולא באפליקציה."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not UPLOAD_PANEL_CODE:
        raise HTTPException(status_code=503, detail="פאנל ההעלאה לא מוגדר בשרת")
    ok = hmac.compare_digest(str(body.get("code") or ""), UPLOAD_PANEL_CODE)
    if not ok:
        _auth_note_fail(req)      # אותה הגנה מפני ניחוש שמשמשת את שאר הפאנל
        raise HTTPException(status_code=403, detail="קוד שגוי")
    bot = _pick_userbot()
    return {"ok": True, "account": (bot or {}).get("who") or "",
            "ready": bot is not None}


async def _saved_send(job_id: str, path: pathlib.Path, filename: str, caption: str):
    """שלב ②: מעלה מהשרת לטלגרם, ומוחק את הקובץ הזמני בכל מקרה."""
    job = _saved_jobs[job_id]
    try:
        bot = _pick_userbot()
        if bot is None:
            raise RuntimeError("אין חשבון משתמש מחובר בשרת "
                               "(רק חשבון יכול לשלוח ל'הודעות שמורות')")
        total = path.stat().st_size
        job.update(stage="telegram", pct=0, sent=0, total=total,
                   started_tg=time.time())

        def _progress(current, _total):
            el = max(0.001, time.time() - job["started_tg"])
            job["sent"] = current
            job["pct"] = round(100 * current / max(1, _total or total), 1)
            job["speed"] = current / el
            left = max(0, (_total or total) - current)
            job["eta"] = int(left / job["speed"]) if job["speed"] > 0 else None

        await bot["client"].send_video(
            "me", str(path), caption=caption or filename,
            file_name=filename, progress=_progress)
        job.update(stage="done", pct=100, done_at=time.time())
        log.info("📤 הועלה ל'הודעות שמורות': %s (%.1fMB)", filename, total / 1048576)
    except asyncio.CancelledError:
        job.update(stage="error", error="בוטל", done_at=time.time())
        raise
    except Exception as e:
        job.update(stage="error", error=f"{type(e).__name__}: {e}",
                   done_at=time.time())
        log.warning("📤 העלאה ל'הודעות שמורות' נכשלה: %s: %s", type(e).__name__, e)
    finally:
        # נמחק גם בכישלון: אחרת כל ניסיון שנפל משאיר גיגה־בייטים על הדיסק.
        try:
            path.unlink(missing_ok=True)
        except Exception as e:
            log.warning("מחיקת קובץ זמני נכשלה: %s", e)


@api.post("/panel/saved-upload")
async def saved_upload(request: Request):
    """גוף גולמי, לא multipart.

    UploadFile/Form של FastAPI דורשים את החבילה python-multipart, ואם היא
    חסרה בשרת האפליקציה כולה לא עולה — כלומר האתר יורד בגלל פיצ'ר צדדי.
    גוף גולמי לא דורש דבר, וגם חוסך את קידוד ופענוח ה-multipart על קובץ של
    גיגה־בייטים. המטא־דאטה עוברת בפרמטרים: הקוד בכותרת (ASCII, ולא בכתובת
    שנכתבת ליומני הגישה), והשם והכיתוב בשאילתה כי הם עברית ואי אפשר לשים
    עברית בכותרת HTTP.
    """
    code = request.headers.get("x-upload-code", "")
    if not UPLOAD_PANEL_CODE or not hmac.compare_digest(code, UPLOAD_PANEL_CODE):
        _auth_note_fail(request)
        raise HTTPException(status_code=403, detail="קוד שגוי")
    if _pick_userbot() is None:
        raise HTTPException(status_code=503,
                            detail="אין חשבון משתמש מחובר בשרת")

    qp = request.query_params
    raw_name = unquote(qp.get("name") or "video.mp4")
    caption = unquote(qp.get("caption") or "")

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
    safe = re.sub(r"[^\w.\-]+", "_", raw_name)[-80:] or "video.mp4"
    path = SAVED_TMP_DIR / f"{job_id}_{safe}"
    declared = int(request.headers.get("content-length") or 0)
    _saved_jobs[job_id] = {"stage": "receiving", "pct": 0, "received": 0,
                           "total": declared, "name": safe, "started": time.time()}
    job = _saved_jobs[job_id]

    try:
        with path.open("wb") as f:
            async for chunk in request.stream():
                if not chunk:
                    continue
                f.write(chunk)
                job["received"] += len(chunk)
                if declared:
                    job["pct"] = round(100 * job["received"] / declared, 1)
    except Exception as e:
        path.unlink(missing_ok=True)
        _saved_jobs.pop(job_id, None)
        raise HTTPException(status_code=400, detail=f"קליטת הקובץ נכשלה: {e}")

    size = path.stat().st_size
    if size == 0:
        path.unlink(missing_ok=True)
        _saved_jobs.pop(job_id, None)
        raise HTTPException(status_code=400, detail="התקבל קובץ ריק")

    job.update(stage="queued", size=size, pct=100)
    _t = asyncio.create_task(_saved_send(job_id, path, safe, caption))
    _saved_tasks.add(_t)
    _t.add_done_callback(_saved_tasks.discard)
    _saved_prune_jobs()
    return {"ok": True, "job": job_id, "size": size}


@api.get("/panel/saved-upload/status")
async def saved_upload_status(job: str = ""):
    j = _saved_jobs.get(job)
    if not j:
        raise HTTPException(status_code=404, detail="משימה לא נמצאה")
    return j


'''


def _fail(msg):
    print("❌ " + msg)
    print("   לא שונה כלום.")
    sys.exit(1)


def undo():
    baks = sorted(glob.glob(str(TARGET) + ".bak-saved-*"))
    if not baks:
        _fail("לא נמצא גיבוי")
    shutil.copy2(baks[-1], TARGET)
    print(f"↩️  שוחזר מ-{os.path.basename(baks[-1])}")
    print("   הרץ:  systemctl restart zovex-bot")


def main():
    if not TARGET.exists():
        _fail(f"לא נמצא {TARGET}")
    src = TARGET.read_text(encoding="utf-8")

    if "/panel/saved-upload" in src:
        print("✓ כבר מוחל. אין מה לעשות.")
        return
    for dep, why in (("_stream_bots", "חסרה בריכת הבוטים"),
                     ("_auth_note_fail", "חסרה הגנת הניחוש של הפאנל"),
                     ("DATA_DIR", "חסר DATA_DIR")):
        if dep not in src:
            _fail(why)
    if src.count(ANCHOR) != 1:
        _fail(f"נקודת העיגון נמצאה {src.count(ANCHOR)} פעמים (ציפינו לאחת)")

    # ייבוא־חסר הוא הכשל השקט הקלאסי כאן: הקוד יתקמפל ויפול רק בזמן ריצה,
    # בתוך משימת רקע, כלומר בלי שאיש ישים לב.
    head = src[:src.index(ANCHOR)]
    need = []
    if "unquote" not in head:
        need.append("from urllib.parse import unquote")
    if "import uuid" not in head:
        need.append("import uuid")
    if "import hmac" not in head:
        need.append("import hmac")
    extra = ("\n".join(need) + "\n") if need else ""

    out = src.replace(ANCHOR, extra + BLOCK.lstrip("\n") + "\n" + ANCHOR, 1)

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

    bak = f"{TARGET}.bak-saved-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print("✅ הוחל.")
    print(f"   גיבוי: {os.path.basename(bak)}")
    if need:
        print("   נוספו ייבואים: " + ", ".join(need))
    print()
    print("   הגדר קוד:  systemctl edit zovex-bot   →  Environment=UPLOAD_PANEL_CODE=…")
    print("   הרץ:       systemctl restart zovex-bot")
    print("   נסיגה:     python3 add_saved_upload.py --undo")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
