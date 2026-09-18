#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
live_check — למה השידורים החיים נתקעים, בלי לחשוף את הספק.

## שני מצבים

    python3 live_check.py --watch 10     ← זה מה שצריך כשזה נתקע *עכשיו*
    python3 live_check.py --min 30       ← מבט לאחור ביומן בלבד

## למה הוספתי --watch, ולמה המבט לאחור לבדו לא מספיק

מבט לאחור סורק את היומן. אבל בקריאה של נתיב הממסר ב-main.py מתברר ששתי
הדרכים הסבירות ביותר לכישלון של ערוץ חי **לא כותבות ליומן כלום**:

    raise HTTPException(502, f"hls_relay: upstream fetch failed - {e}")
    raise HTTPException(502, "hls_relay: upstream did not return a valid m3u8 ...")

שתיהן זורקות חריגה בלי log. כלומר הערוץ מת אצל הצופה, והסריקה לאחור מדפיסה
"לא נמצא כלום". זו בדיוק התשובה המטעה שמבזבזת ערב.

לכן --watch עושה שלושה דברים במקביל, לאורך החלון שביקשת:

  **1. עוקב אחרי היומן חי** (journalctl -f) — תופס שגיאות ברגע שהן קורות.
  **2. קורא את שורות הגישה של uvicorn** — שם כן מופיע "502" על /hls-relay,
     וזה מה שחושף בדיוק את שתי החריגות השקטות שלמעלה.
  **3. מודד בעצמו.** כל כמה שניות מושך את ה-playlist של כמה ערוצים דרך
     127.0.0.1 ובודק אם הוא **מתקדם**. playlist חי שלא משתנה 30 שניות =
     זו התקיעה שהצופה רואה, גם אם אף שורה לא נכתבה לשום יומן.

בסוף מודפסת טבלה של דקה-אחר-דקה: כמה ערוצים היו תקועים בכל דקה, וכמה
שגיאות נרשמו באותה דקה. "נתקע כל כמה דקות" הוא טענה על **קצב**, ורק טבלה
כזאת יכולה לאשר או להפריך אותה.

## מה הכלי במכוון לא עושה

**לא מושך מקטעי וידאו** כברירת מחדל. בקריאת `_proxy_segment` ב-main.py:
הצופה הראשון שמבקש מקטע הוא זה שמושך אותו מהספק, ושאר הצופים באותו ערוץ
"מצטרפים" לזרימה שלו. אם הראשון מתנתק באמצע, ה-`finally` מדליק את
`done_event` — וכל מי שהצטרף מקבל מקטע **קטוע**. כלומר כלי אבחון שמושך
מקטע וסוגר באמצע היה גורם בעצמו לתקיעה אצל צופים אמיתיים. מי שרוצה
בכל זאת למדוד מקטעים: ‎--segments‎ מושך אותם **עד הסוף** ולא נוטש באמצע.

**לא נוגע בספק ישירות.** ערוץ שהכתובת שלו לא עוברת דרך /hls-relay/ מדולג,
ונספר בנפרד. **ולא מפעיל המרות**: כתובת /hls-relay/_fix/ מפעילה ffmpeg
לערוץ שאולי איש לא צופה בו, ולכן מדולגת אלא אם ביקשת ‎--include-fix‎.

## צנזורה, ולמה היא בקוד ולא בהוראות

