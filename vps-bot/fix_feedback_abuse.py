#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_feedback_abuse — רשימה סגורה ל-kind, ומכסה על נתיב לא מאומת.

## מה נמדד

התקבלו הודעות תמיכה שמיפו את הנתיב במפורש:

    "rate-limit probe INT-20261004-125 #1"   05:36
    "rate-limit probe INT-20261004-125 #2"   05:36
    "rate-limit probe INT-20261004-125 #3"   05:36
    "SPOOF TEST INT-20261004-130"            05:51
    kind = "SECTEST-F05"                     ← מצויר בתווית בפאנל

שלוש הודעות באותה דקה עברו. ‎kind‎ שרירותי הופיע בתווית. כלומר שתי
המסקנות שהבודק חיפש אושרו לו על ידי המערכת עצמה.

## שתי התקלות שנסגרות כאן

**1. ‎kind‎ היה טקסט חופשי.**

    kind: Optional[str] = "support"   # support / review / tip

ההערה מתארת שלושה ערכים; הקוד לא אכף אותם. השדה מצויר בפאנל, ושם
הוא נכתב ל-‎innerHTML‎ — ראה ‎fix_feedback_xss.py‎. הבריחה בפאנל היא
השכבה שמגינה גם על מה שכבר נכתב למסד; הרשימה הסגורה כאן מונעת
כניסה מלכתחילה. שתיהן נדרשות.

**2. אין מכסה.**

‎/feedback/send‎ אינו מאומת, וכל בקשה קוראת את ‎feedback.json‎ כולו,
מוסיפה, וכותבת אותו **במלואו** בחזרה. כלומר הצפה אינה רק זבל
במסך — היא קריאה-וכתיבה של הקובץ כולו, פר הודעה.

## מה **לא** נסגר כאן, ואסור להתבלבל

הנתיב עדיין **אינו מאומת**. הזהות היא ‎user_id‎ שהלקוח שולח, ולכן:

* מי שמכיר ‎user_id‎ יכול לכתוב לשיחה של אותו משתמש
* ‎name‎ ו-‎email‎ של שיחה קיימת עדיין ניתנים לדריסה (זה ה-SPOOF)
* ‎fcm_token‎ ניתן לדריסה — כלומר הפניית התראות של משתמש למכשיר אחר
* ‎/feedback/mine?user_id=‎ מחזיר הודעות של כל ‎user_id‎ שיימסר

אלה דורשים **אימות אמיתי**, לא תיקון נקודתי. הפאצ' הזה מצמצם נזק,
אינו פותר זהות. אל תסמן את זה כסגור.

    python3 fix_feedback_abuse.py --check
    python3 fix_feedback_abuse.py
    python3 fix_feedback_abuse.py --revert

אחרי ההחלה:  systemctl restart zovex-bot
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_feedback_abuse"
MARK = "fix_feedback_abuse"

A_HANDLER = '''@api.post("/feedback/send")
async def feedback_send(req: FeedbackSendReq):
    text = (req.text or "").strip()
    if not req.user_id or not text:
        raise HTTPException(status_code=400, detail="חסר משתמש או טקסט")
    d = load_feedback()
    th = d.get(req.user_id) or {"user_id": req.user_id, "messages": []}
    if req.name:  th["name"] = req.name
    if req.email: th["email"] = req.email
    if req.fcm_token: th["fcm_token"] = req.fcm_token
    th["messages"].append({"from": "user", "text": text[:4000],
                           "ts": datetime.utcnow().isoformat(), "kind": req.kind or "support"})
'''

N_HANDLER = '''# [fix_feedback_abuse] שלושת הערכים שהממשק מכיר. השדה מצויר כתווית
# בפאנל, והוא הגיע לשם מהרשת בלי סינון — ההערה בדגם תיארה רשימה
# שהקוד מעולם לא אכף.
_FB_KINDS = {"support", "review", "tip"}

# מכסה לשעה, לכתובת. הנתיב אינו מאומת, וכל בקשה קוראת וכותבת את
# feedback.json **במלואו** — ולכן הצפה אינה רק זבל במסך.
_fb_rate: dict = {}
FB_MAX_PER_HOUR = int(os.environ.get("FB_MAX_PER_HOUR", "12"))


def _fb_rate_ok(ip: str) -> bool:
    """True אם מותר לשלוח. רושם את השליחה רק כשהיא מותרת."""
    now = time.time()
    cutoff = now - 3600
    # בלי הניקוי הזה המילון גדל לכל כתובת שאי פעם שלחה, ולא מתרוקן
    # לעולם. הסף גבוה כדי שהניקוי לא ירוץ בכל בקשה.
    if len(_fb_rate) > 5000:
        for k in [k for k, v in _fb_rate.items() if not v or v[-1] < cutoff]:
            _fb_rate.pop(k, None)
    hits = [t for t in _fb_rate.get(ip, []) if t > cutoff]
    if len(hits) >= FB_MAX_PER_HOUR:
        _fb_rate[ip] = hits          # נדחה — לא נרשם, אחרת העונש מתארך לבד
        return False
    hits.append(now)
    _fb_rate[ip] = hits
    return True


@api.post("/feedback/send")
async def feedback_send(req: FeedbackSendReq, request: Request):
    text = (req.text or "").strip()
    if not req.user_id or not text:
        raise HTTPException(status_code=400, detail="חסר משתמש או טקסט")
    # [fix_feedback_abuse] המכסה נבדקת **לפני** קריאת הקובץ, אחרת
    # ההצפה עולה לנו את מלוא העבודה גם כשהיא נדחית.
    if not _fb_rate_ok(_client_ip(request)):
        raise HTTPException(status_code=429,
                            detail="יותר מדי הודעות. נסה שוב מאוחר יותר.")
    d = load_feedback()
    th = d.get(req.user_id) or {"user_id": req.user_id, "messages": []}
    # קיצוץ אורך: שני השדות מצוירים בפאנל, ואין סיבה שיהיו ארוכים.
    if req.name:  th["name"] = req.name[:80]
    if req.email: th["email"] = req.email[:120]
    if req.fcm_token: th["fcm_token"] = req.fcm_token
    kind = req.kind if req.kind in _FB_KINDS else "support"
    th["messages"].append({"from": "user", "text": text[:4000],
                           "ts": datetime.utcnow().isoformat(), "kind": kind})
'''

