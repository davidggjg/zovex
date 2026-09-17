#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בדיקות ל-fix_slugs, בלי רשת ובלי לגעת בקטלוג האמיתי.

הכלי הזה כותב **כתובות**, ולכן טעות בו שוברת קישורים לכל המשתמשים.
שלוש הסכנות הן: לשנות סלאג תקין, לתת לשתי יצירות את אותה כתובת,
ולהמציא כתובת כשאין ממה. שלושתן נבדקות במפורש.
"""
import importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SP = tempfile.mkdtemp(prefix="zovex_slugs_")
os.environ["ZOVEX_DATA"] = SP
os.environ["TMDB_API_KEY"] = "FAKE"

spec = importlib.util.spec_from_file_location("F", os.path.join(HERE, "fix_slugs.py"))
F = importlib.util.module_from_spec(spec); spec.loader.exec_module(F)

fails = []


def eq(got, want, label):
    if got != want:
        fails.append(f"{label}: קיבלתי {got!r} ציפיתי {want!r}")


# ── זיהוי תעתיק ──────────────────────────────────────────────────────────────
for s in ("hmchtrt", "htyrvn", "drgvn-bvl", "kvkb-ksf", "hbvrr"):
    eq(F.is_transliteration(s), True, f"{s} הוא תעתיק")

for s in ("dragon-ball-super", "the-rookie", "underground", "safe-haven",
          "boy-meets-girl", "ibiza"):
    eq(F.is_transliteration(s), False, f"{s} אינו תעתיק")

# קצרים מדי — לא מכריעים, כי gt/tv הם קיצורים לגיטימיים
eq(F.is_transliteration("gt"), False, "שתי אותיות לא נחשבות")
eq(F.is_transliteration(""), False, "ריק אינו תעתיק")
eq(F.is_transliteration(None), False, "None אינו תעתיק")

# ── המרה לכתובת ──────────────────────────────────────────────────────────────
eq(F.slugify("The Rookie"), "the-rookie", "רווח → מקף")
eq(F.slugify("Tom Clancy's Jack Ryan"), "tom-clancys-jack-ryan",
   "גרש נמחק ולא הופך למקף")
eq(F.slugify("Spider-Man: No Way Home"), "spider-man-no-way-home", "פיסוק")
eq(F.slugify("  Waiting...  "), "waiting", "רווחים ונקודות בקצוות")
eq(F.slugify("Still Waiting... 2"), "still-waiting-2", "מספר נשמר")
eq(F.slugify("WALL·E"), "wall-e", "תו לא-אסקי")
eq(F.slugify(""), "", "ריק")
eq(F.slugify("שלום"), "", "עברית בלבד לא מניבה כתובת")


def it(i, slug=None, en=None, series=None, title=None, year=None, **kw):
    d = {"id": i, "title": title or f"פריט {i}"}
    if slug is not None: d["custom_slug"] = slug
    if en is not None: d["en_title"] = en
    if series is not None: d["series_name"] = series
    if year is not None: d["year"] = year
    d.update(kw)
    return d


def newslugs(ch):
    return {c[0]["id"]: c[2] for c in ch}


# ── המקרה המרכזי ─────────────────────────────────────────────────────────────
ch, sk, st = F.plan([it(1, "hmchtrt", "Underground")])
eq(newslugs(ch), {1: "underground"}, "תעתיק מוחלף בשם האמיתי")

ch, *_ = F.plan([it(1, "the-rookie", "The Rookie")])
eq(ch, [], "סלאג תקין לא נגע")

ch, *_ = F.plan([it(1, None, "Underground")])
eq(newslugs(ch), {1: "underground"}, "סלאג חסר מתמלא")

ch, sk, st = F.plan([it(1, "hmchtrt")])
eq(ch, [], "בלי en_title לא ממציאים כתובת")
eq(len(sk), 1, "והפריט מדווח כמדולג")

ch, *_ = F.plan([it(1, "dragon-ball-super", "Dragon Ball Super")])
eq(ch, [], "סלאג תקין שכבר תואם — אין שינוי")

# ── סדרה: כתובת אחת לכל הפרקים ───────────────────────────────────────────────
eps = [it(i, "drgvn-bvl", "Dragon Ball Z", series="דרגון בול זד") for i in range(4)]
eps[2]["en_title"] = ""          # פרק בלי שם — לא אמור להפריע
ch, *_ = F.plan(eps)
eq(set(newslugs(ch).values()), {"dragon-ball-z"}, "כל הפרקים מקבלים כתובת אחת")
eq(len(ch), 4, "כולל הפרק שחסר בו en_title")

# רוב ולא ראשון: פרק חריג לא קובע לסדרה שלמה
odd = ([it(0, "hmchtrt", "Wrong Name", series="ס")] +
       [it(i, "hmchtrt", "Right Name", series="ס") for i in range(1, 5)])
ch, *_ = F.plan(odd)
eq(set(newslugs(ch).values()), {"right-name"}, "הרוב קובע את שם הסדרה")

# ── התנגשויות ────────────────────────────────────────────────────────────────
ch, _, st = F.plan([
    it(1, "hmchtrt", "Underground", series="א"),
    it(2, "hbvrr", "Underground", series="ב", year=2019),
])
v = set(newslugs(ch).values())
eq(len(v), 2, "שתי יצירות עם אותו שם אנגלי מקבלות כתובות שונות")
eq("underground" in v, True, "הראשונה מקבלת את הבסיס")
eq("underground-2019" in v, True, "השנייה מופרדת בשנה")

# בלי שנה — מונה
ch, *_ = F.plan([
    it(1, "hmchtrt", "Same", series="א"),
    it(2, "htyrvn", "Same", series="ב"),
])
eq(len(set(newslugs(ch).values())), 2, "בלי שנה מפרידים במונה")

# הכי חשוב: אסור לדרוס כתובת תקינה שקיימת כבר
ch, *_ = F.plan([
    it(1, "underground", "Underground", series="קיים"),      # תקין, לא נוגעים
    it(2, "hmchtrt", "Underground", series="חדש"),           # רוצה אותה כתובת
])
ns = newslugs(ch)
eq(1 in ns, False, "הסלאג התקין לא השתנה")
eq(ns[2] != "underground", True, "והחדש לא דרס אותו")

# ── מה שלא נוגעים בו ─────────────────────────────────────────────────────────
ch, *_ = F.plan([it(1, "hmchtrt", "Underground", is_live=True)])
eq(ch, [], "שידור חי לא נגע")

# אידמפוטנטיות: הרצה שנייה על התוצאה לא משנה כלום
items = [it(1, "hmchtrt", "Underground"), it(2, None, "The Rookie")]
ch, *_ = F.plan(items)
for m, _o, n in ch:
    m["custom_slug"] = n
ch2, *_ = F.plan(items)
eq(ch2, [], "הרצה שנייה לא משנה כלום")

# ── הזרימה המלאה ─────────────────────────────────────────────────────────────
E = F._load_enrich()
CAT = [
    it(1, "hmchtrt", "Underground", series="המחתרת"),
    it(2, "hmchtrt", "Underground", series="המחתרת"),
    it(3, "dragon-ball-super", "Dragon Ball Super", series="דרגון בול סופר"),
    it(4, "htyrvn"),                       # אין en_title — לא נוגעים
]
E.CONTENT.write_text(json.dumps(CAT, ensure_ascii=False), encoding="utf-8")
BAK = E.CONTENT.with_name("content.json.bak_slugs")
BAK.unlink(missing_ok=True)


def run(argv):
    sys.argv = ["fix_slugs.py"] + argv
    try:
        F.main()
    except SystemExit as e:
        if e.code:
            raise


print("─" * 62)
run(["--check"])
eq(json.loads(E.CONTENT.read_text(encoding="utf-8")), CAT, "--check לא כתב")
eq(BAK.exists(), False, "--check לא יצר גיבוי")

print("─" * 62)
run([])
after = {i["id"]: i for i in json.loads(E.CONTENT.read_text(encoding="utf-8"))}
eq(after[1]["custom_slug"], "underground", "הוחל")
eq(after[2]["custom_slug"], "underground", "שני הפרקים זהים")
eq(after[3]["custom_slug"], "dragon-ball-super", "התקין לא נגע")
eq(after[4]["custom_slug"], "htyrvn", "בלי en_title נשאר כמו שהוא")
eq(BAK.exists(), True, "גיבוי נוצר")
eq(E.VERSION.read_text().strip(), "1", "גרסת תוכן עלתה")

print("─" * 62)
run(["--revert"])
eq(json.loads(E.CONTENT.read_text(encoding="utf-8")), CAT, "revert מחזיר בית-בית")

print("\n" + "=" * 62)
import shutil as _sh
_sh.rmtree(SP, ignore_errors=True)
if fails:
    print(f"✗ {len(fails)} נכשלו:")
    for f in fails:
        print("   " + f)
    sys.exit(1)
print("✓ כל הבדיקות עברו")
