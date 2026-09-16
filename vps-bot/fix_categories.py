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

ומה שהנתון לא יכול לבטא נשמר בנפרד: category_overrides.json ממפה
tmdb_id לקטגוריה וגובר על הכול. הוא נדרש כי נמדד שמורביוס (526896)
ומאדאם ווב (634492) הוצאו מ"מארוול" — הן הפקות סוני עם דמויות של
מארוול, ורשימת המפיקים ב-TMDB לא מזכירה מארוול בכלל. "מארוול" היא
קטגוריה עריכתית, ולכן היא גם ב-NEVER_DEMOTE: הכלל החלש לא יוציא
ממנה פריט לעולם, אבל הכלל החיובי ימשיך להכניס אליה.

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

# קטגוריות שהכלל החלש ("ברירת מחדל לפי סוג") לא יוציא מהן פריט לעולם.
# "מארוול" היא עריכתית ו-TMDB לא יכול לשחזר אותה: נמדד שמורביוס
# (526896) ומאדאם ווב (634492) הוצאו ממנה, כי הן הפקות סוני עם דמויות
# של מארוול, ורשימת המפיקים ב-TMDB לא מזכירה את מארוול בכלל. הכלל
# החיובי (מארוול מפיקה → מארוול) ממשיך להכניס פריטים פנימה.
NEVER_DEMOTE = {C_MARVEL}

# קביעות עריכתיות: גוברות על הכול, ונשמרות בין ריצות במקום לחזור בכל
# פעם. שני סוגי מפתח:
#   "526896"          לפי tmdb_id  — לפריט עם מזהה (מורביוס/מאדאם ווב).
#   "series:עספור"    לפי שם סדרה  — חל על כל פרקיה **בלי קשר למזהה**,
#                     וזה נדרש כי עספור סדרת ילדים ישראלית שאין לה מזהה
#                     בקטלוג, ולכן fix_categories לבדו לא יכול להכריע.
OVERRIDES = Path(os.environ.get("ZOVEX_CAT_OVERRIDES",
                                os.path.join(_HERE, "category_overrides.json")))


