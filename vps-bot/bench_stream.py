#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_stream — מדידת חוויית הצפייה מנקודת המבט של הנגן. קריאה בלבד.

לוקח כמה סרטים אמיתיים מהקטלוג, ומבקש מכל אחד שני טווחים כמו שנגן עושה:
מההתחלה, ומאמצע הקובץ (שם אין מטמון קצה — זו המשיכה האמיתית מטלגרם).
לכל בקשה נמדד:
  · TTFB      — זמן עד הבייט הראשון (≈ כמה זמן הצופה מחכה שהסרט יתחיל)
  · MB/s      — מהירות ממוצעת
  · gap       — ההפסקה הארוכה ביותר בין חתיכות. זה מה שגורם לתקיעה:
                סרט 1080p צורך ~0.6–1MB/s, ונגן עם באפר של כמה שניות נתקע
                כשמגיע פער ארוך מזה.

    python3 bench_stream.py                 # 6 סרטים, 24MB לכל טווח
    python3 bench_stream.py --n 10 --mb 32
"""
import argparse, json, random, statistics, sys, time, urllib.parse, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://127.0.0.1:8000")
ap.add_argument("--n", type=int, default=6)
ap.add_argument("--mb", type=int, default=24)
ap.add_argument("--seed", type=int, default=7)
ap.add_argument("--timeout", type=float, default=90)
a = ap.parse_args()
REF = "https://zovex.duckdns.org/"


def get(url, rng=None, timeout=30):
    h = {"Referer": REF, "User-Agent": "zovex-bench/1"}
    if rng:
        h["Range"] = rng
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout)


def local(url):
    """הקישור בקטלוג הוא ציבורי (https://domain/stream/...?exp&sig) — שולחים
    אותו ישירות לשרת המקומי, אותו נתיב ואותה חתימה."""
    p = urllib.parse.urlsplit(url)
    return a.base + p.path + (("?" + p.query) if p.query else "")


def measure(url, start, nbytes):
    t0 = time.time()
    try:
        r = get(url, f"bytes={start}-{start + nbytes - 1}", timeout=a.timeout)
    except Exception as e:
        return {"err": f"{type(e).__name__}: {e}"[:80]}
    total = None
    cr = r.headers.get("Content-Range", "")
    if "/" in cr:
        try: total = int(cr.rsplit("/", 1)[1])
        except ValueError: pass
    got, first, last, gap = 0, None, None, 0.0
    deadline = t0 + a.timeout
    while got < nbytes and time.time() < deadline:
        try:
            b = r.read(256 * 1024)
        except Exception as e:
            return {"err": f"read: {type(e).__name__}", "got": got}
        now = time.time()
        if not b:
            break
        if first is None:
            first = now
        elif last is not None:
            gap = max(gap, now - last)
        last = now
        got += len(b)
    r.close()
    el = (last or time.time()) - t0
    return {"status": r.status, "ttfb": (first or time.time()) - t0, "mbps": got / 1048576 / max(el, 1e-6),
            "gap": gap, "got": got, "total": total}


def main():
    try:
        items = json.load(get(a.base + "/content/lite?limit=800"))
    except Exception as e:
        sys.exit(f"לא הצלחתי לקרוא את הקטלוג: {e}")
    vids = [x for x in items if "/stream/" in (x.get("video_url") or "") and not x.get("is_live")]
    if not vids:
        sys.exit("לא נמצאו סרטים מטלגרם בקטלוג")
    random.Random(a.seed).shuffle(vids)
    picks = vids[:a.n]
    nb = a.mb * 1048576
    rows = []
    print(f"{len(picks)} סרטים · {a.mb}MB לכל טווח\n")
    print(f"{'סרט':<28} {'מיקום':<7} {'TTFB':>7} {'MB/s':>7} {'פער מקס':>9}")
    for it in picks:
        url = local(it["video_url"])
        name = (it.get("title") or "?")[:26]
        r0 = measure(url, 0, nb)
        segs = [("התחלה", r0)]
        tot = r0.get("total")
        if tot and tot > nb * 3:
            segs.append(("אמצע", measure(url, (tot // 2) // 1048576 * 1048576, nb)))
        for where, r in segs:
            if "err" in r:
                print(f"{name:<28} {where:<7} ❌ {r['err']}")
                continue
            rows.append((where, r))
            flag = " ⚠️" if r["gap"] > 2 else ""
            print(f"{name:<28} {where:<7} {r['ttfb']:>6.2f}s {r['mbps']:>7.2f} {r['gap']:>8.2f}s{flag}")
            name = ""
    if not rows:
        sys.exit("\nאין מדידות תקינות")

    def summ(sel):
        if not sel: return "—"
        t = sorted(x["ttfb"] for x in sel); m = sorted(x["mbps"] for x in sel); g = sorted(x["gap"] for x in sel)
        p90 = lambda v: v[min(len(v) - 1, int(len(v) * 0.9))]
        return (f"TTFB חציון {statistics.median(t):.2f}s · מהירות חציון {statistics.median(m):.2f}MB/s "
                f"(הכי איטי {m[0]:.2f}) · פער p90 {p90(g):.2f}s · פערים מעל 2ש: {sum(1 for x in g if x > 2)}")
    print("\n== סיכום ==")
    print("  התחלה:", summ([r for w, r in rows if w == "התחלה"]))
    print("  אמצע: ", summ([r for w, r in rows if w == "אמצע"]))
    print("\n  (1080p צריך בערך 0.6–1MB/s בלי פערים ארוכים)")


if __name__ == "__main__":
    main()
