#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tmdb_ai_match — מודל שפה בוחר את ההתאמה ב-TMDB, ו-TMDB נותן את העובדות.

הרעיון של דוד: שהמודל "יחקור את הכותר עד שהוא בטוח ב-99 אחוז". זה בדיוק
מה שנבנה כאן, עם הבדל אחד קריטי: **המודל לא כותב אף שדה.** הוא בוחר
מזהה מתוך רשימת מועמדים אמיתית של TMDB, ומדווח כמה הוא בטוח. התיאור,
השם באנגלית, הטריילר, השנה והז'אנר מגיעים אחר כך מ-TMDB עצמו.

למה זה לא קפריזה: טריילר מומצא הוא סרטון שגוי שמתנגן, ותיאור מומצא הוא
סיפור אמין על סרט אמיתי. שניהם גרועים מלא-כלום, ואי אפשר לראות אותם
בעין. מזהה לעומת זאת הוא מספר שאפשר לאמת מול TMDB בשנייה.

הגודל האמיתי של העבודה (נמדד מהקטלוג):
    12,632 פריטי VOD בלי tmdb_id
    אבל הם מתקפלים ל-932 חיפושים בלבד:
        196 סדרות  → 11,896 פרקים   (חיפוש אחד לסדרה, הפרקים יורשים)
        736 פריטים בודדים
    השמות שמפילים חיפוש מחרוזות: "דרגון בול קאי לעברית", "סברי מרנן",
    "ז מ תשע גופות במקסיקו". על אלה בדיוק מודל שפה טוב.

ואיך יודעים ש-99% זה באמת 99%:
    233 פריטים בקטלוג **כבר** מזוהים. --validate מריץ עליהם את אותו
    מסלול בדיוק ומשווה לתשובה הידועה. זו מדידת דיוק אמיתית, ולא המודל
    שמעיד על עצמו. מודל שמתבקשים ממנו לבחור תמיד בוחר, ולכן ההנחיה
    כוללת במפורש גם "אף אחד מאלה" — ובלי זה הביטחון חסר משמעות.

בטיחות: הסקריפט **לא נוגע ב-content.json**. הוא מייצר קובץ מיפוי,
וההחלה היא שלב נפרד (tmdb_apply.py), בדיוק כמו ב-tmdb_backfill.

    python3 tmdb_ai_match.py --provider mock --validate --limit 20
    python3 tmdb_ai_match.py --validate                  # דיוק אמיתי
    python3 tmdb_ai_match.py --run --limit 40            # טעימה
    python3 tmdb_ai_match.py --run --out tmdb_ai_map.json

מפתחות — מהסביבה או מ-/opt/zovex-bot/.env, אף פעם לא בשורת הפקודה
(היא נשמרת בהיסטוריה של bash):
    TMDB_API_KEY
    LLM_API_KEY          (או GROQ_API_KEY / XAI_API_KEY)
