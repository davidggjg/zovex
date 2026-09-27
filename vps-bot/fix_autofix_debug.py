#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_autofix_debug — למה ההפניה לא נורית, בפקודה אחת במקום עוד סיבוב.

## איפה אנחנו

ההפניה האוטומטית מותקנת על השרת ואינה פועלת. מה שנשלל עד כה, כל אחד
במדידה ולא בהשערה:

* **הפאץ' כן שם.** נקרא ‎main.py‎ החי מתוך קומיט הגיבוי: כל ארבעת
  הסימנים נמצאים בו, והבלוק שהוזרק ל-‎hls_relay‎ קיים מילה במילה.
* **תיקון הפורט פועל.** ‎/hls-relay/_fix/<ספק>:7070/...‎ מחזיר 200 במקום
  403, ו-‎_fix‎ עצמו מצליח על הערוץ הזה.
* **זה אינו מטמון.** ‎?zx=1‎ ו-‎?zx=2‎ מחזירים 200 גם הם.
* **הלוגיקה נכונה.** הפקודה ש-‎_hls_probe_no_idr‎ מריץ הורצה מול אותה
  כתובת: 5,136,571 בתים, 404 slices, אפס IDR — כלומר "צריך המרה".
* **רמת היומן היא INFO**, ולכן ‎log.info‎ אמור להופיע.

ולמרות זאת אין ביומן אף שורה של ‎idr_probe‎ או ‎hls_codec‎. שלוש
האפשרויות שנשארו — הבדיקה לא נשלחה, היא נשלחה ונפלה בשקט, או שהיא
החזירה "יש IDR" — מובילות לשלושה תיקונים שונים לגמרי, ואי אפשר לבחור
ביניהן מבחוץ. גם אבחון דרך היומן נכשל פעמיים בסיבוב הזה, פעם כי
‎stderr‎ הופנה ל-DEVNULL ופעם כי לא הייתה שורה בכלל.

## מה נוסף

נקודת אבחון אחת, ‎GET /debug/autofix‎, שמחזירה בדיוק את המצב שעליו
ההחלטה נשענת: האם ההפניה דולקת, מה יש במטמון ה-IDR ומה גילו, מה סימון
הפרופיל, האם בדיקה באוויר, ומה ‎_hls_autofix_wanted‎ היה מחזיר עכשיו.

עם ‎run=1‎ היא גם מריצה את בדיקת ה-ffmpeg **באותה בקשה** ומחזירה את
המספרים עצמם — בתים, slices, IDR, קוד היציאה ושורות ה-stderr. זו
התשובה המלאה בקריאה אחת, בלי להיתלות ביומן ובלי להמתין לרקע.

## למה זה בטוח

* ‎is_local_request‎ בלבד. בקשה שעברה דרך nginx נושאת X-Forwarded-For
  ולכן **אינה** מקומית, וזו אותה הגנה שכבר שומרת על ‎/content/relink‎
  ועל ‎/admin/migrate‎. מבחוץ זה 404, כאילו הנתיב אינו קיים.
* קורא בלבד, למעט ‎run=1‎ שממלא את מטמון ה-IDR — וזה בדיוק מה שהבדיקה
  ברקע הייתה עושה ממילא.
* אין נגיעה בשום מסלול ניגון.

## ובנוסף — 307 ל-302

ההפניות נשארו 307 על השרת, כי שינוי ה-302 נכנס ל-fix_live_autofix
**אחרי** שהוא הוחל שם, ושומר ה-MARK מונע החלה חוזרת. לכן השינוי הזה
נעשה כאן. זו בקשת GET של playlist בשני המקרים, ו-302 נעקב על ידי כל
לקוח HTTP — כולל ExoPlayer שמאחורי הנגן באפליקציה, שלגביו לא הייתה לי
מדידה.

    python3 fix_autofix_debug.py --check
    python3 fix_autofix_debug.py
    python3 fix_autofix_debug.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_autofix_debug"
MARK = "fix_autofix_debug"
NEEDS = ("fix_live_autofix", "fix_idr_probe_log")

