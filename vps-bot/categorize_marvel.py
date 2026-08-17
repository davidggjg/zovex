"""מעביר כותרות מארוול לקטגוריית "מארוול".

· לא פותח קטגוריה חדשה אם היא כבר קיימת — פשוט מצמיד את הפריטים אליה.
· זיהוי לפי marvel.looks_marvel (רשימת כותרות מוכרת + מילות-מפתח), על en_title
  ועל הכותרת העברית. לא נוגע בשידורים חיים.
· סדרות: מעביר את כל קבוצת ה-series_name יחד.

    python3 categorize_marvel.py            # דו"ח בלבד
    python3 categorize_marvel.py --apply    # מבצע (גיבוי אוטומטי ב-content_backups)
"""
import argparse
import os
import pathlib
import sys

sys.path.insert(0, "/opt/zovex-bot")

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
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
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if k:
            os.environ[k] = v

from main import load_content, save_content       # noqa: E402
from marvel import MARVEL_CATEGORY, looks_marvel   # noqa: E402


def is_live(e):
    return bool(e.get("is_live")) or e.get("category") == "שידורים חיים"


def main():
    content = load_content()
    existing = sum(1 for e in content if e.get("category") == MARVEL_CATEGORY)
    print(f"בקטלוג: {len(content)} פריטים · כבר ב'{MARVEL_CATEGORY}': {existing}")

    move = []
    for e in content:
        if is_live(e) or e.get("category") == MARVEL_CATEGORY:
            continue
        names = [e.get("en_title"), e.get("title"), e.get("series_name")]
        if looks_marvel(*names):
            move.append(e)

    # מקבצים לתצוגה לפי סדרה/סרט
    seen_series = set()
    print(f"\nמועמדים ל'{MARVEL_CATEGORY}': {len(move)} פריטים")
    for e in move:
        sn = e.get("series_name")
        label = sn or e.get("title")
        if sn:
            if sn in seen_series:
                continue
            seen_series.add(sn)
            kind = "📺"
        else:
            kind = "🎬"
        print(f"  {kind} {(label or '?')[:45]:<45} | {(e.get('en_title') or '')[:30]:<30} | מ-{e.get('category')}")

    if not move:
        print("אין מה להעביר.")
        return
    if not args.apply:
        print("\nהרצה יבשה. עברת על הרשימה? להרצה אמיתית: --apply")
        return

    for e in move:
        e["category"] = MARVEL_CATEGORY
    save_content(content)
    print(f"\n✅ הועברו {len(move)} פריטים ל'{MARVEL_CATEGORY}'. גיבוי ב-content_backups/")


if __name__ == "__main__":
    main()
