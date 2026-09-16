#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tmdb_exact_probe — כמה מהקטלוג אפשר להתאים בלי לשאול מודל בכלל.

למה זה נכתב: הסריקה המלאה נתקעה על 429 של Groq עם Retry-After של 679
שניות, כלומר ~11 דקות ליחידה. זה לא באג ולא המפתח — זה מכסת הטוקנים
ליום, שנגמרה. החשבון שמסביר את 679 השניות:

    TPD 500,000 → קצב מילוי 5.79 טוקנים/שנייה
    679s × 5.79 = ~3,900 טוקנים שהבקשה ביקשה ולא היו

ומדידת גודל הבקשה בקוד הקיים מאשרת את הסדר גודל:

    system                    704 תווים  ≈  176 טוקנים
    user (8 מועמדים + overview) 2,206 תווים  ≈ 1,471 טוקנים
    max_tokens שנשמר מראש                      200
    ────────────────────────────────────────────────
    סה"כ                                     ≈ 1,850

935 יחידות × 1,850 = 1.73 מיליון טוקנים. מול מכסה של חצי מיליון ליום,
זה שלושה ימים וחצי של המתנות — בדיוק מה שנמדד.

לכן שתי שאלות, ושתיהן נמדדות כאן **בלי טוקן אחד של מודל**:

  1. כמה יחידות נפתרות בכלל בלי מודל — התאמת שם מדויקת בין השם שלנו
     לכותר של TMDB, אחרי נרמול. אם שם אחד ויחיד מתאים, אין מה לשאול.
  2. כמה מועמדים נחסכים מסינון לפי סוג: יחידה שהיא סדרה אצלנו לא
     צריכה לראות מועמדים מסוג movie. פחות מועמדים = פחות טוקנים.

ועל 234 היחידות שיש להן כבר tmdb_id, הדיוק של הכלל הדטרמיניסטי נמדד
מול התשובה הידועה. חיפושי TMDB חינמיים ולוקחים 0.2 שניות, ולכן כל
המדידה הזאת לא נוגעת במכסה.

    python3 tmdb_exact_probe.py --validate            # דיוק מול האמת
    python3 tmdb_exact_probe.py --run                 # כיסוי על מה שחסר
    python3 tmdb_exact_probe.py --validate --limit 60 # טעימה מהירה
