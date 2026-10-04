#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forensics_ip — כל מה שכתובת אחת עשתה אצלנו, ומה היא ניסתה.

## למה כלי ולא grep

‎grep | awk | sort | uniq‎ נותן ספירות. ספירה לא עונה על השאלות
שבאמת נשאלות אחרי חדירה:

* האם הם **הצליחו** במשהו, או שרק קיבלו 401 חמישים פעם?
* האם הם בכלל **צפו** בתוכן, או רק מיפו?
* האם יש בקשה אחת חריגה שנבלעה בין אלף רגילות?
* והאם הם **הזריקו** משהו — SQL, נתיבים, פקודות — שלא חיפשנו?

הכלי הזה עונה על ארבעתן מאותו קובץ יומן.

## קריאה בלבד

לא כותב, לא מוחק, לא נוגע בשירות. אפשר להריץ בזמן שהמערכת חיה.

## מיסוך

נתיבי ‎/hls-relay/<מארח>/‎ נושאים את כתובת ספק השידורים, ואסימוני
חתימה מופיעים במחרוזות השאילתה. שניהם ממוסכים בפלט — הפלט הזה
מודבק לצ'אטים, וזו תקלה שכבר קרתה כאן פעמיים.

    python3 forensics_ip.py 172.59.210.220
    python3 forensics_ip.py 172.59.210.220 --full      כל הבקשות
    python3 forensics_ip.py --suspicious               מי חשוד בכלל
