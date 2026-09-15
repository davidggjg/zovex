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
import argparse, json, random, re, signal, sys, threading, time
import urllib.request, urllib.error
from urllib.parse import urlsplit, urlunsplit

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
    items = pick_items(catalog, a.streams, origin, seed)
    if not items:
        print("לא נמצאו כותרים עם קישור /stream ישיר."); sys.exit(1)

    bps = a.bitrate * 1_000_000 / 8
    est = bps * a.streams * a.minutes * 60
    print(f"\nזרע אקראי: {seed}   (--seed {seed} כדי לחזור על אותם כותרים)")
    print(f"{len(items)} צופים מדומים · {a.minutes:g} דקות · {a.bitrate:g} מגהביט כל אחד")
    print(f"תעבורה צפויה: ~{human(est)} סה\"כ"
          + ("  (פנימית, לא יוצאת החוצה)" if not a.public else "  (יוצאת החוצה!)"))
    for t, _ in items:
        print(f"   • {t}")
    print()

    watches = [Watch(t, u, bps, a.buffer, a.stall_after, a.prebuffer)
               for t, u in items]
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
        else:
            print("   תקיעות         אין ✅")
        if w.seek_ms:
            print(f"   קפיצה בזמן     {', '.join(str(x) for x in w.seek_ms)} מ\"ש")
        if w.errors:
            print("   שגיאות         " + ", ".join(f"{k}×{v}" for k, v in w.errors.items()))
        print(f"   סיום           {w.ended_reason}")

    bad = [w for w in watches if w.stalls or w.errors]
    print("\n" + "-" * 62)
    if bad:
        print(f"⚠️  {len(bad)} מתוך {len(watches)} כותרים עם תקיעות או שגיאות.")
    else:
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
