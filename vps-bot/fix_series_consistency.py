#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_series_consistency — פרקים של אותה סדרה מסכימים ביניהם.

דוד: "רוב הסרטים לא נמצאים בקטגוריה שלהם, מעורבב". וזה מצב שקורה
מעצמו: פרקים נוספים לקטלוג לאורך זמן, כל אחד בקטגוריה שנבחרה באותו
רגע, ואחרי עונה-שתיים אותה סדרה מפוזרת על שתיים-שלוש קטגוריות. למשתמש
זה נראה בדיוק כמו בלגן.

זה נפתר **בלי שום נתון חיצוני**: סדרה אחת היא יצירה אחת, ולכן כל
פרקיה שייכים לאותה קטגוריה ולאותו tmdb_id. מה שצריך זה רק להסכים.

שני תיקונים, שניהם דטרמיניסטיים:

    1. tmdb_id  אם לפרק אחד בסדרה יש מזהה ולשאר אין — הוא נכון לכולם.
                זה גם מרחיב את הכיסוי של כל השלבים הבאים בחינם, כי
                fix_categories ו-tmdb_enrich עובדים רק על מה שיש לו
                מזהה.
    2. category  רוב הפרקים קובע. סדרה מפוזרת מתאחדת לקטגוריה שבה
                 יושבים רובם.

ומה שלא נוגעים בו, במפורש:
    סדרה ששני פרקים שלה נושאים מזהים **שונים** — זו סתירה אמיתית,
    אולי שתי סדרות עם אותו שם, ואיחוד היה הופך חצי מהן לשגויות.
    היא מדווחת ולא מתוקנת.
    תיקו בקטגוריות (50/50) — אין רוב, ואין סיבה להעדיף צד.

    python3 fix_series_consistency.py --check
    python3 fix_series_consistency.py --ids-only --check
    python3 fix_series_consistency.py
    python3 fix_series_consistency.py --revert
