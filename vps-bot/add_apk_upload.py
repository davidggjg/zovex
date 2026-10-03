#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""add_apk_upload — להעלות את ה-APK לשרת מהדפדפן, במקום שהוא ימשוך.

## למה

הקו מהשרת לגיטהאב נמדד ב-~45KB/ש: 64MB דורשים כ-25 דקות, בעוד אותה
הורדה לטלפון לוקחת 10 שניות. לכן:

* הרענון האוטומטי (‎timeout=180‎) **אינו יכול להצליח לעולם** — הוא מת
  אחרי 3 דקות מתוך 25, ובשקט, כי הוא רץ ברקע.
* וגם הורדה ידנית עם 600 שניות נקטעה ב-27MB מתוך 67MB.

התוצאה: המטמון החזיק גרסה ישנה, ועדכון כפוי היה שולח את כל המשתמשים
להתקין בדיוק את מה שהם כבר מריצים — לולאה סגורה שאי אפשר לצאת ממנה,
כי ‎min‎ כבר חוסם אותם.

הפתרון הפשוט הוא להפוך את הכיוון: מי שיש לו קו מהיר מוריד, והשרת רק
מקבל.

## מה נוסף

    GET  /panel/apk-upload   דף העלאה (סיסמת פאנל)
    POST /panel/apk-upload   גוף גולמי, הסיסמה בכותרת

**גוף גולמי ולא multipart**, בדיוק מאותה סיבה שתועדה ב-
‎/panel/saved-upload‎: ‎UploadFile/Form‎ דורשים את ‎python-multipart‎,
ואם היא חסרה — האפליקציה **כולה** אינה עולה. פיצ'ר צדדי שמפיל את
האתר אינו פיצ'ר.

## מה נבדק לפני הכתיבה לדיסק

חתימת ZIP, גודל מינימלי, ושהארכיון באמת מכיל ‎AndroidManifest.xml‎.
ואז הגרסה נחלצת מתוכו ומוחזרת לדף — כדי שתראה **מה** הועלה ולא רק
ש"הועלה". קובץ שגוי שנכנס למטמון מופץ לכל המשתמשים.

הכתיבה היא לקובץ זמני ורק אז ‎replace‎, כך שהעלאה שנקטעה באמצע אינה
משאירה מטמון חצי-כתוב.

    python3 add_apk_upload.py --check
    python3 add_apk_upload.py
    python3 add_apk_upload.py --revert

אחרי ההחלה:  systemctl restart zovex-bot
ואז בדפדפן:  https://<האתר>/panel/apk-upload
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_apk_upload"
MARK = "add_apk_upload"

A_ANCHOR = '''    APP_VERSION_FILE.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "version": v}
'''

