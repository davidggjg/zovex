#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_relay_deadline — ספק מושבת לא יהפוך לתקיעה של 45 שניות.

## מה נמדד, אחרי ההפעלה מחדש של השרת

99 ערוצי שידור חי דרך הממסר, מקובצים לפי ספק:

    ספק א׳  (7 ערוצים)    7/7   עובדים
    ספק ב׳  (40 ערוצים)   24/24 עובדים
    ספק ג׳  (4 ערוצים)    4/4   עובדים
    ספק ד׳  (46 ערוצים)   0/14  **אף אחד**

כלומר: השרת בסדר, והספק הרביעי מושבת. זה לא באג אצלנו.

## מה **כן** אצלנו, וזה מה שהמשתמשים ראו

ערוץ של הספק המושבת לא החזיר שגיאה — הוא **נתקע**:

    ניקולודיון   בקשה ראשונה: אין תשובה אחרי 25ש · שנייה: אותו דבר
    HOT GOLD     אין תשובה אחרי 45 שניות
    one edge     200 בתוך 0.87ש  (ספק אחר, לשליטה)

45 שניות מתפרקות כך: ‎profile 0‎ מחכה עד 12ש לסגמנט ראשון, אימות ה-IDR
עוד עד 8ש, ‎profile 1‎ עוד 12ש, ואז הפניה למסלול הרגיל שמחכה 15ש משלו.
הכול בזמן שהמקור פשוט אינו עונה.

**תקיעה גרועה משגיאה.** שגיאה גורמת לנגן להציג הודעה ולעבור הלאה;
תקיעה מציגה ספינר לנצח, וזה נראה למשתמש כמו "כלום לא עובד" — גם כשרוב
הערוצים דווקא פועלים. זה מה שדווח.

## מה משתנה

1. **בודקים את המקור לפני שמפעילים ffmpeg.** בקשה אחת, תקרה של 4
   שניות, דרך המסלול הרגיל שלנו — כלומר בלי לשכתב לוגיקת סכימה,
   הרשאות או User-Agent, ובלי לעקוף את הבדיקה של playlist ריק. מקור
   שאינו עונה מקבל 502 מיד, ואף ffmpeg לא נולד.

   העלות במסלול המוצלח היא אפס בפועל: ‎_hls_fix_start‎ מיד אחר כך נותן
   ל-ffmpeg את אותו URL, ומטמון ה-manifest (1.5ש) מגיש לו את מה
   שהבדיקה הרגע הביאה.

2. **מועד יעד לכל הבקשה.** לפני שמתחילים פרופיל נוסף נבדק הזמן שעבר.
   חריגה ⇒ 502 מיד, **בלי** ההפניה למסלול הרגיל — שהיא עוד 15 שניות
   על מקור שכבר הוכח כלא עונה.

3. **זיכרון קצר של "לא עונה".** 45 שניות. הבקשה הבאה מקבלת 502 בתוך
   מיליוניות שנייה במקום לשלם שוב על אותה גלגלת. פג מעצמו, ולכן
   התאוששות של הספק אינה דורשת כלום.

## למה 45 שניות ולא יותר

הסימון הוא ויתור: צופה שמבקש ערוץ שהתאושש רגע לפני קבלת 502. 45 שניות
הן מחיר קטן מול תקיעה של 45 שניות בכל בקשה — והספק שנמדד כאן מושבת
לשעות, לא לשניות.

## מה זה לא מתקן

46 הערוצים של הספק המושבת לא יתנגנו מזה. מה שהם יעשו הוא **להיכשל
מהר ובאמירה מפורשת**, ולהפסיק להאט את הערוצים שכן עובדים — כי כל
בקשה תקועה החזיקה תהליך ffmpeg וחיבור על אותו מעבד שמזרים את השאר.

    python3 fix_relay_deadline.py --check
    python3 fix_relay_deadline.py
    python3 fix_relay_deadline.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_relay_deadline"
MARK = "fix_relay_deadline"

# ── 1. קבועים, מטמון "לא עונה", ובדיקת המקור ──────────────────────────────
A_CONST = '''_hls_manifest_cache: dict = {}
MANIFEST_CACHE_TTL = 1.5
'''

