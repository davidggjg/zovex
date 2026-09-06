#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מוצא את ספורט 5 לייב אצל embyil — לפי התוכן, לא לפי הלוגו.

## למה זה עובד ולמה הניסיון הקודם נכשל

אצל ספק pw הלוגו בפינה הוא תג גנרי — "5 ישיר" — וכל ערוצי משפחת ספורט 5
מציגים אותו זהה לחלוטין. נבדק: 12255 ו-2341 הראו באותו רגע בדיוק אותו תג.
**הפינה שם לא מזהה כלום.**

מה שכן מזהה הוא **מה משודר**. לכל ערוץ יש בכל רגע משחק אחר, ולוח השידורים
של וואלה אומר בדיוק איזה. לכן הסקריפט הזה עושה שני דברים יחד:

  1. מושך מוואלה את "מה משודר עכשיו" בכל ערוצי הספורט הישראליים — זה
     **פתרון התרגיל**, מוכן מראש.
  2. תופס פריים מכל ערוץ מועמד אצל embyil.

אחר כך מצליבים: הערוץ שבפריים שלו רואים את המשחק שוואלה מייחסת ל-5LIVE —
הוא 5LIVE. זיהוי חד-משמעי, בלי לנחש מלוגו.

בונוס: אצל embyil הלוגו בפינה **כן** נושא שם בעברית ("ספורט 6"), בשונה
מ-pw. אז לרוב יש שתי ראיות עצמאיות באותה תמונה.

## למה זה חייב לרוץ על השרת

נוסה מבחוץ ונכשל: הפרוקסי בדרך מפיל חלק מההורדות באמצע ומחזיר קובץ ריק,
וזה נראה בדיוק כמו ערוץ מת. לשרת יש גישה ישירה לספק, והוא גם בישראל.

## מה כבר ידוע (נבדק 06/09, אומת מול הלוח)

  מרחב /live/      120 = ממשפחת ספורט 5 (שידר עפולה-יפו) · 150 = 5GOLD
                   170 = ONE 2 · 180 = EUROSPORT 1 · 190 = EUROSPORT 2
                   200 = one edge · 201 = UFC
  מרחב :7070       102 = 5MAX (שידר מרלינס-קאבס) · 103 = ספורט 6 · 118 = ספורט 2

הנותרים במרחב :7070 הם המועמדים, וברירת המחדל של הסקריפט היא בדיוק הם.

    python3 find_sport5_embyil.py              # מפתח + פריימים למועמדים
    python3 find_sport5_embyil.py --key-only   # רק לוח השידורים, בלי לגעת בספק
    python3 find_sport5_embyil.py 104 108 115  # מספרים מפורשים
    python3 find_sport5_embyil.py --live 130 140   # לסרוק את מרחב /live/ במקום

