#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_relay_flap — פסק זמן אחד לא מפיל ערוץ ל-45 שניות.

## מה שנמדד

דגימה של אותו ערוץ דרך הרלֵיי, כל 6 שניות:

    1.  502              ← סימון "מת" משארית קודמת
    2.  000 / 12.1ש      ← פסק זמן מול המקור
    3.  000 / 11.4ש      ← פסק זמן
    4.  200 · 10 מקטעים  (5.8ש)
    5.  200 · 10 מקטעים  (0.86ש)
    6-9. 200 · 10 מקטעים (0.9–1.8ש)

הערוץ אינו שבור. הבקשה הראשונה מול המקור איטית — ולפעמים פגה — וברגע
שהחיבור חם התשובה חוזרת תוך שנייה. זה דפוס של ספק שמתעורר, לא של
ערוץ מת.

## ההגברה

    if isinstance(e, (httpx.TimeoutException, httpx.ConnectError)):
        _hls_mark_dead(key, ...)

פסק זמן **אחד** מסמן את הערוץ, ו-‎HLS_DEAD_TTL‎ הוא 45 שניות. בזמן
הזה כל בקשה — מכל צופה — מקבלת 502 מיידי בלי לנסות בכלל:

    _dead = _hls_dead_reason(key)
    if _dead:
        raise HTTPException(502, ...)

כלומר תקלה חולפת של שנייה אחת הופכת ל-45 שניות שבהן הערוץ מת לכולם.
וזה מסביר "עובד באפליקציה ולא באתר": שני לקוחות שניסו בחלונות שונים
קיבלו תשובות הפוכות על ערוץ שמצבו האמיתי זהה.

הסימון עצמו נכון — בלעדיו כל בקשה משלמת שוב 15 שניות המתנה. מה שלא
נכון הוא **להכריז מת אחרי כישלון אחד**.

## מה משתנה

* פסק זמן בניסיון הראשון ⇒ ניסיון שני מיידי. לולאת הניסיונות כבר
  קיימת (היא נבנתה ל-playlist ריק), והיא פשוט לא כיסתה פסקי זמן.
* הסימון נקבע רק אחרי **שני כישלונות רצופים**. הצלחה מאפסת את המונה.

כלומר קרטוע חולף נבלע בניסיון השני, וספק שבאמת נפל עדיין מסומן
ומפסיק לעלות 15 שניות לכל בקשה — שתי המטרות נשמרות.

    python3 fix_relay_flap.py --check
    python3 fix_relay_flap.py
    python3 fix_relay_flap.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_relay_flap"
MARK = "fix_relay_flap"

# ── 1. מונה כישלונות רצופים ──────────────────────────────────────────────
A_STATE = '''def _hls_mark_dead(key: str, reason: str) -> None:
    """סימון קצר-מועד. ההתאוששות של הספק לא דורשת מאיתנו כלום."""
    _hls_dead[key] = (time.time() + HLS_DEAD_TTL, reason)
'''

N_STATE = '''def _hls_mark_dead(key: str, reason: str) -> None:
    """סימון קצר-מועד. ההתאוששות של הספק לא דורשת מאיתנו כלום."""
    _hls_dead[key] = (time.time() + HLS_DEAD_TTL, reason)


# [fix_relay_flap] כמה פעמים **ברצף** המקור לא ענה לערוץ הזה.
#
# נמדד: ספק שמתעורר נותן פסק זמן של 12 שניות בבקשה הראשונה, ואז עונה
# תוך 0.9 שניות. סימון אחרי כישלון בודד הפך את הקרטוע הזה ל-45 שניות
# שבהן הערוץ מת לכל הצופים.
_hls_fail_streak: dict = {}
HLS_FAIL_BEFORE_DEAD = int(os.environ.get("HLS_FAIL_BEFORE_DEAD", "2"))


def _hls_note_fail(key: str, reason: str) -> bool:
    """רושם כישלון. מחזיר True אם הערוץ סומן כמת עכשיו."""
    n = _hls_fail_streak.get(key, 0) + 1
    _hls_fail_streak[key] = n
    if n >= HLS_FAIL_BEFORE_DEAD:
        _hls_mark_dead(key, reason)
        return True
    return False


def _hls_note_ok(key: str) -> None:
    """הצלחה מאפסת את הרצף. בלי זה כישלונות מפוזרים על פני שעה היו
    מצטברים עד לסימון, והערוץ היה נופל בלי שום תקלה אמיתית."""
    _hls_fail_streak.pop(key, None)
'''

