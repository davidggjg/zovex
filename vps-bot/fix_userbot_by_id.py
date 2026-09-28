#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_userbot_by_id — שינוי שם משתמש בטלגרם ניתק את ההעלאה.

## מה קרה בפועל

    SAVED_UPLOAD_USER=@old_name אינו ב-pool. יש: @acct_a, @acct_b

החשבון היה שם כל הזמן. מה שהשתנה הוא **שם המשתמש שלו בטלגרם** —
הבעלים החליף אותו, וההעלאה הפסיקה לעבוד בלי שאיש נגע בקוד או בהגדרות.

## הפגם, ולא התקלה

ההתאמה נעשתה לפי ‎username‎:

    if (b.get("who") or "").lstrip("@").lower() == SAVED_UPLOAD_USER:

שם משתמש הוא **תווית**. אפשר להחליף אותה בשתי לחיצות, אפשר לוותר עליה
לגמרי (‎username‎ הוא ‎None‎ וב-‎who‎ נשמר שם פרטי), ושני חשבונות יכולים
להחליף שמות ביניהם. מה שאינו משתנה לעולם הוא **מזהה המשתמש**.

בחירת חשבון שאליו נשלחים סרטונים פרטיים היא בדיוק המקום שבו זיהוי
חייב להיות יציב: התאמה לפי תווית מתחלפת פירושה שהבוט עלול לשלוח לחשבון
אחר — או, כמו שקרה, לסרב לשלוח בכלל.

## מה משתנה

* המזהה נשמר לצד השם בכל מקום שבו נקרא ‎get_me()‎ — בעלייה, בהשלמת
  זהות חסרה, ובכפתור "חבר מחדש".
* ‎SAVED_UPLOAD_USER‎ מקבל **גם מספר**. ‎SAVED_UPLOAD_USER=123456789‎
  מתאים לפי מזהה ולא לפי שם, ולכן שינוי שם משתמש לא נוגע בו.
* שם משתמש ממשיך לעבוד בדיוק כמו קודם — אף הגדרה קיימת לא נשברת.
* ההודעה כשאין התאמה מציגה עכשיו גם את המזהים:

      SAVED_UPLOAD_USER=@old_name אינו ב-pool.
      יש: @acct_a (123456789), @acct_b (987654321)
      אם החלפת שם משתמש — שים את המספר במקום השם, הוא לא משתנה.

  כלומר ההודעה נותנת בדיוק את מה שצריך להעתיק כדי לתקן.

    python3 fix_userbot_by_id.py --check
    python3 fix_userbot_by_id.py
    python3 fix_userbot_by_id.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_userbot_by_id"
MARK = "fix_userbot_by_id"

# ── 1. המזהה נשמר בעלייה, לצד השם ────────────────────────────────────────
A_START = '''        who = ""
        try:
            me = await asyncio.wait_for(c.get_me(), timeout=15)
            who = ("@" + me.username) if me.username else (me.first_name or "")
        except Exception:
            pass
        entry = {"client": c, "name": name, "cooldown_until": 0.0,
                 "token": tok, "kind": kind, "peer_ok": True, "who": who}
'''

N_START = '''        who = ""
        uid = 0          # [fix_userbot_by_id] המזהה אינו משתנה לעולם
        try:
            me = await asyncio.wait_for(c.get_me(), timeout=15)
            who = ("@" + me.username) if me.username else (me.first_name or "")
            uid = int(getattr(me, "id", 0) or 0)
        except Exception:
            pass
        entry = {"client": c, "name": name, "cooldown_until": 0.0,
                 "token": tok, "kind": kind, "peer_ok": True, "who": who,
                 "uid": uid}
'''

# ── 2. השלמת זהות חסרה משלימה גם את המזהה ────────────────────────────────
A_RESOLVE = '''    if b.get("who"):
        return b["who"]
    try:
        me = await asyncio.wait_for(b["client"].get_me(), timeout=15)
        b["who"] = ("@" + me.username) if me.username \\
            else (me.first_name or "")
        if b["who"]:
            log.info("זהות %s הושלמה: %s", b.get("name"), b["who"])
'''

