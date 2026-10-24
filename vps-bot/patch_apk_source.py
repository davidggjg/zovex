#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# שדה "קישור לעדכון" בפאנל הורס את עצמו, ואף אחד לא קורא אותו.
#
# ## שני באגים נפרדים שהצטרפו
#
# 1. ‎/app/version‎ דורס את הקישור לפני שהוא מחזיר אותו:
#
#        v["url"] = f"{STREAM_PUBLIC_BASE}/app/apk"
#
#    זה מכוון — האפליקציה צריכה להוריד מהדומיין שלנו ולא ממקור חיצוני.
#    אבל הפאנל טוען את השדות מאותה נקודת קצה, ולכן מקבל לתוך תיבת הקישור
#    את הכתובת של השרת במקום את מה שהמנהל כתב. השמירה הבאה דורסת את הערך
#    האמיתי. כלומר השדה מוחק את עצמו בכל טעינה של הפאנל.
#
# 2. וגם אילו נשמר נכון — ‎_refresh_apk_cache‎ מושך מ-‎APK_SOURCE_URL‎,
#    שהוא משתנה סביבה. מה שנכתב בפאנל לא השפיע על כלום.
#
# ## התיקון
#
# הקישור שבפאנל הופך למקור האמת שממנו השרת מושך, ו-‎APK_SOURCE_URL‎ נשאר
# ברירת מחדל כשהשדה ריק. ‎/app/version‎ ממשיך להחזיר לאפליקציה את הדומיין
# שלנו (זו ההתנהגות הרצויה), ומוסיף שדה נפרד ‎source_url‎ שבו הפאנל קורא
# ושומר את הערך האמיתי — כך שני השימושים חיים זה לצד זה בלי לדרוס.
#
# שמירת קישור חדש מפעילה רענון מטמון ברקע, אחרת העדכון היה ממתין עד שש
# שעות עד שהשרת היה מבחין בשינוי.
#
# ## השומר שחייב להיות כאן
#
# אם הקישור השמור מצביע על ‎/app/apk‎ עצמו — וזה בדיוק מה שהדריסה הייתה
# שומרת — השרת היה מוריד את עצמו בלולאה. הקוד מסרב לכתובת כזו ונופל חזרה
# לברירת המחדל.
#
#   python3 patch_apk_source.py [נתיב ל-main.py]
#   python3 patch_apk_source.py --revert
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
MARK = "source_url"

# ── 1. פותר את כתובת המקור ─────────────────────────────────────────────────
OLD_SRC = '''_apk_lock = asyncio.Lock()'''
NEW_SRC = '''_apk_lock = asyncio.Lock()


def _apk_source_url() -> str:
    """מאיפה למשוך את ה-APK: מה שהוגדר בפאנל, אחרת ברירת המחדל.

    [fix_apk_source] עד כאן נמשך תמיד מ-APK_SOURCE_URL (משתנה סביבה),
    ומה שנכתב בשדה "קישור לעדכון" בפאנל לא השפיע על דבר.

    השומר אינו תיאורטי: הדריסה ב-/app/version החזירה לפאנל את הכתובת של
    /app/apk, והשמירה הבאה כתבה אותה לקובץ. בלי הבדיקה הזו השרת היה
    מוריד את עצמו בלולאה.
    """
    try:
        u = (load_app_version().get("url") or "").strip()
    except Exception:
        u = ""
    if not u or not u.lower().startswith(("http://", "https://")):
        return APK_SOURCE_URL
    if "/app/apk" in u:
        log.warning("קישור ה-APK בפאנל מצביע על השרת עצמו — "
                    "מתעלם ומשתמש בברירת המחדל")
        return APK_SOURCE_URL
    return u'''

# ── 2. ההורדה משתמשת בו ────────────────────────────────────────────────────
OLD_GET = '''                async with cli.stream("GET", APK_SOURCE_URL) as r:'''
NEW_GET = '''                src = _apk_source_url()
                log.info("מוריד APK מ-%s", src)
                async with cli.stream("GET", src) as r:'''

# ── 3. /app/version מחזיר גם את הערך האמיתי, בשדה נפרד ────────────────────
OLD_VER = '''    v = dict(load_app_version())
    v["apk"] = f"{STREAM_PUBLIC_BASE}/app/apk"
    v["url"] = f"{STREAM_PUBLIC_BASE}/app/apk"
    return v'''
NEW_VER = '''    v = dict(load_app_version())
    # [fix_apk_source] הערך האמיתי נשמר בשדה נפרד לפני הדריסה.
    #
    # ‎url‎ חייב להישאר הדומיין שלנו — זו הסיבה שהדריסה קיימת, והאפליקציה
    # מסתמכת עליה. אבל הפאנל טוען את אותה נקודת קצה, ולכן קיבל לתוך תיבת
    # הקישור את הכתובת של השרת ודרס בשמירה הבאה את מה שהמנהל כתב.
    # ‎source_url‎ הוא מה שהפאנל קורא ושומר, ושני השימושים חיים זה לצד זה.
    v["source_url"] = (v.get("url") or "")
    v["apk"] = f"{STREAM_PUBLIC_BASE}/app/apk"
    v["url"] = f"{STREAM_PUBLIC_BASE}/app/apk"
    return v'''

# ── 4. שמירת קישור חדש מרעננת את המטמון ───────────────────────────────────
OLD_SET = '''    APP_VERSION_FILE.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "version": v}'''
NEW_SET = '''    APP_VERSION_FILE.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
    # [fix_apk_source] שינוי הקישור מפעיל רענון מיד.
    #
    # בלעדיו הקובץ החדש היה ממתין עד שש שעות — תוקף המטמון — ובינתיים
    # המשתמשים היו מקבלים חסימת עדכון ואז מורידים את ה-APK הישן. זה בדיוק
    # התרחיש שמוציא גרסה "מעודכנת" שלא מעדכנת כלום.
    if url_changed:
        asyncio.create_task(_refresh_apk_cache(force=True))
    return {"ok": True, "version": v, "apk_refresh_started": url_changed}'''

OLD_URLSET = '''    if req.url is not None:     v["url"] = req.url.strip() or APP_UPDATE_URL_DEFAULT'''
NEW_URLSET = '''    url_changed = False
    if req.url is not None:
        new_url = req.url.strip() or APP_UPDATE_URL_DEFAULT
        url_changed = new_url != (v.get("url") or "")
        v["url"] = new_url'''

PAIRS = [(OLD_SRC, NEW_SRC), (OLD_GET, NEW_GET), (OLD_VER, NEW_VER),
         (OLD_URLSET, NEW_URLSET), (OLD_SET, NEW_SET)]


def main():
    d = os.path.dirname(P) or "."
    if REVERT:
        bak = sorted((f for f in os.listdir(d)
                      if f.startswith("main_before_apksrc_")), reverse=True)
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
                     f"({n} התאמות). לא נגעתי בכלום — שלח לי את הפלט.")

    bak = f"{d}/main_before_apksrc_{time.strftime('%Y%m%d-%H%M%S')}.py"
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
    print("  הקישור בפאנל הוא עכשיו מקור האמת")
    print("  שמירת קישור חדש מרעננת את המטמון מיד")


if __name__ == "__main__":
    main()
