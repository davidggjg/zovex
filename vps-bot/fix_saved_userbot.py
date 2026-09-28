#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_saved_userbot — "אין חשבון מחובר" בלי לומר למה, ובלי דרך לתקן.

## הדיווח

    באפליקציה:   "חשבון לא מחובר"
    בפאנל ניהול: מחובר

שתי התשובות נכונות ועל שני דברים שונים: הפאנל סופר חברי pool, וההעלאה
ל"הודעות שמורות" דורשת חבר אחד מסוג ‎user‎ — חשבון אמיתי, כי הודעות
שמורות שייכות לחשבון ובוט אינו חשבון. ‎check_userbot.py‎ מפריד בין
המקרים. הקובץ הזה מתקן שלושה פגמים בקוד עצמו.

## 1. זהות שנקראה פעם אחת, ובשקט לא נקראה

    who = ""
    try:
        me = await asyncio.wait_for(c.get_me(), timeout=15)
        who = ("@" + me.username) if me.username else (me.first_name or "")
    except Exception:
        pass

זה רץ פעם אחת בעלייה. אם ‎get_me()‎ חרג — וזה קורה דווקא בהפעלה מחדש,
כשעולים 16 חברים בזה אחר זה וטלגרם מאט, אותו מצב שבגללו כבר הועלה
‎POOL_START_TIMEOUT‎ מ-40 ל-75 — ‎who‎ נשאר ריק לתמיד.

וכשריק, ‎_pick_userbot()‎ מחפש התאמה ל-‎SAVED_UPLOAD_USER‎ ולא מוצא
אף פעם. חשבון עובד לחלוטין, והעלאה מתה — בלי שורה אחת ביומן.

**המדרון:** ‎pool_reconnect‎, הכפתור שאמור לרפא בדיוק את זה, קורא את
‎who‎ מחדש ומחזיר אותו בתשובה — ולא כותב אותו חזרה לרשומה. כלומר
הרפואה קיימת, רצה, ונזרקת.

## 2. ‎ready: false‎ בלי סיבה, ואז כישלון מאוחר

‎/panel/entry-code‎ כבר יודע בשנייה הראשונה שאין חשבון, ומחזיר
‎ready: false‎ בלי להסביר. האפליקציה לא בודקת את זה, פותחת את הפאנל,
והמשתמש בוחר קובץ, ממתין, ורק אז מקבל 503. עכשיו יש ‎reason‎ בעברית,
וההודעות ב-503 אומרות איזו משלוש הסיבות זו.

## 3. "לא מנחשים" הפך ל"לא עונים"

הסירוב להתאמה חלקית נכון ונשאר: סרטון פרטי לא נשלח לחשבון שלא ביקשו.
מה שמשתנה הוא שההתאמה נעשית מול זהות שנקראה בפועל — ‎/panel/entry-code‎
משלים זהות חסרה לפני שהוא בודק — במקום מול שדה ריק.

## מה לא משתנה

‎_pick_userbot()‎ נשארת בדיוק באותה חתימה ובאותה התנהגות, כי ארבעה
מקומות אחרים קוראים לה. היא רק עוטפת עכשיו את ‎_userbot_reason()‎.

    python3 fix_saved_userbot.py --check
    python3 fix_saved_userbot.py
    python3 fix_saved_userbot.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_saved_userbot"
MARK = "fix_saved_userbot"

# ── 1. הבחירה מחזירה גם סיבה, ויש דרך להשלים זהות חסרה ────────────────────
A_PICK = '''def _pick_userbot():
    """חבר פוּל מסוג user. בוט לא יכול לשלוח ל'הודעות שמורות' של חשבון."""
    users = [b for b in _stream_bots if b.get("kind") == "user"]
    if not users:
        return None
    if SAVED_UPLOAD_USER:
        for b in users:
            if (b.get("who") or "").lstrip("@").lower() == SAVED_UPLOAD_USER:
                return b
        return None           # ביקשו חשבון מסוים והוא לא בפוּל — לא מנחשים
    return users[0]
'''

