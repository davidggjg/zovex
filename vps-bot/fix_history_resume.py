#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_history_resume — ההיסטוריה מחזירה גם את המיקום, ולא רק את השם.

## הדיווח

"אני רואה את ההיסטוריה, לוחץ, אבל זה מתחיל מההתחלה. באפליקציה זה עובד."

## מה קורה באמת — תחרות, לא באג לוגי

הצד של האתר פותח את הנגן **מיד**, ובמקביל שולח קריאה שנייה:

    setResumeSeconds(0);
    loadProgress(movie.id).then(pos => { if (pos) setResumeSeconds(pos); });

והדילוג המאוחר, כשהתשובה מגיעה, מוגן כך:

    if (v.currentTime < 2) { v.currentTime = startTime; }

כלומר אם ‎/api/progress‎ ענה אחרי יותר משתי שניות של נגינה — הדילוג
**נזרק בשקט**, והסרט ממשיך מההתחלה. השומר הזה נכון בפני עצמו (אחרת
הנגן היה קופץ אחורה למשתמש שכבר צופה), אבל הוא הופך את ההמשכה לתלויה
בזמן תגובה של רשת.

באפליקציה אין את התחרות הזאת, ולכן שם זה עובד — וזה בדיוק ההבדל
שדווח.

## התיקון: להעלים את הקריאה השנייה

‎/api/history‎ מחזיר ‎media_id · title · thumbnail_url · watched_at‎
ואינו מחזיר את המיקום, למרות שהוא יושב באותו שרת בקובץ שכן. לכן האתר
**חייב** קריאה שנייה לכל פתיחה.

מעכשיו כל פריט בהיסטוריה נושא ‎position‎ ו-‎duration‎. הצד של האתר
יכול להעביר אותם בלחיצה עצמה, ואין יותר על מה להתחרות.

## למה כאן ולא רק באתר

כי זה מתקן את **הסיבה**. אפשר היה להרחיב את חלון שתי השניות, אבל זה
רק מרחיב את חלון התחרות ולא מסגור אותה — ברשת איטית הוא יחמיץ שוב, וגם
יסתכן בקפיצה אחורה למי שכבר צופה.

והקריאה הזולה: ‎/api/history‎ מוגש ממילא, וה-join הוא קריאת קובץ אחת
נוספת לאותו משתמש — אותו קובץ ש-‎/api/progress‎ קורא בכל מקרה.

## תאימות לאחור

נוספים שדות, שום שדה אינו משתנה או נעלם. לקוח ישן שאינו מכיר אותם
ממשיך לעבוד בדיוק כמו קודם.

    python3 fix_history_resume.py --check
    python3 fix_history_resume.py
    python3 fix_history_resume.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_history_resume"
MARK = "fix_history_resume"

A_HIST = '''@api.get("/api/history")
async def get_history(
    x_user_id: str = Header(..., description="Google User ID")
):
    db = load_json(HISTORY_FILE)
    return db.get(x_user_id, [])
'''

N_HIST = '''@api.get("/api/history")
async def get_history(
    x_user_id: str = Header(..., description="Google User ID")
):
    # [fix_history_resume] כל פריט נושא גם את המיקום השמור.
    #
    # קודם הנתיב הזה החזיר שם ותמונה בלבד, ולכן האתר היה חייב קריאה
    # שנייה ל-/api/progress לכל פתיחה מההיסטוריה. הקריאה ההיא חזרה
    # **אחרי** שהנגן כבר התחיל לנגן, והדילוג למקום השמור מוגן שם
    # ב-‎currentTime < 2‎ — כלומר ברשת איטית הוא נזרק, והצופה ראה את
    # הסרט מתחיל מההתחלה. באפליקציה אין תחרות כזאת ולכן שם זה עבד.
    #
    # עם המיקום בתוך הפריט אין קריאה שנייה ואין על מה להתחרות.
    db = load_json(HISTORY_FILE)
    rows = db.get(x_user_id, [])
    prog = load_json(PROGRESS_FILE).get(x_user_id, {})
    out = []
    for h in rows:
        if not isinstance(h, dict):
            continue
        p = prog.get(h.get("media_id")) or {}
        try:
            pos = int(float(p.get("position") or 0))
        except (TypeError, ValueError):
            pos = 0
        try:
            dur = int(float(p.get("duration") or 0))
        except (TypeError, ValueError):
            dur = 0
        # שדות נוספים בלבד: שום שדה קיים אינו משתנה, ולכן לקוח ישן
        # ממשיך לעבוד בדיוק כמו קודם.
        out.append({**h, "position": max(0, pos), "duration": max(0, dur)})
    return out
'''

