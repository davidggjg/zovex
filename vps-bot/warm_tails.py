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
# [moov_aware] מחמם רק את מה שהנגן באמת קורא.
#
# נמדד על 29 פריטים פרושים על הקטלוג (moov_probe.py): ב-21 מהם (72%)
# טבלת האינדקס יושבת ב*התחלה* ולא בסוף — הקבצים כבר עברו faststart.
# עבורם 12MB הזנב הם בזבוז מוחלט: שום נגן לא קורא משם לעולם, והמחמם
# הכריח את השרת למשוך אותם בכוח על כל פריט.
#
# ובאותם קבצים ה-moov מגיע עד 5.46MB, בעוד הראש שנטמן הוא 2MB — כלומר
# דווקא מה שצריך נחתך באמצע ונמשך קר שוב ושוב.
#
# לכן המחמם מאתר קודם את ה-moov (שלוש קריאות של 16 בתים, ראה find_moov),
# ורק אז מחליט: ראש תמיד, זנב רק כשה-moov באמת בסוף.
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
# [budget] למה לא כל הקטלוג: נמדד 18,292 פריטים, 14MB לפריט (ראש+זנב) —
# כלומר 256GB מטמון ו-17 יום ריצה. התקרה של מטמון הקצה קטנה בהרבה, ולכן
# ריצה כזו הייתה מחממת פריטים שהפינוי מוחק מאחוריה. חימום של דברים שאף
# אחד לא פתח גם ממילא מיותר: ה-/stream מטמן לבד כל מה שנצפה, והדבר היחיד
# שהמחמם קונה הוא ביטול ההמתנה של הצופה *הראשון*.
#
# לכן עובדים לפי תקציב, על *ראש* הקטלוג. סדר הקטלוג הוא סדר התצוגה במסך
# הבית, כלומר בדיוק הסדר שבו אנשים לוחצים — שם מרוכזות הצפיות הראשונות.
#
#   python3 warm_tails.py                 # ראש הקטלוג עד התקציב
#   WARM_LIMIT=50 python3 warm_tails.py   # 50 פריטים, לבדיקה
#   WARM_PAUSE=5 python3 warm_tails.py    # לאט יותר, פחות עומס על הבוטים
# ─────────────────────────────────────────────────────────────────────────────
import os
import re
import shutil
import struct
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("WARM_BASE", "http://127.0.0.1:8000")
CACHE = os.environ.get("WARM_CACHE", "/opt/zovex-bot/data/edge_cache")
MIN_FREE_GB = float(os.environ.get("WARM_MIN_FREE_GB", "5"))
PAUSE = float(os.environ.get("WARM_PAUSE", "2"))
# נמדד: מילוי אזור שהצליח לקח עד 184 שניות (14MB בכ-110KB/s — זו מהירות
# המשיכה מטלגרם בקר). תקרה של 240 שניות הפילה פריטים שהיו בדרך.
FILL_TIMEOUT = float(os.environ.get("WARM_FILL_TIMEOUT", "600"))
LIMIT = int(os.environ.get("WARM_LIMIT", "0"))
# תקרת הנפח שהמחמם מוכן לתפוס במטמון. חייבת להיות קטנה מ-
# STREAM_EDGE_CACHE_MAX של השרת, אחרת הפינוי מוחק את מה שחיממנו.
BUDGET_GB = float(os.environ.get("WARM_BUDGET_GB", "15"))
# כמה פעמים לנסות את /ping לפני ויתור (5 שניות בין ניסיונות).
WAIT_FOR_SERVER = int(os.environ.get("WARM_WAIT_FOR_SERVER", "60"))
# כשלים רצופים שאחריהם עוצרים — סימן שהשרת נפל, לא שהפריט בעייתי.
FAIL_STREAK = int(os.environ.get("WARM_FAIL_STREAK", "10"))
# חייב להתאים ל-STREAM_EDGE_HEAD/TAIL של השרת, אחרת נדלג על פריטים לא נכון.
EDGE_HEAD = int(os.environ.get("STREAM_EDGE_HEAD", str(2 * 1024 * 1024)))
EDGE_TAIL = int(os.environ.get("STREAM_EDGE_TAIL", str(12 * 1024 * 1024)))

STREAM_RE = re.compile(r"/stream/(-?\d+)/(\d+)(\?[^\"'\s<>\\]*)?")

# תקרת קפיצות באיתור ה-moov. קובץ תקין מגיע אליו תוך 2-4 קופסאות; התקרה
# מגינה מקובץ פגום שמדווח גודל 0.
MAX_HOPS = 12


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


def cache_gb():
    """נפח המטמון כרגע, בגיגה."""
    total = 0
    try:
        for e in os.scandir(CACHE):
            try:
                if e.is_file():
                    total += e.stat().st_size
            except OSError:
                continue            # נעלם בדיוק עכשיו
    except OSError:
        return 0.0
    return total / 1024 ** 3


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


