#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מריצים **ברגע שנתקע**, ומקבלים למה.

אין צורך להריץ מראש: היומן של השירות כבר שמור, ולכן אפשר להסתכל אחורה. מה
שכן חייב להימדד עכשיו הוא המצב החי — ולכן הסקריפט גם מודד בעצמו בזמן שאתה
עדיין תקוע.

    python3 whystuck.py            # שלוש הדקות האחרונות
    python3 whystuck.py --min 10   # עשר הדקות האחרונות

מה נבדק, לפי הסדר:

**1. עכשיו** — שלוש משיכות של 256KB מעומק אקראי דרך `127.0.0.1`. מדידה מלקוח
חיצוני מוגבלת ברוחב הפס של הלקוח, ולכן חסרת ערך (מלכודת ג' ב-
STREAMING_DIAGNOSIS.md). זה המבחן שמפריד בין "השרת תקוע" ל"הקליטה שלך".

**2. אחורה ביומן** — כל מה שיכול להסביר תקיעה, מתורגם למשמעות.

**3. הבקשות** — אם הנגן ביקש משהו ואז היה שקט של 40 שניות, התקיעה בייצור
התשובה ולא ברשת של הצופה.

**4. פסק דין** — מה הנתונים אומרים, ומה הם *לא* אומרים.

