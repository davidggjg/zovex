#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""הדגלים החדשים ב-tmdb_ai_match, בלי רשת ובלי טוקן אחד.

מזייף את שכבת ה-HTTP: חיפושי TMDB מוחזרים מטבלה, וקריאת הצ'אט מחזירה
usage אמיתי־למראה כדי שספירת הטוקנים והתקציב ייבדקו בפועל.
"""
import importlib.util, json, os, sys, tempfile
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
SP = tempfile.mkdtemp(prefix="zovex_test_")
spec = importlib.util.spec_from_file_location("M", os.path.join(HERE, "tmdb_ai_match.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)

fails = []


def eq(got, want, label):
    if got != want:
        fails.append(f"{label}: קיבלתי {got!r} ציפיתי {want!r}")


# ── קטלוג מזויף: 6 סדרות ו-2 סרטים, כולם בלי tmdb_id ────────────────────────
CAT = []
for k in range(6):
    CAT += [{"id": 100 * k + i, "series_name": f"סדרה {k}", "title": f"פרק {i}"}
            for i in range(3)]
CAT += [{"id": 900, "title": "סרט אחד"}, {"id": 901, "title": "סרט שני"}]
CATP = os.path.join(SP, "m_cat.json")
json.dump(CAT, open(CATP, "w"), ensure_ascii=False)

OVERVIEW = "תקציר ארוך בעברית שנמשך והולך ומכיל הרבה מאוד תווים " * 6
SENT = []            # כל גוף בקשה שנשלח ל"מודל"


def fake_http_json(url, headers=None, data=None, timeout=45, retries=6):
    if "/search/multi" in url:
        return {"results": [
            {"id": 1000 + i, "media_type": "tv" if i % 2 == 0 else "movie",
             "name": f"מועמד {i}", "title": f"מועמד {i}",
             "original_name": f"Cand {i}", "first_air_date": "2010-01-01",
             "popularity": 100 - i, "overview": OVERVIEW}
            for i in range(12)]}
    if "/chat/completions" in url:
        body = json.loads(data.decode())
        SENT.append(body)
        user = json.loads(body["messages"][1]["content"])
        pick = (user["candidates"] or [None])[0]
        content = json.dumps({"tmdb_id": pick and pick["tmdb_id"],
                              "media_type": pick and pick["media_type"],
                              "confidence": 1.0, "why": "fake"})
        # usage בגודל שמתאים למה שנשלח בפועל
        pt = len(body["messages"][0]["content"]) // 3 + len(
            body["messages"][1]["content"]) // 2
        return {"choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": pt, "completion_tokens": 52,
                          "total_tokens": pt + 52}}
    raise AssertionError("כתובת לא צפויה: " + url)


M.http_json = fake_http_json
M.load_key = lambda *a, **k: "FAKE"
M.load_catalog = lambda url: json.loads(open(CATP, encoding="utf-8").read())


def run(argv, out):
    SENT.clear()
    M.USAGE.clear(); M.TMDB_FAILS.clear()
    sys.argv = (["tmdb_ai_match.py", "--catalog", CATP, "--sleep", "0",
                 "--out", out] + argv)
    try:
        M.main()
    except SystemExit as e:
        if e.code:
            raise
    return json.load(open(out, encoding="utf-8"))


O = os.path.join(SP, "m_out.json")

# ── 1. ברירות המחדל: 8 מועמדים, overview של 220 ─────────────────────────────
print("═" * 62)
d = run(["--run"], O)
eq(len(SENT), 8, "8 יחידות = 8 קריאות")
eq(len(json.loads(SENT[0]["messages"][1]["content"])["candidates"]), 8,
   "ברירת מחדל: 8 מועמדים")
eq(len(json.loads(SENT[0]["messages"][1]["content"])["candidates"][0]["overview"]),
   220, "ברירת מחדל: overview 220 תווים")
base_tok = M.USAGE["total"]
assert base_tok > 0, "usage לא נספר"

# ── 2. הברז: 5 מועמדים בלי overview ─────────────────────────────────────────
print("═" * 62)
d = run(["--run", "--max-cands", "5", "--overview", "0"], O)
c0 = json.loads(SENT[0]["messages"][1]["content"])["candidates"]
eq(len(c0), 5, "max-cands 5")
eq(any("overview" in c for c in c0), False, "overview 0 = מוסר לגמרי")
slim_tok = M.USAGE["total"]
assert slim_tok < base_tok / 2, f"הברז לא חסך: {base_tok} → {slim_tok}"
print(f"\n→ חיסכון נמדד: {base_tok:,} → {slim_tok:,} טוקנים "
      f"({100 - 100*slim_tok//base_tok}% פחות)")

# ── 3. overview חתוך ל-80 ───────────────────────────────────────────────────
d = run(["--run", "--overview", "80"], O)
eq(len(json.loads(SENT[0]["messages"][1]["content"])["candidates"][0]["overview"]),
   80, "overview נחתך ל-80")

# ── 4. --skip ───────────────────────────────────────────────────────────────
print("═" * 62)
d = run(["--run", "--skip", "6"], O)
eq(len(SENT), 2, "skip 6 מתוך 8 משאיר 2")
names = [r["name"] for r in d["accepted"] + d["review"]]
eq(sorted(names), ["סרט אחד", "סרט שני"], "דילג על הסדרות והגיע לסרטים")

# ── 5. --skip עם --limit ────────────────────────────────────────────────────
d = run(["--run", "--skip", "2", "--limit", "3"], O)
eq(len(SENT), 3, "skip אז limit")
eq(sorted(r["name"] for r in d["accepted"] + d["review"]),
   ["סדרה 2", "סדרה 3", "סדרה 4"], "החלון הנכון")

# ── 6. --token-budget עוצר בשלום ושומר ──────────────────────────────────────
print("═" * 62)
per = base_tok // 8
d = run(["--run", "--token-budget", str(per * 3)], O)
n = len(d["accepted"]) + len(d["review"])
assert 2 <= n <= 4, f"התקציב עצר אחרי {n} יחידות, ציפיתי ~3"
assert os.path.exists(O), "הפלט נשמר גם כשנעצר על תקציב"
print(f"\n→ תקציב {per*3:,} עצר אחרי {n} יחידות ושמר אותן")

# ── 7. --kind-filter ────────────────────────────────────────────────────────
print("═" * 62)
d = run(["--run", "--kind-filter", "--limit", "1"], O)
c0 = json.loads(SENT[0]["messages"][1]["content"])["candidates"]
eq(any(c["media_type"] == "movie" for c in c0), False,
   "סדרה לא רואה מועמדי movie")
assert c0, "אבל כן נשארו מועמדי tv"
d = run(["--run", "--kind-filter", "--skip", "6", "--limit", "1"], O)
c0 = json.loads(SENT[0]["messages"][1]["content"])["candidates"]
eq(any(c["media_type"] == "movie" for c in c0), True,
   "פריט בודד כן רואה movie")

# ── 8. max_tokens תמיד נשלח ─────────────────────────────────────────────────
eq(SENT[0]["max_tokens"], M._MAX_OUT, "max_tokens נשלח")
eq(SENT[0]["temperature"], 0, "temperature 0")

print("\n" + "=" * 62)
if fails:
    print(f"✗ {len(fails)} נכשלו:")
    for f in fails:
        print("   " + f)
    sys.exit(1)
print("✓ כל הבדיקות עברו")
