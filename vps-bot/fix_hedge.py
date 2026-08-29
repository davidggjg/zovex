#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
תיקון: בקשה מגודרת (hedged request) לחלונות הזרמה.

הבעיה שנמדדה
------------
זמני משיכת חלון מתפלגים לשתי קבוצות בלבד — מהיר (0.1-1.0ש', 4-10 MB/s)
או תקוע (10ש', 34ש', ואף 130ש'). אין ביניים. גם כשהמערכת בריאה לגמרי,
קפיצה בודדת מספיקה כדי לרוקן את הבאפר של הנגן ולעצור את הסרט.

מקור ההגברה נמצא ב-_fetch_window:

    fast = await _media_bands_fetch(chat_id, message_id, wstart, wend)
    if fast is not None:
        return fast
    # ...נפילה למסלול הבוטים הוותיק

ניסיון מהיר *אחד*. אם הוא מאחר — אין רשת ביניים, ונופלים ישר למסלול
הוותיק שתולה SUBRANGE_TIMEOUT (25ש') לכל בוט עד שהוא מוותר. כך עיכוב
רגעי אחד בבקשה לטלגרם (נמדדו 239 "Retrying" בעשר דקות) הופך לעשרות
שניות של תקיעה מול הצופה.

התיקון
------
במקום להמתין לניסיון שאולי ייכשל — משגרים ניסיון נוסף לבוט אחר אחרי
המתנה קצרה, ולוקחים את הראשון שמצליח. טכניקה סטנדרטית נגד "זנב" של
השהיות: הבוט האיטי כבר לא קובע כמה הצופה מחכה.

    לפני:  בוט איטי → תלוי עד שנכשל → מסלול ותיק → 25ש' לכל בוט
    אחרי:  בוט איטי → 4ש' → בוט נוסף במקביל → מי שענה ראשון מנצח

עלות: כשהמערכת מהירה — אפס. הניסיון הראשון חוזר תוך פחות משנייה, ואף
בקשה נוספת לא נשלחת. הגידור מתעורר רק כשמשהו באמת נתקע.

בטיחות
------
מגבה לפני שינוי · בודק תחביר על עותק זמני *לפני* שנוגע בקובץ החי ·
משחזר אוטומטית אם משהו השתבש · idempotent · --undo מחזיר מיד.

    python3 fix_hedge.py            # מחיל
    python3 fix_hedge.py --check    # בודק התאמה בלי לשנות
    python3 fix_hedge.py --undo     # מחזיר מהגיבוי
"""
import py_compile, shutil, sys, tempfile
from datetime import datetime
from pathlib import Path

MAIN = Path("/opt/zovex-bot/main.py")

# העוגן לקבועים — אחרי ההגדרה של SUBRANGE_TIMEOUT
CONST_ANCHOR = "STREAM_SUBRANGE_TIMEOUT"

CONSTS = '''
# ── בקשה מגודרת (hedge) ─────────────────────────────────────────────────
# כמה שניות ממתינים לניסיון לפני שמשגרים עוד אחד לבוט אחר. קצר בכוונה:
# המטרה אינה לחכות לכשל אלא לעקוף אותו. 0 מכבה את הגידור לגמרי.
MEDIA_HEDGE_DELAY = float(os.environ.get("STREAM_HEDGE_DELAY", "4"))
# מקסימום ניסיונות מקבילים לאותו חלון (כולל הראשון).
MEDIA_HEDGE_TRIES = int(os.environ.get("STREAM_HEDGE_TRIES", "3"))
'''

# שלוש השורות שמוחלפות ב-_fetch_window
L1 = "fast = await _media_bands_fetch(chat_id, message_id, wstart, wend)"
L2 = "if fast is not None:"
L3 = "return fast"

BODY = '''# ניסיונות מגודרים: מתחילים באחד, וכל MEDIA_HEDGE_DELAY שניות שבהן
# איש לא חזר — משגרים עוד אחד לבוט אחר. הראשון שמצליח מנצח והשאר
# מבוטלים. כך בוט איטי בודד לא קובע כמה הצופה מחכה, ולא נופלים
# למסלול הוותיק (שתולה SUBRANGE_TIMEOUT שניות לכל בוט) על כל עיכוב.
_hedge_tasks, _hedge_n = set(), 0
try:
    while True:
        if _hedge_n < MEDIA_HEDGE_TRIES:
            _hedge_tasks.add(asyncio.create_task(
                _media_bands_fetch(chat_id, message_id, wstart, wend)))
            _hedge_n += 1
        if not _hedge_tasks:
            break
        # עוד יש ניסיונות במלאי → ממתינים קצר ומשגרים עוד אחד.
        # נגמרו → ממתינים עד שמישהו יחזור.
        _hedge_wait = MEDIA_HEDGE_DELAY if (
            _hedge_n < MEDIA_HEDGE_TRIES and MEDIA_HEDGE_DELAY > 0) else None
        _hedge_done, _hedge_tasks = await asyncio.wait(
            _hedge_tasks, timeout=_hedge_wait,
            return_when=asyncio.FIRST_COMPLETED)
        for _d in _hedge_done:
            try:
                fast = _d.result()
            except Exception:
                fast = None
            if fast is not None:
                return fast
        if not _hedge_done and _hedge_n >= MEDIA_HEDGE_TRIES:
            break
finally:
    # מבטלים ניסיונות שנותרו — כולל כשיצאנו ב-return עם מנצח.
    for _t in _hedge_tasks:
        _t.cancel()
        _t.add_done_callback(lambda x: x.cancelled() or x.exception())
'''


def locate(lines):
    """מוצא את שלוש השורות להחלפה. מחזיר (אינדקס, הזחה) או (None, סיבה)."""
    hits = [i for i, l in enumerate(lines) if l.strip() == L1]
    if len(hits) != 1:
        return None, f"השורה '{L1[:40]}...' נמצאה {len(hits)} פעמים (צריך 1)"
    i = hits[0]
    if i + 2 >= len(lines):
        return None, "הקובץ נגמר מוקדם מהצפוי"
    if lines[i + 1].strip() != L2 or lines[i + 2].strip() != L3:
        return None, (f"המבנה שונה מהצפוי בשורה {i+2}:\n"
                      f"  {lines[i+1].strip()!r}\n  {lines[i+2].strip()!r}")
    return i, len(lines[i]) - len(lines[i].lstrip())


def build(text):
    if "MEDIA_HEDGE_DELAY" in text:
        return None, "כבר מוחל"
    lines = text.split("\n")
    i, info = locate(lines)
    if i is None:
        return None, info
    indent = " " * info

    # הקבועים — אחרי השורה שמגדירה את SUBRANGE_TIMEOUT
    c_hits = [k for k, l in enumerate(lines) if CONST_ANCHOR in l and "=" in l]
    if len(c_hits) != 1:
        return None, f"עוגן הקבועים נמצא {len(c_hits)} פעמים (צריך 1)"

    body = "\n".join((indent + ln) if ln.strip() else ""
                     for ln in BODY.rstrip("\n").split("\n"))
    lines[i:i + 3] = body.split("\n")

    # מוסיפים את הקבועים אחרי ההחלפה, כדי שהאינדקס לא יזוז אם הוא קטן יותר
    c = c_hits[0] if c_hits[0] < i else c_hits[0] + len(body.split("\n")) - 3
    lines[c + 1:c + 1] = CONSTS.strip("\n").split("\n")
    return "\n".join(lines), None


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
    patched, err = build(original)
    if patched is None:
        print(("✓ " if err == "כבר מוחל" else "✗ ") + err)
        return 0 if err == "כבר מוחל" else 1

    # תחביר נבדק על עותק זמני לפני שנוגעים בקובץ החי
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

    if "--check" in sys.argv:
        print("✓ הפאץ' מתאים לקובץ ועובר קומפילציה. לא שונה כלום (--check).")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = MAIN.with_name(f"main.py.bak-hedge-{stamp}")
    shutil.copy2(MAIN, bak)
    MAIN.write_text(patched, encoding="utf-8")
    try:
        py_compile.compile(str(MAIN), doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak, MAIN)
        print("שגיאה אחרי הכתיבה — הגיבוי שוחזר:\n", e, file=sys.stderr)
        return 1

    print("גיבוי:", bak.name)
    print("✓ הוחל: בקשה מגודרת, 4 שניות, עד 3 ניסיונות מקבילים.")
    print("\nהפעל מחדש:  systemctl restart zovex-bot")
    print("ביטול:      python3 fix_hedge.py --undo && systemctl restart zovex-bot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