N_ANCHOR = '''    APP_VERSION_FILE.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "version": v}


# ── [add_apk_upload] העלאת APK מהדפדפן ───────────────────────────────────
#
# הקו מהשרת לגיטהאב נמדד ב-~45KB/ש — 64MB הם כ-25 דקות, והרענון
# האוטומטי מוותר אחרי 180 שניות. במקום להילחם בקו, הופכים את הכיוון:
# מי שיש לו קו מהיר מוריד, והשרת מקבל.

def _apk_version_of(path) -> str:
    """‎versionName‎ מתוך ה-APK, או מחרוזת ריקה.

    ‎AndroidManifest.xml‎ ב-APK הוא בינארי, והמחרוזות בתוכו UTF-16LE.
    פענוח גס ואז חיפוש תבנית גרסה מספיק כאן — המטרה היא **להראות מה
    הועלה**, לא לנתח את הפורמט.
    """
    # ייבוא מקומי: zipfile אינו מיובא ב-main.py, והוספת ייבוא גלובלי
    # היא עוגן נוסף בראש הקובץ בתמורה לשום דבר. הוא נדרש פעם בהעלאה.
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            man = z.read("AndroidManifest.xml")
    except Exception:
        return ""
    txt = man.decode("utf-16-le", "ignore")
    # ‎\\b‎ אינו שמיש כאן: ה-manifest בינארי, והפענוח הגס מייצר מסביב
    # תווים שפייתון מחשיב כתווי מילה (CJK) — ואז אין גבול מילה והחיפוש
    # מחזיר אפס. נתפס בבדיקה העצמית על ארכיון אמיתי.
    hits = re.findall(r"(?<![\\d.])\\d+\\.\\d+\\.\\d+(?![\\d.])", txt)
    return hits[0] if hits else ""


# ‎r"""‎ ולא ‎"""‎: בתוך מחרוזת פייתון רגילה, ‎\\n‎ שנועד ל-JS הופך
# לשורה חדשה **אמיתית** עוד לפני שהדף נשלח — ומחרוזת JS בגרש יחיד
# שנקטעת בשורה חדשה היא שגיאת תחביר. התוצאה: הסקריפט כולו אינו
# נטען, ‎go.onclick‎ לא מוצב, והכפתור פשוט לא מגיב.
_APK_UPLOAD_HTML = r"""<!doctype html><html lang="he" dir="rtl"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>העלאת APK</title><style>
body{font-family:system-ui,Arial;background:#0f1115;color:#e8e8e8;margin:0;
 padding:24px;display:flex;justify-content:center}
.c{width:100%;max-width:460px}h1{font-size:20px;margin:0 0 6px}
p.s{color:#8b92a0;font-size:13px;margin:0 0 20px;line-height:1.6}
input{width:100%;box-sizing:border-box;padding:12px;margin:8px 0;
 border-radius:10px;border:1px solid #2a2f3a;background:#161922;color:#e8e8e8;
 font-size:15px}
button{width:100%;padding:14px;margin-top:12px;border:0;border-radius:10px;
 background:#e50914;color:#fff;font-size:16px;font-weight:700}
button:disabled{background:#3a3f4a}
#bar{height:8px;background:#1d212b;border-radius:6px;overflow:hidden;
 margin-top:14px;display:none}#fill{height:100%;width:0;background:#e50914}
#msg{margin-top:14px;font-size:14px;line-height:1.7;white-space:pre-wrap}
.ok{color:#4ade80}.err{color:#f87171}
</style><div class="c">
<h1>העלאת APK לשרת</h1>
<p class="s">הקובץ נכנס ישירות למטמון שממנו המשתמשים מורידים.
בדוק שהגרסה שמוצגת בסוף היא מה שהתכוונת לפרסם.</p>
<input type="password" id="pw" placeholder="סיסמת פאנל" autocomplete="current-password">
<input type="file" id="f" accept=".apk,application/vnd.android.package-archive">
<button id="go">העלה</button>
<div id="bar"><div id="fill"></div></div>
<div id="msg"></div></div>
<script>
var go=document.getElementById('go'),msg=document.getElementById('msg'),
    bar=document.getElementById('bar'),fill=document.getElementById('fill');
go.onclick=function(){
  var f=document.getElementById('f').files[0],pw=document.getElementById('pw').value;
  if(!f){msg.className='err';msg.textContent='לא נבחר קובץ';return;}
  if(!pw){msg.className='err';msg.textContent='חסרה סיסמה';return;}
  go.disabled=true;bar.style.display='block';msg.className='';
  msg.textContent='מעלה '+(f.size/1048576).toFixed(1)+'MB...';
  var x=new XMLHttpRequest();
  x.open('POST','/panel/apk-upload');
  x.setRequestHeader('x-panel-password',pw);
  x.setRequestHeader('Content-Type','application/octet-stream');
  x.upload.onprogress=function(e){
    if(e.lengthComputable)fill.style.width=(e.loaded/e.total*100).toFixed(1)+'%';};
  x.onload=function(){
    go.disabled=false;
    try{var r=JSON.parse(x.responseText);}catch(_){r={};}
    if(x.status===200&&r.ok){msg.className='ok';
      msg.textContent='\\u2713 הועלה בהצלחה\\n\\nגרסה: '+(r.version||'לא זוהתה')+
        '\\nגודל: '+(r.size/1048576).toFixed(1)+'MB'+
        '\\n\\nעכשיו אפשר למלא את הגרסה בפאנל הניהול.';}
    else{msg.className='err';msg.textContent='\\u2717 '+(r.detail||('שגיאה '+x.status));}};
  x.onerror=function(){go.disabled=false;msg.className='err';
    msg.textContent='\\u2717 ההעלאה נכשלה (רשת)';};
  x.send(f);};
</script></html>"""


@api.get("/panel/apk-upload", response_class=HTMLResponse)
async def apk_upload_page():
    return HTMLResponse(_APK_UPLOAD_HTML)


@api.post("/panel/apk-upload")
async def apk_upload(request: Request):
    """גוף גולמי, לא multipart.

    אותו נימוק שתועד ב-/panel/saved-upload: UploadFile/Form דורשים את
    python-multipart, ובלעדיה **כל** האפליקציה אינה עולה. פיצ'ר צדדי
    שמפיל את האתר אינו פיצ'ר.
    """
    check_panel_password(request, request.headers.get("x-panel-password", ""))
    tmp = APK_CACHE_FILE.with_suffix(".upload")
    n = 0
    try:
        with tmp.open("wb") as fh:
            async for chunk in request.stream():
                fh.write(chunk)
                n += len(chunk)
        if n < 1_000_000:
            raise HTTPException(400, f"קובץ קטן מדי ({n} בתים) — לא APK")
        with tmp.open("rb") as fh:
            if fh.read(4) != b"PK\\x03\\x04":
                raise HTTPException(400, "אינו קובץ APK (חתימת ZIP חסרה)")
        ver = _apk_version_of(tmp)
        if not ver:
            raise HTTPException(400, "לא נמצא AndroidManifest — אינו APK")
        # רק עכשיו, כשהכל אומת, נוגעים במטמון שהמשתמשים מורידים ממנו
        tmp.replace(APK_CACHE_FILE)
        # והנעילה: בלי זה, 6 שעות אחרי ההעלאה הבקשה הבאה מושכת שוב
        # מ-APK_SOURCE_URL ודורסת בדיוק את מה שהעלינו.
        APK_PIN_FILE.write_text(ver, encoding="utf-8")
        log.info("✅ APK הועלה ידנית: %s (%.1f MB)", ver, n / 1e6)
        return {"ok": True, "version": ver, "size": n}
    except HTTPException:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as e:
        tmp.unlink(missing_ok=True)
        log.warning("העלאת APK נכשלה: %s", e)
        raise HTTPException(500, f"ההעלאה נכשלה: {e}")
'''