N_CONST = '''_hls_manifest_cache: dict = {}
MANIFEST_CACHE_TTL = 1.5

# [fix_relay_deadline] מועד יעד לבקשת playlist, ותקרה לבדיקת המקור.
# נמדד: ערוץ של ספק מושבת לא החזיר שגיאה אלא נתקע 25–45 שניות, כי כל
# שלב חיכה בתורו (12ש לסגמנט, 8ש לאימות, 12ש לפרופיל שני, 15ש להפניה).
HLS_FIX_DEADLINE = float(os.environ.get("HLS_FIX_DEADLINE", "14"))
HLS_UP_PROBE_TIMEOUT = float(os.environ.get("HLS_UP_PROBE_TIMEOUT", "4"))
HLS_DEAD_TTL = float(os.environ.get("HLS_DEAD_TTL", "45"))
_hls_dead: dict = {}                 # key -> (expires_at, reason)


def _hls_dead_reason(key: str):
    """הסיבה שהערוץ סומן כלא-עונה, או None. פג מעצמו."""
    hit = _hls_dead.get(key)
    if not hit:
        return None
    if hit[0] <= time.time():
        _hls_dead.pop(key, None)
        return None
    return hit[1]


def _hls_mark_dead(key: str, reason: str) -> None:
    """סימון קצר-מועד. ההתאוששות של הספק לא דורשת מאיתנו כלום."""
    _hls_dead[key] = (time.time() + HLS_DEAD_TTL, reason)


async def _hls_upstream_alive(host: str, path: str):
    """‎(עונה?, סיבה)‎ — בקשה אחת מהירה לפני שמפעילים המרה.

    דרך המסלול הרגיל שלנו ב-127.0.0.1, בדיוק כמו שההמרה עצמה מקבלת את
    הקלט שלה. כך אין כאן שכתוב של לוגיקת הסכימה, ההרשאות או ה-User-Agent,
    והבדיקה של playlist ריק שכבר קיימת שם חלה גם על הבדיקה הזאת.
    """
    if _hls_relay_client is None:
        return True, ""              # לפני האתחול אין מה לבדוק
    src = f"http://127.0.0.1:{PORT}/hls-relay/{host}/{path}"
    try:
        r = await _hls_relay_client.get(src, timeout=HLS_UP_PROBE_TIMEOUT)
    except Exception as e:
        return False, (f"המקור לא ענה תוך {HLS_UP_PROBE_TIMEOUT:.0f} שניות "
                       f"({type(e).__name__})")
    if r.status_code != 200:
        return False, f"המקור החזיר {r.status_code}"
    if _hls_manifest_entries(r.text) == 0:
        return False, "playlist ריק מהמקור"
    return True, ""
'''

# ── 2. בדיקה מקדימה ומועד יעד בתוך מסלול ההמרה ────────────────────────────
A_LOOP = '''    key = _hls_fix_key(host, path)
    # [fix_live_autofix] None (כשל מוחלט) נקרא כ-0, כדי שניסיון ישיר
    # ב-_fix ימשיך לנסות להתאושש ולא יקבל פרופיל None.
    first = _hls_fix_profile.get(key) or 0
    order = [first] + [p for p in (0, 1) if p != first]
    why = ""
    for profile in order:
'''

N_LOOP = '''    key = _hls_fix_key(host, path)

    # [fix_relay_deadline] מה שסומן כלא-עונה נכשל מיד, בלי לשלם שוב.
    dead = _hls_dead_reason(key)
    if dead:
        raise HTTPException(502, f"hls_fix: {dead}")

    # [fix_relay_deadline] המקור נבדק **לפני** שנולד ffmpeg. בלי זה
    # ערוץ של ספק מושבת מחזיק את הבקשה עשרות שניות ותהליך המרה שלם,
    # על אותו מעבד שמזרים את הערוצים שכן עובדים.
    _alive, _why_dead = await _hls_upstream_alive(host, path)
    if not _alive:
        _hls_mark_dead(key, _why_dead)
        log.warning("hls_fix: %s — %s · לא מפעילים המרה", key, _why_dead)
        raise HTTPException(502, f"hls_fix: {_why_dead}")

    _t_start = time.time()
    # [fix_live_autofix] None (כשל מוחלט) נקרא כ-0, כדי שניסיון ישיר
    # ב-_fix ימשיך לנסות להתאושש ולא יקבל פרופיל None.
    first = _hls_fix_profile.get(key) or 0
    order = [first] + [p for p in (0, 1) if p != first]
    why = ""
    for profile in order:
        # [fix_relay_deadline] מועד היעד נבדק לפני כל פרופיל. חריגה
        # מחזירה 502 מיד ו**לא** מפנה למסלול הרגיל, כי הפניה על מקור
        # שהוכח כלא עונה היא עוד 15 שניות של תקיעה.
        if time.time() - _t_start > HLS_FIX_DEADLINE:
            why = why or f"חריגה מ-{HLS_FIX_DEADLINE:.0f} שניות"
            _hls_fix_profile[key] = None
            _hls_fix_failed_at[key] = time.time()
            _hls_mark_dead(key, why)
            log.error("hls_fix: %s — %s", key, why)
            raise HTTPException(502, f"hls_fix: {why}")
'''

