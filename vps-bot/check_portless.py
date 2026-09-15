#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_portless.py — כמה ערוצים מצביעים לשער חסר-פורט שמת, ואיזה שער עובד.

הראיה: האפליקציה החזירה על ערוץ 490
    shaka 1003 (TIMEOUT) | hls networkError/manifestLoadError
    /hls-relay/tv.embyil.tv/live/490/chunks.m3u8
כלומר המניפסט לא נטען בכלל — לא בעיית נגן אלא כתובת שלא עונה.

הספק מגיש כמה שערים במקביל (‎:86, :7070, וללא פורט). הסקריפט לוקח כל
ערוץ שמצביע לשער ללא פורט, ובודק אותו מול השערים החלופיים עם אותו
מספר ערוץ — כדי לדעת אם התיקון הוא הוספת פורט בלבד.

קריאה בלבד: לא נוגע בקטלוג, לא מפעיל restart.

    python3 check_portless.py
    python3 check_portless.py --workers 3 --out /tmp/portless.json
"""
import argparse, json, os, re, subprocess, sys
import concurrent.futures as cf
from pathlib import Path

DATA = Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
UA = "VLC/3.0.20 LibVLC/3.0.20"

# השערים שאומתו כעובדים בסריקת הפריימים.
ALTS = [
    ("‎:86 /live", "https://{host}:86/live/{n}/chunks.m3u8"),
    (":7070 /p", "https://{host}:7070/p/embyil/s/{n}/playlist.m3u8"),
]


def probe(url: str, timeout=14):
    """(קוד, גודל) — האם המניפסט נמשך בפועל."""
    r = subprocess.run(
        ["curl", "-sS", "-m", str(timeout), "-o", "/dev/null",
         "-A", UA, "-w", "%{http_code} %{size_download}", url],
        capture_output=True, text=True)
    parts = (r.stdout or "0 0").split()
    try:
        return int(parts[0]), int(parts[1])
    except Exception:
        return 0, 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    if not CONTENT.exists():
        sys.exit(f"לא נמצא: {CONTENT}")
    items = json.loads(CONTENT.read_text(encoding="utf-8"))

    # ערוצים שמצביעים לשער ללא פורט: /hls-relay/HOST/live/N/chunks.m3u8
    rx = re.compile(r"/hls-relay/(?:_fix/)?([^:/]+)/live/(\d+)/chunks\.m3u8")
    targets = []
    for i in items:
        if not i.get("is_live"):
            continue
        m = rx.search(i.get("video_url") or "")
        if m:
            targets.append((i.get("title", "").strip(), m.group(1), int(m.group(2))))

    if not targets:
        print("לא נמצאו ערוצים בשער ללא פורט. אין מה לבדוק.")
        return

    print(f"{len(targets)} ערוצים מצביעים לשער ללא פורט")
    print(f"בודק כל אחד מול {len(ALTS)} שערים חלופיים, {a.workers} במקביל\n")

    def one(row):
        title, host, n = row
        res = {"title": title, "host": host, "n": n}
        code, size = probe(f"https://{host}/live/{n}/chunks.m3u8")
        res["portless"] = f"{code}/{size}"
        res["portless_ok"] = code == 200 and size > 0
        for label, tmpl in ALTS:
            code, size = probe(tmpl.format(host=host, n=n))
            res[label] = f"{code}/{size}"
            res[label + "_ok"] = code == 200 and size > 0
        return res

    rows, done = [], 0
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for r in ex.map(one, targets):
            rows.append(r)
            done += 1
            print(f"\r  {done}/{len(targets)}".ljust(26), end="", flush=True)
    print("\n")

    hdr = f"{'ערוץ':<26}{'ללא פורט':>11}{'‎:86':>11}{':7070':>11}"
    print(hdr)
    print("-" * len(hdr))
    fixable86, fixable7070, dead, fine = [], [], [], []
    for r in rows:
        print(f"{r['title'][:25]:<26}{r['portless']:>11}"
              f"{r['‎:86 /live']:>11}{r[':7070 /p']:>11}")
        if r["portless_ok"]:
            fine.append(r)
        elif r["‎:86 /live_ok"]:
            fixable86.append(r)
        elif r[":7070 /p_ok"]:
            fixable7070.append(r)
        else:
            dead.append(r)

    print(f"\n{'='*58}")
    print(f"🟢 עובדים כמו שהם:           {len(fine)}")
    print(f"🔧 ייתקנו בהוספת :86:        {len(fixable86)}")
    print(f"🔧 ייתקנו במעבר ל-:7070:     {len(fixable7070)}")
    print(f"🔴 לא עונים באף שער:         {len(dead)}")
    print("=" * 58)

    if dead:
        print("\nלא נמצאו באף שער — כנראה מספר ערוץ שהספק שינה:")
        for r in dead[:15]:
            print(f"   {r['title'][:30]}  (ערוץ {r['n']})")

    if a.out:
        Path(a.out).write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        print(f"\nנשמר: {a.out}")
    if fixable86 or fixable7070:
        print(f"\nשלח לי את הפלט ואבנה תיקון ל-"
              f"{len(fixable86) + len(fixable7070)} הערוצים.")


if __name__ == "__main__":
    main()
