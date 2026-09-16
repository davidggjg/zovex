#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_categories — כל פריט בקטגוריה שלו, לפי נתוני TMDB ולא לפי ניחוש.

מה שנמדד בקטלוג (catalog_stats.py, 13,070 פריטי VOD):

    סדרות ישראליות   4,718     סרטים              577
    סדרות            2,780     סרטים לילדים       244
    סדרות לילדים     2,404     סדרות טורקיות      219
    אנימה            1,966     סרטים ישראלים       65
                               אימה                56
                               מארוול              40

והנקודה שקובעת את כל התכנון: **הקטגוריות האלה אינן ז'אנרים.** הן
צירוף של סוג (סדרה/סרט) × מקור (ישראלי/טורקי/יפני) × קהל (ילדים) ×
זכיינות (מארוול). ז'אנר אמיתי יש בהן אחד — אימה, 56 פריטים.

לכן מיפוי מז'אנרים של TMDB, שזה מה שהצעתי תחילה, היה שם את "האביר
האפל" ב"אקשן" — קטגוריה שלא קיימת. מה שכן קובע:

    ישראלי   original_language == "he"  או  IL ב-origin_country
    טורקי    original_language == "tr"  או  TR
    אנימה    original_language == "ja"  +  ז'אנר אנימציה
    ילדים    ז'אנר Animation / Kids / Family
    מארוול   production_companies מכיל את מארוול
    אימה     ז'אנר Horror
    סדרה     series_name קיים אצלנו

שבעה כללים, כולם דטרמיניסטיים, כולם משדות שאותה קריאת TMDB מחזירה.
אף אחד מהם לא צריך מודל. המודל נדרש רק ל-3,516 הפריטים שאין להם
tmdb_id, וזה שלב נפרד.

חשוב: original_language הוא שפת **המקור**. סדרה טורקית מדובבת לעברית
נשארת "tr", ולכן היא לא תיפול בטעות ל"ישראליות" — וזה בדיוק ההבדל
בין השדה הזה לבין ניחוש לפי שם עברי.

    python3 fix_categories.py --check          # מטריצת מעברים, בלי כתיבה
    python3 fix_categories.py --sample 60 --check
    python3 fix_categories.py
    python3 fix_categories.py --revert
