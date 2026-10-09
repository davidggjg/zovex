#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""add_history_delete — מחיקה אמיתית מהיסטוריה ומ"המשך צפייה".

## הצורך (מחבילת ה-Redesign)

המשתמש צריך להסיר פריט בודד מ"המשך צפייה" ומהיסטוריית הצפייה, וגם
"נקה היסטוריה". המפרט דורש מפורשות: המחיקה חייבת לעדכן את **מקור
הנתונים האמיתי** ולשרוד רענון — לא להסתיר כרטיס ב-UI.

## מה חסר בשרת

    /api/favorites   GET POST DELETE   ← מחיקה כבר קיימת
    /api/history     GET POST          ← אין מחיקה
    /api/progress    GET POST          ← אין מחיקה   ("המשך צפייה")

לכן אי אפשר לממש את הדרישה בצד הלקוח בלבד. הפאצ' הזה מוסיף:

    DELETE /api/history/{media_id}     הסרת פריט אחד מההיסטוריה
    DELETE /api/history                "נקה היסטוריה" (אישור בלקוח)
    DELETE /api/progress/{media_id}    הסרה מ"המשך צפייה"

## אימות — לא ברירת מחדל, חובה

שלושתם מוחקים נתונים לפי ‎x-user-id‎, וזו בדיוק הפעולה שאסור
שתהיה פתוחה: בלי אימות, מי שיודע ‎user_id‎ מוחק היסטוריה של אחר.
לכן הם עוברים דרך ‎_zx_require‎ — אותו שומר שנבנה ב-
‎add_identity_auth.py‎, ולכן הפאצ' הזה דורש שהוא כבר מוחל.

ההחלה מדורגת נשמרת: משתמש שאינו ברשימת המאומתים עובד כרגיל, ולכן
אפליקציה ישנה עדיין יכולה למחוק — ההגנה נסגרת כשהלקוח מתעדכן.

    python3 add_history_delete.py --check
    python3 add_history_delete.py
    python3 add_history_delete.py --revert

אחרי ההחלה:  systemctl restart zovex-bot
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_history_delete"
MARK = "add_history_delete"

# עוגן: מיד אחרי מטפל מחיקת המועדף הקיים, כדי שהחדשים יושבים לצדו
# ובאותו סגנון בדיוק.
A_ANCHOR = '''@api.delete("/api/favorites/{media_id}")
async def remove_favorite(media_id: str,
                          x_user_id: str = Header(..., description="Google User ID")):
    db = load_json(FAVORITES_FILE)
    lst = db.get(x_user_id) or []
    n = len(lst)
    db[x_user_id] = [f for f in lst if f.get("media_id") != media_id]
    if len(db[x_user_id]) != n:
        save_json(FAVORITES_FILE, db, "favorites.json")
    return {"ok": True, "removed": n - len(db[x_user_id])}
'''

N_ANCHOR = A_ANCHOR + '''

# ── [add_history_delete] מחיקה מהיסטוריה ומ"המשך צפייה" ─────────────────
#
# המחיקה חייבת לעדכן את הקובץ עצמו (history.json / progress.json),
# אחרת הפריט חוזר ברענון הבא. שלושתם עוברים דרך _zx_require: מחיקת
# נתונים של משתמש היא בדיוק מה שאסור לפתוח לפי מזהה בלבד.

@api.delete("/api/history/{media_id}")
async def remove_history(media_id: str,
                         x_user_id: str = Header(..., description="Google User ID"),
                         x_zovex_auth: str = Header("", alias="x-zovex-auth")):
    _zx_require(x_zovex_auth, x_user_id)
    db = load_json(HISTORY_FILE)
    lst = db.get(x_user_id) or []
    n = len(lst)
    db[x_user_id] = [h for h in lst if h.get("media_id") != media_id]
    if len(db[x_user_id]) != n:
        save_json(HISTORY_FILE, db, "history.json")
    return {"ok": True, "removed": n - len(db[x_user_id])}


@api.delete("/api/history")
async def clear_history(x_user_id: str = Header(..., description="Google User ID"),
                        x_zovex_auth: str = Header("", alias="x-zovex-auth")):
    """נקה היסטוריה. האישור הוא בצד הלקוח — כאן מוחקים."""
    _zx_require(x_zovex_auth, x_user_id)
    db = load_json(HISTORY_FILE)
    n = len(db.get(x_user_id) or [])
    if n:
        db[x_user_id] = []
        save_json(HISTORY_FILE, db, "history.json")
    return {"ok": True, "removed": n}


@api.delete("/api/progress/{media_id}")
async def remove_progress(media_id: str,
                          x_user_id: str = Header(..., description="Google User ID"),
                          x_zovex_auth: str = Header("", alias="x-zovex-auth")):
    """הסרה מ"המשך צפייה". progress.json הוא {user: {media_id: {...}}}."""
    _zx_require(x_zovex_auth, x_user_id)
    db = load_json(PROGRESS_FILE)
    u = db.get(x_user_id) or {}
    existed = media_id in u
    if existed:
        del u[media_id]
        db[x_user_id] = u
        save_json(PROGRESS_FILE, db, "progress.json")
    return {"ok": True, "removed": 1 if existed else 0}
'''

EDITS = [("נתיבי מחיקה", A_ANCHOR, N_ANCHOR, 1)]


