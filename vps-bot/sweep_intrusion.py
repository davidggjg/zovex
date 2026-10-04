#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sweep_intrusion — לא "מי גישש", אלא "האם מישהו נכנס".

## ההבדל

‎forensics_ip‎ עונה על *מה כתובת אחת ניסתה*. זו שאלה על **ניסיונות**,
והיומן של nginx הוא המקור שלה.

הכלי הזה שואל משהו אחר: **האם מישהו הצליח, ונשאר.** תוקף שנכנס לא
משאיר את העקבות שלו ביומן HTTP — הוא משאיר אותם בדיסק, ברשימת
המשתמשים, בתזמונים, ובחיבורים היוצאים. לכן כאן בודקים את אלה.

## מה נבדק

    1. כתיבות שהצליחו   — 2xx על POST/PUT/DELETE מכתובות חיצוניות
    2. קבצים ששונו      — קוד שהשתנה מחוץ לפריסות שלנו
    3. דלתות אחוריות    — cron, טיימרים, ‎authorized_keys‎
    4. כניסות SSH       — מי נכנס בפועל, ומאיפה
    5. חיבורים יוצאים   — לאן השרת מדבר עכשיו
    6. נתוני הרשאות     — אדמינים, מעלים, חסומים

## קריאה בלבד

לא כותב, לא מוחק, לא נוגע בשירות, **ולא נוגע ב-SSH** — רק קורא את
‎authorized_keys‎ כדי לדווח אם יש שם מפתח שלא הכנסת. זו הבדיקה
הקלאסית לדלת אחורית, והיא חייבת להיות קריאה בלבד.

    python3 sweep_intrusion.py
    python3 sweep_intrusion.py --days 14