N_PICK = '''def _userbot_reason():
    """[fix_saved_userbot] (חשבון, סיבה). סיבה ריקה = יש חשבון.

    קודם הוחזר ‎None‎ יחיד לשלושה מצבים שונים לגמרי, ולכן ההודעה
    למשתמש הייתה "אין חשבון מחובר" גם כשהיה חשבון מחובר לגמרי."""
    users = [b for b in _stream_bots if b.get("kind") == "user"]
    if not users:
        return None, ("אין חשבון משתמש ב-pool — רק בוטים. "
                      "בוט אינו יכול לכתוב להודעות השמורות של חשבון.")
    if SAVED_UPLOAD_USER:
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


def _pick_userbot():
    """חבר פוּל מסוג user. בוט לא יכול לשלוח ל'הודעות שמורות' של חשבון.

    אותה חתימה ואותה התנהגות כמו קודם — ארבעה מקומות קוראים לה."""
    return _userbot_reason()[0]


async def _resolve_who(b):
    """[fix_saved_userbot] משלים זהות שלא נקראה בעלייה.

    ‎who‎ נקרא פעם אחת ב-‎_start_one_pool_bot‎ בתוך ‎except: pass‎.
    חריגה שם — ותשומת לב: היא צפויה דווקא בהפעלה מחדש, כשטלגרם מאט
    שרשרת של 16 התחברויות — משאירה אותו ריק לתמיד, וההתאמה ל-
    ‎SAVED_UPLOAD_USER‎ לא תצליח לעולם. כאן הוא נקרא שוב, בפועל."""
    if b.get("who"):
        return b["who"]
    try:
        me = await asyncio.wait_for(b["client"].get_me(), timeout=15)
        b["who"] = ("@" + me.username) if me.username \\
            else (me.first_name or "")
        if b["who"]:
            log.info("זהות %s הושלמה: %s", b.get("name"), b["who"])
    except Exception as e:
        log.warning("זהות %s לא נקראה: %s: %s",
                    b.get("name"), type(e).__name__, e)
    return b.get("who") or ""


async def _userbot_ready():
    """[fix_saved_userbot] כמו ‎_userbot_reason‎, אחרי השלמת זהויות."""
    for b in [x for x in _stream_bots if x.get("kind") == "user"]:
        await _resolve_who(b)
    return _userbot_reason()
'''

# ── 2. הכניסה אומרת למה, ולא רק "לא מוכן" ────────────────────────────────
A_ENTRY = '''    _check_upload_code(req, str(body.get("code") or ""))
    bot = _pick_userbot()
    _max = await _saved_max_size()
    return {"ok": True, "account": (bot or {}).get("who") or "",
            "ready": bot is not None,
'''

N_ENTRY = '''    _check_upload_code(req, str(body.get("code") or ""))
    # [fix_saved_userbot] משלימים זהות חסרה **לפני** הבדיקה. בלי זה
    # חשבון שעלה תקין נדחה רק מפני ש-get_me נכשל פעם אחת בעלייה.
    bot, _why = await _userbot_ready()
    _max = await _saved_max_size()
    return {"ok": True, "account": (bot or {}).get("who") or "",
            "reason": _why,
            "ready": bot is not None,
'''

# ── 3. הכפתור שמרפא — שומר את מה שריפא ───────────────────────────────────
A_RECON = '''        who = ""
        try:
            me = await asyncio.wait_for(b["client"].get_me(), timeout=10)
            who = ("@" + me.username) if me.username else (me.first_name or "")
        except Exception:
            pass
        out.append({"name": b["name"], "peer_ok": ok, "who": who,
'''

N_RECON = '''        who = ""
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
        out.append({"name": b["name"], "peer_ok": ok, "who": who,
'''

# ── 4. ההודעות אומרות איזו סיבה ──────────────────────────────────────────
A_RUNTIME = '''        bot = _pick_userbot()
        if bot is None:
            raise RuntimeError("אין חשבון משתמש מחובר בשרת "
                               "(רק חשבון יכול לשלוח ל'הודעות שמורות')")
'''

N_RUNTIME = '''        bot, _why = _userbot_reason()
        if bot is None:
            # [fix_saved_userbot] הסיבה, ולא רק העובדה
            raise RuntimeError(_why or "אין חשבון משתמש מחובר בשרת")
'''

