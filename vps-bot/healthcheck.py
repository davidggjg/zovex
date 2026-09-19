#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
healthcheck — בדיקה אחת שעוברת על כל המערכת ואומרת מה עובד ומה לא.

## למה זה קיים

נבנו כאן הרבה חלקים — שירות ההזרמה, האתר, הפאנל, השידורים החיים, mkvtool,
המדים — וכל אחד נבדק בנפרד ברגע שנבנה. אין שום דבר שאומר **עכשיו** אם כולם
עדיין עומדים. חלק מהתקלות שרדפנו אחריהן היו דווקא מהסוג הזה: משהו שהוחל
פעם והפסיק להיות מוחל, שירות שלא עלה אחרי אתחול, פאצ' שנמחק בעדכון.

הכלי הזה עונה על שאלה אחת: **מה מכל זה עובד ברגע זה.**

## קריאה בלבד

לא משנה שום הגדרה, לא מפעיל כלום מחדש, ולא מוריד וידאו. הבדיקה הכבדה
ביותר היא בקשת Range של בייט אחד. אפשר להריץ בשיא העומס.

## מה נבדק

  • שירותים — zovex-bot, mkvtool, nginx, והמדים שרצים ברקע
  • פאצ'ים — מי מוחל בפועל על main.py ו-admin.html, לפי הסימן שלו
  • האתר — מה שהצופה מקבל: הדף, הקטלוג, הפאנל
  • הזרמה — בריכות טלגרם, בוטים בריאים, זמן פתיחת זרם אמיתי
  • שידורים חיים — האם ה-playlist מתקדם
  • משאבים — דיסק, זיכרון, ותיקיית העבודה של mkvtool
  • המדים — האם snapwatch באמת אוסף, ומה הוא מראה

## צנזורה

כל כתובת, IP ומזהה ארוך מוחלפים לפני ההדפסה, כמו בשאר הכלים כאן. אפשר
להדביק את הפלט בבטחה.

    python3 healthcheck.py
    python3 healthcheck.py --quick     # בלי בדיקות שנוגעות בטלגרם
