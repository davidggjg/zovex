#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בדיקות ל-fix_series_consistency, בלי רשת ובלי לגעת בקטלוג האמיתי.

הכלי משלים מזהים ומאחד קטגוריות על סמך שאר הפרקים באותה סדרה. שתי
הסכנות הן להסיק ממה שאין (סדרה בלי שום מזהה) ולהכריע כשאין רוב, ולכן
שתיהן נבדקות במפורש.
"""
import importlib.util, json, os, sys, tempfile
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
SP = tempfile.mkdtemp(prefix="zovex_series_")
os.environ["ZOVEX_DATA"] = SP
os.environ["TMDB_API_KEY"] = "FAKE"

spec = importlib.util.spec_from_file_location(
    "F", os.path.join(HERE, "fix_series_consistency.py"))
F = importlib.util.module_from_spec(spec); spec.loader.exec_module(F)

fails = []


def eq(got, want, label):
    if got != want:
        fails.append(f"{label}: קיבלתי {got!r} ציפיתי {want!r}")


def ep(i, sn, cat=None, tid=None, **kw):
    d = {"id": i, "series_name": sn, "title": f"פרק {i}"}
    if cat is not None:
        d["category"] = cat
    if tid is not None:
        d["tmdb_id"] = tid
    d.update(kw)
    return d


def fields(changes):
    return {(c[0]["id"], c[2]): c[4] for c in changes}


# ── השלמת מזהה ───────────────────────────────────────────────────────────────
ch, clash, tie, st = F.plan([ep(1, "א", tid=100), ep(2, "א"), ep(3, "א")])
eq(fields(ch), {(2, "tmdb_id"): 100, (3, "tmdb_id"): 100},
   "מזהה מפרק אחד מושלם לשאר")
eq(clash, [], "אין סתירה")

ch, *_ = F.plan([ep(1, "א"), ep(2, "א")])
eq(ch, [], "סדרה בלי שום מזהה — אין ממה להסיק")

ch, *_ = F.plan([ep(1, "א", tid=100), ep(2, "א", tid=100)])
eq(ch, [], "כולם כבר עם אותו מזהה")

# tmdb_id=0 אינו מזהה — נמדד שהוא קיים בקטלוג על שני פריטים
ch, *_ = F.plan([ep(1, "א", tid=100), ep(2, "א", tid=0)])
eq(fields(ch), {(2, "tmdb_id"): 100}, "0 נחשב כחסר ומושלם")
ch, clash, *_ = F.plan([ep(1, "א", tid=0), ep(2, "א", tid=0)])
eq(ch, [], "סדרה שכולה 0 — אין ממה להסיק")
eq(clash, [], "ושני אפסים אינם סתירה")

# ── סתירת מזהים: לא נוגעים ───────────────────────────────────────────────────
ch, clash, tie, st = F.plan([ep(1, "א", tid=100), ep(2, "א", tid=200),
                             ep(3, "א")])
eq(ch, [], "סדרה עם שני מזהים שונים — לא נוגעים בכלל")
eq(len(clash), 1, "ומדווחת")
eq(clash[0][0], "א", "בשמה")
eq(clash[0][2], {"100": 1, "200": 1}, "עם המזהים שנמצאו")

# ── איחוד קטגוריה ────────────────────────────────────────────────────────────
ch, clash, tie, st = F.plan([ep(1, "ב", cat="אנימה"), ep(2, "ב", cat="אנימה"),
                             ep(3, "ב", cat="סדרות")])
eq(fields(ch), {(3, "category"): "אנימה"}, "הרוב קובע")
eq(tie, [], "אין תיקו")

ch, clash, tie, st = F.plan([ep(1, "ב", cat="אנימה"), ep(2, "ב", cat="סדרות")])
eq(ch, [], "תיקו 1:1 — לא מכריעים")
eq(len(tie), 1, "ומדווח")
eq(tie[0][2], {"אנימה": 1, "סדרות": 1}, "עם הפילוג")

ch, *_ = F.plan([ep(1, "ב", cat="אנימה"), ep(2, "ב", cat="אנימה")])
eq(ch, [], "כולם כבר באותה קטגוריה")

# קטגוריה ריקה לא נספרת ברוב, אבל כן מתמלאת
ch, *_ = F.plan([ep(1, "ב", cat="אנימה"), ep(2, "ב", cat="אנימה"),
                 ep(3, "ב", cat="")])
eq(fields(ch), {(3, "category"): "אנימה"}, "פרק בלי קטגוריה מקבל את הרוב")

ch, clash, tie, st = F.plan([ep(1, "ב", cat=""), ep(2, "ב", cat="")])
eq(ch, [], "סדרה שכולה בלי קטגוריה — אין ממה להסיק")
eq(tie, [], "ולא תיקו")

# וסדרה עקבית לגמרי אינה נספרת כ"אוחדה"
ch, _, _, st = F.plan([ep(1, "ב", cat="אנימה"), ep(2, "ב", cat="אנימה")])
eq(st.get("סדרות שהקטגוריה אוחדה בהן"), None,
   "סדרה שלא השתנתה לא נספרת")
ch, _, _, st = F.plan([ep(1, "ב", cat="אנימה"), ep(2, "ב", cat="")])
eq(st.get("סדרות שהקטגוריה אוחדה בהן"), 1, "וסדרה שכן — נספרת")

# ── מה שלא סדרה, ומה שלא נוגעים בו ──────────────────────────────────────────
ch, *_ = F.plan([{"id": 1, "title": "סרט", "tmdb_id": 100, "category": "סרטים"},
                 {"id": 2, "title": "סרט אחר", "category": "אנימה"}])
eq(ch, [], "פריטים בודדים אינם סדרה ולא נוגעים בהם")

ch, *_ = F.plan([ep(1, "ג", tid=100, is_live=True), ep(2, "ג")])
eq(ch, [], "שידור חי לא נספר ולא מזהה מושלם ממנו")

ch, *_ = F.plan([ep(1, "  ד  ", tid=100), ep(2, "ד")])
eq(fields(ch), {(2, "tmdb_id"): 100}, "רווחים בשם הסדרה לא מפצלים אותה")

ch, *_ = F.plan([ep(1, "ה", tid=100), ep(2, "ו")])
eq(ch, [], "שמות שונים הם סדרות שונות")

# ── הדגלים ───────────────────────────────────────────────────────────────────
ITEMS = [ep(1, "ז", cat="אנימה", tid=100), ep(2, "ז", cat="אנימה"),
         ep(3, "ז", cat="סדרות")]
ch, *_ = F.plan(ITEMS)
eq(sorted(f for _, _, f, _, _ in ch), ["category", "tmdb_id", "tmdb_id"],
   "כברירת מחדל שני התיקונים")
ch, *_ = F.plan(ITEMS, do_cats=False)
eq({f for _, _, f, _, _ in ch}, {"tmdb_id"}, "--ids-only רק מזהים")
ch, *_ = F.plan(ITEMS, do_ids=False)
eq({f for _, _, f, _, _ in ch}, {"category"}, "--cats-only רק קטגוריות")

# ── הזרימה המלאה: כתיבה, גיבוי, גרסה, revert, אידמפוטנטיות ─────────────────
E = F._load_enrich()
CAT = [ep(1, "סמולוויל", cat="סדרות", tid=1000),
       ep(2, "סמולוויל", cat="סדרות"),
       ep(3, "סמולוויל", cat="אנימה"),
       ep(10, "כפולה", tid=1), ep(11, "כפולה", tid=2),
       {"id": 20, "title": "סרט", "category": "סרטים"}]
E.CONTENT.write_text(json.dumps(CAT, ensure_ascii=False), encoding="utf-8")
BAK = E.CONTENT.with_name("content.json.bak_series")
BAK.unlink(missing_ok=True)


def run(argv):
    sys.argv = ["fix_series_consistency.py"] + argv
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
after = json.loads(E.CONTENT.read_text(encoding="utf-8"))
by = {i["id"]: i for i in after}
eq(by[2].get("tmdb_id"), 1000, "המזהה הושלם")
eq(by[3].get("tmdb_id"), 1000, "לכל הפרקים")
eq(by[3].get("category"), "סדרות", "והקטגוריה אוחדה לרוב")
eq(by[10].get("tmdb_id"), 1, "סדרה עם מזהים סותרים לא נגעה")
eq(by[11].get("tmdb_id"), 2, "בשני הפרקים")
eq(by[20], CAT[5], "פריט בודד לא נגע")
eq(len(after), len(CAT), "מספר הפריטים לא השתנה")
eq(BAK.exists(), True, "גיבוי נוצר")
eq(json.loads(BAK.read_text(encoding="utf-8")), CAT, "הגיבוי הוא המצב שלפני")
eq(E.VERSION.read_text().strip(), "1", "גרסת תוכן עלתה")

print("─" * 62)
run([])
eq(json.loads(E.CONTENT.read_text(encoding="utf-8")), after,
   "הרצה שנייה לא משנה כלום")

print("─" * 62)
run(["--revert"])
eq(json.loads(E.CONTENT.read_text(encoding="utf-8")), CAT,
   "revert מחזיר בית-בית")

print("\n" + "=" * 62)
import shutil as _sh
_sh.rmtree(SP, ignore_errors=True)
if fails:
    print(f"✗ {len(fails)} נכשלו:")
    for f in fails:
        print("   " + f)
    sys.exit(1)
print("✓ כל הבדיקות עברו")
