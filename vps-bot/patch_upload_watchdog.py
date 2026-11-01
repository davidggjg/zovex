#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# בוט ההעלאה מת בשקט, ואין מי שיחייה אותו.
#
# ## מה נמדד
#
# ‎journalctl -f‎ פתוח, נשלחו קבצים לבוט — **אפס שורות**. הוא עלה בהצלחה
# ב-00:17 ("✅ בוט העלאה עלה") ומאז לא קיבל מטלגרם שום עדכון.
#
# ## למה זה קורה דווקא לו
#
# ‎start_upload_bot()‎ מרים אותו פעם אחת בעליית השירות. ה-watchdog הקיים
# שומר על הלקוח הראשי ועל בריכת הסטרימינג — **בוט ההעלאה אינו נמצא בשום
# מנגנון החייאה.** כשה-session שלו נופל, איש אינו מבחין.
#
# וזה מסביר את "פתאום עובד פתאום לא": כל קריסה של השירות הייתה מתקנת
# אותו לכמה שעות. אתמול היו תשע, והן כיסו על הבעיה. ברגע שהקריסות
# נעצרו, הוא נשאר תקוע לאורך זמן — ולכן זה החמיר דווקא כשהכול השתפר.
#
# ## שני תיקונים
#
# 1. **שורת לוג על קבלה.** עד כה נרשם רק כישלון, ולכן שקט מוחלט יכול
#    היה להיות "עובד מצוין" או "מת" — בלי שום דרך להבדיל. זה מה שהפך
#    את האבחון לניחוש.
#
# 2. **בדיקה תקופתית.** פינג כל חמש דקות; אחרי שני כישלונות רצופים
#    הלקוח נבנה **מחדש מאפס** ולא רק start/stop.
#
# ## למה בנייה מחדש ולא הרמה
#
# זה בדיוק הבאג שהפיל את השירות תשע פעמים אתמול: ‎stop()‎ על לקוח תקוע
# נתקע גם הוא, החריגה נבלעת, והלקוח נשאר רשום כמחובר — ואז ‎start()‎
# זורק ‎Client is already connected‎ וההצלה "נכשלת". אובייקט חדש אינו
# יכול להיתקל בזה.
#
#   python3 patch_upload_watchdog.py [נתיב ל-main.py]
#   python3 patch_upload_watchdog.py --revert
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
MARK = "upload_watchdog"

# ── 1. שורת לוג על קבלה ────────────────────────────────────────────────────
OLD_RECV = '''    """מנהל שלח קובץ/וידאו לבוט ההעלאה (או טקסט — לזרימת שם ידני)."""
    uid = message.from_user.id if message.from_user else 0'''
NEW_RECV = '''    """מנהל שלח קובץ/וידאו לבוט ההעלאה (או טקסט — לזרימת שם ידני)."""
    uid = message.from_user.id if message.from_user else 0
    # [upload_watchdog] עד כה נרשם ללוג רק כישלון, ולכן שקט מוחלט יכול
    # היה להיות "עובד מצוין" או "ה-session מת" — בלי דרך להבדיל ביניהם.
    # זו השורה שהופכת את האבחון הבא ממאמץ לשנייה אחת.
    _mk = "טקסט" if (message.text and not message.media) else "מדיה"
    log.info("upload_bot: התקבלה הודעה (%s) מ-%s", _mk, uid)'''

