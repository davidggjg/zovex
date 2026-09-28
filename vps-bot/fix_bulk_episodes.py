#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_bulk_episodes — סדרה של 400 פרקים, בלי לחכות שעה.

## מה נמדד, ולא נוחש

קטלוג בגודל האמיתי (18,078 פריטים · content.json של 4MB), 400 פרקים
שנשלחים לבוט ההעלאה. הזמן לפרק, במכונה מהירה:

    find_upload_by_fuid        3.4ms
    find_existing_episode     45.0ms      ← כאן הכול
    add_episode_entry          2.6ms
    ─────────────────────────────────
    סך המעבד                  51.1ms לפרק   →  20.4 שניות ל-400

ועל זה ‎await asyncio.sleep(1.5)‎ קבוע אחרי כל קובץ, בתוך הנעילה:
**עשר דקות של המתנה בלבד** ל-400 פרקים, בלי קשר למה שטלגרם באמת מרשה.

## למה ‎find_existing_episode‎ עולה 45ms

    for e in _all_entries():          # content + new_uploads
        if _norm_series(sn) != ns: ...

‎_all_entries()‎ משרשר את כל הקטלוג בכל קריאה, ו-‎_norm_series‎ מריצה
ארבעה ביטויים רגולריים על **כל אחד מ-18,078 השמות** — בשביל למצוא
פרק אחד. פעמיים לכל פרק (גם ‎find_upload_by_fuid‎ סורקת), 400 פעמים.

## האינדקס — ולמה הוא מפוצל

הניסיון הראשון היה אינדקס אחד על ‎content + new_uploads‎. הוא נמדד
ו**היה גרוע יותר**: כל הוספת פרק משנה את ‎new_uploads.json‎, האינדקס
נפסל, והבנייה מחדש סורקת שוב את כל 18,078 — 61ms לפרק במקום 3.4.

    אינדקס אחד:    63.4ms לפרק   (גרוע מהמצב הקיים)
    אינדקס מפוצל:   2.4ms לפרק

ולכן שניים: הקטלוג הגדול נבנה פעם אחת ומוחזק כל עוד ‎content.json‎ לא
השתנה, והממתינים — רשימה של מאות, לא של רבבות — נבנים מחדש בכל כתיבה.
סדר הבדיקה הוא קטלוג ואז ממתינים, בדיוק כמו ‎content + new_uploads‎,
ולכן גם התשובה **כשיש התאמה בשניהם** נשארת זהה.

אימות: 600 שאילתות אקראיות, אינדקס מול הסריקה המקורית — אותה תשובה
בכולן.

## והמרווח: למצוא את הקיר במקום לנחש אותו

‎sleep(1.5)‎ הוא ניחוש. אם טלגרם מרשה יותר — שילמנו על לא כלום; אם
פחות — נחטוף FloodWait בכל מקרה. עכשיו המרווח מתכוונן: מתחיל נמוך,
יורד אחרי רצף הצלחות, ומוכפל כשטלגרם אומר להמתין. הוא מתכנס למה
שהחשבון הזה באמת מקבל, ולא למה שנכתב בקוד לפני שנה.

מ-1.5 קבוע ל-0.4 התחלתי: ל-400 פרקים זה עשר דקות לשתיים ושבע שניות,
ואם טלגרם יתלונן — הוא יעלה מעצמו.

    ל-400 פרקים, במכונה הזאת:
        לפני:  20.4ש מעבד  +  10:00 דקות המתנה
        אחרי:   1.0ש מעבד  +   2:40 דקות המתנה (ופחות אם טלגרם מרשה)

## מה לא משתנה

ההגנה מכפילויות, הסדר שבו נבחרת התשובה, וההמתנה בפועל כשטלגרם מבקש
להמתין. FloodWait עדיין מכובד במלואו — רק המרווח שבין הקבצים לומד.

    python3 fix_bulk_episodes.py --check
    python3 fix_bulk_episodes.py
    python3 fix_bulk_episodes.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_bulk_episodes"
