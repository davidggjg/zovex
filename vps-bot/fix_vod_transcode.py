#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_vod_transcode — נתיב /vt שמנגן קבצים שהדפדפן לא תומך בהם (AVI וכו').

הבעיה שנמדדה: "מר פופר והפינגווינים" (id 487eefc2…) נכשל לגמרי בנגן,
"direct 4". בדיקה ישירה של הקובץ:

    Content-Type: video/x-msvideo          ← AVI
    12 בייט ראשונים: "RIFF….AVI "          ← מכולת RIFF/AVI

שום דפדפן לא מנגן AVI ב-HTML5. הקובץ תקין (VLC מנגן) — רק המכולה לא
נתמכת. ומנגנון ה-VOD הקיים (/vh /fs /vodinfo) בנוי כולו ל-MP4: הוא חותך
MP4 לפי הקופסאות הפנימיות שלו (moov/stsd), ולכן דוחה AVI ב-415
("אין ftyp"). AVI נדיר (~1 מ-20-40 סרטים), אבל למי שנתקל בו — הסרט מת.

הפתרון הסטנדרטי (Mux, martin-riedl, flask-mediabrowser): המרה בשרת עם
ffmpeg ל-HLS, וה-hls.js/Shaka שכבר בשימוש מנגן. ffmpeg קורא AVI מצוין.
בשרת כבר יש בדיוק את המכונה הזאת — הערוצים החיים (_hls_fix_start) עושים
ffmpeg→HLS/fMP4 לדיסק. זה מוסיף וריאנט VOD: ffmpeg קורא מה-URL המקומי
/stream/ של הקובץ, מוציא HLS מתגלגל לדיסק, והמקטעים מוגשים משם.

הגנות על שרת מתוח:
  • תקרת מקביליות קשיחה (_VT_MAX, ברירת מחדל 2). מעל זה — 503, לא
    מפילים את השרת. AVI נדיר, ולכן זה כמעט לא ייתקל בתקרה.
  • reaper סוגר ffmpeg ומוחק את הדיסק אחרי שאין צופים (_VT_IDLE).
  • הנתיב לא מופעל אוטומטית — הנגן נופל אליו רק כשנגינה ישירה נכשלה.
    כלומר MP4 תקין לעולם לא עובר דרך ffmpeg, ואפס עלות CPU עליו.

חתימה: /vt מאמת דרך _vf_check_sig, שמשתמש ב-_stream_sig — אותה חתימה
של /stream. כלומר exp+sig מה-URL הכושל תקפים כמו שהם, בלי לחתום מחדש.

    python3 fix_vod_transcode.py --check
    python3 fix_vod_transcode.py
    python3 fix_vod_transcode.py --revert
