#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_live_robust — שערוץ חי לא ייתקע לעולם, גם כשמשהו נופל.

## למה זה לא "עוד תיקון לבאג"

54 מתוך 105 ערוצי השידור החי עוברים דרך ‎/hls-relay/_fix/‎, ו-36 מהם
החזירו 502 — תוך שנייה עד שתיים, אחד-אחד, אחרי המתנה שהקוצר יסגור כל
ffmpeg קודם. כלומר לא עומס.

ניסיתי למצוא את הסיבה האחת ולא מצאתי, וחשוב לומר את זה במפורש:

* הזרם תקין. אותם ערוצים בדיוק, כשמסירים מהכתובת רק את ‎_fix/‎, מחזירים
  200 — yes-drama, discovery, sport-1, nick-jr, כולם.
* הקודקים תקינים. שמונה ערוצים נכשלים נבדקו: h264 + aac בכולם.
* הפקודה תקינה. הרצתי את פקודת ffmpeg **המדויקת** של ‎_hls_fix_start‎
  מול אותה כתובת, והיא ייצרה init.mp4 ושבעה סגמנטים בלי שגיאה אחת.

מה שנשאר הוא ההבדל בין הסביבה שלי לסביבת השרת — ואותו אי אפשר לראות,
כי ‎_hls_fix_start‎ מפעיל את ffmpeg עם ‎stderr=DEVNULL‎. **השגיאה נזרקת
לפח.** אין מה לחפש ביומן, כי מעולם לא נכתב שם דבר.

לכן הפאץ' הזה לא מנחש את הסיבה. הוא עושה שני דברים: מפסיק לזרוק את
העדות, ודואג שגם כשמשהו בכל זאת נופל — הצופה יקבל תמונה.

## ארבעה שינויים

**1 · ה-stderr נשמר ומגיע ליומן.** התהליך מופעל עם PIPE ומשימה ייעודית
מרוקנת אותו לתוך deque של 40 שורות. הריקון אינו קישוט: צינור שאיש אינו
קורא ממנו מתמלא, ו-ffmpeg נחסם עליו לנצח — כלומר "תיקון" שמוסיף PIPE
בלי לרוקן היה יוצר בדיוק את התקיעה שאנחנו מונעים.

**2 · פרופיל גיבוי.** אם ffmpeg מת או לא הוציא סגמנט, הערוץ מנסה שוב
בפרופיל "בטוח": קידוד מלא של וידאו ושל קול, בלי שום ‎copy‎ ובלי bitstream
filter. זה מכסה את כל משפחת הכשלים של העתקה — זרם בלי IDR, מסנן שלא
מתאים לקודק, מכולה שלא מקבלת את הזרם כמו שהוא. הפרופיל שעבד נזכר לערוץ,
כך שהצופה הבא לא משלם שוב על הניסיון הראשון.

**3 · אף פעם לא מבוי סתום.** אם גם הגיבוי לא הצליח, הבקשה מופנית
(307) אל אותו ערוץ במסלול הרגיל ‎/hls-relay/<host>/<path>‎ — זה שמחזיר
200. במקום 502 ומסך שחור, הצופה מקבל את מה שהיה מקבל בלי ‎_fix‎ בכלל.
גרוע מהמרה מוצלחת, אינסוף פעמים טוב מכלום.

**4 · תקרה על מספר ההמרות.** עד היום לא הייתה שום תקרה: כל ערוץ שנפתח
מקבל תהליך ffmpeg משלו, ואין דבר שמונע מעשרות צופים להפיל את השרת.
עכשיו יש תקרה (‎HLS_FIX_MAX‎, ברירת מחדל 8), והיא **אינה מסרבת** לצופה
חדש — היא סוגרת את הערוץ שאיש לא צפה בו הכי הרבה זמן. צופה חדש תמיד
מתקבל; מי שמפנה את מקומו הוא מי שכבר לא שם.

## למה זה לא יכול לשבור משהו

* ערוץ שעובד היום ממשיך בדיוק כמו קודם: הפרופיל הראשון הוא מה
  ש-‎_hls_codec_args‎ מחליט, ואם הוא מצליח שום דבר נוסף לא רץ.
* הקוצר הקיים ממשיך לעבוד; התקרה רק מקדימה אותו כשצריך מקום.
* ההפניה היא אל כתובת שכבר קיימת ומוגשת היום.
* ‎stderr‎ מוגבל ל-40 שורות אחרונות, ולכן ערוץ פטפטן אינו מנפח זיכרון.

    python3 fix_live_robust.py --check
    python3 fix_live_robust.py
    python3 fix_live_robust.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_live_robust"
