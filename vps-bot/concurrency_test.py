#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מודד את התפוקה *המצטברת* של מסלול ההזרמה תחת מקביליות אמיתית.

למה זה נחוץ: /speedtest/bots בודק בוט אחד בכל פעם, בטור. סכום התוצאות שלו
*אינו* קיבולת המערכת — הוא רק אומר כמה כל בוט נותן כשהוא לבד. כאן מריצים
כמה משיכות במקביל, דרך מסלול ההזרמה האמיתי, ומודדים כמה MB/s באמת יוצאים.

רץ מול 127.0.0.1 כדי שרוחב הפס של הלקוח לא יהיה הגורם המגביל.
הטווח נלקח מעומק הקובץ (מעבר למטמון הקצה) כדי שבאמת יימשך מטלגרם.

הרצה:
    python3 concurrency_test.py            # 1,2,4,8 במקביל
    python3 concurrency_test.py --mb 16    # חלון גדול יותר לכל משיכה
"""
import argparse, json, sys, time, threading, urllib.request

LOCAL = "http://127.0.0.1:8000"
SITE = "https://zovex.duckdns.org"
OFFSET = 60 * 1024 * 1024          # 60MB לתוך הקובץ — הרחק מהמטמון


def catalog():
    req = urllib.request.Request(f"{SITE}/content", headers={"User-Agent": "zovex-test"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def pull(url, mb, out, idx):
    """מושך חלון אחד ומדווח כמה בייטים ובכמה זמן."""
    start, end = OFFSET, OFFSET + mb * 1024 * 1024 - 1
    req = urllib.request.Request(url, headers={
        "Referer": SITE + "/", "User-Agent": "zovex-test",
        "Range": f"bytes={start}-{end}"})
    t0 = time.time()
    got = 0
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            while True:
                b = r.read(262144)
                if not b:
                    break
                got += len(b)
    except Exception as e:
        out[idx] = (0, time.time() - t0, type(e).__name__)
        return
    out[idx] = (got, time.time() - t0, None)


def run(urls, n, mb):
    """n משיכות במקביל, כל אחת מקובץ אחר. מחזיר (MB/s מצטבר, פירוט)."""
    out = [None] * n
    threads = [threading.Thread(target=pull, args=(urls[i % len(urls)], mb, out, i))
               for i in range(n)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.time() - t0
    total = sum(o[0] for o in out if o)
    return total / 1024 / 1024 / wall, wall, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mb", type=int, default=8, help="גודל חלון לכל משיכה")
    ap.add_argument("--levels", default="1,2,4,8", help="רמות מקביליות")
    a = ap.parse_args()

    try:
        cat = catalog()
    except Exception as e:
        print("שליפת קטלוג נכשלה:", e, file=sys.stderr)
        return 1

    # קבצים גדולים מספיק כדי שיהיה מה למשוך ב-offset 60MB
    items = [e for e in cat
             if not e.get("is_live") and "/stream/" in str(e.get("video_url") or "")]
    urls = [e["video_url"].replace(SITE, LOCAL) for e in items[:16]]
    if not urls:
        print("לא נמצאו קבצים", file=sys.stderr)
        return 1

    print(f"חלון {a.mb}MB לכל משיכה, מ-offset 60MB (מעבר למטמון).")
    print("מודד תפוקה מצטברת אמיתית:\n")
    print(f"{'במקביל':>8} | {'מצטבר':>12} | {'זמן':>7} | הצליחו")
    print("-" * 48)

    for n in [int(x) for x in a.levels.split(",")]:
        mbps, wall, out = run(urls, n, a.mb)
        ok = sum(1 for o in out if o and o[0] > 0)
        print(f"{n:>8} | {mbps:>8.2f} MB/s | {wall:>5.1f}ש' | {ok}/{n}")
        errs = {o[2] for o in out if o and o[2]}
        if errs:
            print(f"{'':>8} | שגיאות: {', '.join(errs)}")
        time.sleep(3)

    print("\nאם המספר עולה עם המקביליות — יש עוד מקום, והמגבלה היא בכמה")
    print("שאנחנו מושכים בבת אחת. אם הוא נעצר — מצאנו את התקרה האמיתית.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
