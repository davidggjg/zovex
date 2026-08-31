#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מתקן שני ליקויים בבדיקת הבריאות, ששניהם התגלו בריצה אמיתית.

**הראשון: בוט שלא ניתן להרמה.**

    ♻️ bot_20 — חיבור מת, מרים session מחדש
    ⚠️ הרמת bot_20 נכשלה: ConnectionError: Client is already connected

שמונה-עשר סבבים, כל אחד נכשל 6 מילישניות אחרי שהתחיל. כלומר לא רשת ולא
טלגרם — מצב פנימי. Pyrogram מחזיק שני דגלים נפרדים, is_initialized ו-
is_connected: stop() בודק את הראשון ו-connect() את השני. על חיבור מת אפשר
להגיע למצב שבו stop() נכשל מיד ב"already terminated" בעוד is_connected
נשאר True — ומאז כל start() נכשל ב"already connected", לנצח, עד restart
מלא של השירות.

הגרסה הקודמת עטפה את stop() ב-except: pass והמשיכה כאילו הצליח. כאן
מורידים את הלקוח בשלבים — stop, ואם צריך disconnect, ואם צריך גם עצירה
ישירה של ה-session — ורק אם כל אלה נכשלו מאפסים את הדגלים ידנית.

עצירת ה-session אינה קוסמטית: משימת ה-ping שלו היא שממשיכה לכתוב לשקע
המת כל 5 שניות. היא המקור לשורות "Send exception" שספרנו, ובלי לעצור
אותה הרמת הלקוח מותירה אותה רצה ברקע.

**השני: בוט מת שנשאר ברוטציה.**

    בוט bot_20 נכשל (2/3) — עדיין בשירות

צופה אמיתי נחת על bot_20 ושילם timeout מלא — תשעים דקות אחרי שהבדיקה כבר
ידעה שהוא מת. זיהוי בלי הדחה שווה מעט: מסמנים cooldown ברגע שהוא חוצה את
הסף, כך ש-pick_stream_bot מדלג עליו עד שיורם בפועל.

דורש ש-fix_pool_health.py כבר הוחל.

    python3 fix_pool_health2.py          # מחיל
    python3 fix_pool_health2.py --undo   # מחזיר
"""
import datetime, glob, os, pathlib, py_compile, shutil, sys, tempfile

TARGET = pathlib.Path("/opt/zovex-bot/main.py")

OLD_REVIVE = '''async def _revive_bot(b):
    """מפיל ומרים session. True אם הצליח."""
    name = b.get("name", "?")
    log.warning("♻️ %s — חיבור מת, מרים session מחדש", name)
    try:
        # stop() על לקוח תקוע עלול להיתקע בעצמו — עוטפים בתקציב.
        await asyncio.wait_for(b["client"].stop(), timeout=20)
    except Exception:
        pass
    try:
'''

NEW_REVIVE = '''async def _force_down(client):
    """מוודא שהלקוח באמת מנותק לפני start(), ולא רק שביקשנו ממנו.

    Pyrogram מחזיק שני דגלים נפרדים: stop() בודק את is_initialized בעוד
    connect() בודק את is_connected. על חיבור מת אפשר להיתקע ביניהם —
    stop() נכשל מיד ב"already terminated" בזמן ש-is_connected נשאר True,
    ומאז כל start() נכשל ב"already connected". זה בדיוק מה שקרה ל-bot_20:
    18 סבבים, כל אחד נכשל תוך 6 מילישניות, אפס הרמות.

    עצירת ה-session בשלב השלישי אינה ניקיון בעלמא: משימת ה-ping שלו היא
    שכותבת לשקע המת כל 5 שניות ומייצרת את שורות "Send exception". בלי
    לעצור אותה היא ממשיכה לרוץ גם אחרי שהלקוח הורם.
    """
    for meth, budget in (("stop", 20), ("disconnect", 10)):
        if not (getattr(client, "is_connected", False)
                or getattr(client, "is_initialized", False)):
            return
        fn = getattr(client, meth, None)
        if fn is None:
            continue
        try:
            await asyncio.wait_for(fn(), timeout=budget)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
    sess = getattr(client, "session", None)
    if sess is not None:
        try:
            await asyncio.wait_for(sess.stop(), timeout=10)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
    # מוצא אחרון. לא אלגנטי, אבל החלופה היא בוט שלא יחזור לעולם — וזה
    # בדיוק המצב שנמדד לפני התיקון הזה.
    for flag in ("is_connected", "is_initialized"):
        if getattr(client, flag, False):
            try:
                setattr(client, flag, False)
            except Exception:
                pass


async def _revive_bot(b):
    """מפיל ומרים session. True אם הצליח."""
    name = b.get("name", "?")
    log.warning("♻️ %s — חיבור מת, מרים session מחדש", name)
    await _force_down(b["client"])
    try:
'''

OLD_NEED = '''            if b["health_fails"] >= HEALTH_FAILS:
                need.append(b)
'''

NEW_NEED = '''            if b["health_fails"] >= HEALTH_FAILS:
                # מוציאים אותו מהרוטציה *מיד*, לא רק אחרי שההרמה תצליח.
                # ביומן נראה "בוט bot_20 נכשל (2/3) — עדיין בשירות" תשעים
                # דקות אחרי שהבדיקה כבר ידעה שהוא מת: צופה אמיתי נחת עליו
                # ושילם timeout מלא. זיהוי בלי הדחה שווה מעט.
                b["cooldown_until"] = max(b.get("cooldown_until", 0.0),
                                          time.time() + HEALTH_EVERY * 2)
                need.append(b)
'''

EDITS = [("הורדה כפויה לפני הרמה", OLD_REVIVE, NEW_REVIVE),
         ("הדחת בוט מת מהרוטציה", OLD_NEED, NEW_NEED)]


def _fail(msg):
    print("❌ " + msg)
    print("   לא שונה כלום.")
    sys.exit(1)


def undo():
    baks = sorted(glob.glob(str(TARGET) + ".bak-health2-*"))
    if not baks:
        _fail("לא נמצא גיבוי")
    shutil.copy2(baks[-1], TARGET)
    print(f"↩️  שוחזר מ-{os.path.basename(baks[-1])}")
    print("   הרץ:  systemctl restart zovex-bot")


def main():
    if not TARGET.exists():
        _fail(f"לא נמצא {TARGET}")
    src = TARGET.read_text(encoding="utf-8")

    if "_force_down" in src:
        print("✓ כבר מוחל. אין מה לעשות.")
        return
    if "pool_health_loop" not in src:
        _fail("fix_pool_health.py לא הוחל — הרץ אותו קודם")

    out = src
    for name, old, new in EDITS:
        n = out.count(old)
        if n != 1:
            _fail(f"{name}: נמצא {n} פעמים (ציפינו לאחת)")
        out = out.replace(old, new, 1)

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as t:
        t.write(out)
        tmp = t.name
    try:
        py_compile.compile(tmp, doraise=True)
    except py_compile.PyCompileError as e:
        os.unlink(tmp)
        _fail(f"הקוד המתוקן לא מתקמפל: {e}")
    os.unlink(tmp)

    bak = f"{TARGET}.bak-health2-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print("✅ הוחל.")
    print(f"   גיבוי: {os.path.basename(bak)}")
    print()
    print("   הרץ:   systemctl restart zovex-bot")
    print("   נסיגה: python3 fix_pool_health2.py --undo")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