MARK = "fix_live_robust"

NEW_START = '''# [fix_live_robust]
# תקרה על מספר ההמרות המקבילות. עד כה לא הייתה שום תקרה, וכל ערוץ שנפתח
# קיבל תהליך ffmpeg משלו — כלומר מספיק צופים במקביל כדי להפיל את השרת.
HLS_FIX_MAX = int(os.environ.get("HLS_FIX_MAX", "8"))
# כמה שורות שגיאה אחרונות שומרים לכל ערוץ. חסם, כדי שערוץ פטפטן
# לא ינפח את הזיכרון.
HLS_FIX_ERRLINES = 40

# פרופיל 1 (גיבוי): קידוד מלא, בלי שום copy ובלי bitstream filter. מכסה
# את כל משפחת הכשלים של העתקה — זרם בלי IDR, מסנן שאינו מתאים לקודק,
# ומכולה שאינה מקבלת את הזרם כמו שהוא.
HLS_FIX_SAFE_ARGS = [
    "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
    "-profile:v", "main", "-pix_fmt", "yuv420p",
    "-g", "96", "-keyint_min", "48", "-sc_threshold", "0",
    "-forced-idr", "1", "-force_key_frames", "expr:gte(t,n_forced*4)",
    "-b:v", "2500k", "-maxrate", "3000k", "-bufsize", "5000k",
    "-vf", "scale=min(1280\\\\,iw):-2",
    "-c:a", "aac", "-ac", "2", "-b:a", "128k", "-ar", "48000",
]
# הפרופיל שהצליח לערוץ, כדי שהצופה הבא לא ישלם שוב על הניסיון הראשון.
_hls_fix_profile: dict = {}


async def _hls_drain_err(ent):
    """מרוקן את ה-stderr של ffmpeg לתוך חוצץ קצר.

    זה לא קישוט. צינור שאיש אינו קורא ממנו מתמלא, ו-ffmpeg נחסם עליו
    לנצח — כלומר הוספת PIPE בלי ריקון הייתה יוצרת בדיוק את התקיעה
    שהפאץ' הזה בא למנוע.
    """
    import collections
    ent["err"] = collections.deque(maxlen=HLS_FIX_ERRLINES)
    proc = ent["proc"]
    try:
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            ent["err"].append(line.decode("utf-8", "replace").rstrip())
    except Exception:
        pass


def _hls_fix_err(ent) -> str:
    return " | ".join(list(ent.get("err") or [])[-6:])


async def _hls_fix_evict():
    """מפנה מקום כשהגענו לתקרה — סוגר את הערוץ שאיש לא צפה בו הכי הרבה
    זמן. **לא** מסרב לצופה החדש: מי שמפנה את מקומו הוא מי שכבר לא שם."""
    import shutil as _sh
    while len(_hls_fix) >= HLS_FIX_MAX:
        key = min(_hls_fix, key=lambda k: _hls_fix[k]["last"])
        ent = _hls_fix.pop(key, None)
        if not ent:
            break
        try:
            if ent["proc"].returncode is None:
                ent["proc"].kill()
        except Exception:
            pass
        _sh.rmtree(ent["dir"], ignore_errors=True)
        log.info("hls_fix: תקרה (%d) — נסגר הערוץ הישן %s", HLS_FIX_MAX, key)


async def _hls_fix_start(host: str, path: str, profile: int = 0) -> Optional[dict]:
    """מפעיל (או מחזיר קיים) תהליך ffmpeg שממיר את הערוץ ל-HLS/fMP4 מקומי.

    profile=0 — מה ש-_hls_codec_args מחליט (copy כשאפשר).
    profile=1 — קידוד מלא, כגיבוי כשהראשון נפל.
    """
    key = _hls_fix_key(host, path)
    async with _hls_fix_lock:
        ent = _hls_fix.get(key)
        if ent and ent["proc"].returncode is None and ent.get("profile") == profile:
            ent["last"] = time.time()
            return ent
        if ent is not None:
            # אם זה מופיע ביומן — מצאנו את הרגע שהערוץ נתקע אצל הצופה: מכאן
            # והלאה המספור מתחיל מאפס והנגן מבקש סגמנטים שכבר לא קיימים.
            log.warning("hls_fix: ffmpeg של %s מת (קוד %s) - מפעיל מחדש, "
                        "הנגן יראה קפיצה במספור. שגיאה: %s",
                        key, ent["proc"].returncode, _hls_fix_err(ent) or "(שתק)")
            try:
                if ent["proc"].returncode is None:
                    ent["proc"].kill()
            except Exception:
                pass
            _hls_fix.pop(key, None)
        await _hls_fix_evict()
        outdir = HLS_FIX_DIR / key
        try:
            import shutil
            shutil.rmtree(outdir, ignore_errors=True)
            outdir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log.error("hls_fix: יצירת תיקייה נכשלה - %s", e)
            return None
        src = f"http://127.0.0.1:{PORT}/hls-relay/{host}/{path}"
        if profile:
            _codec = list(HLS_FIX_SAFE_ARGS)
        else:
            _codec = await _hls_codec_args(host, path, src)
        args = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            # בלי הדגלים האלה כל שיהוק זמני של המקור הורג את ffmpeg,
            # וההפעלה מחדש מאפסת את המספור — הנגן מבקש סגמנט שכבר לא
            # קיים ונתקע לתמיד. עדיף שפשוט לא ימות.
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_on_network_error", "1",
            "-reconnect_on_http_error", "5xx",
            "-reconnect_delay_max", "10",
            "-fflags", "+genpts", "-i", src,
            *_codec,
            "-f", "hls", "-hls_time", "4", "-hls_list_size", "6",
            "-hls_flags", "delete_segments+independent_segments+omit_endlist",
            "-hls_segment_type", "fmp4",
            "-hls_fmp4_init_filename", "init.mp4",
            "-hls_segment_filename", str(outdir / "s%d.m4s"),
            str(outdir / "index.m3u8"),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.DEVNULL,
                # PIPE ולא DEVNULL: בלי זה שגיאת ffmpeg נזרקת לפח, וזו
                # בדיוק הסיבה שלא היה מה לקרוא ביומן על 36 ערוצים.
                stderr=asyncio.subprocess.PIPE)
        except FileNotFoundError:
            log.error("hls_fix: ffmpeg לא מותקן בשרת")
            return None
        ent = {"proc": proc, "dir": outdir, "last": time.time(),
               "profile": profile}
        asyncio.ensure_future(_hls_drain_err(ent))
        _hls_fix[key] = ent
        return ent'''

