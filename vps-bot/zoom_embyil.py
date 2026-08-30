#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
סבב שני לערוצים שהלוגו בהם לא נקרא.

למה הסבב הראשון לא הספיק: הפריים הוקטן ל-384 פיקסלים רוחב, והלוגו של הערוץ
- שתופס פינה קטנה - נמרח לכמה פיקסלים. בנוסף נתפס פריים אחד בלבד, ואם באותו
רגע רצה פרסומת או שהלוגו היה מוסתר, אין מה לזהות.

שני תיקונים:
  · חותכים רק את הרצועה העליונה (שם יושב הלוגו כמעט תמיד, בשני הצדדים)
    ומגדילים אותה. אותו לוגו מקבל פי חמישה יותר פיקסלים.
  · תופסים ארבע נקודות זמן לאורך כ-70 שניות במקום אחת. מספיק שבאחת מהן
    הלוגו מופיע.

    python3 zoom_embyil.py                    # רשימת הלא-ודאיים המובנית
    python3 zoom_embyil.py A131 B210 B220     # ערוצים מסוימים
    python3 zoom_embyil.py --jobs 8
"""
import argparse, concurrent.futures as cf, json, pathlib, shutil, subprocess, sys

DATA = pathlib.Path("/opt/zovex-bot/data")
OUT = DATA / "scanshots2"
UA = ("Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
FONT = next((f for f in FONTS if pathlib.Path(f).exists()), None)
LABEL_OK = False

# הערוצים שנשארו בלי זיהוי ודאי בסבב הראשון
UNSURE = ["A115", "A117", "A119", "A128", "A129", "A131", "A132", "A135",
          "A149", "A155", "A156", "A157", "A161", "A167",
          "B120", "B160", "B210", "B220", "B230", "B240", "B270", "B300",
          "B340", "B350", "B500", "B692", "B693", "B760", "B770", "B800"]


def url_for(tag):
    n = tag[1:]
    if tag[0].upper() == "A":
        return f"https://tv.embyil.tv:7070/p/embyil/s/{n}/playlist.m3u8"
    return f"https://tv.embyil.tv:86/live/{n}/chunks.m3u8"


def has_drawtext():
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                           capture_output=True, text=True, timeout=20)
        return " drawtext " in (r.stdout or "")
    except Exception:
        return False


def grab(tag):
    """רצועה עליונה מוגדלת, ארבע נקודות זמן, מוערמות זו על זו."""
    dst = OUT / f"{tag}.jpg"
    label = (f",drawtext=fontfile={FONT}:text='{tag}':x=10:y=8:fontsize=34:"
             f"fontcolor=yellow:box=1:boxcolor=black@0.75:boxborderw=7") if LABEL_OK else ""
    # crop: כל הרוחב, החמישית העליונה — הלוגו יושב שם בשני הצדדים.
    # tile דורש בדיוק כמה שביקשנו; ערוץ שמתחיל לאט לא ייתן 4 פריימים
    # ואז לא ייצא כלום. לכן ניסיון שני קצר יותר עם שתי נקודות זמן.
    attempts = [("74", "1/18", 4), ("40", "1/12", 2)]
    ok = False
    for secs, rate, cnt in attempts:
        vf = f"fps={rate},crop=iw:ih*0.20:0:0,scale=1100:-2,tile=1x{cnt}{label}"
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-user_agent", UA, "-t", secs, "-i", url_for(tag),
               "-vf", vf, "-frames:v", "1", "-q:v", "2", str(dst)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=int(secs) + 80)
        except subprocess.TimeoutExpired:
            pass
        if dst.exists() and dst.stat().st_size > 3000:
            ok = True
            break
    if not ok and dst.exists():
        dst.unlink()
    print(f"  {'✓' if ok else '✗'} {tag}", flush=True)
    return tag, ok


def main():
    global LABEL_OK
    ap = argparse.ArgumentParser()
    ap.add_argument("tags", nargs="*")
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg לא מותקן")
    LABEL_OK = bool(FONT) and has_drawtext()
    if not LABEL_OK:
        print("⚠️  בלי drawtext — הרצועות ייווצרו בלי מספר צרוב")

    tags = [t.upper() for t in a.tags] or UNSURE
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    print(f"תופסת רצועה עליונה מ-{len(tags)} ערוצים, 4 נקודות זמן כל אחד "
          f"({a.jobs} במקביל). זה לוקח כדקה לערוץ.\n")
    with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        res = list(ex.map(grab, tags))

    ok = [t for t, good in res if good]
    bad = [t for t, good in res if not good]
    print(f"\nהצליחו: {len(ok)}   נכשלו: {len(bad)}")
    if bad:
        print("בלי תמונה: " + ", ".join(bad))

    # שתי רצועות לגיליון — כל רצועה כבר גבוהה, יותר מזה נהיה בלתי קריא
    files = sorted(OUT.glob("*.jpg"))
    n = 0
    for i in range(0, len(files), 2):
        n += 1
        batch = files[i:i + 2]
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
        for f in batch:
            cmd += ["-i", str(f)]
        st = "".join(f"[{k}:v]scale=1100:-2,setsar=1[v{k}];" for k in range(len(batch)))
        ins = "".join(f"[v{k}]" for k in range(len(batch)))
        if len(batch) == 2:
            fc = f"{st}{ins}hstack=inputs=2[o]"
        else:
            fc = f"{st}[v0]null[o]"
        cmd += ["-filter_complex", fc, "-map", "[o]", "-q:v", "3",
                str(OUT / f"zoom_{n:02d}.jpg")]
        r = subprocess.run(cmd, capture_output=True)
        print(f"{'📄' if not r.returncode else '⚠️'} zoom_{n:02d}.jpg  "
              f"({', '.join(f.stem for f in batch)})")

    print(f"\nהכל ב-{OUT}")
    print("העתק ל-/opt/zovex-bot/data/epg/ כמו קודם ואמשוך.")


if __name__ == "__main__":
    main()
