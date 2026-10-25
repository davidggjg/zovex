#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# מהיר כל היום, נתקע אחרי 21:00.
#
# ## הדפוס מצביע על מקביליות
#
# תקיעה שמופיעה רק בשעת שיא אינה תכונה של קובץ ואינה חנק מצד טלגרם —
# שניהם היו מופיעים גם בצהריים. היא תכונה של משהו שגדל עם מספר הצופים.
#
# ## מה שנמצא בקוד
#
#     asyncio.create_task(_edge_fill(...))
#
# ‎_edge_filling‎ מונע רק כפילות של *אותו* קובץ. אין שום תקרה על כמה
# מילויים רצים יחד. כל צופה שפותח קובץ שאינו במטמון מתחיל משיכה של 6MB
# ברקע; בצהריים זה אחד-שניים, אחרי 21:00 זה עשרות במקביל.
#
# ## למה זה מרעיב דווקא את מי שצופה
#
# מהתיעוד הרשמי של טלגרם: בקשת ‎upload.getFile‎ מוגבלת ל-1MB, ולכן הקצב
# לחיבור נקבע לפי **השהיית הבקשה** ולא לפי רוחב פס. כשעשרות מילויי רקע
# ממלאים את אותם חיבורים, ההשהיה של כל בקשה גדלה, והקצב לצופה יורד מתחת
# לקצב הווידאו. זו התקיעה.
#
# מילוי רקע אינו דחוף: אף אחד לא ממתין לו. צופה כן.
#
# ## התיקון
#
# תקרה גלובלית. מעבר לה המילוי **נזרק ולא מתור** — מילוי שממתין בתור
# בשעת שיא יתחיל בדיוק כשהעומס בשיאו, וממילא המחמם ממלא את המטמון בשעות
# השקטות. מונה פשוט ולא Semaphore: asyncio חד-חוטי, ו-Semaphore ברמת
# המודול נקשר ללופ שאולי עוד לא קיים (אותה מלכודת שכבר מתועדת כאן
# ב-_vf_encode_sem).
#
# ‎edge_fill_dropped‎ נחשף ב-/debug/caches: אם הוא גדל בשעת שיא, זו הוכחה
# שהתקרה אכן נוגעת — וזו המדידה שחיפשנו, בלי להריץ שום בודק.
#
#   python3 patch_edge_cap.py [נתיב ל-main.py]
#   python3 patch_edge_cap.py --revert
# ─────────────────────────────────────────────────────────────────────────────
import io
import os
import py_compile
import shutil
import sys
import time

P = "/opt/zovex-bot/main.py"
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if args:
    P = args[0]
REVERT = "--revert" in sys.argv
MARK = "edge_fill_cap"

OLD_DECL = '''_edge_filling: set = set()'''
NEW_DECL = '''_edge_filling: set = set()

# [edge_fill_cap] תקרה למילויי רקע מקבילים.
#
# בלעדיה כל צופה שפתח קובץ שאינו במטמון התחיל משיכת רקע של 6MB, וכולן
# התחרו על אותם חיבורים מול טלגרם. בקשת upload.getFile מוגבלת ל-1MB
# ולכן הקצב לחיבור נקבע לפי השהיית הבקשה; עשרות מילויים מאריכים את
# ההשהיה ומורידים את הקצב לצופה מתחת לקצב הווידאו. זו התקיעה שמופיעה
# רק בשעת שיא.
#
# מונה ולא Semaphore: asyncio חד-חוטי, ולכן ++/-- כאן בטוחים לחלוטין,
# ו-Semaphore ברמת המודול נקשר ללופ שאולי עוד לא קיים.
EDGE_FILL_MAX = int(os.environ.get("EDGE_FILL_MAX", "3"))
_edge_fill_active = 0
_edge_fill_dropped = 0'''

OLD_GUARD = '''    key = (chat_id, message_id, which)
    if key in _edge_filling:
        return
    _edge_filling.add(key)'''
NEW_GUARD = '''    global _edge_fill_active, _edge_fill_dropped
    key = (chat_id, message_id, which)
    if key in _edge_filling:
        return
    # [edge_fill_cap] נזרק ולא מתור.
    #
    # מילוי שממתין בתור יתחיל בדיוק כשהעומס בשיאו — כלומר יזיק פעמיים.
    # אף אחד לא ממתין למילוי רקע; המחמם ממלא את המטמון בשעות השקטות,
    # ובקשה חוזרת לאותו קובץ תנסה שוב ממילא.
    if _edge_fill_active >= EDGE_FILL_MAX:
        _edge_fill_dropped += 1
        return
    _edge_filling.add(key)
    _edge_fill_active += 1'''

OLD_FIN = '''    finally:
        _edge_filling.discard(key)


def _channel_range_gen(chat_id, message_id, start, end):'''
NEW_FIN = '''    finally:
        _edge_filling.discard(key)
        _edge_fill_active -= 1


def _channel_range_gen(chat_id, message_id, start, end):'''

OLD_DBG = '''        "edge_filling": len(_edge_filling),'''
NEW_DBG = '''        "edge_filling": len(_edge_filling),
        # [edge_fill_cap] אם dropped גדל בשעת שיא, התקרה נוגעת בפועל —
        # כלומר המילויים באמת התחרו על החיבורים עם הצופים.
        "edge_fill_active": _edge_fill_active,
        "edge_fill_dropped": _edge_fill_dropped,
        "edge_fill_max": EDGE_FILL_MAX,'''

PAIRS = [(OLD_DECL, NEW_DECL), (OLD_GUARD, NEW_GUARD),
         (OLD_FIN, NEW_FIN), (OLD_DBG, NEW_DBG)]


def main():
    d = os.path.dirname(P) or "."
    if REVERT:
        bak = sorted((f for f in os.listdir(d)
                      if f.startswith("main_before_edgecap_")), reverse=True)
        if not bak:
            sys.exit("❌ אין גיבוי לשחזר")
        shutil.copy(os.path.join(d, bak[0]), P)
        print(f"✓ שוחזר מ-{bak[0]}")
        return

    try:
        s = io.open(P, encoding="utf-8").read()
    except OSError as e:
        sys.exit(f"❌ לא נפתח {P}: {e}")

    if MARK in s:
        print("✓ כבר מתוקן — מדלג")
        return

    for i, (old, _) in enumerate(PAIRS, 1):
        n = s.count(old)
        if n != 1:
            sys.exit(f"❌ קטע {i} מתוך {len(PAIRS)} לא נמצא בדיוק פעם אחת "
                     f"({n}). לא נגעתי בכלום — שלח לי את הפלט.")

    bak = f"{d}/main_before_edgecap_{time.strftime('%Y%m%d-%H%M%S')}.py"
    shutil.copy(P, bak)
    out = s
    for old, new in PAIRS:
        out = out.replace(old, new, 1)
    io.open(P, "w", encoding="utf-8").write(out)

    try:
        py_compile.compile(P, doraise=True)
    except Exception as e:
        shutil.copy(bak, P)
        sys.exit(f"❌ לא עובר קומפילציה — שוחזר.\n   {e}")

    print(f"✓ הוחל. גיבוי: {bak}")
    print("  תקרה: EDGE_FILL_MAX (ברירת מחדל 3)")
    print("  מונה הזריקות נחשף ב-/debug/caches")


if __name__ == "__main__":
    main()
