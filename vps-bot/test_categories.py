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

# ── הורדת דרגה: ספציפי → גנרי ───────────────────────────────────────────────
# נמדד בהרצה אמיתית: 20 מ-614 השינויים היו ירידה מקטגוריה ספציפית
# לגנרית, כי "ברירת מחדל לפי סוג" הכריעה — הכלל החלש ביותר. כשחסר
# ז'אנר ב-TMDB, בחירה אנושית קודמת עשויה להיות מדויקת יותר.
DEMO = (
    [{"id": 60 + i, "series_name": "ילדים", "title": f"פרק {i}",
      "tmdb_id": 66, "category": "סדרות לילדים"} for i in range(3)]
    + [{"id": 70, "title": "כבר נכון", "tmdb_id": 77, "category": "סרטים"}]
)
TABLE["66"] = tm("en", name="Plain")      # בלי ז'אנר → ברירת מחדל
TABLE["77"] = tm("en", name="Plain2")
E.CONTENT.write_text(json.dumps(DEMO, ensure_ascii=False), encoding="utf-8")
E.CONTENT.with_name("content.json.bak_categories").unlink(missing_ok=True)

run(["--check"])
run([])
by = {i["id"]: i.get("category")
      for i in json.loads(E.CONTENT.read_text(encoding="utf-8"))}
eq(by[60], "סדרות", "בלי --no-demote ההורדה מתבצעת")
eq(by[70], "סרטים", "ומה שכבר גנרי לא משתנה")

E.CONTENT.write_text(json.dumps(DEMO, ensure_ascii=False), encoding="utf-8")
run(["--no-demote"])
by = {i["id"]: i.get("category")
      for i in json.loads(E.CONTENT.read_text(encoding="utf-8"))}
eq(by[60], "סדרות לילדים", "--no-demote משאיר את הקטגוריה הספציפית")
eq(by[62], "סדרות לילדים", "לכל הפרקים")

# --no-demote מונע רק ירידה לגנרי, לא שינוי בין ספציפיים
UP = [{"id": 80, "title": "אנימה יפנית", "tmdb_id": 88, "category": "אימה"}]
TABLE["88"] = tm("ja", genres=[ANIM], name="Anime")
E.CONTENT.write_text(json.dumps(UP, ensure_ascii=False), encoding="utf-8")
run(["--no-demote"])
by = {i["id"]: i.get("category")
      for i in json.loads(E.CONTENT.read_text(encoding="utf-8"))}
eq(by[80], "אנימה", "--no-demote לא חוסם מעבר בין שתי קטגוריות ספציפיות")

# וגם לא חוסם מילוי של קטגוריה ריקה
EMPTY = [{"id": 90, "title": "ריק", "tmdb_id": 77, "category": ""}]
E.CONTENT.write_text(json.dumps(EMPTY, ensure_ascii=False), encoding="utf-8")
run(["--no-demote"])
by = {i["id"]: i.get("category")
      for i in json.loads(E.CONTENT.read_text(encoding="utf-8"))}
eq(by[90], "סרטים", "קטגוריה ריקה מתמלאת גם עם --no-demote")

# ── מארוול לא יורדת לעולם ────────────────────────────────────────────────────
# נמדד בהרצה אמיתית: מורביוס (526896) ומאדאם ווב (634492) הוצאו
# מ"מארוול" ל"סרטים", כי הן הפקות סוני ורשימת המפיקים ב-TMDB לא
# מזכירה מארוול. "מארוול" היא קטגוריה עריכתית שהנתון לא יכול לשחזר.
MV = [{"id": 100, "title": "מורביוס", "tmdb_id": 111, "category": "מארוול"}]
TABLE["111"] = tm("en", companies=["Columbia Pictures"], name="Morbius")
E.CONTENT.write_text(json.dumps(MV, ensure_ascii=False), encoding="utf-8")
E.CONTENT.with_name("content.json.bak_categories").unlink(missing_ok=True)
run([])
by = {i["id"]: i.get("category")
      for i in json.loads(E.CONTENT.read_text(encoding="utf-8"))}
eq(by[100], "מארוול", "מארוול לא יורדת גם בלי --no-demote")

# אבל הכלל החיובי כן מכניס פנימה
IN = [{"id": 101, "title": "נוקמים", "tmdb_id": 112, "category": "סרטים"}]
TABLE["112"] = tm("en", companies=[420], name="Avengers")
E.CONTENT.write_text(json.dumps(IN, ensure_ascii=False), encoding="utf-8")
run([])
by = {i["id"]: i.get("category")
      for i in json.loads(E.CONTENT.read_text(encoding="utf-8"))}
eq(by[101], "מארוול", "והכלל החיובי ממשיך להכניס למארוול")