"""
import argparse, importlib.util, json, os, re, sys, time, unicodedata
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load_matcher():
    """מייבא את tmdb_ai_match כדי לא לשכפל clean/units/tmdb_candidates.

    הייבוא מפעיל גם את תיקון ה-IPv6 שבראש הקובץ, וזה בכוונה: בלעדיו
    כל חיפוש TMDB מכאן היה נתקע 24 שניות בדיוק כמו שם.
    """
    p = os.path.join(_HERE, "tmdb_ai_match.py")
    if not os.path.exists(p):
        sys.exit(f"לא נמצא {p} — הכלי הזה מייבא ממנו.")
    spec = importlib.util.spec_from_file_location("_tmdb_ai_match", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# הכלל עצמו יושב ב-tmdb_names, כדי ש-tmdb_ai_match ישתמש באותו קוד
# בדיוק ולא בעותק שלו. מה שנמדד כאן הוא מה שירוץ שם.
_np = os.path.join(_HERE, "tmdb_names.py")
if not os.path.exists(_np):
    raise SystemExit(f"לא נמצא {_np}")
_nspec = importlib.util.spec_from_file_location("tmdb_names", _np)
_N = importlib.util.module_from_spec(_nspec)
_nspec.loader.exec_module(_N)
norm, kind_ok, exact_pick = _N.norm, _N.kind_ok, _N.exact_pick
est_tokens, payload_variants = _N.est_tokens, _N.payload_variants


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="http://127.0.0.1:8000/content/lite")
    ap.add_argument("--validate", action="store_true",
                    help="על מה שיש לו tmdb_id — ומודד דיוק מול האמת")
    ap.add_argument("--run", action="store_true",
                    help="על מה שחסר — ומודד כיסוי")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-cands", type=int, default=8)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if not (a.validate or a.run):
        ap.error("צריך --validate או --run")

    m = _load_matcher()
    tkey = m.load_key("TMDB_API_KEY")
    if not tkey:
        sys.exit("אין TMDB_API_KEY ב-/opt/zovex-bot/.env")

    items = m.load_catalog(a.catalog)
    rows = m.units(items, want_known=a.validate)
    if a.limit:
        rows = rows[:a.limit]
    print(f"{'אימות מול האמת' if a.validate else 'כיסוי על מה שחסר'} · "
          f"{len(rows)} יחידות · אפס קריאות למודל\n")

    solved, unsolved, wrong = [], [], []
    why = Counter()
    cand_before = cand_after = 0
    tok = Counter()
    t0 = time.time()

    for n, u in enumerate(rows, 1):
        q, yr = m.clean(u["name"])
        qs = [q, u["name"]] if q != u["name"] else [q]
        cands = m.tmdb_candidates(tkey, qs, limit=a.max_cands)
        cand_before += len(cands)
        cands = [c for c in cands if kind_ok(u["kind"], c["media_type"])]
        cand_after += len(cands)

        pick, reason = exact_pick(q, yr, cands)
        why[reason] += 1
        if pick:
            rec = {"name": u["name"], "kind": u["kind"], "n": u.get("n", 1),
                   "id": u.get("id"), "query": q, "tmdb_id": pick["tmdb_id"],
                   "media_type": pick["media_type"], "confidence": 1.0,
                   "why": "התאמת שם מדויקת ללא מודל"}
            if a.validate and u["known"]:
                ok = str(pick["tmdb_id"]) == str(u["known"])
                rec["correct"] = ok
                if not ok:
                    wrong.append((u, pick))
            solved.append(rec)
        else:
            unsolved.append(u)
            for k, v in payload_variants(m, u["name"], yr, cands).items():
                tok[k] += v

        print(f"\r  {n}/{len(rows)}  נפתרו {len(solved)}".ljust(34),
              end="", flush=True)

    took = time.time() - t0
    print(f"\n\nלקח {took:.0f} שניות ({took/max(len(rows),1):.2f}s ליחידה) · "
          f"אפס טוקנים\n" + "=" * 62)
    if m.TMDB_FAILS:
        print(f"⚠ חיפושי TMDB שנכשלו: {dict(m.TMDB_FAILS)}\n")

    tot = len(rows)
    print(f"\nנפתרו בלי מודל:   {len(solved):>4} / {tot}  "
          f"({100*len(solved)//max(tot,1)}%)")
    print(f"נשארו למודל:      {len(unsolved):>4} / {tot}")
    if a.validate and solved:
        graded = [r for r in solved if "correct" in r]
        good = sum(1 for r in graded if r["correct"])
        if graded:
            print(f"\nדיוק הכלל הדטרמיניסטי: {good}/{len(graded)} = "
                  f"{100*good//len(graded)}%")
        for u, p in wrong[:10]:
            print(f"   ✗ {u['name'][:30]:<32} ניחש {p['tmdb_id']} "
                  f"(אמת {u['known']}) · {p['title'][:24]}")

    print(f"\nמועמדים לפני סינון סוג: {cand_before}  ואחרי: {cand_after}"
          f"  (−{100*(cand_before-cand_after)//max(cand_before,1)}%)")

    print("\nעלות הטוקנים למה שנשאר למודל, לפי צורת הבקשה:")
    for k in ("כמו עכשיו", "overview ל-80", "בלי overview"):
        v = tok[k]
        per = v // max(len(unsolved), 1)
        print(f"   {k:<16} {v:>9,} טוקנים  ({per:>5,} ליחידה)"
              f"   ≈ {v/500000:>4.1f} ימי מכסה")

    print("\nלמה לא נפתר בלי מודל:")
    for r, c in why.most_common(6):
        print(f"   {r[:44]:<46} {c:>4}")

    if a.out and solved:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump({"generated": int(time.time()), "provider": "exact",
                       "model": "deterministic", "min_confidence": 1.0,
                       "accepted": solved, "review": []},
                      fh, ensure_ascii=False, indent=1)
        print(f"\nנשמר: {a.out}  ({len(solved)} יחידות)")
        print(f"  לסינון:  python3 tmdb_map_filter.py --src {a.out} --min 0.99 --check")
    print("\nשום דבר לא נכתב לקטלוג.")


if __name__ == "__main__":
    main()