N_RESOLVE = '''    # [fix_userbot_by_id] גם מי שיש לו שם עשוי להיות בלי מזהה: את המזהה
    # התחלנו לשמור רק עכשיו, ורשומה שנוצרה לפני כן מחזיקה שם בלבד.
    if b.get("who") and b.get("uid"):
        return b["who"]
    try:
        me = await asyncio.wait_for(b["client"].get_me(), timeout=15)
        b["who"] = ("@" + me.username) if me.username \\
            else (me.first_name or "")
        b["uid"] = int(getattr(me, "id", 0) or 0)
        if b["who"]:
            log.info("זהות %s הושלמה: %s (%s)",
                     b.get("name"), b["who"], b["uid"])
'''

# ── 3. הכפתור "חבר מחדש" שומר גם את המזהה ────────────────────────────────
A_RECON = '''        who = ""
        try:
            me = await asyncio.wait_for(b["client"].get_me(), timeout=10)
            who = ("@" + me.username) if me.username else (me.first_name or "")
        except Exception:
            pass
        # [fix_saved_userbot] נכתב חזרה לרשומה, ולא רק מוחזר בתשובה.
        # קודם הכפתור קרא את הזהות, הציג אותה פעם אחת, וזרק אותה — ולכן
        # חשבון עם זהות ריקה נשאר כזה גם אחרי לחיצה על "חבר מחדש".
        if who:
            b["who"] = who
'''

N_RECON = '''        who = ""
        uid = 0
        try:
            me = await asyncio.wait_for(b["client"].get_me(), timeout=10)
            who = ("@" + me.username) if me.username else (me.first_name or "")
            uid = int(getattr(me, "id", 0) or 0)
        except Exception:
            pass
        # [fix_saved_userbot] נכתב חזרה לרשומה, ולא רק מוחזר בתשובה.
        # קודם הכפתור קרא את הזהות, הציג אותה פעם אחת, וזרק אותה — ולכן
        # חשבון עם זהות ריקה נשאר כזה גם אחרי לחיצה על "חבר מחדש".
        if who:
            b["who"] = who
        if uid:
            b["uid"] = uid          # [fix_userbot_by_id]
'''

# ── 4. ההתאמה: מזהה כשנתנו מספר, שם כשנתנו שם ────────────────────────────
A_MATCH = '''    if SAVED_UPLOAD_USER:
        for b in users:
            if (b.get("who") or "").lstrip("@").lower() == SAVED_UPLOAD_USER:
                return b, ""
        if [b for b in users if not (b.get("who") or "")]:
            return None, (f"יש {len(users)} חשבונות ב-pool אך זהותם לא "
                          f"נקראה בעלייה, ולכן אי אפשר לדעת מי מהם "
                          f"@{SAVED_UPLOAD_USER}")
        return None, ("SAVED_UPLOAD_USER=@" + SAVED_UPLOAD_USER +
                      " אינו ב-pool. יש: " +
                      ", ".join((b.get("who") or "?") for b in users))
    return users[0], ""
'''

N_MATCH = '''    if SAVED_UPLOAD_USER:
        # [fix_userbot_by_id] מספר = מזהה משתמש, וזה מה שלא משתנה לעולם.
        # שם משתמש הוא תווית: הבעלים החליף אותה פעם אחת וההעלאה נותקה
        # בלי שאיש נגע בקוד. שם ממשיך לעבוד, כדי לא לשבור הגדרה קיימת.
        want_id = int(SAVED_UPLOAD_USER) if SAVED_UPLOAD_USER.isdigit() else 0
        for b in users:
            if want_id:
                if int(b.get("uid") or 0) == want_id:
                    return b, ""
            elif (b.get("who") or "").lstrip("@").lower() == SAVED_UPLOAD_USER:
                return b, ""
        blind = [b for b in users
                 if not (b.get("uid") if want_id else b.get("who"))]
        if blind:
            return None, (f"יש {len(users)} חשבונות ב-pool אך זהותם לא "
                          f"נקראה בעלייה, ולכן אי אפשר לדעת מי מהם "
                          f"{SAVED_UPLOAD_USER}")
        return None, ("SAVED_UPLOAD_USER=" + SAVED_UPLOAD_USER +
                      " אינו ב-pool. יש: " +
                      ", ".join(f"{b.get('who') or '?'} ({b.get('uid') or '?'})"
                                for b in users) +
                      ". אם החלפת שם משתמש — שים את המספר במקום השם, "
                      "הוא לא משתנה.")
    return users[0], ""
'''

