#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בדיקות ל-fix_categories, בלי רשת ובלי לגעת בקטלוג האמיתי.

הכלי הזה דורס את שדה הקטגוריה של אלפי פריטים, וסדר הכללים בו הוא כל
ההחלטה. לכן כל כלל נבדק בנפרד, וגם כל התנגשות בין שניים — מה גובר על
מה כשפריט הוא גם יפני וגם אנימציה, גם ישראלי וגם אימה, וכן הלאה.
"""
import importlib.util, json, os, sys, tempfile
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
SP = tempfile.mkdtemp(prefix="zovex_cats_")
os.environ["ZOVEX_DATA"] = SP
os.environ["TMDB_API_KEY"] = "FAKE"

spec = importlib.util.spec_from_file_location("F", os.path.join(HERE, "fix_categories.py"))
F = importlib.util.module_from_spec(spec); spec.loader.exec_module(F)

fails = []


def eq(got, want, label):
    if got != want:
        fails.append(f"{label}: קיבלתי {got!r} ציפיתי {want!r}")


def tm(lang=None, country=None, genres=(), companies=(), name="X"):
    """תשובת TMDB מינימלית, בצורה שהשרת האמיתי מחזיר."""
    x = {"name": name, "genres": [{"id": g} for g in genres]}
    if lang:
        x["original_language"] = lang
    if country:
        x["origin_country"] = [country]
    if companies:
        x["production_companies"] = [
            ({"id": c} if isinstance(c, int) else {"name": c}) for c in companies]
    return {"he": {}, "en": x, "kind": "tv"}


ANIM, HORROR, FAMILY, KIDS = 16, 27, 10751, 10762

# ── כל כלל בנפרד ─────────────────────────────────────────────────────────────
eq(F.decide(True, tm("he"))[0], "סדרות ישראליות", "עברית → סדרות ישראליות")
eq(F.decide(False, tm("he"))[0], "סרטים ישראלים", "עברית + סרט")
eq(F.decide(True, tm("en", country="IL"))[0], "סדרות ישראליות",
   "origin_country=IL גם בלי שפה עברית")
eq(F.decide(True, tm("tr"))[0], "סדרות טורקיות", "טורקית → סדרות טורקיות")
eq(F.decide(True, tm("en", country="TR"))[0], "סדרות טורקיות", "origin_country=TR")
eq(F.decide(True, tm("ja", genres=[ANIM]))[0], "אנימה", "יפנית + אנימציה")
eq(F.decide(True, tm("en", genres=[HORROR]))[0], "אימה", "אימה")
eq(F.decide(True, tm("en", genres=[ANIM]))[0], "סדרות לילדים",
   "אנימציה לא יפנית → ילדים")
eq(F.decide(False, tm("en", genres=[ANIM]))[0],
   "סרטים לילדים (מתאים גם למשפחה)", "אנימציה + סרט")
eq(F.decide(True, tm("en", genres=[KIDS]))[0], "סדרות לילדים", "ז'אנר Kids")
eq(F.decide(True, tm("en", genres=[FAMILY]))[0], "סדרות לילדים", "ז'אנר Family")
eq(F.decide(True, tm("en"))[0], "סדרות", "ברירת מחדל סדרה")
eq(F.decide(False, tm("en"))[0], "סרטים", "ברירת מחדל סרט")
eq(F.decide(False, tm("en", companies=[420]))[0], "מארוול", "Marvel Studios לפי id")
eq(F.decide(False, tm("en", companies=["Marvel Animation"]))[0], "מארוול",
   "Marvel לפי שם")
eq(F.decide(False, tm("en", companies=["Warner Bros."]))[0], "סרטים",
   "מפיק אחר אינו מארוול")

# ── התנגשויות: מה גובר על מה ─────────────────────────────────────────────────
eq(F.decide(False, tm("en", genres=[ANIM], companies=[420]))[0], "מארוול",
   "מארוול גוברת על אנימציה")
eq(F.decide(True, tm("he", genres=[HORROR]))[0], "סדרות ישראליות",
   "מקור ישראלי גובר על אימה — כך הקטלוג בנוי בפועל")
eq(F.decide(True, tm("he", genres=[ANIM]))[0], "סדרות ישראליות",
   "מקור ישראלי גובר על אנימציה")
eq(F.decide(True, tm("ja", genres=[ANIM, HORROR]))[0], "אנימה",
   "אנימה גוברת על אימה")
eq(F.decide(True, tm("en", genres=[HORROR, ANIM]))[0], "אימה",
   "אימה גוברת על אנימציה")
eq(F.decide(True, tm("ja", companies=[420], genres=[ANIM]))[0], "מארוול",
   "מארוול גוברת גם על אנימה")

# ── מקרי קצה שחייבים לא ליפול לקטגוריה שגויה ─────────────────────────────────
eq(F.decide(True, tm("ja"))[0], "סדרות",
   "יפנית בלי אנימציה אינה אנימה — יש דרמות יפניות")
eq(F.decide(False, tm("tr"))[0], "סרטים",
   "סרט טורקי נשאר בסרטים: אין 'סרטים טורקיים' בקטלוג")
eq(F.decide(True, {"he": {}, "en": {}})[0], None, "בלי נתונים — לא נוגעים")
eq(F.decide(True, {})[0], None, "תשובה ריקה לגמרי — לא נוגעים")
eq(F.decide(True, {"he": {"original_language": "he"}, "en": {}})[0],
   "סדרות ישראליות", "נתונים בצד העברי בלבד")

# כל קטגוריה שהכלי יכול להחזיר חייבת להיות אחת מהקיימות בקטלוג
seen = set()
for is_ser in (True, False):
    for d in (tm("he"), tm("tr"), tm("ja", genres=[ANIM]), tm("en", genres=[HORROR]),
              tm("en", genres=[ANIM]), tm("en"), tm("en", companies=[420])):
        c, _ = F.decide(is_ser, d)
        if c:
            seen.add(c)
eq(seen - F.KNOWN, set(), "אף כלל לא מייצר קטגוריה שלא קיימת בקטלוג")

# ── הזרימה המלאה ─────────────────────────────────────────────────────────────
CAT = (
    # סדרה ישראלית שיושבת בטעות ב"סדרות"
    [{"id": i, "series_name": "זגורי", "title": f"פרק {i}", "tmdb_id": 11,
      "category": "סדרות"} for i in range(4)]
    # אנימה שיושבת ב"סדרות לילדים"
    + [{"id": 20 + i, "series_name": "נארוטו", "title": f"פרק {i}",
        "tmdb_id": 22, "category": "סדרות לילדים"} for i in range(3)]
    # סרט מארוול בקטגוריה נכונה — לא אמור להיחשב שינוי
    + [{"id": 30, "title": "נוקמים", "tmdb_id": 33, "category": "מארוול"},
       # פריט בלי מזהה — לא נוגעים
       {"id": 40, "title": "בלי מזהה", "category": "סרטים"},
       # שידור חי — לא נוגעים
       {"id": 50, "title": "ערוץ", "tmdb_id": 99, "category": "סדרות",
        "is_live": True}]
)
E = F._load_enrich()
E.CONTENT.write_text(json.dumps(CAT, ensure_ascii=False), encoding="utf-8")

FETCHED = []
TABLE = {
    "11": tm("he", name="Zaguri"),
    "22": tm("ja", genres=[ANIM], name="Naruto"),
    "33": tm("en", companies=[420], name="Avengers"),
    "99": tm("en", name="Channel"),
}


def fake_get(url, timeout=40):
    FETCHED.append(url.split("?")[0])
    tid = url.split("?")[0].rstrip("/").split("/")[-1]
    return (TABLE.get(tid) or {"he": {}, "en": {}})["en"]


E.get = fake_get
F._load_enrich = lambda: E          # אותו מודול, לא טעינה חדשה


def run(argv):
    FETCHED.clear()
    sys.argv = ["fix_categories.py", "--sleep", "0"] + argv
    try:
        F.main()
    except SystemExit as e:
        if e.code:
            raise


print("─" * 62)
run(["--check"])
eq(json.loads(E.CONTENT.read_text(encoding="utf-8")), CAT, "--check לא כתב כלום")
eq(sorted({u.split("/3/")[-1] for u in FETCHED}),
   ["movie/33", "tv/11", "tv/22"],
   "רק פריטים עם מזהה ולא שידור חי; סדרה = בקשה אחת")

print("─" * 62)
run([])
after = json.loads(E.CONTENT.read_text(encoding="utf-8"))
by = {i["id"]: i.get("category") for i in after}
eq(by[0], "סדרות ישראליות", "זגורי עברה לסדרות ישראליות")
eq(by[3], "סדרות ישראליות", "וכל הפרקים שלה")
eq(by[20], "אנימה", "נארוטו עברה לאנימה")
eq(by[30], "מארוול", "מארוול נשארה במקומה")
eq(by[40], "סרטים", "פריט בלי מזהה לא נגע")
eq(by[50], "סדרות", "שידור חי לא נגע")
eq(len(after), len(CAT), "מספר הפריטים לא השתנה")
bak = E.CONTENT.with_name("content.json.bak_categories")
eq(bak.exists(), True, "גיבוי נוצר")
eq(json.loads(bak.read_text(encoding="utf-8")), CAT, "הגיבוי הוא המצב שלפני")

print("─" * 62)
run([])         # אידמפוטנטי
eq(json.loads(E.CONTENT.read_text(encoding="utf-8")), after,
   "הרצה שנייה לא משנה כלום")

print("─" * 62)
run(["--revert"])
eq(json.loads(E.CONTENT.read_text(encoding="utf-8")), CAT,
   "revert מחזיר בית-בית")

# --sample לא כותב גם בלי --check, כי דגימה חלקית שנכתבת היא מצב
# חצי-מעובד שאי אפשר להסביר
E.CONTENT.write_text(json.dumps(CAT, ensure_ascii=False), encoding="utf-8")
try:
    sys.argv = ["fix_categories.py", "--sleep", "0", "--sample", "2"]
    F.main()
    fails.append("--sample כתב לקטלוג במקום לסרב")
except SystemExit as e:
    assert "דגימה" in str(e.code), f"נימוק לא צפוי: {e.code}"
eq(json.loads(E.CONTENT.read_text(encoding="utf-8")), CAT, "--sample לא כתב")

print("\n" + "=" * 62)
import shutil as _sh
_sh.rmtree(SP, ignore_errors=True)
if fails:
    print(f"✗ {len(fails)} נכשלו:")
    for f in fails:
        print("   " + f)
    sys.exit(1)
print("✓ כל הבדיקות עברו")
