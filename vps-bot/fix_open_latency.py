#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_open_latency — מעביר את ההשהיה מהצופה אל החיבור.

## הממצא

חציון הפתיחה נמדד 2.31 שניות, ואחרי ריסט 2.08. בקוד:

    STREAM_START_STAGGER = 2.0
    async def _stagger_new_stream():
        async with _stream_start_lock:          # מנעול *גלובלי*
            wait = (_last_stream_start + STREAM_START_STAGGER) - now
            if wait > 0: await asyncio.sleep(wait)

ו-`stream_from_channel` פותחת ב-`await _stagger_new_stream()`. כלומר כל
בקשת /stream ממתינה עד שיעברו שתי שניות מאז הבקשה הקודמת — **של כל
הצופים יחד**, כי המנעול גלובלי.

זה לא קירוב. זה בדיוק המספר שנמדד, וגם דפוס המדידה תואם: פתיחות שנמשכו
0.20, 0.71, 0.79 שניות מתחלפות עם 1.85, 1.94, 1.97, 2.15, 2.33, 2.40 —
בדיוק מה שקורה כשמודדים ברצף מול תור של שתי שניות. פתיחה שארכה 3 שניות
"משלמת" את ההמתנה של הבאה אחריה, ולכן זו יוצאת מיידית.

## למה זה חמור בשיא

ההשהיה **מצטברת**: המנעול גלובלי, ולכן צופה מספר N ממתין 2N שניות. עשרים
צופים שלוחצים פליי באותה דקה — האחרון מחכה 40 שניות. וזה חל על **כל**
בקשת range, לא רק על הראשונה, כי נגן מבקש טווחים לאורך כל הצפייה. זה
מסביר "כל יום שישי" בלי שום קשר לגיל התהליך — וגם למה שרת שאותחל לפני
11 דקות הראה בדיוק אותם 2 שניות.

## למה ההשהיה הוכנסה מלכתחילה, ולמה זה היה המקום הלא נכון

ההערה בקוד מתעדת מדידה אמיתית: "3/4 נכשלים כשמתחילים ביחד, 1/4 כשמפוזרים
ב-4 שניות". הכישלון הזה הוא התנגשות **חיבורים**, לא התנגשות בקשות. מהתיעוד
הרשמי של טלגרם (core.telegram.org/mtproto/mtproto-transports):

    Error 429 "transport flood" — returned when too many transport
    connections are established to the same IP in a too short lapse of time

כלומר המשאב שנגמר הוא קצב פתיחת החיבורים, לא קצב הבקשות. ההשהיה הוצבה על
הצופה, בעוד שהחנק האמיתי הוא על הסוקט. לכן היא גם עזרה וגם עלתה יקר:
בקשה שנופלת על בריכה חמה לא פותחת שום חיבור, ובכל זאת שילמה שתי שניות.

## מה מייצר את ההצפה

`_prewarm_dc` יורה `asyncio.gather` על 8 בוטים בבת אחת, וכל אחד בונה עד
STREAM_MEDIA_CONNS (4) חיבורים: **32 חיבורי TCP במקביל**, לכל DC, כל 20
שניות. זו בדיוק הצורה שטלגרם מגדיר כ-transport flood.

ואז מגיע החלק שהופך את זה ללולאה: ב-pyrogram, חבילה באורך 4 בתים היא
שגיאת transport. ה-recv_worker קורא את הקוד, רושם אזהרה, ומפעיל
`self.restart()` — **בלי שום backoff**; restart הוא stop ואז start מיד,
ו-start מנסה בלולאה. כלומר טלגרם אומר "יותר מדי חיבורים", ו-pyrogram עונה
בפתיחת חיבורים נוספים. זה מה שנמדד ביומן: 250 "Connecting" ב-7 שניות.