"""
import glob
import gzip
import os
import re
import sys
import urllib.parse
from collections import Counter, defaultdict

LOG_GLOB = os.environ.get("NGINX_LOGS", "/var/log/nginx/access.log*")
DATA_DIR = os.environ.get("DATA_DIR", "/opt/zovex-bot/data")

# ‎$remote_addr - $remote_user [$time_local] "$request" $status
#  $body_bytes_sent "$http_referer" "$http_user_agent"‎
LINE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<ts>[^\]]+)\] '
    r'"(?P<method>[A-Z_]+) (?P<path>[^" ]*) ?[^"]*" '
    r'(?P<status>\d{3}) (?P<bytes>\d+|-) '
    r'"(?P<ref>[^"]*)" "(?P<ua>[^"]*)"')

# ── מה נחשב ניסיון הזרקה ────────────────────────────────────────────────
# כל תבנית כאן נבחרה כי היא **ממעטת בהתראות שווא**: מחרוזות שמופיעות
# בשימוש לגיטימי (למשל 'select' בשם סרט) אינן כאן.
INJECT = [
    ("מעבר תיקיות",   re.compile(r"\.\./|\.\.%2f|%2e%2e[/%]", re.I)),
    ("קובץ מערכת",    re.compile(r"/etc/(passwd|shadow)|/proc/self/", re.I)),
    ("SSRF פנימי",    re.compile(r"169\.254\.169\.254|metadata\.google"
                                 r"|127\.0\.0\.1|0\.0\.0\.0|localhost", re.I)),
    ("XSS",           re.compile(r"<script|onerror\s*=|onload\s*=|javascript:"
                                 r"|%3cscript|<img[^>]+src", re.I)),
    ("SQL",           re.compile(r"union\s+select|'\s+or\s+'1|;\s*drop\s+table"
                                 r"|sleep\(\d|benchmark\(", re.I)),
    ("הרצת פקודות",   re.compile(r";\s*(cat|wget|curl|bash|sh|nc)\s"
                                 r"|\$\(|`.*`|\|\s*(bash|sh)\b", re.I)),
    ("קבצי סוד",      re.compile(r"/\.(git|env|aws|ssh)|\.env$|id_rsa"
                                 r"|wp-config|\.htpasswd", re.I)),
    ("תו NUL/בקרה",   re.compile(r"%00|\x00")),
    ("הכללת תבנית",   re.compile(r"\{\{.*\}\}|\$\{.*\}")),
]

# נתיבים שמשמעותם "צפה בתוכן בפועל", להבדיל מ"ביקר בדף"
WATCH = re.compile(r"^/(stream|fs|vt|vh|cast|hls-relay)/")

MASK_HOST = re.compile(r"(/hls-relay/(?:_fix/)?)[^/?\s]+")
MASK_SIG = re.compile(r"(sig=)[A-Za-z0-9]{8,}")
MASK_LONG = re.compile(r"\b[A-Za-z0-9_-]{24,}\b")


def mask(s: str) -> str:
    s = MASK_HOST.sub(r"\1<ספק>", s)
    s = MASK_SIG.sub(r"\1<חתימה>", s)
    return MASK_LONG.sub("<אסימון>", s)


def open_log(p: str):
    return (gzip.open(p, "rt", errors="replace") if p.endswith(".gz")
            else open(p, errors="replace"))


def read_lines():
    for p in sorted(glob.glob(LOG_GLOB)):
        try:
            with open_log(p) as fh:
                for ln in fh:
                    m = LINE.match(ln)
                    if m:
                        yield m.groupdict()
        except OSError:
            continue


def decode(p: str) -> str:
    """נתיב מפוענח — הזרקות מוסתרות לרוב בקידוד אחוזים, לפעמים כפול."""
    out = p
    for _ in range(2):
        try:
            nxt = urllib.parse.unquote(out)
        except Exception:
            break
        if nxt == out:
            break
        out = nxt
    return out


def hdr(t: str) -> None:
    print()
    print(t)
    print("─" * max(len(t), 40))


def report(ip: str, rows: list, full: bool) -> None:
    if not rows:
        print(f"אין אף בקשה מ-{ip} ביומנים שנמצאו.")
        print(f"(נסרקו: {LOG_GLOB})")
        return

    print(f"\n╔══ {ip} ── {len(rows)} בקשות ══╗")

    # ── מתי ─────────────────────────────────────────────────────────────
    days = Counter(r["ts"].split(":")[0] for r in rows)
    hdr("נוכחות לפי יום")
    for d, n in sorted(days.items()):
        print(f"  {d}  {n:>5}  {'▇' * min(n // 20 + 1, 40)}")
    print(f"\n  ראשונה: {rows[0]['ts']}")
    print(f"  אחרונה: {rows[-1]['ts']}")

    # ── הצליח מול נחסם ──────────────────────────────────────────────────
    ok = [r for r in rows if r["status"][0] == "2"]
    blocked = [r for r in rows if r["status"][0] == "4"]
    err = [r for r in rows if r["status"][0] == "5"]
    hdr("תוצאות")
    print(f"  הצליח (2xx):  {len(ok):>5}")
    print(f"  נחסם  (4xx):  {len(blocked):>5}")
    print(f"  שגיאת שרת:    {len(err):>5}")
    if err:
        print("  ⚠ 5xx אומר שהשרת קרס או נכשל על הבקשה — שווה בדיקה:")
        for r in err[:5]:
            print(f"      {r['ts']} {r['status']} {mask(r['path'])[:70]}")

    # ── האם צפו בתוכן ───────────────────────────────────────────────────
    watched = [r for r in rows if WATCH.match(r["path"])
               and r["status"][0] == "2"]
    total_mb = sum(int(r["bytes"]) for r in rows
                   if r["bytes"].isdigit()) / 1e6
    hdr("האם צפו בתוכן")
    if watched:
        wmb = sum(int(r["bytes"]) for r in watched if r["bytes"].isdigit()) / 1e6
        print(f"  {len(watched)} בקשות הזרמה שהצליחו · {wmb:.1f} MB")
        print("  ⇒ כן. הם לא רק מיפו — הם משכו תוכן.")
        for r in watched[:8]:
            print(f"      {r['ts']} {mask(r['path'])[:70]}")
    else:
        print("  אין אף בקשת הזרמה שהצליחה.")
        print("  ⇒ הם לא צפו בכלום. זה פרופיל של סריקה, לא של משתמש.")
    print(f"\n  סך הכול הורדו: {total_mb:.1f} MB")

    # ── ניסיונות הזרקה ──────────────────────────────────────────────────
    hdr("ניסיונות הזרקה")
    found = defaultdict(list)
    for r in rows:
        d = decode(r["path"])
        for name, rx in INJECT:
            if rx.search(d):
                found[name].append(r)
    if not found:
        print("  לא נמצאו.")
    # גודל התשובה הטיפוסי של דף האתר. כל נתיב לא מוכר מגיע ל-‎location /‎
    # ומקבל את ה-SPA עם 200 — ולכן ‎200 /etc/passwd‎ נראה כמו הצלחה
    # והוא כלום. בלי ההבחנה הזו הכלי צועק על הדבר הלא נכון, וזה גרוע
    # מלא לצעוק: אחרי שתי התראות שווא מפסיקים להאמין לו.
    shell = Counter(int(r["bytes"]) for r in rows
                    if r["status"] == "200" and r["bytes"].isdigit()
                    and r["path"].count("/") <= 2)
    shell_size = shell.most_common(1)[0][0] if shell else -1

    for name, hits in sorted(found.items(), key=lambda kv: -len(kv[1])):
        got = [h for h in hits if h["status"][0] == "2"
               and not (h["bytes"].isdigit()
                        and abs(int(h["bytes"]) - shell_size) < 64)]
        spa = [h for h in hits if h["status"][0] == "2" and h not in got]
        flag = ("⚠ חלקם החזירו תוכן אמיתי!" if got else
                "נחסמו (או קיבלו את דף האתר, שאינו הצלחה)")
        print(f"\n  {name}: {len(hits)} ניסיונות — {flag}")
        seen = set()
        for h in hits:
            k = mask(decode(h["path"]))[:84]
            if k in seen:
                continue
            seen.add(k)
            note = ""
            if h in spa:
                note = "  ← דף האתר, לא הקובץ"
            elif h in got:
                note = "  ← ‼ לבדוק"
            print(f"      {h['status']} {h['bytes']:>8}ב  {k}{note}")
            if len(seen) >= 6:
                break
    if found and shell_size > 0:
        print(f"\n  (דף האתר שוקל ~{shell_size} בתים. תשובה 200 בגודל הזה")
        print("   היא ברירת המחדל של ‎location /‎ ולא קובץ שנקרא.)")

    # ── מה ניסו לכתוב ───────────────────────────────────────────────────
    writes = [r for r in rows if r["method"] in ("POST", "PUT", "DELETE",
                                                 "PATCH")]
    hdr("בקשות כתיבה")
    if not writes:
        print("  אין.")
    else:
        agg = Counter((r["method"], r["path"], r["status"]) for r in writes)
        for (mth, path, st), n in agg.most_common(25):
            mark = "✓" if st[0] == "2" else "✗"
            print(f"  {mark} {n:>4} × {st} {mth} {mask(path)[:60]}")
        print("\n  ✗ = נדחה. ✓ = התקבל — ולזה צריך להסתכל בגוף הבקשה,")
        print("  שאינו נשמר ביומן של nginx.")

    # ── באיזה כלי השתמשו ────────────────────────────────────────────────
    hdr("חתימות הלקוח (User-Agent)")
    for ua, n in Counter(r["ua"] for r in rows).most_common(8):
        tool = ""
        low = ua.lower()
        for t in ("curl", "python", "go-http", "nmap", "sqlmap", "nikto",
                  "wget", "burp", "zgrab", "masscan", "postman"):
            if t in low:
                tool = f"   ← כלי אוטומטי ({t})"
                break
        print(f"  {n:>5} × {ua[:72]}{tool}")

    # ── הנתיבים שהצליחו ─────────────────────────────────────────────────
    hdr("מה הם קיבלו בפועל (2xx בלבד)")
    for path, n in Counter(mask(r["path"].split("?")[0])
                           for r in ok).most_common(30):
        print(f"  {n:>5} × {path[:72]}")

    if full:
        hdr("ציר זמן מלא")
        for r in rows:
            print(f"  {r['ts']} {r['status']} {r['method']:<6} "
                  f"{mask(r['path'])[:80]}")


def scan_data_files() -> None:
    """מחפש בקבצי הנתונים תוכן שנראה כמו מטען שהוזרק.

    היומן מראה ש-POST **התקבל**, אבל לא מה היה בגוף שלו. מה שנשמר
    בדיסק הוא הראיה היחידה לכך.
    """
    import json
    hdr("סריקת קבצי הנתונים אחרי מטענים")
    rx = re.compile(r"<\s*(script|img|svg|iframe|object|embed|em|b|i)\b"
                    r"|on\w+\s*=|javascript:", re.I)
    any_hit = False
    for name in ("feedback.json", "content.json", "history.json",
                 "progress.json", "app_version.json"):
        p = os.path.join(DATA_DIR, name)
        if not os.path.exists(p):
            continue
        try:
            raw = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        hits = []

        def walk(node, trail=""):
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(v, f"{trail}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node[:5000]):
                    walk(v, f"{trail}[{i}]")
            elif isinstance(node, str) and rx.search(node):
                hits.append((trail, node[:120]))

        try:
            walk(json.loads(raw))
        except Exception:
            for m in rx.finditer(raw):
                hits.append(("(לא JSON תקין)", raw[max(0, m.start() - 40):
                                                   m.start() + 80]))
        if hits:
            any_hit = True
            print(f"\n  {name}: {len(hits)} ממצאים")
            for trail, val in hits[:10]:
                print(f"      {trail}")
                print(f"        {val!r}")
        else:
            print(f"  {name}: נקי")
    if not any_hit:
        print("\n  ⇒ לא נמצא שום תוכן שנראה כמו מטען שהוזרק.")


def suspicious() -> None:
    """מי בכלל חשוד — לפני שיודעים איזו כתובת לבדוק."""
    score = defaultdict(lambda: Counter())
    for r in read_lines():
        ip = r["ip"]
        d = decode(r["path"])
        if r["status"] in ("401", "403"):
            score[ip]["נדחה"] += 1
        for name, rx in INJECT:
            if rx.search(d):
                score[ip]["הזרקה"] += 1
                break
        score[ip]["סהכ"] += 1

    hdr("כתובות עם סימני סריקה")
    rank = sorted(score.items(),
                  key=lambda kv: -(kv[1]["הזרקה"] * 10 + kv[1]["נדחה"]))
    print(f"  {'כתובת':<22}{'הזרקות':>8}{'נדחו':>8}{'סהכ':>8}")
    for ip, c in rank[:15]:
        if not c["הזרקה"] and c["נדחה"] < 10:
            continue
        print(f"  {ip:<22}{c['הזרקה']:>8}{c['נדחה']:>8}{c['סהכ']:>8}")
    print("\n  דירוג = הזרקות × 10 + דחיות. כתובת בלי הזרקות ועם מעט")
    print("  דחיות אינה מוצגת — היא כנראה משתמש אמיתי שטעה בסיסמה.")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    full = "--full" in sys.argv

    if "--suspicious" in sys.argv:
        suspicious()
        return

    if not args:
        sys.exit(__doc__.strip().split("\n\n")[-1])

    for ip in args:
        rows = [r for r in read_lines() if r["ip"] == ip]
        rows.sort(key=lambda r: r["ts"])
        report(ip, rows, full)

    scan_data_files()
    print()


if __name__ == "__main__":
    main()