"""
import argparse, importlib.util, json, os, shutil, sys, time
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))

# הקטגוריות הגנריות — סוג בלבד, בלי מקור/קהל/ז'אנר. סדרה שכל פרקיה
# גנריים תאוחד; סדרה שחלק מפרקיה בקטגוריה ספציפית לא תיגרר לגנרי
# ברוב, כי הספציפי כמעט תמיד הנכון וההזרמה היא שיצרה את הגנרי.
GENERIC_CATS = {"סדרות", "סרטים"}


def _load_enrich():
    """CONTENT/VERSION/atomic_write מגיעים מ-tmdb_enrich, לא משוכפלים."""
    p = os.path.join(_HERE, "tmdb_enrich.py")
    if not os.path.exists(p):
        sys.exit(f"לא נמצא {p} — הכלי הזה מייבא ממנו.")
    spec = importlib.util.spec_from_file_location("_tmdb_enrich", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def plan(items: list, do_ids=True, do_cats=True) -> tuple:
    """מה היה משתנה. לא כותב — רק מחשב.

    מחזיר (שינויים, סתירות_מזהה, תיקו_קטגוריה, סטטיסטיקה).
    """
    series = {}
    for it in items:
        if it.get("is_live"):
            continue
        sn = str(it.get("series_name") or "").strip()
        if sn:
            series.setdefault(sn, []).append(it)

    changes, id_clash, cat_tie, cat_defer = [], [], [], []
    stat = Counter()
    stat["סדרות"] = len(series)
    for sn, eps in series.items():
        # ── מזהה ──
        ids = Counter(str(e["tmdb_id"]) for e in eps
                      if e.get("tmdb_id") and str(e["tmdb_id"]) != "0")
        if do_ids:
            if len(ids) > 1:
                id_clash.append((sn, len(eps), dict(ids)))
            elif len(ids) == 1:
                tid, have = next(iter(ids.items()))
                missing = [e for e in eps
                           if not e.get("tmdb_id") or str(e["tmdb_id"]) == "0"]
                if missing:
                    stat["סדרות שהמזהה הושלם בהן"] += 1
                    for e in missing:
                        changes.append((e, sn, "tmdb_id", e.get("tmdb_id"),
                                        int(tid) if tid.isdigit() else tid))

        # ── קטגוריה ──
        if not do_cats:
            continue
        cats = Counter(str(e.get("category") or "").strip() for e in eps
                       if str(e.get("category") or "").strip())
        if not cats:
            continue                      # אין ממה להסיק
        top = cats.most_common()
        # אין כאן קיצור-דרך ל"קטגוריה אחת בלבד", בכוונה: סדרה שכל
        # פרקיה ב"אנימה" חוץ מאחד שהקטגוריה שלו **ריקה** נראית למשתמש
        # כמו בלגן בדיוק כמו סדרה מפוצלת. הריקים לא נספרים ברוב, אבל
        # הם כן מתמלאים ממנו. כשאין ריקים ואין פיצול, win שווה לקיים
        # וממילא לא נרשם שינוי.
        if len(top) > 1 and top[0][1] == top[1][1]:
            cat_tie.append((sn, len(eps), dict(cats)))
            continue
        win = top[0][0]
        # הרוב אינו תמיד הצודק. Asfur נמדדה עם 21 פרקים ב"סדרות
        # ישראליות" — הקטגוריה הנכונה, כי זו סדרת ילדים ישראלית —
        # והרוב ב"סדרות" הגנרי משך אותם למטה, רק כי יותר פרקים תויגו
        # לא נכון בהזרמה. כשהמנצח גנרי אבל קיימת קטגוריה ספציפית,
        # לא מכריעים כאן: fix_categories, שרץ מיד אחרי עם נתוני TMDB,
        # יקבע נכון. גנרי מנצח רק כשכל הקטגוריות גנריות.
        if win in GENERIC_CATS and any(c not in GENERIC_CATS for c in cats):
            cat_defer.append((sn, len(eps), dict(cats)))
            continue
        off = [e for e in eps
               if str(e.get("category") or "").strip() != win]
        if off:
            stat["סדרות שהקטגוריה אוחדה בהן"] += 1
            for e in off:
                changes.append((e, sn, "category",
                                str(e.get("category") or "").strip(), win))
    return changes, id_clash, cat_tie, cat_defer, stat


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--ids-only", action="store_true",
                    help="רק להשלים מזהים, בלי לאחד קטגוריות")
    ap.add_argument("--cats-only", action="store_true",
                    help="רק לאחד קטגוריות, בלי להשלים מזהים")
    a = ap.parse_args()
    if a.ids_only and a.cats_only:
        ap.error("--ids-only ו---cats-only סותרים")

    E = _load_enrich()
    CONTENT, VERSION = E.CONTENT, E.VERSION
    BACKUP = CONTENT.with_name("content.json.bak_series")

    if a.revert:
        if not BACKUP.exists():
            sys.exit(f"אין גיבוי ב-{BACKUP}")
        shutil.copy2(BACKUP, CONTENT)
        print(f"✓ שוחזר מ-{BACKUP}")
        return
    if not CONTENT.exists():
        sys.exit(f"לא נמצא: {CONTENT}")

    items = json.loads(CONTENT.read_text(encoding="utf-8"))
    changes, id_clash, cat_tie, cat_defer, stat = plan(
        items, do_ids=not a.cats_only, do_cats=not a.ids_only)

    print(f"קטלוג: {len(items)} פריטים · {stat['סדרות']} סדרות")
    print("אפס קריאות רשת · אפס טוקנים\n" + "=" * 62)

    if id_clash:
        print(f"\n⚠ {len(id_clash)} סדרות שפרקיהן נושאים מזהים שונים — "
              "לא נוגעים בהן.")
        print("   אולי שתי סדרות שונות עם אותו שם. איחוד היה הופך "
              "חצי מהפרקים לשגויים:")
        for sn, n, d in id_clash[:10]:
            print(f"      {sn[:26]:<28} {n:>4} פרקים · {d}")
        if len(id_clash) > 10:
            print(f"      ...ועוד {len(id_clash)-10}")

    if cat_tie:
        print(f"\n⚠ {len(cat_tie)} סדרות בתיקו קטגוריות — אין רוב, "
              "ואין סיבה להעדיף צד:")
        for sn, n, d in cat_tie[:10]:
            print(f"      {sn[:26]:<28} {n:>4} פרקים · {d}")
        if len(cat_tie) > 10:
            print(f"      ...ועוד {len(cat_tie)-10}")

    if cat_defer:
        print(f"\n⚠ {len(cat_defer)} סדרות שרובן בקטגוריה גנרית אבל חלקן "
              "בספציפית — לא מאחדים כאן.")
        print("   הרוב הגנרי בדרך כלל תוצאת הזרמה; fix_categories יכריע "
              "מ-TMDB:")
        for sn, n, d in cat_defer[:10]:
            print(f"      {sn[:26]:<28} {n:>4} פרקים · {d}")
        if len(cat_defer) > 10:
            print(f"      ...ועוד {len(cat_defer)-10}")

    if not changes:
        print("\nכל הסדרות עקביות. אין מה לתקן.")
        return

    by_field = Counter(f for _, _, f, _, _ in changes)
    print(f"\n{len(changes)} פריטים ישתנו: {dict(by_field)}")
    for k, v in stat.most_common():
        if k != "סדרות":
            print(f"   {k:<30} {v:>4}")

    if by_field.get("tmdb_id"):
        print("\nהשלמת מזהה (פרק אחד בסדרה ידע, השאר לא):")
        seen = set()
        for e, sn, f, old, new in changes:
            if f != "tmdb_id" or sn in seen:
                continue
            seen.add(sn)
            cnt = sum(1 for x, s, ff, _, _ in changes
                      if ff == "tmdb_id" and s == sn)
            print(f"   {sn[:26]:<28} → {new}   ({cnt} פרקים)")
            if len(seen) >= 12:
                print(f"   ...ועוד {stat['סדרות שהמזהה הושלם בהן']-12} סדרות")
                break

    if by_field.get("category"):
        print("\nאיחוד קטגוריה (הרוב קובע):")
        seen = set()
        for e, sn, f, old, new in changes:
            if f != "category" or sn in seen:
                continue
            seen.add(sn)
            froms = Counter(o for _, s, ff, o, _ in changes
                            if ff == "category" and s == sn)
            print(f"   {sn[:26]:<28} → {new[:22]:<24} "
                  f"מ-{dict(froms)}")
            if len(seen) >= 12:
                print(f"   ...ועוד "
                      f"{stat['סדרות שהקטגוריה אוחדה בהן']-12} סדרות")
                break

    print("\n" + "=" * 62)
    if a.check:
        print("--check: שום דבר לא נכתב.")
        return

    shutil.copy2(CONTENT, BACKUP)
    for e, sn, f, old, new in changes:
        e[f] = new
    E.atomic_write(CONTENT, json.dumps(items, ensure_ascii=False, indent=2))
    try:
        v = int(VERSION.read_text().strip()) + 1 if VERSION.exists() else 1
    except Exception:
        v = int(time.time())
    E.atomic_write(VERSION, str(v))
    print(f"✓ עודכנו {len(changes)} פריטים · גיבוי: {BACKUP} · גרסה {v}")
    print("  בלי restart. לביטול: python3 fix_series_consistency.py --revert")
    if by_field.get("tmdb_id"):
        print("\n  המזהים החדשים פותחים את שאר הצינור על אותם פרקים:")
        print("     python3 tmdb_enrich.py --check")
        print("     python3 fix_categories.py --check")


if __name__ == "__main__":
    main()