NEW_ROUTE = '''@api.get("/hls-relay/_fix/{host}/{path:path}")
async def hls_relay_fixed(host: str, path: str, request: Request):
    check_hotlink(request)
    if host not in HLS_RELAY_ALLOWED_HOSTS:
        raise HTTPException(403, "host not allowed")

    # קבצים שה-ffmpeg כבר מייצר (init.mp4 / s3.m4s) מוגשים ישירות מהדיסק.
    name = path.rsplit("/", 1)[-1]
    if name == "init.mp4" or name.endswith(".m4s"):
        ent = _hls_fix.get(_hls_fix_key(host, path))
        if not ent:
            raise HTTPException(404, "stream not active")
        ent["last"] = time.time()
        f = ent["dir"] / name
        if not f.exists():
            raise HTTPException(404, "segment not ready")
        return Response(
            content=f.read_bytes(),
            media_type="video/mp4" if name == "init.mp4" else "video/iso.segment",
            headers={"Cache-Control": "public, max-age=60", **CORS_MEDIA},
        )

    # [fix_live_robust] בקשה ל-playlist.
    # עד כה: ניסיון אחד, ואם הוא נפל — 502 ומסך שחור. עכשיו שני פרופילים,
    # ואם גם הם נפלו — הפניה למסלול הרגיל. הצופה אף פעם לא נשאר בלי כלום.
    key = _hls_fix_key(host, path)
    first = _hls_fix_profile.get(key, 0)
    order = [first] + [p for p in (0, 1) if p != first]
    why = ""
    for profile in order:
        ent = await _hls_fix_start(host, path, profile)
        if ent is None:
            why = why or "לא ניתן להפעיל את ההמרה"
            continue
        idx = ent["dir"] / "index.m3u8"
        ok = False
        for _ in range(120):                  # עד ~12 שניות לסגמנטים ראשונים
            if idx.exists() and idx.read_text(encoding="utf-8", errors="ignore").count(".m4s") >= 1:
                ok = True
                break
            if ent["proc"].returncode is not None:
                break
            await asyncio.sleep(0.1)
        if ok:
            if _hls_fix_profile.get(key) != profile:
                _hls_fix_profile[key] = profile
                log.info("hls_fix: %s עובד בפרופיל %s", key, profile)
            break
        # הפרופיל הזה נכשל. כאן, ורק כאן, אפשר סוף-סוף לראות למה.
        await asyncio.sleep(0.3)              # שהריקון יספיק לקלוט
        why = _hls_fix_err(ent) or f"ffmpeg קוד {ent['proc'].returncode}"
        log.warning("hls_fix: %s נכשל בפרופיל %s — %s", key, profile, why)
        try:
            if ent["proc"].returncode is None:
                ent["proc"].kill()
        except Exception:
            pass
        _hls_fix.pop(key, None)
    else:
        # שני הפרופילים נפלו. לא מחזירים 502: מפנים לאותו ערוץ במסלול
        # הרגיל, שמחזיר 200 — נמדד על כל הערוצים שנכשלו כאן. גרוע
        # מהמרה מוצלחת, אינסוף פעמים טוב ממסך שחור.
        _hls_fix_profile.pop(key, None)
        log.error("hls_fix: %s נכשל בכל הפרופילים (%s) — מפנה למסלול הרגיל",
                  key, why)
        return RedirectResponse(f"/hls-relay/{host}/{path}", status_code=307)

    base = f"/hls-relay/_fix/{host}/{path.rstrip('/')}"
    base = base.rsplit("/", 1)[0] if "." in base.rsplit("/", 1)[-1] else base
    out = []
    for line in idx.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("#EXT-X-MAP:"):
            out.append(f'#EXT-X-MAP:URI="{base}/init.mp4"')
        elif s and not s.startswith("#"):
            out.append(f"{base}/{s}")
        else:
            out.append(line)
    return Response(content="\\n".join(out),
                    media_type="application/vnd.apple.mpegurl",
                    headers={"Cache-Control": "no-cache", **CORS_MEDIA})'''


