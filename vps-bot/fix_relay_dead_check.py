#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_relay_dead_check — הסימון נכתב ואף אחד לא קרא אותו.

## מה נמדד על השרת החי, אחרי fix_relay_deadline

    HOT GOLD     200 ב-4.1ש  ·  ואחר כך 0.64ש   — חזר לעבוד
    ניקולודיון   50ש+ בראשונה  ·  502 אחרי 15.4ש בשנייה

ה-502 הוא שיפור: קודם זו הייתה תקיעה בלי סוף. אבל **15 שניות בכל
בקשה** אינן תיקון, והסיבה מדויקת:

    $ grep -n "_hls_dead_reason" main.py
    2493: def _hls_dead_reason(key):        ← ההגדרה
    3370:     dead = _hls_dead_reason(key)   ← מסלול ההמרה בלבד

הפאץ' הקודם הוסיף ‎_hls_mark_dead‎ **גם** למסלול הרגיל, אבל את הבדיקה
הוא הוסיף רק למסלול ההמרה. כלומר המסלול הרגיל מסמן שהמקור אינו עונה,
ואז מתעלם מהסימון של עצמו בבקשה הבאה — ומשלם שוב 15 שניות המתנה, ושוב,
בכל בקשה.

זה בדיוק אותו סוג פגם שכבר תוקן כאן פעמיים: מחצית מנגנון. הסימון בלי
הקריאה אינו "חצי תיקון", הוא קוד מת.

## ולמה בכלל 15 שניות על playlist

    _hls_relay_client = httpx.AsyncClient(timeout=15, ...)

התקרה הזאת נכונה למקטע וידאו — 3.6MB שנמשכים שניות. ‎playlist‎ הוא
מאות בתים, והוא מגיע ברבע שנייה או שלא מגיע. מקור שלא ענה תוך שש
שניות על מאות בתים לא יענה גם בחמש עשרה, והנגן בצד השני ממתין כל הזמן
הזה בלי לדעת כלום.

ולכן: **התקרה לפי סוג הבקשה ולא לפי הלקוח.** מקטע נשאר על 15,
‎playlist‎ יורד לשש. זו שאלה של מה מגיש את הבקשה, ולא של הרשת.

## מה משתנה

* המסלול הרגיל בודק את הסימון לפני שהוא פותח חיבור. ערוץ שסומן מקבל
  502 במיליוניות שנייה במקום 15 שניות — ל-45 שניות, ואז נבדק שוב.
* בקשת ‎playlist‎ מקבלת תקרה של שש שניות במקום חמש עשרה.
* הסימון חל על ‎playlist‎ בלבד. מקטע שנכשל אינו מסמן את הערוץ כמת:
  מקטע בודד נופל גם בשידור בריא, וסימון על זה היה מפיל ערוץ שעובד.

## מה זה לא מתקן

הספק של ניקולודיון ממשיך לא לענות. מה שמשתנה הוא שהצופה יֵדע את זה
בתוך שש שניות פעם אחת, ובאופן מיידי אחר כך — במקום להמתין שוב ושוב.

    python3 fix_relay_dead_check.py --check
    python3 fix_relay_dead_check.py
    python3 fix_relay_dead_check.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_relay_dead_check"
MARK = "fix_relay_dead_check"

# ── 1. תקרה נפרדת ל-playlist ───────────────────────────────────────────────
A_CONST = '''HLS_FIX_DEADLINE = float(os.environ.get("HLS_FIX_DEADLINE", "14"))
'''

N_CONST = '''HLS_FIX_DEADLINE = float(os.environ.get("HLS_FIX_DEADLINE", "14"))
# [fix_relay_dead_check] תקרה לבקשת playlist בלבד. הלקוח מוגדר ל-15
# שניות, וזה נכון למקטע וידאו של 3.6MB — אבל playlist הוא מאות בתים
# שמגיעים ברבע שנייה או שלא מגיעים. נמדד: מקור שאינו עונה גרר 15 שניות
# המתנה בכל בקשה, ובראשונה 50.
HLS_PLAYLIST_TIMEOUT = float(os.environ.get("HLS_PLAYLIST_TIMEOUT", "6"))
'''

# ── 2. המסלול הרגיל קורא את הסימון שהוא עצמו כותב ─────────────────────────
A_CHECK = '''    if _is_hls_manifest(path):
        # [fix_live_autofix] ערוץ בלי IDR מופנה אל _fix, והקישור שבקטלוג
        # נשאר כפי שהוא — הנגן עוקב אחרי ההפניה בעצמו.
'''

