#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מחזיק צופה קבוע על ערוץ אחד אצל הספק.

## אישור

בעל המערכת אישר במפורש, אחרי שדוד פנה אליו. הוא אמר שאצלו זה מסובך בגלל
הממיר, וביקש שנעשה את זה מהצד שלנו. **בלי האישור הזה אין לזה מקום** —
זה מייצר נתוני צפייה במערכת של מישהו אחר.

## למה ערוץ אחד ולא כולם

נמדד כאן ב-06/09: משיכה מקבילה מהספק שרפה את חריצי החיבור של המנוי, וכל
הערוצים החזירו `200` עם פלייליסט ריק — `TARGETDURATION:0`, אפס מקטעים.
זה נראה בדיוק כמו "הספק נפל", ולקח זמן להבין שזה אנחנו.

לכן: **חיבור אחד בלבד, לערוץ אחד**, ועם בלם שעוצר לגמרי כשהספק נראה חנוק.
צופה מזויף שמפיל את הערוץ לצופים האמיתיים מפספס את כל הנקודה.

## איך זה נראה לספק

כמו נגן: מושך את הפלייליסט, ואז את המקטעים החדשים בקצב אמת. ההבדל היחיד
הוא שלא מורידים את כל המקטע אלא רק את תחילתו (`Range`) — מספיק כדי שתירשם
בקשה לכל מקטע, בלי לשרוף ג'יגות.

**לא ידוע בוודאות מה הפאנל של הספק סופר.** אם מסתבר שהוא סופר בייטים ולא
בקשות, `--full` מוריד מקטעים שלמים. זה עולה בערך פי 40 בתעבורה, אז זו לא
ברירת המחדל.

    python3 keepalive_channel.py --check          # בודק ויוצא, בלי לולאה
    python3 keepalive_channel.py                  # רץ עד שעוצרים אותו
    python3 keepalive_channel.py --channel 12255
    python3 keepalive_channel.py --full           # מקטעים שלמים

מיועד לרוץ כשירות systemd. ראה keepalive-sport5live.service.
"""
import argparse, json, re, subprocess, sys, time
import urllib.error, urllib.parse, urllib.request

LOCAL = "http://127.0.0.1:8000"
UA = "VLC/3.0.20 LibVLC/3.0.20"          # נגן אמיתי, לא סקריפט

# כמה מכל מקטע למשוך. 256KB מספיק כדי שהבקשה תיראה אמיתית ותירשם, ועדיין
# פי ~40 פחות תעבורה ממקטע מלא.
PARTIAL_BYTES = 256 * 1024

# בלם: אחרי כך וכך תקלות רצופות עוצרים לזמן ארוך במקום להמשיך לדפוק.
FAIL_LIMIT = 5
COOLDOWN = 900                            # רבע שעה


def provider_base():
    """מוציא את כתובת הספק מהקטלוג ולא מקבוע בקוד — המפתח בכתובת מתחלף."""
    raw = subprocess.run(["curl", "-sS", "--noproxy", "127.0.0.1",
                          "--max-time", "90", f"{LOCAL}/movies.json"],
                         capture_output=True).stdout
    try:
        cat = json.loads(raw)
    except Exception as e:
        sys.exit(f"❌ לא הצלחתי לקרוא את הקטלוג: {e}")
    for m in cat:
        u = str(m.get("video_url", ""))
        if "siauliairsavlt" in u and "/iptv/" in u:
            tail = u.split("/hls-relay/", 1)[1]
            if tail.startswith("_fix/"):
                tail = tail[5:]
            parts = tail.rstrip("/").split("/")
            # host/iptv/key — הספק מגיש ב-http; https אינו נענה כלל אצלו.
            return "http://" + "/".join(parts[:-1])
    sys.exit("❌ לא נמצא ספק ה-pw בקטלוג")


def get(url, timeout=25, rng=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    if rng:
        req.add_header("Range", f"bytes=0-{rng - 1}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_playlist(text, base):
    """מחזיר (מקטעים, משך יעד). מקטע הוא כתובת מלאה."""
    segs, target = [], 6.0
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-TARGETDURATION:"):
            try:
                target = float(line.split(":", 1)[1])
            except ValueError:
                pass
        elif line and not line.startswith("#"):
            segs.append(urllib.parse.urljoin(base, line))
    return segs, target


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="12255",
                    help="מספר הערוץ אצל הספק. ברירת מחדל: ספורט 5 לייב")
    ap.add_argument("--full", action="store_true",
                    help="למשוך מקטעים שלמים (פי ~40 תעבורה)")
    ap.add_argument("--check", action="store_true",
                    help="בדיקה אחת ויציאה, בלי לולאה")
    a = ap.parse_args()

    base = provider_base()
    url = f"{base}/{a.channel}/index.m3u8"
    rng = None if a.full else PARTIAL_BYTES
    print(f"ערוץ {a.channel} · {'מקטעים שלמים' if a.full else f'{PARTIAL_BYTES // 1024}KB למקטע'}")
    print(f"מקור: {url}\n", flush=True)

    seen = set()
    fails = 0
    n_seg = 0
    started = time.time()
    last_report = 0.0

    while True:
        try:
            body = get(url).decode("utf-8", "replace")
            if not body.lstrip().startswith("#EXTM3U"):
                raise ValueError("לא playlist")
            segs, target = parse_playlist(body, url)
            if not segs:
                # 200 עם אפס מקטעים = הספק נפל, או שאנחנו חנוקים. שניהם
                # אומרים לעצור ולא להמשיך לדפוק.
                raise ValueError("playlist ריק (TARGETDURATION:0)")

            fails = 0
            fresh = [s for s in segs if s not in seen]
            for s in fresh:
                try:
                    get(s, timeout=30, rng=rng)
                    n_seg += 1
                except Exception:
                    pass                      # מקטע בודד שנפל אינו תקלה
                seen.add(s)
            # שומרים רק את החלון האחרון, אחרת הזיכרון גדל בלי גבול
            if len(seen) > 400:
                seen = set(segs)

            if a.check:
                print(f"✓ {len(segs)} מקטעים · target {target:.0f}ש · "
                      f"נמשכו {n_seg}")
                return

            now = time.time()
            if now - last_report > 600:       # דיווח כל 10 דקות, לא לכל מקטע
                mb = n_seg * (PARTIAL_BYTES if rng else 2_000_000) / 1e6
                print(f"[{time.strftime('%H:%M')}] פעיל "
                      f"{(now - started) / 3600:.1f}ש · {n_seg} מקטעים · "
                      f"~{mb:.0f}MB", flush=True)
                last_report = now

            # קצב אמת: הנגן מבקש רשימה חדשה בערך כל אורך-מקטע.
            time.sleep(max(2.0, target))

        except KeyboardInterrupt:
            print("\nנעצר.")
            return
        except Exception as e:
            fails += 1
            print(f"⚠ {e} (תקלה {fails}/{FAIL_LIMIT})", flush=True)
            if a.check:
                sys.exit(1)
            if fails >= FAIL_LIMIT:
                print(f"   הספק לא מגיב — הפוגה של {COOLDOWN // 60} דקות. "
                      "לא ממשיכים לדפוק עליו.", flush=True)
                time.sleep(COOLDOWN)
                fails = 0
            else:
                time.sleep(10 * fails)


if __name__ == "__main__":
    main()