# ── 2. המטמון שהועלה ביד אינו מתיישן ─────────────────────────────────────
#
# ‎_refresh_apk_cache‎ מחשיב את המטמון "טרי" רק 6 שעות. אחרי זה הבקשה
# הבאה מושכת שוב מ-‎APK_SOURCE_URL‎ — כלומר מגיטהאב — ודורסת את מה
# שהעלינו ביד.
#
# בזמן **עדכון כפוי** זו לא אי-נוחות אלא מלכודת סגורה: כל המשתמשים
# חסומים ב-‎min‎, ומה שהם מורידים חוזר להיות דווקא הגרסה הישנה שבגללה
# הם חסומים. הם יתקינו אותה, ייחסמו שוב, ויורידו שוב — בלי מוצא.
#
# ולכן העלאה ידנית מניחה סימון, והסימון עוצר את המשיכה האוטומטית
# בלבד. רענון יזום מהפאנל (‎force=True‎) עדיין גובר, והוא דרך היציאה.
A_PIN = '''_apk_lock = asyncio.Lock()
'''

N_PIN = '''_apk_lock = asyncio.Lock()

# [add_apk_upload] קיים ⇒ המטמון הוכן ביד ואין למשוך עליו מבחוץ.
APK_PIN_FILE = DATA_DIR / "zovex-latest.apk.pinned"
'''

A_FRESH = '''        fresh = (APK_CACHE_FILE.exists()
                 and APK_CACHE_FILE.stat().st_size > 1_000_000
                 and (time.time() - APK_CACHE_FILE.stat().st_mtime) < 6 * 3600)
        if fresh and not force:
            return True
'''

N_FRESH = '''        # [add_apk_upload] קובץ שהועלה ידנית אינו מתיישן לעולם. גיל של
        # 6 שעות הוא קריטריון נכון לקובץ שנמשך מבחוץ, ושגוי לחלוטין
        # לקובץ שנבחר במפורש — שם היישנות פירושה לדרוס את הבחירה.
        if APK_PIN_FILE.exists() and not force:
            if APK_CACHE_FILE.exists() and APK_CACHE_FILE.stat().st_size > 1_000_000:
                return True
            # הסימון שרד בלי הקובץ (מחיקה ידנית) — הוא חסר משמעות
            APK_PIN_FILE.unlink(missing_ok=True)
        fresh = (APK_CACHE_FILE.exists()
                 and APK_CACHE_FILE.stat().st_size > 1_000_000
                 and (time.time() - APK_CACHE_FILE.stat().st_mtime) < 6 * 3600)
        if fresh and not force:
            return True
'''