ואחריו:  systemctl restart zovex-bot
"""
import argparse, ast, os, shutil, sys
from pathlib import Path

MAIN = Path(os.environ.get("ZOVEX_MAIN", "/opt/zovex-bot/main.py"))
BAK = MAIN.with_name(MAIN.name + ".bak_vodtranscode")
MARK = "# [fix_vod_transcode]"

# ── עוגן 1: בלוק הקוד — נכנס לפני נתיב /vodinfo (שורה יציבה וייחודית) ─────────
ANCHOR_CODE = '@api.get("/vodinfo/{chat_id}/{message_id}")\n'

CODE = MARK + '''
# ── VOD transcode: ffmpeg ל-HLS לקבצים שהדפדפן לא תומך בהם (AVI ועוד) ────────
_VT_DIR = Path(os.environ.get("VT_DIR", "/tmp/zovex-vt"))
_VT_IDLE = int(os.environ.get("VT_IDLE_SEC", "120"))
_VT_MAX = int(os.environ.get("VT_MAX_CONCURRENT", "2"))
_vt: dict = {}                       # key -> {"proc","dir","last"}
_vt_lock = asyncio.Lock()


def _vt_key(chat_id: int, message_id: int) -> str:
    return f"{chat_id}_{message_id}"


async def _vt_start(chat_id: int, message_id: int):
    """מפעיל (או מחזיר קיים) ffmpeg שממיר את הקובץ ל-HLS/fMP4 מקומי."""
    key = _vt_key(chat_id, message_id)
    async with _vt_lock:
        ent = _vt.get(key)
        if ent and ent["proc"].returncode is None:
            ent["last"] = time.time()
            return ent
        alive = sum(1 for e in _vt.values() if e["proc"].returncode is None)
        if alive >= _VT_MAX and not (ent and ent["proc"].returncode is None):
            return None                   # תקרה — לא מעמיסים על השרת
        outdir = _VT_DIR / key
        try:
            shutil.rmtree(outdir, ignore_errors=True)
            outdir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log.error("vt: יצירת תיקייה נכשלה - %s", e)
            return None
        src = _vf_local_url(chat_id, message_id)
        args = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-reconnect", "1", "-reconnect_streamed", "1",
            "-reconnect_on_network_error", "1", "-reconnect_delay_max", "10",
            "-i", src,
            # AVI מכיל בדרך כלל וידאו mpeg4/xvid ואודיו mp3/ac3 — אף אחד
            # מהם לא נתמך בדפדפן, ולכן מקודדים את שניהם. veryfast כדי לא
            # לחנוק את המעבד, וסקייל תקרה כדי שסרט אחד לא ישתלט על השרת.
            "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "main",
            "-pix_fmt", "yuv420p", "-vf", "scale=min(1280\\,iw):-2",
            "-c:a", "aac", "-ac", "2", "-b:a", "128k",
            "-f", "hls", "-hls_time", "4", "-hls_list_size", "0",
            "-hls_playlist_type", "event",
            "-hls_segment_type", "fmp4",
            "-hls_fmp4_init_filename", "init.mp4",
            "-hls_segment_filename", str(outdir / "s%d.m4s"),
            str(outdir / "index.m3u8"),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL)
        except FileNotFoundError:
            log.error("vt: ffmpeg לא מותקן")
            return None
        ent = {"proc": proc, "dir": outdir, "last": time.time()}
        _vt[key] = ent
        log.info("vt: התחלת המרה %s", key)
        return ent


async def _vt_reaper():
    """סוגר ffmpeg של פריטים שאיש כבר לא צופה בהם."""
    while True:
        await asyncio.sleep(30)
        now = time.time()
        for key, ent in list(_vt.items()):
            if now - ent["last"] < _VT_IDLE:
                continue
            try:
                if ent["proc"].returncode is None:
                    ent["proc"].kill()
            except Exception:
                pass
            shutil.rmtree(ent["dir"], ignore_errors=True)
            _vt.pop(key, None)
            log.info("vt: נסגר פריט לא פעיל %s", key)


@api.get("/vt/{chat_id}/{message_id}/index.m3u8")
async def vt_playlist(chat_id: int, message_id: int, request: Request,
                      exp: int = 0, sig: str = ""):
    check_hotlink(request)
    _vf_check_sig(chat_id, message_id, exp, sig)
    ent = await _vt_start(chat_id, message_id)
    if ent is None:
        raise HTTPException(503, "vt: עומס — נסה שוב בעוד רגע")
    ent["last"] = time.time()
    idx = ent["dir"] / "index.m3u8"
    for _ in range(150):                  # עד ~15 שניות למקטעים ראשונים
        if idx.exists() and idx.read_text(encoding="utf-8", errors="ignore").count(".m4s") >= 1:
            break
        if ent["proc"].returncode is not None:
            raise HTTPException(502, "vt: ffmpeg נכשל")
        await asyncio.sleep(0.1)
    else:
        raise HTTPException(504, "vt: ההמרה לא התחילה בזמן")
    q = f"?exp={exp}&sig={sig}" if SIGN_SECRET else ""
    base = f"/vt/{chat_id}/{message_id}"
    out = []
    for line in idx.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("#EXT-X-MAP:"):
            out.append(f'#EXT-X-MAP:URI="{base}/init.mp4{q}"')
        elif s and not s.startswith("#"):
            out.append(f"{base}/{s}{q}")
        else:
            out.append(line)
    return Response("\\n".join(out) + "\\n",
                    media_type="application/vnd.apple.mpegurl",
                    headers={"Cache-Control": "no-store", **CORS_MEDIA})


@api.get("/vt/{chat_id}/{message_id}/{name}")
async def vt_segment(chat_id: int, message_id: int, name: str,
                     request: Request, exp: int = 0, sig: str = ""):
    check_hotlink(request)
    _vf_check_sig(chat_id, message_id, exp, sig)
    if not (name == "init.mp4" or (name.startswith("s") and name.endswith(".m4s"))):
        raise HTTPException(404, "not found")
    ent = _vt.get(_vt_key(chat_id, message_id))
    if not ent:
        raise HTTPException(404, "vt: לא פעיל")
    ent["last"] = time.time()
    f = ent["dir"] / name
    for _ in range(150):                  # מקטע שעדיין נכתב — ממתינים לו
        if f.exists():
            break
        if ent["proc"].returncode is not None and not f.exists():
            raise HTTPException(404, "vt: מקטע לא נוצר")
        await asyncio.sleep(0.1)
    else:
        raise HTTPException(504, "vt: מקטע לא מוכן בזמן")
    return Response(
        content=f.read_bytes(),
        media_type="video/mp4" if name == "init.mp4" else "video/iso.segment",
        headers={"Cache-Control": "public, max-age=60", **CORS_MEDIA})


'''

# ── עוגן 2: רישום ה-reaper ליד זה של הערוצים החיים ──────────────────────────
ANCHOR_REAP = ('    asyncio.create_task(_hls_fix_reaper())'
               '   # סוגר ffmpeg של ערוצים ללא צופים\n')
INSERT_REAP = ('    asyncio.create_task(_vt_reaper())   ' + MARK
               + '  # סוגר ffmpeg של VOD ללא צופים\n')


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True); raise


def validate(src: str, patched: bool = True) -> None:
    """הקוד חייב להתקמפל תמיד. כשזו הגרסה המתוקנת (patched) בודקים גם
    שהפונקציות החדשות קיימות; ב-revert משחזרים את המקור שבו הן לא קיימות
    בכוונה, ולכן שם בודקים רק שהקוד תקין."""
    compile(src, str(MAIN), "exec")
    if not patched:
        return
    tree = ast.parse(src)
    funcs = {n.name for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for need in ("_vt_start", "_vt_reaper", "vt_playlist", "vt_segment",
                 "_vf_check_sig", "_vf_local_url"):
        if need not in funcs:
            sys.exit(f"אימות נכשל: {need} חסרה — לא כותב.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    if not MAIN.exists():
        sys.exit(f"לא נמצא {MAIN}. הגדר ZOVEX_MAIN אם הנתיב שונה.")
    src = MAIN.read_text(encoding="utf-8")

    if a.revert:
        if not BAK.exists():
            sys.exit(f"אין גיבוי ב-{BAK}")
        orig = BAK.read_text(encoding="utf-8")
        validate(orig, patched=False)
        atomic_write(MAIN, orig)
        print(f"✓ שוחזר מ-{BAK} (בית-בית). הרץ: systemctl restart zovex-bot")
        return

    if MARK in src:
        print("כבר מותקן. אין מה לעשות.")
        return

    for label, anchor in (("קוד", ANCHOR_CODE), ("reaper", ANCHOR_REAP)):
        n = src.count(anchor)
        if n != 1:
            sys.exit(f"עוגן '{label}' נמצא {n} פעמים (ציפיתי 1) — הקוד השתנה, לא כותב.")

    new = src.replace(ANCHOR_CODE, CODE + ANCHOR_CODE)
    new = new.replace(ANCHOR_REAP, ANCHOR_REAP + INSERT_REAP)
    if new.count(MARK) < 2:
        sys.exit("ההוספה לא נתפסה במלואה — לא כותב.")
    validate(new)

    print(f"עוגנים: 2 · שורות שיתווספו: {new.count(chr(10))-src.count(chr(10))} · {MARK}")
    print("  נתיבים חדשים: /vt/{chat}/{msg}/index.m3u8  +  /vt/.../{name}")
    print(f"  תקרת מקביליות: {os.environ.get('VT_MAX_CONCURRENT','2')} המרות במקביל")
    if a.check:
        print("--check: שום דבר לא נכתב. היעד:", MAIN)
        return

    shutil.copy2(MAIN, BAK)
    atomic_write(MAIN, new)
    if MARK not in MAIN.read_text(encoding="utf-8"):
        shutil.copy2(BAK, MAIN)
        sys.exit("הכתיבה לא אומתה — שוחזר.")
    print(f"✓ הוחל · גיבוי: {BAK}")
    print("  הרץ: systemctl restart zovex-bot")
    print("  לביטול: python3 fix_vod_transcode.py --revert")


if __name__ == "__main__":
    main()
