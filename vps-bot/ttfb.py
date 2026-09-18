#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ttfb — כמה זמן לוקח *לפתוח* זרם. זה המספר שהתקלקל.

## למה דווקא זה

המדידה של vod_watch הראתה תמונה חדה: **אפס תקיעות ב-16 דקות של הזרמה
רצופה**, אבל 11.5 ו-15.0 שניות עד הבייט הראשון, ודילוגים של עד 6.9 שניות.
כלומר מה שהתדרדר הוא *פתיחת* זרם, לא ההזרמה עצמה. צופה שלוחץ פליי ומחכה
13 שניות למסך שחור קורא לזה "נתקע", והוא צודק.

הכלי הזה מודד רק את זה, ובזול: בקשת Range של **בייט אחד**. זה מכריח את
השרת לעשות את כל העבודה של הפתיחה — לבחור בוט, לשלוף את ההודעה, להשיג
בריכת חיבורים, לקפוץ לאופסט — בלי להוריד ולו מגהבייט. אפשר להריץ אותו
בשיא העומס בלי להיות חלק מהעומס.

## שתי מדידות לכל כותר

  • **פתיחה** — אופסט 0. זה "לחצתי פליי".
  • **דילוג** — אופסט אקראי באמצע. זה "דילגתי קדימה", והמסלול שונה: אי
    אפשר להגיש את זה ממה שכבר נמשך, צריך לקפוץ לשם מחדש.

## מה זה נועד להכריע

השאלה הפתוחה היא אם 11–15 השניות תלויות ב**זמן שהשרת למעלה** או במשהו
שקרה במקביל. הרצה אחת כשהשרת שקט מול הרצה אחרי ריסט עונה על זה — ואם שתיהן
מהירות, הנחשד עובר למה שרץ במקביל ולא לגיל התהליך.

    python3 ttfb.py                # 8 כותרים אקראיים
    python3 ttfb.py --n 15
    python3 ttfb.py --public       # דרך nginx, להפריד אותו מהבוט
"""
import argparse, json, os, random, statistics, sys, time
import urllib.request, urllib.error
from urllib.parse import urlsplit, urlunsplit

UA = "zovex-ttfb/1"


def rewrite_origin(url, origin):
    if not origin:
        return url
    p, o = urlsplit(url), urlsplit(origin)
    return urlunsplit((o.scheme, o.netloc, p.path, p.query, p.fragment))


def one_byte(url, offset, timeout=60.0):
    """מחזיר (שניות, גודל הקובץ או None, שגיאה או None).

    Range של בייט אחד: השרת חייב לבצע את מלוא הפתיחה, ואנחנו לא מורידים
    כלום. זה ההבדל בין למדוד את הבעיה לבין להיות הבעיה.
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Range": f"bytes={offset}-{offset}"})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read(1)
            size = None
            cr = r.headers.get("Content-Range", "")
            if "/" in cr:
                tail = cr.rsplit("/", 1)[1]
                if tail.isdigit():
                    size = int(tail)
            return time.time() - t, size, None
    except urllib.error.HTTPError as e:
        return time.time() - t, None, f"HTTP {e.code}"
    except Exception as e:
        return time.time() - t, None, type(e).__name__


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=8, help="כמה כותרים לבדוק")
    ap.add_argument("--public", action="store_true",
                    help="דרך הכתובת הציבורית במקום 127.0.0.1")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    local = "http://127.0.0.1:" + os.environ.get("PORT", "8000")
    origin = None if a.public else local
    src = (local if not a.public else "https://zovex.duckdns.org") + "/content/lite"
    try:
        with urllib.request.urlopen(src, timeout=60) as r:
            catalog = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        sys.exit(f"לא הצלחתי למשוך את הקטלוג: {e}")

    cands = []
    for m in catalog:
        if m.get("is_live"):
            continue
        u = (m.get("video_url") or "").strip()
        if "/stream/" in u and u.startswith("http"):
            cands.append((str(m.get("title") or "?"), rewrite_origin(u, origin)))
    if not cands:
        sys.exit("לא נמצאו כותרים עם קישור /stream ישיר.")

    rnd = random.Random(a.seed or None)
    rnd.shuffle(cands)
    items = cands[:a.n]

    print(f"{len(items)} כותרים · {'דרך nginx' if a.public else 'דרך 127.0.0.1'}")
    print("בקשת בייט אחד לכל מדידה — אפס הורדה, אפס עומס\n")
    print(f"  {'כותר':26} {'פתיחה':>9} {'דילוג':>9}")

    opens, seeks, errs = [], [], []
    for title, url in items:
        t0, size, err0 = one_byte(url, 0, a.timeout)
        if err0:
            errs.append((title, "פתיחה", err0))
            print(f"  {title[:26]:26} {'✗ ' + err0:>9}")
            continue
        opens.append(t0)
        t1 = err1 = None
        if size and size > 2_000_000:
            off = int(size * rnd.uniform(0.3, 0.9))
            t1, _sz, err1 = one_byte(url, off, a.timeout)
            if err1:
                errs.append((title, "דילוג", err1))
            else:
                seeks.append(t1)
        print(f"  {title[:26]:26} {t0:8.2f}ש "
              + (f"{t1:8.2f}ש" if t1 is not None and not err1 else
                 (f"{'✗ ' + err1:>9}" if err1 else f"{'—':>9}")))

    def stat(name, xs):
        if not xs:
            return
        xs = sorted(xs)
        print(f"  {name}: חציון {statistics.median(xs):.2f}ש · "
              f"הגרוע {xs[-1]:.2f}ש · הטוב {xs[0]:.2f}ש")

    print("\n── סיכום ──")
    stat("פתיחה", opens)
    stat("דילוג", seeks)
    if errs:
        print(f"  שגיאות: {len(errs)}")
        for t, kind, e in errs[:6]:
            print(f"    {t[:24]} · {kind} · {e}")

    slow = [x for x in opens if x >= 5]
    print()
    if not opens:
        print("  שום פתיחה לא הצליחה — זו תקלה בפני עצמה, לא איטיות.")
    elif slow:
        print(f"  {len(slow)} מתוך {len(opens)} פתיחות לקחו 5 שניות ומעלה.")
        print("  זה מה שהצופה חווה כ'נתקע' מיד אחרי פליי.")
    else:
        print("  כל הפתיחות מתחת ל-5 שניות — הפתיחה תקינה *ברגע הזה*.")
        print("  אם צופים מתלוננים עכשיו, החשוד אינו מסלול הפתיחה.")


if __name__ == "__main__":
    main()
