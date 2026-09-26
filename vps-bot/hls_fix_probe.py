#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hls_fix_probe.py — למה ערוץ חי מחזיר 502 במסלול /hls-relay/_fix/.

הרקע, במדידה ולא בהשערה:
  • 105 ערוצי שידור חי. המסלול הרגיל /hls-relay/<host>/<path> מחזיר 200 ב-31
    מתוך 32 הערוצים שמשתמשים בו. כל הכשלים מרוכזים במסלול השני, _fix.
  • אותם ערוצים בדיוק, כשמסירים מהכתובת רק את "_fix/", מחזירים 200:
        yes-drama   _fix=502  רגיל=200
        discovery   _fix=502  רגיל=200
        sport-1     _fix=502  רגיל=200
        nick-jr     _fix=502  רגיל=200
    כלומר המקור אצל הספק תקין, והבעיה אצלנו בהמרה.
  • ה-502 חוזר תוך כשתי שניות. זה מוקדם מכדי להיות עומס או timeout —
    ffmpeg מת מיד.
  • ולמה זה לא מופיע ביומן: ב-_hls_fix_start התהליך מופעל עם
    stderr=asyncio.subprocess.DEVNULL, כלומר **שגיאת ffmpeg נזרקת לפח**.
    אין מה לקרוא ביומן כי מעולם לא נכתב שם דבר.

הסקריפט הזה מריץ את אותה שרשרת בדיוק — אותה כתובת מקור, אותם דגלים —
אבל עם stderr גלוי, ומדפיס את מה ש-ffmpeg באמת אומר.

הוא **קורא בלבד**: לא נוגע ב-main.py, לא בשירות ולא בקבצים של הערוצים
הפעילים. הוא כותב לתיקייה זמנית משלו ומוחק אותה בסוף.

חייב לרוץ מהשרת: המקור הוא http://127.0.0.1:<PORT>, והמארחים של הספק
אינם נגישים מבחוץ.

    python3 hls_fix_probe.py yes-drama
    python3 hls_fix_probe.py yes-drama discovery sport-1
    python3 hls_fix_probe.py --all-failing
    python3 hls_fix_probe.py yes-drama --seconds 25
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path
from urllib.parse import urlparse

DATA = Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
PORT = int(os.environ.get("PORT", 8000))
UA = ("Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")


def live_channels() -> dict:
    """{slug: כתובת} לערוצי השידור החי מהקטלוג שעל השרת."""
    if not CONTENT.exists():
        sys.exit(f"לא נמצא {CONTENT} — הרץ מהשרת.")
    out = {}
    for it in json.loads(CONTENT.read_text(encoding="utf-8")):
        if it.get("is_live"):
            slug = (it.get("custom_slug") or "").strip() or str(it.get("id"))
            out[slug] = (it.get("video_url") or "").strip()
    return out


def split_fix(url: str):
    """מחלץ (host, path) מכתובת _fix, בדיוק כמו שהמסלול ב-main.py מקבל אותם."""
    p = urlparse(url)
    m = re.match(r"^/hls-relay/_fix/([^/]+)/(.+)$", p.path)
    if not m:
        return None
    return m.group(1), m.group(2)


def redact(s: str) -> str:
    """מסתיר את המארח של הספק ואת האסימון שבנתיב.

    הפלט של הסקריפט נועד להישלח אליי, ו-stderr של ffmpeg מכיל את כתובת
    המקור המלאה — כולל שם המארח של הספק ואת מחרוזת ההרשאה שבתוך הנתיב.
    שני אלה אסורים בהעתקה החוצה, ולכן הם ממוסכים כאן ולא בזיכרון של מי
    שמדביק. אין בזה פגיעה באבחון: מה שחשוב הוא *מה* ffmpeg אמר, לא לאיזו
    כתובת.
    """
    # הסדר חשוב: המארח של הספק אינו הסמכות של הכתובת אלא **מקטע בנתיב**
    # אחרי /hls-relay/ — הסמכות היא 127.0.0.1. מיסוך הסמכות בלבד היה
    # משאיר את שם המארח חשוף, וזו בדיוק הטעות שנתפסה בבדיקה.
    s = re.sub(r"(/hls-relay/)(_fix/)?[^/\s\"']+", r"\1\2<ספק>", s)
    s = re.sub(r"https?://[^/\s\"']+", "http://<מקומי>", s)
    s = re.sub(r"\b[A-Z0-9]{8,}\b", "<אסימון>", s)
    s = re.sub(r"\b[0-9a-f]{16,}\b", "<אסימון>", s)
    # מארח שהופיע בלי /hls-relay/ לפניו (למשל בשורת שגיאה של DNS)
    s = re.sub(r"\b(?:[a-z0-9-]+\.){2,}[a-z]{2,}\b", "<ספק>", s)
    return s


def say(*parts):
    print(redact(" ".join(str(p) for p in parts)))


def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"(חרג מ-{timeout} שניות)"
    except FileNotFoundError:
        return -2, "", f"({cmd[0]} לא מותקן)"


