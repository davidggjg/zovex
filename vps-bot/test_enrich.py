#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בדיקות ל-tmdb_enrich, בלי רשת ובלי לגעת בקטלוג האמיתי.

הקובץ הזה נכתב לפני ההרצה הראשונה על נתונים אמיתיים ולא אחריה. זה
השלב היחיד בצינור שכותב לקטלוג בפועל — תיאורים, פוסטרים, שנים
וקטגוריות על מאות סדרות — ולכן ההתנהגות שלו נבדקת מראש: מה נדרס,
מה לא, ומה קורה כשמזהה שגוי.
"""
import importlib.util, json, os, shutil, sys, tempfile
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
SP = tempfile.mkdtemp(prefix="zovex_enrich_")
os.environ["ZOVEX_DATA"] = SP          # נקרא בזמן טעינת המודול
os.environ["TMDB_API_KEY"] = "FAKE"

spec = importlib.util.spec_from_file_location("E", os.path.join(HERE, "tmdb_enrich.py"))
E = importlib.util.module_from_spec(spec); spec.loader.exec_module(E)

fails = []


def eq(got, want, label):
    if got != want:
        fails.append(f"{label}: קיבלתי {got!r} ציפיתי {want!r}")


# ── plan_item: מה נדרס ומה לא ────────────────────────────────────────────────
HE = {"overview": "תיאור בעברית", "name": "שובר שורות",
      "first_air_date": "2008-01-20", "poster_path": "/he.jpg",
      "genres": [{"id": 18}], "original_language": "en"}
EN = {"overview": "English overview", "name": "Breaking Bad",
      "first_air_date": "2008-01-20", "poster_path": "/en.jpg",
      "genres": [{"id": 18}], "original_language": "en"}
D = {"he": HE, "en": EN}

new = E.plan_item({}, D, force=False)
eq(new.get("description"), "תיאור בעברית", "עברית מועדפת לתיאור")
eq(new.get("en_title"), "Breaking Bad", "שם באנגלית")
eq(new.get("year"), "2008", "שנה מ-first_air_date")
eq(new.get("thumbnail_url"), "https://image.tmdb.org/t/p/w500/he.jpg", "פוסטר")

# תיאור קיים לא נדרס
new = E.plan_item({"description": "מה שכבר היה"}, D, force=False)
eq("description" in new, False, "תיאור קיים נשאר")
new = E.plan_item({"description": "מה שכבר היה"}, D, force=True)
eq(new.get("description"), "תיאור בעברית", "--force כן דורס")

# כל השדות כבר קיימים → אין שינוי בכלל
full = {"description": "א", "en_title": "ב", "year": "1999",
        "thumbnail_url": "x", "category": "אימה"}
eq(E.plan_item(full, D, force=False), {}, "פריט מלא לא משתנה")

# נפילה-אחורה לאנגלית כשאין תרגום עברי. TMDB מחזיר overview ריק ולא
# חסר, ולכן הבדיקה חייבת להיות על תוכן ולא על קיום המפתח.
new = E.plan_item({}, {"he": dict(HE, overview=""), "en": EN}, force=False)
eq(new.get("description"), "English overview", "נפילה-אחורה לאנגלית")

# שום שדה ריק לא נכתב
empty = {"he": {}, "en": {}}
eq(E.plan_item({}, empty, force=False), {}, "בלי נתונים — בלי שינוי")
eq(E.plan_item({}, {"he": {"overview": "   "}, "en": {}}, force=False), {},
   "תיאור של רווחים בלבד לא נכתב")

# שנה: release_date לסרט, ותאריך פסול לא נכתב
new = E.plan_item({}, {"he": {"release_date": "1994-09-23"}, "en": {}},
                  force=False)
eq(new.get("year"), "1994", "שנה מ-release_date")
new = E.plan_item({}, {"he": {"release_date": "לא-תאריך"}, "en": {}},
                  force=False)
eq("year" in new, False, "תאריך פסול לא נכתב")

# ── קטגוריות: רק מה שחד-משמעי ───────────────────────────────────────────────
def cat(gids, lang="en", cur=None):
    g = [{"id": i} for i in gids]
    d = {"he": {}, "en": {"genres": g, "original_language": lang}}
    return E.plan_item({"category": cur} if cur else {}, d, force=False).get("category")


eq(cat([16], "ja"), "אנימה", "אנימציה יפנית = אנימה")
eq(cat([16], "en"), "סרטים לילדים (מתאים גם למשפחה)",
   "אנימציה לא יפנית = ילדים, לא אנימה")
eq(cat([27]), "אימה", "אימה")
eq(cat([10751]), "סרטים לילדים (מתאים גם למשפחה)", "משפחה")
eq(cat([18]), None, "דרמה לא ממופה — קטגוריה שגויה גרועה מחסרה")
eq(cat([28, 12]), None, "אקשן/הרפתקאות לא ממופים")
eq(cat([16, 27], "ja"), "אנימה", "אנימציה גוברת על אימה כשהיא יפנית")
eq(cat([27], cur="אנימה"), None, "קטגוריה קיימת לא נדרסת")

# ── fetch: היפוך סוג כשהמזהה נשמר תחת הסוג הלא-נכון ────────────────────────
CALLS = []
TV_ONLY = {"501": {"name": "מיני סדרה", "overview": "יש"}}


def fake_get(url, timeout=40):
    CALLS.append(url)
    # /movie/501 לא קיים, /tv/501 כן — בדיוק המקרה שהיה נספר כ"לא נענה"
    if "/movie/501" in url:
        raise RuntimeError("404")
    if "/tv/501" in url:
        return TV_ONLY["501"]
    if "/tv/999" in url or "/movie/999" in url:
        raise RuntimeError("404")
    return {"name": "רגיל", "overview": "או"}


E.get = fake_get
E.KIND_FLIPS.clear(); CALLS.clear()
d = E.fetch("K", "movie", 501)
eq(bool(d.get("he") or d.get("en")), True, "היפוך סוג מצא את הפריט")
eq(dict(E.KIND_FLIPS), {"movie→tv": 1}, "ההיפוך נספר ולא נבלע")
eq(d.get("kind"), "tv", "והסוג שנענה בפועל מדווח")

E.KIND_FLIPS.clear(); CALLS.clear()
eq(E.fetch("K", "tv", 7).get("kind"), "tv", "בלי היפוך — הסוג המקורי")

E.KIND_FLIPS.clear(); CALLS.clear()
d = E.fetch("K", "tv", 999)
eq({k: v for k, v in d.items() if k != "kind"}, {"he": {}, "en": {}},
   "מזהה שלא קיים בשום סוג חוזר ריק")
eq(d.get("kind"), "tv", "וגם אז הסוג מדווח")
# main בודק he/en במפורש ולא את האמיתות של d, ולכן התוספת של kind
# לא הופכת תשובה ריקה ל"נענתה"
eq(bool(d.get("he") or d.get("en")), False, "kind לא מסווה כשל")
eq(dict(E.KIND_FLIPS), {}, "ובלי לדווח על היפוך")
eq(len(CALLS), 4, "נוסו שתי שפות בשני סוגים")

E.KIND_FLIPS.clear(); CALLS.clear()
E.fetch("K", "tv", 7)
eq(len(CALLS), 2, "סוג שנענה מיד — בלי ניסיון שני")

# ── דיווח סתירות: הסימן היחיד שמזהה שגוי ────────────────────────────────────
# שנה ושם באנגלית שלא מסתדרים עם TMDB הם מה שחשף ש"300" בקטלוג הצביע
# על רשומת זבל. תיאור ופוסטר *תמיד* שונים ולכן לא נחשבים סתירה.
cl = []
E.plan_item({"year": "1999", "en_title": "Wrong Title",
             "description": "הניסוח שלנו", "thumbnail_url": "https://x/y.jpg"},
            {"he": {}, "en": {"name": "Breaking Bad",
                              "first_air_date": "2008-01-20",
                              "overview": "TMDB text", "poster_path": "/z.jpg"}},
            force=False, conflicts=cl)
eq(sorted(f for f, _, _, _ in cl), ["en_title", "year"],
   "רק שנה ושם באנגלית נחשבים סתירה")
eq([(c, v) for f, _, c, v in cl if f == "year"], [("1999", "2008")],
   "הערך שאצלנו והערך ב-TMDB מדווחים שניהם")

# שדה תואם אינו סתירה, וגם לא הפרש רווחים בלבד
cl = []
E.plan_item({"year": "2008", "en_title": " Breaking Bad "},
            {"he": {}, "en": {"name": "Breaking Bad",
                              "first_air_date": "2008-05-05"}},
            force=False, conflicts=cl)
eq(cl, [], "ערך זהה (וגם עם רווחים) אינו סתירה")

# --force כותב ולא מדווח: הערך נכנס ל-new ולא ל-conflicts
cl = []
new = E.plan_item({"year": "1999"},
                  {"he": {}, "en": {"first_air_date": "2008-01-20"}},
                  force=True, conflicts=cl)
eq(new.get("year"), "2008", "--force כותב את הערך")
eq(cl, [], "--force לא מדווח סתירה על מה שהוא דרס")

# שדה חסר אינו סתירה — הוא פשוט מתמלא
cl = []
new = E.plan_item({}, {"he": {}, "en": {"first_air_date": "2008-01-20"}},
                  force=False, conflicts=cl)
eq(new.get("year"), "2008", "שדה חסר מתמלא")
eq(cl, [], "שדה חסר אינו סתירה")

# וללא conflicts בכלל — התנהגות זהה לקודם, בלי קריסה
eq(E.plan_item({"year": "1999"},
               {"he": {}, "en": {"first_air_date": "2008-01-20"}},
               force=False), {}, "בלי conflicts הפונקציה עובדת כמו קודם")

# ── הזרימה המלאה: קיבוץ, כתיבה, גיבוי, גרסה, revert ────────────────────────
CAT_ITEMS = (
    # סדרה של 3 פרקים עם אותו מזהה = בקשה אחת
    [{"id": i, "series_name": "שובר שורות", "title": f"פרק {i}",
      "tmdb_id": 1396} for i in range(3)]
    + [{"id": 10, "title": "סרט", "tmdb_id": 550},
       # שידור חי — לא נגעים בו בכלל
       {"id": 11, "title": "ערוץ", "tmdb_id": 1, "is_live": True},
       # בלי מזהה — לא נגעים בו
       {"id": 12, "title": "בלי מזהה"}]
)
E.CONTENT.write_text(json.dumps(CAT_ITEMS, ensure_ascii=False), encoding="utf-8")

FETCHED = []


def fake_get2(url, timeout=40):
    """מחזיר שדות לפי הסוג, כמו TMDB האמיתי.

    זה לא פרט טכני: תשובה של tv נושאת name/first_air_date ותשובה של
    movie נושאת title/release_date. גרסה ראשונה של הבדיקה החזירה את
    כולם יחד, וזה הפך את סדר העדיפויות ב-plan_item לבלתי-נבדק.
    """
    FETCHED.append(url.split("?")[0])
    base = {"overview": "תיאור", "poster_path": "/p.jpg",
            "genres": [{"id": 27}], "original_language": "en"}
    if "/tv/" in url:
        return dict(base, name="Breaking Bad", first_air_date="2008-01-20")
    return dict(base, title="Fight Club", release_date="1999-10-15")


E.get = fake_get2


def run(argv):
    sys.argv = ["tmdb_enrich.py", "--sleep", "0"] + argv
    E.main()


print("─" * 62)
run(["--check"])
after_check = json.loads(E.CONTENT.read_text(encoding="utf-8"))
eq(after_check, CAT_ITEMS, "--check לא כתב כלום")
eq(E.BACKUP.exists(), False, "--check לא יצר גיבוי")
# 4 קריאות = 2 יחידות × 2 שפות. הסדרה היא בקשה אחת ולא שלוש.
eq(len(FETCHED), 4, "קיבוץ לפי (סוג, מזהה): 2 יחידות ולא 5")
eq(sorted(set(FETCHED)), sorted({"https://api.themoviedb.org/3/tv/1396",
                                 "https://api.themoviedb.org/3/movie/550"}),
   "הסוג נגזר מ-series_name")

print("─" * 62)
FETCHED.clear()
run([])
after = json.loads(E.CONTENT.read_text(encoding="utf-8"))
eq(len(after), len(CAT_ITEMS), "מספר הפריטים לא השתנה")
eq([i for i in after if i["id"] == 11][0], CAT_ITEMS[4], "שידור חי לא נגע")
eq([i for i in after if i["id"] == 12][0], CAT_ITEMS[5], "פריט בלי מזהה לא נגע")
ep = [i for i in after if i["id"] == 0][0]
eq(ep.get("description"), "תיאור", "תיאור נכתב לכל פרק")
eq(ep.get("year"), "2008", "סדרה לקחה first_air_date")
eq(ep.get("category"), "אימה", "קטגוריה נכתבה")
mv = [i for i in after if i["id"] == 10][0]
eq(mv.get("year"), "1999", "סרט לקח release_date")
eq(mv.get("en_title"), "Fight Club", "לסרט title ולא name")
eq(ep.get("en_title"), "Breaking Bad", "לסדרה name")
eq(E.BACKUP.exists(), True, "גיבוי נוצר")
eq(E.VERSION.read_text().strip(), "1", "גרסת תוכן עלתה")
eq(json.loads(E.BACKUP.read_text(encoding="utf-8")), CAT_ITEMS,
   "הגיבוי הוא המצב שלפני")

print("─" * 62)
# הרצה שנייה: הכול כבר מלא, אין מה לעשות
FETCHED.clear()
run([])
eq(json.loads(E.CONTENT.read_text(encoding="utf-8")), after,
   "הרצה שנייה לא משנה כלום (אידמפוטנטי)")

# הסיכום לפי שדה: Counter.update על מילון מחבר ערכים, ועל מחרוזות
# משרשר אותן. הבאג הזה הדפיס "תיאורתיאורתיאור" במקום 4.
cnt = Counter()
cnt.update({"description": "תיאור"}.keys())
cnt.update({"description": "תיאור"}.keys())
eq(dict(cnt), {"description": 2}, "סיכום לפי שדה סופר ולא משרשר")

print("─" * 62)
run(["--revert"])
eq(json.loads(E.CONTENT.read_text(encoding="utf-8")), CAT_ITEMS,
   "revert מחזיר בית-בית למצב המקורי")

# ── כותר "אנגלי" בעברית: לא נכתב, ומדווח ───────────────────────────────────
# נמדד בדגימה אמיתית: "לבד בבית" קיבל en_title="לבד בבית". זה קורה כי
# language=en-US מחזיר את הכותר הראשי כשאין תרגום, ורשומה שנוצרה
# בעברית מחזירה עברית. זו גם טביעת האצבע של רשומת זבל.
eq(E._has_hebrew("לבד בבית"), True, "מזהה עברית")
eq(E._has_hebrew("Home Alone"), False, "אנגלית אינה עברית")
eq(E._has_hebrew(""), False, "ריק")
eq(E._has_hebrew(None), False, "None")
eq(E._has_hebrew("Home Alone (לבד בבית)"), True, "עברית מעורבת נתפסת")

E.JUNK_EN.clear()
new = E.plan_item({"tmdb_id": 230326, "series_name": "לבד בבית"},
                  {"kind": "tv", "he": {}, "en": {"name": "לבד בבית",
                                                  "first_air_date": "2021-11-12"}},
                  force=False)
eq("en_title" in new, False, "en_title עברי לא נכתב")
eq(new.get("year"), "2021", "אבל שאר השדות כן נכתבים")
eq(len(E.JUNK_EN), 1, "והמזהה נרשם")
# הסוג חייב להגיע מהתשובה ולא להיות מקודד: "לבד בבית" הוא tv/230326,
# סדרת ילדים ישראלית לגיטימית. קישור ל-/movie/230326 מוביל לסרט צרפתי
# מ-1995 ("Le Nouveau Monde") — כלומר גרסה קודמת של הדיווח הפנתה לדף
# הלא-נכון והסיקה ממנו שההתאמה שגויה, כשהיא נכונה.
eq(E.JUNK_EN[0][0], "tv", "הסוג מגיע מהתשובה של fetch")
eq(E.JUNK_EN[0][1], 230326, "המזהה")
eq(E.JUNK_EN[0][3], "לבד בבית", "ושם הפריט אצלנו, כדי שיהיה מה להשוות")

# בלי "kind" בתשובה — ברירת מחדל ולא קריסה
E.JUNK_EN.clear()
E.plan_item({"tmdb_id": 1}, {"he": {}, "en": {"title": "עברית"}}, force=False)
eq(E.JUNK_EN[0][0], "movie", "בלי kind — ברירת מחדל movie")

E.JUNK_EN.clear()
new = E.plan_item({}, {"he": {}, "en": {"title": "Home Alone"}}, force=False)
eq(new.get("en_title"), "Home Alone", "en_title אנגלי כן נכתב")
eq(E.JUNK_EN, [], "ולא נרשם")

# ותיאור בעברית כן רצוי — הכלל חל על en_title בלבד
E.JUNK_EN.clear()
new = E.plan_item({}, {"he": {"overview": "תיאור בעברית"}, "en": {}},
                  force=False)
eq(new.get("description"), "תיאור בעברית", "תיאור עברי הוא בדיוק מה שרוצים")
eq(E.JUNK_EN, [], "ותיאור עברי אינו חריגה")

# ── --force-fields: לדרוס שדה אחד ולא הכול ─────────────────────────────────
# למה זה נדרש: 1,720 פריטים בקטלוג עם שנה שגויה, כי ברירת המחדל בפאנל
# הניהול הייתה new Date().getFullYear(). את השנה צריך לתקן, ותיאורים
# שנכתבו ביד אסור לדרוס — ו---force לבדו דורס את שניהם.
D2 = {"he": {}, "en": {"name": "Right Name", "first_air_date": "1999-10-20",
                       "overview": "TMDB text"}}
cur = {"year": "2026", "en_title": "Old", "description": "התיאור שלנו"}

eq(E.plan_item(dict(cur), D2, force=False), {}, "בלי force — כלום לא נדרס")
eq(E.plan_item(dict(cur), D2, force={"year"}), {"year": "1999"},
   "force על year דורס אותו בלבד")
eq(sorted(E.plan_item(dict(cur), D2, force={"year", "en_title"})),
   ["en_title", "year"], "שני שדות")
eq(E.plan_item(dict(cur), D2, force=True),
   {"year": "1999", "en_title": "Right Name", "description": "TMDB text"},
   "force=True דורס הכול, כולל תיאור")
eq("description" in E.plan_item(dict(cur), D2, force={"year"}), False,
   "force על year לא נוגע בתיאור — זה כל העניין")
eq(E.plan_item(dict(cur), D2, force=set()), {},
   "קבוצה ריקה מתנהגת כמו בלי force")

# ושדה שנדרס אינו מדווח כסתירה — אחרת אותו פריט היה מופיע בשני הדוחות
cl = []
E.plan_item(dict(cur), D2, force={"year"}, conflicts=cl)
eq([f for f, _, _, _ in cl], ["en_title"],
   "year נדרס ולכן אינו סתירה; en_title לא נדרס ולכן כן")

# ── --sample מול --limit: דגימה מייצגת ──────────────────────────────────────
# --limit לוקח את הראשונים בסדר הקטלוג, ולכן על קטלוג שהתחלתו מתוחזקת
# הוא מראה "אין מה למלא" בעוד שהשאר ריק. נמדד בפועל: --limit 40 החזיר
# en_title ל-254 פריטים ו-description לאחד.
BIG = ([{"id": i, "title": f"ישן {i}", "tmdb_id": 100 + i,
         "description": "כבר יש", "year": "2000", "en_title": "Old"}
        for i in range(30)]
       + [{"id": 200 + i, "title": f"חדש {i}", "tmdb_id": 300 + i}
          for i in range(30)])
E.CONTENT.write_text(json.dumps(BIG, ensure_ascii=False), encoding="utf-8")
E.BACKUP.unlink(missing_ok=True)


def names_touched(argv):
    """אילו פריטים באמת נכנסו לעיבוד, לפי מה שנשלף מ-TMDB."""
    FETCHED.clear()
    run(argv)
    return {u.rsplit("/", 1)[-1] for u in FETCHED}


ids = names_touched(["--check", "--limit", "10"])
eq(ids <= {str(100 + i) for i in range(30)}, True,
   "--limit 10 נוגע רק בעשרת הראשונים (הישנים)")
eq(len(ids), 10, "--limit 10 = 10 יחידות")

ids = names_touched(["--check", "--sample", "20"])
new_ids = {str(300 + i) for i in range(30)}
eq(len(ids), 20, "--sample 20 = 20 יחידות")
assert ids & new_ids, "דגימה אקראית חייבת להגיע גם לחדשים"
assert not ids <= new_ids, "ולא רק לחדשים"

# ואותו זרע מחזיר אותה דגימה
eq(names_touched(["--check", "--sample", "20", "--seed", "3"]),
   names_touched(["--check", "--sample", "20", "--seed", "3"]),
   "אותו זרע = אותה דגימה")
assert (names_touched(["--check", "--sample", "20", "--seed", "3"])
        != names_touched(["--check", "--sample", "20", "--seed", "4"])), \
    "זרע אחר = דגימה אחרת"

# --sample גובר על --limit ולא מצטבר איתו
eq(len(names_touched(["--check", "--sample", "15", "--limit", "5"])), 15,
   "--sample גובר על --limit")

print("\n" + "=" * 62)
shutil.rmtree(SP, ignore_errors=True)
if fails:
    print(f"✗ {len(fails)} נכשלו:")
    for f in fails:
        print("   " + f)
    sys.exit(1)
print("✓ כל הבדיקות עברו")
