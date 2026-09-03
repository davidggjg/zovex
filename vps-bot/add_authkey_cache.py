#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
שומר את מפתח ההצפנה לכל DC במקום לייצר אותו מחדש בכל חיבור.

## מה נמדד

שעה אחת ביומן של השרת:

    8,917×  Session started        ← חיבורי מדיה שנבנו מאפס
   10,851×  Connecting...
   10,771×  Disconnected

זה 148 חיבורים בדקה. ובמקביל, מה שאמור להסביר אותם:

      145×  בריכה הופלה אחרי timeouts   ×4 חיבורים  =  580
      168×  חידוש TTL של 30 דקות
    ──────
     ~750   מוסברים.  8,167 לא.

## מה הקוד עושה

`_make_media_session` בונה חיבור מדיה כך:

    if dc_id == home_dc:
        auth_key = await client.storage.auth_key()          # מהמטמון
    else:
        auth_key = await Auth(client, dc_id, test_mode).create()

הענף השני הוא **חילופי מפתחות Diffie-Hellman מלאים מול טלגרם** — חיבור נפרד,
כמה סבבים ברשת, ומפתח חדש לגמרי. הוא רץ בכל פעם שנבנה חיבור, ולא פעם אחת
ל-DC. Pyrogram עצמו שומר את המפתח ב-`client.media_sessions` ומייצר אותו פעם
אחת; כאן הוא נוצר מחדש שוב ושוב.

היחס ביומן תואם: 10,851 `Connecting...` מול 8,917 `Session started` — יחס
1.22. חיבור ל-DC הבית פותח חיבור אחד; חיבור ל-DC אחר פותח שניים, כי ה-DH
פותח משלו. כלומר כחמישית מהחיבורים משלמים DH מלא — בערך **2,000 חילופי
מפתחות בשעה מאותו חשבון.**

## מה התיקון עושה

שומר את המפתח לפי (בוט, DC). הראשון משלם DH ואישור; מכאן והלאה בניית חיבור
היא חיבור TCP בלבד.

מפתח שאושר פעם אחת נשאר מאושר, ולכן `ExportAuthorization`/`ImportAuthorization`
נחוצים רק בפעם הראשונה. אם טלגרם בכל זאת פוסל מפתח שמור (למשל אחרי בטלה
ארוכה), התיקון מזהה את הכישלון, מוחק אותו מהמטמון, ובונה אחד טרי — פעם אחת,
בלי לולאה.

**הפאץ' רק מוסיף בסוף הקובץ.** ההגדרה החדשה של `_make_media_session` דורסת
את הקודמת, כי פייתון מחפש שמות גלובליים בזמן הקריאה. אין עוגנים שיכולים לא
להתאים — זה מה שהפיל כאן תיקונים בעבר.

    python3 add_authkey_cache.py --check
    python3 add_authkey_cache.py && systemctl restart zovex-bot
    python3 add_authkey_cache.py --undo

## איך לדעת אם זה עזר

אחרי הפעלה מחדש, לחכות עשר דקות של צפייה ואז:

    python3 whystuck.py --min 10

