#!/usr/bin/env python3
"""who_is_watching — מי צופה עכשיו ובמה, לפני שמאפסים את השירות.

קורא בלבד. לא כותב כלום, לא נוגע בשירות, ואפשר להריץ אותו מתי שבא לך.

## מאיפה המידע

לשרת אין מעקב "צופים פעילים" — אין טבלה כזאת בקוד. מה שכן יש זה יומן
הגישה של nginx, שבו כל בקשה למקטע וידאו רשומה עם זמן וכתובת. נגן
שמנגן סרט מושך מקטע כל כמה שניות, ולכן "מי ביקש מקטע בדקות האחרונות"
הוא בדיוק "מי צופה עכשיו".

אבל nginx כותב שורה ליומן רק **כשהבקשה נגמרת**, וניגון ישיר הוא לא פעם
בקשה אחת ארוכה שנשארת פתוחה דקות ארוכות. צופה כזה לא מופיע ביומן עד
שהוא מסיים — וכך הספירה יצאה חסרה. לכן נבדקים גם החיבורים הפתוחים ממש
עכשיו, מ-/proc/net/tcp, ומוצלבים מול מה שאותה כתובת משכה לאחרונה.

זה לא תלוי בהתחברות לחשבון בשום שלב: הספירה היא לפי כתובת רשת, ומשתמש
בלי חשבון גוגל נספר בדיוק כמו כל אחד אחר.

    /stream/<ערוץ>/<הודעה>      ניגון ישיר
    /fs/<ערוץ>/<הודעה>          ניגון ישיר עם כותרת מתוקנת
    /vh/<ערוץ>/<הודעה>/...      מקטעים (קפיצה ו-resume עובדים)
    /vt/<ערוץ>/<הודעה>/...      המרה חיה — זה מה שרסטרט הורג
    /hls-relay/...              שידורים חיים

## פרטיות

כתובות IP של הצופים מוצגות ממוסכות (‎1.2.3.x) — מספיק כדי לספור אנשים
שונים, ולא מספיק כדי לזהות מישהו בצילום מסך ששולחים הלאה. ‎--full מציג
מלא אם אתה באמת צריך. שידורים חיים נספרים בלי להדפיס את הנתיב, כי הוא
מכיל את כתובת הספק.

## שימוש

    python3 who_is_watching.py              # 5 הדקות האחרונות
    python3 who_is_watching.py --minutes 15
    python3 who_is_watching.py --full       # בלי מיסוך IP
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/opt/zovex-bot/data"))
LOG_GLOB = os.environ.get("NGINX_LOG_GLOB", "/var/log/nginx/*access*.log")
TAIL_BYTES = 12 * 1024 * 1024        # מספיק לשעות, וזול לקרוא
# ניתן לדריסה רק לצורך בדיקה של הכלי עצמו מול קובץ מזויף
TCP_FILES = tuple(os.environ.get("PROC_TCP",
                                 "/proc/net/tcp,/proc/net/tcp6").split(","))

# 1.2.3.4 - - [22/Sep/2026:15:04:05 +0300] "GET /vh/-100.../7170/s3.ts HTTP/1.1" 200 1234
LINE = re.compile(
    r'^(?P<ip>[0-9a-fA-F:.]+)\s+\S+\s+\S+\s+\[(?P<ts>[^\]]+)\]\s+'
    r'"(?P<method>[A-Z]+)\s+(?P<path>[^"\s]+)[^"]*"\s+(?P<code>\d{3})\s+(?P<bytes>\d+)')
MEDIA = re.compile(r'^/(stream|fs|vh|vt)/(-?\d+)/(\d+)')
LIVE = re.compile(r'^/hls-relay/')
ROUTE_HE = {"stream": "ניגון ישיר", "fs": "ניגון ישיר",
            "vh": "מקטעים", "vt": "המרה חיה"}


def parse_ts(s):
    try:
        return datetime.strptime(s, "%d/%b/%Y:%H:%M:%S %z")
    except ValueError:
        return None


def he_n(n, one="צופה אחד", many="{} צופים"):
    """עברית: "1 צופים" פשוט לא נקרא נכון."""
    return one if n == 1 else many.format(n)


def mask(ip, full):
    if full:
        return ip
    if ":" in ip:                      # IPv6
        return ":".join(ip.split(":")[:3]) + "::x"
    p = ip.split(".")
    return ".".join(p[:3]) + ".x" if len(p) == 4 else ip


def titles():
    """מיפוי (ערוץ, הודעה) → שם להצגה, מתוך content.json."""
    out = {}
    f = DATA_DIR / "content.json"
    if not f.exists():
        return out
    try:
        items = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return out
    for it in items:
        m = re.search(r"/stream/(-?\d+)/(\d+)", str(it.get("video_url", "")))
        if not m:
            continue
        name = it.get("series_name") or it.get("title") or "—"
        if it.get("episode_number"):
            name += f" · עונה {it.get('season_number', 1)} פרק {it['episode_number']}"
        elif it.get("year"):
            name += f" ({it['year']})"
        out[(m.group(1), m.group(2))] = name
    return out


def ffmpeg_now():
    """כמה ffmpeg רצים, ומתוכם כמה הם המרה חיה. קריאה מ-/proc בלבד.

    הזיהוי לפי comm (שם הקובץ הרץ) ולא לפי חיפוש "ffmpeg" בשורת הפקודה:
    כל פקודה שיש בה את המילה — גם הכלי הזה עצמו — הייתה נספרת כתהליך
    המרה, והמסקנה למטה הייתה יוצאת הפוכה.
    """
    vt = other = 0
    for c in glob.glob("/proc/[0-9]*/comm"):
        try:
            with open(c, encoding="utf-8", errors="replace") as fh:
                if fh.read().strip() != "ffmpeg":
                    continue
            with open(c[:-4] + "cmdline", "rb") as fh:
                cmd = fh.read().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue                       # תהליך שנגמר בזמן הקריאה
        if "zovex-vt" in cmd:
            vt += 1
        else:
            other += 1
    return vt, other


def _hex_ip(h):
    """כתובת מ-/proc/net/tcp: הקסה little-endian, IPv4 או IPv6."""
    if len(h) == 8:
        b = bytes.fromhex(h)[::-1]
        return ".".join(str(x) for x in b)
    if len(h) == 32:
        words = [bytes.fromhex(h[i:i + 8])[::-1] for i in range(0, 32, 8)]
        raw = b"".join(words)
        if raw[:12] == b"\x00" * 10 + b"\xff\xff":      # IPv4 ממופה
            return ".".join(str(x) for x in raw[12:])
        p = [raw[i:i + 2].hex() for i in range(0, 16, 2)]
        return ":".join(s.lstrip("0") or "0" for s in p)
    return ""


def open_peers(ports=(443, 80), files=("/proc/net/tcp", "/proc/net/tcp6")):
    """כתובות שיש להן חיבור TCP פתוח לשרת ממש עכשיו.

    זו הבדיקה שהיומן לא יכול לתת: nginx כותב שורה ליומן **כשהבקשה
    נגמרת**. ניגון ישיר הוא לא פעם בקשה אחת ארוכה שנשארת פתוחה דקות,
    ולכן הצופה פשוט לא קיים ביומן עד שהוא מסיים. מכאן הוא כן נראה.
    """
    peers = set()
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                next(fh, None)
                for line in fh:
                    p = line.split()
                    if len(p) < 4 or p[3] != "01":       # ESTABLISHED
                        continue
                    lh, lp = p[1].rsplit(":", 1)
                    rh, _ = p[2].rsplit(":", 1)
                    if int(lp, 16) not in ports:
                        continue
                    ip = _hex_ip(rh)
                    if ip and not ip.startswith(("127.", "::1")) and ip != "0.0.0.0":
                        peers.add(ip)
        except (OSError, StopIteration):
            continue
    return peers


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--full", action="store_true", help="בלי מיסוך IP")
    ap.add_argument("--lookback", type=float, default=60,
                    help="כמה דקות אחורה לחפש מה כל חיבור פתוח צופה בו")
    a = ap.parse_args()

    logs = [p for p in glob.glob(LOG_GLOB) if not p.endswith(".gz")]
    if not logs:
        print(f"❌ לא נמצא יומן nginx ב-{LOG_GLOB}")
        print("   אם היומן במקום אחר:  NGINX_LOG_GLOB='/path/*.log' python3 who_is_watching.py")
        return 1

    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=a.minutes)
    since_look = now - timedelta(minutes=max(a.lookback, a.minutes))
    vod = defaultdict(lambda: {"ips": set(), "routes": set(), "last": None,
                               "hits": 0, "bytes": 0})
    live_ips, seen_lines, newest = set(), 0, None
    last_by_ip = {}          # כתובת → (זמן, מה נצפה) — גם מחוץ לחלון

    for path in logs:
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as fh:
                if size > TAIL_BYTES:
                    fh.seek(size - TAIL_BYTES)
                    fh.readline()             # שורה חתוכה
                raw = fh.read().decode("utf-8", "replace")
        except OSError as e:
            print(f"⚠️  לא ניתן לקרוא {path}: {e}")
            continue
        for line in raw.splitlines():
            m = LINE.match(line)
            if not m:
                continue
            ts = parse_ts(m.group("ts"))
            if not ts:
                continue
            if newest is None or ts > newest:
                newest = ts
            if ts < since_look:
                continue
            p = m.group("path").split("?")[0]
            ip = m.group("ip")
            if LIVE.match(p):
                # שידור חי — נספר בלי להדפיס את הנתיב, שמכיל את כתובת הספק
                prev = last_by_ip.get(ip)
                if prev is None or ts > prev[0]:
                    last_by_ip[ip] = (ts, None)
                if ts >= since:
                    live_ips.add(ip)
                continue
            mm = MEDIA.match(p)
            if not mm:
                continue
            prev = last_by_ip.get(ip)
            if prev is None or ts > prev[0]:
                last_by_ip[ip] = (ts, (mm.group(2), mm.group(3)))
            if ts < since:
                continue
            seen_lines += 1
            route, chat, msg = mm.group(1), mm.group(2), mm.group(3)
            e = vod[(chat, msg)]
            e["ips"].add(m.group("ip"))
            e["routes"].add(route)
            e["hits"] += 1
            e["bytes"] += int(m.group("bytes"))
            if e["last"] is None or ts > e["last"]:
                e["last"] = ts

    names = titles()
    logged_ips = set(live_ips)
    for e in vod.values():
        logged_ips |= e["ips"]

    # ── מי מחזיק חיבור פתוח ממש עכשיו ────────────────────────────────────
    # nginx כותב שורה ליומן רק כשהבקשה נגמרת, וניגון ישיר הוא לא פעם בקשה
    # אחת ארוכה. בלי הבדיקה הזאת צופה כזה פשוט לא מופיע עד שהוא מסיים —
    # וזה מה שגרם לספירה לצאת חסרה.
    peers = open_peers(files=TCP_FILES)
    open_watchers = {}          # כתובת → (לפני כמה שניות נראתה, מה)
    browsing = 0
    for ip in peers:
        ent = last_by_ip.get(ip)
        if ent is None:
            browsing += 1       # חיבור פתוח בלי היסטוריית וידאו — גלישה
            continue
        open_watchers[ip] = ent
    all_ips = logged_ips | set(open_watchers)

    print(f"── {a.minutes:g} הדקות האחרונות " + "─" * 30)
    # אין ולו שורה אחת שנקראה: או שזה לא היומן הנכון, או שהוא זה עתה
    # הסתובב. לא מכריעים — אומרים את זה, וממשיכים לבדיקת ה-ffmpeg, שהיא
    # עצמאית לגמרי מהיומן.
    no_log = newest is None
    if no_log:
        print("⚠️  לא נקראה אף שורה מהיומן — או שזה לא הקובץ הנכון, או")
        print(f"    שהוא הסתובב הרגע. הקבצים שנבדקו: {', '.join(logs)}")
    else:
        age = (now - newest).total_seconds()
        if age > 300:
            print(f"⚠️  הרשומה האחרונה ביומן היא מלפני {age / 60:.0f} דקות — "
                  f"ייתכן שהתאריכון של השרת או היומן אינם מה שחשבתי.")

    print(f"צופים ייחודיים: {len(all_ips)}   ·   "
          f"שידור חי: {len(live_ips)}   ·   "
          f"VOD: {he_n(len(vod), 'פריט אחד', '{} פריטים')}")
    print()

    if vod:
        print("מה נצפה עכשיו:")
        rows = sorted(vod.items(), key=lambda kv: kv[1]["last"], reverse=True)
        for (chat, msg), e in rows:
            title = names.get((chat, msg)) or f"(לא בקטלוג) {chat}/{msg}"
            secs = int((now - e["last"]).total_seconds())
            routes = "+".join(ROUTE_HE.get(r, r) for r in sorted(e["routes"]))
            who = ", ".join(sorted(mask(i, a.full) for i in e["ips"]))
            print(f"  {he_n(len(e['ips']))} · {title}")
            print(f"      {routes} · לפני {secs} שניות · "
                  f"{e['bytes'] / 1048576:.0f}MB · {who}")
    else:
        print("אף אחד לא סיים בקשת וידאו בטווח הזה.")
    print()

    # מי שהיומן לא יכול היה להראות: חיבור פתוח עכשיו, בלי שהבקשה נגמרה.
    only_open = {ip: v for ip, v in open_watchers.items() if ip not in logged_ips}
    if only_open:
        print("חיבור פתוח עכשיו, בלי שורה ביומן (בקשה ארוכה שעוד רצה):")
        for ip, (ts, key) in sorted(only_open.items(),
                                    key=lambda kv: kv[1][0], reverse=True):
            what = "שידור חי" if key is None else (
                names.get(key) or f"(לא בקטלוג) {key[0]}/{key[1]}")
            mins = (now - ts).total_seconds() / 60
            print(f"  {mask(ip, a.full)} · {what} · "
                  f"נרשם לאחרונה לפני {mins:.0f} דקות")
        print()
    if browsing:
        print(he_n(browsing, "עוד חיבור פתוח אחד",
                   "עוד {} חיבורים פתוחים")
              + " בלי היסטוריית וידאו — גלישה באתר, לא צפייה.")
        print()

    vt_procs, other_procs = ffmpeg_now()
    print(f"ffmpeg שרצים עכשיו: {vt_procs + other_procs} "
          f"(מהם המרה חיה: {vt_procs})")
    print()

    # ── שורה תחתונה ──────────────────────────────────────────────────────
    vt_watchers = sum(len(e["ips"]) for e in vod.values() if "vt" in e["routes"])
    print("שורה תחתונה:")
    if no_log and not vt_procs:
        print("  היומן לא נתן מידע, ולכן אני לא יודעת כמה אנשים צופים.")
        print("  מה שכן: אין אף תהליך המרה חיה שרץ, וזאת בדיקה שלא")
        print("  תלויה ביומן — כלומר לפחות אף אחד לא באמצע המרה שתיקטע.")
    elif not all_ips and not vt_procs:
        print("  אף אחד לא צופה. אפשר לאפס בשקט.")
    elif vt_watchers or vt_procs:
        print(f"  בהמרה חיה: {he_n(max(vt_watchers, vt_procs))}. רסטרט יקטע את")
        print("  הסרט ויחייב להתחיל אותו מחדש. שווה לחכות כמה דקות.")
    else:
        print(f"  {he_n(len(all_ips))}, כולם על ניגון ישיר או מקטעים.")
        print("  הרסטרט יעצור להם לכמה שניות והנגן ימשיך מעצמו.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
