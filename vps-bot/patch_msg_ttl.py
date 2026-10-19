#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# מטמון ההודעות פג אחרי 15 דקות — באמצע הסרט, לא בסופו.
#
# ## התסמין
#
# "חלק ב-20 הדקות הראשונות, ואז מתחיל להיתקע כל כמה שניות."
#
# ## הסיבה
#
# כל בוט מחזיק מטמון משלו להודעה של הפריט, כי ה-file_reference תקף רק
# בהקשר הסשן ששלף אותו. הערך היה:
#
#     _BOT_MSG_TTL = 900     # 15 דק' — נשאר "חם" לאורך צפייה שלמה
#
# ההערה מתארת את הכוונה, לא את המציאות: סרט הוא 90 עד 120 דקות, ולכן
# 15 דקות הן שמינית מצפייה שלמה ולא צפייה שלמה.
#
# מה שקורה בפועל: בתחילת הצפייה כל בוט שמשרת מתחמם, והניגון חלק. אחרי
# רבע שעה הרשומות מתחילות לפוג אחת-אחת, ומאז כל בקשת טווח שנוחתת על בוט
# שפג חייבת קודם ‎get_messages‎ מול טלגרם — סבב רשת שלם לפני שבית אחד של
# וידאו זז. הבוטים מתחלפים בסיבוב, ולכן פוגעים בבוט קר שוב ושוב: תקיעה
# כל כמה שניות, בדיוק מהנקודה הזאת ואילך.
#
# ## התיקון
#
# TTL שמכסה סרט שלם (שלוש שעות), דרך STREAM_BOT_MSG_TTL.
#
# זה בטוח: אם ה-file_reference באמת פג בינתיים, הקוד כבר תופס
# FileReferenceExpired ושולף מחדש — זה המנגנון שההערה המקורית מתארת.
# כלומר אנחנו לא מאריכים תוקף של משהו, רק מפסיקים לזרוק מטמון תקין לפני
# הזמן ולשלם על כך סבב רשת.
#
# הזיכרון חסום כמו קודם ב-_BOT_MSG_CACHE_MAX (4000 רשומות). עם TTL ארוך
# יותר הפינוי יסתמך פחות על פקיעה ויותר על התקרה, וזו בדיוק ההתנהגות
# שכבר כתובה שם.
#
# ## בטיחות
#
# התאמה מדויקת או סירוב. גיבוי לפני כתיבה, בדיקת קומפילציה אחרי.
#
#   python3 patch_msg_ttl.py [נתיב ל-main.py]
#   python3 patch_msg_ttl.py --revert
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

MARK = "STREAM_BOT_MSG_TTL"

OLD = '''_BOT_MSG_TTL = 900          # 15 דק' — נשאר "חם" לאורך צפייה שלמה (בקשות Range
                            # פרוסות על כל אורך הסרט). אם ה-file_reference פג
                            # באמצע — נתפס כ-FileReferenceExpired ונשלף מחדש.'''

NEW = '''# [fix_msg_ttl] היה 900 — רבע שעה — עם הערה שזה "לאורך צפייה שלמה".
# ההערה תיארה את הכוונה ולא את המציאות: סרט הוא 90 עד 120 דקות.
#
# דווח מהשטח: "חלק ב-20 הדקות הראשונות, ואז מתחיל להיתקע כל כמה שניות".
# זה בדיוק מה שהערך הזה מייצר. בתחילת הצפייה כל בוט שמשרת מתחמם; אחרי
# רבע שעה הרשומות פגות אחת-אחת, ומאז כל בקשת טווח שנוחתת על בוט שפג
# משלמת get_messages מול טלגרם לפני שבית אחד של וידאו זז. הבוטים
# מתחלפים בסיבוב, ולכן פוגעים בבוט קר שוב ושוב.
#
# שלוש שעות מכסות סרט שלם. זה אינו מאריך תוקף של דבר: אם
# ה-file_reference פג, הקוד תופס FileReferenceExpired ושולף מחדש —
# המנגנון שההערה המקורית מתארת. אנחנו רק מפסיקים לזרוק מטמון תקין
# לפני הזמן.
_BOT_MSG_TTL = int(os.environ.get("STREAM_BOT_MSG_TTL", str(3 * 3600)))'''


def main():
    d = os.path.dirname(P) or "."
    if REVERT:
        bak = sorted((f for f in os.listdir(d)
                      if f.startswith("main_before_msgttl_")), reverse=True)
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

    n = s.count(OLD)
    if n != 1:
        sys.exit(f"❌ הקטע לא נמצא בדיוק פעם אחת ({n} התאמות) ב-{P}.\n"
                 f"   לא נגעתי בכלום — שלח לי את הפלט.")

    bak = f"{d}/main_before_msgttl_{time.strftime('%Y%m%d-%H%M%S')}.py"
    shutil.copy(P, bak)
    io.open(P, "w", encoding="utf-8").write(s.replace(OLD, NEW, 1))

    try:
        py_compile.compile(P, doraise=True)
    except Exception as e:
        shutil.copy(bak, P)
        sys.exit(f"❌ לא עובר קומפילציה — שוחזר.\n   {e}")

    print(f"✓ הוחל. גיבוי: {bak}")
    print("  מטמון ההודעות: 15 דקות → 3 שעות")


if __name__ == "__main__":
    main()
