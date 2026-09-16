#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""בדיקות ל-tmdb_exact_probe: הכלל הדטרמיניסטי והזרימה המלאה, בלי רשת."""
import importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("P", os.path.join(HERE, "tmdb_exact_probe.py"))
P = importlib.util.module_from_spec(spec); spec.loader.exec_module(P)

SP = tempfile.mkdtemp(prefix="zovex_test_")
fails = []


def eq(got, want, label):
    if got != want:
        fails.append(f"{label}: קיבלתי {got!r} ציפיתי {want!r}")


# ── norm ─────────────────────────────────────────────────────────────────────
eq(P.norm("שובר-שורות!"), "שובר שורות", "מקף וסימן קריאה")
eq(P.norm("  שובר   שורות  "), "שובר שורות", "רווחים כפולים")
eq(P.norm("The Batman"), "batman", "תווית the")
eq(P.norm("A Quiet Place"), "quiet place", "תווית a")
eq(P.norm("Breaking Bad"), "breaking bad", "אנגלית פשוטה")
eq(P.norm(None), "", "None")
eq(P.norm("!!!"), "", "סימנים בלבד")
eq(P.norm("300"), "300", "מספרים נשמרים")
eq(P.norm("סְמוֹלְוִיל"), P.norm("סמולויל"), "ניקוד מוסר")
# "האביר האפל" מול "אביר האפל" — ה' הידיעה בעברית *לא* מוסרת, בכוונה:
# היא חלק מהשם ומבדילה בין כותרים.
assert P.norm("האביר האפל") != P.norm("אביר האפל"), "ה' הידיעה לא אמורה ליפול"

# ── kind_ok ──────────────────────────────────────────────────────────────────
eq(P.kind_ok("series", "movie"), False, "סדרה פוסלת movie")
eq(P.kind_ok("series", "tv"), True, "סדרה מקבלת tv")
eq(P.kind_ok("item", "movie"), True, "פריט מקבל movie")
eq(P.kind_ok("item", "tv"), True, "פריט מקבל גם tv")


# ── exact_pick ───────────────────────────────────────────────────────────────
def c(tid, title, orig="", year="", mt="tv", pop=1.0, ov="x"):
    return {"tmdb_id": tid, "media_type": mt, "title": title,
            "original_title": orig, "year": year, "popularity": pop,
            "overview": ov}


p, why = P.exact_pick("שובר שורות", "", [c(1, "שובר שורות"), c(2, "משהו אחר")])
eq(p and p["tmdb_id"], 1, "התאמה יחידה")
eq(why, "שם מדויק יחיד", "נימוק התאמה יחידה")

p, why = P.exact_pick("Breaking Bad", "", [c(1, "שובר שורות", "Breaking Bad")])
eq(p and p["tmdb_id"], 1, "התאמה על original_title")

p, why = P.exact_pick("משהו", "", [c(1, "אחר"), c(2, "שלישי")])
eq(p, None, "אין התאמה")
eq(why, "אין התאמת שם מדויקת", "נימוק אין התאמה")

p, why = P.exact_pick("אלאדין", "", [c(1, "אלאדין", year="1992"),
                                     c(2, "אלאדין", year="2019")])
eq(p, None, "שתי התאמות בלי שנה — מעורפל")
assert "מעורפל" in why, why

p, why = P.exact_pick("אלאדין", "2019", [c(1, "אלאדין", year="1992"),
                                         c(2, "אלאדין", year="2019")])
eq(p and p["tmdb_id"], 2, "שנה מכריעה בין שתי התאמות")

p, why = P.exact_pick("אלאדין", "2018", [c(1, "אלאדין", year="1992"),
                                         c(2, "אלאדין", year="2019")])
eq(p and p["tmdb_id"], 2, "שנה בסטייה של 1 עוד נחשבת")

p, why = P.exact_pick("אלאדין", "2005", [c(1, "אלאדין", year="1992"),
                                         c(2, "אלאדין", year="2019")])
eq(p, None, "שנה שלא מתאימה לאף אחד — נשאר מעורפל")

p, why = P.exact_pick("", "", [c(1, "משהו")])
eq(p, None, "שאילתה ריקה")
eq(P.exact_pick("x", "", [])[0], None, "בלי מועמדים")
p, why = P.exact_pick("אלאדין", "199a", [c(1, "אלאדין", year="ab"),
                                         c(2, "אלאדין", year="")])
eq(p, None, "שנה לא מספרית לא מפילה את הריצה")

# ── est_tokens ───────────────────────────────────────────────────────────────
assert P.est_tokens("abcd") == 1, P.est_tokens("abcd")
assert P.est_tokens("שלום לך") > P.est_tokens("hello!"), "עברית יקרה יותר לתו"
eq(P.est_tokens(""), 0, "מחרוזת ריקה")

