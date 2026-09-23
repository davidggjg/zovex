#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_catalog_meta — סריקת עומק של הקטלוג: תיאורים, פוסטרים וקטגוריות.

## מה נמצא בסריקה (16,561 פריטים)

  • 729 פריטים בלי תיאור — 618 פרקים ב-10 סדרות, ו-105 ערוצי שידור חי
    (לאף ערוץ חי אין תיאור, מעולם לא היה).
  • 98 פריטים בלי פוסטר — כולם הסדרה "המאה", שאין לה גם שום מטא־דאטה.
  • 6 קטגוריות שגויות ודאיות (ראה CATEGORY_FIXES).

## מה הסקריפט עושה

  1. **ממלא תיאורים ופוסטרים** מ-TMDB, ברמת הסדרה — כי כך הקטלוג בנוי:
     לכל פרקי הסדרה אותו תיאור ואותו פוסטר (נבדק על "הבור", "וואן פיס").
  2. **רק כשהזיהוי ודאי.** או מזהה TMDB מפורש שנבדק ידנית, או תוצאת חיפוש
     שהשנה שלה תואמת בדיוק לשנה שבקטלוג. בספק — לא נוגע, ומדווח.
  3. **מתקן קטגוריות** — רק את הרשימה הסגורה שלמטה, שכל שורה בה נבדקה.
  4. **מדווח** על כל מה שהוא לא נגע בו, כולל חשדות קטגוריה לפי ז'אנר TMDB,
     כדי שתחליט בעצמך.

לעולם לא דורס תיאור או פוסטר קיימים — רק ממלא ריקים.

    python3 fix_catalog_meta.py --check     סורק ומדפיס דוח, לא כותב כלום
    python3 fix_catalog_meta.py             מחיל
    python3 fix_catalog_meta.py --revert    מחזיר את הקטלוג מהגיבוי