EDITS = [("ההיסטוריה מחזירה מיקום", A_HIST, N_HIST, 1)]


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
    for need in ("PROGRESS_FILE", "HISTORY_FILE", "load_json"):
        assert need in out, f"חסר {need}"

    body = code_only(fn_source(out, "get_history"))
    assert "PROGRESS_FILE" in body, "ההיסטוריה אינה קוראת את המיקומים"
    assert '"position"' in body and '"duration"' in body

    # ── מריצים את הלוגיקה בפועל, על נתונים אמיתיים בצורתם ──────────────
    HIST = {"u1": [
        {"media_id": "m1", "title": "סרט", "thumbnail_url": "", "watched_at": 1},
        {"media_id": "m2", "title": "אין מיקום", "thumbnail_url": ""},
        {"media_id": "m3", "title": "מיקום פגום", "thumbnail_url": ""},
        {"media_id": "m4", "title": "שבר", "thumbnail_url": ""},
        "לא-מילון",
    ]}
    PROG = {"u1": {
        "m1": {"position": 754, "duration": 5400},
        "m3": {"position": "abc", "duration": None},
        "m4": {"position": 12.9, "duration": 60.4},
        "m9": {"position": 999},
    }}

    ns = {"load_json": lambda f: HIST if f == "H" else PROG,
          "HISTORY_FILE": "H", "PROGRESS_FILE": "P"}
    src = fn_source(out, "get_history")
    # מסירים את העיטור ואת async כדי להריץ ישירות
    src = "\n".join(l for l in src.splitlines()
                    if not l.strip().startswith("@"))
    src = src.replace("async def get_history(", "def get_history(")
    src = src.replace("x_user_id: str = Header(..., "
                      'description="Google User ID")', "x_user_id")
    exec(src, ns)
    rows = ns["get_history"]("u1")

    assert len(rows) == 4, f"פריט שאינו מילון לא דולג: {len(rows)}"
    by = {r["media_id"]: r for r in rows}
    assert by["m1"]["position"] == 754 and by["m1"]["duration"] == 5400, \
        "מיקום תקין לא הועבר"
    assert by["m1"]["title"] == "סרט" and by["m1"]["watched_at"] == 1, \
        "שדות קיימים נדרסו — תאימות לאחור נשברה"
    assert by["m2"]["position"] == 0 and by["m2"]["duration"] == 0, \
        "פריט בלי מיקום אינו 0"
    assert by["m3"]["position"] == 0, "מיקום פגום הפיל או עבר"
    assert by["m4"]["position"] == 12 and by["m4"]["duration"] == 60, \
        "שבר לא נחתך לשלם"
    assert all(r["position"] >= 0 for r in rows), "מיקום שלילי"
    # ומשתמש בלי היסטוריה אינו קורס
    assert ns["get_history"]("אין-כזה") == []

    # ③ מוטציה: בלי ה-join, ההמשכה חוזרת להיות תלויה בקריאה שנייה
    assert "prog.get(" in body, "ה-join הוסר — הבאג חוזר"


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
    print("זה הצד של השרת. האתר צריך גם את הבנייה החדשה כדי להשתמש")
    print("במיקום שמגיע — היא נכנסת עם update_all.sh.")


if __name__ == "__main__":
    main()
