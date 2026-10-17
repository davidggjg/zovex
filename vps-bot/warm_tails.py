#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# מחמם מראש את קצוות הקבצים (ראש + moov) של כל הקטלוג.
#
# למה: ב-MP4 שלא עבר faststart טבלת האינדקס (moov) יושבת בסוף הקובץ, וכל נגן
# חייב לקרוא אותה לפני הפריים הראשון. נמדד על השרת הזה: 16MB מתחילת הקובץ
# חזרו ב-0.27 שניות (מהמטמון), ואותם 16MB מהסוף — ב-28 עד 146 שניות. זה כל
# זמן ההפעלה שהצופה מרגיש, והוא נגבה מהצופה *הראשון* של כל פריט.
#
# השרת כבר יודע לשמור את הזנב (_edge_fill), אבל רק כשמישהו ביקש אותו. כאן
# אנחנו מבקשים אותו מראש, בשקט, בשביל כל הקטלוג — ואז כל סרט נפתח מיד, לכל
# הצופים, גם אחרי restart.
#
# איך: מספיק לבקש בייט *אחד* בתוך האזור. זה מפעיל את המילוי ברקע על כל
# האזור. בקשה לטווח המלא הייתה גורמת לשרת למשוך את האזור פעמיים (פעם למילוי
# ופעם לתשובה) — כלומר להכפיל את העומס על טלגרם בלי שום תועלת.
#
# [head_too] מחמם גם את *ראש* הקובץ, לא רק את הזנב. נמדד מול הקובץ החי:
# בקשה קרה ל-2MB הראשונים נמשכה 62 שניות, ואחרי חימום אותם 2MB חזרו ב-0.04
# עד 0.24 שניות — פי 250 עד פי 1500. כלומר גם כשה-moov כבר במטמון, הצופה
# הראשון עוד חיכה לראש. ממילא ה-/stream מטמן גם ראש (EDGE_HEAD) וגם זנב
# (EDGE_TAIL), ובקשת הגודל שאנחנו עושים (bytes=0-0) כבר מפעילה את מילוי
# הראש — רק שקודם דילגנו על פריט ברגע שהזנב שלו היה קיים, ולכן ראש לא
# מחומם נשאר לא מחומם לנצח.
#
# בטוח: קורא בלבד, לא נוגע בקוד ולא בשירות. עוצר לבד אם הדיסק מתמלא. אפשר
# לעצור אותו ב-Ctrl+C בכל רגע ולהריץ שוב — הוא מדלג על מה שכבר מחומם.
#
#   python3 warm_tails.py                 # כל הקטלוג
#   WARM_LIMIT=50 python3 warm_tails.py   # 50 פריטים, לבדיקה
#   WARM_PAUSE=5 python3 warm_tails.py    # לאט יותר, פחות עומס על הבוטים
# ─────────────────────────────────────────────────────────────────────────────
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("WARM_BASE", "http://127.0.0.1:8000")
CACHE = os.environ.get("WARM_CACHE", "/opt/zovex-bot/data/edge_cache")
MIN_FREE_GB = float(os.environ.get("WARM_MIN_FREE_GB", "5"))
PAUSE = float(os.environ.get("WARM_PAUSE", "2"))
FILL_TIMEOUT = float(os.environ.get("WARM_FILL_TIMEOUT", "240"))
LIMIT = int(os.environ.get("WARM_LIMIT", "0"))
# כמה פעמים לנסות את /ping לפני ויתור (5 שניות בין ניסיונות).
WAIT_FOR_SERVER = int(os.environ.get("WARM_WAIT_FOR_SERVER", "60"))
# כשלים רצופים שאחריהם עוצרים — סימן שהשרת נפל, לא שהפריט בעייתי.
FAIL_STREAK = int(os.environ.get("WARM_FAIL_STREAK", "10"))
# חייב להתאים ל-STREAM_EDGE_HEAD/TAIL של השרת, אחרת נדלג על פריטים לא נכון.
EDGE_HEAD = int(os.environ.get("STREAM_EDGE_HEAD", str(2 * 1024 * 1024)))
EDGE_TAIL = int(os.environ.get("STREAM_EDGE_TAIL", str(12 * 1024 * 1024)))

STREAM_RE = re.compile(r"/stream/(-?\d+)/(\d+)(\?[^\"'\s<>\\]*)?")


def get(path, rng=None, timeout=60):
    req = urllib.request.Request(BASE + path)
    if rng:
        req.add_header("Range", rng)
    return urllib.request.urlopen(req, timeout=timeout)


def free_gb():
    try:
        return shutil.disk_usage(CACHE).free / 1024 ** 3
    except OSError:
        return 0.0


def catalog():
    """כל (chat, msg, query) הייחודיים מהקטלוג, בסדר שבו הם מופיעים."""
    try:
        body = get("/content/lite", timeout=120).read().decode("utf-8", "replace")
    except Exception as e:
        sys.exit(f"לא הצלחתי לקרוא את הקטלוג מ-{BASE}/content/lite: {e}")
    seen, out = set(), []
    for chat, msg, qs in STREAM_RE.findall(body):
        if (chat, msg) in seen:
            continue
        seen.add((chat, msg))
        out.append((chat, msg, qs or ""))
    return out


def region_path(chat, msg, which):
    return os.path.join(CACHE, f"{chat}_{msg}.{which}")


