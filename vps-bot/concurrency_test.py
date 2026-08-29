#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מאבחן איפה מסלול ההזרמה מאבד תפוקה.

הרקע: /speedtest/bots מודד משיכה ישירה דרך חיבורי המדיה ומקבל ~4 MB/s לבוט.
אותה מערכת, דרך מסלול ההזרמה של /stream, נמדדה ב-0.06 MB/s — פער של פי 60.
הכלי הזה מבודד את הסיבה בשלוש שאלות, בסדר הזה:

  1. עומק  — האם משיכה מאמצע הקובץ איטית ממשיכה מתחילתו?
             (אותו קובץ, אותו גודל חלון, רק ה-offset משתנה)
  2. גודל  — האם חלון גדול מתנהג אחרת מחלון קטן?
  3. מקביליות — האם התפוקה גדלה כשמושכים כמה קבצים יחד?

הקבצים נבחרים לפי גודל אמיתי (נקרא מ-Content-Range), כך שאף בקשה לא
חורגת מסוף הקובץ — טעות שפסלה מדידה קודמת.

הרצה:  python3 concurrency_test.py
"""
import json, sys, time, threading, urllib.request

LOCAL = "http://127.0.0.1:8000"
SITE = "https://zovex.duckdns.org"
HDRS = {"Referer": SITE + "/", "User-Agent": "zovex-diag"}
MIN_SIZE = 400 * 1024 * 1024          # רק קבצים מעל 400MB
EDGE_SAFE = 40 * 1024 * 1024          # מעבר למטמון הקצה (32MB)


def _req(url, extra=None, timeout=240):
    h = dict(HDRS)
    if extra:
        h.update(extra)
    return urllib.request.Request(url, headers=h)


def catalog():
    with urllib.request.urlopen(_req(f"{SITE}/content"), timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def file_size(url):
    """גודל אמיתי מ-Content-Range של בקשה זעירה."""
    try:
        with urllib.request.urlopen(
                _req(url, {"Range": "bytes=0-255"}), timeout=120) as r:
            cr = r.headers.get("Content-Range", "")
            r.read(256)
            return int(cr.rsplit("/", 1)[1]) if "/" in cr else None
    except Exception:
        return None


def pull(url, start, nbytes, out=None, idx=0):
    """מושך חלון ומחזיר (בייטים, שניות, שגיאה)."""
    t0 = time.time()
    got = 0
    err = None
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
        err = type(e).__name__
    res = (got, time.time() - t0, err)
    if out is not None:
        out[idx] = res
    return res


def rate(got, secs):
    return (got / 1024 / 1024 / secs) if secs > 0 and got else 0.0


def main():
    try:
        cat = catalog()
    except Exception as e:
        print("שליפת קטלוג נכשלה:", e, file=sys.stderr)
        return 1

    items = [e for e in cat
             if not e.get("is_live") and "/stream/" in str(e.get("video_url") or "")]

    print("בוחר קבצים גדולים (מעל 400MB)...", flush=True)
    picked = []
    for e in items:
        if len(picked) >= 4:
            break
        u = e["video_url"].replace(SITE, LOCAL)
        s = file_size(u)
        if s and s >= MIN_SIZE:
            picked.append((u, s, (e.get("title") or "")[:28]))
            print(f"   ✓ {picked[-1][2]}  ({s/1024/1024:.0f}MB)", flush=True)
    if not picked:
        print("לא נמצאו קבצים גדולים מספיק", file=sys.stderr)
        return 1

    url, size, title = picked[0]
    W = 4 * 1024 * 1024            # חלון 4MB לכל הבדיקות

    print(f"\n{'='*52}\n1. עומק — אותו קובץ, אותו חלון (4MB), offset משתנה\n{'='*52}")
    for label, off in [("קרוב להתחלה (40MB)", EDGE_SAFE),
                       ("רבע לתוך הקובץ", size // 4),
                       ("אמצע הקובץ", size // 2)]:
        got, secs, err = pull(url, off, W)
        print(f"   {label:<22} {rate(got,secs):>6.2f} MB/s  ({secs:>6.1f}ש'"
              f"{', ' + err if err else ''})", flush=True)

    print(f"\n{'='*52}\n2. גודל החלון — מ-offset קבוע (40MB)\n{'='*52}")
    for mb in (1, 4, 16):
        got, secs, err = pull(url, EDGE_SAFE, mb * 1024 * 1024)
        print(f"   חלון {mb:>2}MB              {rate(got,secs):>6.2f} MB/s"
              f"  ({secs:>6.1f}ש'{', ' + err if err else ''})", flush=True)

    print(f"\n{'='*52}\n3. מקביליות — קבצים שונים, חלון 4MB מ-40MB\n{'='*52}")
    for n in (1, 2, 4):
        out = [None] * n
        ths = [threading.Thread(target=pull,
                                args=(picked[i % len(picked)][0], EDGE_SAFE, W, out, i))
               for i in range(n)]
        t0 = time.time()
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        wall = time.time() - t0
        total = sum(o[0] for o in out if o)
        ok = sum(1 for o in out if o and o[0] > 0)
        print(f"   {n} במקביל            {rate(total,wall):>6.2f} MB/s"
              f"  ({wall:>6.1f}ש', {ok}/{n} הצליחו)", flush=True)
        time.sleep(2)

    print("\nמה לחפש: אם 'קרוב להתחלה' מהיר ו'אמצע' איטי — הבעיה היא")
    print("קפיצה לעומק הקובץ. אם כולם איטיים באותה מידה — הבעיה כללית יותר.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