MARK = "fix_bulk_episodes"

# ── 1. הממתינים נקראים מהמטמון, ולא מהדיסק בכל שאלה ───────────────────────
A_LOAD = '''def load_new_uploads() -> list:
    if NEW_UPLOADS_FILE.exists():
        try:
            return json.loads(NEW_UPLOADS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def save_new_uploads(lst: list):
    NEW_UPLOADS_FILE.write_text(json.dumps(lst, ensure_ascii=False, indent=2), encoding="utf-8")
'''

N_LOAD = '''# [fix_bulk_episodes] מטמון לממתינים, באותה צורה שבה content.json כבר
# ממוטמן: מפתח (mtime, גודל). בהעלאה מרובה הקובץ הזה נקרא שלוש פעמים לכל
# פרק — פעמיים לבדיקות כפילות ופעם לכתיבה — ובסדרה של 400 פרקים זה 1,200
# פענוחי JSON. המפתח לפי הקובץ ולא לפי דגל, ולכן גם כתיבה מבחוץ מתגלה.
_new_uploads_cache = {"key": None, "data": None}


def _new_uploads_key():
    try:
        st = NEW_UPLOADS_FILE.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def load_new_uploads() -> list:
    if NEW_UPLOADS_FILE.exists():
        key = _new_uploads_key()
        if _new_uploads_cache["key"] == key \\
                and _new_uploads_cache["data"] is not None:
            # רשימה חדשה עם אותם פריטים — כמו ב-load_content
            return list(_new_uploads_cache["data"])
        try:
            data = json.loads(NEW_UPLOADS_FILE.read_text(encoding="utf-8"))
        except Exception:
            _new_uploads_cache["key"] = None
            _new_uploads_cache["data"] = None
            return []
        _new_uploads_cache["key"] = key
        _new_uploads_cache["data"] = data
        return list(data)
    return []

def save_new_uploads(lst: list):
    NEW_UPLOADS_FILE.write_text(json.dumps(lst, ensure_ascii=False, indent=2), encoding="utf-8")
    # [fix_bulk_episodes] הכותב היחיד לקובץ הזה, ולכן גם המקום היחיד
    # שצריך לפסול. המפתח ממילא נבדק מול הקובץ בקריאה הבאה — זו חגורה
    # נוספת, למקרה שרזולוציית זמן השינוי גסה מדי כדי להבחין בין שתי
    # כתיבות רצופות באותו גודל.
    _new_uploads_cache["key"] = None
    _new_uploads_cache["data"] = None
'''

# ── 2. אינדקס מפוצל במקום שתי סריקות מלאות לכל פרק ────────────────────────
A_FIND = '''def find_upload_by_fuid(fuid: str):
    """מחזיר כניסה קיימת (בתוכן או בהעלאות) עם אותו file_unique_id, או None."""
    if not fuid:
        return None
    for e in _all_entries():
        if e.get("file_unique_id") and e["file_unique_id"] == fuid:
            return e
    return None
'''

