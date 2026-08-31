#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
משחזר "הסרט נתקע באמצע" ומתעד את הרגע המדויק שבו זה קורה.

למה ניסוי ולא עוד קריאת קוד: עברתי על כל קבועי הזמן בשרת ואף אחד מהם לא
יושב על 20–40 דקות. חתימת הקישור תקפה 24 שעות, מטמון ההודעות 15 דקות,
ה-session נסגר אחרי 90 שניות בלי שימוש. כלומר התשובה אינה בקוד עצמו אלא
במה שקורה בפועל לאורך צפייה ארוכה — ואת זה חייבים למדוד.

מה זה עושה: מושך סרט אמיתי דרך /stream, *בקצב של נגן* ולא במלוא המהירות
(נגן צורך בערך את קצב הסיביות של הווידאו; משיכה מהירה יוצרת עומס אחר לגמרי
ולא תשחזר את התקלה). מדווח כל 15 שניות כמה התקבל, ואם ההזרמה נקטעת הוא
רושם בדיוק מתי, אחרי כמה בייטים, ומה החריגה.

    python3 stream_probe.py                    # סרט אקראי, שעה
    python3 stream_probe.py --minutes 90
    python3 stream_probe.py --mbps 8           # קצב צריכה מדומה
    python3 stream_probe.py --url "https://…"  # פריט מסוים
