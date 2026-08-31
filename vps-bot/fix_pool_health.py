#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בודק בריאות ל*כל* בוט בבריכה, ולא רק למי שכבר נחנק.

המדידה שהובילה לזה, בשלושה שלבים:

  1. תחת חמישה צופים בלבד, שניים מהם קיבלו שתיקה של עד 86 שניות.
  2. ביומן: ~105 שורות "Send exception ... TCPTransport closed" בדקה —
     בקצב זהה עם צופים ובלעדיהם (34.5 לדגימה בשקט מול 36.1 תחת עומס,
     יחס 1.05). קצב שאינו זז עם העומס אינו נגרם מהעומס.
  3. ומולן **אפס** שורות "Session started". כלומר חיבורים מתים, ואף אחד
     לא בונה אותם מחדש. אחרי הפעלה נקייה נמדדו שלוש שעות ועשרים דקות של
     אפס מוחלט, ואז עלייה מתמדת עד ~105 לדקה — עקומת הצטברות, בלי ירידה.

למה revive_stream_pool הקיים לא תופס את זה: הוא מסנן chokes >= REVIVE_AFTER_
CHOKES. בוט שהחיבור שלו מת *בלי* שאף בקשה נחתה עליו נשאר עם chokes=0, ולכן
לא נבדק לעולם — עד שצופה נוחת עליו ומשלם את ה-timeout המלא. ככל שיש יותר
בוטים המצב גרוע יותר: כל בוט מקבל פחות תנועה, יושב יותר במנוחה, והחיבור שלו
מת. זו הסיבה ש-22 בוטים מחזיקים פחות טוב מעשרה.

הבדיקה כאן היא על *בריאות החיבור*, לא על היסטוריית כשלים, ולכן היא מוצאת
בדיוק את הבוטים שהמנגנון הקיים עיוור אליהם.

שני כשלים רצופים לפני הרמה: get_me בודדת יכולה להיכשל מרעש רשת חולף, והרמת
בוט תקין מנתקת צופה שיושב עליו באותו רגע. עדיף להחמיץ סבב מאשר לקטוע סרט.

בטוח: מגבה · דורש שכל עוגן יופיע בדיוק פעם אחת · מוודא שהתוצאה מתקמפלת ·
--undo מחזיר.

    python3 fix_pool_health.py          # מחיל
    python3 fix_pool_health.py --undo   # מחזיר