A_DROP = '''            tmp.replace(APK_CACHE_FILE)
            log.info("✅ APK עודכן במטמון (%.1f MB)", APK_CACHE_FILE.stat().st_size / 1e6)
'''

N_DROP = '''            tmp.replace(APK_CACHE_FILE)
            # [add_apk_upload] ירד קובץ מבחוץ — מה שבמטמון כבר אינו
            # ההעלאה הידנית, והסימון היה הופך לשקר.
            APK_PIN_FILE.unlink(missing_ok=True)
            log.info("✅ APK עודכן במטמון (%.1f MB)", APK_CACHE_FILE.stat().st_size / 1e6)
'''

EDITS = [
    ("נתיבי העלאת APK", A_ANCHOR, N_ANCHOR, 1),
    ("הגדרת הסימון", A_PIN, N_PIN, 1),
    ("הסימון עוצר התיישנות", A_FRESH, N_FRESH, 1),
    ("משיכה מוצלחת מסירה סימון", A_DROP, N_DROP, 1),
]


def fn_source(src: str, name: str) -> str:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"לא נמצאה הפונקציה {name}")


def validate(out: str) -> None:
    compile(out, "main.py", "exec")

    for need in ("^import re", "APK_CACHE_FILE",
                 "check_panel_password", "HTMLResponse"):
        ok = (__import__("re").search(need, out, __import__("re").M)
              if need.startswith("^") else need in out)
        assert ok, f"חסר {need} — הפאצ' מסתמך עליו"

    # ── ה-JS בדף חייב להיות תקין ─────────────────────────────────────
    # באג שקרה: ‎\\n‎ בתוך מחרוזת פייתון רגילה הפך לשורה חדשה אמיתית,
    # שברה מחרוזת JS בגרש יחיד, והסקריפט כולו לא נטען — הכפתור לא הגיב
    # ושום שגיאה לא הופיעה בשרת.
    i_html = out.index("_APK_UPLOAD_HTML")
    html = out[i_html:out.index('"""', out.index('"""', i_html) + 3)]
    assert 'r"""' in out[i_html:i_html + 60], "מחרוזת ה-HTML אינה raw"
    for ln in html.splitlines():
        if "textContent=" in ln or "msg.textContent" in ln:
            assert ln.count("'") % 2 == 0, \
                f"מחרוזת JS נקטעת בשורה חדשה: {ln.strip()[:60]}"
    assert "\\n" in html, "רצפי השורה ל-JS נעלמו"

    up = fn_source(out, "apk_upload")
    assert "check_panel_password" in up, "הנתיב אינו מוגן בסיסמה"
    assert "request.stream()" in up, "אינו גוף גולמי"
    assert "multipart" not in up.lower() or "python-multipart" in up, \
        "נכנס multipart — זה מפיל את האפליקציה אם החבילה חסרה"
    assert "tmp.replace(APK_CACHE_FILE)" in up, "אין החלפה אטומית"
    i_rep = up.index("tmp.replace(")
    for guard in ('raise HTTPException(400, f"קובץ קטן מדי',
                  'חתימת ZIP חסרה', "לא נמצא AndroidManifest"):
        assert guard in up[:i_rep], f"הבדיקה '{guard[:24]}' אחרי ההחלפה"

    # ── חילוץ הגרסה, מורץ על APK אמיתי למדי ────────────────────────────
    import io
    import re as _re
    import zipfile as _zip
    ns = {"re": _re}
    exec(fn_source(out, "_apk_version_of"), ns)
    ver_of = ns["_apk_version_of"]

    buf = io.BytesIO()
    with _zip.ZipFile(buf, "w") as z:
        z.writestr("AndroidManifest.xml",
                   b"\x00\x03" + "1.0.49".encode("utf-16-le") + b"\x00")
        z.writestr("classes.dex", b"x" * 100)
    buf.seek(0)
    p = "/tmp/_apk_test.apk"
    open(p, "wb").write(buf.getvalue())
    assert ver_of(p) == "1.0.49", f"גרסה לא חולצה: {ver_of(p)!r}"

    # ארכיון בלי manifest ⇒ ריק, לא קריסה
    buf2 = io.BytesIO()
    with _zip.ZipFile(buf2, "w") as z:
        z.writestr("other.txt", b"hi")
    open(p, "wb").write(buf2.getvalue())
    assert ver_of(p) == "", "ארכיון בלי manifest לא הוחזר ריק"

    # ולא-zip בכלל ⇒ ריק
    open(p, "wb").write(b"not a zip at all")
    assert ver_of(p) == "", "קובץ שאינו zip לא הוחזר ריק"
    os.unlink(p)

    # ── וההחלטה על המטמון, מורצת באמת ─────────────────────────────────
    #
    # זו הבדיקה היחידה שחשובה כאן: "האם השרת ימשוך מגיטהאב ויחליף את
    # מה שהועלה". טענה טקסטואלית לא הייתה תופסת היפוך תנאי, ולכן
    # הפונקציה עצמה רצה — מול httpx מזויף שסופר משיכות.
    assert "APK_PIN_FILE" in fn_source(out, "apk_upload"), \
        "ההעלאה אינה מניחה סימון"
    _run_refresh_tests(out)