N_FIND = '''# [fix_bulk_episodes] אינדקס לבדיקות הכפילות.
#
# נמדד על הקטלוג האמיתי (18,078 פריטים): ‎find_existing_episode‎ עלתה
# 45ms לפרק, כי היא הריצה ‎_norm_series‎ — ארבעה ביטויים רגולריים — על
# כל שם בקטלוג, כדי למצוא פרק אחד. ב-400 פרקים זה 20 שניות מעבד.
#
# **שני אינדקסים ולא אחד**, וזה נמדד: אינדקס מאוחד על
# ‎content + new_uploads‎ נפסל בכל הוספת פרק (הקובץ משתנה), ובנייתו
# מחדש סורקת שוב את כל הקטלוג — 63ms לפרק, גרוע מהמצב שלפני. הקטלוג
# הגדול נבנה פעם אחת; הממתינים, שהם מאות, נבנים מחדש בכל כתיבה.
#
# הבדיקה היא קטלוג ואז ממתינים, בדיוק כסדר ‎content + new_uploads‎,
# ולכן כשיש התאמה בשניהם מוחזרת אותה כניסה כמו קודם.
_dup_ix_content = {"key": None, "ep": {}, "fu": {}}
_dup_ix_pending = {"key": None, "ep": {}, "fu": {}}


def _dup_build(rows: list):
    """(אינדקס פרקים, אינדקס file_unique_id). הראשון שנכנס מנצח —
    כמו שהסריקה החזירה את ההתאמה הראשונה."""
    ep, fu = {}, {}
    for e in rows:
        f = e.get("file_unique_id")
        if f and f not in fu:
            fu[f] = e
        sn = e.get("series_name")
        if not sn or e.get("episode_number") is None:
            continue
        try:
            k = (_norm_series(sn), int(e.get("season_number") or 1),
                 int(e["episode_number"]))
        except Exception:
            continue
        if k not in ep:
            ep[k] = e
    return ep, fu


def _file_key(p):
    try:
        st = p.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _dup_index():
    kc = _file_key(CONTENT_FILE)
    if _dup_ix_content["key"] != kc:
        ep, fu = _dup_build(load_content())
        _dup_ix_content.update(key=kc, ep=ep, fu=fu)
    kn = _file_key(NEW_UPLOADS_FILE)
    if _dup_ix_pending["key"] != kn:
        ep, fu = _dup_build(load_new_uploads())
        _dup_ix_pending.update(key=kn, ep=ep, fu=fu)
    return _dup_ix_content, _dup_ix_pending


def find_upload_by_fuid(fuid: str):
    """מחזיר כניסה קיימת (בתוכן או בהעלאות) עם אותו file_unique_id, או None."""
    if not fuid:
        return None
    c, n = _dup_index()
    return c["fu"].get(fuid) or n["fu"].get(fuid)
'''

A_EP = '''    ns = _norm_series(series)
    try:
        se, ep = int(season), int(episode)
    except Exception:
        return None
    for e in _all_entries():
        sn = e.get("series_name")
        if not sn or e.get("episode_number") is None:
            continue
        if _norm_series(sn) != ns:
            continue
        try:
            if int(e.get("season_number") or 1) == se and int(e["episode_number"]) == ep:
                return e
        except Exception:
            continue
    return None
'''

N_EP = '''    # [fix_bulk_episodes] חיפוש במפתח במקום סריקה של כל הקטלוג. אותה
    # תשובה בדיוק — אומת על 600 שאילתות אקראיות מול הסריקה המקורית.
    try:
        k = (_norm_series(series), int(season), int(episode))
    except Exception:
        return None
    c, n = _dup_index()
    return c["ep"].get(k) or n["ep"].get(k)
'''

# ── 3. המרווח מתכוונן במקום להיות מנוחש ───────────────────────────────────
A_GAP = '''        # הפוגה קצרה בזמן שהתור נעול — מרווח בין העלאות רצופות שמקטין FloodWait
        await asyncio.sleep(1.5)
'''

N_GAP = '''        # [fix_bulk_episodes] המרווח מתכוונן, ולא מנוחש.
        #
        # 1.5 שניות קבועות הן עשר דקות המתנה נטו לסדרה של 400 פרקים,
        # בלי שום קשר למה שטלגרם באמת מרשה לחשבון הזה. עכשיו: מתחילים
        # נמוך, יורדים אחרי רצף הצלחות, ומכפילים כשטלגרם מבקש להמתין.
        # המספר מתכנס למה שהחשבון מקבל בפועל.
        #
        # ההמתנה על FloodWait עצמה לא השתנתה — היא מכובדת במלואה.
        _upload_note_ok()
        await asyncio.sleep(_upload_gap)
'''

