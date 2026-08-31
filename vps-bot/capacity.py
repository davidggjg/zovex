#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
כמה צופים במקביל השרת מחזיק — ומי נשבר ראשון.

השאלה "כמה אנשים יכולים לצפות ביחד" אין לה תשובה אחת, כי יש שלוש תקרות
נפרדות והן נפגעות בסדר שונה בכל שרת:

    קו היציאה   כמה מגהביט אפשר לדחוף החוצה לצופים. בוטים לא מזיזים את זה.
    טלגרם       FloodWait, בוטים שנחנקים, רצועות מדיה שמתחרות. *כאן* בוטים עוזרים.
    מעבד        רלוונטי לערוצים חיים (ffmpeg של _fix), לא לסרטים.

לכן הכלי לא מחזיר מספר יחיד אלא מוצא איפה זה נשבר ולמה. הוא מדמה צופים
אמיתיים — כל אחד סרט אחר, כל אחד מושך *בקצב של נגן* ולא במלוא המהירות
(משיכה מהירה יוצרת עומס אחר לגמרי ולא משחזרת צפייה) — מעלה את מספרם בשלבים,
ואחרי כל שלב סופר ביומן השרת מה קרה שם.

מה נחשב הצלחה: לא "התקבלו בייטים" אלא "הנגן היה שורד". צופה נחשב תקין אם
קיבל לפחות 97% ממה שנגן היה צורך *ולא* חווה שתיקה ארוכה מ-STALL שניות —
כי שתיקה כזאת מרוקנת את הבאפר, וזה בדיוק מה שהמשתמש מרגיש כתקיעה.

    python3 capacity.py                        # 5 → 10 → 20 → 30
    python3 capacity.py --levels 10,25,50
    python3 capacity.py --seconds 180          # שלב ארוך יותר, אמין יותר
    python3 capacity.py --mbps 8               # אם התוכן שלך בקצב גבוה יותר