# ── הזרימה המלאה, עם matcher מזויף ואפס רשת ─────────────────────────────────
CAT = [
    # סדרה שתיפתר לבד
    *[{"id": 100 + i, "series_name": "סמולוויל", "title": f"פרק {i}",
       "tmdb_id": 1000} for i in range(3)],
    # סדרה שלא תיפתר (שני כותרים זהים)
    *[{"id": 200 + i, "series_name": "אלאדין", "title": f"פרק {i}",
       "tmdb_id": 2000} for i in range(2)],
    # סרט שייפתר
    {"id": 300, "title": "הצלף", "tmdb_id": 3000},
    # סרט בלי tmdb_id — יופיע רק ב---run
    {"id": 400, "title": "סרט חסר"},
    # סדרה שמועמדיה כוללים סרט באותו שם בדיוק — סינון הסוג הוא מה
    # שהופך אותה מ"מעורפל" ל"חד-משמעי"
    *[{"id": 600 + i, "series_name": "הרשימה השחורה", "title": f"פרק {i}",
       "tmdb_id": 6000} for i in range(4)],
    # שידור חי — אמור להיעלם לגמרי
    {"id": 500, "title": "ערוץ 12", "is_live": True},
]
CATP = SP + "/cat.json"
json.dump(CAT, open(CATP, "w"), ensure_ascii=False)

FAKE = {
    "סמולוויל": [c(1000, "סמולוויל", "Smallville", "2001"),
                 c(9, "משהו אחר", "", "2010")],
    "אלאדין":   [c(2001, "אלאדין", "Aladdin", "1992", mt="tv"),
                 c(2002, "אלאדין", "Aladdin", "2019", mt="tv")],
    "הצלף":     [c(3000, "הצלף", "American Sniper", "2014", mt="movie"),
                 c(77, "הצלף", "Sniper", "1993", mt="movie")],
    "סרט חסר":  [c(4000, "סרט חסר", "Missing", "2020", mt="movie")],
    "הרשימה השחורה": [c(6000, "הרשימה השחורה", "The Blacklist", "2013", mt="tv"),
                      c(6001, "הרשימה השחורה", "The Blacklist", "2013",
                        mt="movie")],
}

real_loader = P._load_matcher


def fake_loader():
    m = real_loader()
    m.load_key = lambda *a, **k: "FAKE"
    m.load_catalog = lambda url: json.loads(open(CATP, encoding="utf-8").read())
    m.tmdb_candidates = lambda key, qs, limit=8: list(FAKE.get(qs[0], []))[:limit]
    return m


P._load_matcher = fake_loader
OUT = SP + "/probe_out.json"


def run(argv):
    sys.argv = ["tmdb_exact_probe.py", "--catalog", CATP] + argv
    P.main()


print("─" * 62)
run(["--validate", "--out", OUT])
print("─" * 62)
ROUT = SP + "/probe_run.json"
run(["--run", "--out", ROUT])
print("─" * 62)

got = json.load(open(OUT, encoding="utf-8"))
eq(sorted(r["name"] for r in got["accepted"]), ["הרשימה השחורה", "סמולוויל"],
   "רק החד-משמעית נפתרה — 'הצלף' מעורפל ו'אלאדין' מעורפל")
eq([r["tmdb_id"] for r in got["accepted"] if r["name"] == "סמולוויל"], [1000],
   "סמולוויל קיבלה את המזהה הנכון")
eq(all(r["correct"] for r in got["accepted"]), True, "מה שנפתר — נכון")
eq({r["name"]: r["n"] for r in got["accepted"]},
   {"סמולוויל": 3, "הרשימה השחורה": 4}, "מספר הפרקים נשמר")
eq([r["tmdb_id"] for r in got["accepted"] if r["name"] == "הרשימה השחורה"],
   [6000], "סינון הסוג פסל את הסרט והשאיר מועמד אחד")
assert set(got["accepted"][0]) >= {"name", "kind", "n", "tmdb_id",
                                   "media_type", "confidence", "why"}, \
    "הפורמט חייב להתאים למה ש-tmdb_map_filter קורא"

# והפלט חייב לעבור דרך tmdb_map_filter בלי שינוי
fspec = importlib.util.spec_from_file_location(
    "F", os.path.join(HERE, "tmdb_map_filter.py"))
F = importlib.util.module_from_spec(fspec); fspec.loader.exec_module(F)
FOUT = SP + "/probe_filtered.json"
# פלט של --validate חייב להיחסם: היחידות בו כבר מזוהות
sys.argv = ["tmdb_map_filter.py", "--src", OUT, "--min", "0.99", "--out", FOUT]
try:
    F.main()
    fails.append("הפילטר קיבל קובץ אימות במקום לסרב")
except SystemExit as e:
    assert "validate" in str(e.code), f"נימוק לא צפוי: {e.code}"

# ופלט של --run עובר
sys.argv = ["tmdb_map_filter.py", "--src", ROUT, "--min", "0.99", "--out", FOUT]
F.main()
mp = json.load(open(FOUT, encoding="utf-8"))
eq(sorted(mp), ["400"], "מפתח פריט בודד = ה-id שלו")
eq(mp["400"]["kind"], "movie", "פריט = movie")
eq(mp["400"]["tmdb_id"], 4000, "המזהה נכון")
eq(mp["400"]["confidence"], "ודאי", "1.0 → ודאי")

print("\n" + "=" * 62)
if fails:
    print(f"✗ {len(fails)} נכשלו:")
    for f in fails:
        print("   " + f)
    sys.exit(1)
print("✓ כל הבדיקות עברו")