"""
import datetime, glob, os, pathlib, py_compile, shutil, sys, tempfile

TARGET = pathlib.Path("/opt/zovex-bot/main.py")

OLD_CONSTS = '''REVIVE_EVERY = int(os.environ.get("STREAM_REVIVE_EVERY", "120"))
REVIVE_AFTER_CHOKES = int(os.environ.get("STREAM_REVIVE_AFTER_CHOKES", "2"))
'''

NEW_CONSTS = '''REVIVE_EVERY = int(os.environ.get("STREAM_REVIVE_EVERY", "120"))
REVIVE_AFTER_CHOKES = int(os.environ.get("STREAM_REVIVE_AFTER_CHOKES", "2"))

# ── בדיקת בריאות לכל הבריכה ──────────────────────────────────────────────────
# revive_stream_pool בודק רק בוטים שנחנקו (chokes >= REVIVE_AFTER_CHOKES).
# אבל חיבור מת אינו חניקה: הבוט לא נכשל באף בקשה, פשוט אף בקשה לא הגיעה
# אליו. הוא נשאר עם chokes=0, לא נבדק לעולם, ומחכה לצופה שינחת עליו ויספוג
# timeout מלא. היומן הראה ~105 כתיבות לחיבור סגור בדקה מול אפס בניות מחדש —
# כלומר אף חיבור מת לא הוקם, אף פעם.
HEALTH_EVERY = int(os.environ.get("STREAM_HEALTH_EVERY", "300"))
HEALTH_TIMEOUT = float(os.environ.get("STREAM_HEALTH_TIMEOUT", "8"))
HEALTH_FAILS = int(os.environ.get("STREAM_HEALTH_FAILS", "2"))


async def _probe_bot(b):
    """True אם הבוט עונה. get_me היא הקריאה הזולה ביותר שדורשת תשובה אמיתית
    מטלגרם. על חיבור שנסגר היא נכשלת — אבל Pyrogram מנסה עד עשר פעמים לפני
    שהוא מוותר, ועל חיבור *תקוע* הוא פשוט לא חוזר. לכן תקציב זמן הוא חובה."""
    try:
        await asyncio.wait_for(b["client"].get_me(), timeout=HEALTH_TIMEOUT)
        return True
    except asyncio.CancelledError:
        raise
    except Exception as e:
        # str(asyncio.TimeoutError()) הוא מחרוזת ריקה — לקח שכבר נלמד כאן
        # פעם אחת, כשהשורה "לא עלה: " הודפסה בלי שום סיבה. חיבור *תקוע*
        # הוא בדיוק המקרה הזה, והוא הנפוץ ביותר בבדיקה הזאת.
        b["last_health_err"] = (
            f"לא הגיב תוך {HEALTH_TIMEOUT:.0f}ש"
            if isinstance(e, asyncio.TimeoutError)
            else f"{type(e).__name__}: {e}")
        return False


async def _revive_bot(b):
    """מפיל ומרים session. True אם הצליח."""
    name = b.get("name", "?")
    log.warning("♻️ %s — חיבור מת, מרים session מחדש", name)
    try:
        # stop() על לקוח תקוע עלול להיתקע בעצמו — עוטפים בתקציב.
        await asyncio.wait_for(b["client"].stop(), timeout=20)
    except Exception:
        pass
    try:
        await asyncio.wait_for(b["client"].start(), timeout=POOL_START_TIMEOUT)
        # ה-session החדש אינו מכיר את הערוץ, וה-file_reference הישן שייך
        # ל-session שמת — שניהם חייבים להיבנות מחדש, אחרת הבוט "עלה" אבל
        # ייכשל בכל משיכה.
        b["peer_ok"] = await _resolve_peer(b["client"], name)
        for k in [k for k in _bot_msg_cache if k[0] == name]:
            _bot_msg_cache.pop(k, None)
        b["health_fails"] = 0
        b["cooldown_until"] = 0.0
        log.info("✅  %s הורם מחדש", name)
        return True
    except Exception as e:
        log.warning("⚠️ הרמת %s נכשלה: %s: %s", name, type(e).__name__, e)
        return False


async def pool_health_loop():
    """סורק את כל הבריכה ומקים מחדש בוטים שהחיבור שלהם מת.

    הבדיקות רצות *במקביל* וההרמות בטור, וזה לא שרירותי. חיבור תקוע אינו
    מחזיר שגיאה אלא פשוט לא חוזר, כלומר עולה HEALTH_TIMEOUT שלם. בדיקה
    בטור על 22 בוטים שרובם תקועים הייתה נמשכת עד 176 שניות — יותר מחצי
    מהמרווח בין סבבים, כך שהסבבים היו דורכים זה על זה. במקביל, כל הבדיקה
    נגמרת תוך HEALTH_TIMEOUT אחד.
    ההרמות דווקא כן בטור: עשרות התחברויות בו-זמנית לטלגרם הן בדיוק מה
    שגרם בעבר לחסימת IP ולכל הבוטים "לא עלה".
    """
    if not _stream_bots and not STREAM_BOTS_FILE.exists():
        return
    while True:
        await asyncio.sleep(HEALTH_EVERY)
        bots = list(_stream_bots)
        if not bots:
            continue
        results = await asyncio.gather(*[_probe_bot(b) for b in bots],
                                       return_exceptions=True)
        need = []
        for b, ok in zip(bots, results):
            if ok is True:
                if b.get("health_fails"):
                    log.info("✅  %s ענה שוב — לא צריך הרמה", b.get("name", "?"))
                b["health_fails"] = 0
                continue
            if isinstance(ok, BaseException) and not isinstance(ok, Exception):
                raise ok                      # CancelledError — לא בולעים
            b["health_fails"] = b.get("health_fails", 0) + 1
            log.warning("🩺 %s לא ענה (%d/%d): %s", b.get("name", "?"),
                        b["health_fails"], HEALTH_FAILS,
                        b.get("last_health_err", "?"))
            # כשל בודד אינו הוכחה: רעש רשת חולף נראה בדיוק אותו דבר, והרמת
            # בוט תקין מנתקת צופה שיושב עליו ברגע זה. עדיף להמתין לסבב הבא.
            if b["health_fails"] >= HEALTH_FAILS:
                need.append(b)

        revived = 0
        for b in need:
            if await _revive_bot(b):
                revived += 1
            await asyncio.sleep(2)   # לא מציפים את טלגרם בהתחברויות
        if need or revived:
            log.info("🩺 סבב בריאות: %d לא ענו, %d הורמו, %d בבריכה",
                     len(need), revived, len(_stream_bots))
'''

OLD_TASK = ('    asyncio.create_task(revive_stream_pool())'
            '  # מרים מחדש בוטים עם session תקוע\n')

NEW_TASK = ('    asyncio.create_task(revive_stream_pool())'
            '  # מרים מחדש בוטים עם session תקוע\n'
            '    asyncio.create_task(pool_health_loop())'
            '    # בודק *כל* בוט, גם מי שלא נחנק\n')

EDITS = [("קבועים ולולאת הבריאות", OLD_CONSTS, NEW_CONSTS),
         ("רישום המשימה ב-startup", OLD_TASK, NEW_TASK)]


def _fail(msg):
    print("❌ " + msg)
    print("   לא שונה כלום.")
    sys.exit(1)


def undo():
    baks = sorted(glob.glob(str(TARGET) + ".bak-health-*"))
    if not baks:
        _fail("לא נמצא גיבוי")
    shutil.copy2(baks[-1], TARGET)
    print(f"↩️  שוחזר מ-{os.path.basename(baks[-1])}")
    print("   הרץ:  systemctl restart zovex-bot")


def main():
    if not TARGET.exists():
        _fail(f"לא נמצא {TARGET}")
    src = TARGET.read_text(encoding="utf-8")

    if "pool_health_loop" in src:
        print("✓ כבר מוחל. אין מה לעשות.")
        return
    # התלויות שהלולאה משתמשת בהן. אם אחת מהן חסרה, הקוד יתקמפל אבל ייפול
    # בזמן ריצה — ודווקא בתוך משימת רקע, כלומר בשקט ובלי שאיש ישים לב.
    for dep in ("_resolve_peer", "_bot_msg_cache", "POOL_START_TIMEOUT",
                "_stream_bots", "STREAM_BOTS_FILE"):
        if dep not in src:
            _fail(f"חסר {dep} בקוד — הגרסה הזאת אינה מה שציפיתי לה")

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

    bak = f"{TARGET}.bak-health-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print("✅ הוחל.")
    print(f"   גיבוי: {os.path.basename(bak)}")
    print()
    print("   הרץ:   systemctl restart zovex-bot")
    print("   מעקב:  journalctl -u zovex-bot -f | grep --line-buffered 🩺")
    print("   נסיגה: python3 fix_pool_health.py --undo")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
