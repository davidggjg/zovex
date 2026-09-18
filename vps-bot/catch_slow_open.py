#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
catch_slow_open — תופס את הפתיחה האיטית *באמצע המעשה*, בלי ריסט.

## למה בלי ריסט

ריסט משמיד את הראיה. המצב המתדרדר נבנה במשך יממה, ואיפוס שלו אומר לחכות
עוד יממה כדי לחזור לאותה נקודה. לכן כל מה שכאן נעשה על התהליך החי.

## מה הוא עושה

פותח זרם בבקשת Range של בייט אחד — מה שמכריח את השרת לעשות את מלוא עבודת
הפתיחה בלי להוריד כלום — ואוסף שתי עדויות על כל פתיחה שנתקעה:

**1. שורות היומן שנכתבו בדיוק בזמן שהיא הייתה תלויה.** זו העדות העיקרית.
הקוד מדווח ליומן בדיוק את האירועים שיכולים להסביר פתיחה איטית — בוט
שנחנק, חיבור מת שמופל, חלון שנכשל רגעית, בריכה שנבנית — וההצלבה עם חלון
הזמן של הפתיחה מצביעה על האירוע ולא רק על העובדה.

**2. ערימות קריאה (py-spy), אם הוא מצליח לקרוא את התהליך.**

## מה למדנו על py-spy כאן, כדי שלא נחזור על זה

ריצה ראשונה על השרת החזירה `run (uvicorn/main.py:621)` בלבד — כלומר לולאת
האירועים. זו לא תקלה: **py-spy אינו יכול לראות קורוטינה שממתינה.** ב-
asyncio בקשה שתקועה על רשת אינה יושבת על שום ערימה, היא מושהית. ערימות
יעזרו רק אם הזמן נשרף ב-CPU, ולכן מ-21 שניות של המתנה לטלגרם הן יראו
בדיוק כלום. הן נשארו בכלי כי "הליבה בלולאת האירועים" הוא עדיין מידע —
הוא מפריד בין "השרת עובד קשה" ל"השרת מחכה" — אבל העדות היא היומן.

py-spy אופציונלי. הוא קורא תהליך חי מבחוץ, בלי שינוי קוד ובלי ריסט:

    pip install py-spy

הצילום נלקח עם --nonblocking, כלומר בלי לעצור את התהליך ולו לרגע. זה קצת
פחות מדויק ולא מסכן צופים באמצע צפייה — הפשרה הנכונה על שרת חי.

    python3 catch_slow_open.py                 # 12 כותרים
    python3 catch_slow_open.py --n 25 --slow 2