A_307A = '''            return RedirectResponse(f"/hls-relay/_fix/{_fix_host}/{path}",
                                    status_code=307)
'''
N_307A = '''            # [fix_autofix_debug] 302 ולא 307: זו תמיד בקשת GET של
            # playlist, ולכן שמירת השיטה שמבטיח 307 אינה נדרשת — ובתמורה
            # 302 נעקב על ידי כל לקוח HTTP בלי יוצא מן הכלל.
            return RedirectResponse(f"/hls-relay/_fix/{_fix_host}/{path}",
                                    status_code=302)
'''

A_307B = '''        return RedirectResponse(f"/hls-relay/{host}/{path}", status_code=307)
'''
N_307B = '''        return RedirectResponse(f"/hls-relay/{host}/{path}", status_code=302)
'''

A_ROUTE = '''@api.get("/hls-relay/_fix/{host}/{path:path}")
'''

N_ROUTE = '''# [fix_autofix_debug]
# נקודת אבחון להפניה האוטומטית. מקומית בלבד — בקשה שעברה דרך nginx
# נושאת X-Forwarded-For ולכן אינה מקומית, ומקבלת 404 כאילו אין נתיב.
# אותה הגנה בדיוק ששומרת על /content/relink ועל /admin/migrate.
@api.get("/debug/autofix")
async def debug_autofix(request: Request, host: str, path: str,
                        run: int = 0):
    if not is_local_request(request):
        raise HTTPException(404, "not found")
    key = f"{host}/{path}"
    fkey = _hls_fix_key(host, path)
    src = f"http://127.0.0.1:{PORT}/hls-relay/{host}/{path}"

    def _red(v):
        """ממסך את שם המארח של הספק ואת האסימון שבנתיב.

        התשובה נועדה להעתקה, ו-stderr של ffmpeg נושא את הכתובת המלאה.
        המיסוך נעשה כאן ולא בהוראה למי שמעתיק, כדי שהפלט יהיה בטוח
        מעצם בנייתו. הודעת השגיאה עצמה נשמרת — היא מה שמאבחן.
        """
        import re as _re
        s = str(v)
        # מחלקת תווים בלי גרשיים: גרש בתוך מחרוזת המקור שבר כאן את
        # הרגקס, ונתפס בקומפילציה של התוצאה. רווח מפריד ממילא.
        s = _re.sub(r"(/hls-relay/)(_fix/)?[^/\\s]+", r"\\1\\2<ספק>", s)
        s = _re.sub(r"\\b[A-Z0-9]{8,}\\b", "<אסימון>", s)
        s = _re.sub(r"\\b(?:[a-z0-9-]+\\.){2,}[a-z]{2,}\\b", "<ספק>", s)
        return s

    out = {
        "autofix_on": bool(HLS_AUTOFIX),
        "host": _red(host), "path": _red(path),
        "fix_key": fkey,
        # None כאן = "_fix נכשל בכל הפרופילים", וזה **חוסם** את ההפניה
        # בכוונה, כדי שלא תיווצר לולאה. אם זה הערך — זו התשובה.
        "profile_marker": _hls_fix_profile.get(fkey, "אין"),
        "probe_in_flight": key in _hls_idr_probing,
        "fix_active": fkey in _hls_fix,
        "src": _red(src),
    }
    ent = _hls_idr_cache.get(key)
    out["idr_cache"] = None if ent is None else {
        "age_sec": round(time.time() - ent[0], 1),
        "no_idr": bool(ent[1]),
        "ttl_sec": _HLS_IDR_TTL,
    }
    if run:
        # מריצים את אותה פקודה בדיוק שהבדיקה מריצה, ומחזירים את המספרים
        # במקום בוליאני. run_in_executor כדי לא לחסום את הלולאה.
        import subprocess

        def _probe():
            try:
                r = subprocess.run(
                    ["ffmpeg", "-hide_banner", "-v", "error", "-t", "8",
                     "-i", src, "-map", "0:v:0", "-c", "copy",
                     "-f", "h264", "-"],
                    capture_output=True, timeout=90)
                data = r.stdout or b""
                idr, slices = _h264_count_nals(data)
                err = (r.stderr or b"").decode("utf-8", "replace").strip()
                return {"bytes": len(data), "slices": slices, "idr": idr,
                        "rc": r.returncode,
                        "stderr_tail": [_red(l) for l in err.splitlines()[-3:]],
                        "verdict_no_idr": bool(slices) and idr == 0}
            except Exception as e:
                return {"error": _red(f"{type(e).__name__}: {e}")}

        loop = asyncio.get_running_loop()
        out["probe"] = await loop.run_in_executor(None, _probe)
        # ומרעננים את המטמון דרך המסלול האמיתי, כדי שהתשובה תשקף את מה
        # שההחלטה תראה — ולא רק את מה שהבדיקה הידנית ראתה.
        try:
            out["no_idr_via_real_path"] = await _hls_no_idr(host, path, src)
        except Exception as e:
            out["no_idr_via_real_path"] = _red(f"{type(e).__name__}: {e}")
        ent = _hls_idr_cache.get(key)
        out["idr_cache_after"] = None if ent is None else {
            "age_sec": round(time.time() - ent[0], 1),
            "no_idr": bool(ent[1]),
        }
    out["would_redirect"] = _hls_autofix_wanted(host, path)
    out["redirect_to"] = _red(f"/hls-relay/_fix/{host}/{path}")
    return JSONResponse(out)


@api.get("/hls-relay/_fix/{host}/{path:path}")
'''