"""
import glob
import gzip
import os
import re
import subprocess
import sys
import time

LOG_GLOB = os.environ.get("NGINX_LOGS", "/var/log/nginx/access.log*")
DATA_DIR = os.environ.get("DATA_DIR", "/opt/zovex-bot/data")
CODE_DIRS = [p for p in (os.environ.get("CODE_DIRS") or
                         "/opt/zovex-bot,/opt/zovex-site").split(",") if p]

LINE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<ts>[^\]]+)\] '
    r'"(?P<method>[A-Z_]+) (?P<path>[^" ]*) ?[^"]*" '
    r'(?P<status>\d{3}) (?P<bytes>\d+|-) "[^"]*" "(?P<ua>[^"]*)"')

LOCAL = re.compile(r"^(127\.|::1|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)")

# נתיבים שכתיבה מוצלחת אליהם משנה מצב — להבדיל ממשוב והיסטוריה,
# שכל משתמש כותב אליהם כל היום.
SENSITIVE = re.compile(
    r"^/(panel|admin|channels|pool|import|app/version|content/save|"
    r"uploads|api/relay|apps/save)", re.I)


def hdr(t):
    print()
    print("━" * 58)
    print(t)
    print("━" * 58)


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True,
                              text=True, timeout=30).stdout.strip()
    except Exception as e:
        return f"(נכשל: {e})"


def read_logs():
    for p in sorted(glob.glob(LOG_GLOB)):
        op = gzip.open if p.endswith(".gz") else open
        try:
            with op(p, "rt", errors="replace") as fh:
                for ln in fh:
                    m = LINE.match(ln)
                    if m:
                        yield m.groupdict()
        except OSError:
            continue


def check_writes():
    hdr("1 · כתיבות שהצליחו מכתובות חיצוניות")
    hits = {}
    for r in read_logs():
        if r["method"] not in ("POST", "PUT", "DELETE", "PATCH"):
            continue
        if r["status"][0] != "2" or LOCAL.match(r["ip"]):
            continue
        if not SENSITIVE.match(r["path"]):
            continue
        k = (r["ip"], r["method"], r["path"].split("?")[0])
        hits.setdefault(k, []).append(r["ts"])
    if not hits:
        print("  ✓ אין. אף כתובת חיצונית לא כתבה בהצלחה לנתיב רגיש.")
        print("    (משוב והיסטוריה אינם כאן — אליהם כל משתמש כותב.)")
        return
    print("  ⚠ נמצאו. כל שורה כאן דורשת הסבר:")
    for (ip, mth, path), times in sorted(hits.items(),
                                         key=lambda kv: -len(kv[1])):
        print(f"\n   {ip}  {mth} {path}   ({len(times)} פעמים)")
        for t in times[:4]:
            print(f"       {t}")


def check_files(days):
    hdr(f"2 · קוד שהשתנה ב-{days} הימים האחרונים")
    cutoff = time.time() - days * 86400
    skip = re.compile(r"/(data|__pycache__|node_modules|\.git)/|\.(log|bak"
                      r"|bak_[\w]+|pyc|tgz|apk|part|upload)$")
    found = []
    for root in CODE_DIRS:
        if not os.path.isdir(root):
            continue
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in
                      ("node_modules", "__pycache__", ".git", "data")]
            for fn in fns:
                p = os.path.join(dp, fn)
                if skip.search(p):
                    continue
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                if st.st_mtime > cutoff:
                    found.append((st.st_mtime, st.st_size, p))
    if not found:
        print("  ✓ שום קובץ קוד לא השתנה בחלון הזה.")
        return
    print(f"  {len(found)} קבצים. כל אחד צריך להתאים לפריסה שאתה זוכר:")
    for mt, sz, p in sorted(found, reverse=True)[:40]:
        print(f"   {time.strftime('%d/%m %H:%M', time.localtime(mt))}  "
              f"{sz:>9}ב  {p}")
    if len(found) > 40:
        print(f"   … ועוד {len(found) - 40}")


def check_persistence():
    hdr("3 · דלתות אחוריות: תזמונים ומפתחות")
    print("\n  ── cron ──")
    out = sh("crontab -l 2>/dev/null; ls -la /etc/cron.d/ 2>/dev/null | tail -n +4")
    print("   " + (out.replace("\n", "\n   ") if out else "(ריק)"))

    print("\n  ── טיימרים של systemd ──")
    out = sh("systemctl list-timers --no-pager --no-legend 2>/dev/null | head -12")
    print("   " + (out.replace("\n", "\n   ") if out else "(אין)"))

    print("\n  ── שירותים שנוצרו לאחרונה ──")
    out = sh("ls -lt /etc/systemd/system/*.service 2>/dev/null | head -8")
    print("   " + (out.replace("\n", "\n   ") if out else "(אין)"))

    # ‎authorized_keys‎ — קריאה בלבד. אסור לגעת ב-SSH, אבל מפתח שנשתל
    # שם הוא הדלת האחורית הקלאסית, ובלי לקרוא אותו אי אפשר לדעת.
    print("\n  ── authorized_keys (קריאה בלבד) ──")
    any_key = False
    for p in glob.glob("/root/.ssh/authorized_keys") + \
            glob.glob("/home/*/.ssh/authorized_keys"):
        try:
            lines = [l for l in open(p, errors="replace").read().splitlines()
                     if l.strip() and not l.strip().startswith("#")]
        except OSError:
            continue
        any_key = True
        print(f"   {p}: {len(lines)} מפתחות")
        for l in lines:
            parts = l.split()
            tag = parts[-1] if len(parts) > 2 else "(בלי תווית)"
            fp = parts[1][:12] + "…" if len(parts) > 1 else "?"
            print(f"       {tag}   {fp}")
    if not any_key:
        print("   ✓ אין אף קובץ authorized_keys — ולכן אין מפתח שנשתל.")
    else:
        print("\n   ⚠ אמרת שאין לך מפתחות SSH. כל מפתח שמופיע כאן")
        print("     הוא דלת שלא אתה פתחת.")


def check_ssh():
    hdr("4 · כניסות SSH שהצליחו")
    out = sh("grep -h 'Accepted' /var/log/auth.log* 2>/dev/null | tail -20")
    if not out:
        print("  (אין יומן auth.log נגיש, או אין כניסות)")
        return
    ips = {}
    for ln in out.splitlines():
        m = re.search(r"Accepted (\w+) for (\S+) from (\S+)", ln)
        if m:
            ips.setdefault(m.group(3), []).append((m.group(1), m.group(2), ln[:15]))
    for ip, rows in ips.items():
        print(f"\n   {ip}  ({len(rows)} כניסות)")
        for how, who, when in rows[:3]:
            print(f"       {when}  {who}  דרך {how}")
    print("\n   כל כתובת שאינה שלך — זו פריצה, לא גישוש.")


def check_net():
    hdr("5 · חיבורים יוצאים פעילים")
    out = sh("ss -tnp state established 2>/dev/null | head -25")
    print("   " + (out.replace("\n", "\n   ") if out else "(אין)"))
    print("\n   חפש תהליך שאתה לא מכיר, או יעד שאין סיבה לדבר איתו.")


def check_perms():
    hdr("6 · מי מורשה במערכת")
    import json
    for name, label in (("admins.json", "אדמינים"),
                        ("drive_uploaders.json", "מעלי דרייב"),
                        ("bans.json", "חסומים")):
        p = os.path.join(DATA_DIR, name)
        if not os.path.exists(p):
            print(f"  {label}: (אין קובץ)")
            continue
        try:
            d = json.loads(open(p, encoding="utf-8").read())
        except Exception as e:
            print(f"  {label}: לא נקרא ({e})")
            continue
        n = len(d) if isinstance(d, (list, dict)) else 0
        mt = time.strftime("%d/%m %H:%M", time.localtime(os.stat(p).st_mtime))
        print(f"\n  {label}: {n} רשומות · שונה לאחרונה {mt}")
        items = d if isinstance(d, list) else list(d)
        for it in items[:12]:
            s = json.dumps(it, ensure_ascii=False) if not isinstance(it, str) else it
            print(f"      {s[:90]}")
    print("\n  ⚠ רשומה שאתה לא מזהה = חשבון שמישהו הוסיף.")


def main():
    days = 7
    if "--days" in sys.argv:
        try:
            days = int(sys.argv[sys.argv.index("--days") + 1])
        except Exception:
            pass
    print("sweep_intrusion · קריאה בלבד · לא נוגע ב-SSH ולא בשירותים")
    check_writes()
    check_files(days)
    check_persistence()
    check_ssh()
    check_net()
    check_perms()
    print()
    print("━" * 58)
    print("כל סעיף שחזר ✓ נבדק ונמצא נקי. סעיף עם ⚠ דורש שתסתכל.")
    print("━" * 58)


if __name__ == "__main__":
    main()