## התיקון

  1. **חנק על פתיחת חיבורים** — מרווח מזערי בין יצירת סשנים (0.2ש, כלומר
     עד 5 בשנייה). זה מטפל בדיוק במה שטלגרם מגביל, ובמקום שבו זה קורה.
     חימום של 32 חיבורים לוקח 6.4 שניות ברקע, ואף צופה לא ממתין לו.
  2. **ההשהיה על הצופה יורדת** מ-2.0 ל-0.25 שניות. היא כבר לא צריכה להגן
     על החיבורים — סעיף 1 עושה את זה במקום הנכון — ומה שנשאר הוא רק פיזור
     קל. חציון הפתיחה אמור לרדת מ~2.1 שניות לפחות מחצי שנייה.
  3. **החימום המקדים יורד** מ-8 בוטים ל-3. 8 היה מייצר 32 חיבורים מקבילים
     כל 20 שניות; 3 מייצר 12, והחנק מפזר גם אותם.

הסדר חשוב: בלי (1), הורדת ההשהיה ב-(2) הייתה מחזירה את התנגשות החיבורים
שבגללה היא הוכנסה מלכתחילה.

    python3 fix_open_latency.py --check
    python3 fix_open_latency.py
    python3 fix_open_latency.py --revert
ואחריו:  systemctl restart zovex-bot
"""
import argparse, ast, os, shutil, sys
from pathlib import Path

MAIN = Path(os.environ.get("ZOVEX_MAIN", "/opt/zovex-bot/main.py"))
BAK = MAIN.with_name(MAIN.name + ".bak_openlat")
MARK = "_conn_throttle"

OLD_STAGGER = 'STREAM_START_STAGGER = float(os.environ.get("STREAM_START_STAGGER", "2.0"))\n'
NEW_STAGGER = '''# היה 2.0. ראה fix_open_latency.py: המנעול גלובלי, ולכן זו הייתה השהיה
# מצטברת על *כל* הצופים יחד — צופה מספר N המתין 2N שניות, וזה נמדד
# כחציון פתיחה של 2.1 שניות. ההגנה על החיבורים עברה ל-_conn_throttle,
# שחונק את מה שטלגרם באמת מגביל (קצב פתיחת חיבורים), ולכן כאן נשאר רק
# פיזור קל.
STREAM_START_STAGGER = float(os.environ.get("STREAM_START_STAGGER", "0.25"))
'''

OLD_PREWARM = 'PREWARM_BOTS = int(os.environ.get("STREAM_PREWARM_BOTS", "8"))\n'
NEW_PREWARM = '''# היה 8. _prewarm_dc יורה gather על כל הבוטים האלה יחד, וכל אחד בונה עד
# STREAM_MEDIA_CONNS חיבורים — כלומר 8×4=32 חיבורי TCP במקביל לכל DC כל
# 20 שניות. זו בדיוק הצורה שטלגרם מגדיר כ-transport flood.
PREWARM_BOTS = int(os.environ.get("STREAM_PREWARM_BOTS", "3"))
'''

OLD_MAKE = '''async def _make_media_session(client, dc_id: int, _retry: bool = True):
    """חיבור media לאותו לקוח, עם מפתח שמור במקום DH בכל פעם."""
    test_mode = await client.storage.test_mode()
'''

NEW_MAKE = '''# ── חנק על *פתיחת* חיבורים ───────────────────────────────────────────────────
# מהתיעוד של טלגרם (core.telegram.org/mtproto/mtproto-transports):
#   Error 429 "transport flood" — too many transport connections are
#   established to the same IP in a too short lapse of time
#
# זה המשאב שנגמר, ולכן זה המקום לחנוק. ב-pyrogram חבילה של 4 בתים היא
# שגיאת transport: ה-recv_worker רושם אזהרה ומפעיל restart() בלי שום
# backoff, כלומר עונה ל"יותר מדי חיבורים" בפתיחת עוד חיבורים. נמדד ביומן
# שלנו: 250 "Connecting" ב-7 שניות.
#
# מרווח מזערי בין יצירות מגביל את הקצב מהצד שלנו. 0.2ש = עד 5 בשנייה;
# חימום של 32 חיבורים לוקח 6.4 שניות ברקע, ואף צופה לא ממתין לו.
_conn_gate_lock = None
_last_conn_at = 0.0
MEDIA_CONN_MIN_GAP = float(os.environ.get("MEDIA_CONN_MIN_GAP", "0.2"))


async def _conn_throttle():
    global _last_conn_at, _conn_gate_lock
    if _conn_gate_lock is None:              # נוצר עצלנית: אין loop בזמן import
        _conn_gate_lock = asyncio.Lock()
    async with _conn_gate_lock:
        _wait = (_last_conn_at + MEDIA_CONN_MIN_GAP) - time.time()
        if _wait > 0:
            await asyncio.sleep(_wait)
        _last_conn_at = time.time()


async def _make_media_session(client, dc_id: int, _retry: bool = True):
    """חיבור media לאותו לקוח, עם מפתח שמור במקום DH בכל פעם."""
    await _conn_throttle()
    test_mode = await client.storage.test_mode()
'''


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def validate(src: str, patched: bool = True) -> None:
    compile(src, str(MAIN), "exec")
    names = [n.name for n in ast.walk(ast.parse(src))
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for fn in ("_make_media_session", "_stagger_new_stream", "_prewarm_dc"):
        if fn not in names:
            sys.exit(f"אימות נכשל: {fn} נעלמה — לא כותב.")
    if not patched:
        return
    if "_conn_throttle" not in names:
        sys.exit("אימות נכשל: _conn_throttle לא נוצרה — לא כותב.")
    # החנק חייב להיות *בתוך* הפונקציה שיוצרת חיבורים, אחרת הוא מעולם לא רץ
    if "await _conn_throttle()" not in src:
        sys.exit("אימות נכשל: החנק לא נקרא — לא כותב.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    if not MAIN.exists():
        sys.exit(f"לא נמצא {MAIN}. הגדר ZOVEX_MAIN אם הנתיב שונה.")
    src = MAIN.read_text(encoding="utf-8")

    if a.revert:
        if not BAK.exists():
            sys.exit(f"אין גיבוי ב-{BAK}")
        orig = BAK.read_text(encoding="utf-8")
        validate(orig, patched=False)
        atomic_write(MAIN, orig)
        print(f"✓ שוחזר מ-{BAK} (בית-בית)")
        print("  הרץ: systemctl restart zovex-bot")
        return

    if MARK in src:
        print("כבר מותקן. אין מה לעשות.")
        return

    for label, old in (("STREAM_START_STAGGER", OLD_STAGGER),
                       ("PREWARM_BOTS", OLD_PREWARM),
                       ("_make_media_session", OLD_MAKE)):
        n = src.count(old)
        if n != 1:
            sys.exit(f"העוגן '{label}' נמצא {n} פעמים (ציפיתי 1) — "
                     "הקוד בשרת שונה ממה שציפיתי. לא כותב.")

    new = (src.replace(OLD_STAGGER, NEW_STAGGER, 1)
              .replace(OLD_PREWARM, NEW_PREWARM, 1)
              .replace(OLD_MAKE, NEW_MAKE, 1))
    validate(new)

    print("1. חנק על פתיחת חיבורים: מרווח 0.2ש (עד 5 בשנייה)")
    print("2. השהיית פתיחת זרם: 2.0ש → 0.25ש  ← זה מה שהצופה מרגיש")
    print("3. חימום מקדים: 8 בוטים → 3  (32 חיבורים מקבילים → 12)")
    print()
    print("נמדד לפני: חציון פתיחה 2.08-2.31 שניות")
    print("צפוי אחרי: מתחת לחצי שנייה")
    if a.check:
        print("--check: שום דבר לא נכתב. היעד:", MAIN)
        return

    shutil.copy2(MAIN, BAK)
    atomic_write(MAIN, new)
    if MARK not in MAIN.read_text(encoding="utf-8"):
        shutil.copy2(BAK, MAIN)
        sys.exit("הכתיבה לא אומתה — שוחזר.")
    print(f"✓ הוחל · גיבוי: {BAK}")
    print("  הרץ עכשיו: systemctl restart zovex-bot")
    print("  לביטול:    python3 fix_open_latency.py --revert")
    print()
    print("  לאימות:  python3 catch_slow_open.py --n 20 --slow 3")


if __name__ == "__main__":
    main()
