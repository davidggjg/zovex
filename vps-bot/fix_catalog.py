"""משלים שדות חסרים בקטלוג: כתובת אנגלית (custom_slug) ופוסטר.

למה זה קיים
-----------
· 649 פריטים נכנסו בלי custom_slug, ולכן הכתובת שלהם באתר היא השם העברי
  מקודד ב-percent-encoding — קישור מכוער שנשבר בשיתוף ובאינדוקס.
· כמה עשרות פריטים נכנסו בלי thumbnail_url, ומוצגים כריבוע ריק עם אימוג'י.

מה הוא עושה
-----------
· slug: מעדיף en_title שכבר קיים; אם אין — מחפש ב-TMDB שם אנגלי; ואם גם זה
  לא נמצא — מתעתק את השם העברי, בדיוק כמו שהבוט עושה בהעלאה רגילה.
  ייחודיות נאכפת: התנגשות מקבלת סיומת מספרית.
· פוסטר: חיפוש TMDB לפי השם (ולפי השנה אם ידועה), ולוקח את הפוסטר הראשון.
· פריטים של אותה סדרה מקבלים את אותו slug ואת אותו פוסטר, כדי שלא ייווצרו
  שתי כתובות לאותה סדרה.

הרצה
----
    python3 fix_catalog.py                 # דוח בלבד, לא נוגע בכלום
    python3 fix_catalog.py --posters       # רק פוסטרים (דוח)
    python3 fix_catalog.py --apply         # מבצע בפועל (עם גיבוי אוטומטי)
    python3 fix_catalog.py --limit 20      # לבדוק על מדגם קטן קודם
"""
import argparse
import asyncio
import os
import pathlib
import re
import sys

sys.path.insert(0, "/opt/zovex-bot")

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true", help="לשמור בפועל (ברירת מחדל: דוח בלבד)")
ap.add_argument("--slugs", action="store_true", help="רק כתובות")
ap.add_argument("--posters", action="store_true", help="רק פוסטרים")
ap.add_argument("--limit", type=int, default=0, help="לעצור אחרי N תיקונים (0=הכל)")
ap.add_argument("--no-tmdb", action="store_true", help="בלי TMDB — רק תעתיק מהעברית")
args = ap.parse_args()
DO_SLUGS = args.slugs or not args.posters
DO_POSTERS = args.posters or not args.slugs

# main.py קורא משתני סביבה שנטענים רק ע"י systemd מתוך .env
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
else:
    print(f"⚠️  {ENV_FILE} לא נמצא")

from main import (load_content, save_content, tmdb_search, _slug_base,  # noqa: E402
                  TMDB_API_KEY)


def is_live(e):
    return bool(e.get("is_live")) or e.get("category") == "שידורים חיים"


def group_key(e):
    """סדרה שלמה היא ישות אחת לעניין כתובת ופוסטר; סרט הוא בפני עצמו."""
    return ("series", e["series_name"]) if e.get("series_name") else ("movie", e.get("id"))


def display_name(e):
    return e.get("series_name") or e.get("title") or e.get("name") or ""


async def tmdb_best(name, year=""):
    """התאמה ראשונה מ-TMDB, או None. מחזיר (en_title, poster)."""
    if args.no_tmdb or not TMDB_API_KEY or not name:
        return None
    try:
        opts = await tmdb_search(name, str(year or ""))
    except Exception as ex:
        print(f"    TMDB נכשל על '{name}': {type(ex).__name__}: {ex}")
        return None
    if not opts:
        return None
    o = opts[0]
    return (o.get("en_title") or "").strip(), (o.get("poster") or "").strip()


async def main():
    content = load_content()
    print(f"בקטלוג: {len(content)} פריטים\n")

    # כל ה-slug-ים התפוסים, כדי לא ליצור התנגשות
    taken = {(e.get("custom_slug") or "").strip() for e in content}
    taken.discard("")

    # קיבוץ לפי ישות
    groups = {}
    for e in content:
        if is_live(e):
            continue          # שידורים חיים מנוהלים ידנית — לא נוגעים
        groups.setdefault(group_key(e), []).append(e)

    need_slug, need_poster = [], []
    for key, items in groups.items():
        if DO_SLUGS and not any((e.get("custom_slug") or "").strip() for e in items):
            need_slug.append((key, items))
        if DO_POSTERS and not any((e.get("thumbnail_url") or "").strip() for e in items):
            need_poster.append((key, items))

    print(f"בלי כתובת אנגלית: {len(need_slug)} ישויות "
          f"({sum(len(i) for _, i in need_slug)} פריטים)")
    print(f"בלי פוסטר:        {len(need_poster)} ישויות "
          f"({sum(len(i) for _, i in need_poster)} פריטים)")
    if not TMDB_API_KEY and not args.no_tmdb:
        print("⚠️  אין TMDB_API_KEY — הכתובות ייווצרו מתעתיק, ופוסטרים לא יימצאו")
    print()

    changed = 0

    # ── כתובות ──────────────────────────────────────────────────────────────
    for key, items in need_slug:
        if args.limit and changed >= args.limit:
            break
        rep = items[0]
        name = display_name(rep)
        if not name:
            continue
        en = (rep.get("en_title") or "").strip()
        if not en:
            hit = await tmdb_best(name, rep.get("year"))
            if hit:
                en = hit[0]
        base = _slug_base(en) or _slug_base(name)
        if not base:
            print(f"  ✗ אין ממה לבנות כתובת: {name!r}")
            continue
        slug = base
        n = 2
        while slug in taken:                 # ייחודיות
            slug = f"{base}-{n}"
            n += 1
        taken.add(slug)
        print(f"  {name}  →  /{slug}" + (f"   (מ-'{en}')" if en else "   (תעתיק)"))
        for e in items:
            e["custom_slug"] = slug
            if en and not (e.get("en_title") or "").strip():
                e["en_title"] = en
        changed += 1

    # ── פוסטרים ─────────────────────────────────────────────────────────────
    if DO_POSTERS:
        print()
        for key, items in need_poster:
            if args.limit and changed >= args.limit:
                break
            rep = items[0]
            name = display_name(rep)
            hit = await tmdb_best(name, rep.get("year"))
            if not hit or not hit[1]:
                print(f"  ✗ לא נמצא פוסטר: {name!r}")
                continue
            en, poster = hit
            print(f"  {name}  →  {poster}")
            for e in items:
                if not (e.get("thumbnail_url") or "").strip():
                    e["thumbnail_url"] = poster
                if en and not (e.get("en_title") or "").strip():
                    e["en_title"] = en
            changed += 1

    print(f"\nישויות שתוקנו: {changed}")
    if not changed:
        print("אין מה לשמור.")
        return
    if not args.apply:
        print("זו הרצה יבשה. להרצה אמיתית: --apply")
        return
    save_content(content)
    print("נשמר. גיבוי נוצר אוטומטית ב-data/content_backups/")


if __name__ == "__main__":
    asyncio.run(main())
