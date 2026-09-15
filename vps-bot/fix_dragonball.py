#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_dragonball.py — סדרות דרגון בול לקטגוריית אנימה, ותיקון השם "סדרה".

מה נמצא בקטלוג (נמדד, 13,172 פריטים):

    158 פרקים   דרגון בול קאי לעברית      157 ב"סדרות",  1 ב"אנימה"
    153 פרקים   דרגון בול לעברית          149 ב"סדרות",  4 ב"אנימה"
     64 פרקים   דרגון בול ג'יטי לעברית     63 ב"סדרות",  1 ב"אימה"  ← שגיאת כתיב
     19 פרקים   דרגון בול דאימה            18 ב"סדרות",  1 ב"אנימה"
     65 פרקים   שם הסדרה: "סדרה"           64 ב"סדרות",  1 ב"סדרות לילדים"
    131 פרקים   דרגון בול סופר            כולם ב"אנימה"   ← כבר תקין
     50 פרקים   דרגון בול                 כולם ב"אנימה"   ← כבר תקין

ה"סדרה" ששמה "סדרה" היא דרגון בול Z, ולא ניחשתי: הורדתי את הפוסטר שלה
מ-TMDB (8Nz9cmt9DzWJe8U5SpMzIvfhZ3E.jpg) והסתכלתי עליו — כתוב עליו
"דרגון בול Z" בעברית. גם השנה מתאימה: 1993 ב-35 מהפרקים.

הפיצול בין "סדרות" ל"אנימה" באותה סדרה הוא גם מה שגורם לסדרה להופיע
פעמיים בשורות שונות במסך הבית, כי הכרטיס נבנה לפי קטגוריה.

ה-id של כל פריט הוא UUID ולא נגזר מהשם, ולכן שינוי series_name ו-title
בטוח ולא שובר קישורים.

מה הסקריפט **לא** עושה: לא נוגע ב-custom_slug. לחלק מהסדרות אין slug
(‎dragon-ball-super יש, לאחרות אין), וזה משפיע על קישור ישיר — אבל
הוספת slug היא החלטה נפרדת, והוא מדווח עליה בלבד.

    python3 fix_dragonball.py --check
    python3 fix_dragonball.py
    python3 fix_dragonball.py --revert

בלי restart — האתר והאפליקציה מרעננים לפי content_version.
"""
import argparse, json, os, shutil, sys, time
from collections import Counter
from pathlib import Path

DATA = Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
VERSION = DATA / "content_version.txt"
BACKUP = CONTENT.with_name("content.json.bak_dragonball")

ANIME = "אנימה"

# שינוי שם: (השם הנוכחי, השם החדש). גם title מתעדכן, כי בסדרות התקינות
# title זהה ל-series_name — ראה "דרגון בול סופר".
RENAME = [("סדרה", "דרגון בול זד")]

# כל אלה עוברות לאנימה. הרשימה כוללת גם את מה שכבר שם, כדי שפרק בודד
# שנשאר מאחור ייאסף גם הוא.
TO_ANIME = [
    "דרגון בול לעברית",
    "דרגון בול קאי לעברית",
    "דרגון בול ג'יטי לעברית",
    "דרגון בול דאימה",
    "דרגון בול זד",          # אחרי השינוי שם
    "דרגון בול סופר",
    "דרגון בול",
    "דרגון בול זי",
]


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True); raise


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    if a.revert:
        if not BACKUP.exists():
            sys.exit(f"אין גיבוי ב-{BACKUP}")
        shutil.copy2(BACKUP, CONTENT)
        print(f"✓ שוחזר מ-{BACKUP}")
        return
    if not CONTENT.exists():
        sys.exit(f"לא נמצא: {CONTENT}")

    items = json.loads(CONTENT.read_text(encoding="utf-8"))
    renames, cats = [], []

    for old, new in RENAME:
        hits = [i for i in items if (i.get("series_name") or "").strip() == old]
        if not hits:
            print(f"⚠ לא נמצאה סדרה בשם {old!r} — מדלג")
            continue
        # אזהרה אם כבר קיימת סדרה בשם היעד: מיזוג בשוגג הוא לא מה שביקשנו
        clash = [i for i in items if (i.get("series_name") or "").strip() == new]
        if clash:
            print(f"⚠ כבר קיימת סדרה בשם {new!r} עם {len(clash)} פרקים — "
                  f"השינוי ימזג אותן. עוצר.")
            sys.exit(1)
        renames.append((old, new, hits))

    # שינוי השם מתבצע לוגית לפני חלוקת הקטגוריות, כדי ש"דרגון בול זד"
    # שברשימה יתפוס את הפרקים שרק עכשיו קיבלו את השם.
    renamed_names = {old: new for old, new, _ in renames}
    for name in TO_ANIME:
        src_names = [k for k, v in renamed_names.items() if v == name] or [name]
        hits = [i for i in items
                if (i.get("series_name") or "").strip() in src_names
                and (i.get("category") or "") != ANIME]
        if hits:
            cats.append((name, hits))

    print(f"קטלוג: {len(items)} פריטים\n" + "=" * 66)

    for old, new, hits in renames:
        titles = Counter((i.get("title") or "").strip() for i in hits)
        print(f"\n  שינוי שם: {old!r} → {new!r}   ({len(hits)} פרקים)")
        print(f"     title כיום: {dict(titles)}  →  {new!r}")

    total_cat = 0
    print(f"\n  מעבר לקטגוריית {ANIME!r}:")
    for name, hits in cats:
        prev = Counter((i.get("category") or "(ריק)") for i in hits)
        total_cat += len(hits)
        print(f"     {name:<26} {len(hits):>4} פרקים   מ-{dict(prev)}")
    if not cats:
        print("     אין מה להעביר — הכול כבר באנימה.")

    # דיווח בלבד: אין slug
    noslug = {}
    for name in TO_ANIME:
        g = [i for i in items if (i.get("series_name") or "").strip() == name]
        if g and not any(i.get("custom_slug") for i in g):
            noslug[name] = len(g)
    if noslug:
        print(f"\n  ℹ בלי custom_slug (קישור ישיר לא יעבוד) — לא נוגעים:")
        for n, c in noslug.items():
            print(f"     {n} ({c} פרקים)")

    print("\n" + "=" * 66)
    print(f"סה\"כ: {sum(len(h) for _, _, h in renames)} פרקים ישנו שם · "
          f"{total_cat} פרקים יעברו קטגוריה")

    if a.check:
        print("\n--check: שום דבר לא נכתב.")
        return
    if not renames and not cats:
        print("אין מה לשנות.")
        return

    shutil.copy2(CONTENT, BACKUP)
    for old, new, hits in renames:
        for i in hits:
            i["series_name"] = new
            if (i.get("title") or "").strip() == old:
                i["title"] = new
    for _, hits in cats:
        for i in hits:
            i["category"] = ANIME
    atomic_write(CONTENT, json.dumps(items, ensure_ascii=False, indent=2))
    try:
        v = int(VERSION.read_text().strip()) + 1 if VERSION.exists() else 1
    except Exception:
        v = int(time.time())
    atomic_write(VERSION, str(v))
    print(f"\n✓ נכתב · גיבוי: {BACKUP} · גרסה {v}")
    print("  בלי restart.")


if __name__ == "__main__":
    main()
