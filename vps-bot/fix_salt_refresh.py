#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_salt_refresh — מרענן את ה-salt של סשני המדיה, כדי שלא נצטרך לזרוק אותם.

## הממצא (מתועד במלואו ב-FINDING_server_salt.md)

ה-salt של MTProto תקף 30 דקות ועוד 30 דקות חסד. pyrogram **אינו** מרענן
אותו מראש: `GetFutureSalts` לא נקראת בשום מקום בספרייה, וה-salt מתעדכן
רק בתגובה ל-`BadServerSalt`. גרוע מזה — ping נשלח עם `wait_response=False`
ולכן אין לו handler, ו-`BadServerSalt` שמגיע בתשובה ל-ping **נזרק בשקט**.

המשמעות: סשן לא פעיל אינו מתקן את ה-salt שלו לעולם, גם אם הוא שולח ping
כל 5 שניות. התיקון מגיע רק כשבקשה אמיתית נופלת עליו — כלומר על גב הצופה.

זה תוקן במעלה הזרם ב-kurigram (PR #464), עם מדידה: `GetFutureSalts` בשעה
0 → 3, וה-salt ב-+60 דקות פג → תקף.

## ולמה זה נוגע דווקא לנו

    MEDIA_SESSION_TTL = 1800

1800 שניות = 30 דקות = **בדיוק** תוחלת החיים של ה-salt. הערך נקבע
אמפירית מסיבה אחרת, אבל התוצאה בפועל היא שהקוד מעקף את באג ה-salt בכך
שהוא זורק את הסשן לפני שה-salt מתיישן — ומשלם על זה בבנייה מחדש של 84
חיבורי מדיה כל 30 דקות.

המחיר נמדד ותואם: המודל חוזה 14 חיבורים חדשים בחלון של 5 דקות, ונמדד
ממוצע 6.8 (49%) — בדיוק מה שמצפים בשעה שקטה, שבה רק בריכות שנוגעים בהן
מתרעננות. הסחרור הבסיסי שראינו ביומן **הוא** מחזור הבריכות.

## מה הפאצ' הזה עושה — ומה הוא בכוונה לא עושה

**עושה:** לולאת רקע שמבקשת `GetFutureSalts` לכל סשן מדיה חי ומציבה את
ה-salt שתקף כרגע. זו תוספת טהורה — שום נתיב קיים לא משתנה.

**לא עושה:** לא נוגע ב-`MEDIA_SESSION_TTL`. זה בכוונה. לשנות גם את מקור
הסחרור וגם את מה שמונע אותו באותה נקודה פירושו שלא נדע מה גרם למה — זו
בדיוק הטעות שנעשתה כאן אמש (חנק על פתיחת חיבורים + הורדת ההשהיה + שינוי
החימום, כולם יחד, ואז מדידה שלא ניתן לפרש).

הסדר: **קודם** מאמתים שהרענון בכלל עובד (המונים ב-/debug/caches), **ורק
אחרי זה** מעלים את ה-TTL בפאצ' נפרד ומודדים את `conn` צונח.

## מדידה, לא אמונה

שלושה מונים נחשפים ב-/debug/caches:

    salt_ok        כמה רענונים הצליחו
    salt_fail      כמה נכשלו
    salt_last_err  השגיאה האחרונה, אם הייתה

אם `salt_ok` עולה ו-`salt_fail` אפס — הרענון עובד ואפשר להמשיך לשלב הבא.
אם `salt_fail` עולה — הפאצ' לא מזיק (כל חריגה נתפסת), אבל הוא גם לא עוזר,
ואז `salt_last_err` אומר למה. בלי המונים האלה זה היה "תיקון" שאי אפשר
לאמת, וכאלה כבר היו כאן.

## בטיחות

כל חריגה נתפסת ונספרת. הלולאה לא נוגעת בבריכות, לא סוגרת כלום, ולא
משנה מצב מלבד ה-salt של סשן קיים. כישלון מלא שלה = המצב הנוכחי בדיוק.

    python3 fix_salt_refresh.py --check
    python3 fix_salt_refresh.py
    python3 fix_salt_refresh.py --revert
ואחריו:  systemctl restart zovex-bot
"""
import argparse, ast, os, shutil, sys
from pathlib import Path

MAIN = Path(os.environ.get("ZOVEX_MAIN", "/opt/zovex-bot/main.py"))
BAK = MAIN.with_name(MAIN.name + ".bak_saltrefresh")
MARK = "_salt_refresh_loop"

OLD_DECL = "_media_gen_counter = itertools.count(1)\n"
NEW_DECL = '''_media_gen_counter = itertools.count(1)

# ── רענון ה-salt של סשני המדיה ────────────────────────────────────────────────
# ראה FINDING_server_salt.md. בקצרה: salt של MTProto תקף 30 דקות + 30 חסד,
# ו-pyrogram לא מרענן אותו מראש — GetFutureSalts לא נקראת בספרייה כלל, וה-
# salt מתוקן רק בתגובה ל-BadServerSalt. ping נשלח עם wait_response=False
# ולכן BadServerSalt שמגיע בתשובה לו נזרק בשקט, כך שסשן לא פעיל אינו מתקן
# את עצמו לעולם והתיקון נופל על הבקשה האמיתית הראשונה — של צופה.
#
# תוקן במעלה הזרם ב-kurigram PR #464. כאן עושים את אותו דבר מבחוץ, בלי
# לגעת בספרייה: מבקשים salts עתידיים ומציבים את מי שתקף כרגע.
#
# המונים נחשפים ב-/debug/caches כדי שיהיה אפשר לאמת שזה באמת עובד ולא
# להאמין שזה עובד.
SALT_REFRESH_EVERY = int(os.environ.get("MEDIA_SALT_REFRESH", "600"))
_salt_stats = {"ok": 0, "fail": 0, "last_err": ""}


async def _salt_refresh_loop():
    """מציב לכל סשן מדיה חי את ה-salt שתקף כרגע.

    כל חריגה נתפסת ונספרת: הלולאה הזאת היא שיפור, ואם היא נכשלת המצב חוזר
    להיות בדיוק מה שהיה לפניה. היא לא נוגעת בבריכות ולא סוגרת כלום.
    """
    while True:
        await asyncio.sleep(SALT_REFRESH_EVERY)
        try:
            pools = [(k, list(v.get("pool") or []))
                     for k, v in list(_media_sessions.items())]
        except Exception:
            continue
        for _key, sessions in pools:
            for sess in sessions:
                try:
                    r = await asyncio.wait_for(
                        sess.invoke(functions.GetFutureSalts(num=4)), timeout=20)
                    now = time.time()
                    picked = None
                    for fs in (getattr(r, "salts", None) or []):
                        if fs.valid_since <= now < fs.valid_until:
                            picked = fs.salt
                            break
                    if picked is not None:
                        sess.salt = picked
                        _salt_stats["ok"] += 1
                    else:
                        # השרת ענה אבל אין salt תקף כרגע ברשימה. לא שגיאה,
                        # אבל גם לא הצלחה — נספר בנפרד כדי שלא ייראה כמו כן.
                        _salt_stats["fail"] += 1
                        _salt_stats["last_err"] = "no valid salt in reply"
                except Exception as e:
                    _salt_stats["fail"] += 1
                    _salt_stats["last_err"] = f"{type(e).__name__}: {e}"[:140]
                # פיזור: 84 בקשות בבת אחת הן בדיוק סוג הפרץ שהכל כאן
                # מנסה להימנע ממנו.
                await asyncio.sleep(0.15)
'''

OLD_REG = '    asyncio.create_task(pool_health_loop())    # בודק *כל* בוט, גם מי שלא נחנק\n'
NEW_REG = ('    asyncio.create_task(pool_health_loop())    # בודק *כל* בוט, גם מי שלא נחנק\n'
           '    asyncio.create_task(_salt_refresh_loop())  # salt תקף בלי לזרוק סשנים\n')

OLD_DBG = '        "media_sessions_total_conns": media_conns,\n'
NEW_DBG = ('        "media_sessions_total_conns": media_conns,\n'
           '        "salt_ok": _salt_stats["ok"],\n'
           '        "salt_fail": _salt_stats["fail"],\n'
           '        "salt_last_err": _salt_stats["last_err"],\n')


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
    for fn in ("get_media_session_pool_gen", "drop_media_sessions", "debug_caches"):
        if fn not in names:
            sys.exit(f"אימות נכשל: {fn} נעלמה — לא כותב.")
    if not patched:
        return
    if "_salt_refresh_loop" not in names:
        sys.exit("אימות נכשל: הלולאה לא נוצרה — לא כותב.")
    # לולאה שלא נרשמה היא קוד מת שנראה כמו תיקון. זו טעות שקל לעשות
    # ובלתי אפשרי לגלות בלי הבדיקה הזאת.
    if "asyncio.create_task(_salt_refresh_loop())" not in src:
        sys.exit("אימות נכשל: הלולאה לא נרשמה להפעלה — לא כותב.")
    if '"salt_ok"' not in src:
        sys.exit("אימות נכשל: המונים לא נחשפו ב-debug — לא כותב.")


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

    for needle in ("from pyrogram.raw import functions", "import time", "_media_sessions"):
        if needle not in src:
            sys.exit(f"לא מצאתי '{needle}' ב-main.py — ההזרקה תלויה בו, לא כותב.")

    for label, old in (("_media_gen_counter", OLD_DECL),
                       ("רישום המשימות", OLD_REG),
                       ("שורת debug", OLD_DBG)):
        n = src.count(old)
        if n != 1:
            sys.exit(f"העוגן '{label}' נמצא {n} פעמים (ציפיתי 1) — "
                     "הקוד בשרת שונה ממה שציפיתי. לא כותב.")

    new = (src.replace(OLD_DECL, NEW_DECL, 1)
              .replace(OLD_REG, NEW_REG, 1)
              .replace(OLD_DBG, NEW_DBG, 1))
    validate(new)

    print(f"רענון salt כל {os.environ.get('MEDIA_SALT_REFRESH', '600')} שניות")
    print("MEDIA_SESSION_TTL לא משתנה — זה שלב נפרד, אחרי שנאמת שזה עובד")
    print("מונים חדשים ב-/debug/caches: salt_ok · salt_fail · salt_last_err")
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
    print("  לביטול:    python3 fix_salt_refresh.py --revert")
    print()
    print("  אימות אחרי ~12 דקות (הרענון הראשון ב-10):")
    print("    curl -s localhost:8000/debug/caches | tr ',' '\\n' | grep salt")


if __name__ == "__main__":
    main()
