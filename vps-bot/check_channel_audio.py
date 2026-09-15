#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_channel_audio.py — איזה ערוץ חי משדר אודיו שהדפדפן לא מפענח.

דפדפן מפענח AAC / MP3 / Opus / FLAC בלבד (כך כתוב ב-main.py:7483).
ערוץ ששולח AC-3, E-AC-3 או MP2 מגיע לצופה עם וידאו ובלי קול — וזה
בדיוק מה שקורה בספורט 5.

קריאה בלבד: רק ffprobe דרך ה-relay המקומי, אין שינוי בשום קובץ ואין
restart. אפשר להריץ תוך כדי צפייה.

    python3 check_channel_audio.py
    python3 check_channel_audio.py --workers 3 --filter ספורט

שלושה workers בכוונה. בדיקה מקבילית אגרסיבית על אותם ערוצים כבר
ייצרה כאן 50 כשלים מדומים — העומס עצמו הפיל את המקורות.
"""
import argparse, concurrent.futures as cf, json, os, re, subprocess, sys
from collections import Counter
from pathlib import Path

DATA = Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
PORT = int(os.environ.get("PORT", "8000"))
BROWSER_OK = {"aac", "mp3", "opus", "flac"}


def probe(url: str):
    """(קודק_וידאו, קודק_אודיו) או (None, שגיאה)."""
    exe = "ffprobe"
    try:
        r = subprocess.run(
            [exe, "-v", "error", "-show_entries", "stream=codec_type,codec_name",
             "-of", "json", "-analyzeduration", "4000000", "-probesize", "4000000",
             url], capture_output=True, text=True, timeout=45)
        if r.returncode != 0:
            return None, (r.stderr.strip().splitlines() or ["ffprobe נכשל"])[-1][:70]
        streams = json.loads(r.stdout or "{}").get("streams") or []
        v = next((s.get("codec_name") for s in streams if s.get("codec_type") == "video"), None)
        a = next((s.get("codec_name") for s in streams if s.get("codec_type") == "audio"), None)
        return v, a
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except FileNotFoundError:
        sys.exit("ffprobe לא מותקן")
    except Exception as e:
        return None, f"{type(e).__name__}"


def local_url(video_url: str):
    """ממיר קישור ציבורי לקישור דרך ה-relay המקומי — אותו מסלול
    ש-ffmpeg עצמו משתמש בו, כולל רשימת ההיתר."""
    m = re.search(r"/hls-relay/(?:_fix/)?(.+)$", video_url or "")
    if not m:
        return None
    return f"http://127.0.0.1:{PORT}/hls-relay/{m.group(1)}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--filter", default="")
    a = ap.parse_args()

    if not CONTENT.exists():
        sys.exit(f"לא נמצא: {CONTENT}")
    items = json.loads(CONTENT.read_text(encoding="utf-8"))
    chans = []
    for i in items:
        u = local_url(i.get("video_url") or "")
        t = (i.get("title") or "").strip()
        if u and (not a.filter or a.filter in t):
            chans.append((t, u, "_fix/" in (i.get("video_url") or "")))
    if not chans:
        sys.exit("לא נמצאו ערוצים חיים")

    print(f"בודק {len(chans)} ערוצים ב-{a.workers} תהליכים במקביל...\n")
    rows = []
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(probe, u): (t, fix) for t, u, fix in chans}
        for n, f in enumerate(cf.as_completed(futs), 1):
            t, fix = futs[f]
            v, aud = f.result()
            rows.append((t, v, aud, fix))
            print(f"\r  {n}/{len(chans)}", end="", flush=True)
    print("\n")

    bad = [r for r in rows if r[1] and r[2] and r[2] not in BROWSER_OK]
    noaud = [r for r in rows if r[1] and not r[2]]
    failed = [r for r in rows if not r[1]]
    ok = [r for r in rows if r[1] and r[2] in BROWSER_OK]

    print("=" * 64)
    print(f"🔴 אודיו שהדפדפן לא מפענח: {len(bad)}")
    for t, v, aud, fix in sorted(bad, key=lambda r: r[2]):
        route = "_fix" if fix else "ישיר"
        print(f"     {t:<30} {aud:<8} (וידאו {v}, {route})")
    if bad:
        c = Counter(r[2] for r in bad)
        print(f"     לפי קודק: {', '.join(f'{k}×{v}' for k, v in c.most_common())}")

    if noaud:
        print(f"\n🟠 בלי רצועת אודיו כלל: {len(noaud)}")
        for t, v, _, _ in noaud[:10]:
            print(f"     {t}")

    if failed:
        print(f"\n⚪ לא נבדקו (ייתכן שהערוץ פשוט מת): {len(failed)}")
        for t, _, err, _ in failed[:12]:
            print(f"     {t:<30} {err}")

    print(f"\n🟢 תקינים: {len(ok)}")
    print("=" * 64)
    if bad:
        print("התיקון:  python3 fix_hls_audio.py --check   ואז בלי --check")
        print("ממיר אודיו ל-AAC רק לערוצים שצריך. עלות: אחוז-שניים מליבה.")
    else:
        print("אין ערוץ עם בעיית אודיו. אם אין קול — הסיבה במקום אחר.")


if __name__ == "__main__":
    main()