# ── 5. הפאנל מציג גם את המזהה ────────────────────────────────────────────
A_LIST = '''            "who": b.get("who", ""),           # @username — לזיהוי איזה בוט זה
'''

N_LIST = '''            "who": b.get("who", ""),           # @username — לזיהוי איזה בוט זה
            # [fix_userbot_by_id] המזהה, כדי שאפשר יהיה להעתיק אותו
            # ל-SAVED_UPLOAD_USER במקום שם משתמש שעלול להתחלף
            "uid": b.get("uid", 0),
'''

EDITS = [
    ("המזהה בעלייה", A_START, N_START, 1),
    ("השלמת מזהה חסר", A_RESOLVE, N_RESOLVE, 1),
    ("חבר מחדש שומר מזהה", A_RECON, N_RECON, 1),
    ("ההתאמה לפי מזהה", A_MATCH, N_MATCH, 1),
    ("הפאנל מציג מזהה", A_LIST, N_LIST, 1),
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
    assert "fix_saved_userbot" in out, \
        "חסר fix_saved_userbot — הרץ אותו קודם (update_all.sh עושה זאת בסדר)"

    reason = code_only(fn_source(out, "_userbot_reason"))
    assert "want_id" in reason, "ההתאמה עדיין לפי שם בלבד"
    assert 'b.get("uid")' in reason, "המזהה אינו נקרא"

    # שלושת מקורות הזהות שומרים מזהה
    for fn, why in (("_start_one_pool_bot", "העלייה"),
                    ("_resolve_who", "השלמת הזהות"),
                    ("pool_reconnect", "חבר מחדש")):
        body = code_only(fn_source(out, fn))
        assert 'getattr(me, "id", 0)' in body, f"{why} אינה שומרת מזהה"

    # ── ההתנהגות, ולא רק המחרוזות ───────────────────────────────────────
    src = fn_source(out, "_userbot_reason")

    def run(bots, want):
        ns = {"_stream_bots": bots, "SAVED_UPLOAD_USER": want}
        exec(src, ns, ns)
        return ns["_userbot_reason"]()

    a = {"kind": "user", "who": "@acct_a", "uid": 111}
    b = {"kind": "user", "who": "@acct_b", "uid": 222}

    # שם משתמש — כמו קודם, בלי רגרסיה
    got, why = run([a, b], "acct_a")
    assert got is a and why == "", why
    got, why = run([a, b], "acct_b")
    assert got is b and why == "", why

    # **הבאג עצמו**: השם התחלף, המזהה לא. לפי מספר זה עובד.
    got, why = run([a, b], "111")
    assert got is a and why == "", why
    renamed = dict(a, who="@david_new")
    got, why = run([renamed, b], "111")
    assert got is renamed, "שינוי שם משתמש עדיין מנתק התאמה לפי מזהה"

    # שם שאינו קיים — נדחה, וההודעה נותנת את המספרים להעתקה
    got, why = run([a, b], "old_name")
    assert got is None
    assert "111" in why and "222" in why, why
    assert "לא משתנה" in why, why

    # מזהה שאינו קיים — נדחה גם הוא
    got, why = run([a, b], "999")
    assert got is None and "999" in why, why

    # רשומה ישנה בלי מזהה, וביקשו לפי מזהה: לא מנחשים
    old = {"kind": "user", "who": "@acct_a"}
    got, why = run([old], "111")
    assert got is None and "זהותם לא" in why, why

    # ואותה רשומה ישנה עם בקשה לפי שם — עובדת כרגיל
    got, why = run([old], "acct_a")
    assert got is old and why == "", why


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
    print("python3 check_userbot.py     # מדפיס את המזהים")
    print()
    print("ואז ב-.env:  SAVED_UPLOAD_USER=<המספר>")
    print("מספר ולא שם — שם משתמש אפשר להחליף, מזהה לא.")


if __name__ == "__main__":
    main()
