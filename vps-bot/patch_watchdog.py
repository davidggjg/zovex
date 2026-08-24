#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ה-Watchdog מפסיק להרוג את השירות בזמן שהבריכה מזרימה תקין.

אומת בשרת ב-21:25:04 — שלושה פספוסים של ping לבוט הראשי, os._exit(1),
ו-systemd מרים מחדש. זו הייתה התקיעה של חצי דקה עד דקה באמצע הסרט.

בטוח להרצה חוזרת. גיבוי + בדיקת קומפילציה + שחזור אוטומטי בכשל.
"""
import pathlib, py_compile, shutil, sys, time

P = pathlib.Path("/opt/zovex-bot/main.py")
s = P.read_text(encoding="utf-8")
done = []

OLD_WD = 'WATCHDOG_INITIAL_DELAY_SECS = 120\n\nasync def telegram_watchdog():\n    consecutive_failures = 0\n    await asyncio.sleep(WATCHDOG_INITIAL_DELAY_SECS)\n    while True:\n        try:\n            await asyncio.wait_for(bot_client.get_me(), timeout=WATCHDOG_TIMEOUT_SECS)\n            if consecutive_failures > 0:\n                log.info("✅ Watchdog: החיבור לטלגרם חזר לענות")\n            consecutive_failures = 0\n        except Exception as e:\n            consecutive_failures += 1\n            log.error(\n                "⚠️ Watchdog: החיבור לטלגרם לא הגיב תוך %ds (נסיון %d/%d): %s",\n                WATCHDOG_TIMEOUT_SECS, consecutive_failures, WATCHDOG_MAX_CONSECUTIVE_FAILURES, e,\n            )\n            if consecutive_failures >= WATCHDOG_MAX_CONSECUTIVE_FAILURES:\n                log.critical("💥 Watchdog: החיבור לטלגרם תקוע - מפעיל restart אוטומטי לתהליך")\n                os._exit(1)\n        await asyncio.sleep(WATCHDOG_CHECK_INTERVAL_SECS)\n\n'
NEW_WD = 'WATCHDOG_INITIAL_DELAY_SECS = 120\n# תוך כמה שניות אחורה משיכה מוצלחת של בוט מהבריכה נחשבת עדות שטלגרם מגיב.\nWATCHDOG_POOL_GRACE = int(os.environ.get("WATCHDOG_POOL_GRACE", "120"))\n\n\nasync def _restart_main_client() -> bool:\n    """מרים את הלקוח הראשי מחדש. מחזיר True אם הוא עונה אחרי זה.\n\n    זו הפעולה שה-Watchdog צריך לעשות *לפני* שהוא שוקל להפיל את השירות: אם רק\n    ה-session של הבוט הראשי תקוע, בניית אחד חדשה לוקחת שניות ולא נוגעת ב-21\n    בוטי הבריכה ולא בצופים שמנגנים באותו רגע.\n    """\n    try:\n        await asyncio.wait_for(bot_client.stop(), timeout=20)\n    except Exception:\n        pass          # לקוח תקוע עלול להיתקע גם ב-stop; ממשיכים ל-start\n    try:\n        await asyncio.wait_for(bot_client.start(), timeout=60)\n        await asyncio.wait_for(bot_client.get_me(), timeout=WATCHDOG_TIMEOUT_SECS)\n        log.info("✅ Watchdog: הלקוח הראשי הורם מחדש ועונה — השירות ממשיך לרוץ")\n        return True\n    except Exception as e:\n        log.error("⚠️ Watchdog: הרמת הלקוח הראשי נכשלה: %s: %s", type(e).__name__, e)\n        return False\n\n\nasync def telegram_watchdog():\n    """שומר על החיבור לטלגרם — אבל בלי להרוג את השירות על סמך בדיקה אחת.\n\n    הגרסה הקודמת בדקה רק את `bot_client.get_me()`, ואחרי שלושה פספוסים הריצה\n    `os._exit(1)`. היא נכתבה ל-Hugging Face Spaces, שם restart של הקונטיינר\n    היה הדרך היחידה להתאושש. על ה-VPS, עם `Restart=always`, התוצאה היא שכל\n    השירות נהרג — וכל 21 הבוטים צריכים לעלות מחדש, ~90 שניות שבהן הצופה מקבל\n    אפס בייטים.\n\n    נמדד בשרת ב-24/08 בשעה 21:25: שלושה פספוסים ב-25 שניות, `os._exit(1)`,\n    `Scheduled restart job` — ובדיוק אז הצופה דיווח על תקיעה של חצי דקה עד\n    דקה. כלומר "נתקע כל כמה דקות, צריך לצאת ולהיכנס" היה השירות שמפיל את\n    עצמו, לא טלגרם ולא הבוטים.\n\n    שני תיקונים:\n\n    1. משיכה מוצלחת של *כל* בוט מהבריכה היא הוכחה שטלגרם מגיב. אם היא קרתה\n       בדקותיים האחרונות, ה-ping של הבוט הראשי נתקע מסיבה מקומית (ה-session\n       שלו, או event loop עמוס תחת הזרמה) — ואין שום סיבה להפיל את השירות.\n    2. גם כשאין הוכחה כזו, קודם מרימים מחדש רק את הלקוח הראשי. הפלת התהליך\n       נשארת המוצא האחרון, אחרי שגם זה נכשל.\n    """\n    consecutive_failures = 0\n    await asyncio.sleep(WATCHDOG_INITIAL_DELAY_SECS)\n    while True:\n        try:\n            await asyncio.wait_for(bot_client.get_me(), timeout=WATCHDOG_TIMEOUT_SECS)\n            if consecutive_failures > 0:\n                log.info("✅ Watchdog: החיבור לטלגרם חזר לענות")\n            consecutive_failures = 0\n        except Exception as e:\n            consecutive_failures += 1\n            log.error(\n                "⚠️ Watchdog: החיבור לטלגרם לא הגיב תוך %ds (נסיון %d/%d): %s",\n                WATCHDOG_TIMEOUT_SECS, consecutive_failures, WATCHDOG_MAX_CONSECUTIVE_FAILURES, e,\n            )\n            if consecutive_failures >= WATCHDOG_MAX_CONSECUTIVE_FAILURES:\n                idle = time.time() - _last_pool_success\n                if idle < WATCHDOG_POOL_GRACE:\n                    log.warning(\n                        "⚠️ Watchdog: הבוט הראשי לא עונה, אבל הבריכה סיפקה "\n                        "בייטים לפני %.0f שניות — טלגרם מגיב, לא מפילים את "\n                        "השירות. מרים רק את הלקוח הראשי.", idle)\n                    await _restart_main_client()\n                    consecutive_failures = 0\n                elif await _restart_main_client():\n                    consecutive_failures = 0\n                else:\n                    log.critical("💥 Watchdog: החיבור לטלגרם תקוע וגם הרמת הלקוח "\n                                 "הראשי נכשלה - מפעיל restart אוטומטי לתהליך")\n                    os._exit(1)\n        await asyncio.sleep(WATCHDOG_CHECK_INTERVAL_SECS)\n\n'
OLD_OK = 'def _mark_ok(bot):\n    """משיכה הצליחה — מאפסים את מונה הכשלים הרצופים ואת דרגת העונש."""\n    if bot.get("fails"):\n        bot["fails"] = 0\n    if bot.get("chokes"):\n        bot["chokes"] = 0\n\n'
NEW_OK = '# מתי בפעם האחרונה בוט כלשהו מהבריכה סיפק בייטים בהצלחה. ה-Watchdog משתמש\n# בזה כעדות חיה לכך שטלגרם מגיב — ראה telegram_watchdog.\n_last_pool_success = 0.0\n\n\ndef _mark_ok(bot):\n    """משיכה הצליחה — מאפסים את מונה הכשלים הרצופים ואת דרגת העונש."""\n    global _last_pool_success\n    _last_pool_success = time.time()\n    if bot.get("fails"):\n        bot["fails"] = 0\n    if bot.get("chokes"):\n        bot["chokes"] = 0\n\n'

if "_restart_main_client" in s and "_last_pool_success" in s:
    print("כבר מוחל — אין מה לעשות.")
    sys.exit(0)

for old, new, label in ((OLD_OK, NEW_OK, "חותמת משיכה מוצלחת של הבריכה"),
                        (OLD_WD, NEW_WD, "Watchdog — הרמת לקוח ראשי במקום הפלת השירות")):
    if old not in s:
        print("### הקטע '%s' בשרת אינו תואם למצופה — לא שונה כלום ###" % label)
        sys.exit(1)
    s = s.replace(old, new, 1)
    done.append(label)

bak = P.with_name("main_before_watchdog_%d.py" % time.time())
shutil.copy2(P, bak)
P.write_text(s, encoding="utf-8")
try:
    py_compile.compile(str(P), doraise=True)
except Exception as e:
    shutil.copy2(bak, P)
    print("### הקומפילציה נכשלה — שוחזר הגיבוי ###")
    print(e)
    sys.exit(1)
print("הוחל:")
for d in done:
    print("   + " + d)
print("\n   גיבוי: " + bak.name)
print("\n   עכשיו:  sudo systemctl restart zovex-bot")