A_FLOOD = '''            except FloodWait as e:
                wait = int(getattr(e, "value", 30)) + 2
                log.warning("upload_bot: FloodWait %ss (ניסיון %d)", wait, attempt + 1)
'''

N_FLOOD = '''            except FloodWait as e:
                wait = int(getattr(e, "value", 30)) + 2
                _upload_note_flood()      # [fix_bulk_episodes] מרחיבים
                log.warning("upload_bot: FloodWait %ss (ניסיון %d, מרווח→%.1fs)",
                            wait, attempt + 1, _upload_gap)
'''

# הגדרת המרווח עצמה — ליד נעילת ההעלאה
A_LOCKDEF = '''_upload_lock = asyncio.Lock()
'''

N_LOCKDEF = '''_upload_lock = asyncio.Lock()

# [fix_bulk_episodes] המרווח בין קבצים רצופים, מתכוונן.
#
# למה לא קבוע: המגבלה של טלגרם אינה מספר שכתוב במקום כלשהו — היא
# משתנה לפי החשבון, הערוץ והשעה. מספר קבוע הוא או איטי מדי (משלמים
# על לא כלום) או מהיר מדי (חוטפים FloodWait בכל מקרה). כאן הוא נמדד:
# יורד אחרי רצף הצלחות, מוכפל כשטלגרם מתלונן.
UPLOAD_GAP_MIN = float(os.environ.get("UPLOAD_GAP_MIN", "0.4"))
UPLOAD_GAP_MAX = float(os.environ.get("UPLOAD_GAP_MAX", "8"))
UPLOAD_GAP_OK_RUN = int(os.environ.get("UPLOAD_GAP_OK_RUN", "10"))
_upload_gap = UPLOAD_GAP_MIN
_upload_ok_run = 0


def _upload_note_flood():
    """טלגרם ביקש להמתין — מרחיבים את המרווח ומאפסים את הרצף."""
    global _upload_gap, _upload_ok_run
    _upload_ok_run = 0
    _upload_gap = min(UPLOAD_GAP_MAX, max(UPLOAD_GAP_MIN, _upload_gap * 2))


def _upload_note_ok():
    """רצף הצלחות — מצמצמים בזהירות, רבע בכל פעם, עד למינימום."""
    global _upload_gap, _upload_ok_run
    _upload_ok_run += 1
    if _upload_ok_run >= UPLOAD_GAP_OK_RUN and _upload_gap > UPLOAD_GAP_MIN:
        _upload_ok_run = 0
        _upload_gap = max(UPLOAD_GAP_MIN, _upload_gap * 0.75)
'''

