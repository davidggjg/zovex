#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
subburn_bench.py — עונה על שאלה אחת: האם צריבת כתוביות על השרת הזה
תחנוק את הסטרימינג, וכמה זמן היא תיקח לסרט מלא.

צריבת כתוביות (-vf subtitles) מחייבת קידוד מחדש של כל הווידאו. אין
דרך לעקוף את זה: הכתובית נצרבת לתוך הפיקסלים, ולכן -c copy בלתי אפשרי.
זה ההבדל בין הבוט הזה לכל שאר מה שהשרת עושה היום.

הסקריפט מייצר קליפ בדיקה קצר, צורב עליו כתוביות בדיוק באותה פקודה
שהבוט משתמש בה, ובמקביל **מודד את זמן התגובה של zovex-bot** — כדי
לראות בפועל אם הצפייה נפגעת, במקום לנחש.

    python3 subburn_bench.py                 # 60 שניות בדיקה, חצי מהליבות
    python3 subburn_bench.py --threads 2
    python3 subburn_bench.py --seconds 30    # קצר יותר, פחות הפרעה

בטיחות: הקליפ קצר, ה-ffmpeg רץ ב-nice 10, והכול נמחק בסוף.
עדיין — זה כן מעמיס מעבד לזמן קצר. אם יש עכשיו הרבה צופים, המתן.
"""
import argparse, os, shutil, statistics, subprocess, sys, tempfile, threading, time
from pathlib import Path
from urllib.request import urlopen

PORT = int(os.environ.get("PORT", "8000"))
PROBE = f"http://127.0.0.1:{PORT}/debug/tasks"


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def specs() -> dict:
    d = {}
    d["cores"] = os.cpu_count() or 1
    try:
        for ln in Path("/proc/meminfo").read_text().splitlines():
            if ln.startswith("MemTotal:"):
                d["ram_gb"] = round(int(ln.split()[1]) / 1024 / 1024, 1)
            if ln.startswith("MemAvailable:"):
                d["ram_free_gb"] = round(int(ln.split()[1]) / 1024 / 1024, 1)
    except Exception:
        d["ram_gb"] = d["ram_free_gb"] = 0
    try:
        st = os.statvfs("/")
        d["disk_free_gb"] = round(st.f_bavail * st.f_frsize / 1024**3, 1)
    except Exception:
        d["disk_free_gb"] = 0
    try:
        d["load1"] = float(Path("/proc/loadavg").read_text().split()[0])
    except Exception:
        d["load1"] = 0.0
    return d


def probe_once(timeout=5.0):
    """זמן תגובה של השירות. זה המדד שאומר אם הצופים נפגעים."""
    t0 = time.time()
    try:
        with urlopen(PROBE, timeout=timeout) as r:
            r.read()
        return (time.time() - t0) * 1000
    except Exception:
        return None


class Prober(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.samples, self.fails, self.stop = [], 0, False

    def run(self):
        while not self.stop:
            ms = probe_once()
            if ms is None:
                self.fails += 1
            else:
                self.samples.append(ms)
            time.sleep(0.5)

    def report(self):
        if not self.samples:
            return None
        s = sorted(self.samples)
        return {
            "n": len(s), "fails": self.fails,
            "median": statistics.median(s),
            "p95": s[int(len(s) * 0.95) - 1] if len(s) >= 20 else max(s),
            "max": max(s),
        }


def make_clip(d: Path, seconds: int) -> tuple:
    """קליפ 1080p סינתטי + קובץ כתוביות. מייצג סרט טיפוסי."""
    src = d / "src.mp4"
    srt = d / "s.srt"
    r = sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate=25:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)])
    if r.returncode != 0 or not src.exists():
        sys.exit(f"יצירת קליפ הבדיקה נכשלה:\n{r.stderr[-500:]}")
    blocks = []
    for i in range(seconds // 3):
        a, b = i * 3, i * 3 + 2
        blocks.append(f"{i+1}\n00:00:{a:02d},000 --> 00:00:{b:02d},500\n"
                      f"שורת כתובית לבדיקה מספר {i+1}\n")
    srt.write_text("\n".join(blocks), encoding="utf-8")
    return src, srt


def burn(src: Path, srt: Path, out: Path, threads: int, preset: str) -> tuple:
    """בדיוק הפקודה של הבוט: nice, libx264, crf 24, faststart."""
    esc = str(srt).replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'")
    nice = ["nice", "-n", "10"] if shutil.which("nice") else []
    cmd = nice + [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src),
        "-vf", f"subtitles='{esc}':force_style='FontSize=24,Alignment=2'",
        "-c:v", "libx264", "-preset", preset, "-crf", "24",
        "-pix_fmt", "yuv420p", "-threads", str(threads),
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        "-max_muxing_queue_size", "1024", str(out),
    ]
    t0 = time.time()
    r = sh(cmd)
    return time.time() - t0, r


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--threads", type=int, default=0, help="0 = חצי מהליבות")
    ap.add_argument("--preset", default="faster")
    a = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg לא מותקן.")

    sp = specs()
    threads = a.threads if a.threads > 0 else max(1, sp["cores"] // 2)

    print("=" * 68)
    print(f"ליבות: {sp['cores']} · RAM: {sp['ram_free_gb']}/{sp['ram_gb']}GB פנוי · "
          f"דיסק: {sp['disk_free_gb']}GB פנוי · load: {sp['load1']}")
    print(f"בדיקה: {a.seconds}ש · threads={threads} · preset={a.preset} · nice 10")
    print("=" * 68)

    base = [probe_once() for _ in range(10)]
    base = [x for x in base if x is not None]
    if not base:
        print("⚠ אין תגובה מ-zovex-bot ב-localhost. ממשיך בלי מדידת השפעה.\n")
        base_med = None
    else:
        base_med = statistics.median(base)
        print(f"\nזמן תגובה לפני העומס: חציון {base_med:.0f}ms\n")

    d = Path(tempfile.mkdtemp(prefix="subburn_"))
    try:
        print("מייצר קליפ בדיקה...")
        src, srt = make_clip(d, a.seconds)
        src_mb = src.stat().st_size / 1024**2
        print(f"קליפ מוכן: {src_mb:.1f}MB\n")

        print("צורב כתוביות — מודד במקביל את זמן התגובה של השירות...")
        pr = Prober()
        pr.start()
        elapsed, r = burn(src, srt, d / "out.mp4", threads, a.preset)
        pr.stop = True
        pr.join(timeout=3)

        if r.returncode != 0:
            print(f"\n✗ ffmpeg נכשל:\n{r.stderr[-800:]}")
            return

        ratio = elapsed / a.seconds
        out_mb = (d / "out.mp4").stat().st_size / 1024**2

        print(f"\n{'='*68}")
        print(f"צריבה של {a.seconds}ש לקחה {elapsed:.1f}ש  →  "
              f"יחס {ratio:.2f}× זמן אמת")
        print(f"פלט: {out_mb:.1f}MB (מקור {src_mb:.1f}MB)")
        print("=" * 68)

        print("\nהערכה לסרט מלא (באותו עומס, קליפ 1080p):")
        for label, mins in (("סרט 90 דקות", 90), ("סרט שעתיים", 120),
                            ("פרק 45 דקות", 45)):
            est = mins * 60 * ratio / 60
            h, m = divmod(int(est), 60)
            print(f"   {label:<16} ≈ {h}ש {m:02d}דק' קידוד")

        rep = pr.report()
        print(f"\n{'='*68}\nהשפעה על הסטרימינג\n{'='*68}")
        if rep is None:
            print("לא נאספו דגימות.")
        else:
            print(f"דגימות: {rep['n']} · כשלים: {rep['fails']}")
            print(f"חציון בזמן העומס: {rep['median']:.0f}ms · "
                  f"p95: {rep['p95']:.0f}ms · שיא: {rep['max']:.0f}ms")
            if base_med:
                x = rep["median"] / base_med if base_med > 0 else 0
                print(f"לפני העומס: {base_med:.0f}ms  →  פי {x:.1f}")
                print()
                if rep["fails"] > 0 or rep["max"] > 2000:
                    print("🔴 השירות נחנק. אסור להריץ צריבה בזמן שיש צופים.")
                elif x > 3 or rep["p95"] > 500:
                    print("🟠 יש האטה מורגשת. רק בשעות שקטות, ועם CPUQuota.")
                else:
                    print("🟢 השירות נשאר מהיר תחת העומס הזה.")
                    print("   שים לב: זו ליבה אחת או שתיים. עם threads=0")
                    print("   (ברירת המחדל של הבוט) התמונה תהיה גרועה בהרבה.")

        print(f"\n{'='*68}\nדיסק\n{'='*68}")
        print(f"עבודה אחת על סרט 2GB דורשת ~5GB פנויים בו-זמנית")
        print(f"(מקור + פלט + אודיו + חלקים). פנוי כרגע: {sp['disk_free_gb']}GB")
        if sp["disk_free_gb"] < 10:
            print("🔴 אין מספיק מקום. עבודה אחת תמלא את הדיסק.")
        elif sp["disk_free_gb"] < 25:
            print("🟠 גבולי. חייב בדיקת מקום פנוי לפני כל עבודה.")
        else:
            print("🟢 מספיק מקום לעבודה אחת בכל רגע.")
    finally:
        shutil.rmtree(d, ignore_errors=True)
        print(f"\nקבצי הבדיקה נמחקו.")


if __name__ == "__main__":
    main()