def find_moov(path):
    """(היסט, אורך, בסוף?) של ה-moov, או None אם אינו MP4 או שלא נמצא.

    MP4 הוא שרשרת קופסאות שכל אחת פותחת ב-8 בתים: גודל וסוג. לכן קריאה
    של 16 בתים בתחילת קופסה מספיקה כדי לקפוץ לבאה — שלוש קריאות זעירות
    במקום לנחש חלון מהסוף.
    """
    off, total, hops = 0, None, 0
    while hops < MAX_HOPS:
        hops += 1
        try:
            with get(path, f"bytes={off}-{off + 15}", timeout=90) as r:
                head = r.read()
                cr = r.headers.get("Content-Range", "")
        except Exception:
            return None
        if total is None:
            total = int(cr.rsplit("/", 1)[1]) if "/" in cr else 0
        if len(head) < 8:
            return None
        size = struct.unpack_from(">I", head, 0)[0]
        typ = head[4:8]
        hdr = 8
        if size == 1:                       # גודל 64 ביט
            if len(head) < 16:
                return None
            size = struct.unpack_from(">Q", head, 8)[0]
            hdr = 16
        elif size == 0:                     # "עד סוף הקובץ"
            size = total - off
        if typ == b"moov":
            return off, size, (off + size == total)
        if size < hdr:
            return None
        off += size
        if total and off >= total:
            return None
    return None


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
    per_item = (EDGE_HEAD + EDGE_TAIL) / 1024 ** 3
    used = cache_gb()
    room = max(0.0, BUDGET_GB - used)
    print(f"ראש: {EDGE_HEAD // 1024 // 1024}MB · זנב: "
          f"{EDGE_TAIL // 1024 // 1024}MB   השהיה בין פריטים: {PAUSE}s")
    print(f"תקציב: {BUDGET_GB:.0f}GB   תפוס: {used:.1f}GB   "
          f"מקום ל-{int(room / per_item)} פריטים נוספים")
    print(f"קצב נמדד: כ-2 דקות לפריט → "
          f"כ-{int(room / per_item) * 2 / 60:.0f} שעות עד מילוי התקציב\n")

    done = warmed = skipped = failed = 0
    moov_mb = moov_seen = 0.0        # לסיכום: כמה moov באמת שוקל
    saved_mb = 0.0                   # זנבות שלא נמשכו כי ה-moov בהתחלה
    streak = 0                      # כשלים רצופים
    t_start = time.time()
    try:
        for chat, msg, qs in items:
            done += 1
            if cache_gb() >= BUDGET_GB:
                print(f"\n✅ התקציב ({BUDGET_GB:.0f}GB) מלא — עוצר. "
                      f"ראש הקטלוג מחומם, וזה מה שנצפה בפועל.")
                break
            if free_gb() < MIN_FREE_GB:
                print(f"\n⚠️  נשארו פחות מ-{MIN_FREE_GB}GB פנויים — עוצר.")
                break
            path = f"/stream/{chat}/{msg}{qs}"
            hp = region_path(chat, msg, "head")
            tp = region_path(chat, msg, "tail")
            # דילוג מהיר: ראש קיים *וגם* זנב קיים — בוודאות אין מה
            # לעשות. פריט faststart שחומם בגרסה הזו לא ייצור קובץ זנב,
            # ולכן הוא לא ייתפס כאן; find_moov למטה יגלה שאין צורך בו,
            # וזו קריאה אחת זולה ולא 12MB.
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

            # ── מה באמת צריך לחמם ────────────────────────────────────
            #
            # איתור ה-moov עולה שלוש קריאות של 16 בתים, ומונע משיכה של
            # 12MB שאיש לא יקרא. ב-72% מהקטלוג ה-moov בהתחלה, ושם הזנב
            # מיותר לחלוטין.
            #
            # כשלא מצאנו moov (לא MP4 — mkv, avi), חוזרים להתנהגות
            # הישנה: שני הקצוות. עדיף לשלם מיותר מאשר לא לחמם בכלל.
            mv = find_moov(path)
            need_tail = True
            if mv is not None:
                _, mv_len, mv_at_end = mv
                need_tail = mv_at_end
                moov_mb += mv_len / 1024 / 1024
                moov_seen += 1
                if not mv_at_end:
                    saved_mb += EDGE_TAIL / 1024 / 1024

            t0 = time.time()
            ok = True
            plan = [("head", hp, None)]
            if need_tail:
                plan.append(("tail", tp, f"bytes={sz - 1}-{sz - 1}"))
            for which, want, trigger in plan:
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
    if moov_seen:
        print(f"moov: ממוצע {moov_mb / moov_seen:.2f}MB על {int(moov_seen)} פריטים")
    if saved_mb:
        print(f"נחסכו {saved_mb / 1024:.1f}GB משיכה — זנבות שאיש לא היה קורא")
    print(f"פנוי בדיסק: {free_gb():.1f}GB")
    if failed:
        print("כשלונות הם בדרך כלל בוטים חנוקים — הרצה חוזרת תתפוס אותם.")


if __name__ == "__main__":
    main()