# ── 3. ההמתנה לסגמנט הראשון מכבדת את מועד היעד ────────────────────────────
A_WAIT = '''        for _ in range(120):                  # עד ~12 שניות לסגמנטים ראשונים
            if idx.exists() and idx.read_text(encoding="utf-8", errors="ignore").count(".m4s") >= 1:
                ok = True
                break
            if ent["proc"].returncode is not None:
                break
            await asyncio.sleep(0.1)
'''

N_WAIT = '''        for _ in range(120):                  # עד ~12 שניות לסגמנטים ראשונים
            if idx.exists() and idx.read_text(encoding="utf-8", errors="ignore").count(".m4s") >= 1:
                ok = True
                break
            if ent["proc"].returncode is not None:
                break
            # [fix_relay_deadline] גם כאן, ולא רק בין פרופילים: ההמתנה
            # הזאת היא רוב ה-12 השניות, ואין טעם להשלים אותה כשהמועד
            # כבר עבר.
            if time.time() - _t_start > HLS_FIX_DEADLINE:
                break
            await asyncio.sleep(0.1)
'''

# ── 4. פסק זמן במסלול הרגיל מסמן, כדי שלא ישולם שוב ──────────────────────
A_PLAIN = '''                try:
                    resp = await _hls_relay_client.get(
                        upstream_url, headers=HLS_RELAY_UPSTREAM_HEADERS)
                except httpx.HTTPError as e:
                    raise HTTPException(
                        502, f"hls_relay: upstream fetch failed - {e}")
'''

N_PLAIN = '''                try:
                    resp = await _hls_relay_client.get(
                        upstream_url, headers=HLS_RELAY_UPSTREAM_HEADERS)
                except httpx.HTTPError as e:
                    # [fix_relay_deadline] פסק זמן מסומן לזמן קצר. בלי זה
                    # כל בקשה לאותו ערוץ משלמת שוב 15 שניות המתנה, גם
                    # כשברור שהמקור אינו עונה.
                    if isinstance(e, (httpx.TimeoutException,
                                      httpx.ConnectError)):
                        _hls_mark_dead(_hls_fix_key(host, path),
                                       f"המקור לא ענה ({type(e).__name__})")
                    raise HTTPException(
                        502, f"hls_relay: upstream fetch failed - {e}")
'''

EDITS = [
    ("קבועים ובדיקת המקור", A_CONST, N_CONST),
    ("בדיקה מקדימה ומועד יעד", A_LOOP, N_LOOP),
    ("המתנה לסגמנט ראשון", A_WAIT, N_WAIT),
    ("סימון פסק זמן במסלול הרגיל", A_PLAIN, N_PLAIN),
]


# ── אימות ─────────────────────────────────────────────────────────────────
def fn_source(src: str, name: str) -> str:
    """מקור הפונקציה לפי AST ולא לפי הזחה.

    חילוץ לפי הזחה גרר פעם את המשך החתימה של הפונקציה העוטפת, והבדיקה
    בדקה טקסט שאינו הפונקציה."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"לא נמצאה הפונקציה {name}")


def code_only(text: str) -> str:
    """בלי מחרוזות תיעוד ובלי הערות.

    זה נדרש כי טענות על מחרוזות נפלו ארבע פעמים על ההערות של עצמי —
    מחרוזת שמופיעה בהסבר אינה מחרוזת שמופיעה בקוד."""
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("#"):
            continue
        out.append(ln)
    joined = "\n".join(out)
    # מחרוזות תיעוד: החלק שבין שלושה גרשיים
    parts = joined.split('"""')
    return "".join(parts[::2]) if len(parts) > 2 else joined