def probe(slug: str, url: str, seconds: int) -> str:
    print(f"\n{'═' * 66}\n{slug}\n{'═' * 66}")
    parts = split_fix(url)
    if not parts:
        print("  הכתובת אינה במסלול _fix — אין מה לבדוק כאן.")
        return "לא _fix"
    host, path = parts
    src = f"http://127.0.0.1:{PORT}/hls-relay/{host}/{path}"

    # ── 1 · האם המקור שממנו ffmpeg אמור לקרוא בכלל עונה ──────────────────
    # זו בדיוק הכתובת ש-_hls_fix_start בונה, כולל הפנייה ל-127.0.0.1 ולא
    # דרך nginx. אם היא נופלת — הבעיה לפני ffmpeg.
    code, out, _ = run(["curl", "-s", "-o", "/tmp/.hlsprobe.m3u8", "-m", "20",
                        "-w", "%{http_code} %{size_download}", src])
    print(f"  1 · המקור הפנימי: HTTP {out or '—'}")
    body = ""
    try:
        body = Path("/tmp/.hlsprobe.m3u8").read_text(errors="replace")[:400]
    except Exception:
        pass
    if not out.startswith("200"):
        say(f"      ✗ ffmpeg לא יכול לקרוא מכאן. גוף התשובה:\n      {body[:200]}")
        return "המקור הפנימי נפל"
    first = [l for l in body.splitlines() if l.strip()][:4]
    say("      " + " | ".join(first))
    variant = "#EXT-X-STREAM-INF" in body

    # ── 2 · מה ffprobe רואה ───────────────────────────────────────────────
    rc, out, err = run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name", "-of",
                        "default=nw=1:nk=0", "-user_agent", UA, src], timeout=40)
    if rc == 0 and out.strip():
        say("  2 · ffprobe: " + " · ".join(out.split()))
    else:
        say(f"  2 · ffprobe נכשל (rc={rc}): {(err or '').strip()[:220]}")

    # ── 3 · אותו ffmpeg בדיוק, רק ש-stderr לא נזרק ───────────────────────
    outdir = Path(tempfile.mkdtemp(prefix="hlsprobe-"))
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error",
            "-reconnect", "1", "-reconnect_streamed", "1",
            "-reconnect_on_network_error", "1",
            "-reconnect_on_http_error", "5xx", "-reconnect_delay_max", "10",
            "-fflags", "+genpts", "-i", src,
            "-c:v", "copy", "-c:a", "copy",
            "-f", "hls", "-hls_time", "4", "-hls_list_size", "6",
            "-hls_flags", "delete_segments+independent_segments+omit_endlist",
            "-hls_segment_type", "fmp4", "-hls_fmp4_init_filename", "init.mp4",
            "-hls_segment_filename", str(outdir / "s%d.m4s"),
            str(outdir / "index.m3u8")]
    print(f"  3 · מריץ ffmpeg עד {seconds} שניות…")
    t0 = time.time()
    verdict = "?"
    try:
        p = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE, text=True)
        idx = outdir / "index.m3u8"
        while time.time() - t0 < seconds:
            if idx.exists() and idx.read_text(errors="ignore").count(".m4s") >= 1:
                print(f"      ✓ סגמנט ראשון אחרי {time.time()-t0:.1f} שניות — "
                      "הערוץ הזה **כן** עובד עכשיו")
                verdict = "עבד"
                p.kill()
                break
            if p.poll() is not None:
                err = (p.stderr.read() or "").strip()
                print(f"      ✗ ffmpeg מת אחרי {time.time()-t0:.1f} שניות, "
                      f"קוד {p.returncode}")
                print("      — מה ש-main.py זורק לפח: —")
                for line in (err.splitlines() or ["(שתק לגמרי)"])[-12:]:
                    say(f"        {line[:200]}")
                verdict = f"ffmpeg מת (קוד {p.returncode})"
                break
            time.sleep(0.2)
        else:
            p.kill()
            err = (p.stderr.read() or "").strip()
            print(f"      ✗ {seconds} שניות ואין סגמנט. ffmpeg עדיין חי.")
            if err:
                print("      — stderr: —")
                for line in err.splitlines()[-12:]:
                    say(f"        {line[:200]}")
            verdict = "לא ייצר סגמנט"
    finally:
        shutil.rmtree(outdir, ignore_errors=True)

    if variant and verdict != "עבד":
        print("      הערה: המקור הוא playlist של גרסאות (EXT-X-STREAM-INF).")
        print("      ffmpeg אמור לבחור גרסה לבד, אבל הכתובות שבתוכו יחסיות")
        print("      ומצביעות בחזרה אל הריליי — כדאי לבדוק שהן נפתחות.")
    return verdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--all-failing", action="store_true",
                    help="כל ערוצי _fix שמחזירים עכשיו שגיאה")
    ap.add_argument("--seconds", type=int, default=20)
    a = ap.parse_args()

    ch = live_channels()
    if a.all_failing:
        targets = []
        for slug, url in sorted(ch.items()):
            if not split_fix(url):
                continue
            rc, out, _ = run(["curl", "-s", "-o", "/dev/null", "-m", "20",
                              "-w", "%{http_code}", url], timeout=25)
            if out.strip() != "200":
                targets.append(slug)
            time.sleep(1)   # אחד-אחד: כל בקשה מפעילה ffmpeg משלה בשרת
        print(f"\n{len(targets)} ערוצי _fix נכשלים כרגע: {', '.join(targets)}")
    else:
        targets = a.slugs
    if not targets:
        ap.print_help()
        return

    results = {}
    for slug in targets:
        url = ch.get(slug)
        if not url:
            print(f"\n{slug}: אין בקטלוג")
            continue
        results[slug] = probe(slug, url, a.seconds)
        time.sleep(2)

    if results:
        print(f"\n{'═' * 66}\nסיכום\n{'═' * 66}")
        for slug, v in results.items():
            print(f"  {slug:<22} {v}")
        print("\nשלח לי את הפלט הזה — שורות ה-stderr הן מה שחסר כדי לתקן.")


if __name__ == "__main__":
    main()