"""
import json
import os
import re
import shutil
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

DATA = os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data")
CONTENT = os.path.join(DATA, "content.json")
ENV = os.environ.get("ZOVEX_ENV", "/opt/zovex-bot/.env")
BAK = CONTENT + ".bak_catalog_meta"
REPORT = os.path.join(DATA, "catalog_meta_report.txt")
TMDB = os.environ.get("TMDB_BASE", "https://api.themoviedb.org/3")
IMG = "https://image.tmdb.org/t/p/w500"

# ── תיקוני קטגוריה ─────────────────────────────────────────────────────────
# רשימה סגורה. כל שורה נבדקה אחת-אחת, ולא נוצרת מחיפוש אוטומטי.
#   (סוג, שם, שנה או None, קטגוריה נוכחית או None=כל אחת, קטגוריה חדשה, נימוק)
CATEGORY_FIXES = [
    # ארבעת הסרטים הראשונים בסדרות שההמשכים שלהם כבר בקטגוריית מארוול.
    ("movie", "דוקטור סטריינג'", 2016, None, "מארוול",
     "MCU — ההמשך 'בממדי הטירוף' כבר במארוול"),
    ("movie", "שומרי הגלקסיה", 2014, None, "מארוול",
     "MCU — חלק 2 ו-3 כבר במארוול"),
    ("movie", "הפנתר השחור", 2018, None, "מארוול",
     "MCU — 'וואקנדה לנצח' כבר במארוול"),
    ("movie", "האלמנה השחורה", 2021, None, "מארוול",
     "MCU"),
    # אנימציה למבוגרים (TV-MA) שיושבת בקטגוריית הילדים.
    ("series", "ריק ומורטי", None, "סדרות לילדים", "סדרות",
     "אנימציה למבוגרים בדירוג TV-MA — לא תוכן ילדים"),
    # הסדרה מפוצלת בין שתי קטגוריות; היא ישראלית (פרודיה בהנחיית שני כהן).
    ("series", "אחת שיודעת", None, "סדרות", "סדרות ישראליות",
     "סדרה ישראלית שהייתה מפוצלת 121/28 בין שתי קטגוריות"),
]

# ── זיהוי לסדרות/סרטים שחסר להם תיאור או פוסטר ─────────────────────────────
# tmdb: מזהה שנבדק ידנית. q: טקסט חיפוש כשאין מזהה.
# expect_year: חייב להתאים לשנה שמחזיר TMDB, אחרת לא נוגעים.
HINTS = {
    # ודאי — מזהי TMDB שנבדקו
    "המאה": dict(kind="tv", tmdb=48866, expect_year=2014,
                 note="The 100 — 7 עונות, 100 פרקים"),
    "דרגון בול לעברית": dict(kind="tv", tmdb=12609, expect_year=1986,
                             note="Dragon Ball המקורית, 153 פרקים"),
    "דרגון בול ג'יטי לעברית": dict(kind="tv", tmdb=12610, expect_year=1996,
                                   note="Dragon Ball GT, 64 פרקים"),
    "דרגון בול זד": dict(kind="tv", tmdb=12971, expect_year=1989,
                         note="Dragon Ball Z"),
    # חיפוש — נכתב רק אם השנה תואמת
    "הסיפור שלנו": dict(kind="tv", q="Bizim Hikaye", expect_year=2017),
    "פלוריבוס": dict(kind="tv", q="Pluribus", expect_year=2025),
    "בו, ביץ'!": dict(kind="tv", q="Boo, Bitch", expect_year=2022),
    "דרגון בול": dict(kind="tv", q="Super Dragon Ball Heroes", expect_year=2018),
    "דם רע": dict(kind="tv", q="דם רע", expect_year=2024),
    "9 אגוזים": dict(kind="tv", q="9 אגוזים", expect_year=2023),
    "Drive Through Fire": dict(kind="movie", q="Drive Through Fire", expect_year=2026),
    "Sacrifice": dict(kind="movie", q="Sacrifice", expect_year=2026),
    "אומהה": dict(kind="movie", q="Omaha", expect_year=2025),
    "He's Watching You": dict(kind="movie", q="He's Watching You", expect_year=2026),
    "Sultana": dict(kind="movie", q="Sultana", expect_year=2026),
    "Lion Fist": dict(kind="movie", q="Lion Fist", expect_year=2026),
}

# ── ערוצי שידור חי ─────────────────────────────────────────────────────────
# ל-TMDB אין ערוצי טלוויזיה, ולכן התיאורים כאן נכתבו ידנית. כל שורה מתארת
# מה באמת משודר בערוץ; ערוץ שלא ידענו לתאר במדויק פשוט אינו ברשימה.
LIVE_DESC = {
    "כאן11": "ערוץ השידור הציבורי — חדשות, אקטואליה, תעודה ודרמה ישראלית.",
    "רשת 13": "ערוץ מסחרי — חדשות, ריאליטי, בידור ותוכניות אירוח.",
    "Mako(+12)": "קשת 12 — חדשות, ריאליטי, דרמה ובידור.",
    "ערוץ 24": "ערוץ המוזיקה הישראלית — קליפים, הופעות ותוכניות מוזיקה.",
    "ערוץ 9": "ערוץ בשפה הרוסית — חדשות, סדרות ותוכניות אירוח.",
    "i24": "ערוץ חדשות בינלאומי מישראל, בשידור רצוף.",
    "C14": "ערוץ חדשות ואקטואליה.",
    "ערוץ הכנסת": "שידורים ישירים ממליאת הכנסת ומהוועדות.",
    "כאן חינוכית": "הטלוויזיה החינוכית — תוכניות ילדים, נוער וידע.",
    "מכאן 33": "ערוץ השידור הציבורי בערבית.",
    "ערוץ 98": "ערוץ ספורט ואורח חיים.",
    "ים תיכוני": "מוזיקה ים-תיכונית — קליפים והופעות.",
    "חיים טובים": "אורח חיים, בריאות, בישול ועיצוב הבית.",
    "הופ!": "ערוץ הילדים הצעירים — שירים, סיפורים ותוכניות לגיל הרך.",
    "בית+": "ערוץ עיצוב, שיפוצים ואורח חיים.",
    # ילדים
    "ניקולודיון": "ערוץ הילדים של ניקלודיאון — אנימציה, קומדיה וסדרות נוער.",
    "טין ניק": "ניקלודיאון לנוער — סדרות וקומדיה לגילאי העשרה.",
    "ניק ג'וניור": "ניקלודיאון לגיל הרך — אנימציה ותוכניות לפעוטות.",
    "דיסני ג'וניור": "דיסני לגיל הרך — אנימציה ושירים לפעוטות.",
    "דסני": "ערוץ דיסני — סדרות, אנימציה וסרטים לילדים ולנוער.",
    "ערוץ לולי": "ערוץ לגיל הרך — שירים, סיפורים ותוכניות לפעוטות.",
    "בייבי": "ערוץ לתינוקות ולפעוטות — תוכן רגוע, שירים וסיפורים.",
    "ערוץ גוניור": "ערוץ ילדים — אנימציה וסדרות לגילאים הצעירים.",
    "ערוץ הכוכבים": "ערוץ ילדים ונוער — סדרות, אנימציה ובידור.",
    "סלקום קידס": "ערוץ ילדים — אנימציה וסדרות.",
    "זום": "ערוץ הנוער — סדרות, ריאליטי ובידור לגילאי העשרה.",
    "WIZ": "ערוץ ילדים ונוער — אנימציה, סדרות ובידור.",
    "קריוקי": "שירה בציבור — קליפים עם מילים על המסך, ברצף.",
    # ספורט
    "ספורט 1": "ערוצי הספורט — שידורים חיים, ליגות וסיקור ספורט.",
    "ספורט 2": "ערוצי הספורט — שידורים חיים, ליגות וסיקור ספורט.",
    "ספורט 3": "ערוצי הספורט — שידורים חיים, ליגות וסיקור ספורט.",
    "ספורט 4": "ערוצי הספורט — שידורים חיים, ליגות וסיקור ספורט.",
    "ספורט 5": "ספורט 5 — כדורגל, כדורסל וספורט בשידור חי.",
    "ספורט 6": "ערוצי הספורט — שידורים חיים, ליגות וסיקור ספורט.",
    "ספורט 5 פלוס": "ספורט 5 פלוס — שידורי ספורט חיים נוספים.",
    "ספורט 5 לייב": "ספורט 5 לייב — שידורים חיים ואירועי ספורט.",
    "ספורט 5 מקס": "ספורט 5 מקס — שידורי ספורט חיים.",
    "ספורט 5 גולד": "ספורט 5 גולד — שידורי ספורט ומשחקי עבר.",
    "ספורט 5 סטארס": "ספורט 5 סטארס — ספורט, תוכניות ואולפנים.",
    "one 1": "ONE — ספורט, אולפנים וסיקור ליגות.",
    "one 2": "ONE — ספורט, אולפנים וסיקור ליגות.",
    "one edge": "ONE EDGE — ספורט ותוכניות ספורט.",
    "יורוספורט 2": "יורוספורט — ספורט אירופי בשידור חי.",
    "UFC": "אומנויות לחימה מעורבות — קרבות ואירועי UFC.",
    # סרטים וסדרות
    "HOT cinema1": "HOT Cinema — סרטי קולנוע ברצף.",
    "Hotcinema2": "HOT Cinema — סרטי קולנוע ברצף.",
    "HOT cinema 3": "HOT Cinema — סרטי קולנוע ברצף.",
    "HOT cinema 4": "HOT Cinema — סרטי קולנוע ברצף.",
    "HOT GOLD": "HOT Gold — סרטים וסדרות קלאסיים.",
    "HOT HBO": "HBO — סדרות דרמה וקומדיה של HBO.",
    "HOT סדרות": "HOT — סדרות דרמה וקומדיה ברצף.",
    "HOT בידור": "HOT — בידור, תוכניות אירוח וריאליטי.",
    "HOT ריל": "HOT Real — ריאליטי ותוכניות מציאות.",
    "HOT Real": "HOT Real — ריאליטי ותוכניות מציאות.",
    "HOT Comedy": "HOT Comedy — סדרות קומדיה ברצף.",
    "HOT משפחה": "HOT — תוכן לכל המשפחה.",
    "הוט משפחה גיבוי": "HOT — תוכן לכל המשפחה.",
    "HOT 3": "HOT 3 — סדרות, סרטים ובידור.",
    "HOT 8": "HOT 8 — סדרות, סרטים ובידור.",
    "הוט זון": "HOT Zone — סדרות ובידור.",
    "הוט דרמה": "HOT Drama — סדרות דרמה ברצף.",
    "yes Drama": "yes — סדרות דרמה.",
    "yes Comedy": "yes — סדרות קומדיה.",
    "yes Action": "yes — סדרות ותוכן אקשן.",
    "yes ישראלי": "yes — תוכן ישראלי מקורי.",
    "yes דוקו": "yes — סרטי וסדרות תעודה.",
    "yes Movies Comedy": "yes Movies — סרטי קומדיה.",
    "yes Movies Drama": "yes Movies — סרטי דרמה.",
    "yes Movies Kids": "yes Movies — סרטים לילדים ולמשפחה.",
    "Yes Movies Action": "yes Movies — סרטי אקשן.",
    "cellcom קולנוע הישראלי": "קולנוע ישראלי — סרטים ישראליים ברצף.",
    # תעודה ואורח חיים
    "נשיונל גאוגרפיק": "נשיונל ג'יאוגרפיק — תעודה, טבע, מדע והיסטוריה.",
    "נשיונל ווילד": "נשיונל ג'יאוגרפיק וויילד — עולם החי והטבע.",
    "ערוץ ההיסטוריה": "ערוץ ההיסטוריה — סדרות תעודה על העבר.",
    "דיסקברי": "דיסקברי — מדע, טכנולוגיה, הרפתקאות ותעודה.",
    "פרי דוקו": "סרטי תעודה ברצף.",
    "Food Network": "Food Network — בישול, אפייה ותחרויות קולינריה.",
    "Health": "בריאות, כושר ואורח חיים.",
    "E!": "E! — בידור, סלבריטאים ותרבות פופולרית.",
    # לועזי / טלנובלות
    "ויוה טלנובלות": "ויוה — טלנובלות ודרמות.",
    "ויוה פרימיום": "ויוה — דרמות וטלנובלות.",
    "ויוה וינטג'": "ויוה — טלנובלות קלאסיות.",
    "ויוה איסטנבול": "ויוה — דרמות טורקיות.",
    "דרמות טורקיות": "דרמות טורקיות ברצף.",
    "דרמות טורקיות 2": "דרמות טורקיות ברצף.",
    "דרמות טורקיות 3": "דרמות טורקיות ברצף.",
    "הדרמות הטורקיות+": "דרמות טורקיות ברצף.",
    "הדרמות הטורקיות 2": "דרמות טורקיות ברצף.",
    "הדרמות הטורקיות 3": "דרמות טורקיות ברצף.",
    "דרמות הודיות 1": "דרמות הודיות ברצף.",
    "דרמות הודיות 2": "דרמות הודיות ברצף.",
    "דרמות ספרדיות 1": "דרמות ספרדיות ברצף.",
    "דרמות ספרדיות 2": "דרמות ספרדיות ברצף.",
    "סרטים הודיים — Bollywood": "סרטי בוליווד — קולנוע הודי ברצף.",
    # FREE TV
    "FREE TV ישראל": "FREE TV — תוכן ישראלי.",
    "FREE TV סרטים": "FREE TV — סרטים ברצף.",
    "FREE TV דרמה": "FREE TV — דרמה.",
    "FREE TV רומנטיקה": "FREE TV — רומנטיקה.",
    "FREETV אימה": "FREE TV — סרטי אימה ומתח.",
    "FREE TVקומדיה": "FREE TV — קומדיה.",
    "FREE TV קומדיה 2": "FREE TV — קומדיה.",
    "FREE TV משפחה": "FREE TV — תוכן לכל המשפחה.",
    "FREE TV אוכל": "FREE TV — בישול ואוכל.",
    "FREE TV לייף סטייל": "FREE TV — אורח חיים.",
    "FREE TV גלובלי": "FREE TV — תוכן בינלאומי.",
}


# ── עזר ────────────────────────────────────────────────────────────────────

def blank(v):
    return v is None or (isinstance(v, str) and not v.strip())


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).lower()
    return re.sub(r"[^a-z0-9֐-׿]+", "", s)


def read_key():
    """TMDB_API_KEY מתוך .env. לא מודפס ולא נכתב לשום מקום."""
    try:
        with open(ENV, encoding="utf-8") as f:
            for line in f:
                if line.startswith("TMDB_API_KEY"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return os.environ.get("TMDB_API_KEY", "").strip()


class Tmdb:
    def __init__(self, key):
        self.key = key
        self.n = 0

    def get(self, path, **params):
        if not self.key:
            return None
        params["api_key"] = self.key
        url = f"{TMDB}{path}?" + urllib.parse.urlencode(params)
        for attempt in range(3):
            try:
                self.n += 1
                req = urllib.request.Request(url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    return json.loads(r.read().decode("utf-8"))
            except Exception as e:
                code = getattr(e, "code", None)
                if code == 404:
                    return None
                if code == 429:          # מגבלת קצב — ממתינים ומנסים שוב
                    time.sleep(2 + attempt * 2)
                    continue
                if attempt == 2:
                    return None
                time.sleep(1 + attempt)
        return None

    def details(self, kind, tid):
        # he-IL קודם; TMDB מחזיר overview ריק כשאין תרגום, ואז נופלים לאנגלית
        he = self.get(f"/{kind}/{tid}", language="he-IL")
        if not he:
            return None
        if not (he.get("overview") or "").strip():
            en = self.get(f"/{kind}/{tid}", language="en-US")
            if en and (en.get("overview") or "").strip():
                he["overview"] = en["overview"]
                he["_overview_lang"] = "en"
        return he

    def search(self, kind, q, year=None):
        p = {"query": q, "language": "he-IL", "include_adult": "false"}
        if year:
            p["first_air_date_year" if kind == "tv" else "year"] = year
        r = self.get(f"/search/{kind}", **p)
        return (r or {}).get("results") or []


def year_of(det, kind):
    d = det.get("first_air_date") if kind == "tv" else det.get("release_date")
    try:
        return int(str(d or "")[:4])
    except ValueError:
        return None


def title_of(det, kind):
    return det.get("name") if kind == "tv" else det.get("title")


def en_title_of(det, kind):
    return (det.get("original_name") if kind == "tv"
            else det.get("original_title")) or title_of(det, kind)


# ── הסריקה ─────────────────────────────────────────────────────────────────

def group_key(it):
    return it.get("series_name") or it.get("title")


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    dry = arg in ("--check", "--dry-run", "--report")

    if arg == "--revert":
        if not os.path.exists(BAK):
            print(f"❌ אין גיבוי ב-{BAK}")
            return 1
        shutil.copyfile(BAK, CONTENT)
        print("✓ הקטלוג שוחזר מהגיבוי. השרת יטען אותו מחדש לבד.")
        return 0

    if not os.path.exists(CONTENT):
        print(f"❌ לא נמצא {CONTENT}")
        return 1

    st0 = os.stat(CONTENT)
    with open(CONTENT, encoding="utf-8") as f:
        items = json.load(f)
    if not isinstance(items, list) or not items:
        print("❌ הקטלוג אינו רשימה או שהוא ריק — לא נוגע")
        return 1
    print(f"קטלוג: {len(items):,} פריטים\n")

    key = read_key()
    api = Tmdb(key)
    if not key:
        print("⚠ אין TMDB_API_KEY — אפשר רק לדווח, בלי למלא מ-TMDB.\n")

    log = []                       # שורות הדוח
    changed = 0                    # כמה פריטים שונו בפועל

    def note(s):
        log.append(s)
        print(s)

    # ── 1. קטגוריות ────────────────────────────────────────────────────────
    note("════════ 1/4 · קטגוריות ════════")
    for kind, name, yr, from_cat, to_cat, why in CATEGORY_FIXES:
        if kind == "series":
            hits = [i for i in items if i.get("series_name") == name]
        else:
            hits = [i for i in items if not i.get("series_name")
                    and i.get("title") == name
                    and (yr is None or str(i.get("year") or "") == str(yr))]
        if from_cat:
            hits = [i for i in hits if i.get("category") == from_cat]
        hits = [i for i in hits if i.get("category") != to_cat]
        if not hits:
            note(f"  ● {name} — כבר במקום, אין מה לשנות")
            continue
        was = sorted({i.get("category") for i in hits})
        note(f"  ✓ {name} ({len(hits)}) : {', '.join(map(str, was))} → {to_cat}")
        note(f"      {why}")
        if not dry:
            for i in hits:
                i["category"] = to_cat
            changed += len(hits)

    # ── 2. תיאורים ופוסטרים מ-TMDB ─────────────────────────────────────────
    note("\n════════ 2/4 · תיאורים ופוסטרים מ-TMDB ════════")
    groups = {}
    for it in items:
        if it.get("category") == "שידורים חיים":
            continue
        if blank(it.get("description")) or blank(it.get("thumbnail_url")):
            groups.setdefault(group_key(it), []).append(it)

    for name in sorted(groups, key=lambda n: -len(groups[n])):
        grp = groups[name]
        # תיאור/פוסטר שכבר קיימים באחים באותה קבוצה — עדיפים על TMDB
        sibs = [i for i in items if group_key(i) == name]
        have_desc = next((i["description"] for i in sibs
                          if not blank(i.get("description"))), "")
        have_poster = next((i["thumbnail_url"] for i in sibs
                            if not blank(i.get("thumbnail_url"))), "")

        hint = HINTS.get(name)
        det = None
        kind = (hint or {}).get("kind") or ("tv" if grp[0].get("series_name") else "movie")
        why = ""
        if hint and hint.get("tmdb"):
            det = api.details(kind, hint["tmdb"])
            if det:
                y = year_of(det, kind)
                if hint.get("expect_year") and y != hint["expect_year"]:
                    why = f"מזהה {hint['tmdb']} מחזיר שנה {y}, ציפינו {hint['expect_year']}"
                    det = None
        elif hint and hint.get("q"):
            want = hint.get("expect_year")
            for r in api.search(kind, hint["q"], want)[:5]:
                d2 = api.details(kind, r["id"])
                if d2 and (not want or year_of(d2, kind) == want):
                    det = d2
                    break
            if det is None:
                why = f"חיפוש '{hint['q']}' לא החזיר תוצאה עם שנה {want}"
        else:
            why = "אין רמז מאומת — לא מנחשים"

        new_desc = ""
        new_poster = ""
        if det:
            new_desc = (det.get("overview") or "").strip()
            if det.get("poster_path"):
                new_poster = IMG + det["poster_path"]
        desc = have_desc or new_desc
        poster = have_poster or new_poster

        nd = [i for i in grp if blank(i.get("description"))]
        np_ = [i for i in grp if blank(i.get("thumbnail_url"))]

        # מדווחים בנפרד על כל שדה. קבוצה שיש לה פוסטר אבל אין לה תיאור בשום
        # מקום צריכה להופיע ככישלון על התיאור, ולא כ"✓" מטעה.
        src = []
        if det:
            src.append(f"TMDB {det.get('id')} · {title_of(det, kind)} ({year_of(det, kind)})")
            if det.get("_overview_lang") == "en":
                src.append("תיאור באנגלית — אין תרגום ב-TMDB")
        elif have_desc or have_poster:
            src.append("מתוך פריט אחר באותה קבוצה")
        tag = " | ".join(src)

        done, fail = [], []
        if nd:
            (done if desc else fail).append(f"{len(nd)} תיאורים")
        if np_:
            (done if poster else fail).append(f"{len(np_)} פוסטרים")
        if done:
            note(f"  ✓ {name} — מילוי {', '.join(done)}  ({tag})")
        if fail:
            note(f"  ✗ {name} — {', '.join(fail)} לא מולאו. {why or 'אין מקור'}")

        if dry or not done:
            continue
        for i in grp:
            if blank(i.get("description")) and desc:
                i["description"] = desc
                changed += 1
            if blank(i.get("thumbnail_url")) and poster:
                i["thumbnail_url"] = poster
                changed += 1
        # מטא־דאטה משלימה, רק לשדות ריקים
        if det:
            for i in [x for x in items if group_key(x) == name]:
                if not i.get("tmdb_id"):
                    i["tmdb_id"] = det.get("id")
                if blank(i.get("en_title")):
                    i["en_title"] = en_title_of(det, kind)
                if not i.get("year"):
                    i["year"] = year_of(det, kind)

    # ── 3. ערוצי שידור חי ──────────────────────────────────────────────────
    note("\n════════ 3/4 · ערוצי שידור חי ════════")
    live = [i for i in items if i.get("category") == "שידורים חיים"]
    filled = [i for i in live if blank(i.get("description"))
              and LIVE_DESC.get(i.get("title"))]
    missing = sorted({i.get("title") for i in live
                      if blank(i.get("description"))
                      and not LIVE_DESC.get(i.get("title"))})
    note(f"  {len(live)} ערוצים · ממלא תיאור ל-{len(filled)}")
    if missing:
        note(f"  ✗ {len(missing)} בלי תיאור (לא ידענו לתאר במדויק): "
             + ", ".join(missing))
    if not dry:
        for i in filled:
            i["description"] = LIVE_DESC[i["title"]]
            changed += 1

    # ── 4. חשדות קטגוריה לפי ז'אנר TMDB — דיווח בלבד ───────────────────────
    note("\n════════ 4/4 · חשדות קטגוריה (דיווח בלבד, לא משנה כלום) ════════")
    if not key:
        note("  (מדלג — אין מפתח TMDB)")
    else:
        seen = {}
        for it in items:
            tid = it.get("tmdb_id")
            if not tid or it.get("category") == "שידורים חיים":
                continue
            k = (group_key(it), it.get("category"), tid,
                 "tv" if it.get("series_name") else "movie")
            seen.setdefault(k, 0)
            seen[k] += 1
        note(f"  בודק ז'אנרים ל-{len(seen)} כותרים…")
        sus = []
        for (name, cat, tid, kind), n in seen.items():
            det = api.get(f"/{kind}/{tid}", language="en-US")
            if not det:
                continue
            gen = {g["name"] for g in (det.get("genres") or [])}
            cc = set(det.get("origin_country") or [])
            if "Horror" in gen and cat not in ("אימה",):
                sus.append(f"אימה? [{cat}] {name} ({n}) — ז'אנר Horror")
            elif "TR" in cc and cat not in ("סדרות טורקיות",):
                sus.append(f"טורקי? [{cat}] {name} ({n}) — מדינת מקור TR")
            elif "JP" in cc and "Animation" in gen and cat not in ("אנימה",):
                sus.append(f"אנימה? [{cat}] {name} ({n}) — אנימציה יפנית")
            elif "IL" in cc and cat in ("סדרות", "סרטים"):
                sus.append(f"ישראלי? [{cat}] {name} ({n}) — מדינת מקור IL")
        for s in sorted(sus):
            note("  • " + s)
        if not sus:
            note("  ✓ לא נמצאו חשדות")

    # ── כתיבה ──────────────────────────────────────────────────────────────
    note("")
    if dry:
        note("--check: שום דבר לא נכתב.")
    elif changed == 0:
        note("אין מה לשנות — הקטלוג כבר תקין.")
    else:
        st1 = os.stat(CONTENT)
        if (st1.st_mtime_ns, st1.st_size) != (st0.st_mtime_ns, st0.st_size):
            note("❌ הקטלוג השתנה בזמן הריצה (כנראה העלאה) — לא כותב. הרץ שוב.")
            return 1
        if not os.path.exists(BAK):
            shutil.copyfile(CONTENT, BAK)
        tmp = CONTENT + ".tmp_catalog_meta"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        # לא מחליפים לפני שהתוצאה נקראת בחזרה ונמצאה שלמה
        with open(tmp, encoding="utf-8") as f:
            back = json.load(f)
        if len(back) != len(items):
            os.unlink(tmp)
            note("❌ הקובץ שנכתב אינו שלם — לא מחליף.")
            return 1
        os.replace(tmp, CONTENT)
        note(f"✓ עודכנו {changed:,} שדות ב-{len(items):,} פריטים.")
        note(f"  גיבוי: {BAK}")
        note("  לביטול:  python3 fix_catalog_meta.py --revert")
    note(f"  קריאות TMDB: {api.n}")

    try:
        with open(REPORT, "w", encoding="utf-8") as f:
            f.write("\n".join(log) + "\n")
        print(f"\nהדוח המלא נשמר ב-{REPORT}")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
