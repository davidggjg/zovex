#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מזהה מה כל ערוץ שנמצא בסריקה, על ידי תפיסת פריים מהשידור עצמו.

הסורק מחזיר מספרים בלבד. השם האמיתי של הערוץ כתוב על המסך — לוגו בפינה,
באנר, שם התוכנית — ולכן פריים אחד מכל ערוץ מספיק כדי לזהות אותו. זו בדיוק
השיטה שבה זוהו Freetv6 ו-HOT DRAMA קודם.

הפריימים מוצמדים לגיליונות של 20, כי גיליון אחד שאפשר להסתכל עליו שווה
יותר מ-92 קבצים נפרדים. מספר הערוץ נצרב על כל תמונה כדי שאפשר יהיה לחזור
ממנה לכתובת.

    python3 identify_embyil.py              # כל החדשים
    python3 identify_embyil.py --all        # גם אלה שכבר באתר
    python3 identify_embyil.py --jobs 8     # מהיר יותר

הפלט: data/scanshots/sheet_NN.jpg  —  שלח לי אותם ואחזיר רשימת שמות.
"""
import argparse, concurrent.futures as cf, json, pathlib, shutil, subprocess, sys

DATA = pathlib.Path("/opt/zovex-bot/data")
SCAN = DATA / "embyil_scan.json"
OUT = DATA / "scanshots"
UA = ("Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
FONT = next((f for f in FONTS if pathlib.Path(f).exists()), None)
LABEL_OK = False          # נקבע בזמן ריצה, אחרי בדיקה שהפילטר קיים


def has_drawtext():
    """לא כל בניית ffmpeg כוללת drawtext (הוא דורש freetype). בלי הבדיקה הזאת
    כל תפיסת פריים הייתה נכשלת בשקט ולא היינו מקבלים ולו תמונה אחת."""
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                             capture_output=True, text=True, timeout=20)
        return " drawtext " in (out.stdout or "")
    except Exception:
        return False


def grab(ch):
    """פריים אחד מהערוץ. מדלג על ההתחלה כי השנייה הראשונה לרוב שחורה."""
    tag = f"{ch['pattern'].upper()}{ch['id']}"
    dst = OUT / f"{tag}.jpg"
    label = (f",drawtext=fontfile={FONT}:text='{tag}':x=8:y=8:fontsize=26:"
             f"fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=6") if LABEL_OK else ""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-user_agent", UA, "-timeout", "12000000",
           "-i", ch["url"], "-ss", "2", "-frames:v", "1",
           "-vf", f"scale=384:-2{label}", "-q:v", "4", str(dst)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=45)
    except subprocess.TimeoutExpired:
        pass
    ok = dst.exists() and dst.stat().st_size > 2000
    if not ok and dst.exists():
        dst.unlink()
    print(f"  {'✓' if ok else '✗'} {tag}", flush=True)
    return tag, ok, ch["url"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg לא מותקן")
    if not SCAN.exists():
        sys.exit(f"אין {SCAN} — הרץ קודם את scan_embyil.py")
    global LABEL_OK
    LABEL_OK = bool(FONT) and has_drawtext()
    if not LABEL_OK:
        why = "לא נמצא פונט" if not FONT else "ה-ffmpeg כאן בלי drawtext"
        print(f"⚠️  {why} — התמונות ייווצרו בלי מספר צרוב. הסדר בגיליון עדיין\n"
              f"    לפי map.json, אז אפשר לזהות לפיו.")

    data = json.loads(SCAN.read_text(encoding="utf-8"))
    chans = data["all"] if a.all else data["new"]
    chans = sorted(chans, key=lambda c: (c["pattern"], c["id"]))
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    print(f"תופסת פריים מ-{len(chans)} ערוצים ({a.jobs} במקביל)…\n")
    with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        res = list(ex.map(grab, chans))

    live = [r for r in res if r[1]]
    dead = [r for r in res if not r[1]]
    print(f"\nהצליחו: {len(live)}   לא החזירו תמונה: {len(dead)}")
    if dead:
        print("לא עובדים כרגע: " + ", ".join(t for t, _, _ in dead))

    # מפה ממספר לכתובת, כדי שאפשר יהיה לחזור מהתמונה לערוץ
    (OUT / "map.json").write_text(
        json.dumps({t: u for t, ok, u in res if ok}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    # גיליונות של 20 (5x4). קל יותר להסתכל על חמישה גיליונות מאשר על 92 קבצים.
    files = sorted(p for p in OUT.glob("*.jpg"))
    per, n = 20, 0
    for i in range(0, len(files), per):
        n += 1
        batch = files[i:i + per]
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
        for f in batch:
            cmd += ["-i", str(f)]
        streams = "".join(f"[{k}:v]scale=384:216,setsar=1[v{k}];"
                          for k in range(len(batch)))
        ins = "".join(f"[v{k}]" for k in range(len(batch)))
        cmd += ["-filter_complex",
                f"{streams}{ins}xstack=inputs={len(batch)}:"
                f"layout={'|'.join(f'{(k%5)*384}_{(k//5)*216}' for k in range(len(batch)))}[o]",
                "-map", "[o]", "-q:v", "3", str(OUT / f"sheet_{n:02d}.jpg")]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode:
            print(f"⚠️  גיליון {n} נכשל: {r.stderr.decode()[-200:]}")
        else:
            print(f"📄 sheet_{n:02d}.jpg  ({len(batch)} ערוצים)")

    print(f"\nהכל ב-{OUT}")
    print("שלח לי את קבצי ה-sheet ואחזיר רשימת שמות לכל מספר.")


if __name__ == "__main__":
    main()
