#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ai_cost_calc — כמה באמת יעלה להעביר את ה-AI של בוט הקבוצות ל-Gemini.

הרעיון "נשתמש בכמה מפתחות Gemini וזה ירוץ אצל גוגל" נכון בחלקו ושגוי
בחלקו, ושני החלקים ניתנים לחישוב.

## מה שנבדק מול התיעוד הרשמי (ספטמבר 2026)

  • המכסה נספרת **לפי פרויקט ולא לפי מפתח**. חמישה מפתחות באותו פרויקט
    חולקים בדיוק אותה מכסה. ai.google.dev/gemini-api/docs/rate-limits
  • תנאי ה-API של גוגל: "You agree to, and will not attempt to circumvent,
    such limitations". כלומר פתיחת פרויקטים נוספים כדי להכפיל מכסה חינמית
    היא הפרה — והסיכון הוא סגירת החשבונות, לא קנס. developers.google.com/terms
  • מחירי Flash-Lite בתשלום: 0.30$ למיליון טוקני קלט, 2.50$ למיליון פלט.

## מה שהכלי מחשב

  1. עלות בדולרים לפי נפח ההודעות שלך.
  2. כמה זה יורד כשמסננים מקומית ושולחים ל-AI רק את החשודות.
  3. כמה **רוחב פס יוצא** ייאכל בהעלאת קול ווידאו לגוגל — וזה החלק
     שמתחרה ישירות בצופים של zovex, כי זו אותה יציאה.

    python3 ai_cost_calc.py
    python3 ai_cost_calc.py --messages 200000 --groups 10
"""
import argparse
import sys

# מחירון Flash-Lite, דולר למיליון טוקנים (נבדק ב-ai.google.dev/gemini-api/docs/pricing)
IN_PER_M = 0.30
OUT_PER_M = 2.50

# צריכת טוקנים בקריאת מודרציה טיפוסית
PROMPT_TOKENS = 300      # הוראות המערכת
MSG_TOKENS = 50          # הודעה ממוצעת בקבוצה
OUT_TOKENS = 30          # פסק דין קצר ב-JSON

# משקל מדיה להעלאה, בבייטים
VOICE_BYTES = 30 * 1024          # הודעה קולית של חצי דקה, opus
IMAGE_BYTES = 250 * 1024         # תמונה בטלגרם אחרי דחיסה
VIDEO_BYTES = 8 * 1024 * 1024    # קליפ קצר


def money(x):
    return f"${x:,.2f}"


def gb(b):
    return b / 1024 ** 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--messages", type=int, default=20000,
                    help="הודעות טקסט ביום, בכל הקבוצות יחד")
    ap.add_argument("--groups", type=int, default=1)
    ap.add_argument("--images", type=int, default=200, help="תמונות ביום")
    ap.add_argument("--voices", type=int, default=100, help="הודעות קוליות ביום")
    ap.add_argument("--videos", type=int, default=20, help="סרטונים ביום")
    ap.add_argument("--suspicious", type=float, default=2.0,
                    help="אחוז ההודעות שהמסנן המקומי מסמן כחשודות")
    a = ap.parse_args()

    print(f"נפח שהוזן: {a.messages:,} הודעות/יום ב-{a.groups} קבוצות, "
          f"{a.images:,} תמונות, {a.voices:,} קוליות, {a.videos:,} סרטונים\n")

    def text_cost(n):
        inp = n * (PROMPT_TOKENS + MSG_TOKENS) / 1e6 * IN_PER_M
        out = n * OUT_TOKENS / 1e6 * OUT_PER_M
        return inp + out

    print("═══════ 1. AI על כל הודעת טקסט ═══════")
    d = text_cost(a.messages)
    print(f"  {a.messages:,} קריאות ביום")
    print(f"  ליום:   {money(d)}")
    print(f"  לחודש:  {money(d * 30)}")
    print(f"  לשנה:   {money(d * 365)}")

    n_sus = int(a.messages * a.suspicious / 100)
    ds = text_cost(n_sus)
    print(f"\n═══════ 2. סינון מקומי קודם, AI רק ל-{a.suspicious:g}% החשודות ═══════")
    print(f"  {n_sus:,} קריאות ביום במקום {a.messages:,}")
    print(f"  ליום:   {money(ds)}")
    print(f"  לחודש:  {money(ds * 30)}")
    print(f"  לשנה:   {money(ds * 365)}")
    if d > 0:
        print(f"  ← חיסכון של {100 * (1 - ds / d):.0f}% על אותה הגנה")

    print("\n═══════ 3. רוחב פס יוצא — כאן זה נוגע בצופים ═══════")
    print("  העברת העיבוד לגוגל לא מייתרת את ההעלאה. כל קובץ קול, תמונה")
    print("  או וידאו צריך לצאת מהשרת שלך אל גוגל — באותו קו שמזרים סרטים.")
    up = (a.images * IMAGE_BYTES + a.voices * VOICE_BYTES + a.videos * VIDEO_BYTES)
    print(f"    תמונות : {gb(a.images * IMAGE_BYTES) * 1024:7.1f}MB ליום")
    print(f"    קוליות : {gb(a.voices * VOICE_BYTES) * 1024:7.1f}MB ליום")
    print(f"    וידאו  : {gb(a.videos * VIDEO_BYTES) * 1024:7.1f}MB ליום")
    print(f"    סה\"כ   : {gb(up) * 1024:7.1f}MB ליום  ·  {gb(up) * 30:.1f}GB לחודש")
    mbit = up * 8 / 86400 / 1e6
    print(f"  ממוצע פרוס על היממה: {mbit:.2f} מגהביט/שנייה")
    if mbit < 0.5:
        print("  ← זניח מול הזרמת וידאו. לא ירגישו.")
    elif mbit < 3:
        print("  ← מורגש בשעות שיא. כדאי לתזמן לשעות שקטות.")
    else:
        print("  ⚠ זה כבר נתח אמיתי מהקו שמשרת צופים.")

    print("\n═══════ 4. מכסה חינמית ═══════")
    print("  המכסה נספרת לפי פרויקט ולא לפי מפתח, ולכן חמישה מפתחות")
    print("  באותו פרויקט = אותה מכסה בדיוק. חמישה פרויקטים כדי להכפיל")
    print("  מכסה חינמית הם הפרה מפורשת של תנאי ה-API של גוגל, והסיכון")
    print("  הוא סגירת החשבונות — כלומר המערכת כולה נופלת ביום אחד.")
    print("  המסקנה המעשית: לסנן מקומי, ולשלם על מה שבאמת צריך AI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