"""
import argparse, json, os, random, re, subprocess, sys, threading, time
import urllib.request, urllib.error
from urllib.parse import urlsplit, urlunsplit

UA = "zovex-catch/1"
# רק main.py שלנו. גרסה קודמת סיננה על "main.py" וקלטה גם את
# uvicorn/main.py, ואז כל "ממצא" היה לולאת האירועים.
SELF = re.compile(r"/opt/zovex-bot/main\.py|\bmain\.py:\d")
SERVICE = "zovex-bot"


def find_pid():
    try:
        out = subprocess.run(["systemctl", "show", "zovex-bot", "-p", "MainPID",
                              "--value"], capture_output=True, text=True,
                             timeout=10).stdout.strip()
        if out.isdigit() and int(out) > 0:
            return int(out)
    except Exception:
        pass
    try:
        out = subprocess.run(["pgrep", "-f", "/opt/zovex-bot/main.py"],
                             capture_output=True, text=True, timeout=10).stdout.split()
        if out:
            return int(out[0])
    except Exception:
        pass
    sys.exit("לא מצאתי את התהליך של zovex-bot.")


def have_pyspy():
    try:
        subprocess.run(["py-spy", "--version"], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def dump(pid):
    """ערימות הקריאה של התהליך, בלי לעצור אותו. מחזיר (הצליח, טקסט).

    py-spy יכול להיות מותקן ועדיין להיכשל — הרשאות ptrace, מכל, או גרסת
    פייתון שהוא לא מזהה. גרסה קודמת בלעה את זה והדפיסה "py-spy לא מותקן",
    כלומר שלחה לכיוון הלא נכון בדיוק ברגע שהיה ממצא.
    """
    try:
        r = subprocess.run(["py-spy", "dump", "--nonblocking", "--pid", str(pid)],
                           capture_output=True, text=True, timeout=40)
        if r.returncode != 0 or "Thread" not in (r.stdout or ""):
            # py-spy מדפיס backtrace של Rust באורך 15 שורות. השורה הראשונה
            # היא הסיבה, וכל השאר רעש שמסתיר אותה.
            msg = (r.stderr or r.stdout or "").strip().splitlines()
            return False, (msg[0][:200] if msg else "כשל ללא הודעה")
        return True, r.stdout
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def interesting(text):
    """רק המסגרות מהקוד שלנו. py-spy מדפיס גם את כל הפנימיות של asyncio
    ו-pyrogram, ובלי סינון הפלט הוא מאות שורות שבהן הממצא נעלם."""
    out, seen = [], set()
    for ln in text.splitlines():
        s = ln.strip()
        if SELF.search(s) and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def rewrite_origin(url, origin):
    p, o = urlsplit(url), urlsplit(origin)
    return urlunsplit((o.scheme, o.netloc, p.path, p.query, p.fragment))


# ── היומן, וזו העדות האמיתית ─────────────────────────────────────────────────
# py-spy לא יכול לראות קורוטינה שממתינה: ב-asyncio בקשה שתקועה על רשת אינה
# יושבת על שום ערימה, היא מושהית. ריצה ראשונה החזירה בדיוק את זה — הליבה
# בלולאת האירועים, כלומר "השרת מחכה", וזה נכון אבל לא אומר *למה*.
#
# הקוד עצמו כן מדווח את הרגעים האלה ליומן: בוט שנחנק, חיבור מת שמופל,
# חלון שנכשל רגעית, בריכה שנבנית. לכן העדות היא שורות היומן שנכתבו *בדיוק*
# בזמן שהפתיחה הייתה תלויה.
JOURNAL = []
JLOCK = threading.Lock()
REDACT = [(re.compile(r"https?://[^\s\"'<>]+"), "‹כתובת›"),
          (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "‹IP›")]


def _clean(s):
    for pat, rep in REDACT:
        s = pat.sub(rep, s)
    return s


def follow_journal(stop):
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
            if stop.is_set():
                break
            with JLOCK:
                JOURNAL.append((time.time(), _clean(ln.strip())[:200]))
    except Exception:
        pass
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


def journal_between(t0, t1):
    with JLOCK:
        return [l for ts, l in JOURNAL if t0 - 0.5 <= ts <= t1 + 0.5]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--slow", type=float, default=3.0,
                    help="מאיזה רגע להתחיל לצלם ערימות")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--out", default="/tmp/catch_slow_open.txt")
    a = ap.parse_args()

    pid = find_pid()
    local = "http://127.0.0.1:" + os.environ.get("PORT", "8000")
    print(f"תהליך {pid}")

    # בדיקה מקדימה, לפני 12 פתיחות: מותקן זה לא אותו דבר כמו עובד. בלי זה
    # מגלים רק בסוף הריצה שאין ערימות, ואז צריך להריץ הכל מחדש.
    pyspy_err = None
    if not have_pyspy():
        pyspy = False
        pyspy_err = "py-spy לא מותקן"
    else:
        pyspy, txt = dump(pid)
        if not pyspy:
            pyspy_err = txt
    if pyspy:
        print("py-spy: קורא את התהליך בהצלחה ✓")
    else:
        print(f"py-spy: לא יעבוד — {pyspy_err}")
        print("  בלי זה נמדדים רק הזמנים, בלי לדעת *איפה* הם נשרפים.")
        print("  התקנה:      pip install py-spy")
        print("  הרשאות:     sysctl -w kernel.yama.ptrace_scope=0")
        print("  (שניהם לא דורשים ריסט של הבוט)")

    try:
        with urllib.request.urlopen(local + "/content/lite", timeout=60) as r:
            catalog = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        sys.exit(f"לא הצלחתי למשוך את הקטלוג: {e}")

    cands = [(str(m.get("title") or "?"), rewrite_origin((m.get("video_url") or "").strip(), local))
             for m in catalog
             if not m.get("is_live") and "/stream/" in str(m.get("video_url") or "")]
    if not cands:
        sys.exit("לא נמצאו כותרים עם קישור /stream.")
    random.shuffle(cands)
    items = cands[:a.n]

    stop = threading.Event()
    threading.Thread(target=follow_journal, args=(stop,), daemon=True).start()
    time.sleep(1.0)                      # שיספיק להתחבר ליומן לפני הפתיחה הראשונה

    print(f"{len(items)} פתיחות · עוקב אחרי היומן ומצלם ערימות אחרי {a.slow}ש\n")
    log = open(a.out, "w", encoding="utf-8")
    results, caught, jcaught = [], [], []

    for title, url in items:
        box = {}

        def open_one():
            t = time.time()
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": UA, "Range": "bytes=0-0"})
                with urllib.request.urlopen(req, timeout=a.timeout) as r:
                    r.read(1)
                box["err"] = None
            except Exception as e:
                box["err"] = type(e).__name__
            box["t"] = time.time() - t

        th = threading.Thread(target=open_one, daemon=True)
        t0 = time.time()
        th.start()

        shots = []
        # מצלמים פעמיים בזמן שהבקשה תלויה: פעם בתחילת ההמתנה ופעם בעומקה.
        # צילום אחד יכול לתפוס רגע מקרי; שניים שמצביעים לאותו מקום כבר לא.
        for at in (a.slow, a.slow + 5):
            while th.is_alive() and (time.time() - t0) < at:
                time.sleep(0.2)
            if th.is_alive() and pyspy:
                ok, text = dump(pid)
                if ok:
                    shots.append((round(time.time() - t0, 1), text))
        th.join(timeout=a.timeout + 10)

        t1 = time.time()
        dt = box.get("t", -1)
        err = box.get("err")
        results.append(dt)
        jlines = journal_between(t0, t1) if dt >= a.slow else []
        mark = "🐢" if dt >= a.slow else "  "
        print(f"  {mark} {title[:30]:30} {dt:6.2f}ש" + (f"  ✗ {err}" if err else ""))
        log.write(f"\n===== {title} · {dt:.2f}ש" + (f" · {err}" if err else "") + " =====\n")
        if jlines:
            log.write("--- היומן בזמן שהפתיחה הייתה תלויה ---\n")
            for l in jlines:
                log.write(f"  {l}\n")
            jcaught.append((title, dt, jlines))
            for l in jlines:
                print(f"       יומן: {l[:120]}")
        elif dt >= a.slow:
            print("       יומן: שקט מוחלט לאורך כל ההמתנה")
        for at, text in shots:
            frames = interesting(text)
            log.write(f"--- צילום ב-{at}ש ---\n")
            log.write("\n".join(frames) if frames else "(לא נמצאו מסגרות מהקוד שלנו)")
            log.write("\n")
            if frames:
                caught.append((title, at, frames))

    stop.set()
    log.close()
    ok = [x for x in results if x >= 0]
    slow = [x for x in ok if x >= a.slow]
    print(f"\n── סיכום ──")
    if ok:
        ok_s = sorted(ok)
        print(f"  חציון {ok_s[len(ok_s)//2]:.2f}ש · הגרוע {ok_s[-1]:.2f}ש · "
              f"איטיות ({a.slow}ש+): {len(slow)}/{len(ok)}")

    if jcaught:
        from collections import Counter
        # מנרמלים מספרים כדי ששורות זהות בתוכן יתאחדו לספירה אחת.
        norm = lambda l: re.sub(r"\d+", "N", l)
        c = Counter(norm(l) for _t, _d, ls in jcaught for l in ls)
        print("\n── מה נרשם ביומן בזמן הפתיחות האיטיות ──")
        for line, n in c.most_common(10):
            print(f"  {n:3}×  {line[:110]}")
    elif [x for x in ok if x >= a.slow]:
        print("\n── היומן ──")
        print("  אף שורה לא נכתבה בזמן אף אחת מהפתיחות האיטיות.")
        print("  כלומר הקוד לא חשב שקרה משהו חריג — הוא פשוט חיכה לטלגרם.")

    if caught:
        # מה שחוזר על עצמו בין פתיחות איטיות שונות הוא החשוד. מסגרת שמופיעה
        # פעם אחת היא צירוף מקרים; מסגרת שמופיעה בכל הצילומים היא הבאג.
        from collections import Counter
        c = Counter(f for _t, _a, fr in caught for f in fr)
        print("\n── איפה נשרף הזמן (הכי חוזר על עצמו) ──")
        for frame, n in c.most_common(12):
            print(f"  {n:3}×  {frame[:110]}")
        print(f"\n  הכל בקובץ: {a.out}")
    elif slow and not pyspy:
        print(f"\n  היו {len(slow)} פתיחות איטיות אבל py-spy לא יכול לקרוא")
        print(f"  את התהליך ({pyspy_err}) — יש זמנים, אין מיקום.")
    elif slow:
        print("\n  היו פתיחות איטיות, py-spy עבד, אבל אף מסגרת לא הגיעה")
        print("  מהקוד שלנו. כלומר ההמתנה היא בתוך pyrogram/asyncio —")
        print(f"  הערימות המלאות בקובץ {a.out}.")
    else:
        print("\n  אף פתיחה לא הייתה איטית. אין מה לצלם — ברגע הזה הפתיחה תקינה.")


if __name__ == "__main__":
    main()
