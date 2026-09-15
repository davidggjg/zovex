#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vod_watch — מדמה צופים אמיתיים בסרטים/סדרות ותופס תקיעות.

למה לא פשוט להוריד ולמדוד מהירות: הורדה במלוא הקצב מודדת רוחב פס, לא חוויה.
נגן אמיתי ממלא באפר וצורך ממנו בקצב הווידאו; תקיעה היא הרגע שבו הבאפר
מתרוקן. הכלי מדמה בדיוק את זה — ולכן הוא גם צורך כמו צופה אחד ולא כמו הורדה.

מה נמדד לכל כותר:
  • זמן התחלה (TTFB) — כמה זמן עד הבייט הראשון. זה מה שהמשתמש קורא "נטען לאט".
  • תקיעות — כמה פעמים הבאפר התרוקן, לכמה זמן, והארוכה ביותר.
  • קצב אספקה בפועל מול הקצב הדרוש.
  • שגיאות באמצע הזרימה (נתק, 403 של חתימה שפגה, 5xx).
  • קפיצה בזמן — Range מאמצע הקובץ, כמו משתמש שמדלג. נמדד בנפרד.

ברירת המחדל פונה ל-127.0.0.1:8000, כלומר בודקת את החוליה טלגרם→שרת בלי
לצרוך רוחב פס חיצוני ובלי להפריע לצופים.

    python3 vod_watch.py --minutes 40 --streams 3
    python3 vod_watch.py --minutes 5 --streams 2 --bitrate 2.5
    python3 vod_watch.py --minutes 40 --streams 3 --public     # דרך הכתובת הציבורית
