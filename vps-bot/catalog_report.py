"""דו"ח מצב הקטלוג — קריאה בלבד, לא משנה כלום.

נותן תמונה מלאה לפני סידור קטגוריות:
  · כמה פריטים בכל קטגוריה (וכל שמות הקטגוריות הקיימות)
  · האם כבר קיימת קטגוריית "מארוול"
  · כיסוי en_title / year (חשוב לזיהוי אוטומטי)
  · תצוגה מקדימה: אילו כותרות בקטלוג נראות כמו מארוול (לפי רשימה מוכרת)

    python3 catalog_report.py
    python3 catalog_report.py --titles      # מדפיס גם את כל שמות הסרטים/הסדרות
"""
import argparse
import os
import pathlib
import re
import sys
from collections import Counter

sys.path.insert(0, "/opt/zovex-bot")

ap = argparse.ArgumentParser()
ap.add_argument("--titles", action="store_true", help="להדפיס את כל הכותרות")
args = ap.parse_args()

ENV_FILE = pathlib.Path("/opt/zovex-bot/.env")
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip().lstrip("﻿")
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        k, v = line.split("=", 1)
        if "=" and k.strip():
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            os.environ[k.strip()] = v

from main import load_content                        # noqa: E402
from marvel import MARVEL_CATEGORY, looks_marvel       # noqa: E402


def main():
    content = load_content()
    print(f"סה\"כ פריטים בקטלוג: {len(content)}\n")

    cats = Counter(e.get("category") or "(ללא קטגוריה)" for e in content)
    print("── קטגוריות קיימות ──")
    for cat, n in cats.most_common():
        mark = "  ✅" if cat == MARVEL_CATEGORY else ""
        print(f"  {n:>5}  {cat}{mark}")
    print()
    if MARVEL_CATEGORY in cats:
        print(f"→ קטגוריית '{MARVEL_CATEGORY}' כבר קיימת ({cats[MARVEL_CATEGORY]} פריטים) — לא נפתח חדשה.\n")
    else:
        print(f"→ קטגוריית '{MARVEL_CATEGORY}' לא קיימת עדיין.\n")

    # כיסוי שדות (חשוב לזיהוי אוטומטי מול TMDB)
    movies = [e for e in content if not e.get("series_name")
              and not e.get("is_live") and e.get("category") != "שידורים חיים"]
    series = {}
    for e in content:
        if e.get("series_name") and not e.get("is_live"):
            series.setdefault(e["series_name"], e)
    with_en = sum(1 for e in content if (e.get("en_title") or "").strip())
    with_year = sum(1 for e in content if str(e.get("year") or "").strip())
    print("── כיסוי נתונים ──")
    print(f"  סרטים (בודדים):        {len(movies)}")
    print(f"  סדרות (ייחודיות):      {len(series)}")
    print(f"  יש en_title:           {with_en}/{len(content)}")
    print(f"  יש year:               {with_year}/{len(content)}\n")

    # תצוגה מקדימה של מארוול
    marvel_movies = [e for e in movies if looks_marvel(e.get("en_title"), e.get("title"))
                     and e.get("category") != MARVEL_CATEGORY]
    marvel_series = [(nm, e) for nm, e in series.items()
                     if looks_marvel(e.get("en_title"), nm)
                     and e.get("category") != MARVEL_CATEGORY]
    print("── מועמדים ל'מארוול' (לפי זיהוי כותרת) ──")
    print(f"  סרטים: {len(marvel_movies)} · סדרות: {len(marvel_series)}")
    for e in marvel_movies[:40]:
        print(f"    🎬 {(e.get('title') or '?')[:40]:<40} | {(e.get('en_title') or '')[:32]:<32} | {e.get('category')}")
    for nm, e in marvel_series[:40]:
        print(f"    📺 {nm[:40]:<40} | {(e.get('en_title') or '')[:32]:<32} | {e.get('category')}")
    print()

    if args.titles:
        print("── כל הסרטים ──")
        for e in sorted(movies, key=lambda x: x.get("category") or ""):
            print(f"  [{e.get('category')}] {e.get('title')}  ({e.get('en_title') or '—'}, {e.get('year') or '—'})")
        print("\n── כל הסדרות ──")
        for nm, e in sorted(series.items(), key=lambda x: x[1].get("category") or ""):
            print(f"  [{e.get('category')}] {nm}  ({e.get('en_title') or '—'})")


if __name__ == "__main__":
    main()