EDITS = [("נתיב שליחת המשוב", A_HANDLER, N_HANDLER, 1)]


def fn_source(src: str, name: str) -> str:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"לא נמצאה הפונקציה {name}")


def code_only(text: str) -> str:
    return "\n".join(l for l in text.splitlines()
                     if not l.strip().startswith("#"))


def validate(out: str) -> None:
    compile(out, "main.py", "exec")

    body = code_only(fn_source(out, "feedback_send"))
    assert "_fb_rate_ok(_client_ip(request))" in body, "אין מכסה"
    assert "req.kind in _FB_KINDS" in body, "kind אינו מוגבל לרשימה"
    assert "req.kind or \"support\"" not in body, "נשארה הנפילה הישנה"
    assert "request: Request" in body, "ה-handler אינו מקבל Request"
    # והמכסה לפני העבודה היקרה, לא אחריה
    assert body.index("_fb_rate_ok") < body.index("load_feedback()"), \
        "המכסה נבדקת אחרי קריאת הקובץ"

    # ── המכסה עצמה, מורצת ─────────────────────────────────────────────
    ns = {"os": os, "time": __import__("time"), "_fb_rate": {},
          "FB_MAX_PER_HOUR": 3}
    exec(fn_source(out, "_fb_rate_ok"), ns)
    ok = ns["_fb_rate_ok"]

    assert all(ok("1.2.3.4") for _ in range(3)), "נחסם מתחת למכסה"
    assert not ok("1.2.3.4"), "המכסה אינה נאכפת"
    assert not ok("1.2.3.4"), "דחייה אחת בלבד — המכסה דולפת"

    # בקשה **שנדחתה** אסור שתירשם. אחרת כל ניסיון חוזר דוחף את החלון
    # קדימה, המציף אינו משתחרר לעולם — ומשתמש תמים מאחורי אותו NAT
    # ננעל לצמיתות. ‎not ok(...)‎ לבדו אינו מבחין בזה: שתי ההתנהגויות
    # מחזירות False. נתפס במוטציה.
    assert len(ns["_fb_rate"]["1.2.3.4"]) == 3, \
        f"דחייה נרשמה — העונש מתארך מעצמו ({len(ns['_fb_rate']['1.2.3.4'])})"

    # וכתובת אחרת אינה נענשת על מי שלפניה
    assert ok("5.6.7.8"), "כתובות התערבבו"

    # דחייה אינה מאריכה את העונש: אחרי שהחלון זז, מותר שוב
    ns["_fb_rate"]["9.9.9.9"] = [ns["time"].time() - 3700] * 10
    assert ok("9.9.9.9"), "רשומות ישנות לא פגו"

    # ומוטציה: מכסה 0 חייבת לחסום הכול — אחרת הבדיקה חסרת ערך
    ns["FB_MAX_PER_HOUR"] = 0
    ns["_fb_rate"].clear()
    assert not ok("1.1.1.1"), "הסף אינו משפיע — הבדיקה חסרת ערך"

    # ── הרשימה הסגורה, מורצת ──────────────────────────────────────────
    i = out.index("_FB_KINDS = ")
    kinds = eval(out[out.index("{", i):out.index("}", i) + 1])
    assert kinds == {"support", "review", "tip"}, f"רשימה לא צפויה: {kinds}"
    for bad in ("SECTEST-F05", "<img src=x onerror=alert(1)>", "", None):
        assert (bad if bad in kinds else "support") == "support", \
            f"ערך זר עבר: {bad!r}"
    for good in ("support", "review", "tip"):
        assert (good if good in kinds else "support") == good, \
            f"ערך תקין נדחה: {good}"


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
    print("שים לב: הנתיב עדיין אינו מאומת. זיוף שם ודריסת טוקן התראות")
    print("נשארו פתוחים — ראה את ההסבר בראש הקובץ.")


if __name__ == "__main__":
    main()
