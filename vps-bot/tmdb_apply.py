#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מחיל את מיפוי ה-tmdb_id שנמדד ב-tmdb_backfill.py על content.json.

זה השלב השני מתוך שניים, והוא זה שכותב. הראשון (tmdb_backfill.py) רק מדד
וייצר tmdb_map.json; כאן קוראים את המיפוי ומעדכנים את הקטלוג.

למה זה שווה: tmdb_id הוא התנאי לטריילר, לשם ולתקציר באנגלית, ולסיווג
אוטומטי. בלעדיו השרת לא יכול לשאול על הפריט שום דבר.

בטיחות:
  • ברירת המחדל מחילה רק התאמות "ודאי" ו"סביר". "ספק" נדרש במפורש.
  • גיבוי לפני כתיבה, לאותה תיקייה שבה השרת מגבה בעצמו.
  • מונה הגרסה עולה, אחרת המטמון בשרת ימשיך להגיש את הקטלוג הישן.
  • פריט שכבר יש לו tmdb_id לא נדרס לעולם.

    python3 tmdb_apply.py --check                 # מה היה קורה, בלי לכתוב
    python3 tmdb_apply.py                         # ודאי + סביר
    python3 tmdb_apply.py --confidence ודאי       # רק ההתאמות המדויקות
    python3 tmdb_apply.py --revert                # שחזור הגיבוי האחרון
"""
import argparse, glob, json, os, pathlib, shutil, sys, time
from collections import Counter

DATA = pathlib.Path(os.environ.get("DATA_DIR", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
BAKDIR = DATA / "content_backups"
VERSION = DATA / "content_version.txt"
DEFAULT_MAP = "tmdb_map.json"


def _fail(m):
    print(f"❌ {m}"); sys.exit(1)


def _bump():
    try:
        cur = int(VERSION.read_text(encoding="utf-8").strip())
    except Exception:
        cur = 0
    VERSION.write_text(str(cur + 1), encoding="utf-8")
    return cur + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default=DEFAULT_MAP)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--confidence", nargs="*", default=["ודאי", "סביר"],
                    help="אילו רמות ביטחון להחיל")
    a = ap.parse_args()

    if a.revert:
        baks = sorted(glob.glob(str(BAKDIR / "content_*.json")))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], CONTENT)
        v = _bump()
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}   גרסת תוכן: {v}")
        print("   אין צורך בריסטארט — מונה הגרסה מבטל את המטמון.")
        return

    if not CONTENT.exists():
        _fail(f"{CONTENT} לא נמצא")
    if not os.path.exists(a.map):
        _fail(f"{a.map} לא נמצא — צריך להריץ קודם tmdb_backfill.py")

    mapping = json.loads(open(a.map, encoding="utf-8").read())
    content = json.loads(CONTENT.read_text(encoding="utf-8"))
    allow = set(a.confidence)

    # המיפוי ממופתח פעמיים: לסרטים לפי מזהה הפריט, לסדרות לפי שם הסדרה.
    # כך שורה אחת במיפוי מכסה את כל פרקי הסדרה.
    by_series, by_id = {}, {}
    skipped_conf = Counter()
    for key, v in mapping.items():
        conf = v.get("confidence")
        if conf not in allow:
            skipped_conf[conf] += 1
            continue
        tid = v.get("tmdb_id")
        if not tid:
            continue
        (by_series if v.get("kind") == "tv" else by_id)[key] = tid

    changed = 0
    touched_series, touched_movies = set(), 0
    for m in content:
        if m.get("tmdb_id"):
            continue                      # לא דורסים מזהה קיים לעולם
        sn = (m.get("series_name") or "").strip()
        tid = by_series.get(sn) if sn else by_id.get(str(m.get("id")))
        if not tid:
            continue
        if not a.check:
            m["tmdb_id"] = tid
        changed += 1
        if sn:
            touched_series.add(sn)
        else:
            touched_movies += 1

    have_before = sum(1 for m in content if m.get("tmdb_id")) - (0 if a.check else changed)
    total = len(content)

    print(f"{'='*52}")
    print(f"פריטים בקטלוג            {total:>7}")
    print(f"היו עם tmdb_id           {have_before:>7}")
    print(f"יתווספו                  {changed:>7}   ({touched_movies} סרטים · "
          f"{len(touched_series)} סדרות)")
    print(f"סה\"כ אחרי               {have_before + changed:>7}   "
          f"({(have_before + changed) * 100 // max(1, total)}%)")
    if skipped_conf:
        print("\nלא הוחלו לפי רמת ביטחון:")
        for c, n in skipped_conf.most_common():
            print(f"   {c or '?':<8} {n}")
        print("   (להחלה: --confidence ודאי סביר ספק)")
    print("=" * 52)

    if a.check:
        print("\n✓ לא נכתב כלום (--check).")
        return
    if changed == 0:
        print("\nאין מה להחיל.")
        return

    BAKDIR.mkdir(parents=True, exist_ok=True)
    bak = BAKDIR / f"content_{int(time.time())}.json"
    bak.write_text(CONTENT.read_text(encoding="utf-8"), encoding="utf-8")
    # אותו פורמט שהשרת כותב בו, אחרת כל שמירה הבאה מהפאנל תיראה כשינוי ענק.
    CONTENT.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    v = _bump()
    print(f"\n✓ הוחל.  גיבוי: {bak.name}   גרסת תוכן: {v}")
    print("   אין צורך בריסטארט — מונה הגרסה מבטל את המטמון בשרת.")
    print("   לביטול: python3 tmdb_apply.py --revert")


if __name__ == "__main__":
    main()