N_CHECK = '''    if _is_hls_manifest(path):
        # [fix_relay_dead_check] הסימון נקרא, ולא רק נכתב. הפאץ' הקודם
        # הוסיף כאן ‎_hls_mark_dead‎ אבל את הבדיקה רק במסלול ההמרה, ולכן
        # המסלול הזה סימן שהמקור אינו עונה והתעלם מכך בבקשה הבאה —
        # ושילם שוב 15 שניות, בכל בקשה. נמדד: 502 אחרי 15.4 שניות.
        #
        # רק על playlist: מקטע בודד נופל גם בשידור בריא, וסימון על זה
        # היה מפיל ערוץ שעובד.
        _dead = _hls_dead_reason(_hls_fix_key(host, path))
        if _dead:
            raise HTTPException(502, f"hls_relay: {_dead}")
        # [fix_live_autofix] ערוץ בלי IDR מופנה אל _fix, והקישור שבקטלוג
        # נשאר כפי שהוא — הנגן עוקב אחרי ההפניה בעצמו.
'''

# ── 3. הבקשה עצמה עם התקרה הקצרה ──────────────────────────────────────────
A_FETCH = '''                try:
                    resp = await _hls_relay_client.get(
                        upstream_url, headers=HLS_RELAY_UPSTREAM_HEADERS)
                except httpx.HTTPError as e:
'''

N_FETCH = '''                try:
                    resp = await _hls_relay_client.get(
                        upstream_url, headers=HLS_RELAY_UPSTREAM_HEADERS,
                        timeout=HLS_PLAYLIST_TIMEOUT)
                except httpx.HTTPError as e:
'''

EDITS = [
    ("תקרה ל-playlist", A_CONST, N_CONST),
    ("קריאת הסימון במסלול הרגיל", A_CHECK, N_CHECK),
    ("התקרה הקצרה בבקשה", A_FETCH, N_FETCH),
]


def fn_source(src: str, name: str) -> str:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"לא נמצאה הפונקציה {name}")


def code_only(text: str) -> str:
    out = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
    joined = "\n".join(out)
    parts = joined.split('"""')
    return "".join(parts[::2]) if len(parts) > 2 else joined


def validate(out: str) -> None:
    compile(out, "main.py", "exec")

    # תלות: שני הפאצ'ים הקודמים
    assert "_hls_mark_dead" in out, "חסר _hls_mark_dead — הרץ fix_relay_deadline"
    assert "_hls_manifest_entries" in out, "חסר — הרץ fix_empty_manifest"

    plain = code_only(fn_source(out, "hls_relay"))
    fixed = code_only(fn_source(out, "hls_relay_fixed"))

    # הבדיקה קיימת בשני המסלולים, ולא רק באחד — זה הבאג עצמו
    assert "_hls_dead_reason" in plain, "המסלול הרגיל עדיין לא קורא את הסימון"
    assert "_hls_dead_reason" in fixed, "מסלול ההמרה איבד את הבדיקה"
    assert out.count("_hls_dead_reason(") >= 3, \
        "הבדיקה אינה מופיעה בשני המסלולים (מלבד ההגדרה)"

    # התקרה הקצרה חלה על playlist בלבד
    assert "timeout=HLS_PLAYLIST_TIMEOUT" in plain, "התקרה לא הועברה"
    assert plain.count("timeout=HLS_PLAYLIST_TIMEOUT") == 1, \
        "התקרה הקצרה הוחלה על יותר מבקשת ה-playlist"

    # הבדיקה יושבת בתוך ‎if _is_hls_manifest(path):‎ ולא לפניו, אחרת
    # מקטע וידאו שנופל היה מפיל את כל הערוץ
    i_if = plain.index("_is_hls_manifest(path)")
    i_chk = plain.index("_hls_dead_reason")
    assert i_chk > i_if, "הבדיקה מחוץ לענף ה-playlist — מקטע היה מסמן ערוץ"

    # והיא לפני פתיחת החיבור, אחרת אין חיסכון
    i_get = plain.index("_hls_relay_client.get")
    assert i_chk < i_get, "הבדיקה אחרי פתיחת החיבור — לא חוסכת כלום"

    # ההגדרה נקראת בפועל
    ns = {"os": os}
    exec("HLS_PLAYLIST_TIMEOUT = float(os.environ.get("
         "'HLS_PLAYLIST_TIMEOUT', '6'))", ns)
    assert ns["HLS_PLAYLIST_TIMEOUT"] == 6.0, "ברירת המחדל אינה 6"


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
    print("ערוץ שהמקור שלו אינו עונה: שש שניות פעם אחת, ואז מיידי")
    print("במשך 45 שניות. במקום 15 שניות בכל בקשה.")


if __name__ == "__main__":
    main()