"""
import argparse, json, os, re, shutil, subprocess, sys, time
import urllib.request, urllib.error
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

PORT = os.environ.get("PORT", "8000")
LOCAL = f"http://127.0.0.1:{PORT}"
PUBLIC = os.environ.get("ZOVEX_PUBLIC", "https://zovex.duckdns.org")
MAIN = Path(os.environ.get("ZOVEX_MAIN", "/opt/zovex-bot/main.py"))
ADMIN = Path(os.environ.get("ZOVEX_ADMIN", "/opt/zovex-bot/admin.html"))
SNAP_LOG = Path("/tmp/zovex_snap.log")

REDACT = [
    (re.compile(r"https?://[^\s\"'<>]+"), "‹כתובת›"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "‹IP›"),
    (re.compile(r"\b[a-z0-9][a-z0-9.-]{6,}\.(?:tv|pw|cc|xyz|to)\b", re.I), "‹מתחם›"),
]

OK, WARN, BAD = "✅", "⚠️ ", "❌"
_score = {"ok": 0, "warn": 0, "bad": 0}


def clean(s):
    for pat, rep in REDACT:
        s = pat.sub(rep, str(s))
    return s


def say(level, label, detail=""):
    _score["ok" if level is OK else "warn" if level is WARN else "bad"] += 1
    line = f"  {level} {label}"
    if detail:
        line += f" — {clean(detail)}"
    print(line)


def head(t):
    print(f"\n{'─' * 3} {t} {'─' * max(3, 58 - len(t))}")


def sh(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except Exception as e:
        return 1, "", f"{type(e).__name__}: {e}"


def get(url, timeout=12, rng=None):
    """מחזיר (status, body, שניות, שגיאה). לא זורק לעולם."""
    h = {"User-Agent": "zovex-healthcheck/1"}
    if rng:
        h["Range"] = rng
    t = time.time()
    try:
        with urllib.request.urlopen(
                urllib.request.Request(url, headers=h), timeout=timeout) as r:
            return r.status, r.read(200000), time.time() - t, None
    except urllib.error.HTTPError as e:
        try:
            e.read()
        except Exception:
            pass
        return e.code, b"", time.time() - t, None
    except Exception as e:
        return 0, b"", time.time() - t, type(e).__name__


# ── שירותים ──────────────────────────────────────────────────────────────────
def check_services():
    head("שירותים")
    for unit, must in (("zovex-bot", True), ("mkvtool", False), ("nginx", True)):
        _, state, _ = sh(["systemctl", "is-active", unit])
        _, nres, _ = sh(["systemctl", "show", unit, "-p", "NRestarts", "--value"])
        _, pid, _ = sh(["systemctl", "show", unit, "-p", "MainPID", "--value"])
        up = ""
        if pid.isdigit() and int(pid) > 0:
            _, et, _ = sh(["ps", "-o", "etimes=", "-p", pid])
            if et.strip().isdigit():
                s = int(et.strip())
                up = f"למעלה {s // 3600}ש {(s % 3600) // 60}ד"
        if state == "active":
            n = int(nres) if nres.isdigit() else 0
            # קריסות חוזרות הן התקלה שנראית כמו "active" ולכן מתפספסת:
            # systemd מרים מחדש, הסטטוס ירוק, והשירות בעצם לא עובד.
            if n > 3:
                say(WARN, unit, f"active אבל קרס וקם {n} פעמים · {up}")
            else:
                say(OK, unit, f"{up}" + (f" · קריסות {n}" if n else ""))
        else:
            say(BAD if must else WARN, unit, state or "לא מוגדר")

    for name, pat in (("snapwatch", "snapwatch.sh"),):
        rc, out, _ = sh(["pgrep", "-f", pat])
        say(OK if rc == 0 else WARN, name,
            f"{len(out.split())} תהליכים" if rc == 0 else "לא רץ")


# ── פאצ'ים ───────────────────────────────────────────────────────────────────
PATCHES = [
    ("fix_media_session_leak", "# [fix_media_session_leak]", "main"),
    ("fix_vod_transcode", "# [fix_vod_transcode]", "main"),
    ("fix_admin_freshness", "# [fix_admin_freshness]", "main"),
    ("fix_pool_thrash", "_pool_dropped_at", "main"),
    ("fix_salt_refresh", "_salt_refresh_loop", "main"),
    ("fix_admin_upload", "פרטים נוספים — כמעט תמיד לא צריך", "admin"),
    ("fix_admin_series_save", "_seriesNote", "admin"),
]


def check_patches():
    head("פאצ'ים מוחלים")
    src = {"main": "", "admin": ""}
    for k, p in (("main", MAIN), ("admin", ADMIN)):
        try:
            src[k] = p.read_text(encoding="utf-8")
        except Exception as e:
            say(BAD, f"קריאת {p.name}", str(e))
    for name, mark, target in PATCHES:
        if not src[target]:
            continue
        on = mark in src[target]
        say(OK if on else WARN, name, "" if on else "לא מוחל")
    # קוד שהוזרק אך לא נרשם להפעלה הוא קוד מת שנראה כמו תיקון.
    if "_salt_refresh_loop" in src["main"]:
        reg = "asyncio.create_task(_salt_refresh_loop())" in src["main"]
        say(OK if reg else BAD, "רענון salt נרשם להפעלה",
            "" if reg else "הפונקציה קיימת אבל אף אחד לא מפעיל אותה")


# ── האתר ─────────────────────────────────────────────────────────────────────
def check_site():
    head("האתר — מה שהצופה מקבל")
    for label, url, want in (
            ("דף הבית (ציבורי)", PUBLIC + "/", b"<"),
            ("קטלוג", LOCAL + "/content/version", b"version"),
            ("פאנל הניהול", LOCAL + "/admin", b"<"),
            ("גרסת האפליקציה", LOCAL + "/app/version", b"{"),
    ):
        st, body, dt, err = get(url)
        if st == 200 and want in body:
            say(OK, label, f"{dt:.2f}ש")
        elif st == 200:
            say(WARN, label, f"200 אבל התוכן לא כצפוי ({len(body)} בתים)")
        else:
            say(BAD, label, f"HTTP {st}" if st else (err or "אין תשובה"))

    # הבאנר של הפאנל נועד לומר מתי admin.html עודכן. אם /admin נשמר במטמון
    # זה חוזר להיות הבעיה שבגללה הוא נבנה.
    st, body, _, _ = get(LOCAL + "/admin")
    if st == 200:
        has = b"no-store" in body or "עודכן".encode() in body
        say(OK if has else WARN, "הפאנל לא נשמר במטמון",
            "" if has else "לא נמצא no-store — שינויים עלולים לא להופיע")


# ── הזרמה ────────────────────────────────────────────────────────────────────
def check_stream(quick):
    head("הזרמה")
    st, body, _, err = get(LOCAL + "/debug/caches")
    caches = {}
    if st == 200:
        try:
            caches = json.loads(body)
        except Exception:
            pass
    if not caches:
        say(BAD, "נקודת הדיבאג", f"HTTP {st}" if st else (err or "אין תשובה"))
        return

    bots = caches.get("stream_bots", 0)
    pools = caches.get("media_sessions_pools", 0)
    conns = caches.get("media_sessions_total_conns", 0)
    say(OK if bots else BAD, "בוטים בבריכה", f"{bots}")
    say(OK if pools else WARN, "בריכות מדיה", f"{pools} בריכות · {conns} חיבורים")

    if "salt_ok" in caches:
        ok_n, bad_n = caches.get("salt_ok", 0), caches.get("salt_fail", 0)
        if ok_n and not bad_n:
            say(OK, "רענון salt", f"{ok_n} הצלחות, אפס כשלונות")
        elif ok_n and bad_n:
            say(WARN, "רענון salt", f"{ok_n} הצליחו, {bad_n} נכשלו · "
                                    f"{caches.get('salt_last_err', '')}")
        elif bad_n:
            say(BAD, "רענון salt", f"{bad_n} כשלונות · "
                                   f"{caches.get('salt_last_err', '')}")
        else:
            say(WARN, "רענון salt", "עוד לא רץ (הראשון ~10 דקות אחרי הפעלה)")
    else:
        say(WARN, "רענון salt", "fix_salt_refresh לא מוחל")

    fix = caches.get("hls_fix", 0)
    if fix:
        say(WARN, "המרות ffmpeg פעילות", f"{fix} — תקין אם מישהו צופה בערוץ חי")

    if quick:
        return

    # פתיחת זרם אמיתית: בקשת בייט אחד. זו העלות שהצופה משלם על "פליי".
    st, body, _, err = get(LOCAL + "/content/lite", timeout=40)
    try:
        cat = json.loads(body) if st == 200 else []
    except Exception:
        cat = []
    vod = [m for m in cat
           if not m.get("is_live") and "/stream/" in str(m.get("video_url") or "")]
    live = [m for m in cat if m.get("is_live")
            and "/hls-relay/" in str(m.get("video_url") or "")
            and "/_fix/" not in str(m.get("video_url") or "")]
    say(OK if vod else WARN, "קטלוג", f"{len(cat)} פריטים · {len(vod)} להזרמה · "
                                      f"{len(live)} ערוצים חיים")

    def local_of(u):
        p = urlsplit(u)
        o = urlsplit(LOCAL)
        return urlunsplit((o.scheme, o.netloc, p.path, p.query, ""))

    import random
    picks = random.sample(vod, min(3, len(vod)))
    times = []
    for m in picks:
        st, _b, dt, err = get(local_of(m["video_url"]), timeout=60, rng="bytes=0-0")
        times.append(dt if st in (200, 206) else None)
    good = [t for t in times if t is not None]
    n = len(picks)
    if not picks:
        say(WARN, "פתיחת זרם", "אין פריטים לדגום")
    elif not good:
        say(BAD, "פתיחת זרם", f"אף אחת מ-{n} הדגימות לא נפתחה")
    else:
        # המכנה הוא מה שנדגם בפועל ולא 3 קבוע, וכישלון חלקי אינו ירוק:
        # גרסה קודמת הדפיסה "1/3 ✅" גם כששתיים נכשלו — בדיקה שמדווחת
        # תקין על כישלון גרועה מלא לבדוק בכלל.
        worst = max(good)
        lvl = OK if worst < 3 else (WARN if worst < 8 else BAD)
        if len(good) < n:
            lvl = BAD if len(good) * 2 < n else WARN
        say(lvl, "פתיחת זרם", f"{len(good)}/{n} נפתחו · הגרוע {worst:.2f}ש · "
                              f"הטוב {min(good):.2f}ש")

    # ערוץ חי: ה-playlist חייב להתקדם. שתי דגימות במרווח.
    if live:
        m = random.choice(live)
        u = local_of(m["video_url"])
        st1, b1, _, _ = get(u, timeout=20)
        time.sleep(6)
        st2, b2, _, _ = get(u, timeout=20)
        if st1 != 200 or st2 != 200:
            say(BAD, "ערוץ חי", f"HTTP {st1}/{st2} — לא נפתח")
        elif b1 == b2:
            say(WARN, "ערוץ חי", "ה-playlist לא זז ב-6 שניות (ייתכן שתקין "
                                 "אם המקטע ארוך)")
        else:
            say(OK, "ערוץ חי", "ה-playlist מתקדם")


# ── משאבים ───────────────────────────────────────────────────────────────────
def check_resources():
    head("משאבים")
    try:
        du = shutil.disk_usage("/")
        pct = du.used * 100.0 / du.total
        free_gb = du.free / (1024 ** 3)
        lvl = OK if pct < 80 else (WARN if pct < 92 else BAD)
        say(lvl, "דיסק", f"{pct:.0f}% בשימוש · {free_gb:.1f} GB פנוי")
    except Exception as e:
        say(WARN, "דיסק", str(e))

    work = Path("/opt/zovex-bot/mkvwork")
    if work.exists():
        rc, out, _ = sh(["du", "-sb", str(work)], timeout=60)
        if rc == 0 and out.split():
            gb = int(out.split()[0]) / (1024 ** 3)
            # הקבצים אמורים להימחק שעה אחרי הטיפול. הצטברות כאן ממלאת
            # את הדיסק ומפילה גם את ההזרמה.
            lvl = OK if gb < 5 else (WARN if gb < 20 else BAD)
            say(lvl, "תיקיית mkvtool", f"{gb:.1f} GB")

    try:
        mem = dict(l.split(":", 1) for l in
                   Path("/proc/meminfo").read_text().splitlines() if ":" in l)
        tot = int(mem["MemTotal"].split()[0])
        avail = int(mem["MemAvailable"].split()[0])
        pct = 100 - avail * 100.0 / tot
        lvl = OK if pct < 85 else (WARN if pct < 95 else BAD)
        say(lvl, "זיכרון", f"{pct:.0f}% בשימוש · {avail / 1048576:.1f} GB פנוי")
    except Exception:
        pass

    load = Path("/proc/loadavg").read_text().split()[:3]
    ncpu = os.cpu_count() or 1
    lvl = OK if float(load[0]) < ncpu else (WARN if float(load[0]) < ncpu * 2 else BAD)
    say(lvl, "עומס", f"{' '.join(load)} · {ncpu} ליבות")


# ── המדים ────────────────────────────────────────────────────────────────────
def check_monitors():
    head("המדים")
    if not SNAP_LOG.exists():
        say(WARN, "snapwatch", "אין קובץ לוג")
        return
    try:
        lines = [l for l in SNAP_LOG.read_text(encoding="utf-8",
                                               errors="replace").splitlines()
                 if "| up" in l]
    except Exception as e:
        say(WARN, "snapwatch", str(e))
        return
    if not lines:
        say(WARN, "snapwatch", "הקובץ קיים אבל אין בו דגימות")
        return

    age = time.time() - SNAP_LOG.stat().st_mtime
    lvl = OK if age < 700 else (WARN if age < 3600 else BAD)
    say(lvl, "snapwatch אוסף", f"{len(lines)} דגימות · "
                               f"האחרונה לפני {int(age // 60)} דקות")

    def col(line, key):
        m = re.search(key + r"\s+([0-9.]+)", line)
        return float(m.group(1)) if m else None

    recent = lines[-24:]
    conns = [c for c in (col(l, "conn") for l in recent) if c is not None]
    if conns:
        avg = sum(conns) / len(conns)
        # הבסיס שנמדד לפני התיקונים היה 6.8 לחלון של 5 דקות.
        lvl = OK if avg < 3 else (WARN if avg < 20 else BAD)
        say(lvl, "סחרור חיבורים", f"ממוצע {avg:.1f} לחלון · "
                                  f"מקסימום {max(conns):.0f} · (בסיס היה 6.8)")
    ups = [c for c in (col(l, "up") for l in recent) if c is not None]
    if ups:
        say(OK, "השירות למעלה", f"{ups[-1]:.1f} שעות")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                    help="לדלג על בדיקות שנוגעות בטלגרם")
    a = ap.parse_args()

    print("=" * 62)
    print(f"  בדיקת מערכת · {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 62)

    check_services()
    check_patches()
    check_site()
    check_stream(a.quick)
    check_resources()
    check_monitors()

    print("\n" + "=" * 62)
    tot = sum(_score.values())
    print(f"  {OK} {_score['ok']}    {WARN}{_score['warn']}    "
          f"{BAD} {_score['bad']}     (מתוך {tot} בדיקות)")
    if _score["bad"]:
        print("  יש כשלים. הדבק את הפלט.")
    elif _score["warn"]:
        print("  אין כשלים. יש אזהרות שכדאי להסתכל עליהן.")
    else:
        print("  הכל עובד.")
    print("=" * 62)
    print("(כתובות, IP ומזהים צונזרו — אפשר להדביק בבטחה.)")


if __name__ == "__main__":
    main()