`Session started` אמור לרדת דרמטית, וכך גם `Connecting...`. אם הם לא יורדים,
מקור הבנייה הוא במקום אחר וצריך להמשיך לחפש — לא להשאיר את זה ולקוות.
"""
import datetime, glob, os, pathlib, py_compile, shutil, sys, tempfile

TARGET = pathlib.Path("/opt/zovex-bot/main.py")
DONE_MARK = "_MEDIA_AUTH_KEYS"

# החתימה המדויקת, ולא רק השם: התוספת דורסת את הפונקציה, ולכן היא חייבת לקבל
# בדיוק את מה שהקוראים שולחים. בעותק ישן של הקובץ החתימה היא (dc_id) בלבד —
# דריסה שם הייתה שוברת כל קריאה.
NEEDED = ["async def _make_media_session(client, dc_id", "Auth(", "Session(",
          "functions.auth.ExportAuthorization",
          "functions.auth.ImportAuthorization",
          "log = logging.getLogger"]

BLOCK = r'''

# ── מטמון מפתחות הצפנה לחיבורי מדיה ─────────────────────────────────────────
# ההגדרה הקודמת של _make_media_session הריצה Auth(...).create() — חילופי
# מפתחות Diffie-Hellman מלאים מול טלגרם — בכל בנייה של חיבור ל-DC שאינו
# ה-DC הביתי. נמדדו 8,917 חיבורי מדיה שנבנו בשעה, מתוכם כחמישית מול DC אחר,
# כלומר בערך 2,000 חילופי מפתחות בשעה מאותו חשבון.
#
# מפתח שאושר פעם אחת נשאר מאושר. לכן הוא נשמר לפי (בוט, DC): הראשון משלם
# DH ואישור, וכל השאר משלמים חיבור TCP בלבד.
#
# ההגדרה הזאת דורסת את הקודמת בכוונה — פייתון מחפש שמות גלובליים בזמן
# הקריאה, ולכן כל מי שקורא ל-_make_media_session יקבל מכאן והלאה את זו.
_MEDIA_AUTH_KEYS: dict = {}
_media_authkey_stats = {"dh": 0, "reused": 0, "recovered": 0}


def _media_auth_owner(client) -> str:
    return getattr(client, "name", None) or f"client-{id(client)}"


async def _make_media_session(client, dc_id: int, _retry: bool = True):
    """חיבור media לאותו לקוח, עם מפתח שמור במקום DH בכל פעם."""
    test_mode = await client.storage.test_mode()
    home_dc = await client.storage.dc_id()

    # ה-DC הביתי כבר משתמש במפתח השמור של הלקוח — שם לא היה מה לתקן.
    if dc_id == home_dc:
        session = Session(client, dc_id, await client.storage.auth_key(),
                          test_mode, is_media=True)
        await session.start()
        return session

    key = (_media_auth_owner(client), dc_id)
    auth_key = _MEDIA_AUTH_KEYS.get(key)
    fresh = auth_key is None
    if fresh:
        auth_key = await Auth(client, dc_id, test_mode).create()
        _media_authkey_stats["dh"] += 1

    session = Session(client, dc_id, auth_key, test_mode, is_media=True)
    try:
        await session.start()
    except Exception:
        # מפתח שמור שטלגרם כבר לא מכיר. מוחקים ובונים טרי — פעם אחת בלבד,
        # כדי שלא תיווצר לולאה כשהתקלה אינה במפתח.
        if not fresh and _retry:
            _MEDIA_AUTH_KEYS.pop(key, None)
            _media_authkey_stats["recovered"] += 1
            log.info("media auth: המפתח השמור ל-%s/DC%s נדחה — בונה טרי",
                     key[0], dc_id)
            return await _make_media_session(client, dc_id, _retry=False)
        raise

    if not fresh:
        _media_authkey_stats["reused"] += 1
        return session

    # רק מפתח חדש צריך אישור. אחרי שאושר, הוא נשמר ומשמש את כל הבאים.
    last = None
    for _ in range(3):
        try:
            exported = await client.invoke(
                functions.auth.ExportAuthorization(dc_id=dc_id))
            await session.invoke(functions.auth.ImportAuthorization(
                id=exported.id, bytes=exported.bytes))
            _MEDIA_AUTH_KEYS[key] = auth_key
            return session
        except Exception as e:
            last = e
            log.warning("ImportAuthorization ל-DC %d נכשל, מנסה שוב: %s",
                        dc_id, e)
    # לא אושר — לא שומרים מפתח שלא עובד, ולא מחזירים חיבור שיתלה בקשות.
    try:
        await session.stop()
    except Exception:
        pass
    raise last if last else RuntimeError(
        f"ImportAuthorization ל-DC {dc_id} נכשל")


@api.get("/media-auth/stats")
async def media_auth_stats():
    """כמה DH נחסכו בפועל. זו הבדיקה שאומרת אם התיקון עובד."""
    s = dict(_media_authkey_stats)
    s["cached_keys"] = len(_MEDIA_AUTH_KEYS)
    total = s["dh"] + s["reused"]
    s["reuse_pct"] = round(s["reused"] * 100 / total, 1) if total else 0.0
    return s
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

    # אם ההגדרה הישנה אינה האחרונה, הדריסה לא תעבוד וצריך לדעת את זה מראש.
    if src.count("async def _make_media_session") != 1:
        _fail(f"_make_media_session מוגדרת "
              f"{src.count('async def _make_media_session')} פעמים — ציפינו לאחת")

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

    bak = f"{TARGET}.bak-authkey-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print("✅ הוחל. מפתח ההצפנה נשמר לכל DC (לא שונתה אף שורה קיימת).")
    print(f"   גיבוי: {os.path.basename(bak)}")
    print()
    print("   הרץ:   systemctl restart zovex-bot")
    print("   בדיקה: curl -s http://127.0.0.1:8000/media-auth/stats")
    print("   נסיגה: python3 add_authkey_cache.py --undo")


def undo():
    baks = sorted(glob.glob(str(TARGET) + ".bak-authkey-*"))
    if not baks:
        _fail("לא נמצא גיבוי")
    shutil.copy2(baks[-1], TARGET)
    print(f"↩️  שוחזר מ-{os.path.basename(baks[-1])}")
    print("   הרץ:  systemctl restart zovex-bot")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
