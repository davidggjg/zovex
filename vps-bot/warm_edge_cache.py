#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מחמם מראש את מטמון-הקצה של הסרטים.

הבעיה שזה פותר: הצופה *הראשון* בכל סרט ממתין ~100 שניות — הוא זה שממלא
את המטמון עבור כל השאר (נמדד: צפייה ראשונה 98ש', שנייה 1.5ש'). כאן השרת
עושה את זה לבד, מראש, בקצב אטי — וכך אף צופה לא משלם את המחיר.

איך זה עובד: מספיק לבקש כמה קילובייטים מקצה הקובץ. השרת מזהה שהבקשה
נמצאת באזור-קצה, ומדליק לבד מילוי מלא ברקע (_edge_fill). אנחנו לא מורידים
כלום בעצמנו — רק "נוגעים" ומרפים.

עדיפות: מהחדש לישן — התוכן החדש הוא הנצפה ביותר.

הרצה:
    python3 warm_edge_cache.py                # הכל, בקצב אטי (ברקע)
    python3 warm_edge_cache.py --limit 300    # רק 300 החדשים
    python3 warm_edge_cache.py --delay 8      # עדין יותר על טלגרם
    python3 warm_edge_cache.py --heads-only   # בלי הזנבות (חוסך מקום)
"""
import argparse, json, sys, time, urllib.request, urllib.error

BASE = "http://127.0.0.1:8000"
SITE = "https://zovex.duckdns.org"


def get(url, headers=None, timeout=90, method="GET"):
    req = urllib.request.Request(url, headers=headers or {}, method=method)
    return urllib.request.urlopen(req, timeout=timeout)


def load_catalog():
    """מושך את הקטלוג *עם* הקישורים החתומים (exp+sig נוצרים בכל בקשה)."""
    with get(f"{SITE}/content", {"User-Agent": "zovex-warmer"}) as r:
        return json.loads(r.read().decode("utf-8"))


def touch(url, start, end):
    """בקשת-טווח זעירה. מחזיר (ok, שניות). לא מוריד את התוכן במלואו."""
    t0 = time.time()
    try:
        with get(url, {"Referer": SITE + "/", "User-Agent": "zovex-warmer",
                       "Range": f"bytes={start}-{end}"}) as r:
            r.read(65536)
        return True, time.time() - t0
    except Exception as e:
        return False, time.time() - t0


def file_size(url):
    """גודל הקובץ מתוך Content-Range של בקשה זעירה."""
    try:
        with get(url, {"Referer": SITE + "/", "User-Agent": "zovex-warmer",
                       "Range": "bytes=0-1023"}, timeout=120) as r:
            cr = r.headers.get("Content-Range", "")
            r.read(1024)
            if "/" in cr:
                return int(cr.rsplit("/", 1)[1])
    except Exception:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="כמה פריטים (0=הכל)")
    ap.add_argument("--delay", type=float, default=5.0, help="שניות בין פריטים")
    ap.add_argument("--heads-only", action="store_true", help="בלי זנבות")
    a = ap.parse_args()

    try:
        cat = load_catalog()
    except Exception as e:
        print("שליפת הקטלוג נכשלה:", e, file=sys.stderr)
        return 1

    items = [e for e in cat
             if not e.get("is_live") and "/stream/" in str(e.get("video_url") or "")]
    items.sort(key=lambda e: str(e.get("created_date") or ""), reverse=True)
    if a.limit:
        items = items[:a.limit]

    print(f"מחמם {len(items)} פריטים (מהחדש לישן), {a.delay}ש' בין אחד לשני.")
    print("זה רץ לאט בכוונה — כדי לא להעמיס על טלגרם.\n", flush=True)

    warmed = slow = failed = 0
    for i, e in enumerate(items, 1):
        url = e["video_url"]
        title = (e.get("title") or "")[:34]

        ok, secs = touch(url, 0, 65535)          # ראש — מדליק מילוי ברקע
        if not ok:
            failed += 1
            print(f"[{i}/{len(items)}] ✗ {title}", flush=True)
            time.sleep(a.delay)
            continue
        if secs > 5:
            slow += 1                            # היה קר — עכשיו מתמלא
        else:
            warmed += 1                          # כבר היה חם

        if not a.heads_only:
            size = file_size(url)
            if size and size > 4 * 1024 * 1024:
                touch(url, size - 65536, size - 1)   # זנב (אינדקס ה-moov)

        if i % 25 == 0 or secs > 5:
            print(f"[{i}/{len(items)}] {title} — {secs:.1f}ש'"
                  f"   (חמים {warmed} · קוררו {slow} · כשלו {failed})", flush=True)
        time.sleep(a.delay)

    print(f"\nסיום: {warmed} כבר היו חמים, {slow} מולאו עכשיו, {failed} נכשלו.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
