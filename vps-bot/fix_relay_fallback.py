#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_relay_fallback — כשההמרה נופלת, הצופה מקבל את הערוץ ולא שגיאה.

## השאלה שהובילה לזה

"יכול להיות שההמרה היא ששוברת, ואם נשתמש בקישור הישיר זה לא יישבר?"

חצי נכון, ובחצי הזה יש תיקון אמיתי. "הקישור שלנו" הוא שני דברים:

* **המסלול הרגיל** ‎/hls-relay/<host>/<path>‎ — העברה בלבד. אינו נוגע
  במדיה, רק מושך ומוסר הלאה.
* **‎_fix‎** — **ממיר** בפועל, ב-ffmpeg. זו המרה אמיתית, וזה החלק
  ששובר.

והמדידה שכבר תועדה בשרת אומרת בדיוק את זה:

    yes-drama   _fix=502  רגיל=200
    discovery   _fix=502  רגיל=200
    sport-1     _fix=502  רגיל=200
    nick-jr     _fix=502  רגיל=200

אותם ערוצים: המסלול הרגיל מחזיר 200, ההמרה נופלת. כלומר המקור אצל
הספק תקין, וההמרה היא הבעיה — בדיוק כפי שנטען.

## אבל התשובה אינה קישור ישיר

הקוד **כבר** יודע לרדת למסלול הרגיל כשההמרה נופלת:

    else:
        log.error("... נכשל בכל הפרופילים — מפנה למסלול הרגיל")
        return RedirectResponse(f"/hls-relay/{host}/{path}", 302)

שתי הדרכים שהתווספו ב-‎fix_relay_deadline‎ **עוקפות את ההפניה הזאת**:

    if dead:                     raise HTTPException(502, ...)
    if חריגה מהמועד:              raise HTTPException(502, ...)

כלומר דווקא במקרים שקורים בפועל היום, הצופה מקבל שגיאה במקום את
הערוץ. זו רגרסיה שלי, והיא מסבירה למה נראה ש"ההמרה שוברת": ההמרה
נפלה, וגם רשת הביטחון שכבר הייתה שם נעקפה.

## מה משתנה

שתי הדרכים מפנות למסלול הרגיל, כמו הענף שכבר קיים.

והן מסמנות קודם ‎_hls_fix_profile[key] = None‎ ו-‎_hls_fix_failed_at‎,
בדיוק כמו הענף ההוא — כי ‎_hls_autofix_wanted‎ קורא את הסימון הזה, ובלעדיו
המסלול הרגיל היה מפנה בחזרה אל ‎_fix‎ ונוצרת לולאת הפניות.

## מה זה לא פותר

ערוץ open-GOP במסלול הרגיל מגיע לנגן ללא IDR: ב-MSE הוא נתקע על 0:00
בלי שגיאה. זה מתועד ב-‎fix_verify_output‎, וזו הסיבה שההמרה קיימת
מלכתחילה. ולכן ההפניה היא רשת ביטחון ולא פתרון — מה שצריך לתקן הוא
למה ההמרה נופלת, וזה מה שהאסימון וההודעה המפורטת נועדו לגלות.

    python3 fix_relay_fallback.py --check
    python3 fix_relay_fallback.py
    python3 fix_relay_fallback.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_relay_fallback"
MARK = "fix_relay_fallback"

A_DEAD = '''    dead = _hls_dead_reason(key)
    if dead:
        raise HTTPException(502, f"hls_fix: {dead}")
'''

N_DEAD = '''    dead = _hls_dead_reason(key)
    if dead:
        # [fix_relay_fallback] מפנים למסלול הרגיל במקום 502. הענף
        # "נכשלו כל הפרופילים" עושה בדיוק את זה מאז ומתמיד; fix_relay_deadline
        # הוסיף כאן יציאה שעוקפת אותו, ולכן דווקא במקרה שקורה בפועל
        # הצופה קיבל שגיאה במקום ערוץ.
        #
        # הסימון לפני ההפניה, כי _hls_autofix_wanted קורא אותו — בלעדיו
        # המסלול הרגיל היה מפנה בחזרה לכאן ונוצרת לולאת הפניות.
        _hls_fix_profile[key] = None
        _hls_fix_failed_at[key] = time.time()
        log.warning("hls_fix: %s — %s · מפנה למסלול הרגיל", key, dead)
        return RedirectResponse(f"/hls-relay/{host}/{path}", status_code=302)
'''