קריאה בלבד. לא משנה כלום ולא מפעיל כלום מחדש.
"""
import argparse, json, random, re, shutil, subprocess, sys, time
from collections import Counter, defaultdict

LOCAL = "http://127.0.0.1:8000"
DEFAULT_MOVIE = "-1003936100530/8967"      # ונסדיי עונה 1 פרק 1

PATTERNS = [
    # ── ענפי הכישלון של החלון, לפי הסדר שבקוד. הסדר כאן חשוב: ההתאמה
    #    הראשונה קובעת, ולכן המדויקות חייבות לבוא לפני הכלליות.
    (r"חרג מתקציב הקיר",
     "🧱 חלון הגיע לקיר (30ש') — מכאן הגוף נמסר קטוע"),
    (r"timeouts רצופים",
     "♻️ בריכת חיבורים הופלה אחרי timeouts רצופים"),
    (r"חיבור מת: .*מרענן",
     "💀 חיבור מת → הבריכה רועננה"),
    (r"חלון איטי \(timeout",
     "🐌 חלון איטי (timeout בודד — הקוד מתעלם בכוונה)"),
    (r"חלון נכשל רגעית",
     "🌤 כשל רגעי (FloodWait/reference) — נפילה למסלול גיבוי"),
    (r"חלון .*נכשל \(\d+/\d+",
     "🔁 ניסיון חוזר לחלון"),
    (r"קריאה-מראש נכשלה",
     "📖 קריאה-מראש נכשלה — נמשך ישירות"),
    (r"FloodWait", "🚦 טלגרם הגביל אותנו (FloodWait)"),
    (r"Send exception|TCPTransport closed", "💀 חיבור מת לטלגרם"),
    (r"Retrying", "🔁 בקשה לטלגרם לא חזרה בזמן, ניסיון נוסף"),
    (r"choke|חנוק", "🥶 בוט נחנק והוצא מהמחזור"),
    (r"FileReferenceExpired", "🔑 מזהה הקובץ פג ונמשך מחדש"),
    (r"Session started", "🔌 חיבור חדש לטלגרם נבנה"),
    (r"Session stopped", "🔻 חיבור לטלגרם נסגר"),
    (r"🩺", "🩺 בדיקת בריאות לבריכה"),
    (r"vodfix", "🎬 מסלול תיקון ה-VOD"),
    (r"hls_fix", "📺 צינור הערוצים החיים"),
    (r"Traceback|CRITICAL|ERROR", "🔥 שגיאה"),
]

REQ = re.compile(r'"(?:GET|POST) (\S+) HTTP/[\d.]+" (\d{3})')
TS = re.compile(r"^(\w{3} \d{2} \d{2}:\d{2}:\d{2})")
# journald מקדים לכל שורה חותמת, מארח ושם התהליך. בלי להסיר אותה, ההזחה
# של ה-traceback לא נראית ואי אפשר לזהות איפה הוא נגמר.
PREFIX = re.compile(r"^\w{3} \d{2} [\d:]{8} \S+ [^:]+?(?:\[\d+\])?: ")
FRAME = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')

CURL = ["curl", "-sS", "--noproxy", "127.0.0.1"]


def signed_url(movie):
    """קישור חתום טרי מהקטלוג של השרת עצמו, מופנה ל-127.0.0.1."""
    try:
        raw = subprocess.run(CURL + ["--max-time", "60", f"{LOCAL}/movies.json"],
                             capture_output=True).stdout
        chat, msg = movie.split("/")
        for m in json.loads(raw):
            if (str(m.get("channel_id")) == chat
                    and str(m.get("channel_msg_id")) == msg):
                return m["video_url"].replace("https://zovex.duckdns.org", LOCAL)
    except Exception:
        pass
    return f"{LOCAL}/stream/{movie}"


def measure_now(movie, n=3):
    print("─" * 62)
    print("1 · מה קורה **ברגע זה** (דרך 127.0.0.1, לא דרך האינטרנט)")
    print("─" * 62)
    url = signed_url(movie)
    txt = subprocess.run(CURL + ["-D", "-", "-o", "/dev/null", "--max-time", "40",
                                 "-H", "Range: bytes=0-1", url],
                         capture_output=True, text=True).stdout
    size = None
    for l in txt.splitlines():
        if l.lower().startswith("content-range"):
            try:
                size = int(l.rsplit("/", 1)[1])
            except ValueError:
                pass
    if not size:
        print("   ❌ אין תשובה מ-127.0.0.1:8000.")
        print("      או שהשירות למטה (systemctl status zovex-bot),")
        print("      או שאתה לא מריץ את זה על השרת עצמו.")
        return []
    times = []
    for i in range(n):
        off = random.randint(0, max(0, size - 300000))
        r = subprocess.run(
            CURL + ["-o", "/dev/null", "--max-time", "90",
                    "-w", "%{time_starttransfer} %{http_code} %{size_download}",
                    "-H", f"Range: bytes={off}-{off + 262143}", url],
            capture_output=True, text=True)
        p = r.stdout.split()
        try:
            ttfb = float(p[0]); code = p[1]; got = int(p[2])
        except (IndexError, ValueError):
            ttfb, code, got = 999.0, "?", 0
        times.append(ttfb)
        mark = "🛑" if (ttfb >= 6 or got == 0) else ("⚠️" if ttfb >= 2 else "✓")
        print(f"   {mark} {ttfb:6.1f} שניות   עומק {off / size * 100:3.0f}%"
              f"   קוד {code}   {got // 1024}KB")
    return times


def read_journal(minutes):
    print()
    print("─" * 62)
    print(f"2 · מה היומן אומר על {minutes} הדקות האחרונות")
    print("─" * 62)
    if not shutil.which("journalctl"):
        print("   ❌ אין journalctl")
        return None, None
    out = subprocess.run(
        ["journalctl", "-u", "zovex-bot", "--since", f"{minutes} min ago",
         "--no-pager", "-o", "short"],
        capture_output=True, text=True).stdout.splitlines()
    if not out:
        print("   היומן ריק לחלון הזה.")
        return Counter(), []

    counts = Counter()
    reqs = []
    errors = Counter()
    tracebacks = Counter()      # (החריגה, המסגרת האחרונה ב-main.py) → כמה
    tb_lines, in_tb = [], False
    churn = defaultdict(Counter)      # דקה → {נסגר, נבנה, מת}
    for raw in out:
        line = raw
        body = PREFIX.sub("", raw)

        # ── איסוף traceback שלם ─────────────────────────────────────────
        if in_tb:
            if body.startswith(("  ", "\t")) or body.startswith("Traceback"):
                tb_lines.append(body)
                continue
            # השורה הראשונה שאינה מוזחת היא החריגה עצמה — כאן ה-traceback נגמר
            exc = re.sub(r"0x[0-9a-f]+|\b\d{6,}\b", "…", body.strip())[:120]
            # שם הקובץ האמיתי, לא תווית קבועה. הגרסה הקודמת הדפיסה
            # "main.py:" לכל מסגרת שהנתיב שלה הכיל "zovex" — וזה תופס גם
            # ספריות שמותקנות תחת /opt/zovex-bot/venv. כך שורות של pyrogram
            # הוצגו כאילו הן הקוד שלנו.
            ours, last = "", ""
            for fr in FRAME.finditer("\n".join(tb_lines)):
                path, ln, fn = fr.group(1), fr.group(2), fr.group(3)
                base = path.rsplit("/", 1)[-1]
                lib = ""
                for marker in ("site-packages/", "dist-packages/"):
                    if marker in path:
                        lib = path.split(marker, 1)[1].split("/")[0]
                last = f"{base}:{ln} ב-{fn}" + (f"   [{lib}]" if lib else "")
                if base == "main.py" and "packages/" not in path:
                    ours = f"main.py:{ln} ב-{fn}"
            mine = ours or (last + ("  ← לא הקוד שלנו" if "[" in last else ""))
            tracebacks[(exc, mine)] += 1
            in_tb, tb_lines = False, []
            # ממשיכים לסווג את השורה הזאת כרגיל
        elif "Traceback (most recent call last)" in body:
            in_tb, tb_lines = True, [body]
            counts["🔥 שגיאה"] += 1
            continue

        m = REQ.search(line)
        if m:
            reqs.append((TS.match(line).group(1) if TS.match(line) else "",
                         m.group(1).split("?")[0], m.group(2)))
            continue
        stamp = TS.match(line)
        minute = stamp.group(1)[:-3] if stamp else ""
        if "Session stopped" in line:
            churn[minute]["נסגר"] += 1
        elif "Session started" in line:
            churn[minute]["נבנה"] += 1
        elif "Send exception" in line or "TCPTransport closed" in line:
            churn[minute]["מת"] += 1
        for pat, meaning in PATTERNS:
            if re.search(pat, line):
                counts[meaning] += 1
                if meaning.startswith("🔥"):
                    # הטקסט עצמו, בלי החותמת והמארח — כדי שנוכל לאחד כפילויות
                    txt = re.sub(r"^[A-Za-z]{3} \d{2} [\d:]{8} \S+ \S+?: ", "", line)
                    txt = re.sub(r"0x[0-9a-f]+|\b\d{5,}\b", "…", txt)
                    errors[txt.strip()[:150]] += 1
                break
    print(f"   {len(out)} שורות ביומן · {len(reqs)} בקשות")
    print()
    if counts:
        for meaning, c in counts.most_common(14):
            print(f"   {c:5}×  {meaning}")
    else:
        print("   שום דבר ביומן שמסביר תקיעה.")
        print("   זה ממצא בפני עצמו: אף רכיב לא דיווח על תקלה, כלומר")
        print("   ההמתנה היא לטלגרם והיא לא מרימה שגיאה בכלל.")
    if tracebacks:
        print()
        print("   השגיאות עצמן — מה נזרק ואיפה:")
        for (exc, mine), c in tracebacks.most_common(8):
            print(f"   {c:5}×  {exc}")
            if mine:
                print(f"          └─ {mine}")
    leftovers = {t: c for t, c in errors.items()
                 if "Traceback" not in t and t.strip()}
    if leftovers:
        print()
        print("   שורות שגיאה נוספות:")
        for txt, c in sorted(leftovers.items(), key=lambda kv: -kv[1])[:6]:
            print(f"   {c:5}×  {txt}")

    if churn:
        rows = sorted(churn.items())
        interesting = [r for r in rows if sum(r[1].values()) > 0]
        if interesting:
            print()
            print("   מחזור החיבורים, לפי דקה:")
            print("        דקה        נסגר   נבנה    מת")
            for minute, c in interesting[-10:]:
                print(f"   {minute:>14}  {c['נסגר']:6} {c['נבנה']:6} {c['מת']:5}")
            tot_stop = sum(c["נסגר"] for _, c in rows)
            tot_start = sum(c["נבנה"] for _, c in rows)
            if tot_stop > 50 and tot_stop > tot_start * 1.3:
                print()
                print(f"   ⚠️  נסגרו {tot_stop} וניבנו {tot_start} — נסגרים מהר")
                print("       יותר ממה שנבנים. הבריכה מתכווצת בזמן אמת.")
    chain(counts, sum(c for (e, _), c in tracebacks.items()
                      if "shorter than Content-Length" in e))
    return counts, reqs


def chain(counts, tracebacks_seen):
    """קושר את ענפי הכישלון לתקיעה שהצופה רואה."""
    wall = sum(c for k, c in counts.items() if k.startswith("🧱"))
    short = tracebacks_seen
    if not (wall or short):
        return
    print()
    print("   ── מה זה עשה לצופה ─────────────────────────────────────")
    print(f"   {wall:5}×  חלון הגיע לקיר של 30 שניות")
    print(f"   {short:5}×  תשובה נמסרה קטועה")
    print("          זו התנהגות מכוונת: הקוד מעדיף גוף קטוע על שתיקה")
    print("          ארוכה, בהנחה שהנגן יבקש שוב. כל אחת כזאת היא")
    print("          הרגע שבו הצופה רואה ספינר.")


def read_gaps(reqs):
    print()
    print("─" * 62)
    print("3 · פערים בין בקשות")
    print("─" * 62)
    print("   ⚠️  /stream מחזיר תשובה מזרימה: בקשה אחת יכולה לרוץ חצי שעה")
    print("       בלי לרשום עוד שורה. לכן פער כאן אינו תקיעה — הוא רק אומר")
    print("       שלא התחילה בקשה חדשה. לקריאה בלבד, לא כראיה.")
    if not reqs:
        print("   אין בקשות בחלון הזה. הנגן לא ביקש כלום —")
        print("   כלומר הוא לא הגיע לשרת בכלל.")
        return []
    def secs(t):
        try:
            h, m, s = t.split()[-1].split(":")
            return int(h) * 3600 + int(m) * 60 + int(s)
        except Exception:
            return None
    gaps = []
    for i in range(1, len(reqs)):
        a, b = secs(reqs[i - 1][0]), secs(reqs[i][0])
        if a is None or b is None:
            continue
        d = b - a
        if d < 0:
            d += 86400
        if d >= 15:
            gaps.append((d, reqs[i - 1], reqs[i]))
    if not gaps:
        print("   אין פער מעל 15 שניות. הבקשות זרמו ברצף.")
    else:
        for d, before, after in sorted(gaps, reverse=True)[:8]:
            print(f"   🕳️  {d:4} שניות שקט")
            print(f"        אחרי:  {before[0]}  {before[1]} → {before[2]}")
            print(f"        ואז:   {after[0]}  {after[1]} → {after[2]}")
    bad = [r for r in reqs if r[2] not in ("200", "206", "304")]
    if bad:
        print()
        print(f"   בקשות שנכשלו ({len(bad)}):")
        for t, path, code in bad[-8:]:
            print(f"      {t}  {path} → {code}")
    return gaps


def verdict(times, counts, gaps):
    print()
    print("─" * 62)
    print("4 · פסק דין")
    print("─" * 62)
    slow = [t for t in times if t >= 6]
    if times and not slow and max(times) < 2:
        print("   השרת עונה מהר **עכשיו** ({:.1f}ש' הכי גרוע).".format(max(times)))
        if gaps:
            print("   (הפערים בסעיף 3 אינם ראיה — ראה האזהרה שם.)")
            print()
        else:
            print()
            print("   ⇒ המשיכה מטלגרם תקינה. אם ראית תקיעה בזמן הזה, היא")
            print("     אצל הצופה — קליטה, נגן, או המכשיר. זה מוציא את")
            print("     השרת מהחשד, וזו תשובה שווה בדיוק כמו כל אחרת.")
    elif slow:
        print(f"   השרת איטי **עכשיו**: {len(slow)} מתוך {len(times)} מדידות "
              f"מעל 6 שניות, הגרועה {max(times):.1f}.")
        print()
        print("   ⇒ התקיעה בשרת, והיא חיה ברגע זה. מה שרשום בסעיף 2 הוא")
        print("     ההסבר — תשלח לי את זה.")
    else:
        print("   לא הצלחתי למדוד. תסתכל בסעיף 2.")

    if counts:
        dead = sum(c for k, c in counts.items() if "חיבור מת" in k)
        started = sum(c for k, c in counts.items() if "חיבור חדש" in k)
        if dead > 20 and started == 0:
            print()
            print(f"   ⚠️  {dead} חיבורים מתים ו-{started} חיבורים חדשים.")
            print("      חיבורים מתים ואף אחד לא בונה אותם מחדש — זה")
            print("      החשוד המרכזי שנשאר פתוח ב-STREAMING_DIAGNOSIS.md.")
    print("─" * 62)


def dump_full(minutes, n):
    """N שגיאות במלואן, כלשונן. ספירה לא מספיקה כדי לדעת מי קרא למי."""
    out = subprocess.run(
        ["journalctl", "-u", "zovex-bot", "--since", f"{minutes} min ago",
         "--no-pager", "-o", "short"],
        capture_output=True, text=True).stdout.splitlines()
    shown, block, inside = 0, [], False
    for raw in out:
        body = PREFIX.sub("", raw)
        if inside:
            block.append(body)
            if not body.startswith(("  ", "\t")) and not body.startswith("Traceback"):
                print("═" * 62)
                print("\n".join(block))
                print()
                shown += 1
                inside, block = False, []
                if shown >= n:
                    return
        elif "Traceback (most recent call last)" in body:
            inside, block = True, [body]
    if not shown:
        print(f"לא נמצאה אף שגיאה ב-{minutes} הדקות האחרונות.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=3, help="כמה דקות אחורה")
    ap.add_argument("--movie", default=DEFAULT_MOVIE)
    ap.add_argument("--full", type=int, default=0, metavar="N",
                    help="להדפיס N שגיאות במלואן, כלשונן. זה מה שמראה "
                         "את שרשרת הקריאות שהובילה לשגיאה.")
    a = ap.parse_args()
    print()
    print(f"למה זה נתקע — {time.strftime('%H:%M:%S')}")
    if a.full:
        dump_full(a.min, a.full)
        return
    times = measure_now(a.movie)
    counts, reqs = read_journal(a.min)
    gaps = read_gaps(reqs) if reqs is not None else []
    verdict(times, counts or Counter(), gaps)
    print()


if __name__ == "__main__":
    main()