"""
import argparse, json, os, random, re, signal, sys, threading, time
import urllib.request, urllib.error
from urllib.parse import urlsplit, urlunsplit
from concurrent.futures import ThreadPoolExecutor

STOP = threading.Event()


def _classify(e):
    """שם קריא לשגיאה, כדי שהדוח לא יהיה ערימת traceback."""
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    if isinstance(e, urllib.error.URLError):
        return f"רשת: {getattr(e, 'reason', e)}"
    return type(e).__name__


def rewrite_origin(url, origin):
    """מחליף סכימה+מארח ומשאיר נתיב ופרמטרים — כך החתימה נשארת תקפה,
    כי היא מחושבת על chat/msg/exp בלבד ולא על המארח."""
    if not origin:
        return url
    p, o = urlsplit(url), urlsplit(origin)
    return urlunsplit((o.scheme, o.netloc, p.path, p.query, p.fragment))


class Watch:
    """מצב של צופה מדומה אחד."""

    def __init__(self, title, url, bitrate_bps, buf_cap_s, stall_after, prebuffer_s):
        self.title, self.url = title, url
        self.bitrate = bitrate_bps          # בייט לשנייה שהנגן "צורך"
        self.buf_cap = buf_cap_s * bitrate_bps
        self.prebuffer = prebuffer_s * bitrate_bps
        self.stall_after = stall_after
        self.startup_s = None               # עד שהנגן התחיל לנגן בפועל
        self.ttfb_ms = None
        self.total_bytes = 0
        self.errors = {}
        self.stalls = []                    # (שנייה מתחילת הריצה, משך בשניות)
        self.stall_open = None
        self.first_byte_at = None
        self.ended_reason = ''
        self.seek_ms = []
        self.size_bytes = None

    def note_error(self, name):
        self.errors[name] = self.errors.get(name, 0) + 1

    # ── הריצה עצמה ─────────────────────────────────────────────────────────
    def run(self, deadline):
        """מדמה נגן: ממלא באפר מקדים, מתחיל 'לנגן', ומודד מתי הבאפר מתרוקן.

        שתי הפרדות שחשובות לדוח:
        1. זמן ההתחלה נמדד בנפרד ואינו נספר כתקיעה. צריכת הווידאו מתחילה רק
           כשהנגן היה מתחיל — אחרי שהבאפר המקדים התמלא.
        2. תקיעה = הבאפר התרוקן והנגן עצר. היא נסגרת רק כשהבאפר חזר לרמת
           ההתחלה, כמו נגן אמיתי שממתין למילוי מחדש ולא מקפץ על בייט בודד.
        """
        t0 = time.monotonic()
        buf = 0.0
        playing = False
        last = None                      # נקבע רק כשהניגון מתחיל
        try:
            req = urllib.request.Request(
                self.url, headers={"User-Agent": "zovex-vodwatch/1",
                                   "Range": "bytes=0-"})
            started = time.monotonic()
            resp = urllib.request.urlopen(req, timeout=30)
            cr = resp.headers.get("Content-Range", "")
            m = re.search(r"/(\d+)$", cr)
            if m:
                self.size_bytes = int(m.group(1))
            elif resp.headers.get("Content-Length"):
                self.size_bytes = int(resp.headers["Content-Length"])
        except Exception as e:
            self.note_error(_classify(e))
            self.ended_reason = "לא נפתח"
            return

        with resp:
            while not STOP.is_set() and time.monotonic() < deadline:
                # באפר מלא: הנגן מפסיק למשוך, בדיוק כמו נגן אמיתי.
                if playing and buf >= self.buf_cap:
                    time.sleep(0.2)
                    now = time.monotonic()
                    buf = max(0.0, buf - (now - last) * self.bitrate)
                    last = now
                    continue
                try:
                    chunk = resp.read(64 * 1024)
                except Exception as e:
                    self.note_error(_classify(e))
                    self.ended_reason = "נותק באמצע"
                    break
                now = time.monotonic()
                if not chunk:
                    self.ended_reason = "הקובץ נגמר"
                    break
                if self.ttfb_ms is None:
                    self.ttfb_ms = int((now - started) * 1000)
                self.total_bytes += len(chunk)
                buf += len(chunk)

                if not playing:
                    # עוד ממלאים את הבאפר המקדים — לא צורכים ולא סופרים תקיעות.
                    if buf >= self.prebuffer:
                        playing = True
                        last = now
                        if self.startup_s is None:
                            self.startup_s = round(now - started, 2)
                        elif self.stall_open is not None:
                            # סוף תקיעה: הבאפר התמלא והנגן חוזר לנגן.
                            dur = now - self.stall_open
                            if dur >= self.stall_after:
                                self.stalls.append((round(self.stall_open - t0, 1),
                                                    round(dur, 1)))
                            self.stall_open = None
                    continue

                buf -= (now - last) * self.bitrate
                last = now
                if buf <= 0:
                    # הבאפר התרוקן: הנגן עוצר וממתין למילוי מחדש.
                    buf = 0.0
                    playing = False
                    if self.stall_open is None:
                        self.stall_open = now

        if self.stall_open is not None:
            dur = time.monotonic() - self.stall_open
            if dur >= self.stall_after:
                self.stalls.append((round(self.stall_open - t0, 1), round(dur, 1)))
        if not self.ended_reason:
            self.ended_reason = "הסתיים בזמן"

    # ── קפיצה בזמן ─────────────────────────────────────────────────────────
    def seek_test(self, fractions=(0.25, 0.5, 0.8)):
        if not self.size_bytes:
            return
        for f in fractions:
            if STOP.is_set():
                return
            start = int(self.size_bytes * f)
            try:
                t = time.monotonic()
                req = urllib.request.Request(
                    self.url, headers={"User-Agent": "zovex-vodwatch/1",
                                       "Range": f"bytes={start}-{start + 65535}"})
                with urllib.request.urlopen(req, timeout=40) as r:
                    r.read(65536)
                self.seek_ms.append(int((time.monotonic() - t) * 1000))
            except Exception as e:
                self.note_error("קפיצה: " + _classify(e))


def probe_size(url, timeout=25):
    """גודל הקובץ, בבקשת Range זעירה (בייט אחד). לא מוריד את הקובץ."""
    req = urllib.request.Request(url, headers={"User-Agent": "zovex-vodwatch/1",
                                               "Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        cr = r.headers.get("Content-Range", "")
        r.read(8)
        m = re.search(r"/(\d+)$", cr)
        if m:
            return int(m.group(1))
        cl = r.headers.get("Content-Length")
        return int(cl) if cl and not cr else None


def find_heaviest(catalog, origin, want, scan, cache_path, workers=3):
    """מוצא את הכותרים הכבדים ביותר.

    הקטלוג לא מחזיק גודל, אז צריך למדוד. שני צמצומים שומרים על זה זול:
    בודקים רק סרטים (פרק של סדרה לעולם לא יהיה הקובץ הכי כבד), ושומרים
    את מה שנמדד לקובץ מטמון, כך שהרצה חוזרת כמעט לא עולה כלום.
    המקביליות נמוכה בכוונה — כל בדיקה נוגעת בפול של טלגרם, ובדיקה
    שמציפה את השרת מייצרת בדיוק את התקלה שהיא אמורה למדוד.
    """
    try:
        cache = json.load(open(cache_path, encoding="utf-8"))
    except Exception:
        cache = {}

    movies = [m for m in catalog
              if not m.get("is_live") and not m.get("series_name")
              and "/stream/" in str(m.get("video_url") or "")]
    print(f"{len(movies)} סרטים בקטלוג. {len(cache)} גדלים כבר במטמון.")

    todo = [m for m in movies if str(m.get("id")) not in cache]
    random.shuffle(todo)
    if scan > 0:
        todo = todo[:scan]
    if todo:
        print(f"מודד גודל של {len(todo)} סרטים (בקשה של בייט אחד לכל אחד)...")

    lock = threading.Lock()
    done = [0]

    def one(m):
        mid = str(m.get("id"))
        url = rewrite_origin((m.get("video_url") or "").strip(), origin)
        try:
            sz = probe_size(url)
        except Exception:
            sz = None
        with lock:
            cache[mid] = sz
            done[0] += 1
            if done[0] % 25 == 0:
                print(f"   ... {done[0]}/{len(todo)}", flush=True)

    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(one, todo))
        try:
            json.dump(cache, open(cache_path, "w"), ensure_ascii=False)
        except Exception:
            pass

    ranked = []
    for m in movies:
        sz = cache.get(str(m.get("id")))
        if sz:
            ranked.append((sz, str(m.get("title") or "?"),
                           rewrite_origin((m.get("video_url") or "").strip(), origin)))
    ranked.sort(reverse=True)
    if not ranked:
        return []
    print("\nהכבדים ביותר שנמצאו:")
    for sz, t, _ in ranked[:10]:
        print(f"   {human(sz):>9}   {t}")
    return [(t, u, sz) for sz, t, u in ranked[:want]]


def pick_items(catalog, n, origin, seed):
    """בוחר כותרים עם קישור /stream ישיר. מדלג על חי ועל מוטמעים (יוטיוב וכו')."""
    cands = []
    for m in catalog:
        if m.get("is_live"):
            continue
        u = (m.get("video_url") or m.get("video_id") or "").strip()
        if "/stream/" not in u or not u.startswith("http"):
            continue
        cands.append((str(m.get("title") or m.get("name") or "?"), u))
    random.Random(seed).shuffle(cands)
    return [(t, rewrite_origin(u, origin)) for t, u in cands[:n]]


def human(b):
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024 or unit == "GB":
            return f"{b:.1f} {unit}"
        b /= 1024


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=40)
    ap.add_argument("--streams", type=int, default=3, help="כמה צופים במקביל")
    ap.add_argument("--bitrate", type=float, default=3.0, help="מגהביט לשנייה שהנגן צורך")
    ap.add_argument("--buffer", type=float, default=30, help="שניות באפר מקסימלי")
    ap.add_argument("--prebuffer", type=float, default=5,
                    help="שניות שהנגן צובר לפני שהוא מתחיל לנגן")
    ap.add_argument("--stall-after", type=float, default=0.5,
                    help="כמה שניות של באפר ריק נחשבות תקיעה")
    ap.add_argument("--public", action="store_true",
                    help="לבדוק דרך הכתובת הציבורית במקום 127.0.0.1")
    ap.add_argument("--heaviest", action="store_true",
                    help="לבחור את הסרטים הכבדים ביותר במקום אקראיים")
    ap.add_argument("--scan", type=int, default=250,
                    help="כמה סרטים למדוד בחיפוש הכבדים (0 = כולם)")
    ap.add_argument("--assume-minutes", type=float, default=120,
                    help="אורך משוער של סרט, לגזירת קצב הווידאו מהגודל")
    ap.add_argument("--seed", type=int, default=0, help="0 = אקראי בכל הרצה")
    ap.add_argument("--out", default="vod_watch_report.json")
    a = ap.parse_args()

    origin = None if a.public else "http://127.0.0.1:8000"
    src = ("http://127.0.0.1:8000" if not a.public
           else "https://zovex.duckdns.org") + "/content/lite"
    print(f"מושך קטלוג מ-{src} ...")
    with urllib.request.urlopen(src, timeout=60) as r:
        catalog = json.loads(r.read().decode("utf-8", "replace"))

    seed = a.seed or random.randrange(1 << 30)
    if a.heaviest:
        # מטמון הגדלים יושב ליד הסקריפט, ולא ליד קובץ הדוח. קודם הוא נגזר
        # מ---out, כך ש-"--out /tmp/x.json" לא מצא מטמון שנבנה בהרצה קודמת
        # והתחיל למדוד 909 סרטים מחדש — רבע שעה על לא כלום.
        cache_path = os.environ.get("VOD_SIZES_CACHE") or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "vod_sizes.json")
        chosen = find_heaviest(catalog, origin, a.streams, a.scan, cache_path)
        if not chosen:
            print("לא הצלחתי למדוד גודל של אף סרט."); sys.exit(1)
        # קצב הווידאו נגזר מהגודל: קובץ של 4 ג'יגה לשעתיים הוא ~4.7 מגהביט,
        # ולנגן אותו ב-3 זה לא לבדוק אותו. מוגבל לטווח שפוי.
        items = []
        for t, u, sz in chosen:
            br = (sz * 8) / (a.assume_minutes * 60) / 1e6
            items.append((t, u, max(1.0, min(15.0, br))))
    else:
        items = [(t, u, a.bitrate) for t, u in
                 pick_items(catalog, a.streams, origin, seed)]
    if not items:
        print("לא נמצאו כותרים עם קישור /stream ישיר."); sys.exit(1)

    est = sum(br * 1e6 / 8 for _, _, br in items) * a.minutes * 60
    print(f"\nזרע אקראי: {seed}   (--seed {seed} כדי לחזור על אותם כותרים)")
    print(f"{len(items)} צופים מדומים · {a.minutes:g} דקות")
    print(f"תעבורה צפויה: ~{human(est)} סה\"כ"
          + ("  (פנימית, לא יוצאת החוצה)" if not a.public else "  (יוצאת החוצה!)"))
    for t, _, br in items:
        print(f"   • {t}   ({br:.1f} מגהביט)")
    print()

    watches = [Watch(t, u, br * 1e6 / 8, a.buffer, a.stall_after, a.prebuffer)
               for t, u, br in items]
    deadline = time.monotonic() + a.minutes * 60

    def on_sig(*_):
        print("\nעוצר...  (מדפיס דוח חלקי)")
        STOP.set()
    signal.signal(signal.SIGINT, on_sig)
    signal.signal(signal.SIGTERM, on_sig)

    threads = [threading.Thread(target=w.run, args=(deadline,), daemon=True)
               for w in watches]
    t_start = time.monotonic()
    for th in threads:
        th.start()

    # התקדמות חיה
    while any(th.is_alive() for th in threads):
        time.sleep(10)
        el = time.monotonic() - t_start
        tot = sum(w.total_bytes for w in watches)
        st = sum(len(w.stalls) for w in watches)
        print(f"  [{el/60:5.1f} דק']  ירדו {human(tot):>9}   תקיעות עד כה: {st}",
              flush=True)
    for th in threads:
        th.join(timeout=5)

    print("\nבודק קפיצה בזמן (Range מאמצע הקובץ)...")
    for w in watches:
        w.seek_test()

    # ── דוח ────────────────────────────────────────────────────────────────
    el = time.monotonic() - t_start
    print("\n" + "=" * 62)
    print(f"דוח — {el/60:.1f} דקות")
    print("=" * 62)
    for w in watches:
        need = w.bitrate
        got = w.total_bytes / el if el else 0
        stall_tot = sum(d for _, d in w.stalls)
        print(f"\n▶ {w.title}")
        print(f"   בייט ראשון     {w.ttfb_ms if w.ttfb_ms is not None else '—'} מ\"ש")
        print(f"   עד שהתחיל      {w.startup_s if w.startup_s is not None else '—'} שנ'"
              f"   (מילוי באפר מקדים)")
        print(f"   ירדו           {human(w.total_bytes)}  ({got*8/1e6:.2f} מגהביט/ש' בפועל,"
              f" נדרש {need*8/1e6:.2f})")
        if w.stalls:
            longest = max(d for _, d in w.stalls)
            print(f"   תקיעות         {len(w.stalls)}  ·  סה\"כ {stall_tot:.1f} שנ'"
                  f"  ·  הארוכה {longest:.1f} שנ'")
            for at, d in w.stalls[:6]:
                print(f"                    בדקה {at/60:.1f} — {d:.1f} שנ'")
            if len(w.stalls) > 6:
                print(f"                    ... ועוד {len(w.stalls)-6}")
        elif w.startup_s is None:
            # בלי "אין תקיעות ✅" כאן: הניגון לא התחיל, ולכן גלאי התקיעות
            # מעולם לא נדרך. דיווח "תקין" על זרם שלא זרם הוא שקר.
            print("   תקיעות         — הניגון לא התחיל, אין מה למדוד")
        else:
            print("   תקיעות         אין ✅")
        if got < need * 0.9:
            print(f"   ⚠️  אספקה       {got*8/1e6:.2f} מתוך {need*8/1e6:.2f} מגהביט —"
                  f" פי {need/max(got,1):.0f} איטי מהנדרש")
        if w.seek_ms:
            print(f"   קפיצה בזמן     {', '.join(str(x) for x in w.seek_ms)} מ\"ש")
        if w.errors:
            print("   שגיאות         " + ", ".join(f"{k}×{v}" for k, v in w.errors.items()))
        print(f"   סיום           {w.ended_reason}")

    never = [w for w in watches if w.startup_s is None]
    bad = [w for w in watches if w.stalls or w.errors]
    print("\n" + "-" * 62)
    if never:
        print(f"🔴 {len(never)} מתוך {len(watches)} כותרים לא התחילו לנגן כלל.")
    if bad:
        print(f"⚠️  {len(bad)} מתוך {len(watches)} כותרים עם תקיעות או שגיאות.")
    if not bad and not never:
        print(f"✅ כל {len(watches)} הכותרים זרמו נקי, בלי תקיעה אחת.")

    json.dump({
        "seed": seed, "minutes": el / 60, "bitrate_mbps": a.bitrate,
        "public": a.public,
        "items": [{"title": w.title, "ttfb_ms": w.ttfb_ms, "startup_s": w.startup_s,
                   "bytes": w.total_bytes, "size_bytes": w.size_bytes,
                   "stalls": w.stalls, "seek_ms": w.seek_ms,
                   "errors": w.errors, "ended": w.ended_reason} for w in watches],
    }, open(a.out, "w"), ensure_ascii=False, indent=1)
    print(f"דוח מלא נשמר ל-{a.out}")


if __name__ == "__main__":
    main()