# שתי העריכות של ה-307 הן **אופציונליות**, ובכוונה: על השרת ההפניות
# נכתבו ב-307 (השינוי ל-302 נכנס ל-fix_live_autofix אחרי שהוא הוחל שם),
# אבל בהתקנה טרייה fix_live_autofix כבר כותב 302 מלכתחילה. פאץ' שדורש
# למצוא 307 היה נכשל על התקנה טרייה — נתפס בבדיקה על main.py נקי.
D_307A = '''            return RedirectResponse(f"/hls-relay/_fix/{_fix_host}/{path}",
                                    status_code=302)
'''
D_307B = '''        return RedirectResponse(f"/hls-relay/{host}/{path}", status_code=302)
'''
OPTIONAL = [("307 ל-302 בהפניה האוטומטית", A_307A, N_307A, D_307A),
            ("307 ל-302 בנפילה מ-_fix", A_307B, N_307B, D_307B)]
EDITS = [("נקודת האבחון", A_ROUTE, N_ROUTE)]


def fn_source(src, name):
    for n in ast.walk(ast.parse(src)):
        if getattr(n, "name", "") == name and isinstance(
                n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ast.get_source_segment(src, n)
    return None


def validate(s):
    compile(s, PATH, "exec")
    tree = ast.parse(s)
    names = [n.name for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for f in ("debug_autofix", "hls_relay_fixed", "hls_relay",
              "_hls_autofix_wanted", "_h264_count_nals", "is_local_request"):
        assert names.count(f) == 1, f"{f} חסרה או כפולה"

    # המסלולים לא נרשמו פעמיים
    assert s.count('@api.get("/hls-relay/_fix/{host}/{path:path}")') == 1
    assert s.count('@api.get("/debug/autofix")') == 1

    dbg = fn_source(s, "debug_autofix")
    # ההגנה חייבת להיות הדבר הראשון, לפני שנגענו בכלום
    body = [l.strip() for l in dbg.splitlines()
            if l.strip() and not l.strip().startswith("#")]
    i = next(k for k, l in enumerate(body) if "is_local_request" in l)
    assert i <= 2, f"בדיקת המקומיות אינה ראשונה (שורה {i})"
    assert "raise HTTPException(404" in dbg, "מבחוץ זה אינו 404"
    for k in ("profile_marker", "idr_cache", "probe_in_flight",
              "would_redirect", "autofix_on"):
        assert f'"{k}"' in dbg, f"חסר {k} בתשובה"
    assert "run_in_executor" in dbg, "הבדיקה חוסמת את הלולאה"
    # כל שדה שיוצא חייב לעבור מיסוך — הפלט נועד להעתקה
    assert '"src": _red(src)' in dbg, "ה-src אינו ממוסך"
    assert "[_red(l) for l in err.splitlines()" in dbg, "ה-stderr אינו ממוסך"

    # המיסוך עצמו: מסתיר מארח ואסימון, שומר את הודעת השגיאה.
    # החילוץ דרך AST ולא לפי הזחה — ניסיון קודם שלי לחתוך לפי הזחה
    # תפס גם את המשך חתימת הפונקציה העוטפת ונפל.
    red_node = next(
        n for n in ast.walk(ast.parse(s))
        if isinstance(n, ast.FunctionDef) and n.name == "_red")
    nsr = {}
    exec(ast.get_source_segment(s, red_node), nsr)
    red = nsr["_red"]
    t1 = red("http://127.0.0.1:8000/hls-relay/tv.example.tv/iptv/ABCDEFGH12/2/i.m3u8")
    assert "example.tv" not in t1 and "ABCDEFGH12" not in t1, t1
    t2 = red("Server returned 404 Not Found")
    assert "404 Not Found" in t2, "המיסוך מוחק את הודעת השגיאה"

    # אין יותר 307 באף מסלול
    for f in ("hls_relay", "hls_relay_fixed"):
        src_f = fn_source(s, f)
        assert "status_code=307" not in src_f, f"נשאר 307 ב-{f}"
        assert "status_code=302" in src_f, f"חסר 302 ב-{f}"

    # ── התנהגות: ההגנה ──────────────────────────────────────────────────
    # Request הוא רק הערת טיפוס, אבל היא מוערכת בזמן ה-def ולכן חייבת
    # להיות בתחום — נתפס בבדיקה.
    ns = {"Request": object}
    exec(fn_source(s, "is_local_request"), ns)
    loc = ns["is_local_request"]

    class _R:
        def __init__(self, h, ip): self.headers = h; self.client = type(
            "C", (), {"host": ip})()

    assert loc(_R({}, "127.0.0.1")) is True, "curl מקומי נחסם"
    assert loc(_R({"x-forwarded-for": "1.2.3.4"}, "127.0.0.1")) is False, \
        "בקשה דרך nginx נחשבה מקומית"
    assert loc(_R({}, "8.8.8.8")) is False
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
    for dep in NEEDS:
        if dep not in src:
            sys.exit(f"✗ דורש {dep}, שאינו מוחל. לא נוגע בכלום.")
    if "JSONResponse" not in src:
        sys.exit("✗ JSONResponse אינו מיובא. לא נוגע בכלום.")

    out = src
    for label, a, n, done in OPTIONAL:
        if out.count(a) == 1:
            out = out.replace(a, n)
            print(f"  ✓ {label}")
        elif done in out:
            print(f"  ● {label} — כבר 302")
        else:
            sys.exit(f"✗ '{label}': לא נמצא לא 307 ולא 302. לא נוגע בכלום.")
    for label, a, n in EDITS:
        if out.count(a) != 1:
            sys.exit(f"✗ העוגן '{label}' נמצא {out.count(a)} פעמים — "
                     "לא נוגע בכלום.")
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
    print("התשובה המלאה בפקודה אחת (מהשרת, ל-127.0.0.1 — מבחוץ זה 404).")
    print("ה-host וה-path נשלפים מהקטלוג ולא נכתבים כאן: שם המארח של")
    print("הספק אינו נכנס לשום קובץ במאגר.")
    print()
    print("  SLUG=5plus")
    print("  read H P < <(python3 - \"$SLUG\" <<'PY'")
    print("import json, sys, re")
    print("from urllib.parse import urlparse")
    print("items = json.load(open('/opt/zovex-bot/data/content.json'))")
    print("u = next(i['video_url'] for i in items")
    print("         if i.get('is_live') and i.get('custom_slug') == sys.argv[1])")
    print("m = re.match(r'^/hls-relay/(?:_fix/)?([^/]+)/(.+)$', urlparse(u).path)")
    print("print(m.group(1), m.group(2))")
    print("PY")
    print("  )")
    print("  curl -s -G 'http://127.0.0.1:8000/debug/autofix' \\")
    print("       --data-urlencode \"host=$H\" --data-urlencode \"path=$P\" \\")
    print("       --data 'run=1' | python3 -m json.tool")
    print()
    print("ה-JSON מכיל את כל מה שההחלטה נשענת עליו. אם תעתיק אותו,")
    print("הקפד למסך את שם המארח שמופיע בשדה src.")


if __name__ == "__main__":
    main()