"""
import argparse, importlib.util, json, os, shutil, sys, time
from collections import Counter
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load_enrich():
    """שכבת ה-HTTP, תיקון ה-IPv6 ו-fetch מגיעים מ-tmdb_enrich.

    לא משכפלים אותם: fetch שם כבר יודע לנסות את הסוג ההפוך כשמזהה
    נשמר תחת הסוג הלא-נכון, וזה נדרש גם כאן.
    """
    p = os.path.join(_HERE, "tmdb_enrich.py")
    if not os.path.exists(p):
        sys.exit(f"לא נמצא {p} — הכלי הזה מייבא ממנו.")
    spec = importlib.util.spec_from_file_location("_tmdb_enrich", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── הקטגוריות, בשמות המדויקים שקיימים בקטלוג ────────────────────────────────
# שם שלא תואם בית-בית יוצר קטגוריה חדשה וריקה באתר, ולכן הם מועתקים
# מהפלט של catalog_stats ולא נכתבים מהזיכרון.
C_SER_IL   = "סדרות ישראליות"
C_SER      = "סדרות"
C_SER_KIDS = "סדרות לילדים"
C_SER_TR   = "סדרות טורקיות"
C_ANIME    = "אנימה"
C_MOV      = "סרטים"
C_MOV_KIDS = "סרטים לילדים (מתאים גם למשפחה)"
C_MOV_IL   = "סרטים ישראלים"
C_HORROR   = "אימה"
C_MARVEL   = "מארוול"

KNOWN = {C_SER_IL, C_SER, C_SER_KIDS, C_SER_TR, C_ANIME,
         C_MOV, C_MOV_KIDS, C_MOV_IL, C_HORROR, C_MARVEL}

G_ANIMATION, G_HORROR, G_FAMILY, G_KIDS = 16, 27, 10751, 10762

# מזהי מארוול ב-TMDB. Marvel Studios הוא המפיק של סרטי ה-MCU;
# Marvel Entertainment ו-Marvel Animation מופיעים על השאר.
MARVEL_IDS = {420, 7505, 19551, 12939}
MARVEL_WORDS = ("marvel",)


def _langs(d: dict) -> set:
    out = set()
    for side in ("he", "en"):
        x = d.get(side) or {}
        if x.get("original_language"):
            out.add(str(x["original_language"]).lower())
        for c in (x.get("origin_country") or []):
            out.add(str(c).upper())
        for c in (x.get("production_countries") or []):
            if c.get("iso_3166_1"):
                out.add(str(c["iso_3166_1"]).upper())
    return out


def _genres(d: dict) -> set:
    out = set()
    for side in ("he", "en"):
        for g in ((d.get(side) or {}).get("genres") or []):
            if g.get("id") is not None:
                out.add(g["id"])
    return out


def _is_marvel(d: dict) -> bool:
    for side in ("he", "en"):
        for c in ((d.get(side) or {}).get("production_companies") or []):
            if c.get("id") in MARVEL_IDS:
                return True
            nm = str(c.get("name") or "").lower()
            if any(w in nm for w in MARVEL_WORDS):
                return True
    return False


def decide(is_series: bool, d: dict) -> tuple:
    """הקטגוריה הנכונה לפריט, ונימוק. None = אין די נתונים, לא נוגעים.

    סדר הכללים הוא ההחלטה האמיתית כאן, והוא מהספציפי לכללי:

    1. מארוול — זכיינות, ולכן חזקה מכל השאר. פריט של מארוול נמצא
       בקטגוריה שלו בין אם הוא סרט או סדרה.
    2. אנימה — יפנית **ואנימציה**. יפנית לבדה אינה אנימה (יש דרמות
       יפניות), ואנימציה לבדה היא "לילדים" (אחרת דיסני היה באנימה).
    3. מקור — ישראלי וטורקי. אצל דוד המקור גובר על הז'אנר: 4,718
       פריטים ב"סדרות ישראליות" לעומת 56 ב"אימה", כלומר זו החלוקה
       שהקטלוג בנוי עליה בפועל.
    4. אימה — הז'אנר היחיד שקיים כקטגוריה.
    5. ילדים — אנימציה שאינה יפנית, או Kids, או Family.
    6. ברירת מחדל — סדרות או סרטים לפי הסוג.
    """
    if not (d.get("he") or d.get("en")):
        return None, "אין נתוני TMDB"
    L, G = _langs(d), _genres(d)
    if _is_marvel(d):
        return C_MARVEL, "מארוול מפיקה"
    if "ja" in L and G_ANIMATION in G:
        return C_ANIME, "יפנית + אנימציה"
    if "he" in L or "IL" in L:
        return (C_SER_IL if is_series else C_MOV_IL), "מקור ישראלי"
    if "tr" in L or "TR" in L:
        # אין "סרטים טורקיים" בקטלוג, ולכן סרט טורקי נשאר "סרטים"
        # ולא יוצר קטגוריה חדשה שאין לה מקום באתר.
        return (C_SER_TR if is_series else C_MOV), "מקור טורקי"
    if G_HORROR in G:
        return C_HORROR, "ז'אנר אימה"
    if G_ANIMATION in G or G_KIDS in G or G_FAMILY in G:
        return (C_SER_KIDS if is_series else C_MOV_KIDS), "אנימציה/ילדים/משפחה"
    return (C_SER if is_series else C_MOV), "ברירת מחדל לפי סוג"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--sample", type=int, default=0,
                    help="N יחידות באקראי — טעימה מייצגת")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--sleep", type=float, default=0.06)
    a = ap.parse_args()

    E = _load_enrich()
    CONTENT, VERSION = E.CONTENT, E.VERSION
    BACKUP = CONTENT.with_name("content.json.bak_categories")

    if a.revert:
        if not BACKUP.exists():
            sys.exit(f"אין גיבוי ב-{BACKUP}")
        shutil.copy2(BACKUP, CONTENT)
        print(f"✓ שוחזר מ-{BACKUP}")
        return
    key = E.load_key()
    if not key:
        sys.exit("אין TMDB_API_KEY בסביבה או ב-/opt/zovex-bot/.env")
    if not CONTENT.exists():
        sys.exit(f"לא נמצא: {CONTENT}")

    items = json.loads(CONTENT.read_text(encoding="utf-8"))
    groups = {}
    for it in items:
        tid = it.get("tmdb_id")
        if not tid or it.get("is_live"):
            continue
        kind = "tv" if str(it.get("series_name") or "").strip() else "movie"
        groups.setdefault((kind, str(tid)), []).append(it)

    keys = list(groups)
    if a.sample:
        import random
        random.Random(a.seed).shuffle(keys)
        keys = keys[:a.sample]
    print(f"קטלוג: {len(items)} פריטים · {len(groups)} יחידות עם tmdb_id")
    print(f"מעבד {len(keys)} יחידות · "
          f"{sum(len(groups[k]) for k in keys)} פריטים"
          + (f" · דגימה אקראית (זרע {a.seed})" if a.sample else "") + "\n")

    changes, moves, why_cnt, nodata = [], Counter(), Counter(), 0
    t0 = time.time()
    for n, k in enumerate(keys, 1):
        kind, tid = k
        d = E.fetch(key, kind, tid)
        cat, why = decide(kind == "tv", d)
        if cat is None:
            nodata += 1
        else:
            why_cnt[why] += 1
            for it in groups[k]:
                cur = (it.get("category") or "").strip()
                if cur != cat:
                    changes.append((it, cur, cat))
                    moves[(cur or "(ריק)", cat)] += 1
        print(f"\r  {n}/{len(keys)}".ljust(22), end="", flush=True)
        if a.sleep:
            time.sleep(a.sleep)
    print(f"\n\nלקח {time.time()-t0:.0f} שניות · {nodata} יחידות בלי נתונים\n"
          + "=" * 62)

    if not changes:
        print("כל הפריטים כבר בקטגוריה הנכונה.")
        return

    print(f"\n{len(changes)} פריטים יעברו קטגוריה.\n")
    print(f"{'מ':<32}{'ל':<32}{'פריטים':>7}")
    for (src, dst), c in moves.most_common(25):
        print(f"{src[:30]:<32}{dst[:30]:<32}{c:>7}")
    if len(moves) > 25:
        print(f"...ועוד {len(moves)-25} מעברים")

    print("\nלפי הכלל שהכריע:")
    for w, c in why_cnt.most_common():
        print(f"   {w:<26} {c:>5} יחידות")

    after = Counter((it.get("category") or "(ריק)").strip()
                    for it in items if not it.get("is_live"))
    for it, cur, cat in changes:
        after[cur or "(ריק)"] -= 1
        after[cat] += 1
    print("\nהתפלגות אחרי:")
    for c, v in after.most_common():
        if v:
            print(f"   {c[:40]:<42}{v:>6}")
    bad = {c for c in after if after[c] and c not in KNOWN and c != "(ריק)"}
    if bad:
        print(f"\n⚠ קטגוריות שלא היו קיימות: {sorted(bad)}")

    print("\nדוגמאות:")
    for it, cur, cat in changes[:8]:
        nm = (it.get("series_name") or it.get("title") or "?").strip()
        print(f"   {nm[:26]:<28} {cur[:18]:<20} → {cat}")

    print("\n" + "=" * 62)
    if a.check:
        print("--check: שום דבר לא נכתב.")
        return
    if a.sample:
        sys.exit("דגימה היא לבדיקה בלבד. להחלה — להריץ בלי --sample.")

    shutil.copy2(CONTENT, BACKUP)
    for it, cur, cat in changes:
        it["category"] = cat
    E.atomic_write(CONTENT, json.dumps(items, ensure_ascii=False, indent=2))
    try:
        v = int(VERSION.read_text().strip()) + 1 if VERSION.exists() else 1
    except Exception:
        v = int(time.time())
    E.atomic_write(VERSION, str(v))
    print(f"✓ הועברו {len(changes)} פריטים · גיבוי: {BACKUP} · גרסה {v}")
    print("  בלי restart. לביטול: python3 fix_categories.py --revert")


if __name__ == "__main__":
    main()