def load_overrides() -> tuple:
    """מחזיר (לפי מזהה, לפי שם סדרה, לפי כותרת).

    שלושה סוגי מפתח, כי לא לכל פריט יש אותו עוגן:
      "526896"        tmdb_id — לפריט עם מזהה.
      "series:עספור"  שם סדרה — לכל פרקיה, בלי קשר למזהה.
      "title:ונום 2"  כותרת   — לסרט בודד בלי series_name ובלי מזהה,
                      וזה בדיוק המצב של 6 סרטי מארוול שנמצאו מפוזרים
                      ב"סרטים": ונום 2, הפנתר השחור, דוקטור סטריינג'
                      וכו', שאין להם עוגן אחר.
    קטגוריה שלא קיימת בקטלוג נפסלת בקריאה.
    """
    try:
        d = json.loads(OVERRIDES.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, {}, {}
    except Exception as e:
        sys.exit(f"{OVERRIDES} לא נקרא: {e}")
    by_id, by_series, by_title, bad = {}, {}, {}, []
    for k, v in (d or {}).items():
        cat, key = str(v).strip(), str(k).strip()
        if cat not in KNOWN:
            bad.append((k, v))
        elif key.startswith("series:"):
            by_series[key[len("series:"):].strip()] = cat
        elif key.startswith("title:"):
            by_title[key[len("title:"):].strip()] = cat
        else:
            by_id[key] = cat
    if bad:
        sys.exit(f"{OVERRIDES}: קטגוריות שלא קיימות בקטלוג {bad}")
    return by_id, by_series, by_title


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
    ap.add_argument("--no-demote", action="store_true",
                    help="לא להוריד פריט מקטגוריה ספציפית לגנרית")
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

    over, over_series, over_title = load_overrides()
    if over or over_series or over_title:
        print(f"{len(over)+len(over_series)+len(over_title)} קביעות עריכתיות "
              f"מ-{OVERRIDES.name}\n")
    changes, moves, why_cnt, nodata = [], Counter(), Counter(), 0

    # קביעות לפי שם סדרה / כותרת — פועלות על **כל** הפריטים, גם בלי
    # tmdb_id, ולכן פס נפרד לפני הלולאה מבוססת-המזהה. עספור נופלת ב-
    # שם-סדרה; 6 סרטי מארוול המפוזרים נופלים ב-כותרת.
    if over_series or over_title:
        for it in items:
            if it.get("is_live"):
                continue
            sn = str(it.get("series_name") or "").strip()
            cat = over_series.get(sn)
            if not cat and not sn:            # כותרת חלה רק על פריט בודד
                cat = over_title.get(str(it.get("title") or "").strip())
            cur = (it.get("category") or "").strip()
            if cat and cur != cat:
                changes.append((it, cur, cat, "קביעה עריכתית (שם/כותרת)"))
                moves[(cur or "(ריק)", cat)] += 1
        why_cnt["קביעה עריכתית (שם/כותרת)"] = sum(
            1 for _, _, _, w in changes if w == "קביעה עריכתית (שם/כותרת)")

    t0 = time.time()
    for n, k in enumerate(keys, 1):
        kind, tid = k
        d = E.fetch(key, kind, tid)
        cat, why = decide(kind == "tv", d)
        if str(tid) in over:
            cat, why = over[str(tid)], "קביעה עריכתית"
        if cat is None:
            nodata += 1
        else:
            why_cnt[why] += 1
            for it in groups[k]:
                # קביעה לפי שם סדרה/כותרת כבר טיפלה בפריט הזה בפס הקודם
                # וגוברת על ההחלטה מ-TMDB.
                _sn = str(it.get("series_name") or "").strip()
                if _sn in over_series:
                    continue
                if not _sn and str(it.get("title") or "").strip() in over_title:
                    continue
                cur = (it.get("category") or "").strip()
                if (why == "ברירת מחדל לפי סוג" and cur in KNOWN
                        and cur not in (C_SER, C_MOV)
                        and (a.no_demote or cur in NEVER_DEMOTE)):
                    continue
                if cur != cat:
                    changes.append((it, cur, cat, why))
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
    for it, cur, cat, _w in changes:
        after[cur or "(ריק)"] -= 1
        after[cat] += 1
    print("\nהתפלגות אחרי:")
    for c, v in after.most_common():
        if v:
            print(f"   {c[:40]:<42}{v:>6}")
    bad = {c for c in after if after[c] and c not in KNOWN and c != "(ריק)"}
    if bad:
        print(f"\n⚠ קטגוריות שלא היו קיימות: {sorted(bad)}")

    # הורדות דרגה: ירידה מקטגוריה ספציפית לקטגוריה הגנרית, בגלל
    # ש"ברירת מחדל לפי סוג" הכריעה. זה הכלל החלש ביותר — הוא פשוט
    # אומר "סדרה" או "סרט" — וכשהוא דורס בחירה אנושית ספציפית, בדרך
    # כלל הסיבה היא שחסר ז'אנר ב-TMDB ולא שהקטגוריה הייתה שגויה.
    # הן מעטות, ולכן מפורטות בשמן ולא רק נספרות.
    FALLBACK = {C_SER, C_MOV}
    demo = [(it, cur, cat) for it, cur, cat, w in changes
            if w == "ברירת מחדל לפי סוג" and cur in KNOWN and cat in FALLBACK
            and cur not in FALLBACK]
    if demo:
        print(f"\n⚠ {len(demo)} פריטים יורדים מקטגוריה ספציפית לגנרית, "
              "כי חסר ז'אנר ב-TMDB.")
        print("   כאן בחירה אנושית קודמת עשויה להיות טובה מהנתון — "
              "שווה עין, וזה קטן מספיק לתקן ביד:")
        seen = set()
        for it, cur, cat in demo:
            nm = (it.get("series_name") or it.get("title") or "?").strip()
            if nm in seen:
                continue
            seen.add(nm)
            print(f"      {nm[:28]:<30} {cur[:20]:<22} → {cat}"
                  f"   (tmdb_id {it.get('tmdb_id')})")
        print(f"   {len(seen)} שמות, {len(demo)} פריטים. "
              "--no-demote משאיר אותם כמו שהם.")

    print("\nדוגמאות:")
    for it, cur, cat, _w in changes[:8]:
        nm = (it.get("series_name") or it.get("title") or "?").strip()
        print(f"   {nm[:26]:<28} {cur[:18]:<20} → {cat}")

    print("\n" + "=" * 62)
    if a.check:
        print("--check: שום דבר לא נכתב.")
        return
    if a.sample:
        sys.exit("דגימה היא לבדיקה בלבד. להחלה — להריץ בלי --sample.")

    shutil.copy2(CONTENT, BACKUP)
    for it, cur, cat, _w in changes:
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
