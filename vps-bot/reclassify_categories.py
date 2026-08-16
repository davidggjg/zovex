"""מסדר תוכן לקטגוריה הנכונה לפי שפת המקור מ-TMDB.

הבעיה
-----
אין בקטלוג שדה שפה/מוצא, והכותרות בעברית גם לסרטים זרים — אז אי אפשר לזהות
"סרט ישראלי" או "סדרה טורקית" מהנתונים לבד. הסימן האמין היחיד הוא
original_language של TMDB. הסקריפט מחפש כל פריט ב-TMDB, לוקח את שפת המקור,
ומציע העברה לקטגוריה המתאימה.

הכלל (שמרני):
  · סרט  ששפת המקור שלו he  → "סרטים ישראלים"
  · סדרה ששפת המקור שלה tr → "סדרות טורקיות"
  (אפשר להרחיב עם --hebrew-series כדי לתפוס גם סדרות ישראליות שממוקמות לא נכון.)

זה מתקן את עצמו: "הענק הירוק" יחזור כ-en ולא יזוז; "ברש" כ-he ויזוז.
פריט שלא נמצא ב-TMDB — לא זז. עדיף להשאיר במקום מאשר לנחש.

הרצה
----
    python3 reclassify_categories.py                 # דוח בלבד (לא משנה כלום)
    python3 reclassify_categories.py --apply         # מבצע (עם גיבוי אוטומטי)
    python3 reclassify_categories.py --limit 40       # מדגם לבדיקה מהירה
    python3 reclassify_categories.py --hebrew-series  # גם סדרות ישראליות
"""
import argparse
import asyncio
import os
import pathlib
import sys

sys.path.insert(0, "/opt/zovex-bot")

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true", help="לשמור בפועל")
ap.add_argument("--limit", type=int, default=0, help="לעצור אחרי N בדיקות")
ap.add_argument("--hebrew-series", action="store_true",
                help="גם להעביר סדרות ששפתן he ל'סדרות ישראליות'")
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

from main import load_content, save_content, tmdb_search, TMDB_API_KEY  # noqa: E402

MOVIE_CATS = {"סרטים", "סרטים לילדים (מתאים גם למשפחה)", "אימה"}
SERIES_CATS = {"סדרות", "סדרות לילדים", "אנימה", "סדרות ישראליות"}
CAT_IL_MOVIE = "סרטים ישראלים"
CAT_TR_SERIES = "סדרות טורקיות"
CAT_IL_SERIES = "סדרות ישראליות"


def is_live(e):
    return bool(e.get("is_live")) or e.get("category") == "שידורים חיים"


async def tmdb_lang(name, en, year, want_type):
    """שפת המקור מ-TMDB עבור פריט. מעדיף חיפוש בשם האנגלי (אמין יותר),
    ומסנן לתוצאה מהסוג הנכון (movie/tv). מחזיר (lang, matched_title) או (None,None)."""
    for q in [en, name]:
        if not (q or "").strip():
            continue
        try:
            opts = await tmdb_search(q, str(year or ""))
        except Exception:
            opts = []
        if not opts:
            continue
        typed = [o for o in opts if o.get("type") == want_type] or opts
        o = typed[0]
        lang = (o.get("lang") or "").lower()
        if lang:
            return lang, o.get("title") or o.get("en_title") or q
    return None, None


async def main():
    content = load_content()
    print(f"בקטלוג: {len(content)} פריטים")
    if not TMDB_API_KEY:
        print("⚠️  אין TMDB_API_KEY — אי אפשר לזהות שפה. עצירה.")
        return

    # ── סרטים → he? ─────────────────────────────────────────────────────────
    movies = [e for e in content
              if e.get("category") in MOVIE_CATS and not e.get("series_name")
              and not is_live(e)]
    # ── סדרות (מקובצות) → tr / he? ──────────────────────────────────────────
    series = {}
    for e in content:
        if (e.get("category") in SERIES_CATS and e.get("series_name")
                and not is_live(e)):
            series.setdefault(e["series_name"], e)

    print(f"סרטים לבדיקה: {len(movies)} · סדרות ייחודיות: {len(series)}\n")

    checked = 0
    move_movie, move_tr, move_he_s = [], [], []

    print("בודק סרטים...")
    for e in movies:
        if args.limit and checked >= args.limit:
            break
        checked += 1
        lang, matched = await tmdb_lang(e.get("title"), e.get("en_title"),
                                        e.get("year"), "movie")
        if lang == "he":
            move_movie.append((e, matched))
            print(f"  🎬 {e.get('title')!r}  →  {CAT_IL_MOVIE}   (TMDB: {matched!r}, he)")

    print("\nבודק סדרות...")
    for name, rep in series.items():
        if args.limit and checked >= args.limit:
            break
        checked += 1
        lang, matched = await tmdb_lang(name, rep.get("en_title"),
                                        rep.get("year"), "tv")
        if lang == "tr" and rep.get("category") != CAT_TR_SERIES:
            move_tr.append((name, matched))
            print(f"  📺 {name!r}  →  {CAT_TR_SERIES}   (TMDB: {matched!r}, tr)")
        elif (args.hebrew_series and lang == "he"
              and rep.get("category") != CAT_IL_SERIES):
            move_he_s.append((name, matched))
            print(f"  📺 {name!r}  →  {CAT_IL_SERIES}   (TMDB: {matched!r}, he)")

    # ── יישום ───────────────────────────────────────────────────────────────
    move_movie_ids = {id(e) for e, _ in move_movie}
    tr_names = {n for n, _ in move_tr}
    he_names = {n for n, _ in move_he_s}
    changed = 0
    for e in content:
        if id(e) in move_movie_ids:
            e["category"] = CAT_IL_MOVIE
            changed += 1
        elif e.get("series_name") in tr_names:
            e["category"] = CAT_TR_SERIES
            changed += 1
        elif e.get("series_name") in he_names:
            e["category"] = CAT_IL_SERIES
            changed += 1

    print(f"\n── סיכום ──")
    print(f"סרטים → ישראלים:   {len(move_movie)}")
    print(f"סדרות → טורקיות:   {len(move_tr)} סדרות")
    if args.hebrew_series:
        print(f"סדרות → ישראליות:  {len(move_he_s)} סדרות")
    print(f"סה\"כ פריטים שישתנו: {changed}")

    if not changed:
        print("אין מה לשנות.")
        return
    if not args.apply:
        print("\nזו הרצה יבשה. עברת על הרשימה למעלה? להרצה אמיתית: --apply")
        return
    save_content(content)
    print("✅ נשמר. גיבוי אוטומטי ב-data/content_backups/")


if __name__ == "__main__":
    asyncio.run(main())