def validate(out: str) -> None:
    compile(out, "main.py", "exec")

    # תלות: הבדיקה של playlist ריק חייבת להיות מותקנת לפני זה
    assert "_hls_manifest_entries" in out, \
        "חסר _hls_manifest_entries — הרץ קודם fix_empty_manifest.py"

    fixed = code_only(fn_source(out, "hls_relay_fixed"))
    assert "_hls_dead_reason(key)" in fixed, "אין בדיקת סימון בתחילת המסלול"
    assert "_hls_upstream_alive(host, path)" in fixed, "אין בדיקה מקדימה"
    assert fixed.count("HLS_FIX_DEADLINE") >= 2, \
        "מועד היעד אינו נבדק גם בין פרופילים וגם בהמתנה"
    # ההפניה למסלול הרגיל נשארת **רק** לכשל של ההמרה על מקור שכן עונה
    assert fixed.count("RedirectResponse") == 1, \
        "ההפניה למסלול הרגיל אבדה או שוכפלה"

    # הפונקציות החדשות מורצות בפועל, לא רק נקראות
    ns = {"time": __import__("time"), "os": os}
    for name in ("_hls_dead_reason", "_hls_mark_dead"):
        exec(fn_source(out, name), ns)
    ns["_hls_dead"] = {}
    ns["HLS_DEAD_TTL"] = 45.0
    assert ns["_hls_dead_reason"]("k") is None, "מפתח לא מסומן החזיר סיבה"
    ns["_hls_mark_dead"]("k", "המקור לא ענה")
    assert ns["_hls_dead_reason"]("k") == "המקור לא ענה", "הסימון לא נקרא"
    # פג מעצמו
    ns["_hls_dead"]["k"] = (ns["time"].time() - 1, "ישן")
    assert ns["_hls_dead_reason"]("k") is None, "סימון שפג לא נוקה"
    assert "k" not in ns["_hls_dead"], "סימון שפג נשאר במילון"

    # _hls_upstream_alive מול שלושה מקרים אמיתיים
    import asyncio

    class _Resp:
        def __init__(self, code, text):
            self.status_code, self.text = code, text

    class _Cli:
        def __init__(self, behave):
            self.behave = behave
            self.timeouts = []

        async def get(self, url, timeout=None, **kw):
            self.timeouts.append(timeout)
            if self.behave == "boom":
                raise TimeoutError("לא ענה")
            if self.behave == "empty":
                return _Resp(200, "#EXTM3U\n#EXT-X-TARGETDURATION:0\n")
            if self.behave == "404":
                return _Resp(404, "")
            return _Resp(200, "#EXTM3U\n#EXTINF:6,\nseg1.ts\n")

    ns2 = {"time": __import__("time"), "os": os, "PORT": 8000,
           "HLS_UP_PROBE_TIMEOUT": 4.0,
           "_hls_manifest_entries": lambda t: sum(
               1 for ln in t.splitlines()
               if ln.strip() and not ln.strip().startswith("#"))}
    exec(fn_source(out, "_hls_upstream_alive"), ns2)
    fn = ns2["_hls_upstream_alive"]

    ns2["_hls_relay_client"] = None
    assert asyncio.run(fn("h", "p")) == (True, ""), \
        "לפני אתחול הלקוח הבדיקה חייבת לא לחסום"

    cli = _Cli("boom")
    ns2["_hls_relay_client"] = cli
    alive, why = asyncio.run(fn("h", "p"))
    assert not alive and "לא ענה" in why, f"פסק זמן לא זוהה: {why}"
    assert cli.timeouts == [4.0], f"תקרת הבדיקה לא הועברה: {cli.timeouts}"

    ns2["_hls_relay_client"] = _Cli("empty")
    alive, why = asyncio.run(fn("h", "p"))
    assert not alive and "ריק" in why, f"playlist ריק לא זוהה: {why}"

    ns2["_hls_relay_client"] = _Cli("404")
    alive, why = asyncio.run(fn("h", "p"))
    assert not alive and "404" in why, f"קוד שגיאה לא זוהה: {why}"

    ns2["_hls_relay_client"] = _Cli("ok")
    assert asyncio.run(fn("h", "p")) == (True, ""), "מקור תקין נדחה"

    # הכתובת נבנית דרך המסלול שלנו ולא בשכתוב סכימה
    src_alive = code_only(fn_source(out, "_hls_upstream_alive"))
    assert "127.0.0.1" in src_alive and "/hls-relay/" in src_alive, \
        "הבדיקה אינה עוברת במסלול הרגיל"


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
    print("מעכשיו ערוץ של ספק שאינו עונה מחזיר 502 בתוך 4 שניות במקום")
    print("להיתקע 25–45, והבקשה הבאה מקבלת אותו מיד. ביומן:")
    print("  hls_fix: <מפתח> — המקור לא ענה תוך 4 שניות · לא מפעילים המרה")
    print()
    print("לספור כמה ערוצים במצב הזה בשעה האחרונה:")
    print("  journalctl -u zovex-bot --since '1 hour ago' \\")
    print("    | grep -c 'לא מפעילים המרה'")


if __name__ == "__main__":
    main()
