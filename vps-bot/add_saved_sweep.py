#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מוסיף ניקוי עצמאי ותקופתי לתיקיית saved_uploads, בלי לחכות להעלאה הבאה.

## מה נמצא בפועל

ב-saved_uploads היו שני קבצים בני ~4GB (apparent size — du הראה 193M בפועל,
קבצים דלילים) לאותו סרטון (VN20260905_231907.mp4), שני job_id שונים, ~6
דקות בין הניסיונות. שניהם שאריות של קליטה שנתקעה: `async for chunk in
request.stream()` ב-/panel/saved-upload אין לו שום timeout, ואם החיבור
מהטלפון נופל באמצע בלי לזרוק שגיאה - הבקשה פשוט תלויה, ה-except/finally
הקיימים לא מופעלים לעולם, והקובץ נשאר.

הניקוי היחיד שקיים (SAVED_STALE_SEC) רץ רק בתוך /panel/saved-upload עצמו,
כלומר רק כשמישהו מעלה קובץ *חדש*. בלי העלאה נוספת - שריד יושב לנצח.

## מה לא מתקן כאן, ולמה

לתקן את הקבלה עצמה (timeout על request.stream()) דורש לגעת ב-route הקיים
/panel/saved-upload. route רשום ב-FastAPI לא נדרס כמו פונקציה רגילה -
declare מחדש עם אותו path רק מוסיף route שני ומת, הראשון עדיין קודם בתור.
זה משאיר את הבעיה השורשית (בקשה תקועה יכולה עדיין להשאיר קובץ פתוח וחצי-
כתוב עד שמישהו יסגור אותה), אבל התיקון כאן מבטיח שהשאריות *לא נשארות
לנצח* בלי קשר להעלאה הבאה.

## מה זה כן מתקן

דורס את reap_idle_sessions (פונקציה רגילה - דריסה בטוחה, פייתון מחפש שם
גלובלי בזמן הקריאה) כך שהיא ממשיכה לעשות בדיוק מה שהיא עושה היום (ניקוי
STREAM_SESSIONS כל 30 שניות), וגם - פעם ב-~30 דקות - סורקת את
saved_uploads ומוחקת קבצים ישנים מ-SAVED_STALE_SEC, ומנקה רשומות ב-
_saved_jobs שנתקעו בלי done_at מעבר לאותו סף.

    python3 add_saved_sweep.py --check
    python3 add_saved_sweep.py && systemctl restart zovex-bot
    python3 add_saved_sweep.py --undo
"""
import datetime, glob, os, pathlib, py_compile, shutil, sys, tempfile

TARGET = pathlib.Path("/opt/zovex-bot/main.py")
DONE_MARK = "_SAVED_SWEEP_INSTALLED"

NEEDED = [
    "async def reap_idle_sessions():",
    "STREAM_SESSIONS_LOCK",
    "SESSION_IDLE_SECS",
    "SAVED_TMP_DIR",
    "SAVED_STALE_SEC",
    "_saved_jobs: dict = {}",
]

BLOCK = r'''

# ── ניקוי עצמאי של saved_uploads, לא תלוי בהעלאה הבאה ───────────────────────
# נמצאו בפועל שני קבצים ~4GB (דלילים) מהעלאה שנתקעה - request.stream() בלי
# timeout, שאריה נשארת עד שמישהו מעלה קובץ חדש (הניקוי היחיד היה בתוך
# /panel/saved-upload עצמו). דורסים את reap_idle_sessions (פונקציה רגילה,
# לא route - דריסה בטוחה) כדי שסבב שכבר רץ כל 30 שניות ינקה גם את זה,
# פעם ב-~30 דקות, בלי לחכות להעלאה הבאה.
_SAVED_SWEEP_INSTALLED = True
_saved_sweep_counter = 0
SAVED_SWEEP_EVERY = 60  # כל 60 סבבים של 30ש' = פעם ב-30 דקות בערך


def _saved_sweep_once():
    now = time.time()
    try:
        for old in SAVED_TMP_DIR.glob("*"):
            try:
                if now - old.stat().st_mtime > SAVED_STALE_SEC:
                    old.unlink()
                    log.info("saved_uploads: נמחקה שארית ישנה: %s", old.name)
            except Exception:
                pass
    except Exception:
        pass
    for k in [k for k, v in _saved_jobs.items()
              if not v.get("done_at") and now - v.get("started", now) > SAVED_STALE_SEC]:
        _saved_jobs.pop(k, None)


async def reap_idle_sessions():
    """מנקה sessions שלא נעשה בהם שימוש זמן מה, כדי לא לצבור זיכרון/חיבורים.
    כולל גם סריקת saved_uploads פעם ב-SAVED_SWEEP_EVERY סבבים."""
    global _saved_sweep_counter
    while True:
        await asyncio.sleep(30)
        now = time.time()
        async with STREAM_SESSIONS_LOCK:
            dead = [k for k, s in STREAM_SESSIONS.items() if now - s.last_used > SESSION_IDLE_SECS]
            for k in dead:
                del STREAM_SESSIONS[k]
        _saved_sweep_counter += 1
        if _saved_sweep_counter >= SAVED_SWEEP_EVERY:
            _saved_sweep_counter = 0
            _saved_sweep_once()
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

    if src.count("async def reap_idle_sessions") != 1:
        _fail(f"reap_idle_sessions מוגדרת {src.count('async def reap_idle_sessions')} פעמים — ציפינו לאחת")

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

    bak = f"{TARGET}.bak-savedsweep-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print("✅ הוחל. saved_uploads יינוקה עצמאית כל ~30 דקות (שום שורה קיימת לא שונתה).")
    print(f"   גיבוי: {os.path.basename(bak)}")
    print()
    print("   הרץ:   systemctl restart zovex-bot")
    print("   נסיגה: python3 add_saved_sweep.py --undo")


def undo():
    baks = sorted(glob.glob(str(TARGET) + ".bak-savedsweep-*"))
    if not baks:
        _fail("לא נמצא גיבוי")
    shutil.copy2(baks[-1], TARGET)
    print(f"↩️  שוחזר מ-{os.path.basename(baks[-1])}")
    print("   הרץ:  systemctl restart zovex-bot")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
