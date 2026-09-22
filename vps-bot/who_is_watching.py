#!/usr/bin/env python3
"""who_is_watching — מי צופה עכשיו ובמה, לפני שמאפסים את השירות.

קורא בלבד. לא כותב כלום, לא נוגע בשירות, ואפשר להריץ אותו מתי שבא לך.

## מאיפה המידע

לשרת אין מעקב "צופים פעילים" — אין טבלה כזאת בקוד. מה שכן יש זה יומן
הגישה של nginx, שבו כל בקשה למקטע וידאו רשומה עם זמן וכתובת. נגן
שמנגן סרט מושך מקטע כל כמה שניות, ולכן "מי ביקש מקטע בדקות האחרונות"
הוא בדיוק "מי צופה עכשיו".

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


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--full", action="store_true", help="בלי מיסוך IP")
    a = ap.parse_args()

    logs = [p for p in glob.glob(LOG_GLOB) if not p.endswith(".gz")]
    if not logs:
        print(f"❌ לא נמצא יומן nginx ב-{LOG_GLOB}")
        print("   אם היומן במקום אחר:  NGINX_LOG_GLOB='/path/*.log' python3 who_is_watching.py")
        return 1

    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=a.minutes)
    vod = defaultdict(lambda: {"ips": set(), "routes": set(), "last": None,
                               "hits": 0, "bytes": 0})
    live_ips, seen_lines, newest = set(), 0, None

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
            if ts < since:
                continue
            seen_lines += 1
            p = m.group("path").split("?")[0]
            if LIVE.match(p):
                live_ips.add(m.group("ip"))
                continue
            mm = MEDIA.match(p)
            if not mm:
                continue
            route, chat, msg = mm.group(1), mm.group(2), mm.group(3)
            e = vod[(chat, msg)]
            e["ips"].add(m.group("ip"))
            e["routes"].add(route)
            e["hits"] += 1
            e["bytes"] += int(m.group("bytes"))
            if e["last"] is None or ts > e["last"]:
                e["last"] = ts

    names = titles()
    all_ips = set(live_ips)
    for e in vod.values():
        all_ips |= e["ips"]

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
          f"שידור חי: {len(live_ips)}   ·   VOD: {len(vod)} פריטים")
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
        print("אף אחד לא מושך וידאו בטווח הזה.")
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
