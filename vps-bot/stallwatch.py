#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
עונה על שאלה אחת: **כשזה נתקע עכשיו — למה.**

משאירים את זה רץ בטרמינל, נכנסים לצפות, וברגע שהתמונה נתקעת מסתכלים במסך.

## למה זה נדרש

עד היום חקרנו תקיעות בדיעבד: הצופה מדווח, ואנחנו מנסים לשחזר שעה אחר כך על
מערכת שכבר במצב אחר. זה נכשל שוב ושוב, כי התקיעות **דו-קוטביות** — או מהיר
או תקוע, בלי אמצע — ומצב "תקוע" לא נשאר. צריך לתפוס אותו בזמן אמת.

## מה זה עושה, בו-זמנית

**1. עוקב אחרי היומן** ומסנן רק מה שמסביר תקיעה. כל שורה מתורגמת למה שהיא
אומרת בפועל, לא למחרוזת הגולמית.

**2. מודד בעצמו.** כל כמה שניות מבקש קטע קטן מעומק אקראי בקובץ, דרך
`127.0.0.1` (מדידה מלקוח חיצוני מוגבלת ברוחב הפס של הלקוח — זו מלכודת ג'
ב-STREAMING_DIAGNOSIS.md). זמן התגובה הוא הסימן החי: 0.5 שניות = בריא,
30 שניות = זו התקיעה שהצופה רואה.

**3. סופר בקשות.** uvicorn רושם כל בקשה. אם הנגן ביקש סגמנט ואז שקט של 40
שניות — התקיעה היא בייצור הסגמנט הזה, ולא ברשת של הצופה.

**4. כשנתפסת תקיעה** — מדפיס בלוק מסכם: מה קרה ב-60 השניות שלפניה.

הכל **קריאה בלבד**. לא משנה שום הגדרה ולא מפעיל מחדש כלום.

    python3 stallwatch.py                      # קובץ ברירת המחדל (ונסדיי פרק 1)
    python3 stallwatch.py --movie -100.../8967 # קובץ אחר
    python3 stallwatch.py --probe 0            # בלי מדידה עצמית, רק יומן