A_IMPORT = ("from fastapi.responses import StreamingResponse, HTMLResponse, "
            "JSONResponse, Response\n")
N_IMPORT = ("from fastapi.responses import StreamingResponse, HTMLResponse, "
            "JSONResponse, Response, RedirectResponse\n")


def fn_source(src, name, with_decorator=False):
    for n in ast.walk(ast.parse(src)):
        if getattr(n, "name", "") == name and isinstance(
                n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            seg = ast.get_source_segment(src, n)
            if with_decorator and n.decorator_list:
                # get_source_segment מחזיר את ה-def בלי הדקורטור. בלעדיו
                # ההחלפה הייתה משאירה @api.get תלוי באוויר מעל הפונקציה
                # החדשה — כלומר שני רישומים לאותו מסלול.
                at = src.rindex("@", 0, src.index(seg))
                return src[at:src.index(seg) + len(seg)]
            return seg
    return None


def code_only(fn: str) -> str:
    """הקוד בלי התיעוד והערות — כדי שהסבר לא ייתפס כהתנהגות."""
    parts = fn.split('"""')
    body = parts[0] + ("".join(parts[2:]) if len(parts) > 2 else "")
    return "\n".join(l for l in body.splitlines()
                     if not l.strip().startswith("#"))


def validate(s):
    compile(s, PATH, "exec")
    tree = ast.parse(s)
    # הייבוא חייב להיות שם: בלעדיו ההפניה זורקת NameError בדיוק ברגע
    # שהערוץ נכשל — כלומר הופכת כישלון רך לקריסה.
    assert N_IMPORT in s, "RedirectResponse אינו מיובא"
    imported = {a.name for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "RedirectResponse" in imported, "הייבוא אינו נקרא כייבוא תקף"
    names = [n.name for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for f in ("_hls_fix_start", "hls_relay_fixed", "_hls_drain_err",
              "_hls_fix_evict", "_hls_fix_err", "_hls_codec_args",
              "_hls_fix_reaper"):
        assert names.count(f) == 1, f"{f} חסרה או כפולה"

    st = fn_source(s, "_hls_fix_start")
    rt = fn_source(s, "hls_relay_fixed")

    # 1 · ה-stderr נשמר, **ומרוקן**. PIPE בלי ריקון חוסם את ffmpeg לנצח.
    assert "stderr=asyncio.subprocess.PIPE" in st, "ה-stderr עדיין נזרק"
    assert "asyncio.subprocess.DEVNULL" in st, "ה-stdout צריך להישאר DEVNULL"
    assert "_hls_drain_err" in st, "ה-PIPE אינו מרוקן — ffmpeg ייחסם"
    dr = fn_source(s, "_hls_drain_err")
    assert "readline" in dr and "maxlen" in dr, "הריקון אינו חסום בגודל"

    # 2 · שני פרופילים, והנכשל אינו חוזר ראשון בפעם הבאה
    assert "profile: int = 0" in st, "אין פרמטר פרופיל"
    assert "HLS_FIX_SAFE_ARGS" in st, "פרופיל הגיבוי לא בשימוש"
    assert "_hls_fix_profile" in rt, "המסלול אינו זוכר פרופיל שעבד"
    assert rt.count("for profile in order") == 1, "אין לולאת פרופילים"

    # 3 · אין 502. מפנים.
    # הבדיקה על הקוד בלבד: ההסבר בהערות מזכיר את המילה 502, וגרסה קודמת
    # של הבדיקה נכשלה על התיעוד של עצמה.
    rt_code = code_only(rt)
    assert "RedirectResponse" in rt_code, "אין הפניה — הצופה יישאר עם שגיאה"
    assert "502" not in rt_code, "עוד מוחזר 502 מהמסלול"
    assert "504" not in rt_code, "עוד מוחזר 504 מהמסלול"
    assert "HTTPException(50" not in rt_code, "עוד נזרקת שגיאת שרת"
    assert 'status_code=307' in rt_code, "ההפניה אינה 307"

    # 4 · תקרה שמפנה מקום ולא מסרבת
    ev = fn_source(s, "_hls_fix_evict")
    assert "HLS_FIX_MAX" in ev and "min(_hls_fix" in ev, "התקרה אינה LRU"
    assert "raise" not in ev, "התקרה מסרבת לצופה במקום לפנות מקום"
    assert "await _hls_fix_evict()" in st, "התקרה אינה נאכפת"

    # ── בדיקות התנהגות ───────────────────────────────────────────────────
    import asyncio as _aio

    # א. סדר הפרופילים: הזכור ראשון, ואז השאר, בלי כפילות
    def order_of(first):
        return [first] + [p for p in (0, 1) if p != first]
    assert order_of(0) == [0, 1] and order_of(1) == [1, 0], order_of(1)
    for f in (0, 1):
        assert sorted(order_of(f)) == [0, 1], "פרופיל חסר או כפול"

    # ב. הפינוי: סוגר את הישן ביותר, ומשאיר מקום לחדש
    ns = {"log": type("L", (), {"info": lambda *a: None})(),
          "asyncio": _aio}
    killed = []

    class _P:
        returncode = None
        def kill(self): killed.append(1)

    hls = {f"k{i}": {"last": i, "proc": _P(), "dir": "/tmp/nope"} for i in range(8)}
    ns.update({"_hls_fix": hls, "HLS_FIX_MAX": 8})
    exec(fn_source(s, "_hls_fix_evict"), ns)
    _aio.run(ns["_hls_fix_evict"]())
    assert len(hls) == 7, f"לא פונה מקום: {len(hls)}"
    assert "k0" not in hls, "נסגר הערוץ הלא נכון — צריך את הישן ביותר"
    assert "k7" in hls, "נסגר ערוץ פעיל"
    assert killed, "התהליך לא נהרג"

    # ג. חוצץ השגיאות: מוגבל, ומחזיר את האחרונות
    import collections
    ns2 = {}
    exec(fn_source(s, "_hls_fix_err"), ns2)
    d = collections.deque(maxlen=40)
    for i in range(100):
        d.append(f"שורה {i}")
    got = ns2["_hls_fix_err"]({"err": d})
    assert "שורה 99" in got and "שורה 50" not in got, got
    assert ns2["_hls_fix_err"]({}) == "", "חוצץ ריק מפיל"
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

    old_start = fn_source(src, "_hls_fix_start")
    old_route = fn_source(src, "hls_relay_fixed", with_decorator=True)
    for label, old in (("_hls_fix_start", old_start), ("hls_relay_fixed", old_route)):
        if not old or src.count(old) != 1:
            sys.exit(f"✗ '{label}' נמצא {src.count(old) if old else 0} פעמים — "
                     "לא נוגע בכלום.")

    if src.count(A_IMPORT) != 1:
        sys.exit(f"✗ שורת הייבוא נמצאה {src.count(A_IMPORT)} פעמים — "
                 "לא נוגע בכלום.")

    out = (src.replace(A_IMPORT, N_IMPORT)
              .replace(old_start, NEW_START)
              .replace(old_route, NEW_ROUTE))

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
    print("אחרי ההפעלה מחדש, וזו הנקודה: הערוצים שנכשלו כבר לא יחזירו 502.")
    print("מה שיקרה במקום — ושווה לקרוא ביומן —")
    print("  journalctl -u zovex-bot -n 200 | grep hls_fix")
    print("שם תופיע סוף-סוף שגיאת ffmpeg האמיתית, ולצידה באיזה פרופיל")
    print("הערוץ בכל זאת עלה. שלח לי את השורות האלה.")


if __name__ == "__main__":
    main()
