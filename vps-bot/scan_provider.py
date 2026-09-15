#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan_provider.py — ממפה אילו ערוצים קיימים בחשבון שלך אצל הספק.

כתובות הספק בנויות כך שרק המספר משתנה:
    https://HOST/p/USER/s/<N>/playlist.m3u8

הסורק עובר על טווח מספרים, בודק מי מהם עונה, ומזהה כל ערוץ לפי
service_name — זרם MPEG-TS נושא את שם הערוץ בתוך המטא-דאטה שלו, ולכן
אין צורך לנחש מה כל מספר מייצג.

בסוף הוא משווה מול content.json ומסמן מה כבר יש לך ומה חדש.

    python3 scan_provider.py --base 'https://HOST:PORT/p/USER/s/{n}/playlist.m3u8'
    python3 scan_provider.py --base '...' --from 1 --to 400
    python3 scan_provider.py --base '...' --filter ספורט
    python3 scan_provider.py --base '...' --out /tmp/found.json

להריץ על השרת: ספקי IPTV נועלים לרוב לפי כתובת IP, ומהמחשב הביתי
התשובות יהיו שונות.

קריאה בלבד. לא נוגע ב-content.json ולא מפעיל restart.
עובד ב-3 תהליכים ובהשהיה קצרה — סריקה אגרסיבית מעמיסה על הספק,
ובשרת הזה כבר ראינו איך עומס שאנחנו יוצרים מייצר 50 כשלים מדומים.
"""
import argparse, json, os, re, subprocess, sys, threading, time
import concurrent.futures as cf
from pathlib import Path
from urllib.request import Request, urlopen

DATA = Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
UA = "VLC/3.0.20 LibVLC/3.0.20"
_gate = threading.Semaphore(3)


def head(url: str, timeout=12):
    """קיים או לא. זול: לא מוריד את הזרם, רק את הפלייליסט."""
    try:
        with urlopen(Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
            body = r.read(4096).decode("utf-8", "ignore")
            return r.status, body
    except Exception as e:
        code = getattr(e, "code", None)
        return code, str(e)[:60]


def identify(url: str, timeout=40):
    """שם הערוץ + קודקים, מתוך המטא-דאטה של הזרם."""
    try:
        r = subprocess.run(
            ["ffprobe", "-hide_banner", "-v", "error",
             "-user_agent", UA,
             "-show_entries", "format_tags=service_name,service_provider",
             "-show_entries", "stream=codec_type,codec_name",
             "-of", "json", "-analyzeduration", "4000000", "-probesize", "4000000",
             url], capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            return None, None, None
        j = json.loads(r.stdout or "{}")
        tags = (j.get("format") or {}).get("tags") or {}
        name = tags.get("service_name") or tags.get("service_provider")
        streams = j.get("streams") or []
        v = next((s.get("codec_name") for s in streams if s.get("codec_type") == "video"), None)
        a = next((s.get("codec_name") for s in streams if s.get("codec_type") == "audio"), None)
        return name, v, a
    except Exception:
        return None, None, None


def probe_one(n: int, base: str, deep: bool):
    url = base.replace("{n}", str(n))
    with _gate:
        time.sleep(0.25)          # נימוס כלפי הספק
        code, body = head(url)
    if code != 200 or "#EXTM3U" not in (body or ""):
        return None
    name = v = a = None
    if deep:
        with _gate:
            name, v, a = identify(url)
    return {"n": n, "url": url, "name": name, "video": v, "audio": a}


def existing_ids(base: str):
    """אילו מספרים כבר יושבים בקטלוג, כדי לסמן מה חדש."""
    have = {}
    if not CONTENT.exists():
        return have
    try:
        items = json.loads(CONTENT.read_text(encoding="utf-8"))
    except Exception:
        return have
    # בונים תבנית מה-base: הכל חוץ מהמספר
    pat = re.escape(base).replace(re.escape("{n}"), r"(\d+)")
    pat = pat.split("://", 1)[-1]          # הקטלוג שומר דרך /hls-relay/
    rx = re.compile(pat)
    for i in items:
        u = i.get("video_url") or ""
        m = rx.search(u)
        if m:
            have[int(m.group(1))] = (i.get("title") or "").strip()
    return have


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True,
                    help="כתובת עם {n} במקום המספר")
    ap.add_argument("--from", dest="lo", type=int, default=1)
    ap.add_argument("--to", dest="hi", type=int, default=400)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--filter", default="",
                    help="הצג רק ערוצים ששמם מכיל (לא תלוי רישיות)")
    ap.add_argument("--fast", action="store_true",
                    help="רק מי עונה, בלי זיהוי שם (מהיר בהרבה)")
    ap.add_argument("--out", default="", help="שמור את התוצאה כ-JSON")
    a = ap.parse_args()

    if "{n}" not in a.base:
        sys.exit("--base חייב להכיל {n} במקום המספר")
    if a.hi < a.lo:
        sys.exit("--to קטן מ---from")

    have = existing_ids(a.base)
    total = a.hi - a.lo + 1
    print(f"סורק {total} מספרים ({a.lo}–{a.hi}) ב-{a.workers} תהליכים")
    print(f"כבר בקטלוג: {len(have)} ערוצים מהספק הזה")
    print("קריאה בלבד — לא נוגע בקטלוג.\n")

    found, done = [], 0
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(probe_one, n, a.base, not a.fast)
                for n in range(a.lo, a.hi + 1)]
        for f in cf.as_completed(futs):
            done += 1
            r = f.result()
            if r:
                found.append(r)
            if done % 10 == 0 or done == total:
                print(f"\r  {done}/{total} · נמצאו {len(found)}".ljust(40),
                      end="", flush=True)
    print("\n")

    found.sort(key=lambda r: r["n"])
    new = [r for r in found if r["n"] not in have]
    old = [r for r in found if r["n"] in have]

    def show(rows, title):
        if a.filter:
            # לא תלוי רישיות: שם הערוץ במטא-דאטה יכול להיות SPORT או Sport
            f = a.filter.lower()
            rows = [r for r in rows if f in (r.get("name") or "").lower()]
        print(f"\n{title}: {len(rows)}")
        for r in rows:
            nm = r.get("name") or "(בלי שם במטא-דאטה)"
            codecs = f"{r.get('video') or '?'}/{r.get('audio') or '?'}"
            mark = f"  ← יש לך בשם {have[r['n']]!r}" if r["n"] in have else ""
            print(f"   {r['n']:>4}  {nm:<34} {codecs:<14}{mark}")

    print("=" * 70)
    show(new, "🆕 לא בקטלוג שלך")
    show(old, "✓ כבר בקטלוג")
    print("=" * 70)
    print(f"סה\"כ עונים: {len(found)} מתוך {total}")

    if a.out:
        Path(a.out).write_text(json.dumps(found, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        print(f"נשמר: {a.out}")
    if new:
        print("\nלהוסיף לאתר: קח את המספרים מהרשימה העליונה והוסף אותם")
        print("בפאנל כערוץ חי. הכתובת הציבורית היא /hls-relay/<host>/<path>.")


if __name__ == "__main__":
    main()