בפעם הקודמת הפלט של כלי אבחון כלל את שם השרת של הספק ואת הסיסמה שבנתיב,
והודבק לצ'אט. לכן הצנזור הוא חלק מהכלי ולא בקשה מהמשתמש: כל מה שנראה כמו
כתובת, שם מתחם, IP או מזהה ארוך מוחלף לפני ההדפסה, ושמות הערוצים מוצגים
במקום הכתובות שלהם. אפשר להדביק את הפלט בבטחה.
"""
import argparse, json, os, re, subprocess, sys, threading, time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request as UrlRequest, urlopen

SERVICE = "zovex-bot"
PORT = int(os.environ.get("PORT", "8000"))
LOCAL = f"http://127.0.0.1:{PORT}"
PUBLIC = os.environ.get("ZOVEX_PUBLIC", "https://zovex.duckdns.org")

# ── צנזורה ───────────────────────────────────────────────────────────────────
# מוחלף לפני כל הדפסה. הסדר חשוב: קודם כתובות מלאות, אחר כך מה שנשאר.
REDACT = [
    (re.compile(r"https?://[^\s\"'<>]+"), "‹כתובת›"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "‹IP›"),
    (re.compile(r"\b[a-z0-9][a-z0-9.-]{6,}\.(?:tv|pw|com|net|org|io|me|cc|xyz|to)\b", re.I), "‹מתחם›"),
    (re.compile(r"\b[A-Za-z0-9]{12,}\b"), "‹מזהה›"),
]


def clean(s):
    for pat, rep in REDACT:
        s = pat.sub(rep, s)
    return s


# ── סיווג שורות יומן ─────────────────────────────────────────────────────────
PATTERNS = [
    ("ffmpeg של ערוץ מת / הופעל מחדש", re.compile(r"ffmpeg|hls_fix|_hls_", re.I)),
    ("מקטע שהמקור החזיר עליו שגיאה", re.compile(r"segment upstream returned", re.I)),
    ("מקטע שנקטע באמצע המשיכה", re.compile(r"segment stream failed", re.I)),
    ("חיבור מת (דליפת בריכות?)", re.compile(r"Send exception|TCPTransport closed|dead connection", re.I)),
    ("timeout / reconnect מול המקור", re.compile(r"timeout|timed out|reconnect|ConnectError|ReadError", re.I)),
    ("שגיאת ממסר (hls-relay)", re.compile(r"hls-relay|hls_relay|relay", re.I)),
]
# שם ערוץ מופיע בלוג כ-[שם] או channel=שם
CHAN = re.compile(r"\[([^\]\s]{2,40})\]|channel[= ]([^\s,]{2,40})")
# שורת הגישה של uvicorn. זה המקום היחיד שבו מופיעות שתי חריגות ה-502
# השקטות של הממסר, ולכן היא נקראת בנפרד משאר הסיווג.
ACCESS = re.compile(r'"(?:GET|HEAD) (/hls-relay/\S*) HTTP/[\d.]+" (\d{3})')


def journal(minutes):
    """מבט לאחור. מחזיר שורות, או None אם היומן לא נקרא."""
    for unit in (SERVICE, SERVICE + ".service"):
        cmd = ["journalctl", "-u", unit, "--since", f"{minutes} min ago",
               "--no-pager", "-o", "cat"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.splitlines()
        except Exception:
            pass
    return None


# ── HTTP ─────────────────────────────────────────────────────────────────────
UA = "zovex-live-check/2"


def fetch(url, timeout=8.0, max_bytes=None):
    """מחזיר (status, body_bytes, seconds, err). לא זורק."""
    t0 = time.time()
    req = UrlRequest(url, headers={"User-Agent": UA})
    try:
        with urlopen(req, timeout=timeout) as r:
            body = r.read() if max_bytes is None else r.read(max_bytes)
            return r.status, body, time.time() - t0, None
    except HTTPError as e:
        try:
            e.read()
        except Exception:
            pass
        return e.code, b"", time.time() - t0, None
    except URLError as e:
        return 0, b"", time.time() - t0, str(e.reason)[:60]
    except Exception as e:                      # timeout, קריאה שנקטעה, וכו'
        return 0, b"", time.time() - t0, type(e).__name__


def parse_manifest(text):
    """מחזיר (fingerprint, segments, is_master).

    הטביעה היא מספר הרצף + ארבעת המקטעים האחרונים. playlist חי חייב לשנות
    אותה כל כמה שניות; אם היא לא זזה — הזרם עצמו לא מתקדם, וזה בדיוק מה
    שהצופה רואה כתמונה קפואה.
    """
    seq, segs, master = "", [], False
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("#EXT-X-MEDIA-SEQUENCE"):
            seq = s
        elif s.startswith("#EXT-X-STREAM-INF"):
            master = True
        elif s and not s.startswith("#"):
            segs.append(s)
    return (seq, tuple(segs[-4:])), segs, master


class Chan:
    def __init__(self, title, path):
        self.title = title
        self.path = path                       # רק נתיב — הכתובת המלאה לא נשמרת
        self.polls = self.ok = 0
        self.errors = Counter()
        self.pub_errors = Counter()
        self.seg = Counter()
        self.fp = None
        self.changed_at = None                 # מתי ה-playlist זז בפעם האחרונה
        self.in_stall = False
        self.stalls = []                       # אורכי תקיעות שהסתיימו
        self.max_stall = 0.0
        self.latency = []
        self.resolved = False                  # master → variant כבר נפתר

    @property
    def url(self):
        return LOCAL + self.path

    @property
    def pub_url(self):
        return PUBLIC + self.path


def live_channels(count, only, include_fix):
    """שואב את רשימת השידורים החיים מהשרת עצמו.

    מדלג על כל מה שלא עובר דרך /hls-relay/ — כדי שהכלי לא ייגע בספק
    ישירות — ועל /_fix/ — כדי לא להדליק ffmpeg לערוץ שאיש לא צופה בו.
    """
    st, body, _, err = fetch(LOCAL + "/content/live", timeout=25)
    if st != 200 or not body:
        sys.exit(f"לא הצלחתי לקרוא את רשימת הערוצים מהשרת (status {st}"
                 + (f", {err}" if err else "") + ").\n"
                 f"בדוק שהבוט רץ: systemctl status {SERVICE}")
    try:
        items = json.loads(body.decode("utf-8", "replace"))
    except Exception as e:
        sys.exit(f"רשימת הערוצים לא נקראה כ-JSON: {e}")

    chans, skipped = [], Counter()
    for e in items:
        title = (e.get("title") or e.get("name") or "?").strip()
        if only and only not in title:
            continue
        u = str(e.get("video_url") or "")
        if not u:
            skipped["בלי כתובת"] += 1
            continue
        p = urlparse(u)
        path = p.path + (("?" + p.query) if p.query else "")
        if not p.path.startswith("/hls-relay/"):
            skipped["לא דרך הממסר — לא נוגעים"] += 1
            continue
        if p.path.startswith("/hls-relay/_fix/") and not include_fix:
            skipped["_fix (היה מדליק ffmpeg)"] += 1
            continue
        chans.append(Chan(title, path))

    # דגימה מפוזרת ולא 6 הראשונים: ערוצים שכנים ברשימה מגיעים מאותו מקור,
    # ודגימה של הראשונים בלבד מודדת מקור אחד ומדווחת עליו כאילו הוא הכול.
    if count and len(chans) > count:
        step = len(chans) / float(count)
        chans = [chans[int(i * step)] for i in range(count)]
    return chans, skipped


# ── מצב מעקב ─────────────────────────────────────────────────────────────────
def watch(a):
    chans, skipped = live_channels(a.channels, a.only, a.include_fix)
    if not chans:
        sys.exit("לא נמצאו ערוצים לבדיקה. נסה --include-fix, או --only עם שם ערוץ.")

    print(f"מעקב: {a.watch} דקות · {len(chans)} ערוצים · דגימה כל {a.every}ש")
    for k, v in skipped.most_common():
        print(f"  דולגו {v}: {k}")
    print("  ערוצים שנבדקים: " + clean(", ".join(c.title for c in chans)))
    print(f"  סף תקיעה: {a.stall} שניות בלי ש-ה-playlist זז")
    if a.segments:
        print(f"  מקטעים: כן, כל {a.seg_every}ש (נמשכים עד הסוף, לא ננטשים)")
    print(f"  {'גם דרך הכתובת הציבורית (nginx)' if a.public else 'דרך 127.0.0.1 בלבד'}")
    print("\nמריץ. אפשר להשאיר את זה ולצפות בערוץ במקביל — כך נדע אם מה\n"
          "שהצופה רואה מופיע גם במדידה.\n")

    start = time.time()
    end = start + a.watch * 60
    stop = threading.Event()

    # יומן חי
    jcounts, jsamples = Counter(), defaultdict(list)
    access = Counter()
    jminute = Counter()
    jlock = threading.Lock()

    def on_line(ln, now):
        m = ACCESS.search(ln)
        if m:
            code = m.group(2)
            with jlock:
                access[code] += 1
                if not code.startswith("2"):
                    jminute[int((now - start) // 60)] += 1
                    if len(jsamples["גישה"]) < a.show:
                        jsamples["גישה"].append(clean(ln.strip())[:170])
            return
        for name, pat in PATTERNS:
            if pat.search(ln):
                with jlock:
                    jcounts[name] += 1
                    jminute[int((now - start) // 60)] += 1
                    if len(jsamples[name]) < a.show:
                        jsamples[name].append(clean(ln.strip())[:170])
                return

    def follow():
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
            print("  (אזהרה: לא הצלחתי לעקוב אחרי היומן — ממשיך עם המדידה בלבד)")
            return
        try:
            for ln in proc.stdout:
                if stop.is_set():
                    break
                on_line(ln, time.time())
        except Exception:
            pass
        finally:
            try:
                proc.terminate()
            except Exception:
                pass

    th = threading.Thread(target=follow, daemon=True)
    th.start()

    stall_minute = Counter()
    pub_fail = [0]
    pub_on = [a.public]
    next_seg = start + a.seg_every

    def poll(c, now, do_seg):
        st, body, dt, err = fetch(c.url, timeout=a.timeout)
        c.polls += 1
        c.latency.append(dt)
        if st != 200:
            c.errors[f"HTTP {st}" if st else (err or "timeout")] += 1
            return
        text = body.decode("utf-8", "replace")
        if not text.lstrip().startswith("#EXTM3U"):
            c.errors["לא m3u8"] += 1
            return
        fp, segs, master = parse_manifest(text)

        # master playlist: יורדים פעם אחת לוריאנט הראשון וממשיכים למדוד אותו.
        if master and segs and not c.resolved:
            c.resolved = True
            nxt = urlparse(urljoin(c.url, segs[0]))
            c.path = nxt.path + (("?" + nxt.query) if nxt.query else "")
            return
        c.ok += 1

        if c.fp is None or fp != c.fp:
            if c.in_stall and c.changed_at:
                c.stalls.append(now - c.changed_at)
            c.in_stall = False
            c.fp, c.changed_at = fp, now
        else:
            gap = now - (c.changed_at or now)
            c.max_stall = max(c.max_stall, gap)
            if gap >= a.stall:
                c.in_stall = True
                stall_minute[int((now - start) // 60)] += 1

        if do_seg and segs:
            # עד הסוף במכוון — ראה את ההערה בראש הקובץ על מקטע קטוע.
            sst, sbody, sdt, serr = fetch(urljoin(c.url, segs[-1]), timeout=a.timeout)
            if sst != 200:
                c.seg[f"HTTP {sst}" if sst else (serr or "timeout")] += 1
            elif not sbody:
                c.seg["200 ריק (!)"] += 1
            else:
                c.seg["תקין"] += 1

        if pub_on[0]:
            pst, pbody, _, perr = fetch(c.pub_url, timeout=a.timeout)
            if pst != 200 or not pbody.lstrip().startswith(b"#EXTM3U"):
                c.pub_errors[f"HTTP {pst}" if pst else (perr or "timeout")] += 1
                pub_fail[0] += 1
                if pub_fail[0] >= 3 * len(chans):
                    pub_on[0] = False
                    print("  (הבדיקה הציבורית כבתה — נכשלה שוב ושוב. "
                          "ממשיך עם 127.0.0.1)")

    pool = ThreadPoolExecutor(max_workers=min(len(chans), 12))
    beat = start
    try:
        while time.time() < end:
            now = time.time()
            do_seg = a.segments and now >= next_seg
            if do_seg:
                next_seg = now + a.seg_every
            list(pool.map(lambda c: poll(c, now, do_seg), chans))

            if time.time() - beat >= 30:
                beat = time.time()
                el = int(beat - start)
                stuck = [c.title for c in chans if c.in_stall]
                with jlock:
                    jerr = sum(jcounts.values()) + sum(
                        n for k, n in access.items() if not k.startswith("2"))
                line = (f"  [{el // 60:02d}:{el % 60:02d}] "
                        f"דגימות {sum(c.polls for c in chans)} · "
                        f"שגיאות יומן {jerr} · תקועים עכשיו {len(stuck)}")
                if stuck:
                    line += ": " + clean(", ".join(stuck[:4]))
                print(line, flush=True)

            slack = a.every - (time.time() - now)
            if slack > 0:
                time.sleep(slack)
    except KeyboardInterrupt:
        print("\n(הופסק ידנית — מדפיס את מה שנאסף)")
    finally:
        stop.set()
        pool.shutdown(wait=False)

    # תקיעה שעדיין נמשכת בסוף החלון נספרת — אחרת ערוץ שמת ולא קם כלל
    # לא היה מופיע בדוח, וזה בדיוק המקרה החמור ביותר.
    now = time.time()
    for c in chans:
        if c.in_stall and c.changed_at:
            c.stalls.append(now - c.changed_at)

    report(a, chans, jcounts, jsamples, access, stall_minute, jminute,
           int(now - start))


def report(a, chans, jcounts, jsamples, access, stall_minute, jminute, elapsed):
    m, s = elapsed // 60, elapsed % 60
    dur = ("דקה" if m == 1 else f"{m} דקות") + f" ו-{s} שניות"
    print(f"\n{'=' * 62}\nסיכום · {dur}\n{'=' * 62}")

    print("\n── לפי ערוץ ──")
    print(f"  {'ערוץ':22} {'דגימות':>7} {'שגיאות':>7} {'תקיעות':>7} {'ארוכה':>7}")
    for c in sorted(chans, key=lambda x: -x.max_stall):
        errs = sum(c.errors.values())
        print(f"  {clean(c.title)[:22]:22} {c.polls:>7} {errs:>7} "
              f"{len(c.stalls):>7} {c.max_stall:>6.0f}ש")
        detail = []
        if c.errors:
            detail.append("שגיאות: " + ", ".join(f"{k}×{v}" for k, v in c.errors.most_common(4)))
        if c.pub_errors:
            detail.append("דרך nginx: " + ", ".join(f"{k}×{v}" for k, v in c.pub_errors.most_common(3)))
        if c.seg:
            detail.append("מקטעים: " + ", ".join(f"{k}×{v}" for k, v in c.seg.most_common(4)))
        for d in detail:
            print(f"      {d}")

    # הטבלה שעונה על "נתקע כל כמה דקות"
    mins = max(stall_minute.keys() | jminute.keys(), default=-1) + 1
    if mins > 0 and (stall_minute or jminute):
        print("\n── דקה אחר דקה ──")
        print("  (כל שורה = דקה. 'תקועים' = דגימות שבהן ערוץ לא התקדם)")
        for m in range(mins):
            s, j = stall_minute.get(m, 0), jminute.get(m, 0)
            if not s and not j:
                continue
            print(f"  דקה {m:>2}:  תקועים {s:>3}  ·  שגיאות ביומן {j:>3}  "
                  + "█" * min(s, 40))

    print("\n── היומן ──")
    if not jcounts and not access:
        print("  שקט מוחלט. שום שורה ושום בקשה ל-/hls-relay לא נרשמו.")
    for name, n in jcounts.most_common():
        print(f"  {n:6}  {name}")
    if access:
        bad = {k: v for k, v in access.items() if not k.startswith("2")}
        okn = sum(v for k, v in access.items() if k.startswith("2"))
        print(f"\n  בקשות ל-/hls-relay: {okn} תקינות"
              + (", " + ", ".join(f"{k}×{v}" for k, v in sorted(bad.items())) if bad else ""))
        if bad.get("502"):
            print("  ← 502 על הממסר הוא בדיוק החריגה שלא נכתבת ליומן:")
            print("    המקור לא ענה, או שהחזיר משהו שאינו m3u8 תקין.")

    for name in list(jsamples):
        if jsamples[name]:
            print(f"\n── דוגמאות: {name} ──")
            for s in jsamples[name]:
                print(f"  {s}")

    # ── פסק דין ──
    print("\n── מה זה אומר ──")
    stalled = [c for c in chans if c.stalls]
    errored = [c for c in chans if c.errors]
    # ערוץ שלא החזיר ולו playlist תקין אחד הוא המקרה החמור ביותר, והוא גם
    # השקט ביותר: אין לו "תקיעה" למדוד, כי הוא אף פעם לא התחיל. בלי השורה
    # הזאת הוא היה נעלם מפסק הדין לגמרי.
    dead = [c for c in chans if c.polls and not c.ok]
    bad502 = access.get("502", 0)
    if not stalled and not errored and not bad502 and not jcounts:
        print("  בחלון הזה השרת היה נקי: כל playlist שנבדק המשיך להתקדם,")
        print("  ואף בקשה לא נכשלה. זה לא אומר שאין בעיה — זה אומר שהיא לא")
        print("  קרתה כאן ועכשיו. אם צופה נתקע בדיוק בזמן הריצה, החשוד עובר")
        print("  ללקוח (נגן/רשת), ולא לשרת. אם לא נתקע — הרץ שוב בזמן תקיעה.")
    else:
        if dead:
            print("  · ערוצים שלא החזירו ולו playlist תקין אחד בכל החלון: "
                  + clean(", ".join(c.title for c in dead)))
            print("    אלה לא 'נתקעים' — הם פשוט מתים. אצל הצופה זה מסך שחור")
            print("    או טעינה אינסופית, לא תמונה קפואה.")
        if bad502:
            print(f"  · {bad502} בקשות ל-/hls-relay חזרו 502 — כלומר המקור")
            print("    לא ענה או לא החזיר m3u8. זה כשל בצד הספק/הרשת אליו,")
            print("    לא בקוד שלנו.")
        if len(stalled) >= max(2, len(chans) * 2 // 3):
            print(f"  · {len(stalled)} מתוך {len(chans)} הערוצים נתקעו — זה מפוזר,")
            print("    ולכן החשוד הוא משאב משותף: רשת, CPU, או הספק כולו.")
        elif stalled:
            print("  · נתקעו רק: " + clean(", ".join(c.title for c in stalled)))
            print("    זה מרוכז, ולכן החשוד הוא המקורות הספציפיים האלה ולא המערכת.")
        if any(c.pub_errors and not c.errors for c in chans):
            print("  · יש ערוצים שתקינים דרך 127.0.0.1 ונכשלים דרך הכתובת")
            print("    הציבורית — כלומר הבוט בסדר והבעיה ב-nginx שלפניו.")
        if any("200 ריק" in k for c in chans for k in c.seg):
            print("  · מקטע שחזר 200 עם גוף ריק. זה בדיוק מה שנגן רואה")
            print("    כתמונה קפואה בלי שום הודעת שגיאה.")
    if any(c.latency for c in chans):
        avg = sum(sum(c.latency) for c in chans) / max(1, sum(len(c.latency) for c in chans))
        worst = max((max(c.latency), c.title) for c in chans if c.latency)
        print(f"  · זמן תגובה ל-playlist: ממוצע {avg:.2f}ש · "
              f"הגרוע ביותר {worst[0]:.1f}ש ({clean(worst[1])})")

    print("\n(כל הכתובות, ה-IP והמזהים צונזרו — אפשר להדביק את הפלט בבטחה.)")


# ── מצב מבט לאחור ────────────────────────────────────────────────────────────
def look_back(a):
    lines = journal(a.min)
    if lines is None:
        sys.exit(f"לא הצלחתי לקרוא את היומן של {SERVICE}. נסה:\n"
                 f"  journalctl -u {SERVICE} --since '{a.min} min ago' | tail -50")

    print(f"חלון: {a.min} דקות · {len(lines)} שורות ביומן\n")
    counts, per_chan, access = Counter(), Counter(), Counter()
    samples = defaultdict(list)

    for ln in lines:
        m = ACCESS.search(ln)
        if m:
            access[m.group(2)] += 1
            continue
        for name, pat in PATTERNS:
            if pat.search(ln):
                counts[name] += 1
                if len(samples[name]) < a.show:
                    samples[name].append(clean(ln.strip())[:170])
                if name.startswith("ffmpeg"):
                    mm = CHAN.search(ln)
                    if mm:
                        per_chan[clean(mm.group(1) or mm.group(2) or "?")[:34]] += 1
                break

    print("── מה נמצא ──")
    if not counts and not access:
        print("  שום דבר מהמשפחות שחיפשתי.")
        print("  שים לב: שתי החריגות של הממסר (502) לא נכתבות ליומן בכלל,")
        print("  ולכן 'לא נמצא כלום' כאן אינו הוכחה שהכול תקין.")
        print(f"  כדי למדוד באמת: python3 live_check.py --watch 10")
    for name, n in counts.most_common():
        print(f"  {n:6}  ({n / max(a.min, 1):5.1f}/דקה)  {name}")
    if access:
        bad = {k: v for k, v in access.items() if not k.startswith("2")}
        print(f"\n  בקשות ל-/hls-relay: {sum(access.values())}"
              + (" · כשלים: " + ", ".join(f"{k}×{v}" for k, v in sorted(bad.items())) if bad else ""))

    if per_chan:
        print("\n── ffmpeg לפי ערוץ (מובילים) ──")
        for ch, n in per_chan.most_common(10):
            print(f"  {n:5}  {ch}")
        spread = len(per_chan)
        print(f"\n  {spread} ערוצים שונים הופיעו.")
        print("  → מרוכז במעט ערוצים: מקורות ספציפיים." if spread <= 5
              else "  → מפוזר על הרבה ערוצים: משאב משותף (רשת/CPU/הספק).")

    for name, _ in PATTERNS:
        if samples[name]:
            print(f"\n── דוגמאות: {name} ──")
            for s in samples[name]:
                print(f"  {s}")

    print("\n(כל הכתובות, ה-IP והמזהים צונזרו — אפשר להדביק את הפלט בבטחה.)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", type=int, default=0,
                    help="מדידה חיה למשך N דקות (מומלץ: 10)")
    ap.add_argument("--min", type=int, default=30, help="מבט לאחור: חלון בדקות")
    ap.add_argument("--show", type=int, default=6, help="כמה דוגמאות לכל סוג")
    ap.add_argument("--channels", type=int, default=6, help="כמה ערוצים לדגום")
    ap.add_argument("--only", default="", help="רק ערוצים ששמם מכיל את זה")
    ap.add_argument("--every", type=float, default=6.0, help="שניות בין דגימות")
    ap.add_argument("--stall", type=float, default=30.0,
                    help="כמה שניות בלי תזוזה נחשבות תקיעה")
    ap.add_argument("--timeout", type=float, default=8.0)
    ap.add_argument("--segments", action="store_true",
                    help="למדוד גם מקטעי וידאו (נמשכים עד הסוף)")
    ap.add_argument("--seg-every", type=float, default=60.0, dest="seg_every")
    ap.add_argument("--include-fix", action="store_true",
                    help="לכלול ערוצי _fix — מדליק ffmpeg, השתמש רק אם צריך")
    ap.add_argument("--no-public", action="store_false", dest="public",
                    help="לא לבדוק דרך הכתובת הציבורית (nginx)")
    a = ap.parse_args()

    if a.watch:
        watch(a)
    else:
        look_back(a)


if __name__ == "__main__":
    main()