# ── 2. ניסיון שני על פסק זמן, וסימון רק אחרי שניים ──────────────────────
A_CATCH = '''                except httpx.HTTPError as e:
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

N_CATCH = '''                except httpx.HTTPError as e:
                    # [fix_relay_deadline] פסק זמן מסומן לזמן קצר. בלי זה
                    # כל בקשה לאותו ערוץ משלמת שוב 15 שניות המתנה, גם
                    # כשברור שהמקור אינו עונה.
                    #
                    # [fix_relay_flap] אבל לא אחרי כישלון **אחד**. ספק
                    # שמתעורר נותן פסק זמן בבקשה הראשונה ועונה תוך
                    # שנייה בשנייה — ולכן סימון מיידי הפך קרטוע חולף
                    # ל-45 שניות שבהן הערוץ מת לכולם.
                    if isinstance(e, (httpx.TimeoutException,
                                      httpx.ConnectError)):
                        if _try == 0:
                            await asyncio.sleep(0.3)
                            continue          # ניסיון שני, מיד
                        _hls_note_fail(_hls_fix_key(host, path),
                                       f"המקור לא ענה ({type(e).__name__})")
                    raise HTTPException(
                        502, f"hls_relay: upstream fetch failed - {e}")
'''

# ── 3. הצלחה מאפסת ───────────────────────────────────────────────────────
A_OK = '''                n_entries = _hls_manifest_entries(resp.text)
                if n_entries:
                    break
'''

N_OK = '''                n_entries = _hls_manifest_entries(resp.text)
                if n_entries:
                    # [fix_relay_flap] המקור ענה — הרצף מתאפס.
                    _hls_note_ok(_hls_fix_key(host, path))
                    break
'''

EDITS = [
    ("מונה כישלונות", A_STATE, N_STATE, 1),
    ("ניסיון שני על פסק זמן", A_CATCH, N_CATCH, 1),
    ("הצלחה מאפסת", A_OK, N_OK, 1),
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

    body = code_only(fn_source(out, "hls_relay"))
    assert "_hls_note_fail" in body, "הסימון אינו עובר דרך המונה"
    assert "_hls_note_ok" in body, "הצלחה אינה מאפסת"
    assert "_hls_mark_dead" not in body.split("_hls_note_fail")[0][-600:], \
        "נשאר סימון ישיר על פסק זמן"
    assert "continue" in body, "אין ניסיון שני"

    # ── המונה עצמו, מורץ ────────────────────────────────────────────────
    ns = {"time": __import__("time"), "HLS_DEAD_TTL": 45,
          "HLS_FAIL_BEFORE_DEAD": 2, "_hls_dead": {}, "_hls_fail_streak": {}}
    for fn in ("_hls_mark_dead", "_hls_note_fail", "_hls_note_ok"):
        exec(fn_source(out, fn), ns)
    note, ok, dead = ns["_hls_note_fail"], ns["_hls_note_ok"], ns["_hls_dead"]

    assert note("a", "x") is False, "כישלון ראשון סימן — זו בדיוק התקלה"
    assert "a" not in dead, "סומן מוקדם מדי"
    assert note("a", "x") is True, "כישלון שני לא סימן"
    assert "a" in dead, "הסימון לא נכתב"

    # הצלחה מאפסת: שני כישלונות **לא רצופים** אינם מסמנים
    ns["_hls_dead"].clear()
    note("b", "x")
    ok("b")
    assert note("b", "x") is False, "הרצף לא התאפס אחרי הצלחה"
    assert "b" not in ns["_hls_dead"]

    # וערוצים שונים אינם מתערבבים
    ns["_hls_dead"].clear()
    ns["_hls_fail_streak"].clear()
    note("c", "x")
    note("d", "x")
    assert "c" not in ns["_hls_dead"] and "d" not in ns["_hls_dead"], \
        "כישלון בערוץ אחד ספר לאחר"

    # ומוטציה: סף 1 מחזיר את ההתנהגות הישנה, והבדיקה חייבת להבחין
    ns["HLS_FAIL_BEFORE_DEAD"] = 1
    ns["_hls_dead"].clear()
    ns["_hls_fail_streak"].clear()
    assert note("e", "x") is True, "הסף אינו משפיע — הבדיקה חסרת ערך"

    # ── והניסיון השני נמצא בלולאה הנכונה ────────────────────────────────
    assert "for _try in range(2)" in body, "לולאת הניסיונות השתנתה"
    i_loop = body.index("for _try in range(2)")
    i_cont = body.index("continue", i_loop)
    i_raise = body.index("raise HTTPException", i_loop)
    assert i_cont < i_raise, "ה-continue אינו לפני ההרמה"


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
    print("מעכשיו פסק זמן חולף נבלע בניסיון שני, והערוץ מסומן כמת רק")
    print("אחרי שני כישלונות רצופים.")


if __name__ == "__main__":
    main()