"""
import argparse, json, pathlib, random, statistics, subprocess, sys
import threading, time, urllib.request, urllib.error

LOCAL = "http://127.0.0.1:8000"
SITE = "https://zovex.duckdns.org"
LOG = pathlib.Path("/opt/zovex-bot/capacity.log")
UA = ("Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
      "Chrome/120 Mobile Safari/537.36")

# חיפוש התקלות שמעיד איזו תקרה נפגעה. כל קבוצה = חשוד אחר.
SIGNALS = {
    "טלגרם — בוט נחנק":      ("נחנק", "FloodWait", "flood"),
    "טלגרם — רצועות נכשלו":  ("media bands", "subrange", "GetFile"),
    "חיבורים נופלים":        ("Session stopped", "Send exception", "TCPTransport"),
    "חלון ויתר (הריכוך)":    ("ויתר אחרי", "חלון .* נכשל"),
}


def say(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── מצב המכונה ───────────────────────────────────────────────────────────────

def nic():
    """שם הממשק הפעיל ומהירות הקו שלו (Mbps), או 0 אם לא ידועה.

    הרבה VPS-ים לא חושפים speed בכלל (virtio מחזיר -1 או קובץ שלא ניתן
    לקריאה). בחירה לפי speed בלבד הייתה מחזירה "אין ממשק" ומפילה את כל
    הבדיקה, ולכן הבחירה היא לפי הממשק שבאמת העביר הכי הרבה תעבורה."""
    best, best_tx, speed = None, -1, 0
    root = pathlib.Path("/sys/class/net")
    for p in sorted(root.iterdir()):
        if p.name == "lo":
            continue
        try:
            if (p / "operstate").read_text().strip() not in ("up", "unknown"):
                continue
        except Exception:
            continue
        tx = net_counters(p.name)[1]
        if tx > best_tx:
            try:
                sp = int((p / "speed").read_text().strip())
            except Exception:
                sp = 0
            best, best_tx, speed = p.name, tx, max(0, sp)
    return best, speed


def net_counters(dev):
    """בייטים שנכנסו/יצאו מאז עליית המכונה, מהמונה של הליבה."""
    for line in pathlib.Path("/proc/net/dev").read_text().splitlines():
        if ":" not in line:
            continue
        name, rest = line.split(":", 1)
        if name.strip() != dev:
            continue
        f = rest.split()
        return int(f[0]), int(f[8])          # rx, tx
    return 0, 0


def cpu_busy():
    """אחוז תפוסה של המעבד מאז הקריאה הקודמת (שומר מצב בין קריאות)."""
    f = pathlib.Path("/proc/stat").read_text().split("\n")[0].split()[1:]
    v = [int(x) for x in f]
    idle, total = v[3] + v[4], sum(v)
    prev = cpu_busy.__dict__.get("prev")
    cpu_busy.prev = (idle, total)
    if not prev:
        return None
    di, dt = idle - prev[0], total - prev[1]
    return 100.0 * (1 - di / dt) if dt > 0 else None


def journal_since(t0):
    """סופר ביומן השרת רק את מה שקרה *במהלך* השלב הזה."""
    since = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0))
    try:
        out = subprocess.run(
            ["journalctl", "-u", "zovex-bot", "--since", since, "--no-pager"],
            capture_output=True, text=True, timeout=45).stdout
    except Exception:
        return {}
    import re
    counts = {}
    for label, pats in SIGNALS.items():
        n = sum(len(re.findall(p, out)) for p in pats)
        if n:
            counts[label] = n
    return counts


# ── קטלוג ────────────────────────────────────────────────────────────────────

def catalog():
    """הקישורים חייבים לבוא מ-/movies.json ולא מ-content.json: בקובץ יושב
    מציין המקום %BASE% והחתימה נוספת רק בהגשה. קריאה מהקובץ מחזירה מחרוזת
    שאינה URL, וכל הבדיקה מתה מיד."""
    last = None
    for base in (LOCAL, SITE):
        try:
            req = urllib.request.Request(base + "/movies.json",
                                         headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read().decode("utf-8"))
            items = data if isinstance(data, list) else data.get("movies", [])
            pool = [m for m in items
                    if "/stream/" in (m.get("video_url") or "")
                    and (m.get("video_url") or "").startswith("http")
                    and not m.get("series_name")
                    and m.get("category") != "שידורים חיים"]
            if pool:
                return pool
            last = f"{base}: הקטלוג נטען אבל אין בו פריט מתאים"
        except Exception as e:
            last = f"{base}: {type(e).__name__}: {e}"
    sys.exit(f"לא ניתן למשוך קטלוג. אחרון: {last}")


# ── צופה מדומה ───────────────────────────────────────────────────────────────

class Viewer(threading.Thread):
    """מושך סרט בקצב של נגן, ורושם לא רק כמה קיבל אלא גם את השתיקה הארוכה
    ביותר — כי זה מה שמפיל צפייה, לא הממוצע."""

    def __init__(self, title, url, seconds, rate, stall, start_gate):
        super().__init__(daemon=True)
        self.title, self.url = title, url
        self.seconds, self.rate, self.stall_limit = seconds, rate, stall
        self.gate = start_gate
        self.got = 0
        self.max_gap = 0.0
        self.ttfb = None
        self.error = None
        self.needed = 0

    def run(self):
        self.gate.wait()                      # כולם יוצאים יחד — זה העומס
        t0 = time.time()
        try:
            req = urllib.request.Request(self.url, headers={
                "User-Agent": UA, "Referer": SITE + "/", "Range": "bytes=0-"})
            r = urllib.request.urlopen(req, timeout=90)
            self.ttfb = time.time() - t0
            while True:
                now = time.time()
                el = now - t0
                if el > self.seconds:
                    break
                allowed = int(el * self.rate)
                if self.got >= allowed:
                    time.sleep(0.2)           # אנחנו ממתינים בכוונה, לא השרת
                    continue
                # השתיקה נמדדת *סביב* הקריאה ולא אחריה. read() חוסם כל עוד
                # השרת שותק, ולכן חישוב הפער אחרי שהוא חוזר נותן תמיד ~0 —
                # בדיוק התקלה שאנחנו מחפשים הייתה נעלמת מהמדידה.
                r_t0 = time.time()
                chunk = r.read(min(262144, allowed - self.got))
                gap = time.time() - r_t0
                if gap > self.max_gap:
                    self.max_gap = gap
                if not chunk:
                    self.error = "הגוף נסגר מוקדם"
                    break
                self.got += len(chunk)
        except urllib.error.HTTPError as e:
            self.error = f"HTTP {e.code}"
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
        el = max(0.001, time.time() - t0)
        self.needed = int(min(el, self.seconds) * self.rate)

    @property
    def ok(self):
        if self.error:
            return False
        if self.max_gap > self.stall_limit:
            return False
        return self.needed == 0 or self.got >= 0.97 * self.needed


# ── שלב ──────────────────────────────────────────────────────────────────────

def run_level(n, pool, seconds, rate, stall, dev):
    say("")
    say("─" * 60)
    say(f"שלב: {n} צופים במקביל · {seconds}ש · {rate*8/1e6:.1f} Mbps לצופה")

    picks = random.sample(pool, min(n, len(pool)))
    while len(picks) < n:                      # קטלוג קטן — חוזרים על פריטים
        picks.append(random.choice(pool))

    gate = threading.Event()
    vs = [Viewer(m.get("title") or "?", m["video_url"], seconds, rate, stall, gate)
          for m in picks]
    for v in vs:
        v.start()

    t0 = time.time()
    rx0, tx0 = net_counters(dev)
    cpu_busy()                                 # מאפס את מונה המעבד
    gate.set()

    peak_cpu = 0.0
    while any(v.is_alive() for v in vs):
        time.sleep(5)
        c = cpu_busy()
        if c:
            peak_cpu = max(peak_cpu, c)
    for v in vs:
        v.join(timeout=30)

    el = time.time() - t0
    rx1, tx1 = net_counters(dev)
    out_mbps = (tx1 - tx0) * 8 / el / 1e6
    in_mbps = (rx1 - rx0) * 8 / el / 1e6

    ok = [v for v in vs if v.ok]
    gaps = sorted(v.max_gap for v in vs)
    ttfbs = [v.ttfb for v in vs if v.ttfb is not None]
    served = sum(v.got for v in vs) * 8 / el / 1e6

    say(f"  תקינים: {len(ok)}/{n}"
        f"   ({100*len(ok)//max(1,n)}%)")
    say(f"  שתיקה ארוכה ביותר: חציון {statistics.median(gaps):.1f}ש · "
        f"גרוע ביותר {gaps[-1]:.1f}ש   (סף {stall:.0f}ש)")
    if ttfbs:
        say(f"  זמן לבייט ראשון: חציון {statistics.median(ttfbs):.1f}ש · "
            f"גרוע ביותר {max(ttfbs):.1f}ש")
    # out_mbps כאן אינו הבדיקה עצמה (היא רצה על 127.0.0.1) אלא מה שיצא
    # מהכרטיס באותו זמן — כלומר צופים אמיתיים שהיו באתר במקביל.
    say(f"  הוגשו {served:.0f} Mbps · נכנס מטלגרם {in_mbps:.0f} Mbps · "
        f"בכרטיס במקביל (צופים אמיתיים) {out_mbps:.0f} Mbps")
    say(f"  מעבד בשיא: {peak_cpu:.0f}%")

    bad = {}
    for v in vs:
        if v.error:
            bad[v.error] = bad.get(v.error, 0) + 1
    if bad:
        say("  כשלים: " + " · ".join(f"{k}×{c}" for k, c in
                                     sorted(bad.items(), key=lambda x: -x[1])[:4]))

    sig = journal_since(t0)
    if sig:
        say("  ביומן השרת: " + " · ".join(f"{k} ×{v}" for k, v in
                                          sorted(sig.items(), key=lambda x: -x[1])))
    else:
        say("  ביומן השרת: שקט")

    # served = מה שהאפליקציה באמת הגישה. זה המספר להשוואה מול קיבולת הקו,
    # ולא מונה הכרטיס: הבדיקה רצה מול 127.0.0.1 והתעבורה כלל לא חוצה את
    # הכרטיס, כך שהמונה שלו יראה 0 גם כשהאפליקציה דוחפת מאות מגהביט.
    return dict(n=n, ok=len(ok), served=served, out=out_mbps, inbound=in_mbps,
                cpu=peak_cpu, worst_gap=gaps[-1], sig=sig)


def verdict(rows, link_mbps, rate):
    say("")
    say("=" * 60)
    say("סיכום")
    say("")
    say("  צופים   תקינים   Mbps שהוגשו   מעבד שיא   שתיקה גרועה")
    for r in rows:
        say(f"  {r['n']:5}   {r['ok']:4}/{r['n']:<3}  {r['served']:9.0f}   "
            f"{r['cpu']:7.0f}%   {r['worst_gap']:9.1f}ש")

    good = [r for r in rows if r["ok"] >= 0.9 * r["n"]]
    broke = [r for r in rows if r["ok"] < 0.9 * r["n"]]
    say("")
    if good:
        say(f"✅ החזיק בנוחות עד {max(r['n'] for r in good)} צופים במקביל.")
    if not broke:
        say("   לא הגענו לתקרה — הרץ שוב עם --levels גבוה יותר כדי למצוא אותה.")
    else:
        _blame(broke[0], link_mbps, broke[0]["inbound"])

    say("")
    if link_mbps:
        say(f"תקרת קו היציאה, בנפרד: {link_mbps} Mbps ÷ {rate} Mbps לצופה "
            f"= ~{int(link_mbps / rate)} צופים.")
        say("   הבדיקה רצה מקומית ולכן לא בחנה את הקו עצמו — המספר הזה הוא "
            "החישוב, והנמוך מבין השניים הוא התשובה האמיתית.")
    else:
        say("תקרת קו היציאה לא ידועה — הכרטיס לא מדווח מהירות (רגיל ב-VPS).")
        say("   שאל את הספק מה הקו, וחלק אותו ב-"
            f"{rate} Mbps כדי לקבל את תקרת הצופים מהצד הזה.")


def _blame(first, link_mbps, in_mbps):
    """מייחס את הכישלון לתקרה שנמדדה, ולא לניחוש.

    הגרסה הראשונה בדקה את הקטגוריות בסדר שבו הן כתובות והדפיסה את הראשונה
    שנמצאה. בריצה אמיתית זה תלה את הכישלון ב'צד טלגרם' על סמך 63 אירועים,
    בזמן ש'חיבורים נופלים' עמד על 1168 — פי 18 — והמסקנה יצאה הפוכה:
    'תוסיף בוטים' במקום 'תפסיק להפיל חיבורים'. לכן הדירוג הוא לפי כמות."""
    say(f"⚠️  נשבר ב-{first['n']} צופים ({first['ok']} תקינים).")

    if link_mbps and first["served"] > 0.75 * link_mbps:
        say(f"   הסיבה: **קו היציאה**. האפליקציה הגישה {first['served']:.0f} Mbps "
            f"והקו נותן {link_mbps} — בעולם האמיתי הוא היה נחנק כאן.")
        say("   בוטים נוספים לא יעזרו כאן בכלל. צריך יותר רוחב פס, או "
            "להוריד את קצב הסיביות של התוכן, או שרת נוסף.")
        return
    if first["cpu"] > 85:
        say(f"   הסיבה: **מעבד** ({first['cpu']:.0f}%). בוטים לא יעזרו.")
        return

    sig = first["sig"]
    if not sig:
        say("   הסיבה לא חד-משמעית מהמדידה. הרץ שוב עם --seconds 180 — "
            "שלב קצר מדי נותן רעש.")
        return

    ranked = sorted(sig.items(), key=lambda kv: -kv[1])
    top, n_top = ranked[0]
    rest = sum(v for _, v in ranked[1:])
    say("   סימנים ביומן, לפי כמות: " +
        " · ".join(f"{k} ×{v}" for k, v in ranked))

    if n_top < 2 * max(1, rest):
        say(f"   אין סימן דומיננטי ({top} מוביל אבל לא בפער משמעותי) — "
            "אל תתקן על סמך זה. הרץ שוב עם --seconds 180.")
        return

    if "חיבורים" in top:
        say(f"   הסיבה: **חיבורים לטלגרם נופלים ונבנים מחדש** ({n_top} פעמים).")
        say("   בוטים נוספים לא מרפאים את זה — כל בוט נוסף פותח עוד חיבורים "
            "שנופלים באותו קצב, כלומר יותר רעש ולא יותר קיבולת.")
    elif "טלגרם" in top:
        say(f"   הסיבה: **צד טלגרם** ({top}, {n_top} פעמים).")
        say("   *כאן* בוטים נוספים כן עוזרים: כל בוט הוא מכסת FloodWait נפרדת "
            "וחיבורי מדיה נפרדים. שווה להוסיף ולהריץ את הבדיקה שוב.")
    else:
        say(f"   הסיבה: {top} ({n_top} פעמים).")

    # יחס בזבוז: כמה נמשך מטלגרם לעומת כמה הגיע לצופה. יחס גבוה = בייטים
    # נמשכים ונזרקים (חלונות שנכשלו ונמשכו שוב), וזה מכפיל את העומס על
    # טלגרם בלי להוסיף ולו צופה אחד.
    if first["served"] > 1 and in_mbps > 0:
        ratio = in_mbps / first["served"]
        if ratio > 1.3:
            say(f"   ובנוסף: נמשכו {in_mbps:.0f} Mbps מטלגרם כדי להגיש "
                f"{first['served']:.0f} — יחס {ratio:.1f}. כלומר "
                f"{100*(1-1/ratio):.0f}% מהבייטים נמשכו ונזרקו.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", default="5,10,20,30")
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--mbps", type=float, default=6.0,
                    help="קצב סיביות לצופה — כמו נגן אמיתי")
    ap.add_argument("--stall", type=float, default=10.0,
                    help="שתיקה ארוכה מזה נחשבת תקיעה")
    a = ap.parse_args()

    levels = [int(x) for x in a.levels.split(",") if x.strip()]
    dev, link = nic()
    if not dev:
        sys.exit("לא נמצא ממשק רשת פעיל")

    say("=" * 60)
    say(f"בדיקת קיבולת · ממשק {dev} · "
        + (f"קו {link} Mbps" if link else "מהירות הקו לא מדווחת"))
    if link:
        say(f"תקרה תיאורטית של קו היציאה בלבד: "
            f"~{int(link / a.mbps)} צופים ב-{a.mbps} Mbps")
    say(f"שלבים: {levels} · {a.seconds}ש כל אחד · "
        f"סף תקיעה {a.stall:.0f}ש")

    pool = catalog()
    say(f"קטלוג: {len(pool)} סרטים זמינים לבדיקה")

    rows = []
    for n in levels:
        rows.append(run_level(n, pool, a.seconds, a.mbps * 1e6 / 8, a.stall, dev))
        if rows[-1]["ok"] < 0.5 * n:
            say("")
            say("  עוצרת — מעל חצי מהצופים נפלו, אין טעם להעמיס יותר.")
            break
        time.sleep(20)          # שהשרת יתאושש בין שלבים

    verdict(rows, link, a.mbps)
    say(f"\nהכל נשמר גם ב-{LOG}")


if __name__ == "__main__":
    main()