def fn_source(src: str, name: str) -> str:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError("לא נמצאה הפונקציה %s" % name)


def validate(out: str) -> None:
    compile(out, "main.py", "exec")

    assert "_zx_require(" in out, \
        "add_identity_auth אינו מוחל — החל אותו קודם (המחיקה חייבת שומר)"

    # שלושתם עוברים דרך השומר, לפני כל נגיעה בנתונים
    for fn in ("remove_history", "clear_history", "remove_progress"):
        body = fn_source(out, fn)
        assert "_zx_require(x_zovex_auth, x_user_id)" in body, \
            "%s אינו מאומת" % fn
        assert body.index("_zx_require") < body.index("load_json"), \
            "%s קורא נתונים לפני האימות" % fn
        assert "save_json" in body, "%s אינו כותב לדיסק" % fn

    # ── והמטפלים מורצים באמת, מול אחסון מזויף ──────────────────────────
    import asyncio

    saved = {}

    def fake_load(path):
        return {k: (v.copy() if isinstance(v, (dict, list)) else v)
                for k, v in saved.get(path, {}).items()}

    def fake_save(path, data, name):
        saved[path] = {k: (v.copy() if isinstance(v, (dict, list)) else v)
                       for k, v in data.items()}

    ns = {"load_json": fake_load, "save_json": fake_save,
          "HISTORY_FILE": "H", "PROGRESS_FILE": "P",
          "Header": lambda *a, **k: "", "_zx_require": lambda *a: None}
    for fn in ("remove_history", "clear_history", "remove_progress"):
        exec(fn_source(out, fn), ns)
    rh, ch, rp = ns["remove_history"], ns["clear_history"], ns["remove_progress"]

    def run(c):
        return asyncio.get_event_loop().run_until_complete(c)

    # היסטוריה: מוחקים אחד, השאר נשאר, והמחיקה שורדת (נכתבה לדיסק)
    saved["H"] = {"u1": [{"media_id": "a"}, {"media_id": "b"}]}
    r = run(rh("a", "u1", ""))
    assert r["removed"] == 1, "לא נמחק פריט ההיסטוריה"
    assert fake_load("H")["u1"] == [{"media_id": "b"}], "המחיקה לא נכתבה לדיסק"
    # מזהה שלא קיים אינו מוחק כלום ואינו קורס
    assert run(rh("zzz", "u1", ""))["removed"] == 0, "מזהה לא קיים מחק משהו"
    # משתמש אחר אינו מושפע
    saved["H"] = {"u1": [{"media_id": "a"}], "u2": [{"media_id": "a"}]}
    run(rh("a", "u1", ""))
    assert fake_load("H")["u2"] == [{"media_id": "a"}], "מחיקה דלפה למשתמש אחר"

    # נקה היסטוריה: מרוקן רק את המשתמש הזה
    saved["H"] = {"u1": [{"media_id": "a"}, {"media_id": "b"}],
                  "u2": [{"media_id": "c"}]}
    r = run(ch("u1", ""))
    assert r["removed"] == 2 and fake_load("H")["u1"] == [], "נקה היסטוריה נכשל"
    assert fake_load("H")["u2"] == [{"media_id": "c"}], "נקה מחק משתמש אחר"

    # המשך צפייה: מסירים מזהה בודד מתוך מילון
    saved["P"] = {"u1": {"a": {"position": 5}, "b": {"position": 9}}}
    r = run(rp("a", "u1", ""))
    assert r["removed"] == 1 and "a" not in fake_load("P")["u1"], "לא הוסר מ-progress"
    assert "b" in fake_load("P")["u1"], "הוסר הפריט הלא נכון מ-progress"
    assert run(rp("zzz", "u1", ""))["removed"] == 0, "progress: מזהה לא קיים"

    # ── ומוטציה: בלי כתיבה לדיסק, המחיקה 'מצליחה' אך לא שורדת ──────────
    # (נבדק דרך הטענה save_json לעיל + ההשוואה fake_load אחרי)


def main() -> None:
    if not os.path.exists(PATH):
        sys.exit("אין קובץ ב-%s (אפשר MAIN_PY=...)" % PATH)
    with open(PATH, encoding="utf-8") as fh:
        src = fh.read()

    if "--revert" in sys.argv:
        if not os.path.exists(BAK):
            sys.exit("אין גיבוי ב-%s" % BAK)
        shutil.copy2(BAK, PATH)
        print("✓ שוחזר מ-%s" % BAK)
        return

    if MARK in src:
        print("כבר מותקן.")
        return

    out = src
    for label, a, n, want in EDITS:
        got = out.count(a)
        if got != want:
            sys.exit("✗ העוגן '%s' נמצא %d פעמים (צפוי %d) — לא נוגע בכלום."
                     % (label, got, want))
        out = out.replace(a, n)

    validate(out)
    print("✓ כל הבדיקות עברו")
    if "--check" in sys.argv:
        print("--check: שום דבר לא נכתב.")
        return

    shutil.copy2(PATH, BAK)
    with open(PATH, "w", encoding="utf-8") as fh:
        fh.write(out)
    print("✓ הוחל. גיבוי: %s" % BAK)
    print()
    print("systemctl restart zovex-bot")


if __name__ == "__main__":
    main()
