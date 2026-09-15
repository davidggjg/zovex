#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tmdb_backfill — משלים tmdb_id חסר בקטלוג, כדי לפתוח טריילרים ומטא-דאטה.

למה זה שווה: פריט בלי tmdb_id לא יכול לקבל טריילר, וגם לא פוסטר או תיאור
מעודכנים. כרגע רק 435 מתוך ~9,590 פריטי VOD מזוהים.

למה זה זול: 8,479 הפרקים החסרים שייכים ל-117 סדרות בלבד. מחפשים את הסדרה
פעם אחת, וכל הפרקים שלה יורשים את המזהה. סה"כ ~793 קריאות ולא 9,155.

בטיחות: ברירת המחדל היא מדידה בלבד. הסקריפט לא כותב דבר לנתונים —
הוא מייצר קובץ מיפוי ודוח, וההחלה היא שלב נפרד ומאוחר יותר.

    python3 tmdb_backfill.py                 # מדידה בלבד
    python3 tmdb_backfill.py --limit 60      # טעימה מהירה
    python3 tmdb_backfill.py --out map.json
"""
import argparse, json, os, re, sys, threading, time
import urllib.parse, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

TMDB = "https://api.themoviedb.org/3"
ENV_PATHS = ["/opt/zovex-bot/.env", ".env"]


def load_key():
    k = os.environ.get("TMDB_API_KEY", "").strip()
    if k:
        return k
    for p in ENV_PATHS:
        try:
            for line in open(p, encoding="utf-8", errors="replace"):
                if line.strip().startswith("TMDB_API_KEY"):
                    return line.split("=", 1)[1].strip().strip("'\"")
        except Exception:
            continue
    return ""


def norm(s):
    """נרמול שם להשוואה: בלי שנה, בלי סימני פיסוק, רווחים מכווצים."""
    s = str(s or "").lower()
    s = re.sub(r"\(\s*\d{4}\s*\)", " ", s)
    s = re.sub(r"\b(19|20)\d{2}\b", " ", s)
    s = re.sub(r"[^\w֐-׿]+", " ", s, flags=re.U)
    return re.sub(r"\s+", " ", s).strip()


_last = [0.0]
_lock = threading.Lock()


def api(path, **params):
    """קריאה ל-TMDB עם ויסות קצב עדין. TMDB מרשה יותר, אבל אין סיבה למהר."""
    with _lock:
        gap = time.monotonic() - _last[0]
        if gap < 0.06:
            time.sleep(0.06 - gap)
        _last[0] = time.monotonic()
    url = f"{TMDB}{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code == 429:                       # מכסה — ממתינים ומנסים שוב
                time.sleep(2 + attempt * 3)
                continue
            raise
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)
    return {}


def best_match(results, title, year, kind):
    """בוחר תוצאה ומדרג את הביטחון בה.

    ודאי  — השם מתאים במדויק אחרי נרמול
    סביר  — התוצאה הראשונה והשנה תואמת (הצלבה שנייה)
    ספק   — התוצאה הראשונה בלבד, בלי שום אישוש נוסף
    """
    if not results:
        return None, "אין"
    want = norm(title)
    for r in results:
        for f in ("title", "name", "original_title", "original_name"):
            if r.get(f) and norm(r[f]) == want:
                return r, "ודאי"
    top = results[0]
    date = top.get("release_date") or top.get("first_air_date") or ""
    if year and date[:4] and str(year) == date[:4]:
        return top, "סביר"
    return top, "ספק"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="http://127.0.0.1:8000/content/lite")
    ap.add_argument("--out", default="tmdb_map.json")
    ap.add_argument("--limit", type=int, default=0, help="לבדוק רק N (טעימה)")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    key = load_key()
    if not key:
        print("❌ לא נמצא TMDB_API_KEY (בסביבה או ב-/opt/zovex-bot/.env)"); sys.exit(1)

    print(f"מושך קטלוג מ-{a.catalog} ...")
    with urllib.request.urlopen(a.catalog, timeout=90) as r:
        cat = json.loads(r.read().decode("utf-8", "replace"))
    vod = [m for m in cat if not m.get("is_live")
           and "/stream/" in str(m.get("video_url") or "")]

    # סדרה שיש לה מזהה באחד הפרקים — אין צורך ב-TMDB בשבילה
    known_series = {}
    for m in vod:
        if m.get("tmdb_id") and m.get("series_name"):
            known_series.setdefault(str(m["series_name"]).strip(), m["tmdb_id"])

    jobs, seen = [], set()
    for m in vod:
        if m.get("tmdb_id"):
            continue
        sn = str(m.get("series_name") or "").strip()
        if sn:
            if sn in known_series or sn in seen:
                continue
            seen.add(sn)
            jobs.append(("tv", sn, "", sn))
        else:
            jobs.append(("movie", str(m.get("title") or ""), str(m.get("year") or ""),
                         str(m.get("id"))))
    if a.limit:
        jobs = jobs[:a.limit]

    print(f"{len(jobs)} חיפושים ({sum(1 for j in jobs if j[0]=='movie')} סרטים, "
          f"{sum(1 for j in jobs if j[0]=='tv')} סדרות)\n")

    out, counts = {}, {"ודאי": 0, "סביר": 0, "ספק": 0, "אין": 0, "שגיאה": 0}
    done = [0]
    plock = threading.Lock()

    def work(job):
        kind, title, year, keyname = job
        try:
            p = {"api_key": key, "query": title, "include_adult": "false"}
            if year and kind == "movie":
                p["year"] = year
            res = api(f"/search/{kind}", **p).get("results", [])
            if not res and year:
                p.pop("year", None)
                res = api(f"/search/{kind}", **p).get("results", [])
            hit, conf = best_match(res, title, year, kind)
        except Exception as e:
            hit, conf = None, "שגיאה"
        with plock:
            counts[conf] = counts.get(conf, 0) + 1
            if hit:
                out[keyname] = {"kind": kind, "query": title, "confidence": conf,
                                "tmdb_id": hit.get("id"),
                                "matched": hit.get("title") or hit.get("name"),
                                "date": hit.get("release_date") or hit.get("first_air_date")}
            done[0] += 1
            if done[0] % 50 == 0:
                print(f"   ... {done[0]}/{len(jobs)}", flush=True)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(work, jobs))

    json.dump(out, open(a.out, "w"), ensure_ascii=False, indent=1)
    tot = len(jobs) or 1
    print(f"\n{'='*54}\nהסתיים ב-{time.time()-t0:.0f} שניות\n{'='*54}")
    for k in ("ודאי", "סביר", "ספק", "אין", "שגיאה"):
        n = counts.get(k, 0)
        print(f"  {k:<7} {n:>5}   {n*100/tot:5.1f}%")
    usable = counts.get("ודאי", 0) + counts.get("סביר", 0)
    print(f"\n➜ ניתנים להחלה בביטחון (ודאי+סביר): {usable}  ({usable*100/tot:.0f}%)")

    ex_conf = [v for v in out.values() if v["confidence"] == "ספק"][:8]
    if ex_conf:
        print("\nדוגמאות שסומנו 'ספק' — אלה שכדאי לעבור עליהן ידנית:")
        for v in ex_conf:
            print(f"   «{v['query']}»  →  «{v['matched']}» ({v.get('date') or '?'})")
    print(f"\nמיפוי נשמר ל-{a.out}. שום דבר בנתונים לא שונה.")


if __name__ == "__main__":
    main()
