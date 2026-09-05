#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
עוטף את asyncio.create_task כדי לעקוב אחרי כל משימת "ירה ותשכח" בקובץ,
ולתקן את הדליפה הידועה שנובעת מכך.

## למה

בקובץ יש 28 קריאות ל-asyncio.create_task. חלק מהן לולאות רקע יחידות שרצות
פעם אחת מההפעלה (pool_health_loop וכו') — לא חשודות. אבל כ-18 מהן הן משימות
חד-פעמיות שנוצרות בכל אירוע/בקשה (_fill_pool_bg, _refresh_pool_bg,
_retire_pool, _prefetch_one לסגמנטים של שידור חי ברמה של פעם בכמה שניות
לכל אחד מ-102 ערוצים, ועוד) — ואף אחת מהן לא שומרת reference שמנוקה כשה-task
מסתיים.

זו תבנית מתועדת: issue פתוח בפרויקט fastmcp (PrefectHQ/fastmcp #1349) מדד
את זה במפורש — "ירה ותשכח" בלי מעקב גורם להצטברות במבני הפנימיים של asyncio
עצמו (לא בקוד שלנו), כ-48 בייט למשימה. זה זעיר לבד, אבל ב-102 ערוצי HLS
שמושכים סגמנט חדש כל כמה שניות זה בקלות מגיע לסדר גודל של מיליון+ משימות
ביום - באותו טווח שבו נמדד שם ~47MB ביום. התיקון שם: לשמור כל task ב-set
ולנקות אותו עם add_done_callback כשהוא מסתיים. אחרי התיקון - אפס הצטברות.

## מה התיקון עושה

עוטף את asyncio.create_task גלובלית (לא נוגע באף אחת מ-28 נקודות הקריאה
עצמן): כל קריאה קיימת ל-asyncio.create_task(...) עוברת דרך העטיפה
אוטומטית, כי פייתון מחפש את asyncio.create_task מחדש בכל קריאה - לא
פעם אחת בזמן import. מוסיף גם /debug/tasks לתצפית.

**הגבלה חשובה:** זה מכסה רק קריאות דרך asyncio.create_task(...) בקובץ הזה.
pyrogram עצמו קורא internally דרך self.loop.create_task(...) (ראינו את זה
ב-session.py) - נתיב קריאה שונה שהעטיפה הזו לא נוגעת בו. זה מתקן את חלקנו
בקובץ, לא את pyrogram.

    python3 add_task_tracking.py --check
    python3 add_task_tracking.py && systemctl restart zovex-bot
    python3 add_task_tracking.py --undo

## איך קוראים את התוצאה

    curl -s http://127.0.0.1:8000/debug/tasks | python3 -m json.tool

`pending_tracked` אמור להישאר קטן (רוב המשימות מסתיימות תוך שניות). `created_total`
הוא מונה מצטבר מאז ההפעלה - משמש להשוואה מול גידול הזיכרון: אם היחס בין
עלייה ב-created_total לעלייה ב-RSS דומה ל-~48 בייט למשימה, זו אישוש ישיר
שזו הייתה הדליפה.
"""
import datetime, glob, os, pathlib, py_compile, shutil, sys, tempfile

TARGET = pathlib.Path("/opt/zovex-bot/main.py")
DONE_MARK = "_TASK_TRACKING_INSTALLED"

NEEDED = ["api = FastAPI", "import asyncio", "asyncio.create_task("]

BLOCK = r'''

# ── מעקב אחרי משימות asyncio "ירה ותשכח" ────────────────────────────────────
# 28 קריאות ל-asyncio.create_task בקובץ, אף אחת לא שומרת/מנקה reference.
# תבנית מתועדת (PrefectHQ/fastmcp #1349): בלי מעקב+add_done_callback,
# asyncio עצמו צובר כ-48 בייט למשימה במבנים הפנימיים שלו, שלא משתחררים
# מיד גם אחרי שהמשימה מסתיימת ונאספת. ב-102 ערוצי HLS עם prefetch כל
# כמה שניות זה מגיע למאות אלפי-מיליוני משימות ביום.
#
# עוטפים את asyncio.create_task גלובלית: פייתון מחפש שמות בזמן הקריאה,
# ולכן כל קריאה קיימת ל-asyncio.create_task(...) עוברת דרך זה אוטומטית,
# בלי לגעת באף אחת מ-28 נקודות הקריאה. לא מכסה קריאות pyrogram פנימיות
# דרך self.loop.create_task(...) - נתיב שונה.
_bg_tasks: set = set()
_bg_tasks_created_total = 0
_TASK_TRACKING_INSTALLED = True

_orig_create_task = asyncio.create_task


def _tracked_create_task(coro, *args, **kwargs):
    global _bg_tasks_created_total
    task = _orig_create_task(coro, *args, **kwargs)
    _bg_tasks.add(task)
    _bg_tasks_created_total += 1
    task.add_done_callback(_bg_tasks.discard)
    return task


asyncio.create_task = _tracked_create_task


@api.get("/debug/tasks")
async def debug_tasks():
    """כמה משימות "ירה ותשכח" ממתינות עכשיו, וכמה נוצרו סה"כ מאז ההפעלה."""
    return {
        "pending_tracked": len(_bg_tasks),
        "created_total": _bg_tasks_created_total,
    }
'''


def _fail(msg):
    print("❌ " + msg)
    print("   לא שונה כלום.")
    sys.exit(1)


def main():
    if not TARGET.exists():
        _fail(f"לא נמצא {TARGET}")
    src = TARGET.read_text(encoding="utf-8")

    if DONE_MARK in src:
        print("✓ כבר מוחל. אין מה לעשות.")
        return

    missing = [n for n in NEEDED if n not in src]
    if missing:
        _fail("חסרים בקובץ שבשרת: " + ", ".join(missing))

    out = src.rstrip("\n") + "\n" + BLOCK

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

    if "--check" in sys.argv:
        print("✓ הפאץ' מתאים לקובץ ועובר קומפילציה. לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-tasktrack-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print("✅ הוחל. נוסף /debug/tasks + עטיפת asyncio.create_task (שום שורה קיימת לא שונתה).")
    print(f"   גיבוי: {os.path.basename(bak)}")
    print()
    print("   הרץ:   systemctl restart zovex-bot")
    print("   בדיקה: curl -s http://127.0.0.1:8000/debug/tasks | python3 -m json.tool")
    print("   נסיגה: python3 add_task_tracking.py --undo")


def undo():
    baks = sorted(glob.glob(str(TARGET) + ".bak-tasktrack-*"))
    if not baks:
        _fail("לא נמצא גיבוי")
    shutil.copy2(baks[-1], TARGET)
    print(f"↩️  שוחזר מ-{os.path.basename(baks[-1])}")
    print("   הרץ:  systemctl restart zovex-bot")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
