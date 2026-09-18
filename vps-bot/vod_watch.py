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

## למה יש גם יומן אירועים

הכלי ידע לספור תקיעות, אבל לא לומר **למה**. "תקיעה בדקה 7.2" היא עובדה
נכונה שלא מקדמת כלום. לכן כל תקיעה נרשמת עכשיו עם כל מה שידוע עליה —
כמה נמשכה, איפה בקובץ, ומה היה קצב האספקה בעשר השניות שלפניה (זה מה
שמפריד בין "הכל נעצר" ל"זרם לאט מדי", שתי תקלות שונות עם שני פתרונות) —
ולצידה שורות היומן של השירות מאותן שניות. הכתיבה היא מיידית ולא בסוף,
כי ריצה ארוכה ברקע עלולה להיקטע, ודוח שנכתב רק בסוף הוא דוח שלא קיים.

בסוף מודפסת גם פריסה של תקיעות לפי דקה: "נתקע כל כמה דקות" היא טענה על
**קצב**, ותקיעה אחת ארוכה ותקיעה כל שתי דקות נראות זהות בספירה כוללת.

## להריץ בלי לשבת מול המסך

    nohup python3 vod_watch.py --minutes 60 --streams 3 \
          --log /tmp/vod_events.log > /tmp/vod_watch.txt 2>&1 &

ואז, בכל רגע: tail -40 /tmp/vod_events.log

    python3 vod_watch.py --minutes 40 --streams 3
    python3 vod_watch.py --minutes 5 --streams 2 --bitrate 2.5
    python3 vod_watch.py --minutes 40 --streams 3 --public     # דרך הכתובת הציבורית
