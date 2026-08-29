#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מודד את **אחוז התקיעות** — המדד שקובע אם סרט רץ חלק.

למה לא למדוד מהירות: המהירות החציונית שלנו כבר מצוינת (4-10 MB/s מול
0.22 MB/s שסרט צריך). מה ששובר את הצפייה אינו הממוצע אלא ה"זנב" —
אחוז הבקשות שנתקעות לעשרות שניות ומרוקנות את הבאפר של הנגן.

למה מדידה בודדת חסרת ערך כאן: אותה בדיקה בדיוק נמדדה 9.65 MB/s ואז
0.39 MB/s בהפרש 39 דקות. הפיזור עצום, ולכן השוואה של מדידה-מול-מדידה
היא רעש. כאן מריצים הרבה דגימות ומדווחים התפלגות.

הדגימות נלקחות מאופסטים אקראיים באמצע הקובץ (מעבר למטמון הקצה), על
כמה קבצים לסירוגין, כדי שאף מטמון לא יזייף את התוצאה.

    python3 bench.py                 # 15 דגימות
    python3 bench.py --runs 30       # מדויק יותר
    python3 bench.py --label "אחרי"  # תווית לתיעוד
"""
import argparse, json, random, statistics, sys, time, urllib.request

LOCAL = "http://127.0.0.1:8000"
SITE = "https://zovex.duckdns.org"
HDRS = {"Referer": SITE + "/", "User-Agent": "zovex-bench"}
MIN_SIZE = 400 * 1024 * 1024
STALL = 10.0          # שנייה שמעליה זו "תקיעה" מבחינת הצופה


def _req(url, extra=None):
    h = dict(HDRS)
    if extra:
        h.update(extra)
    return urllib.request.Request(url, headers=h)


def size_of(url):
    try:
        with urllib.request.urlopen(_req(url, {"Range": "bytes=0-255"}),
                                    timeout=120) as r:
            cr = r.headers.get("Content-Range", "")
            r.read(256)
            return int(cr.rsplit("/", 1)[1]) if "/" in cr else None
    except Exception:
        return None


def sample(url, start, nbytes):
    t0 = time.time()
    got = 0
    try:
        with urllib.request.urlopen(
                _req(url, {"Range": f"bytes={start}-{start + nbytes - 1}"}),
                timeout=240) as r:
            while True:
                b = r.read(262144)
                if not b:
                    break
                got += len(b)
    except Exception as e:
        return time.time() - t0, 0, type(e).__name__
    return time.time() - t0, got, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=15)
    ap.add_argument("--mb", type=int, default=4)
    ap.add_argument("--label", default="")
    a = ap.parse_args()

    try:
        with urllib.request.urlopen(_req(f"{SITE}/content"), timeout=90) as r:
            cat = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print("שליפת קטלוג נכשלה:", e, file=sys.stderr)
        return 1

    items = [e for e in cat
             if not e.get("is_live") and "/stream/" in str(e.get("video_url") or "")]
    files = []
    for e in items:
        if len(files) >= 6:
            break
        u = e["video_url"].replace(SITE, LOCAL)
        s = size_of(u)
        if s and s >= MIN_SIZE:
            files.append((u, s))
    if not files:
        print("לא נמצאו קבצים גדולים", file=sys.stderr)
        return 1

    n = a.mb * 1024 * 1024
    print(f"{a.runs} דגימות של {a.mb}MB, אופסטים אקראיים, {len(files)} קבצים"
          + (f"  [{a.label}]" if a.label else ""))
    print("תקיעה = מעל %.0f שניות\n" % STALL, flush=True)

    times, stalls, errs = [], 0, 0
    for i in range(1, a.runs + 1):
        url, size = files[(i - 1) % len(files)]
        # אמצע הקובץ, הרחק ממטמון הראש והזנב
        off = random.randint(int(size * 0.2), int(size * 0.75))
        secs, got, err = sample(url, off, n)
        times.append(secs)
        if err or got == 0:
            errs += 1
        mark = ""
        if secs > STALL:
            stalls += 1
            mark = "  ← תקיעה"
        rate = (got / 1024 / 1024 / secs) if secs > 0 and got else 0
        print(f"  {i:>3}/{a.runs}  {secs:>7.1f}ש'  {rate:>6.2f} MB/s"
              f"{'  ' + err if err else ''}{mark}", flush=True)

    times.sort()
    p = lambda q: times[min(len(times) - 1, int(len(times) * q))]
    print("\n" + "=" * 46)
    print(f"  חציון          {statistics.median(times):>7.1f} שניות")
    print(f"  אחוזון 90      {p(0.90):>7.1f} שניות")
    print(f"  הגרוע ביותר    {max(times):>7.1f} שניות")
    print(f"  🎯 אחוז תקיעות {100*stalls/len(times):>6.0f}%   ({stalls}/{len(times)})")
    if errs:
        print(f"  שגיאות         {errs}")
    print("=" * 46)
    print("\nהמדד היחיד שקובע הוא אחוז התקיעות. חציון טוב עם 20% תקיעות")
    print("= סרט שנתקע כל דקה. המטרה: 0%.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
