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

from main import load_content, clean_name           # noqa: E402

MARVEL_CATEGORY = "מארוול"

# רשימת כותרות מוכרות (אנגלית, מנורמלת) — MCU + ספיידרמן + אקס-מן + דדפול + וונום.
_MARVEL_TITLES = {
    "iron man", "iron man 2", "iron man 3", "the incredible hulk", "thor",
    "thor the dark world", "thor ragnarok", "thor love and thunder",
    "captain america the first avenger", "captain america the winter soldier",
    "captain america civil war", "captain america brave new world",
    "the avengers", "avengers age of ultron", "avengers infinity war",
    "avengers endgame", "guardians of the galaxy", "guardians of the galaxy vol 2",
    "guardians of the galaxy vol 3", "ant man", "ant man and the wasp",
    "ant man and the wasp quantumania", "doctor strange",
    "doctor strange in the multiverse of madness", "black panther",
    "black panther wakanda forever", "captain marvel", "the marvels",
    "spider man homecoming", "spider man far from home", "spider man no way home",
    "black widow", "shang chi and the legend of the ten rings", "eternals",
    "deadpool", "deadpool 2", "deadpool and wolverine", "deadpool wolverine",
    "venom", "venom let there be carnage", "venom the last dance", "morbius",
    "madame web", "kraven the hunter", "spider man", "spider man 2", "spider man 3",
    "the amazing spider man", "the amazing spider man 2", "x men", "x2",
    "x men the last stand", "x men first class", "x men days of future past",
    "x men apocalypse", "x men dark phoenix", "the wolverine", "logan",
    "x men origins wolverine", "fantastic four", "the fantastic four first steps",
    "blade", "wandavision", "the falcon and the winter soldier", "loki",
    "hawkeye", "moon knight", "ms marvel", "she hulk attorney at law",
    "secret invasion", "echo", "agatha all along", "daredevil",
    "daredevil born again", "the punisher", "jessica jones", "luke cage",
    "iron fist", "the defenders", "agents of shield",
}
# מילות-מפתח של זכיינות — לתפוס גם וריאציות שלא ברשימה המדויקת.
_MARVEL_KEYWORDS = ("avengers", "x men", "deadpool", "spider man", "iron man",
                    "captain america", "guardians of the galaxy", "ant man",
                    "black panther", "doctor strange", "thor", "wolverine",
                    "venom", "loki", "wandavision", "moon knight")


def _norm(s):
    s = clean_name(str(s or "")).lower()
    s = re.sub(r"[^\w֐-׿]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def looks_marvel(en, he):
    for cand in (en, he):
        n = _norm(cand)
        if not n:
            continue
        if n in _MARVEL_TITLES:
            return True
        if any(kw in n for kw in _MARVEL_KEYWORDS):
            return True
    return False


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