"""
import argparse, json, pathlib, random, subprocess, sys, time
import urllib.request, urllib.error

DATA = pathlib.Path("/opt/zovex-bot/data")
CONTENT = DATA / "content.json"
LOG = pathlib.Path("/opt/zovex-bot/stream_probe.log")
UA = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"


def say(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def dump_server_log(since_epoch):
    """יומן השרת מרגע תחילת הניסוי. בלי זה יש לנו רק את צד הלקוח — רואים
    שנפל אבל לא למה. השורות האלה הן הצד השני של אותו רגע."""
    since = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(since_epoch - 30))
    try:
        out = subprocess.run(
            ["journalctl", "-u", "zovex-bot", "--since", since, "--no-pager"],
            capture_output=True, text=True, timeout=60).stdout
    except Exception as e:
        say(f"(לא ניתן לקרוא את יומן השרת: {e})")
        return
    keep = [l for l in out.splitlines() if any(
        k in l for k in ("חלון", "קריאה-מראש", "subrange", "band", "רצועות",
                         "session", "Session", "flood", "Flood", "choke",
                         "נחנק", "Error", "error", "Timeout", "timeout",
                         "Traceback", "Exception", "WARNING", "ERROR"))]
    say(f"── יומן השרת מאז תחילת הניסוי ({len(keep)} שורות רלוונטיות) ──")
    for l in keep[-60:]:
        say("   " + l[:190])
    if not keep:
        say("   (היומן שקט לגמרי — כלומר השרת לא חשב שקרתה תקלה)")


def load_catalog():
    """חייבים למשוך מ-/movies.json ולא לקרוא את content.json.

    content.json שומר "%BASE%/stream/..." כמציין מקום; השרת מחליף אותו
    בכתובת האמיתית *ומוסיף את החתימה* רק כשהוא מגיש את הקטלוג ללקוח.
    קריאה ישירה מהקובץ מחזירה מחרוזת שאינה URL, וכל ניסוי מת מיד."""
    last = None
    for base in ("http://127.0.0.1:8000", "https://zovex.duckdns.org"):
        try:
            req = urllib.request.Request(base + "/movies.json",
                                         headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = f"{base}: {type(e).__name__}: {e}"
            say(f"(לא ניתן למשוך קטלוג מ-{base} — {type(e).__name__})")
    sys.exit(f"לא ניתן למשוך את movies.json. אחרון: {last}")


def pick_url():
    data = load_catalog()
    items = data if isinstance(data, list) else data.get("movies", [])
    # סרטים בלבד ולא פרקים: פרק קצר ייגמר לפני שנגיע ל-20 דקות הקריטיות
    pool = [m for m in items
            if "/stream/" in (m.get("video_url") or "")
            and not m.get("series_name")
            and m.get("category") not in ("שידורים חיים",)]
    if not pool:
        sys.exit("לא נמצא פריט מתאים ב-content.json")
    random.shuffle(pool)
    for m in pool:
        u = m.get("video_url") or ""
        if u.startswith("http"):
            return m.get("title") or "?", u
    sys.exit("כל הכתובות בקטלוג אינן http — משהו שבור בהגשת הקטלוג")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=60)
    ap.add_argument("--mbps", type=float, default=6.0,
                    help="קצב צריכה מדומה, כמו נגן אמיתי")
    ap.add_argument("--url")
    ap.add_argument("--report", type=int, default=15, help="שניות בין דיווחים")
    a = ap.parse_args()

    title, url = ("ידני", a.url) if a.url else pick_url()
    budget = a.minutes * 60
    rate = a.mbps * 1024 * 1024 / 8          # בייט לשנייה

    say("=" * 62)
    say(f"ניסוי: {title}")
    say(f"קצב מדומה {a.mbps} Mbps · עד {a.minutes} דקות · דיווח כל {a.report}ש")
    say(f"URL: {url[:110]}")

    if not url.startswith("http"):
        say(f"⛔ הכתובת אינה URL תקין: {url[:60]}")
        sys.exit(1)

    t0 = time.time()
    got = 0
    last_report = t0
    clen = None
    status = None
    try:
        # נבנה כאן ולא למעלה: חריגה בבניית הבקשה הייתה עוקפת את ה-try
        # ואת ה-finally, והניסוי היה מת בלי להשאיר ולו שורת הסבר אחת.
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Referer": "https://zovex.duckdns.org/",
            "Range": "bytes=0-",        # בדיוק כמו נגן: מההתחלה והלאה
        })
        r = urllib.request.urlopen(req, timeout=90)
        status = r.status
        clen = r.headers.get("Content-Length")
        crange = r.headers.get("Content-Range")
        say(f"נפתח: HTTP {status} · Content-Length {clen} · Range {crange}")
        say(f"TTFB {time.time()-t0:.2f}ש")

        while True:
            now = time.time()
            if now - t0 > budget:
                say(f"✅ הגיע לסוף הזמן שהוקצב בלי תקלה. התקבלו {got/1048576:.1f}MB")
                break
            # מווסת: לא מושכים מהר יותר ממה שנגן היה צורך
            allowed = int((now - t0) * rate)
            if got >= allowed:
                time.sleep(0.25)
                continue
            chunk = r.read(min(262144, allowed - got))
            if not chunk:
                el = now - t0
                say(f"⛔ ההזרמה נגמרה מוקדם אחרי {el/60:.1f} דקות "
                    f"({el:.0f}ש), {got/1048576:.1f}MB מתוך {clen}")
                say("   הגוף נסגר בלי שגיאה — כלומר השרת סיים את התשובה.")
                break
            got += len(chunk)
            if now - last_report >= a.report:
                el = now - t0
                say(f"  {el/60:5.1f} דק' · {got/1048576:8.1f}MB · "
                    f"ממוצע {got/el/131072:.2f} Mbps")
                last_report = now
    except urllib.error.HTTPError as e:
        say(f"⛔ HTTP {e.code} אחרי {(time.time()-t0)/60:.1f} דקות, {got/1048576:.1f}MB")
    except Exception as e:
        el = time.time() - t0
        say(f"⛔ נקטע אחרי {el/60:.1f} דקות ({el:.0f}ש), {got/1048576:.1f}MB")
        say(f"   חריגה: {type(e).__name__}: {e}")
    finally:
        el = time.time() - t0
        say(f"סיום. סה\"כ {got/1048576:.1f}MB ב-{el/60:.1f} דקות")
        # שולפים את יומן השרת רק כשבאמת נפל — בריצה מוצלחת זה סתם רעש
        if el < budget - 5:
            dump_server_log(t0)
        say("")


if __name__ == "__main__":
    main()