A_503 = '''    if _pick_userbot() is None:
        raise HTTPException(status_code=503,
                            detail="אין חשבון משתמש מחובר בשרת")
'''

N_503 = '''    _ub, _why = _userbot_reason()
    if _ub is None:
        # [fix_saved_userbot] הסיבה מגיעה לאפליקציה במקום "לא מחובר" סתם
        raise HTTPException(status_code=503,
                            detail=_why or "אין חשבון משתמש מחובר בשרת")
'''

EDITS = [
    ("בחירת החשבון עם סיבה", A_PICK, N_PICK, 1),
    ("הכניסה מחזירה סיבה", A_ENTRY, N_ENTRY, 1),
    ("reconnect שומר את הזהות", A_RECON, N_RECON, 1),
    ("הודעת ההעלאה", A_RUNTIME, N_RUNTIME, 1),
    ("שני שערי ה-503", A_503, N_503, 2),
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

    # ── החתימה הישנה נשמרה: ארבעה מקומות אחרים תלויים בה ────────────────
    pick = code_only(fn_source(out, "_pick_userbot"))
    assert "_userbot_reason()[0]" in pick, "_pick_userbot כבר לא עוטפת"
    # ‎_saved_max_size‎ הוא הקורא שנשאר אחרי הפאץ' (השאר עברו ל-
    # ‎_userbot_reason‎), והוא מחזיר 0 בלי חשבון — כלומר המסך היה מכריז
    # "גדול מדי" על כל קובץ. אסור שהעטיפה תיעלם מתחתיו.
    assert "_pick_userbot()" in code_only(fn_source(out, "_saved_max_size")), \
        "_saved_max_size איבד את הקריאה"

    # ── הזהות נכתבת חזרה, ולא רק נקראת ─────────────────────────────────
    recon = code_only(fn_source(out, "pool_reconnect"))
    assert 'b["who"] = who' in recon, "reconnect עדיין זורק את הזהות"

    entry = code_only(fn_source(out, "panel_entry_code"))
    assert "await _userbot_ready()" in entry, "הכניסה לא משלימה זהות"
    assert '"reason"' in entry, "הכניסה לא מחזירה סיבה"

    # ── אין 503 שנשאר בלי סיבה ─────────────────────────────────────────
    assert "detail=_why or" in out, "שער 503 בלי סיבה"
    assert out.count("detail=_why or") == 2, \
        f'צפויים שני שערי 503, יש {out.count("detail=_why or")}'
    assert 'detail="אין חשבון משתמש מחובר בשרת"' not in out, \
        "נשארה הודעת 503 בלי סיבה"

    # ── ההתנהגות עצמה, ולא רק המחרוזות ─────────────────────────────────
    ns = {}
    src = fn_source(out, "_userbot_reason")

    def run(bots, want):
        local = {"_stream_bots": bots, "SAVED_UPLOAD_USER": want}
        exec(src, local, local)
        return local["_userbot_reason"]()

    # אין חשבון בכלל
    b, why = run([{"kind": "bot", "who": "@x"}], "")
    assert b is None and "רק בוטים" in why, why

    # חשבון יחיד בלי הגבלה
    u = {"kind": "user", "who": "@me"}
    b, why = run([u], "")
    assert b is u and why == "", why

    # ההגבלה תואמת
    b, why = run([u], "me")
    assert b is u and why == "", why

    # ההגבלה אינה תואמת — נדחה בכוונה, ואומר את מי כן יש
    b, why = run([u], "other")
    assert b is None and "@me" in why, why

    # **הבאג עצמו**: זהות ריקה. נדחה, אבל הסיבה אומרת שזו זהות ולא חשבון
    b, why = run([{"kind": "user", "who": ""}], "me")
    assert b is None, "חשבון בלי זהות אינו יכול להיבחר — לא מנחשים"
    assert "זהותם לא" in why, f"הסיבה השגויה: {why}"

    ns.clear()


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
    print("python3 check_userbot.py")


if __name__ == "__main__":
    main()