"""
import argparse, json, os, random, re, shutil, signal, subprocess, sys, threading, time
from collections import deque

LOCAL = "http://127.0.0.1:8000"
DEFAULT_MOVIE = "-1003936100530/8967"          # ונסדיי עונה 1 פרק 1

# ── מה שנחשב הסבר לתקיעה ────────────────────────────────────────────────────
# כל דפוס והמשמעות שלו. הסדר חשוב: הראשון שמתאים קובע.
PATTERNS = [
    (r"FloodWait", "🚦 טלגרם מגביל אותנו (FloodWait)", 3),
    (r"Send exception|TCPTransport closed",
     "💀 חיבור מת לטלגרם (Send exception)", 2),
    (r"Session started", "🔌 חיבור חדש לטלגרם נבנה", 1),
    (r"Session stopped", "🔻 חיבור לטלגרם נסגר", 1),
    (r"Retrying", "🔁 בקשה לטלגרם לא חזרה בזמן, מנסה שוב", 2),
    (r"נכשל סופית|ויתר", "❌ חלון נזנח אחרי כל הניסיונות", 3),
    (r"חלון .*ניסיון|קריאה-מראש", "🪟 חלון נמשך מחדש", 2),
    (r"choke|חנוק", "🥶 בוט נחנק והוצא מהמחזור", 3),
    (r"🩺", "🩺 בדיקת בריאות לבריכה", 1),
    (r"vodfix", "🎬 מסלול תיקון ה-VOD", 2),
    (r"hls_fix", "📺 צינור הערוצים החיים", 2),
    (r"FileReferenceExpired", "🔑 מזהה הקובץ פג — נמשך מחדש", 2),
    (r"Traceback|ERROR", "🔥 שגיאה", 3),
]

REQ = re.compile(r'"(GET|POST) (\S+) HTTP/[\d.]+" (\d{3})')

STALL_SECONDS = 6.0        # תגובה איטית מזה = תקיעה שהצופה מרגיש
QUIET_SECONDS = 20.0       # שקט ארוך מזה אחרי בקשה = הנגן ממתין


class Recent:
    """מה קרה לאחרונה, לשליפה כשנתפסת תקיעה."""

    def __init__(self, seconds=60):
        self.seconds = seconds
        self.items = deque(maxlen=400)
        self.lock = threading.Lock()

    def add(self, kind, text):
        with self.lock:
            self.items.append((time.time(), kind, text))

    def window(self):
        cut = time.time() - self.seconds
        with self.lock:
            return [x for x in self.items if x[0] >= cut]


recent = Recent()
stop = threading.Event()
state = {"last_req": 0.0, "last_req_path": "", "stalls": 0, "probes": 0,
         "slow": 0, "worst": 0.0}


def clock(t=None):
    return time.strftime("%H:%M:%S", time.localtime(t or time.time()))


def emit(icon, text, weight=1):
    line = f"{clock()}  {icon} {text}"
    print(line, flush=True)
    recent.add(weight, text)


def follow_journal():
    """עוקב אחרי יומן השירות ומתרגם רק את מה שמסביר תקיעה."""
    if not shutil.which("journalctl"):
        emit("⚠️", "אין journalctl — מעקב היומן מושבת")
        return
    p = subprocess.Popen(
        ["journalctl", "-u", "zovex-bot", "-n", "0", "-f", "--no-pager"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        bufsize=1)
    try:
        for line in p.stdout:
            if stop.is_set():
                break
            line = line.rstrip()
            m = REQ.search(line)
            if m:
                path, code = m.group(2), m.group(3)
                gap = time.time() - state["last_req"] if state["last_req"] else 0
                state["last_req"] = time.time()
                state["last_req_path"] = path
                short = path.split("?")[0]
                if gap > QUIET_SECONDS:
                    emit("🕳️", f"שקט של {gap:.0f} שניות לפני {short} "
                               f"— הנגן חיכה כל הזמן הזה", 3)
                    dump_window(f"שקט של {gap:.0f} שניות")
                elif code != "200" and code != "206":
                    emit("⚠️", f"{short} → {code}", 3)
                continue
            for pat, meaning, weight in PATTERNS:
                if re.search(pat, line):
                    if weight >= 2:
                        emit("│", meaning, weight)
                    else:
                        recent.add(weight, meaning)
                    break
    finally:
        try:
            p.kill()
        except Exception:
            pass


def probe_loop(movie, every):
    """מודד בעצמו: קטע קטן מעומק אקראי, דרך 127.0.0.1."""
    url = f"{LOCAL}/stream/{movie}"
    size = None
    # הקישור חתום; מושכים אחד טרי מהקטלוג של השרת עצמו
    try:
        raw = subprocess.run(["curl", "-sS", "--noproxy", "127.0.0.1", "--max-time", "60",
                              f"{LOCAL}/movies.json"], capture_output=True).stdout
        cat = json.loads(raw)
        chat, msg = movie.split("/")
        for m in cat:
            if str(m.get("channel_id")) == chat and str(m.get("channel_msg_id")) == msg:
                url = m["video_url"].replace("https://zovex.duckdns.org", LOCAL)
                break
    except Exception as e:
        emit("⚠️", f"לא הצלחתי לקחת קישור חתום מהקטלוג ({e}) — מנסה בלי")

    txt = subprocess.run(["curl", "-sS", "--noproxy", "127.0.0.1", "-D", "-", "-o", "/dev/null",
                          "--max-time", "40", "-H", "Range: bytes=0-1", url],
                         capture_output=True, text=True).stdout
    for l in txt.splitlines():
        if l.lower().startswith("content-range"):
            try:
                size = int(l.rsplit("/", 1)[1])
            except ValueError:
                pass
    if not size:
        emit("⚠️", "לא הצלחתי לקבל את גודל הקובץ — המדידה העצמית מושבתת")
        return
    emit("📏", f"מודד כל {every} שניות: 256KB מעומק אקראי "
               f"({size / 1048576:.0f}MB)")

    while not stop.is_set():
        off = random.randint(0, max(0, size - 300000))
        t0 = time.time()
        r = subprocess.run(
            ["curl", "-sS", "--noproxy", "127.0.0.1", "-o", "/dev/null",
             "--max-time", "90",
             "-w", "%{time_starttransfer} %{http_code} %{size_download}",
             "-H", f"Range: bytes={off}-{off + 262143}", url],
            capture_output=True, text=True)
        dt = time.time() - t0
        parts = r.stdout.split()
        ttfb = float(parts[0]) if parts and parts[0][0].isdigit() else dt
        code = parts[1] if len(parts) > 1 else "?"
        got = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        state["probes"] += 1
        state["worst"] = max(state["worst"], ttfb)

        depth = off / size * 100
        if ttfb >= STALL_SECONDS or code not in ("200", "206") or got == 0:
            state["slow"] += 1
            emit("🛑", f"תגובה אחרי {ttfb:.1f} שניות "
                       f"(עומק {depth:.0f}%, קוד {code}, {got // 1024}KB) "
                       f"— זו התקיעה", 3)
            dump_window(f"תגובה של {ttfb:.1f} שניות")
        else:
            recent.add(1, f"מדידה תקינה {ttfb:.1f}ש' בעומק {depth:.0f}%")
            print(f"{clock()}  ·  {ttfb:.1f}ש'  עומק {depth:.0f}%",
                  flush=True)
        stop.wait(every)


def dump_window(why):
    """מה קרה ב-60 השניות שלפני הרגע הזה."""
    items = recent.window()
    state["stalls"] += 1
    print()
    print("┌─ " + f"תקיעה #{state['stalls']}: {why}")
    print("│  60 השניות שקדמו לה:")
    if not items:
        print("│    (שום דבר ביומן — כלומר אף רכיב לא דיווח על בעיה,")
        print("│     והעיכוב הוא בהמתנה לטלגרם בלי שגיאה)")
    else:
        counts = {}
        for t, w, text in items:
            counts[text] = counts.get(text, 0) + 1
        for text, c in sorted(counts.items(), key=lambda kv: -kv[1])[:12]:
            print(f"│    {c:3}×  {text}")
    print("└─" + "─" * 50)
    print(flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--movie", default=DEFAULT_MOVIE,
                    help="chat/msg למדידה העצמית")
    ap.add_argument("--probe", type=float, default=5.0,
                    help="שניות בין מדידות. 0 = בלי מדידה עצמית.")
    a = ap.parse_args()

    print("─" * 60)
    print("  צופה בתקיעות. תשאיר את זה פתוח, תיכנס לצפות,")
    print("  וכשהתמונה נתקעת תסתכל כאן.")
    print("  ליציאה: Ctrl+C")
    print("─" * 60, flush=True)

    threads = [threading.Thread(target=follow_journal, daemon=True)]
    if a.probe > 0:
        threads.append(threading.Thread(target=probe_loop,
                                        args=(a.movie, a.probe), daemon=True))
    for t in threads:
        t.start()

    def bye(*_):
        stop.set()
    signal.signal(signal.SIGINT, bye)

    try:
        while not stop.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        stop.set()

    print()
    print("─" * 60)
    print(f"  מדידות: {state['probes']}   ·   מהן איטיות: {state['slow']}"
          f"   ·   הגרועה: {state['worst']:.1f} שניות")
    print(f"  תקיעות שנתפסו: {state['stalls']}")
    if state["probes"] and not state["slow"]:
        print("  לא נתפסה אף תקיעה במדידה — אם ראית תקיעה בזמן הזה,")
        print("  היא לא במשיכה מטלגרם אלא אצל הצופה או בנגן.")
    print("─" * 60)


if __name__ == "__main__":
    main()