"""
import argparse, json, os, re, sys, time
import urllib.parse, urllib.request, urllib.error
from collections import Counter

TMDB = "https://api.themoviedb.org/3"
ENV_PATHS = ["/opt/zovex-bot/.env", ".env"]

# שני הספקים תואמי-OpenAI, ולכן זה הבדל של כתובת ושם דגם בלבד.
#
# ברירת המחדל נבחרה במדידה ולא בהנחה. דוד העיר שגרוק מחליפה מודלים, וצדק:
# llama-3.3-70b-versatile שהגדרתי קודם כבר לא קיים, וכל שורת ה-Llama לצ'אט
# הוסרה. מתוך מה שנותר הרצתי מבחן על שש דוגמאות אמיתיות מהקטלוג, כולל שתי
# מלכודות — מועמד מזויף בתרגום מילולי ("הרעשנים" מול The Noisy Ones), ומקרה
# שבו התשובה הנכונה כלל לא ברשימה ("הטירון") וצריך להחזיר null:
#
#     qwen/qwen3.8-27b      6/6   0.4 שניות לפריט
#     openai/gpt-oss-120b   5/6   0.9
#     openai/gpt-oss-20b    4/6   0.8   ← ענה בביטחון 0.9 על מלכודת ה-null
#
# ההפרש הזה הוא בדיוק ההבדל בין מיפוי שאפשר לסמוך עליו לבין מיפוי שמכניס
# שטויות לקטלוג. 0.4 שניות ליחידה = כשש דקות לכל 924 היחידות.
PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1", "qwen/qwen3.8-27b",
             ("LLM_API_KEY", "GROQ_API_KEY")),
    "xai":  ("https://api.x.ai/v1", "grok-2-latest",
             ("LLM_API_KEY", "XAI_API_KEY")),
    "mock": ("", "mock", ()),
}

# תרגום ביטחון מספרי לתוויות ש-tmdb_apply.py כבר יודע לקרוא.
def _conf_label(c: float) -> str:
    return "ודאי" if c >= 0.9 else ("סביר" if c >= 0.75 else "ספק")

# מילים שמודבקות לשמות אצלנו ואינן חלק מהכותר. הסרתן לפני החיפוש
# היא מה שהופך "דרגון בול קאי לעברית" לשאילתה שמחזירה מועמדים.
NOISE = [
    r"\bלעברית\b", r"\bמדובב(?:ת)?\b", r"\bמתורגם\b", r"\bעונה\s*\d+",
    r"\bפרק\s*\d+", r"\bע\s*\d+\b", r"\bפ\s*\d+", r"\bHD\b", r"\b4K\b",
    r"\bWEB-?DL\b", r"\bBluRay\b", r"\bx26[45]\b", r"\bT\.?S\b",
    r"\bמ\s+(?=\S)", r"[\[\]\(\)]", r"\s*[-–_]\s*$",
]


def load_key(*names: str) -> str:
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    for p in ENV_PATHS:
        try:
            for line in open(p, encoding="utf-8", errors="replace"):
                line = line.strip()
                for n in names:
                    if line.startswith(n + "="):
                        return line.split("=", 1)[1].strip().strip("'\"")
        except Exception:
            continue
    return ""


# אימוג'ים מגיעים מהשמות בטלגרם ומזיקים לחיפוש ב-TMDB. הטווחים הם
# דגלים, סמלים, פיקטוגרמות ווריאציות — לא אותיות בשום שפה.
EMOJI = re.compile(
    "[\U0001F1E6-\U0001F1FF\U0001F300-\U0001FAFF\U00002600-\U000027BF"
    "\U0000FE00-\U0000FE0F\U00002190-\U000021FF\U00002B00-\U00002BFF]+")
YEAR = re.compile(r"\b(19|20)\d{2}\b")


def clean(name: str):
    """(שאילתה, שנה). השנה נשלפת החוצה ולא נשארת בשאילתה: TMDB מחפש
    אותה כמילה ומדרדר את התוצאות. היא כן נמסרת למודל כרמז להבחנה בין
    גרסאות (למשל רימייק מול המקור)."""
    s = EMOJI.sub(" ", str(name or ""))
    yr = ""
    m = YEAR.search(s)
    if m:
        yr = m.group(0)
        s = s[:m.start()] + " " + s[m.end():]
    for rx in NOISE:
        s = re.sub(rx, " ", s, flags=re.I)
    s = re.sub(r"\s{2,}", " ", s).strip(" -–_·:")
    return s, yr


# Cloudflare יושב לפני Groq וחוסם את ה-User-Agent שברירת המחדל של urllib
# שולחת ("Python-urllib/3.x"). זה חוזר כ-403 עם "error code: 1010", שנראה
# כמו מפתח פסול אבל אינו: אותה בקשה בדיוק עם UA רגיל מחזירה 200. נמדד
# בשלושה ניסיונות — ברירת מחדל נכשלת, curl/8.5.0 ו-zovex-bot/1.0 עוברים.
UA = "zovex-bot/1.0"


def http_json(url: str, headers=None, data=None, timeout=45):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    req.add_header("User-Agent", UA)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# ── TMDB ─────────────────────────────────────────────────────────────────────
def tmdb_candidates(key: str, queries, limit: int = 8) -> list:
    """מועמדים אמיתיים בלבד.

    שתי שפות, כי חלק מהכותרים קיימים רק באחת. וכמה שאילתות, כי שנה
    בסוף השם היא לפעמים חלק מהכותר ולא שנת יציאה — "וונדר וומן 1984"
    היא הדוגמה. מחפשים גם עם וגם בלי ומאחדים, והכפילויות מסוננות ממילא.
    """
    if isinstance(queries, str):
        queries = [queries]
    queries = [q for q in dict.fromkeys(x.strip() for x in queries) if q]
    seen, out = set(), []
    for name in queries:
        for lang in ("he-IL", "en-US"):
            qs = urllib.parse.urlencode(
                {"api_key": key, "query": name, "language": lang,
                 "include_adult": "false"})
            try:
                res = http_json(f"{TMDB}/search/multi?{qs}")
            except Exception:
                continue
            for r in (res.get("results") or []):
                mt = r.get("media_type")
                if mt not in ("movie", "tv"):
                    continue
                rid = (mt, r.get("id"))
                if rid in seen:
                    continue
                seen.add(rid)
                date = r.get("release_date") or r.get("first_air_date") or ""
                ov = (r.get("overview") or "").replace("\n", " ")
                out.append({
                    "tmdb_id": r.get("id"), "media_type": mt,
                    "title": r.get("title") or r.get("name") or "",
                    "original_title": (r.get("original_title")
                                       or r.get("original_name") or ""),
                    "year": date[:4],
                    "popularity": round(r.get("popularity") or 0, 1),
                    "overview": ov[:220],
                })
    out.sort(key=lambda c: -c["popularity"])
    return out[:limit]


# ── המודל ────────────────────────────────────────────────────────────────────
SYSTEM = (
    "You match messy Hebrew media library entries to TMDB entries.\n"
    "You are given the raw catalogue name and a list of real TMDB candidates.\n"
    "Pick the ONE candidate that is the same work, or none.\n"
    "Rules:\n"
    "- Choose ONLY from the given candidates. Never invent an id.\n"
    "- Hebrew names are often localised or transliterated, sometimes "
    "misspelled. Judge by meaning, not by spelling.\n"
    "- If none of the candidates is the same work, return tmdb_id null.\n"
    "- confidence is your honest probability that the pick is correct, "
    "0.0 to 1.0. Use low values freely; a wrong match is worse than none.\n"
    'Answer with JSON only: '
    '{"tmdb_id": <int|null>, "media_type": "movie"|"tv"|null, '
    '"confidence": <float>, "why": "<one short sentence>"}'
)


def ask_model(cfg: dict, raw: str, cands: list, year: str = "") -> dict:
    if cfg["provider"] == "mock":
        # בודק את הצנרת בלי לשלם ובלי מפתח: בוחר את המועמד הפופולרי
        # ביותר, וביטחון שנגזר מדמיון המחרוזות. לא חכם — אבל מאפשר
        # להריץ את כל המסלול ולראות שהדוח, הסף והפורמט נכונים.
        if not cands:
            return {"tmdb_id": None, "media_type": None, "confidence": 0.0,
                    "why": "mock: אין מועמדים"}
        c = cands[0]
        a, b = clean(raw)[0].lower(), (c["title"] or "").lower()
        common = len(set(a.split()) & set(b.split()))
        conf = min(0.99, 0.55 + 0.15 * common)
        return {"tmdb_id": c["tmdb_id"], "media_type": c["media_type"],
                "confidence": round(conf, 2), "why": "mock"}

    body = json.dumps({
        "model": cfg["model"],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(
                {"catalogue_name": raw, "catalogue_year": year or None,
                 "candidates": cands}, ensure_ascii=False)},
        ],
    }).encode()
    res = http_json(f"{cfg['base_url']}/chat/completions",
                    headers={"Authorization": "Bearer " + cfg["key"]},
                    data=body, timeout=90)
    txt = res["choices"][0]["message"]["content"]
    try:
        out = json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}", txt, re.S)
        out = json.loads(m.group(0)) if m else {}
    # אף פעם לא סומכים על הפלט: מזהה שלא ברשימה נפסל כאן ולא בהמשך
    ok = {(c["media_type"], c["tmdb_id"]) for c in cands}
    tid, mt = out.get("tmdb_id"), out.get("media_type")
    if tid is not None and (mt, tid) not in ok:
        return {"tmdb_id": None, "media_type": None, "confidence": 0.0,
                "why": f"המודל החזיר מזהה שלא ברשימה ({mt}/{tid}) — נפסל"}
    try:
        conf = float(out.get("confidence") or 0)
    except Exception:
        conf = 0.0
    return {"tmdb_id": tid, "media_type": mt,
            "confidence": max(0.0, min(1.0, conf)),
            "why": str(out.get("why") or "")[:160]}


# ── הקטלוג ───────────────────────────────────────────────────────────────────
def load_catalog(url: str) -> list:
    if url.startswith("http"):
        return http_json(url, timeout=120)
    return json.loads(open(url, encoding="utf-8").read())


def units(items: list, want_known: bool) -> list:
    """מקפל את הקטלוג ליחידות חיפוש: סדרה אחת = חיפוש אחד."""
    by_series, singles = {}, []
    for i in items:
        if i.get("is_live"):
            continue
        known = i.get("tmdb_id")
        if bool(known) != want_known:
            continue
        sn = (i.get("series_name") or "").strip()
        if sn:
            e = by_series.setdefault(sn, {"name": sn, "kind": "series",
                                          "n": 0, "known": known})
            e["n"] += 1
        else:
            singles.append({"name": (i.get("title") or "").strip(),
                            "kind": "item", "n": 1, "known": known,
                            "id": i.get("id")})
    return list(by_series.values()) + singles


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="http://127.0.0.1:8000/content/lite")
    ap.add_argument("--provider", default="groq", choices=list(PROVIDERS))
    ap.add_argument("--model", default="")
    ap.add_argument("--base-url", default="")
    ap.add_argument("--validate", action="store_true",
                    help="מריץ על מה שכבר מזוהה ומודד דיוק מול התשובה הידועה")
    ap.add_argument("--run", action="store_true",
                    help="מייצר הצעות למה שחסר")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--min-confidence", type=float, default=0.9)
    ap.add_argument("--sleep", type=float, default=0.25)
    ap.add_argument("--out", default="tmdb_ai_map.json")
    a = ap.parse_args()

    if not (a.validate or a.run):
        ap.error("צריך --validate או --run")

    base, model, key_names = PROVIDERS[a.provider]
    cfg = {"provider": a.provider,
           "base_url": a.base_url or base,
           "model": a.model or model,
           "key": load_key(*key_names) if key_names else ""}
    if a.provider != "mock" and not cfg["key"]:
        sys.exit(f"אין מפתח. שים {' או '.join(key_names)} ב-/opt/zovex-bot/.env")
    tkey = load_key("TMDB_API_KEY")
    if not tkey:
        sys.exit("אין TMDB_API_KEY ב-/opt/zovex-bot/.env")

    items = load_catalog(a.catalog)
    rows = units(items, want_known=a.validate)
    if a.limit:
        rows = rows[:a.limit]
    mode = "אימות מול תשובות ידועות" if a.validate else "התאמה למה שחסר"
    print(f"{mode} · ספק {a.provider} · דגם {cfg['model']}")
    print(f"{len(rows)} יחידות חיפוש · סף ביטחון {a.min_confidence}\n")

    out, t0 = [], time.time()
    for n, u in enumerate(rows, 1):
        q, yr = clean(u["name"])
        # גם עם השנה וגם בלעדיה — ראה ההערה ב-tmdb_candidates
        qs = [q] + ([f"{q} {yr}"] if yr else [])
        cands = tmdb_candidates(tkey, qs) if q else []
        try:
            ans = ask_model(cfg, u["name"], cands, yr)
        except urllib.error.HTTPError as e:
            sys.exit(f"\nהמודל החזיר {e.code}: "
                     f"{e.read()[:200].decode('utf-8', 'replace')}")
        except Exception as e:
            ans = {"tmdb_id": None, "media_type": None, "confidence": 0.0,
                   "why": f"שגיאה: {type(e).__name__}"}
        rec = {**u, "query": q, "year_hint": yr,
               "candidates": len(cands), **ans}
        out.append(rec)
        mark = "·"
        if a.validate and u["known"]:
            rec["correct"] = (str(ans["tmdb_id"]) == str(u["known"]))
            mark = "✓" if rec["correct"] else "✗"
        print(f"\r  {n}/{len(rows)} {mark} {u['name'][:34]:<36}", end="", flush=True)
        if a.sleep:
            time.sleep(a.sleep)
    print(f"\n\nלקח {time.time()-t0:.0f} שניות\n" + "=" * 62)

    if a.validate:
        graded = [r for r in out if "correct" in r]
        print(f"\nדיוק על {len(graded)} פריטים שהתשובה שלהם ידועה:\n")
        print(f"  {'סף':>6} {'נבחרו':>8} {'נכונים':>8} {'דיוק':>8} {'כיסוי':>8}")
        for th in (0.5, 0.7, 0.8, 0.9, 0.95, 0.99):
            sel = [r for r in graded if r["confidence"] >= th and r["tmdb_id"]]
            good = sum(1 for r in sel if r["correct"])
            acc = f"{good*100//len(sel)}%" if sel else "—"
            cov = f"{len(sel)*100//len(graded)}%" if graded else "—"
            print(f"  {th:>6} {len(sel):>8} {good:>8} {acc:>8} {cov:>8}")
        bad = [r for r in graded if r["confidence"] >= a.min_confidence
               and r["tmdb_id"] and not r["correct"]]
        if bad:
            print(f"\n⚠ {len(bad)} טעויות מעל הסף — אלה שצריך להסתכל עליהן:")
            for r in bad[:10]:
                print(f"   {r['name'][:32]:<34} ניחש {r['tmdb_id']} "
                      f"(אמת {r['known']}) ביטחון {r['confidence']}")
        else:
            print(f"\n✓ אפס טעויות מעל סף {a.min_confidence}")
        print("\nהעמודה שקובעת היא 'דיוק'. 'כיסוי' אומר כמה מהקטלוג יטופל")
        print("בסף הזה — סף גבוה יותר מדויק יותר ומכסה פחות.")

    accepted = [r for r in out if r["tmdb_id"]
                and r["confidence"] >= a.min_confidence]
    review = [r for r in out if r not in accepted]
    if a.run:
        eps = sum(r["n"] for r in accepted)
        print(f"\nעברו את הסף: {len(accepted)} יחידות → {eps} פריטים בקטלוג")
        print(f"לבדיקה ידנית:  {len(review)} יחידות")
        print("\nדוגמאות שהתקבלו:")
        for r in accepted[:8]:
            print(f"   {r['name'][:30]:<32} → {r['media_type']}/{r['tmdb_id']} "
                  f"({r['confidence']}) {r['why'][:40]}")
        if review:
            print("\nדוגמאות שנפלו מתחת לסף:")
            for r in review[:8]:
                print(f"   {r['name'][:30]:<32} ביטחון {r['confidence']} "
                      f"· {r['candidates']} מועמדים · {r['why'][:40]}")

    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump({"generated": int(time.time()), "provider": a.provider,
                   "model": cfg["model"], "min_confidence": a.min_confidence,
                   "accepted": accepted, "review": review},
                  fh, ensure_ascii=False, indent=1)
    print(f"\nנשמר: {a.out}")

    # ובנוסף, קובץ בפורמט של tmdb_backfill — כדי ש-tmdb_apply.py יוכל להחיל
    # אותו בלי לשנות בו שורה. המפתח הוא שם הסדרה לסדרות ו-id לפריט בודד,
    # בדיוק כמו ש-tmdb_apply מחפש (by_series מול by_id).
    if a.run:
        compat = {}
        for r in out:
            if not r["tmdb_id"]:
                continue
            key = r["name"] if r["kind"] == "series" else str(r.get("id") or r["name"])
            compat[key] = {"kind": "tv" if r["kind"] == "series" else "movie",
                           "query": r["query"], "tmdb_id": r["tmdb_id"],
                           "confidence": _conf_label(r["confidence"])}
        cpath = a.out.replace(".json", "") + "_apply.json"
        with open(cpath, "w", encoding="utf-8") as fh:
            json.dump(compat, fh, ensure_ascii=False, indent=1)
        lab = Counter(v["confidence"] for v in compat.values())
        print(f"נשמר גם: {cpath}  ({len(compat)} רשומות · {dict(lab)})")
        print(f"  להחלה:  python3 tmdb_apply.py --map {cpath} --check")
    print("שום דבר לא נכתב לקטלוג. ההחלה היא שלב נפרד ומאוחר יותר.")
    print(f"התפלגות ביטחון: "
          f"{dict(Counter(round(r['confidence'], 1) for r in out).most_common())}")


if __name__ == "__main__":
    main()
