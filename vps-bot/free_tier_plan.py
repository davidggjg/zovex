#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""free_tier_plan — האם אפשר להריץ את ה-AI של בוט הקבוצות בחינם, בלי טריקים.

## ההבחנה שהכל תלוי בה

  ✗ מספר חשבונות **באותו ספק** כדי להכפיל מכסה — זה מה שתנאי ה-API של
    גוגל אוסרים במפורש ("will not attempt to circumvent"), והנפילה בו
    היא של כל המפתחות ביחד.

  ✓ מספר **ספקים שונים**, חשבון אחד תקין בכל אחד — לגיטימי לחלוטין.
    כל ספק נותן מכסה חינמית ומצפה שישתמשו בה. זה גם עמיד יותר: ספק
    שנופל לא מפיל את המערכת, כי נשארו האחרים.

## מקורות המספרים

  Groq   — התיעוד הרשמי, console.groq.com/docs/rate-limits
  Gemini — גוגל מפנה ללוח המחוונים של AI Studio ואינה מפרסמת טבלה
           בתיעוד; המספרים כאן מדווחים ממקורות צד-שלישי ולכן מסומנים
           כ"לא רשמי". **תאמת אותם בלוח המחוונים שלך לפני שתסתמך עליהם.**

    python3 free_tier_plan.py --messages 50000
    python3 free_tier_plan.py --messages 1000000 --filter-rate 2
"""
import argparse
import sys

# (ספק, מודל, לשימוש, בקשות/דקה, בקשות/יום, מאומת רשמית)
TIERS = [
    ("Groq",   "Llama Prompt Guard", "סינון תוכן",      30, 14400, True),
    ("Groq",   "GPT-OSS / Qwen",     "הבנת הקשר",       30,  1000, True),
    ("Gemini", "Flash",              "הבנת הקשר",       15,  1500, False),
    ("Gemini", "Flash-Lite",         "סינון מהיר",      30,  1000, False),
]

# תמלול קול — נמדד ביחידות של שניות אודיו, לא בקשות
VOICE = ("Groq", "Whisper", 2000, 28800, True)   # בקשות/יום, שניות אודיו/יום


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--messages", type=int, default=50000,
                    help="הודעות טקסט ביום בכל הקבוצות יחד")
    ap.add_argument("--filter-rate", type=float, default=2.0,
                    help="אחוז ההודעות שהמנוע המקומי מעביר ל-AI")
    ap.add_argument("--voice-minutes", type=int, default=60,
                    help="דקות של הודעות קוליות ביום")
    a = ap.parse_args()

    need = int(a.messages * a.filter_rate / 100)
    print(f"נפח: {a.messages:,} הודעות/יום")
    print(f"המנוע המקומי מעביר ל-AI {a.filter_rate:g}% → {need:,} קריאות/יום\n")

    print("═══════ מכסות חינמיות, חשבון אחד בכל ספק ═══════")
    total_rpd = 0
    total_rpm = 0
    for prov, model, use, rpm, rpd, official in TIERS:
        mark = "רשמי" if official else "לא רשמי — לאמת"
        print(f"  {prov:7} {model:20} {use:12} {rpm:>3}/דקה {rpd:>7,}/יום   ({mark})")
        total_rpd += rpd
        total_rpm += rpm
    total_label = "סה״כ"
    print(f"  {'':7} {total_label:20} {'':12} {total_rpm:>3}/דקה {total_rpd:>7,}/יום")

    print("\n═══════ האם זה מספיק ═══════")
    if need <= total_rpd:
        spare = total_rpd - need
        print(f"  ✓ כן. צריך {need:,}, יש {total_rpd:,}. נשאר עודף של {spare:,} ביום.")
        print(f"    כלומר הנפח יכול לגדול פי {total_rpd / max(1, need):.1f} לפני שמשלמים.")
    else:
        short = need - total_rpd
        print(f"  ✗ לא. צריך {need:,}, יש {total_rpd:,}. חסרות {short:,} קריאות ביום.")
        ok_msgs = int(total_rpd / (a.filter_rate / 100))
        print(f"    המכסה הזאת מכסה עד {ok_msgs:,} הודעות/יום בשיעור סינון כזה.")
        need_rate = 100.0 * total_rpd / a.messages
        print(f"    או: להדק את המסנן ל-{need_rate:.2f}% במקום {a.filter_rate:g}%.")

    # תקרת הדקה היא לרוב מה שנשבר קודם, כי תעבורה אינה אחידה
    peak = need / 24 / 60
    print(f"\n  קצב ממוצע נדרש: {peak:.1f} קריאות/דקה מול {total_rpm}/דקה זמינות.")
    if peak * 10 > total_rpm:
        print("  ⚠ בשעת שיא זה יכול לגעת בתקרת הדקה. צריך תור שמווסת קצב,")
        print("    אחרת בקשות ייזרקו בדיוק כשהכי צריך אותן.")
    else:
        print("  ✓ גם פי 10 בשעת שיא נכנס בתקרת הדקה.")

    prov, model, rpd, asd, _ = VOICE
    print(f"\n═══════ תמלול קול ═══════")
    print(f"  {prov} {model}: {rpd:,} בקשות/יום, {asd:,} שניות אודיו/יום (רשמי)")
    print(f"  = {asd / 3600:.1f} שעות קול ביום, בחינם.")
    if a.voice_minutes * 60 <= asd:
        print(f"  ✓ {a.voice_minutes} דקות/יום נכנסות בנוחות.")
    else:
        print(f"  ✗ {a.voice_minutes} דקות/יום = {a.voice_minutes*60:,} שניות, מעל המכסה.")
    print("  זה פותר בדיוק את מה שאמרתי שלא ריאלי על השרת שלך — התמלול")
    print("  רץ אצלם, והשרת רק מעלה קובץ קול קטן.")

    print("\n═══════ מה שעדיין לא חינם ═══════")
    print("  ניתוח וידאו — פריימים ותמלול יחד. גם אצל ספקים זה יקר,")
    print("  וגם ההעלאה עצמה אוכלת מרוחב הפס שמשרת את הצופים.")
    print("  ההמלצה: לא לנתח וידאו אוטומטית. רק לפי דיווח או חשד.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
