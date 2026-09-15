#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hunt_channels.py — סורק כמה פורמטים של הספק, מושך פריים מכל ערוץ
שנמצא, ומפרסם גיליונות מוכנים לצפייה. פקודה אחת מתחילה עד סוף.

למה פורמטים ורבים: לספק כמה שערים במקביל, לכל אחד מספור משלו, וערוץ
יכול להתקיים באחד ולא בשני. הסורק מריץ את כולם ומסמן מאיפה כל ממצא.

    python3 hunt_channels.py --from 1 --to 600
    python3 hunt_channels.py --from 1 --to 600 --formats fmt.txt
    python3 hunt_channels.py --from 1 --to 300 --skip-known

ברירת המחדל לפורמטים נלקחת מ--formats, קובץ טקסט עם תבנית בכל שורה
ו-{n} במקום המספר. בלעדיו צריך --format (אפשר לחזור על הדגל).

בסוף מודפסות כתובות לגיליונות — פתח בדפדפן, צלם, ושלח לזיהוי.

קריאה בלבד מבחינת הקטלוג: לא נוגע ב-content.json ולא מפעיל restart.
הקבצים היחידים שנכתבים הם התמונות ותיקיית העבודה.
"""
import argparse, json, os, re, secrets, shutil, subprocess, sys, threading, time
import concurrent.futures as cf
from pathlib import Path
from urllib.request import Request, urlopen

DATA = Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
SITE = Path(os.environ.get("ZOVEX_SITE", "/opt/zovex-site"))
SITE_URL = os.environ.get("ZOVEX_URL", "https://zovex.duckdns.org")
UA = "VLC/3.0.20 LibVLC/3.0.20"
_gate = threading.Semaphore(4)


def alive(url: str, timeout=10):
    with _gate:
        time.sleep(0.15)
        try:
            with urlopen(Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
                head = r.read(4096).decode("utf-8", "ignore")
                return r.status == 200 and "#EXTM3U" in head
        except Exception:
            return False


def grab(url: str, out: Path, seek: int, timeout: int) -> bool:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-user_agent", UA, "-i", url, "-ss", str(seek),
           "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", str(out)]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        pass
    if out.exists() and out.stat().st_size > 2000:
        return True
    out.unlink(missing_ok=True)
    return False


def known_urls() -> set:
    """מה שכבר בקטלוג — כדי לא לבזבז זמן על ערוצים שיש לך."""
    out = set()
    if not CONTENT.exists():
        return out
    try:
        for i in json.loads(CONTENT.read_text(encoding="utf-8")):
            u = i.get("video_url") or ""
            m = re.search(r"/hls-relay/(?:_fix/)?(.+)$", u)
            if m:
                out.add(m.group(1).rstrip("/"))
    except Exception:
        pass
    return out


def sheet(files, dest: Path, cols: int) -> bool:
    tmp = dest.parent / f"_seq_{secrets.token_hex(3)}"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        for i, f in enumerate(files):
            shutil.copy2(f, tmp / f"s{i:03d}.jpg")
        rows = (len(files) + cols - 1) // cols
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-framerate", "1", "-i", str(tmp / "s%03d.jpg"), "-frames:v", "1",
             "-filter_complex", f"tile={cols}x{rows}:padding=6:color=black",
             "-q:v", "3", str(dest)],
            capture_output=True, timeout=120)
    except Exception:
        pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return dest.exists() and dest.stat().st_size > 2000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", action="append", default=[],
                    help="תבנית עם {n}. אפשר לחזור על הדגל")
    ap.add_argument("--formats", default="", help="קובץ עם תבנית בכל שורה")
    ap.add_argument("--from", dest="lo", type=int, default=1)
    ap.add_argument("--to", dest="hi", type=int, default=600)
    ap.add_argument("--dir", default="/tmp/hunt")
    ap.add_argument("--per-sheet", type=int, default=12)
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--seek", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=50)
    ap.add_argument("--skip-known", action="store_true",
                    help="דלג על ערוצים שכבר בקטלוג")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()

    fmts = list(a.format)
    if a.formats:
        fmts += [l.strip() for l in Path(a.formats).read_text().splitlines()
                 if l.strip() and not l.startswith("#")]
    fmts = [f for f in fmts if "{n}" in f]
    if not fmts:
        sys.exit("צריך לפחות תבנית אחת עם {n} — דרך --format או --formats")
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg לא מותקן")

    outdir = Path(a.dir)
    shutil.rmtree(outdir, ignore_errors=True)
    outdir.mkdir(parents=True, exist_ok=True)
    known = known_urls() if a.skip_known else set()

    nums = list(range(a.lo, a.hi + 1))
    print(f"{len(fmts)} פורמטים × {len(nums)} מספרים = "
          f"{len(fmts)*len(nums):,} בדיקות")
    if known:
        print(f"מדלג על {len(known)} ערוצים שכבר בקטלוג")
    print()

    # ── שלב 1: מי עונה ────────────────────────────────────────────────
    hits = []
    for fi, fmt in enumerate(fmts, 1):
        label = re.sub(r"https?://", "", fmt).replace("{n}", "N")[:52]
        print(f"[{fi}/{len(fmts)}] {label}")
        found, done = [], 0
        with cf.ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(alive, fmt.replace("{n}", str(n))): n for n in nums}
            for f in cf.as_completed(futs):
                done += 1
                if f.result():
                    found.append(futs[f])
                if done % 25 == 0 or done == len(nums):
                    print(f"\r    {done}/{len(nums)} · נמצאו {len(found)}".ljust(44),
                          end="", flush=True)
        found.sort()
        print()
        for n in found:
            url = fmt.replace("{n}", str(n))
            key = re.sub(r"^https?://", "", url).rstrip("/")
            if key in known:
                continue
            hits.append({"n": n, "fmt": fi, "url": url, "label": label})
        print(f"    → {len(found)} עונים, "
              f"{len([h for h in hits if h['fmt']==fi])} חדשים\n")

    if not hits:
        sys.exit("לא נמצא שום ערוץ חדש.")

    # ── שלב 2: פריים מכל אחד ──────────────────────────────────────────
    print(f"מושך פריים מ-{len(hits)} ערוצים...")
    ok = []
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        futs = {}
        for h in hits:
            p = outdir / f"f{h['fmt']}_{h['n']:04d}.jpg"
            futs[ex.submit(grab, h["url"], p, a.seek, a.timeout)] = (h, p)
        for done, f in enumerate(cf.as_completed(futs), 1):
            h, p = futs[f]
            if f.result():
                ok.append((h, p))
            print(f"\r  {done}/{len(hits)} · תמונות {len(ok)}".ljust(40),
                  end="", flush=True)
    print("\n")
    if not ok:
        sys.exit("לא הצלחתי למשוך אף פריים.")

    ok.sort(key=lambda x: (x[0]["fmt"], x[0]["n"]))

    # ── שלב 3: גיליונות ───────────────────────────────────────────────
    print("=" * 66)
    urls = []
    for i in range(0, len(ok), a.per_sheet):
        batch = ok[i:i + a.per_sheet]
        idx = i // a.per_sheet + 1
        dest = outdir / f"sheet{idx}.jpg"
        if not sheet([p for _, p in batch], dest, a.cols):
            print(f"⚠ גיליון {idx} נכשל")
            continue
        print(f"\nגיליון {idx} — סדר שמאל לימין, שורה אחרי שורה:")
        for r in range(0, len(batch), a.cols):
            row = batch[r:r + a.cols]
            print("   " + "   ".join(f"[{h['fmt']}] {h['n']}" for h, _ in row))
        if not a.no_publish and SITE.is_dir():
            name = f"hunt-{secrets.token_hex(5)}.jpg"
            try:
                shutil.copy2(dest, SITE / name)
                urls.append(f"{SITE_URL}/{name}")
            except Exception as e:
                print(f"   ⚠ פרסום נכשל: {e}")

    print("\n" + "=" * 66)
    print("מקרא הפורמטים:")
    for fi, fmt in enumerate(fmts, 1):
        print(f"   [{fi}] {fmt}")
    if urls:
        print("\nפתח בדפדפן, צלם ושלח לזיהוי:")
        for u in urls:
            print(f"   {u}")
        print("\nלניקוי אחר כך:  rm -f /opt/zovex-site/hunt-*.jpg")
    else:
        print(f"\nהגיליונות: {outdir}/sheet*.jpg")
    print(f"תמונות בודדות: {outdir}/f<פורמט>_<מספר>.jpg")


if __name__ == "__main__":
    main()