# ומעבר מ"מארוול" לקטגוריה ספציפית אחרת כן מותר — ההגנה היא רק מהגנרי
SPEC = [{"id": 102, "title": "אנימה", "tmdb_id": 113, "category": "מארוול"}]
TABLE["113"] = tm("ja", genres=[ANIM], name="Anime")
E.CONTENT.write_text(json.dumps(SPEC, ensure_ascii=False), encoding="utf-8")
run([])
by = {i["id"]: i.get("category")
      for i in json.loads(E.CONTENT.read_text(encoding="utf-8"))}
eq(by[102], "אנימה", "ההגנה היא רק מהכלל הגנרי, לא מקטגוריה ספציפית")

# ── קביעות עריכתיות ─────────────────────────────────────────────────────────
OV = os.path.join(SP, "ov.json")
os.environ["ZOVEX_CAT_OVERRIDES"] = OV
import importlib
spec2 = importlib.util.spec_from_file_location(
    "F2", os.path.join(HERE, "fix_categories.py"))
F2 = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(F2)
F2._load_enrich = lambda: E

eq(F2.load_overrides(), ({}, {}), "בלי קובץ — אין קביעות, בלי קריסה")

json.dump({"113": "אימה"}, open(OV, "w"), ensure_ascii=False)
eq(F2.load_overrides(), ({"113": "אימה"}, {}), "קובץ נקרא — מזהה בלבד")

# מפתח לפי שם סדרה נכנס למילון הנפרד
json.dump({"113": "אימה", "series:עספור": "סדרות ישראליות"},
          open(OV, "w"), ensure_ascii=False)
eq(F2.load_overrides(), ({"113": "אימה"}, {"עספור": "סדרות ישראליות"}),
   "מפתח series: נכנס לפי שם סדרה")

json.dump({"113": "קטגוריה שלא קיימת"}, open(OV, "w"), ensure_ascii=False)
try:
    F2.load_overrides()
    fails.append("קביעה לקטגוריה שלא קיימת עברה")
except SystemExit as e:
    assert "לא קיימות" in str(e.code), e.code

# והקביעה גוברת על ההחלטה האוטומטית
json.dump({"113": "אימה"}, open(OV, "w"), ensure_ascii=False)
E.CONTENT.write_text(json.dumps(
    [{"id": 103, "title": "אנימה", "tmdb_id": 113, "category": "סרטים"}],
    ensure_ascii=False), encoding="utf-8")
sys.argv = ["fix_categories.py", "--sleep", "0"]
F2.main()
by = {i["id"]: i.get("category")
      for i in json.loads(E.CONTENT.read_text(encoding="utf-8"))}
eq(by[103], "אימה", "קביעה עריכתית גוברת על 'יפנית + אנימציה'")
del os.environ["ZOVEX_CAT_OVERRIDES"]

# ── קביעה לפי שם סדרה: חלה גם בלי tmdb_id ───────────────────────────────────
# עספור סדרה ישראלית בלי מזהה בקטלוג, ולכן הפס מבוסס-המזהה לא נוגע בה.
# הקביעה לפי שם סדרה כן — וזה כל הטעם.
json.dump({"series:עספור": "סדרות ישראליות"}, open(OV, "w"), ensure_ascii=False)
os.environ["ZOVEX_CAT_OVERRIDES"] = OV
E.CONTENT.write_text(json.dumps([
    {"id": 1, "series_name": "עספור", "title": "e1", "category": "סדרות"},
    {"id": 2, "series_name": "עספור", "title": "e2", "category": "סדרות ישראליות"},
    {"id": 3, "series_name": "עספור", "title": "e3", "category": ""},
    {"id": 9, "series_name": "אחרת", "title": "e", "category": "סדרות"},
], ensure_ascii=False), encoding="utf-8")
E.CONTENT.with_name("content.json.bak_categories").unlink(missing_ok=True)
sys.argv = ["fix_categories.py", "--sleep", "0"]
F2.main()
_by = {i["id"]: i.get("category")
       for i in json.loads(E.CONTENT.read_text(encoding="utf-8"))}
eq(_by[1], "סדרות ישראליות", "פרק גנרי עבר לקביעה לפי שם")
eq(_by[2], "סדרות ישראליות", "פרק שכבר נכון נשאר")
eq(_by[3], "סדרות ישראליות", "פרק ריק מתמלא")
eq(_by[9], "סדרות", "סדרה אחרת לא נגעה")
os.environ.pop("ZOVEX_CAT_OVERRIDES", None)

print("\n" + "=" * 62)
import shutil as _sh
_sh.rmtree(SP, ignore_errors=True)
if fails:
    print(f"✗ {len(fails)} נכשלו:")
    for f in fails:
        print("   " + f)
    sys.exit(1)
print("✓ כל הבדיקות עברו")