הפלט: data/sport5emb/sheet_NN.jpg — שלח לי אותם ואחזיר מי מי.
"""
import argparse, json, pathlib, re, shutil, subprocess, sys, time, urllib.request
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    IL = ZoneInfo("Asia/Jerusalem")
except Exception:
    IL = None

RELAY = "http://127.0.0.1:8000/hls-relay"
OUT = pathlib.Path("/opt/zovex-bot/data/sport5emb")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "Chrome/124 Safari/537.36")

# מועמדים: מה שענה בסריקה במרחב :7070 ועדיין לא מזוהה.
# 103 ו-118 מושארים בכוונה — הם ידועים, ומשמשים אמת מידה שהשיטה עובדת.
CAND_7070 = [103, 104, 108, 115, 117, 118, 119, 121, 122, 123,
             125, 126, 127, 128, 129, 130]

# ערוצי הספורט הישראליים בוואלה. provider=2 (HOT) מחזיק את כולם.
# 3600 הוא 5LIVE — זה מה שמחפשים.
WALLA_SPORT = {
    3600: "★ 5LIVE  ← זה מה שמחפשים",
    322: "★ 5+ LIVE (אותו ערוץ, שם ישן)",
    521: "ספורט 5", 204: "ספורט 5+", 321: "5+ GOLD", 4662: "5MAX",
    4271: "ספורט 5 סטארס", 289: "ערוץ הספורט", 3540: "ספורט 1",
    520: "ספורט 2", 3762: "ספורט 3", 3763: "ספורט 4", 3539: "ספורט 6",
    336: "יורוספורט", 3536: "יורוספורט 2", 3550: "ONE", 4259: "ONE 2",
}


def now_playing():
    """{שם: (כותרת, תקציר)} לכל ערוץ ספורט, מהלוח של וואלה.

    השדות הם title_name/synopsis ולא title/desc — קל ליפול על זה ולקבל
    לוח עם שעות נכונות וכותרות ריקות."""
    req = urllib.request.Request(
        "https://dal.walla.co.il/tv/list?provider=2",
        headers={"User-Agent": UA, "Referer": "https://tv-guide.walla.co.il/"})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = json.loads(r.read()).get("data", [])
    now, out = time.time(), {}
    for ch in data:
        code = ch.get("channel_code")
        if code not in WALLA_SPORT:
            continue
        for p in (ch.get("schedule") or []):
            try:
                dt = datetime.strptime(p["start_time"], "%Y-%m-%d %H:%M:%S")
                st = (dt.replace(tzinfo=IL) if IL else dt).timestamp()
                dt = datetime.strptime(p["end_time"], "%Y-%m-%d %H:%M:%S")
                en = (dt.replace(tzinfo=IL) if IL else dt).timestamp()
            except Exception:
                continue
            if st <= now < en:
                out[WALLA_SPORT[code]] = ((p.get("title_name") or "").strip(),
                                          (p.get("synopsis") or "").strip())
                break
    return out


def print_key():
    try:
        np = now_playing()
    except Exception as e:
        print(f"⚠ לא הצלחתי למשוך את הלוח מוואלה: {e}")
        print("  בלי המפתח אפשר עדיין לזהות מהלוגו, רק פחות ודאי.\n")
        return
    stamp = datetime.now(IL) if IL else datetime.now()
    print("═" * 72)
    print(f"  מה משודר עכשיו — {stamp.strftime('%d/%m %H:%M')} · מקור: וואלה")
    print("═" * 72)
    for name in sorted(np, key=lambda n: (not n.startswith("★"), n)):
        title, syn = np[name]
        print(f"  {name}")
        print(f"      {title}")
        if syn:
            print(f"      {syn[:120]}")
    print("═" * 72)
    print("  חפש בפריימים את המשחק שמופיע מול ★ — הערוץ הזה הוא 5LIVE.\n")


def url_for(n: int, live: bool) -> str:
    if live:
        return f"{RELAY}/tv.embyil.tv/live/{n}/chunks.m3u8"
    return f"{RELAY}/tv.embyil.tv:7070/p/embyil/s/{n}/playlist.m3u8"


def grab(n: int, live: bool, work: pathlib.Path):
    """פריים אחד. ffmpeg קורא את ה-playlist ומושך בעצמו — מהשרת זה ישיר
    ואמין, בשונה מהורדה ידנית דרך פרוקסי."""
    dst = work / f"g{n}.jpg"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
         "-rw_timeout", "20000000", "-i", url_for(n, live),
         "-frames:v", "1", "-q:v", "2", "-y", str(dst)],
        capture_output=True, timeout=120)
    return dst if dst.exists() and dst.stat().st_size > 5000 else None


def strip(src: pathlib.Path, dst: pathlib.Path):
    """הרצועה העליונה בלבד, מוגדלת. שם המשחק יושב שם משמאל והלוגו מימין,
    ובפריים מוקטן שניהם נמרחים לכמה פיקסלים."""
    subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
         "-i", str(src), "-vf", "crop=iw:ih*0.17:0:0,scale=1500:-2",
         "-frames:v", "1", "-q:v", "2", "-y", str(dst)],
        capture_output=True, timeout=60)
    return dst if dst.exists() else None


def sheet(images, dst: pathlib.Path):
    args = []
    for p in images:
        args += ["-i", str(p)]
    filt = "".join(f"[{i}:v]" for i in range(len(images)))
    filt += f"vstack=inputs={len(images)}[o]"
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                    *args, "-filter_complex", filt, "-map", "[o]",
                    "-q:v", "3", "-y", str(dst)], capture_output=True,
                   timeout=180)
    return dst if dst.exists() else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("channels", nargs="*", type=int)
    ap.add_argument("--key-only", action="store_true",
                    help="רק לוח השידורים — לא נוגע בספק בכלל")
    ap.add_argument("--live", nargs=2, type=int, metavar=("מ", "עד"),
                    help="לסרוק טווח במרחב /live/ במקום ב-:7070")
    ap.add_argument("--sleep", type=float, default=3.0)
    a = ap.parse_args()

    print_key()
    if a.key_only:
        return
    if not shutil.which("ffmpeg"):
        sys.exit("❌ ffmpeg אינו מותקן")

    live = bool(a.live)
    nums = (list(range(a.live[0], a.live[1] + 1)) if live
            else (a.channels or CAND_7070))
    space = "/live/" if live else ":7070"
    print(f"{len(nums)} ערוצים במרחב {space} · השהיה {a.sleep}ש'\n")

    OUT.mkdir(parents=True, exist_ok=True)
    work = OUT / "raw"
    work.mkdir(exist_ok=True)

    strips = []
    for i, n in enumerate(nums, 1):
        f = grab(n, live, work)
        print(f"  {i:3}/{len(nums)}  {'✓' if f else '✗'}  {space}{n}", flush=True)
        if f:
            s = strip(f, work / f"s{n}.jpg")
            if s:
                strips.append(s)
        time.sleep(a.sleep)

    if not strips:
        print("\n❌ לא נתפס אף פריים. הספק אולי חונק — נסה שוב בעוד כמה דקות.")
        return

    made = []
    for k in range(0, len(strips), 6):
        d = OUT / f"sheet_{k // 6 + 1:02d}.jpg"
        if sheet(strips[k:k + 6], d):
            made.append(d)

    print("\n" + "─" * 66)
    for p in made:
        print(f"  {p}   ({p.stat().st_size // 1024}KB)")
    print("─" * 66)
    print("שלח לי את הגיליונות. אצליב אותם מול המפתח שלמעלה ואחזיר מי מי.")


if __name__ == "__main__":
    main()
