#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# FLOOD_PREMIUM_WAIT — החניקה שמעולם לא ראינו.
#
# ## העיוורון
#
# Pyrogram 2.0.106 שוחרר בדצמבר 2022. טלגרם הוסיפו את ‎FLOOD_PREMIUM_WAIT‎
# ב-2024. אומת על השרת:
#
#     grep -rl "FLOOD_PREMIUM_WAIT" .../pyrogram/errors/  →  לא נמצא
#
# כלומר הספרייה אינה ממפה את השגיאה ל-‎FloodWait‎. היא נופלת ל-‎except
# Exception‎ הגנרי, ולכן "אפס FloodWait ב-24 שעות" — המספר שעליו נשענו —
# מדד שאנחנו לא מזהים אותה, לא שהיא לא קורית.
#
# ## ומה הקוד עשה איתה
#
#     except Exception as e:
#         _mark_choked(bot, 30, e)
#
# ‎hard=False‎, ולכן היא נספרת ככשל *רך*: הקוד מדפיס "עדיין בשירות" וממשיך
# להפציץ את אותו בוט — בדיוק מה שמאריך את העונש לפי התיעוד — ורק אחרי
# ‎CHOKE_AFTER_FAILS‎ מחיל 30 שניות **משלנו**, עם הסלמה, במקום את הזמן
# שטלגרם ביקש במפורש.
#
# ## התיקון
#
# זיהוי בתוך ‎_mark_choked‎ — נקודה אחת שכל 12 הקריאות עוברות דרכה:
#
#   · הזמן נלקח מהשגיאה עצמה (‎FLOOD_PREMIUM_WAIT_7‎ → 8 שניות), לא מניחוש
#   · ‎hard=True‎ — קירור מיידי במקום להמשיך להפציץ
#   · ‎escalate=False‎ — טלגרם אמר כמה, לא מכפילים אותו
#   · מונה ‎flood_premium‎ ב-/debug/caches — סוף העיוורון
#
# הבוט המקורר פשוט מדולג, והבקשה הבאה הולכת לבוט אחר. זו התנהגות קיימת.
#
# ## למה דווקא עכשיו
#
# בלי זה, כל העלאה של מקביליות (512KB, יותר חיבורים, פיזור בין בוטים)
# תגדיל את הסיכוי לפגוע בתקרה — ואנחנו נראה בוטים "נכשלים" בלי לדעת למה,
# ונסיק שטלגרם חוסמים אותנו.
#
#   python3 patch_flood_premium.py [נתיב ל-main.py]
#   python3 patch_flood_premium.py --revert
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
MARK = "flood_premium"

OLD_COUNTER = '''_last_pool_success = 0.0'''
NEW_COUNTER = '''_last_pool_success = 0.0

# [flood_premium] כמה פעמים טלגרם חנק אותנו על היעדר Premium.
#
# עד כה המספר הזה לא היה קיים, ו-FloodWait הראה אפס — לא כי לא נחנקנו
# אלא כי Pyrogram 2.0.106 אינו מכיר את שם השגיאה. זה המונה שהופך את
# "אנחנו לא נוגעים בתקרה" מהנחה למדידה.
_flood_premium_hits = 0'''

OLD_FN = '''def _mark_choked(bot, seconds, err=None, hard=False, escalate=True):
    # "Peer id invalid" הוא לא חניקה אלא בוט ששכח את הערוץ: cooldown לבדו לא'''
NEW_FN = '''def _mark_choked(bot, seconds, err=None, hard=False, escalate=True):
    # [flood_premium] החניקה על היעדר Premium, שעד כה נראתה ככשל רגיל.
    #
    # Pyrogram 2.0.106 אינו ממפה את FLOOD_PREMIUM_WAIT ל-FloodWait, ולכן
    # היא הגיעה לכאן מה-except הגנרי עם seconds=30 ו-hard=False — כלומר
    # נספרה ככשל רך, הקוד המשיך להפציץ את אותו בוט (מה שמאריך את העונש),
    # ובסוף הוחל קירור מומצא במקום זה שטלגרם ביקש.
    #
    # גם CODE==420 נבדק: אם Pyrogram יעטוף את השגיאה בלי שם מוכר, הקוד
    # המספרי עדיין מזהה אותה כחניקה.
    global _flood_premium_hits
    _txt = str(err).upper() if err is not None else ""
    _code = getattr(err, "CODE", None)
    if "FLOOD_PREMIUM_WAIT" in _txt or (_code == 420 and "FLOOD" in _txt):
        _flood_premium_hits += 1
        _m = re.search(r"FLOOD[_A-Z]*WAIT_?(\\d+)", _txt)
        if _m:
            seconds = int(_m.group(1)) + 1
        hard = True          # קירור מיידי — לא "עדיין בשירות"
        escalate = False     # טלגרם נקב בזמן; לא מכפילים אותו
        log.warning("🐢 FLOOD_PREMIUM_WAIT על %s — מקרר %ds (פגיעה מס' %d)",
                    bot.get("name", "?"), seconds, _flood_premium_hits)
    # "Peer id invalid" הוא לא חניקה אלא בוט ששכח את הערוץ: cooldown לבדו לא'''

OLD_DBG = '''        "edge_filling": len(_edge_filling),'''
NEW_DBG = '''        "edge_filling": len(_edge_filling),
        # [flood_premium] אם זה גדל — טלגרם כן חונקים אותנו, ועד היום לא
        # ידענו. אם הוא נשאר 0 תחת עומס אמיתי — יש לנו מרווח לטפס.
        "flood_premium": _flood_premium_hits,'''

PAIRS = [(OLD_COUNTER, NEW_COUNTER), (OLD_FN, NEW_FN), (OLD_DBG, NEW_DBG)]


def main():
    d = os.path.dirname(P) or "."
    if REVERT:
        bak = sorted((f for f in os.listdir(d)
                      if f.startswith("main_before_floodprem_")), reverse=True)
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
    if "\nimport re" not in s and "\nimport re\n" not in s:
        if "import re" not in s.split("\n\n")[0] and "import re" not in s[:4000]:
            sys.exit("❌ ‎re‎ לא מיובא בראש הקובץ — לא נגעתי בכלום")

    for i, (old, _) in enumerate(PAIRS, 1):
        n = s.count(old)
        if n != 1:
            sys.exit(f"❌ קטע {i} מתוך {len(PAIRS)} לא נמצא בדיוק פעם אחת "
                     f"({n}). לא נגעתי בכלום — שלח לי את הפלט.")

    bak = f"{d}/main_before_floodprem_{time.strftime('%Y%m%d-%H%M%S')}.py"
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
    print("  הזמן נלקח מהשגיאה, קירור מיידי, בלי הסלמה")
    print("  מונה flood_premium נחשף ב-/debug/caches")


if __name__ == "__main__":
    main()