# ── 2. הבדיקה התקופתית ─────────────────────────────────────────────────────
OLD_WD = '''async def stop_upload_bot():'''
NEW_WD = '''# [upload_watchdog] בדיקה תקופתית לבוט ההעלאה.
#
# הוא הלקוח היחיד שלא היה בשום מנגנון החייאה: הלקוח הראשי מכוסה
# ב-telegram_watchdog, בריכת הסטרימינג ב-revive_stream_pool, והוא — בכלום.
UPLOAD_PING_SECS = int(os.environ.get("UPLOAD_PING_SECS", "300"))
UPLOAD_PING_TIMEOUT = int(os.environ.get("UPLOAD_PING_TIMEOUT", "20"))
UPLOAD_FAILS_BEFORE_REBUILD = 2


async def upload_bot_watchdog():
    """מוודא שבוט ההעלאה עדיין עונה, ובונה אותו מחדש כשלא.

    שני כישלונות רצופים ולא אחד: פספוס בודד יכול להיות עומס רגעי על
    ה-event loop בזמן הזרמה, ובנייה מחדש על כל רעש היא תרופה גרועה
    מהמחלה.

    הבנייה היא **אובייקט חדש** ולא start/stop על הקיים. זה הבאג שהפיל
    את השירות תשע פעמים: stop() על לקוח תקוע נתקע גם הוא, הלקוח נשאר
    רשום כמחובר, ו-start() זורק "Client is already connected" — כך
    שמסלול ההצלה מובטח להיכשל דווקא במקרה שהוא נכתב בשבילו.
    """
    global upload_bot
    if not UPLOAD_BOT_TOKEN:
        return
    await asyncio.sleep(180)          # לתת לעלייה הראשונה להסתיים
    fails = 0
    while True:
        await asyncio.sleep(UPLOAD_PING_SECS)
        if upload_bot is None:
            log.warning("upload_bot: אינו קיים — בונה")
        else:
            try:
                await asyncio.wait_for(upload_bot.get_me(),
                                       timeout=UPLOAD_PING_TIMEOUT)
                fails = 0
                continue
            except Exception as e:
                fails += 1
                log.warning("upload_bot: פינג נכשל (%d/%d): %s: %s",
                            fails, UPLOAD_FAILS_BEFORE_REBUILD,
                            type(e).__name__, e)
                if fails < UPLOAD_FAILS_BEFORE_REBUILD:
                    continue
        fails = 0
        try:
            if upload_bot is not None:
                try:
                    await asyncio.wait_for(upload_bot.stop(), timeout=20)
                except Exception:
                    pass              # תקוע גם ב-stop; האובייקט נזרק ממילא
            upload_bot = None
            await start_upload_bot()
            if upload_bot is not None:
                log.info("✅ upload_bot: נבנה מחדש ועונה")
        except Exception as e:
            log.error("upload_bot: בנייה מחדש נכשלה: %s: %s",
                      type(e).__name__, e)


async def stop_upload_bot():'''

# ── 3. הפעלה ───────────────────────────────────────────────────────────────
OLD_GO = '''        log.info("✅ בוט העלאה עלה")'''
NEW_GO = '''        log.info("✅ בוט העלאה עלה")
        # [upload_watchdog] מופעל פעם אחת, בעלייה הראשונה בלבד.
        global _upload_wd_started
        if not globals().get("_upload_wd_started"):
            _upload_wd_started = True
            asyncio.create_task(upload_bot_watchdog())'''

PAIRS = [(OLD_RECV, NEW_RECV), (OLD_WD, NEW_WD), (OLD_GO, NEW_GO)]


def main():
    d = os.path.dirname(P) or "."
    if REVERT:
        bak = sorted((f for f in os.listdir(d)
                      if f.startswith("main_before_uplwd_")), reverse=True)
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
        if s.count(old) != 1:
            sys.exit(f"❌ קטע {i} מתוך {len(PAIRS)} נמצא {s.count(old)} פעמים. "
                     f"לא נגעתי בכלום.")
    bak = f"{d}/main_before_uplwd_{time.strftime('%Y%m%d-%H%M%S')}.py"
    shutil.copy(P, bak)
    out = s
    for old, new in PAIRS:
        out = out.replace(old, new, 1)
    # ההצהרה הגלובלית חייבת לבוא לפני כל שימוש בשם בתוך אותה פונקציה
    out = out.replace("_upload_wd_started = True",
                      "_upload_wd_started = True", 1)
    io.open(P, "w", encoding="utf-8").write(out)
    try:
        py_compile.compile(P, doraise=True)
    except Exception as e:
        shutil.copy(bak, P)
        sys.exit(f"❌ לא עובר קומפילציה — שוחזר.\n   {e}")
    print(f"✓ הוחל. גיבוי: {bak}")
    print("  פינג כל 5 דק', בנייה מחדש אחרי 2 כישלונות")
    print("  שורת לוג על כל הודעה שמתקבלת")


if __name__ == "__main__":
    main()