A_DEADLINE = '''            _hls_mark_dead(key, why)
            log.error("hls_fix: %s — %s", key, why)
            raise HTTPException(502, f"hls_fix: {why}")
'''

N_DEADLINE = '''            _hls_mark_dead(key, why)
            # [fix_relay_fallback] גם כאן: ערוץ ולא שגיאה. הסימון כבר
            # נכתב בשתי השורות שמעל, ולכן ההפניה אינה יוצרת לולאה.
            log.error("hls_fix: %s — %s · מפנה למסלול הרגיל", key, why)
            return RedirectResponse(f"/hls-relay/{host}/{path}",
                                    status_code=302)
'''

EDITS = [
    ("סימון מת → הפניה", A_DEAD, N_DEAD, 1),
    ("חריגת מועד → הפניה", A_DEADLINE, N_DEADLINE, 1),
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

    fixed = code_only(fn_source(out, "hls_relay_fixed"))

    # שלוש הפניות: סימון, חריגת מועד, וכל-הפרופילים-נפלו
    assert fixed.count('RedirectResponse(f"/hls-relay/{host}/{path}"') == 3, \
        "צפויות שלוש הפניות"
    # ונשאר **בדיוק** 502 אחד: זה של בדיקת החיות.
    #
    # שם הפניה לא תעזור ולא תהיה כנה. הבדיקה כבר פנתה למסלול הרגיל
    # בעצמה, עם האסימון שעוקף כל סימון, ולא קיבלה playlist תקין —
    # כלומר המקור אצל הספק אינו עונה. הפניה לאותו מסלול תיתן את אותה
    # תשובה בדיוק, רק אחרי עוד סיבוב. 502 כאן הוא המידע הנכון.
    assert fixed.count('HTTPException(502, f"hls_fix:') == 1, \
        "מספר יציאות ה-502 השתנה — צפויה אחת, של בדיקת החיות"
    assert "_why_dead" in fixed[fixed.index('HTTPException(502, f"hls_fix:') - 400:], \
        "ה-502 שנשאר אינו זה של בדיקת החיות"

    # ── הגנת הלולאה: כל הפניה מסמנת קודם ─────────────────────────────
    # בלי הסימון המסלול הרגיל מפנה בחזרה לכאן, וזו לולאה אינסופית
    for i, at in enumerate(_find_all(fixed, 'RedirectResponse(f"/hls-relay/')):
        before = fixed[:at]
        assert "_hls_fix_profile[key] = None" in before, \
            f"הפניה #{i + 1} בלי סימון — לולאת הפניות"
        assert "_hls_fix_failed_at[key]" in before, \
            f"הפניה #{i + 1} בלי חותמת זמן — הסימון לא יפוג"

    # והשומר עצמו עדיין קורא את הסימון
    wanted = code_only(fn_source(out, "_hls_autofix_wanted"))
    assert "_hls_fix_profile.get(key, 0) is None" in wanted, \
        "השומר מפני לולאה נעלם"

    # ── והמסלול הרגיל עדיין חוסם מסומנים לצופים רגילים ──────────────
    plain = code_only(fn_source(out, "hls_relay"))
    assert "_hls_dead_reason" in plain, "המסלול הרגיל איבד את בדיקת הסימון"

    # ── לולאה מדומה: הפניה עם סימון נעצרת, בלי סימון רצה לנצח ────────
    def walk(mark: bool, hops: int = 10):
        marked = {}
        at = "fix"
        for i in range(hops):
            if at == "fix":
                if mark:
                    marked["k"] = True
                at = "plain"
            else:
                at = "fix" if not marked.get("k") else "done"
        return at

    assert walk(mark=True) == "done", "הסימון אינו עוצר את הלולאה"
    assert walk(mark=False) != "done", "הלולאה לא שוחזרה — הבדיקה חסרת ערך"


def _find_all(hay: str, needle: str):
    i = hay.find(needle)
    while i != -1:
        yield i
        i = hay.find(needle, i + 1)


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
    print("מעכשיו ערוץ שההמרה נופלת עליו מוגש במסלול הרגיל במקום שגיאה.")


if __name__ == "__main__":
    main()
