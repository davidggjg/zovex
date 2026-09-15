#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מתקן דליפת sessions בפול הסטרימינג.

מה נמדד בשרת: 90 כתובות transport שונות, כל אחת בדיוק 360 שגיאות
"handler is closed" ב-30 דקות — אחת כל 5 שניות, שהוא בדיוק מרווח ה-ping
של Pyrogram. כלומר 90 sessions מתים שממשיכים לפעול, 18 שגיאות בשנייה,
50,916 ב-90 דקות.

מקור הדליפה: _force_down מבקש מה-session להיעצר, ואם הבקשה נכשלת או
חורגת מהזמן הוא בולע את השגיאה ומאלץ את הדגלים ל-False. הלקוח נראה אז
"מנותק" ו-start() יוצר session חדש — בעוד משימת ה-ping של הישן ממשיכה
לכתוב לשקע המת לנצח. כל החייאה שנכשלת בניקיון מוסיפה רוח רפאים.

התיקון: לפני אילוץ הדגלים, לבטל ישירות כל משימה אסינכרונית שעדיין חיה
על ה-session, ולסגור את החיבור. הסריקה היא על תכונות ה-session ולא לפי
שמות קבועים, כי שמות המשימות משתנים בין גרסאות Pyrogram.

בטיחות: פועל אך ורק על session שכבר הוחלט שהוא מת (_force_down נקרא רק
במסלול ההפלה לפני הרמה מחדש). אינו נוגע בחיבור פעיל.

הערה: התיקון מונע דליפות חדשות. 90 הקיימות ייעלמו בהפעלה מחדש אחת.

    python3 fix_pool_session_leak.py --check
    python3 fix_pool_session_leak.py
    python3 fix_pool_session_leak.py --revert
"""
import argparse, datetime, glob, os, pathlib, shutil, sys

TARGET = pathlib.Path(os.environ.get("BOT_PY", "/opt/zovex-bot/main.py"))
MARK = "_kill_session_tasks"

ANCHOR = '''    # מוצא אחרון. לא אלגנטי, אבל החלופה היא בוט שלא יחזור לעולם — וזה
    # בדיוק המצב שנמדד לפני התיקון הזה.
    for flag in ("is_connected", "is_initialized"):'''

BLOCK = '''    # ביקשנו מה-session להיעצר; כאן מוודאים שהוא באמת נעצר. אם הבקשה
    # נכשלה, משימת ה-ping שלו ממשיכה לכתוב לשקע מת כל 5 שניות — לנצח —
    # בעוד start() יוצר session חדש לידה. כך הצטברו 90 sessions יתומים
    # ו-18 שגיאות בשנייה. ביטול ישיר סוגר את זה.
    _kill_session_tasks(sess)

    # מוצא אחרון. לא אלגנטי, אבל החלופה היא בוט שלא יחזור לעולם — וזה
    # בדיוק המצב שנמדד לפני התיקון הזה.
    for flag in ("is_connected", "is_initialized"):'''

HELPER_ANCHOR = "async def _force_down(client):"

HELPER = '''def _kill_session_tasks(sess) -> int:
    """מבטל כל משימה אסינכרונית שעדיין חיה על session מת, וסוגר את החיבור.

    סורק את תכונות ה-session ולא מחפש שמות קבועים ("ping_task" וכו'), כי
    השמות משתנים בין גרסאות Pyrogram ותיקון שתלוי בהם יישבר בשקט בשדרוג
    הבא — וכישלון שקט כאן מחזיר בדיוק את הדליפה שהוא נועד למנוע.

    נקרא אך ורק מ-_force_down, כלומר על session שכבר הוחלט שהוא מת.
    """
    if sess is None:
        return 0
    killed = 0
    try:
        for val in list(vars(sess).values()):
            if isinstance(val, asyncio.Task) and not val.done():
                val.cancel()
                killed += 1
    except Exception:
        pass
    # החיבור עצמו: בלי סגירה מפורשת השקע עלול להישאר פתוח עד שה-GC יגיע
    # אליו, ועד אז משימה שלא נתפסה בסריקה עוד יכולה לכתוב אליו.
    conn = getattr(sess, "connection", None)
    if conn is not None:
        for meth in ("close", "disconnect"):
            fn = getattr(conn, meth, None)
            if fn is None:
                continue
            try:
                r = fn()
                if asyncio.iscoroutine(r):
                    asyncio.ensure_future(r)
                break
            except Exception:
                pass
    if killed:
        log.info("🧹 בוטלו %d משימות של session מת", killed)
    return killed


async def _force_down(client):'''


def _fail(m):
    print(f"❌ {m}"); sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    if not TARGET.exists():
        _fail(f"{TARGET} לא נמצא")

    if a.revert:
        baks = sorted(glob.glob(str(TARGET) + ".bak-poolleak-*"))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], TARGET)
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}\n   צריך: systemctl restart zovex-bot")
        return

    src = TARGET.read_text(encoding="utf-8")
    if MARK in src:
        print("✓ התיקון כבר מוחל. לא שונה כלום.")
        return
    for name, anc in (("קריאת העזר", ANCHOR), ("הגדרת _force_down", HELPER_ANCHOR)):
        if src.count(anc) != 1:
            _fail(f"{name}: נמצאו {src.count(anc)} עוגנים, ציפינו ל-1.")
    # התיקון מסתמך על כך ש-sess כבר קיים במשתנה המקומי של _force_down
    if "sess = getattr(client, \"session\", None)" not in src:
        _fail("לא נמצא המשתנה sess ב-_force_down — הפונקציה לא מה שציפינו לה.")

    out = src.replace(HELPER_ANCHOR, HELPER).replace(ANCHOR, BLOCK)
    try:
        compile(out, str(TARGET), "exec")
    except SyntaxError as e:
        _fail(f"לא עובר קומפילציה: {e}")
    for n in ("import asyncio", "log ="):
        if n not in src and n.replace("import ", "") not in src:
            _fail(f"main.py חסר {n} — הבלוק היה נופל בזמן ריצה.")

    if a.check:
        print("✓ העוגנים מתאימים, הקומפילציה עוברת, וכל השמות קיימים. לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-poolleak-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print(f"✓ הוחל. גיבוי: {os.path.basename(bak)}")
    print("   צריך: systemctl restart zovex-bot")
    print("   (הריסטארט גם מנקה את 90 היתומים הקיימים)")


if __name__ == "__main__":
    main()