"""
import argparse, json, os, random, re, signal, subprocess, sys, threading, time
import urllib.request, urllib.error
from urllib.parse import urlsplit, urlunsplit
from collections import deque
from concurrent.futures import ThreadPoolExecutor

STOP = threading.Event()

# ── יומן אירועים ─────────────────────────────────────────────────────────────
# הכלי ידע לספור תקיעות, אבל לא לומר **למה** אחת מהן קרתה. לכן שורות היומן
# של השירות נאספות בזמן אמת, וכל תקיעה נרשמת יחד עם מה שהופיע ביומן סביבה.
# בלי זה נשארים עם "תקיעה בדקה 7.2" — עובדה נכונה שלא מקדמת כלום.
SERVICE = "zovex-bot"
JOURNAL = deque(maxlen=600)                  # (זמן, שורה מצונזרת)
JLOCK = threading.Lock()
LOGF = None
LOGLOCK = threading.Lock()
T_START = [0.0]

REDACT = [
    (re.compile(r"https?://[^\s\"'<>]+"), "‹כתובת›"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "‹IP›"),
    (re.compile(r"\b[a-z0-9][a-z0-9.-]{6,}\.(?:tv|pw|com|net|org|io|me|cc|xyz|to)\b", re.I), "‹מתחם›"),
]
# רק מה שיכול להסביר תקיעה בהזרמה מטלגרם. סינון רחב מדי מציף את הקובץ
# בשורות גישה רגילות ומסתיר בדיוק את מה שחיפשנו.
INTERESTING = re.compile(
    r"Send exception|TCPTransport|dead connection|timeout|timed out|reconnect|"
    r"flood|FloodWait|Telegram|pool|session|ConnectError|ReadError|RpcError|"
    r"stream|ERROR|WARNING|Traceback", re.I)


def clean(s):
    for pat, rep in REDACT:
        s = pat.sub(rep, s)
    return s


def follow_journal():
    """עוקב אחרי יומן השירות ברקע. כישלון כאן לא מפיל כלום — פשוט אין הקשר."""
    proc = None
    for unit in (SERVICE, SERVICE + ".service"):
        try:
            proc = subprocess.Popen(
                ["journalctl", "-u", unit, "-f", "-n", "0", "-o", "cat"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, errors="replace", bufsize=1)
            break
        except Exception:
            proc = None
    if proc is None:
        return
    try:
        for ln in proc.stdout:
            if STOP.is_set():
                break
            if INTERESTING.search(ln):
                with JLOCK:
                    JOURNAL.append((time.monotonic(), clean(ln.strip())[:180]))
    except Exception:
        pass
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


def log_event(title, kind, detail, at=None, context_s=45.0):
    """רושם אירוע מיד — ריצה ארוכה ברקע עלולה להיקטע, ודוח שנכתב רק בסוף
    הוא דוח שלא קיים."""
    now = at if at is not None else time.monotonic()
    rel = int(now - T_START[0])
    line = f"[{rel // 60:02d}:{rel % 60:02d}] {clean(title)[:30]} — {kind} — {detail}"
    with JLOCK:
        ctx = [l for ts, l in JOURNAL if now - ts <= context_s]
    with LOGLOCK:
        if LOGF:
            LOGF.write(line + "\n")
            for l in ctx[-8:]:
                LOGF.write(f"           ↳ יומן: {l}\n")
            if not ctx:
                LOGF.write("           ↳ יומן: שקט — שום שורה לא נרשמה סביב האירוע\n")
    return line, ctx


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
        self.recent = deque(maxlen=400)     # (זמן, בייטים) — קצב לפני התקיעה
        self.stall_at_bytes = 0             # איפה בקובץ נתפסה התקיעה
        self.details = []                   # תיאור מלא לכל תקיעה
        # כמה זמן הזרם הזה באמת רץ. בלי זה, כותר שהקובץ שלו נגמר בדקה 8
        # מתוך 16 נראה כאילו סופק בחצי מהקצב — הזמן שאחרי הסוף נכנס למכנה.
        self.active_s = 0.0
        self.started_playing_at = None
        # הקצב לפני שהבאפר התמלא. זו המדידה היחידה שאינה חנוקה: מרגע
        # שהבאפר מלא הנגן *בכוונה* מפסיק למשוך, ולכן קצב ממוצע על כל
        # הריצה לא יכול לעלות על קצב הווידאו ואינו מודד יכולת אספקה.
        self.startup_rate = None
        self.seeks = []                     # (שנייה מתחילת הריצה, מ"ש, תקין)
        self.played = []                    # כותרים שנוגנו (במצב --loop)

    def _rate_before(self, t, window=10.0):
        """כמה בייט הגיעו ב-window השניות שלפני t. זה מפריד בין 'הכל נעצר'
        לבין 'זרם לאט מדי' — שתי תקלות שונות עם שני פתרונות שונים."""
        n = sum(b for ts, b in self.recent if t - window <= ts <= t)
        return n / window

    def _close_stall(self, now, t0):
        dur = now - self.stall_open
        if dur >= self.stall_after:
            at = round(self.stall_open - t0, 1)
            self.stalls.append((at, round(dur, 1)))
            pct = (f"{self.stall_at_bytes * 100.0 / self.size_bytes:.0f}% מהקובץ"
                   if self.size_bytes else f"בייט {self.stall_at_bytes}")
            rate = self._rate_before(self.stall_open)
            detail = (f"נמשכה {dur:.1f}ש · {pct} · "
                      f"בעשר השניות שלפניה הגיעו {rate * 8 / 1e6:.2f} מגהביט/ש "
                      f"מתוך {self.bitrate * 8 / 1e6:.2f} שנדרשו")
            line, ctx = log_event(self.title, "תקיעה", detail, at=now)
            self.details.append({"at": at, "dur": round(dur, 1),
                                 "detail": detail, "journal": ctx[-8:]})
        self.stall_open = None

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
        self._last_ttfb = self._last_startup = None
        self.ended_reason = ''
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
            log_event(self.title, "לא נפתח בכלל", _classify(e))
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
                    log_event(self.title, "נותק באמצע הזרימה",
                              f"{_classify(e)} · אחרי {human(self.total_bytes)}")
                    break
                now = time.monotonic()
                if not chunk:
                    self.ended_reason = "הקובץ נגמר"
                    break
                if self._last_ttfb is None:
                    self._last_ttfb = int((now - started) * 1000)
                    if self.ttfb_ms is None:
                        self.ttfb_ms = self._last_ttfb
                self.total_bytes += len(chunk)
                buf += len(chunk)
                self.recent.append((now, len(chunk)))

                if not playing:
                    # עוד ממלאים את הבאפר המקדים — לא צורכים ולא סופרים תקיעות.
                    if buf >= self.prebuffer:
                        playing = True
                        last = now
                        if self._last_startup is None:
                            self._last_startup = round(now - started, 2)
                            el0 = now - started
                            if el0 > 0 and self.startup_rate is None:
                                self.startup_rate = self.total_bytes / el0
                            if self.startup_s is None:
                                self.startup_s = self._last_startup
                                self.started_playing_at = now
                            if self._last_startup >= 4.0:
                                log_event(self.title, "התחלה איטית",
                                          f"{self._last_startup:.1f}ש עד שהנגן התחיל "
                                          f"(בייט ראשון אחרי {self._last_ttfb} מ\"ש)",
                                          at=now)
                        elif self.stall_open is not None:
                            # סוף תקיעה: הבאפר התמלא והנגן חוזר לנגן.
                            self._close_stall(now, t0)
                    continue

                buf -= (now - last) * self.bitrate
                last = now
                if buf <= 0:
                    # הבאפר התרוקן: הנגן עוצר וממתין למילוי מחדש.
                    buf = 0.0
                    playing = False
                    if self.stall_open is None:
                        self.stall_open = now
                        self.stall_at_bytes = self.total_bytes

        if self.stall_open is not None:
            self._close_stall(time.monotonic(), t0)
        self.active_s += time.monotonic() - t0
        if not self.ended_reason:
            self.ended_reason = "הסתיים בזמן"

    def run_many(self, deadline, next_item):
        """ממשיך לצפות: כשקובץ נגמר, עובר לכותר הבא.

        בלי זה ריצה של 30 דקות מסתיימת אחרי 16, כי הקבצים נגמרו — והשקט
        שאחריהם נכנס לכל ממוצע ומזייף אותו. צופה אמיתי גם הוא לא מפסיק
        לצפות כשפרק נגמר.
        """
        while True:
            before = self.total_bytes
            self.run(deadline)
            self.played.append({
                "title": self.title, "startup_s": self._last_startup,
                "ttfb_ms": self._last_ttfb, "bytes": self.total_bytes - before,
                "ended": self.ended_reason})
            if (STOP.is_set() or time.monotonic() >= deadline
                    or self.ended_reason != "הקובץ נגמר"):
                break
            nxt = next_item()
            if not nxt:
                break
            self.title, self.url = nxt[0], nxt[1]
            self.size_bytes = None
            log_event(self.title, "כותר חדש", "הקודם נגמר — ממשיך לצפות")

    def seek_probe(self, slow_s):
        """קפיצה בודדת למקום אקראי, כמו משתמש שמדלג. נמדדת בחיבור נפרד
        כדי לא לעצור את הזרימה ולייצר תקיעה מדומה."""
        if not self.size_bytes or STOP.is_set():
            return
        start = int(self.size_bytes * random.uniform(0.05, 0.95))
        t = time.monotonic()
        try:
            req = urllib.request.Request(
                self.url, headers={"User-Agent": "zovex-vodwatch/1",
                                   "Range": f"bytes={start}-{start + 65535}"})
            with urllib.request.urlopen(req, timeout=40) as r:
                r.read(65536)
            ms = int((time.monotonic() - t) * 1000)
            self.seeks.append((round(time.monotonic() - T_START[0], 1), ms, True))
            if ms >= slow_s * 1000:
                log_event(self.title, "קפיצה איטית",
                          f"{ms} מ\"ש עד הבייט הראשון אחרי דילוג "
                          f"({start * 100.0 / self.size_bytes:.0f}% מהקובץ)")
        except Exception as e:
            self.note_error("קפיצה: " + _classify(e))
            self.seeks.append((round(time.monotonic() - T_START[0], 1), None, False))
            log_event(self.title, "קפיצה נכשלה", _classify(e))

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
    ap.add_argument("--log", default="/tmp/vod_events.log",
                    help="יומן אירועים מפורט, נכתב תוך כדי ריצה (ריק = בלי)")
    ap.add_argument("--loop", action="store_true",
                    help="כשקובץ נגמר — לעבור לכותר הבא ולהמשיך עד סוף החלון")
    ap.add_argument("--seek-every", type=float, default=90.0, dest="seek_every",
                    help="כל כמה שניות לבדוק דילוג באמצע הצפייה (0 = בלי)")
    ap.add_argument("--seek-slow", type=float, default=2.0, dest="seek_slow",
                    help="דילוג איטי מזה נרשם כאירוע")
    a = ap.parse_args()

    global LOGF
    if a.log:
        try:
            LOGF = open(a.log, "a", encoding="utf-8", buffering=1)
            LOGF.write(f"\n===== ריצה חדשה · {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
        except Exception as e:
            print(f"אזהרה: לא הצלחתי לפתוח את {a.log}: {e}")

    # הפורט לא היה ניתן לשינוי, וזה חוסם גם בדיקה מול מופע אחר וגם שרת
    # שמאזין במקום אחר. PORT הוא אותו משתנה ש-main.py קורא.
    local = "http://127.0.0.1:" + os.environ.get("PORT", "8000")
    origin = None if a.public else local
    src = (local if not a.public else "https://zovex.duckdns.org") + "/content/lite"
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

    # מאגר כותרים להמשך במצב --loop. ננעל, כי כמה צופים שואבים ממנו.
    spare = [(t, u) for t, u in pick_items(catalog, 60, origin, seed + 1)
             if u not in {w.url for w in watches}]
    spare_lock = threading.Lock()

    def next_item():
        with spare_lock:
            return spare.pop(0) if spare else None

    t_start = time.monotonic()
    T_START[0] = t_start
    threading.Thread(target=follow_journal, daemon=True).start()
    target = (lambda w: w.run_many(deadline, next_item)) if a.loop else \
             (lambda w: w.run(deadline))
    threads = [threading.Thread(target=target, args=(w,), daemon=True)
               for w in watches]
    for th in threads:
        th.start()

    if a.seek_every > 0:
        def seek_loop():
            # דילוג הוא החשוד שהמדידה הקודמת הצביעה עליו: הזרימה הרציפה
            # הייתה נקייה, אבל דילוג לקח שניות. לכן הוא נמדד תוך כדי
            # צפייה ולא רק בסוף, ובחיבור נפרד כדי לא לעצור את הזרימה.
            while not STOP.is_set() and time.monotonic() < deadline:
                time.sleep(a.seek_every)
                for w in watches:
                    if STOP.is_set():
                        break
                    w.seek_probe(a.seek_slow)
        threading.Thread(target=seek_loop, daemon=True).start()

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
        # לפי הזמן שהזרם הזה באמת רץ, ולא לפי אורך הריצה כולה. כותר שהקובץ
        # שלו נגמר בדקה 8 מתוך 16 נראה אחרת לגמרי בין שתי הנוסחאות, וקודם
        # הוא דווח כ"פי 2 איטי מהנדרש" כשלמעשה סופק במלואו.
        span = w.active_s or el
        got = w.total_bytes / span if span else 0
        stall_tot = sum(d for _, d in w.stalls)
        print(f"\n▶ {w.title}")
        print(f"   בייט ראשון     {w.ttfb_ms if w.ttfb_ms is not None else '—'} מ\"ש")
        print(f"   עד שהתחיל      {w.startup_s if w.startup_s is not None else '—'} שנ'"
              f"   (מילוי באפר מקדים)")
        print(f"   ירדו           {human(w.total_bytes)}  ({got*8/1e6:.2f} מגהביט/ש' בפועל,"
              f" נדרש {need*8/1e6:.2f})  · זרם {span/60:.1f} דק'")
        if w.startup_rate:
            # המדידה היחידה שאינה חנוקה: מרגע שהבאפר מלא הנגן מפסיק למשוך
            # בכוונה, ולכן הממוצע לא יכול לעלות על קצב הווידאו ואינו אומר
            # כלום על יכולת האספקה. זה כן.
            print(f"   קצב לא חנוק   {w.startup_rate*8/1e6:.2f} מגהביט/ש'"
                  f"   (נמדד בזמן מילוי הבאפר הראשון)")
        if w.played:
            print(f"   כותרים         {len(w.played)}: "
                  + ", ".join(p["title"][:22] for p in w.played[:6])
                  + (" ..." if len(w.played) > 6 else ""))
        if w.stalls:
            longest = max(d for _, d in w.stalls)
            print(f"   תקיעות         {len(w.stalls)}  ·  סה\"כ {stall_tot:.1f} שנ'"
                  f"  ·  הארוכה {longest:.1f} שנ'")
            for d in w.details[:12]:
                print(f"       ├ דקה {d['at']/60:5.1f} — {d['detail']}")
                for l in d["journal"][-3:]:
                    print(f"       │    יומן: {l}")
                if not d["journal"]:
                    print("       │    יומן: שקט — שום שורה סביב התקיעה הזאת")
            if len(w.details) > 12:
                print(f"       └ ... ועוד {len(w.details)-12} (כולן בקובץ היומן)")
        elif w.startup_s is None:
            # בלי "אין תקיעות ✅" כאן: הניגון לא התחיל, ולכן גלאי התקיעות
            # מעולם לא נדרך. דיווח "תקין" על זרם שלא זרם הוא שקר.
            print("   תקיעות         — הניגון לא התחיל, אין מה למדוד")
        else:
            print("   תקיעות         אין ✅")
        # אזהרת אספקה רק כשיש לה על מה להישען. הממוצע לבדו לא יכול
        # להעיד: הנגן חונק את עצמו בכוונה כשהבאפר מלא, ולכן "פחות מהנדרש"
        # הוא המצב התקין ולא תקלה. הקצב הלא-חנוק הוא הראיה.
        if w.startup_rate is not None and w.startup_rate < need:
            print(f"   ⚠️  אספקה       גם בלי חניקה סופק רק "
                  f"{w.startup_rate*8/1e6:.2f} מתוך {need*8/1e6:.2f} מגהביט —"
                  f" פי {need/max(w.startup_rate,1):.1f} איטי מהנדרש")
        ok_seeks = [ms for _, ms, ok in w.seeks if ok and ms is not None]
        if ok_seeks:
            ok_seeks_sorted = sorted(ok_seeks)
            med = ok_seeks_sorted[len(ok_seeks_sorted) // 2]
            print(f"   דילוגים        {len(w.seeks)} · חציון {med} מ\"ש · "
                  f"הגרוע {max(ok_seeks)} מ\"ש")
        if w.seek_ms:
            print(f"   קפיצה בסוף     {', '.join(str(x) for x in w.seek_ms)} מ\"ש")
        if w.errors:
            print("   שגיאות         " + ", ".join(f"{k}×{v}" for k, v in w.errors.items()))
        print(f"   סיום           {w.ended_reason}")

    # "נתקע כל כמה דקות" היא טענה על קצב, ורק פריסה על ציר הזמן מאשרת
    # או מפריכה אותה. תקיעה אחת ארוכה ותקיעה כל שתי דקות נראות זהות
    # בספירה כוללת, והן שתי תקלות שונות לגמרי.
    per_min = {}
    for w in watches:
        for at, _d in w.stalls:
            per_min[int(at // 60)] = per_min.get(int(at // 60), 0) + 1
    if per_min:
        print("\n── תקיעות לפי דקה ──")
        for m in range(int(el // 60) + 1):
            n = per_min.get(m, 0)
            if n:
                print(f"  דקה {m:>3}:  {n:>3}  " + "█" * min(n, 40))
        gaps = sorted(per_min)
        if len(gaps) > 1:
            d = [gaps[i + 1] - gaps[i] for i in range(len(gaps) - 1)]
            print(f"  מרווח ממוצע בין דקות עם תקיעה: {sum(d)/len(d):.1f} דקות")

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
                   "stalls": w.stalls, "details": w.details, "seek_ms": w.seek_ms,
                   "errors": w.errors, "ended": w.ended_reason} for w in watches],
    }, open(a.out, "w"), ensure_ascii=False, indent=1)
    print(f"דוח מלא נשמר ל-{a.out}")
    if LOGF:
        print(f"יומן אירועים מפורט: {a.log}")
        try:
            LOGF.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