def _run_refresh_tests(out: str) -> None:
    import asyncio
    import pathlib
    import tempfile
    import time as _time

    pulls = []

    class _Resp:
        status_code = 200

        async def aiter_bytes(self, n):
            yield b"x" * 2_000_000

    class _Stream:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *a):
            return False

    class _Cli:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url):
            pulls.append(url)
            return _Stream()

    class _Log:
        def info(self, *a, **k):
            pass

        warning = info

    d = pathlib.Path(tempfile.mkdtemp())
    cache = d / "zovex-latest.apk"
    pin = d / "zovex-latest.apk.pinned"
    ns = {
        "asyncio": asyncio, "time": _time, "log": _Log(),
        "httpx": type("H", (), {"AsyncClient": _Cli}),
        "APK_CACHE_FILE": cache, "APK_PIN_FILE": pin,
        "APK_SOURCE_URL": "http://example.invalid/zovex.apk",
        "_apk_lock": asyncio.Lock(),
    }
    exec(fn_source(out, "_refresh_apk_cache"), ns)
    refresh = ns["_refresh_apk_cache"]

    def run(**kw):
        pulls.clear()
        return asyncio.run(refresh(**kw)), list(pulls)

    # א. הועלה ביד, והקובץ ישן בהרבה מ-6 שעות ⇒ אסור למשוך.
    cache.write_bytes(b"u" * 2_000_000)
    pin.write_text("1.0.49")
    old = _time.time() - 48 * 3600
    os.utime(cache, (old, old))
    ok, got = run()
    assert ok and not got, f"המטמון הידני נדרס אחרי 6 שעות (משיכות: {got})"
    assert cache.read_bytes()[:1] == b"u", "תוכן המטמון הידני הוחלף"

    # ב. אותו מצב בלי סימון ⇒ כן מושך. בלי זה סעיף א' חסר ערך: ייתכן
    #    שהוא עובר כי שום משיכה לא קורית אף פעם.
    pin.unlink()
    ok, got = run()
    assert ok and len(got) == 1, f"קובץ ישן לא נמשך מחדש (משיכות: {got})"

    # ג. רענון יזום מהפאנל גובר על הסימון — זו דרך היציאה.
    cache.write_bytes(b"u" * 2_000_000)
    pin.write_text("1.0.49")
    ok, got = run(force=True)
    assert ok and len(got) == 1, f"force לא גבר על הסימון (משיכות: {got})"
    assert not pin.exists(), "הסימון שרד משיכה מוצלחת — הוא כבר לא נכון"

    # ד. סימון יתום (הקובץ נמחק ביד) אינו חוסם.
    cache.unlink(missing_ok=True)
    pin.write_text("1.0.49")
    ok, got = run()
    assert ok and len(got) == 1, f"סימון בלי קובץ חסם משיכה (משיכות: {got})"

    shutil.rmtree(d, ignore_errors=True)


def main() -> None:
    if not os.path.exists(PATH):
        sys.exit(f"אין קובץ ב-{PATH} (אפשר MAIN_PY=...)")
    with open(PATH, encoding="utf-8") as fh:
        src = fh.read()

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
    for label, a, n, want in EDITS:
        got = out.count(a)
        if got != want:
            sys.exit(f"✗ העוגן '{label}' נמצא {got} פעמים (צפוי {want}) — "
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
    print("systemctl restart zovex-bot")
    print()
    print("ואז בדפדפן:  https://zovex.duckdns.org/panel/apk-upload")


if __name__ == "__main__":
    main()
