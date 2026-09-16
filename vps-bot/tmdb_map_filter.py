#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tmdb_map_filter — מסנן מיפוי קיים לפי סף ביטחון, בלי לסרוק מחדש.

למה זה נדרש: tmdb_ai_match.py --run סורק את כל הקטלוג (כשעה), ושומר
בקובץ המיפוי את **כל** השורות עם הביטחון המספרי שלהן. אין שום סיבה
לסרוק שוב רק כדי לשנות סף — הנתון כבר על הדיסק.

ובעיה שנייה שזה פותר: תוויות הביטחון של tmdb_apply הן שלוש בלבד
(ודאי / סביר / ספק), ו-_conf_label ממפה כל 0.9 ומעלה ל"ודאי". כלומר
דרך התוויות אי אפשר להבחין בין 0.9 ל-0.99 — וזה בדיוק הגבול שנמדד
כמשמעותי:

    סף 0.90   94% דיוק · 89% כיסוי   (11 שגיאות מ-209)
    סף 0.99   99% דיוק · 70% כיסוי   ( 1 שגיאה  מ-165)

לכן הסינון נעשה כאן על המספר, והפלט הוא קובץ בפורמט שה-apply קורא.

    python3 tmdb_map_filter.py --min 0.99 --check
    python3 tmdb_map_filter.py --min 0.99
    python3 tmdb_map_filter.py --min 0.99 --out my_map.json
"""
import argparse, json, sys
from collections import Counter


def label(c: float) -> str:
    return "ודאי" if c >= 0.9 else ("סביר" if c >= 0.75 else "ספק")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="tmdb_ai_map.json",
                    help="המיפוי מ---run, או קובץ .partial של ריצה שנעצרה")
    ap.add_argument("--min", type=float, default=0.99)
    ap.add_argument("--out", default="")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    try:
        d = json.loads(open(a.src, encoding="utf-8").read())
    except FileNotFoundError:
        sys.exit(f"לא נמצא {a.src}. הוא נוצר ב-tmdb_ai_match.py --run.")

    # קובץ .partial: tmdb_ai_match שומר אותו כל 25 יחידות תחת המפתח
    # "rows", והמיפוי הסופי נכתב רק בסוף הריצה. בלי לקרוא אותו, ריצה
    # שנפלה באמצע מאבדת את כל מה שכבר נעשה — וזה בדיוק מה שקרה כמעט
    # כשההמתנות על 429 הגיעו ל-572 שניות ליחידה.
    if d.get("rows") and not d.get("accepted"):
        rows = list(d["rows"])
        print(f"קובץ חלקי: {d.get('done', '?')} מתוך {d.get('of', '?')} "
              f"יחידות נסרקו" + (f" (מדלג על {d['skip']})" if d.get("skip")
                                 else "") + "\n")
    else:
        rows = (d.get("accepted") or []) + (d.get("review") or [])
    if not rows:
        sys.exit(f"{a.src} ריק או בפורמט לא מוכר.")

    # מלכודת אמיתית: --validate ו---run כותבים לאותו שם קובץ כברירת מחדל.
    # קובץ אימות מכיל רק יחידות שכבר יש להן tmdb_id, ולכן tmdb_apply
    # היה מדלג על כולן ומדווח "0 שינויים" — שנראה כמו כלום לתקן, ולא
    # כמו הקובץ הלא-נכון. השדה correct קיים רק בקבצי אימות.
    if sum(1 for r in rows if "correct" in r) > len(rows) // 2:
        sys.exit(f"{a.src} הוא פלט של --validate ולא של --run: היחידות בו "
                 "כבר מזוהות,\nולכן tmdb_apply לא ישנה בהן כלום. צריך את "
                 "הקובץ מ---run.")

    keep, drop = [], []
    for r in rows:
        try:
            c = float(r.get("confidence") or 0)
        except (TypeError, ValueError):
            c = 0.0
        (keep if (r.get("tmdb_id") and c >= a.min) else drop).append((r, c))

    # המפתח זהה בדיוק למה ש-tmdb_apply מחפש: שם הסדרה לסדרות, id לפריט
    # בודד. שתי שורות שנופלות על אותו מפתח — הראשונה נשמרת, והשנייה לא
    # נספרת כעוברת, כדי שמה שמודפס יהיה מה שנכתב.
    out, wrote, clash, eps = {}, [], [], 0
    for r, c in keep:
        key = r["name"] if r.get("kind") == "series" else str(r.get("id") or r["name"])
        if key in out:
            clash.append((r, c))
            continue
        out[key] = {"kind": "tv" if r.get("kind") == "series" else "movie",
                    "query": r.get("query", ""), "tmdb_id": r["tmdb_id"],
                    "confidence": label(c)}
        wrote.append((r, c))
        eps += int(r.get("n") or 1)

    print(f"מקור: {a.src} · {len(rows)} יחידות · "
          f"דגם {d.get('model', '?')}")
    print(f"סף {a.min}\n")
    print(f"  עוברות:        {len(out):>4} יחידות → {eps} פריטים בקטלוג")
    print(f"  נופלות:        {len(drop):>4} יחידות")
    if clash:
        print(f"  כפילויות מפתח: {len(clash):>4} (נשמרה הראשונה, השנייה ירדה)")
        for r, c in clash[:3]:
            print(f"     {r['name'][:30]:<32} {r.get('media_type')}/{r['tmdb_id']}")
    dist = Counter(round(c, 2) for _, c in keep + drop)
    print(f"\n  התפלגות ביטחון בכל המיפוי: {dict(sorted(dist.items(), reverse=True))}")

    print("\n  דוגמאות שעוברות:")
    for r, c in wrote[:6]:
        print(f"     {r['name'][:30]:<32} → {r.get('media_type')}/{r['tmdb_id']} ({c})")
    print("\n  דוגמאות שנופלות (לבדיקה ידנית):")
    for r, c in sorted(drop, key=lambda x: -x[1])[:6]:
        print(f"     {r['name'][:30]:<32} ביטחון {c} · {str(r.get('why'))[:40]}")

    dest = a.out or a.src.replace(".json", "") + f"_ge{str(a.min).replace('.', '')}.json"
    if not out:
        # קובץ מיפוי ריק הוא מלכודת: tmdb_apply היה מדווח "0 שינויים"
        # כאילו אין מה להחיל, במקום לומר שהסף פשוט גבוה מדי.
        sys.exit(f"\nאף יחידה לא עברה את הסף {a.min} — שום קובץ לא נוצר.")
    if a.check:
        print(f"\n--check: שום דבר לא נכתב. היעד היה {dest}")
        return
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"\n✓ נשמר: {dest}  ({len(out)} רשומות)")
    print(f"  להחלה:  python3 tmdb_apply.py --map {dest} --check")


if __name__ == "__main__":
    main()
