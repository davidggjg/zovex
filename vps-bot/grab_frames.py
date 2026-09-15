#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
grab_frames.py — מוציא פריים אחד מכל ערוץ כדי לזהות מה הוא.

כשהספק לא שולח service_name במטא-דאטה, אין דרך לדעת מה כל מספר מייצג
חוץ מלהסתכל. הסקריפט מושך תמונה בודדת מכל זרם ומרכיב מהן גיליון אחד,
כך שאפשר לזהות את כל הערוצים במבט אחד לפי הלוגו שעל המסך.

    python3 grab_frames.py --base 'https://HOST:PORT/live/{n}/chunks.m3u8' --nums 120,140,150,160
    python3 grab_frames.py --base '...' --from 100 --to 200
    python3 grab_frames.py --base '...' --nums 120,140 --dir /tmp/frames

בסוף נוצר גיליון אחד: /tmp/frames/sheet.jpg
שלח אותו ואפשר לזהות את הערוצים לפי הלוגואים.

קריאה בלבד: לא נוגע בקטלוג ולא מפעיל restart.
"""
import argparse, os, re, shutil, subprocess, sys, time
import concurrent.futures as cf
from pathlib import Path

UA = "VLC/3.0.20 LibVLC/3.0.20"


def grab(n: int, base: str, outdir: Path, seek: int, timeout: int):
    """פריים אחד מהערוץ. מדלג כמה שניות קדימה — הפריים הראשון
    בזרם חי הוא לעתים קרובות שחור או חלקי."""
    url = base.replace("{n}", str(n))
    out = outdir / f"ch_{n:04d}.jpg"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-user_agent", UA,
           "-i", url,
           "-ss", str(seek),            # אחרי הקלט: מדלג בתוך הזרם שנקלט
           "-frames:v", "1",
           "-vf", "scale=480:-2",
           "-q:v", "4", str(out)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return n, None, "timeout"
    except FileNotFoundError:
        sys.exit("ffmpeg לא מותקן")
    if out.exists() and out.stat().st_size > 2000:
        return n, out, None
    err = (r.stderr.strip().splitlines() or ["אין פלט"])[-1][:80]
    out.unlink(missing_ok=True)
    return n, None, err


def sheet(files, outdir: Path, cols: int):
    """מרכיב את כל הפריימים לתמונה אחת. דרך ffmpeg, כדי לא לדרוש
    ImageMagick או PIL שאולי אינם מותקנים בשרת."""
    if not files:
        return None
    tmp = outdir / "_seq"
    tmp.mkdir(exist_ok=True)
    for i, f in enumerate(files):
        shutil.copy2(f, tmp / f"s{i:03d}.jpg")
    rows = (len(files) + cols - 1) // cols
    out = outdir / "sheet.jpg"
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-framerate", "1", "-i", str(tmp / "s%03d.jpg"),
         "-frames:v", "1",
         "-filter_complex", f"tile={cols}x{rows}:padding=6:color=black",
         "-q:v", "3", str(out)],
        capture_output=True, text=True)
    shutil.rmtree(tmp, ignore_errors=True)
    if out.exists() and out.stat().st_size > 2000:
        return out
    print("⚠ הרכבת הגיליון נכשלה:", (r.stderr or "").strip()[-200:])
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="כתובת עם {n}")
    ap.add_argument("--nums", default="", help="מספרים מופרדים בפסיק")
    ap.add_argument("--from", dest="lo", type=int)
    ap.add_argument("--to", dest="hi", type=int)
    ap.add_argument("--dir", default="/tmp/frames")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seek", type=int, default=4, help="שניות לדלג לפני הפריים")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--cols", type=int, default=4)
    a = ap.parse_args()

    if "{n}" not in a.base:
        sys.exit("--base חייב להכיל {n}")
    if a.nums:
        nums = [int(x) for x in re.findall(r"\d+", a.nums)]
    elif a.lo is not None and a.hi is not None:
        nums = list(range(a.lo, a.hi + 1))
    else:
        sys.exit("צריך --nums או --from ו---to")

    outdir = Path(a.dir)
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"מושך פריים מ-{len(nums)} ערוצים ל-{outdir}\n")

    got, failed = [], []
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(grab, n, a.base, outdir, a.seek, a.timeout) for n in nums]
        for done, f in enumerate(cf.as_completed(futs), 1):
            n, path, err = f.result()
            if path:
                got.append((n, path))
                print(f"  ✓ {n}   ({done}/{len(nums)})", flush=True)
            else:
                failed.append((n, err))
                print(f"  ✗ {n}   ({done}/{len(nums)})", flush=True)
    print()

    got.sort()
    print(f"הצליחו: {len(got)} · נכשלו: {len(failed)}")
    if failed:
        for n, err in failed[:10]:
            print(f"   ✗ {n}: {err}")

    if got:
        s = sheet([p for _, p in got], outdir, a.cols)
        print()
        print("סדר הערוצים בגיליון, שמאל לימין ואז שורה הבאה:")
        for i in range(0, len(got), a.cols):
            print("   " + "  ".join(str(n) for n, _ in got[i:i + a.cols]))
        if s:
            print(f"\nהגיליון: {s}")
            print("שלח אותו ואפשר לזהות כל ערוץ לפי הלוגו.")
        print(f"תמונות בודדות: {outdir}/ch_<מספר>.jpg")


if __name__ == "__main__":
    main()