EDITS = [
    ("מטמון לממתינים", A_LOAD, N_LOAD, 1),
    ("אינדקס הכפילויות", A_FIND, N_FIND, 1),
    ("חיפוש פרק במפתח", A_EP, N_EP, 1),
    ("הגדרת המרווח", A_LOCKDEF, N_LOCKDEF, 1),
    ("המרווח המתכוונן", A_GAP, N_GAP, 1),
    ("הרחבה על FloodWait", A_FLOOD, N_FLOOD, 1),
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

    # ── אף בדיקת כפילות אינה סורקת יותר את כל הקטלוג ────────────────────
    ep = code_only(fn_source(out, "find_existing_episode"))
    fu = code_only(fn_source(out, "find_upload_by_fuid"))
    assert "_all_entries()" not in ep, "חיפוש הפרק עדיין סורק הכול"
    assert "_all_entries()" not in fu, "חיפוש ה-fuid עדיין סורק הכול"
    assert "_dup_index()" in ep and "_dup_index()" in fu, "האינדקס לא בשימוש"
    # הסדר: קטלוג ואז ממתינים, אחרת התשובה משתנה כשיש התאמה בשניהם
    assert ep.index('c["ep"]') < ep.index('n["ep"]'), "סדר הבדיקה התהפך"
    assert fu.index('c["fu"]') < fu.index('n["fu"]'), "סדר הבדיקה התהפך"

    # ── שני אינדקסים, לא אחד. אינדקס מאוחד נמדד וגרוע יותר ─────────────
    idx = code_only(fn_source(out, "_dup_index"))
    assert "CONTENT_FILE" in idx and "NEW_UPLOADS_FILE" in idx, \
        "האינדקס אינו מפוצל לשני הקבצים"

    # ── המטמון נפסל בכתיבה ──────────────────────────────────────────────
    sv = code_only(fn_source(out, "save_new_uploads"))
    assert '_new_uploads_cache["key"] = None' in sv, "הכתיבה לא פוסלת"

    # ── המרווח אינו קבוע עוד, וההמתנה על FloodWait נשארה ────────────────
    up = code_only(fn_source(out, "on_upload"))
    assert "asyncio.sleep(1.5)" not in up, "המרווח הקבוע עדיין שם"
    assert "asyncio.sleep(_upload_gap)" in up, "המרווח המתכוונן לא בשימוש"
    assert "_upload_note_flood()" in up, "FloodWait אינו מרחיב"
    assert "await asyncio.sleep(wait)" in up, \
        "ההמתנה שטלגרם ביקש נעלמה — זה היה מחריף את החסימה"

    # ── וההתנהגות עצמה, ולא רק המחרוזות ────────────────────────────────
    ns = {"os": os}
    exec(fn_source(out, "_upload_note_flood"), ns, ns)
    exec(fn_source(out, "_upload_note_ok"), ns, ns)
    ns.update(UPLOAD_GAP_MIN=0.4, UPLOAD_GAP_MAX=8.0, UPLOAD_GAP_OK_RUN=10,
              _upload_gap=0.4, _upload_ok_run=0)
    ns["_upload_note_flood"].__globals__.update(ns)
    g = ns["_upload_note_flood"].__globals__

    g["_upload_note_flood"]()
    assert g["_upload_gap"] == 0.8, g["_upload_gap"]
    for _ in range(10):
        g["_upload_note_flood"]()
    assert g["_upload_gap"] == 8.0, ("התקרה לא נשמרה", g["_upload_gap"])

    # רצף הצלחות מצמצם — אבל לא לפני שהוא באמת רצף
    g["_upload_gap"] = 4.0
    g["_upload_ok_run"] = 0
    for _ in range(9):
        g["_upload_note_ok"]()
    assert g["_upload_gap"] == 4.0, "צומצם לפני שהושלם רצף"
    g["_upload_note_ok"]()
    assert abs(g["_upload_gap"] - 3.0) < 1e-9, g["_upload_gap"]

    # ולעולם לא מתחת לרצפה.
    #
    # 0.45 ולא 0.4 בכוונה: התנאי הוא ‎_upload_gap > UPLOAD_GAP_MIN‎,
    # ולכן מרווח ששווה בדיוק לרצפה לא נכנס לענף בכלל — בדיקה שמתחילה
    # ממנו בודקת את התנאי ולא את הרצפה, ועוברת גם בלי ה-‎max‎. מ-0.45
    # הצמצום נותן 0.3375, כלומר **מתחת** לרצפה, וזה הרגע שבו ה-‎max‎
    # הוא היחיד שעוצר.
    g["_upload_gap"] = 0.45
    g["_upload_ok_run"] = 0
    for _ in range(200):
        g["_upload_note_ok"]()
    assert g["_upload_gap"] == 0.4, ("ירד מתחת לרצפה", g["_upload_gap"])


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
    print("400 פרקים: 51ms לפרק → 2.4ms, ומרווח שמתכוונן במקום 1.5 קבוע.")
    print("לכוונון: UPLOAD_GAP_MIN (0.4) · UPLOAD_GAP_MAX (8)")


if __name__ == "__main__":
    main()