def size_of(path):
    """גודל הקובץ, מתוך Content-Range של בקשה לבייט אחד."""
    with get(path, "bytes=0-0", timeout=90) as r:
        cr = r.headers.get("Content-Range", "")
    return int(cr.rsplit("/", 1)[1]) if "/" in cr else 0


def main():
    if not os.path.isdir(CACHE):
        sys.exit(f"תיקיית המטמון לא נמצאה: {CACHE}")
    # בדיקה מקדימה: אין טעם להתחיל אם השרת לא מגיש. אחרי restart הוא
    # יכול להיות דקות ארוכות בלי להאזין — ההפעלה חוסמת עד שהלקוח הראשי
    # מתחבר — ובלי הבדיקה הזו הריצה מתדרדרת לאלפי ניסיונות ריקים.
    for attempt in range(WAIT_FOR_SERVER):
        try:
            get("/ping", timeout=5).read()
            break
        except Exception as e:
            if attempt == 0:
                print(f"השרת עוד לא מגיש ({type(e).__name__}) — ממתין...")
            time.sleep(5)
    else:
        sys.exit(f"השרת ב-{BASE} לא ענה — לא מתחיל. "
                 f"בדוק: systemctl status zovex-bot")

    items = catalog()
    if LIMIT:
        items = items[:LIMIT]
    print(f"קטלוג: {len(items)} פריטים   מטמון: {CACHE}   פנוי: {free_gb():.1f}GB")
    print(f"ראש: {EDGE_HEAD // 1024 // 1024}MB · זנב: {EDGE_TAIL // 1024 // 1024}MB   השהיה בין פריטים: {PAUSE}s\n")

    done = warmed = skipped = failed = 0
    streak = 0                      # כשלים רצופים
    t_start = time.time()
    try:
        for chat, msg, qs in items:
            done += 1
            if free_gb() < MIN_FREE_GB:
                print(f"\n⚠️  נשארו פחות מ-{MIN_FREE_GB}GB פנויים — עוצר.")
                break
            path = f"/stream/{chat}/{msg}{qs}"
            hp = region_path(chat, msg, "head")
            tp = region_path(chat, msg, "tail")
            if os.path.exists(hp) and os.path.exists(tp):
                skipped += 1
                continue
            try:
                # bytes=0-0 מחזיר את הגודל *וגם* מפעיל את מילוי הראש.
                sz = size_of(path)
            except Exception as e:
                failed += 1
                print(f"[{done}/{len(items)}] {chat}/{msg}  גודל נכשל: "
                      f"{type(e).__name__}")
                streak += 1
                if streak >= FAIL_STREAK:
                    print(f"\n⚠️  {streak} כשלים רצופים — השרת כנראה לא מגיש. עוצר.")
                    break
                time.sleep(PAUSE)       # גם כישלון חייב להאט
                continue
            if sz <= EDGE_HEAD + EDGE_TAIL:
                skipped += 1          # קטן מדי — השרת לא מטמן קצוות כאלה
                continue

            # שני האזורים, בזה אחר זה. הראש כבר בדרך מבקשת הגודל, ולכן
            # ה"טריגר" שלו הוא בדיוק הבקשה הזו — אין צורך בשנייה.
            t0 = time.time()
            ok = True
            for which, want, trigger in (
                    ("head", hp, None),
                    ("tail", tp, f"bytes={sz - 1}-{sz - 1}")):
                if os.path.exists(want):
                    continue
                if trigger:
                    try:
                        with get(path, trigger, timeout=120) as r:
                            r.read()
                    except Exception as e:
                        ok = False
                        print(f"[{done}/{len(items)}] {chat}/{msg}  טריגר "
                              f"{which} נכשל: {type(e).__name__}")
                        break
                # ממתינים שהמילוי יסתיים, כדי לא להציף את הבוטים בעשרות
                # מילויים מקבילים. זה גם מה שמקצב אותנו לפי מהירות טלגרם.
                deadline = time.time() + FILL_TIMEOUT
                while time.time() < deadline and not os.path.exists(want):
                    time.sleep(2)
                if not os.path.exists(want):
                    ok = False
                    print(f"[{done}/{len(items)}] {chat}/{msg}  ⏱️  {which} לא "
                          f"הסתיים תוך {FILL_TIMEOUT:.0f}s")
                    break

            if ok:
                warmed += 1
                streak = 0
                print(f"[{done}/{len(items)}] {chat}/{msg}  ✅ "
                      f"{time.time() - t0:.0f}s   (חומם {warmed})")
            else:
                failed += 1
                streak += 1
                if streak >= FAIL_STREAK:
                    print(f"\n⚠️  {streak} כשלים רצופים — השרת כנראה לא מגיש. עוצר.")
                    break
            time.sleep(PAUSE)
    except KeyboardInterrupt:
        print("\nנעצר ידנית.")

    mins = (time.time() - t_start) / 60
    print(f"\nסיכום: חוממו {warmed} · דולגו {skipped} · נכשלו {failed} · "
          f"מתוך {done} שנבדקו, ב-{mins:.0f} דקות")
    print(f"פנוי בדיסק: {free_gb():.1f}GB")
    if failed:
        print("כשלונות הם בדרך כלל בוטים חנוקים — הרצה חוזרת תתפוס אותם.")


if __name__ == "__main__":
    main()
