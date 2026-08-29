#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
תיקון: בקשה מגודרת (hedged request) לחלונות הזרמה.

הבעיה שנמדדה
------------
זמני משיכת חלון התפלגו לשתי קבוצות בלבד — מהיר (0.6-13ש') או תקוע
(44-132ש'). אין ביניים. מקור ההגברה הוא הטיפול בכשל:

    parts = await asyncio.wait_for(gather(*bands), timeout=budget)

כשרצועה *אחת* מאחרת, כל החלון נזרק — כולל הרצועות שכבר הצליחו — ואז
מנסים את החלון כולו מחדש על בוט אחר, ורק אחרי MEDIA_BANDS_TRIES ניסיונות
יורדים למסלול הוותיק שתולה SUBRANGE_TIMEOUT (25ש') לכל בוט:

    3 × 9ש' (מסלול מהיר) + 4 × 25ש' (מסלול ותיק) ≈ 127ש'

וזה בדיוק מה שנמדד: 132, 125, 112. עיכוב רגעי של ~10ש' בבקשה בודדת
לטלגרם (651 "Retrying upload.GetFile" בשעה) מתנפח לתקיעה של שתי דקות.

התיקון
------
במקום להמתין לניסיון שייכשל עד הסוף ורק אז להתחיל את הבא — משגרים ניסיון
נוסף על בוט אחר אחרי המתנה קצרה, ולוקחים את הראשון שמצליח. זו טכניקה
סטנדרטית נגד "זנב" של השהיות: הבוט האיטי כבר לא קובע את זמן ההמתנה.

    לפני:  בוט איטי → 9ש' → בוט → 9ש' → בוט → 9ש' → מסלול ותיק → 100ש'
    אחרי:  בוט איטי → 4ש' → בוט נוסף במקביל → מי שענה ראשון מנצח

עלות: כשהמערכת מהירה — אפס (הניסיון הראשון חוזר לפני ההמתנה, ואף בקשה
נוספת לא נשלחת). כשהיא איטית — פי 2-3 משיכות לאותו חלון, בדיוק ברגע
שבו הצופה עומד להיתקע. זו עסקה טובה.

הרצה על השרת:
    python3 fix_hedge.py            # מחיל
    python3 fix_hedge.py --undo     # מחזיר מהגיבוי
"""
import hashlib, py_compile, shutil, subprocess, sys, tempfile
from datetime import datetime
from pathlib import Path

MAIN = Path("/opt/zovex-bot/main.py")

ANCHOR_TRIES = 'MEDIA_BANDS_TRIES = int(os.environ.get("STREAM_BANDS_TRIES", "3"))'

NEW_TRIES = ANCHOR_TRIES + '''
# השהיה לפני שיגור ניסיון מקביל לבוט אחר על אותו חלון. קצר מהתקציב של רצועה
# בכוונה: המטרה היא לא לחכות לכשל אלא לעקוף אותו. 0 מכבה את הגידור.
MEDIA_HEDGE_DELAY = float(os.environ.get("STREAM_HEDGE_DELAY", "4"))'''

ANCHOR_LOOP = '''        tried = set()
        for _ in range(max(1, MEDIA_BANDS_TRIES)):
            fast = await _media_bands_fetch(chat_id, message_id, wstart, wend, tried)
            if fast is not None:
                return fast
'''

NEW_LOOP = '''        tried = set()
        # ניסיונות מגודרים: מתחילים באחד, וכל MEDIA_HEDGE_DELAY שניות שבהן
        # אף אחד לא חזר — משגרים עוד אחד לבוט אחר. הראשון שמצליח מנצח,
        # והשאר מבוטלים. כך בוט איטי בודד לא קובע את זמן ההמתנה של הצופה.
        # ה-set המשותף tried דואג שכל ניסיון ייפול על בוט אחר.
        tasks, launched = set(), 0
        max_tries = max(1, MEDIA_BANDS_TRIES)
        try:
            while True:
                if launched < max_tries:
                    tasks.add(asyncio.create_task(_media_bands_fetch(
                        chat_id, message_id, wstart, wend, tried)))
                    launched += 1
                if not tasks:
                    break
                # עוד יש ניסיונות במלאי → ממתינים קצר ומשגרים עוד אחד.
                # נגמרו → ממתינים עד שמישהו יחזור.
                wait_for = MEDIA_HEDGE_DELAY if (
                    launched < max_tries and MEDIA_HEDGE_DELAY > 0) else None
                done, tasks = await asyncio.wait(
                    tasks, timeout=wait_for,
                    return_when=asyncio.FIRST_COMPLETED)
                for d in done:
                    try:
                        fast = d.result()
                    except Exception:
                        fast = None
                    if fast is not None:
                        return fast
                if not done and launched >= max_tries:
                    break
        finally:
            # מבטלים ניסיונות שנותרו — כולל כשיצאנו ב-return עם מנצח.
            for t in tasks:
                t.cancel()
                t.add_done_callback(lambda x: x.cancelled() or x.exception())
'''


def apply(text):
    if "MEDIA_HEDGE_DELAY" in text:
        return None, "כבר מוחל"
    for name, anchor in (("MEDIA_BANDS_TRIES", ANCHOR_TRIES),
                         ("_fetch_window", ANCHOR_LOOP)):
        if text.count(anchor) != 1:
            return None, f"עוגן '{name}' נמצא {text.count(anchor)} פעמים — עוצר"
    text = text.replace(ANCHOR_TRIES, NEW_TRIES, 1)
    text = text.replace(ANCHOR_LOOP, NEW_LOOP, 1)
    return text, None


def newest_backup():
    b = sorted(MAIN.parent.glob("main.py.bak-hedge-*"))
    return b[-1] if b else None


def main():
    if not MAIN.exists():
        print("לא נמצא", MAIN, file=sys.stderr)
        return 1

    if "--undo" in sys.argv:
        bak = newest_backup()
        if not bak:
            print("אין גיבוי לשחזור", file=sys.stderr)
            return 1
        shutil.copy2(bak, MAIN)
        print("שוחזר מ:", bak.name)
        print("הפעל מחדש:  systemctl restart zovex-bot")
        return 0

    original = MAIN.read_text(encoding="utf-8")
    patched, err = apply(original)
    if patched is None:
        print(err)
        return 0 if err == "כבר מוחל" else 1

    # בדיקת תקינות תחביר על עותק זמני *לפני* שנוגעים בקובץ החי
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as t:
        t.write(patched)
        tmp = Path(t.name)
    try:
        py_compile.compile(str(tmp), doraise=True)
    except py_compile.PyCompileError as e:
        print("הקוד המתוקן לא עובר קומפילציה — לא שונה כלום:\n", e, file=sys.stderr)
        return 1
    finally:
        tmp.unlink(missing_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = MAIN.with_name(f"main.py.bak-hedge-{stamp}")
    shutil.copy2(MAIN, bak)
    MAIN.write_text(patched, encoding="utf-8")

    try:
        py_compile.compile(str(MAIN), doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak, MAIN)
        print("שגיאה אחרי הכתיבה — שוחזר הגיבוי:\n", e, file=sys.stderr)
        return 1

    print("גיבוי:", bak.name)
    print("הוחל: בקשה מגודרת (hedge) בהשהיה של 4 שניות.")
    print("sha256:", hashlib.sha256(patched.encode()).hexdigest()[:16])
    print("\nהפעל מחדש:  systemctl restart zovex-bot")
    print("ביטול:      python3 fix_hedge.py --undo && systemctl restart zovex-bot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
