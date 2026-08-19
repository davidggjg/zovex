"""טלאי כירורגי ל-main.py החי: מתקן את באג "נתקע אחרי חצי שעה".

הבאג: בריכת חיבורי ה-media שפג תוקפה (MEDIA_SESSION_TTL=1800ש') לא התחדשה
אף פעם במסלול block=False, וכל הזרמה נפלה למסלול הבוט האיטי לצמיתות אחרי
30 דק' → הסרט נתקע ונטען.

הטלאי נוגע *רק* בקטע הזה — לא דורס את כל הקובץ, כדי לשמור תיקונים ידניים
שכבר יש ב-main.py החי. מגבה, מחיל, בודק קומפילציה, ומשחזר אם משהו נכשל.

    /opt/zovex-bot/venv/bin/python3 patch_media_pool.py           # דו"ח בלבד
    /opt/zovex-bot/venv/bin/python3 patch_media_pool.py --apply   # מחיל
"""
import argparse
import py_compile
import shutil
import sys
import time
from pathlib import Path

TARGET = Path("/opt/zovex-bot/main.py")

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

OLD_BLOCK = '''    if not block:
        ent = _media_sessions.get(key)
        if ent is not None and (now - ent["born"]) <= MEDIA_SESSION_TTL \\
                and len(ent["pool"]) >= n:
            return ent["pool"][:n], ent["gen"]
        if key not in _media_building:
            _media_building.add(key)
            asyncio.create_task(_fill_pool_bg(client, owner, dc_id, n))
        return [], None'''

NEW_BLOCK = '''    if not block:
        ent = _media_sessions.get(key)
        if ent is not None and len(ent["pool"]) >= n:
            if (now - ent["born"]) <= MEDIA_SESSION_TTL:
                return ent["pool"][:n], ent["gen"]
            # פג תוקף (מעל 30 דק') — בונים דור חדש ברקע, אבל *עדיין מגישים את
            # הישן* (חי בגרייס) כדי לא ליצור תקיעה באמצע צפייה. הבקשה הבאה כבר
            # תקבל את החדש. בלי זה הזרמה של סרט ארוך נתקעה בדיוק אחרי חצי שעה.
            if key not in _media_building:
                _media_building.add(key)
                asyncio.create_task(_refresh_pool_bg(client, owner, dc_id, n, ent))
            return ent["pool"][:n], ent["gen"]
        if key not in _media_building:
            _media_building.add(key)
            asyncio.create_task(_fill_pool_bg(client, owner, dc_id, n))
        return [], None'''

REFRESH_FN = '''async def _refresh_pool_bg(client, owner: str, dc_id: int, n: int, old_ent: dict):
    """בונה דור חדש של חיבורים ברקע ומחליף את הישן, ואז מוציא את הישן לגמלאות.
    מתקן את הבאג שבו בריכה שפג תוקפה לא התחדשה ב-block=False (נתקע אחרי 30 דק')."""
    key = (owner, dc_id)
    try:
        fresh = []
        for _ in range(n):
            try:
                fresh.append(await _make_media_session(client, dc_id))
            except Exception as e:
                log.error("רענון media session ל-%s נכשל: %s", owner, e)
                break
        if fresh:
            async with _media_lock(key):
                _media_sessions[key] = {"born": time.time(),
                                        "gen": next(_media_gen_counter),
                                        "pool": fresh}
            asyncio.create_task(_retire_pool(old_ent["pool"]))
            log.info("media pool ל-%s רוענן (%d חיבורים טריים)", owner, len(fresh))
    finally:
        _media_building.discard(key)


'''

ANCHOR = "async def get_media_session_pool_gen("


def main():
    if not TARGET.exists():
        print(f"❌ לא נמצא {TARGET}")
        return 1
    src = TARGET.read_text(encoding="utf-8")

    if "_refresh_pool_bg" in src:
        print("✅ הטלאי כבר מוחל (נמצא _refresh_pool_bg). אין מה לעשות.")
        return 0

    problems = []
    if OLD_BLOCK not in src:
        problems.append("לא נמצא קטע ה-block=False המדויק (ייתכן שה-main.py החי שונה).")
    if ANCHOR not in src:
        problems.append("לא נמצא get_media_session_pool_gen.")
    if problems:
        print("❌ לא ניתן להחיל בבטחה:")
        for p in problems:
            print("   · " + p)
        print("   שלח לי את הפלט של:  grep -n 'if not block:' /opt/zovex-bot/main.py")
        return 1

    patched = src.replace(OLD_BLOCK, NEW_BLOCK, 1)
    patched = patched.replace(ANCHOR, REFRESH_FN + ANCHOR, 1)

    print(f"נמצאו שני העוגנים. הטלאי יוסיף _refresh_pool_bg וישנה את block=False.")
    if not args.apply:
        print("\nהרצה יבשה — לא שונה כלום. להחלה: --apply")
        return 0

    backup = TARGET.with_suffix(f".py.bak.{int(time.time())}")
    shutil.copy2(TARGET, backup)
    TARGET.write_text(patched, encoding="utf-8")
    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(backup, TARGET)
        print(f"❌ הקומפילציה נכשלה — שוחזר הגיבוי. שגיאה:\n{e}")
        return 1
    print(f"✅ הוחל בהצלחה. גיבוי: {backup.name}")
    print("   להפעלה: systemctl restart zovex-bot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
