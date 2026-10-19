#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# ההשהיה בין פתיחות זרמים חלה על *כל* בקשה, וחנקה את השרת כולו.
#
# ## מה נמצא
#
# ‎stream_from_channel‎ — המטפל בכל בקשת ‎/stream/‎ — פתח בשורה:
#
#     await _stagger_new_stream()
#
# והפונקציה הזאת מחזיקה מנעול **גלובלי** ומבטיחה שלא יתחילו שתי בקשות
# בפער קטן מ-‎STREAM_START_STAGGER‎ (ברירת מחדל 2.0 שניות). כלומר השרת
# כולו הוגבל ל**חצי בקשה בשנייה** — לא לכל צופה, בסך הכל.
#
# ## למה זה לא נתפס
#
# ההערה בקוד טענה "לצופה בודד זה שקוף לגמרי — ה-wait כמעט תמיד 0, כי אין
# עם מי להתנגש". זה נכון רק אם צופה בודד שולח בקשה אחת. נגן וידאו שולח
# בקשות טווח ברצף, וכל אחת מהן נחשבה "זרם חדש" — ולכן שילמה שתי שניות.
#
# נמדד על השרת החי, ארבע בקשות טווח רצופות לאותו קובץ:
#
#     0.79s → 1.53s → 1.89s → 2.07s        (מתכנס בדיוק ל-2.0)
#
# ואחרי ‎STREAM_START_STAGGER=0‎, אותה בדיקה:
#
#     0.93s → 3.95s → 0.00s → 1.98s        (המדרגה נעלמה)
#
# ה-0.00 הוא הממצא החשוב: הגשה מיידית ממטמון הקצה. ההשהיה ישבה **לפני**
# בדיקת המטמון, ולכן גם תוכן מחומם לגמרי שילם שתי שניות — כלומר כל מטמון
# הקצה וכל עבודת החימום היו מנוטרלים.
#
# ## התיקון
#
# ההשהיה נשארת, אבל רק במקום שאליו היא נועדה: ממש לפני פתיחת זרם אמיתי
# מול טלגרם. בקשה שנענית מהמטמון אינה פותחת זרם ולכן אינה ממתינה, וכך גם
# בקשה שנכשלת על מטא-דאטה.
#
# ברירת המחדל יורדת מ-2.0 ל-0.3. 2.0 נבחר כשההשהיה חלה על כל בקשה והיה
# צריך להיות שמרני; עכשיו היא חלה רק על פתיחות אמיתיות, ו-2.0 היה מסרס
# עשרה צופים במקביל לעשרים שניות המתנה. הערך נשלט ב-
# STREAM_START_STAGGER ואפשר לכוון אותו בלי פריסה מחדש.
#
# ## בטיחות
#
# התאמה מדויקת או סירוב. גיבוי לפני כתיבה, בדיקת קומפילציה אחרי.
#
#   python3 patch_stagger.py [נתיב ל-main.py]
#   python3 patch_stagger.py --revert
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

MARK = "fix_stagger"

OLD_TOP = '''async def stream_from_channel(chat_id: int, message_id: int, request: Request):
    await _stagger_new_stream()
    meta = await stream_meta(chat_id, message_id)'''
NEW_TOP = '''async def stream_from_channel(chat_id: int, message_id: int, request: Request):
    # [fix_stagger] ההשהיה הייתה כאן, בשורה הראשונה, ולכן חלה על *כל*
    # בקשה — כולל בקשות שנענות מהמטמון בלי לגעת בטלגרם. היא מחזיקה
    # מנעול גלובלי, כלומר השרת כולו הוגבל לחצי בקשה בשנייה.
    #
    # נמדד, ארבע בקשות טווח רצופות: 0.79 → 1.53 → 1.89 → 2.07 שניות,
    # מתכנס בדיוק לערך ההשהיה. אחרי ביטולה, אותה בדיקה החזירה 0.00
    # שניות על בקשה שנענתה מהמטמון — כלומר כל עבודת החימום והמטמון
    # הייתה מנוטרלת על ידי השורה הזאת.
    #
    # היא עברה למטה, לנקודה שבה באמת נפתח זרם מול טלגרם.
    meta = await stream_meta(chat_id, message_id)'''

OLD_206 = '''        return StreamingResponse(
            _channel_range_gen(chat_id, message_id, start, end),
            status_code=206, media_type=mime_type, headers=headers)'''
NEW_206 = '''        # [fix_stagger] כאן נפתח זרם אמיתי מול טלגרם — וזו הנקודה שאליה
        # ההשהיה נועדה מלכתחילה. בקשה שנענתה מהמטמון כבר חזרה למעלה
        # ואינה מגיעה לכאן.
        await _stagger_new_stream()
        return StreamingResponse(
            _channel_range_gen(chat_id, message_id, start, end),
            status_code=206, media_type=mime_type, headers=headers)'''

OLD_200 = '''    return StreamingResponse(
        _channel_range_gen(chat_id, message_id, 0, file_size - 1),
        status_code=200, media_type=mime_type, headers=headers)'''
NEW_200 = '''    # [fix_stagger] אותו דבר במסלול הקובץ המלא.
    await _stagger_new_stream()
    return StreamingResponse(
        _channel_range_gen(chat_id, message_id, 0, file_size - 1),
        status_code=200, media_type=mime_type, headers=headers)'''

OLD_DEF = '''STREAM_START_STAGGER = float(os.environ.get("STREAM_START_STAGGER", "2.0"))'''
NEW_DEF = '''# [fix_stagger] 2.0 נבחר כשההשהיה חלה על כל בקשה, ולכן היה חייב להיות
# שמרני. עכשיו היא חלה רק על פתיחת זרם אמיתית, ושם 2.0 היה אומר שעשרה
# צופים שנכנסים יחד ממתינים עשרים שניות. ניתן לכוונון בלי פריסה מחדש.
STREAM_START_STAGGER = float(os.environ.get("STREAM_START_STAGGER", "0.3"))'''

PAIRS = [(OLD_DEF, NEW_DEF), (OLD_TOP, NEW_TOP),
         (OLD_206, NEW_206), (OLD_200, NEW_200)]


def main():
    d = os.path.dirname(P) or "."
    if REVERT:
        bak = sorted((f for f in os.listdir(d)
                      if f.startswith("main_before_stagger_")), reverse=True)
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

    bak = f"{d}/main_before_stagger_{time.strftime('%Y%m%d-%H%M%S')}.py"
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
    print("  ההשהיה עברה לנקודת פתיחת הזרם, אחרי בדיקת המטמון")
    print("  ברירת מחדל: 2.0 → 0.3 שניות")


if __name__ == "__main__":
    main()
