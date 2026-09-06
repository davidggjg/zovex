#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מזהה ערוצים לפי הלוגו שבפינה — במיוחד למצוא את 5LIVE.

## למה זה נדרש

בקטלוג יש `ספורט 5`, `ספורט 5 גולד` ו`ספורט 5 סטארס`, אבל **אין `ספורט 5
לייב`** — וזה ערוץ נפרד ואמיתי. ויקיפדיה מאשרת שבע ערוצים במשפחה:
5SPORT · 5PLUS · **5LIVE** · 5GOLD · 5STARS · 5MAX · 5SPORT 4K.
5LIVE נקרא בעבר "5+ לייב" והמותג שונה ב-2013.

## מה שכן ומה שלא מזהה ערוץ

**"ישיר" בפינה אינו שם של ערוץ.** זה תג שידור חי שכל ערוץ מציג בזמן משחק —
ספורט 1 בשידור חי יראה אותו בדיוק כמו 5LIVE. זו הסיבה ששני ערוצים נראו
"אותו דבר" בבדיקה קודמת.

**⚠️ נבדק בשטח ב-06/09 — והשיטה הזאת אינה עובדת.** חמישה ערוצי ספורט 5
שידרו חמישה משחקים שונים והציגו **סימן פינה זהה לחלוטין** (דגל + 5 + תג
אדום). והתג עצמו מתחלף: ערוץ 12255 הראה `LIVE` באנגלית, ושתי דקות אחר כך
`ישיר` בעברית. **הפינה אינה מזהה את הערוץ, לא לפי הלוגו ולא לפי המילה.**

מה שכן מבדיל הוא **התוכן**: כל ערוץ משדר משחק אחר, ואת זה אפשר להצליב מול
לוח השידורים הרשמי. לכן הכלי הזה שווה למיפוי ולתפיסת פריימים — אבל התיוג
הסופי דורש מקור חיצוני, או תפיסה בשעה שקטה שבה כל ערוץ מציג את המותג שלו
במקום גרפיקת הליגה המשותפת.

## למה מתחילים מערוצים שכבר ידועים

`ספורט 5` (2341) ו`ספורט 5 סטארס` (12278) כבר מזוהים ומגיעים **מאותו ספק,
אותו מקודד, אותה שכבת גרפיקה.** הפינה שלהם היא אמת המידה הטובה ביותר שיש —
טובה מכל צילום מסך מהרשת. לכן `--known` תופס אותם קודם.

## זהירות מול הספק

סריקה קודמת פתחה כמה ערוצים ברצף והספק חנק אותנו — 502 על כל הערוצים.
לכן: ערוץ אחד בכל פעם, השהיה ביניהם, וברירת מחדל של רשימה קצרה. אין כאן
סריקת טווח עיוורת.

    python3 find_sport5live.py --known          # רק המזוהים, כאמת מידה
    python3 find_sport5live.py --near           # שכני ערוצי הספורט
    python3 find_sport5live.py 12250 12252 …    # מספרים מפורשים
    python3 find_sport5live.py --known --sleep 6

הפלט: `data/sport5/sheet_NN.jpg` — **שלח לי אותם ואחזיר מי מי.**
"""
import argparse, json, os, pathlib, shutil, subprocess, sys, time

LOCAL = "http://127.0.0.1:8000"
OUT = pathlib.Path("/opt/zovex-bot/data/sport5")

# ערוצי הספורט המזוהים אצל ספק pw, מהקטלוג. אלה אמת המידה.
KNOWN = {
    2341: "ספורט 5",
    2389: "ספורט 4",
    7203: "יורוספורט 2",
    12249: "ספורט 1",
    12251: "ספורט 3",
    12278: "ספורט 5 סטארס",
}

# משפחת הספורט מרוכזת סביב 12249-12278. 5LIVE כמעט בוודאות שם.
NEAR = [n for n in range(12245, 12290) if n not in KNOWN]


def relay_url(host_path: str, n: int, fix: bool) -> str:
    pre = "_fix/" if fix else ""
    return f"{LOCAL}/hls-relay/{pre}{host_path}/{n}/"


def provider_from_catalog():
    """מוציא את הכתובת של ספק הספורט מהקטלוג עצמו, ולא מקבוע בקוד —
    המפתח בכתובת עשוי להתחלף."""
    raw = subprocess.run(["curl", "-sS", "--noproxy", "127.0.0.1",
                          "--max-time", "90", f"{LOCAL}/movies.json"],
                         capture_output=True).stdout
    try:
        cat = json.loads(raw)
    except Exception as e:
        print(f"❌ לא הצלחתי לקרוא את הקטלוג: {e}")
        sys.exit(1)
    for m in cat:
        u = str(m.get("video_url", ""))
        if "siauliairsavlt" in u and "/iptv/" in u:
            # …/hls-relay/[_fix/]<host>/iptv/<key>/<n>[/]
            tail = u.split("/hls-relay/", 1)[1]
            if tail.startswith("_fix/"):
                tail = tail[5:]
            parts = tail.rstrip("/").split("/")
            return "/".join(parts[:-1])          # host/iptv/key
    print("❌ לא נמצא ספק הספורט בקטלוג")
    sys.exit(1)


def grab(host_path: str, n: int, workdir: pathlib.Path, shots=3, spacing=14):
    """כמה פריימים לאורך זמן. פריים אחד נופל על פרסומת או על רגע שהלוגו מוסתר."""
    got = []
    for i in range(shots):
        dst = workdir / f"{n}_{i}.jpg"
        for fix in (False, True):        # קודם בלי המרה — זול בהרבה
            r = subprocess.run(
                ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                 "-rw_timeout", "20000000", "-i", relay_url(host_path, n, fix),
                 "-frames:v", "1", "-q:v", "2", "-y", str(dst)],
                capture_output=True, timeout=90)
            if dst.exists() and dst.stat().st_size > 5000:
                got.append(dst)
                break
        if i < shots - 1:
            time.sleep(spacing)
    return got


def has_drawtext() -> bool:
    """לא כל בניית ffmpeg כוללת drawtext — הוא דורש libfreetype. הבנייה
    הסטטית שנבדקה כאן *אינה* כוללת אותו, וזה הפיל את כל השלב."""
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                         capture_output=True, text=True).stdout
    return " drawtext " in out


_DRAWTEXT = None


def strip_and_label(src: pathlib.Path, label: str, dst: pathlib.Path):
    """חותך את הרצועה העליונה ומגדיל אותה. הלוגו יושב שם כמעט תמיד, ובפריים
    מוקטן הוא נמרח לכמה פיקסלים ואי אפשר לקרוא אותו.

    התווית נצרבת רק אם ffmpeg יודע. אחרת היא נשארת בשם הקובץ — עדיף פריים
    בלי כיתוב מאשר שלב שנופל כולו."""
    global _DRAWTEXT
    if _DRAWTEXT is None:
        _DRAWTEXT = has_drawtext()
    vf = "crop=iw:ih*0.20:0:0,scale=1200:-2"
    if _DRAWTEXT:
        vf += (f",drawtext=text='{label}':x=10:y=10:fontsize=34:"
               "fontcolor=yellow:box=1:boxcolor=black@0.7:boxborderw=6")
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                    "-i", str(src), "-vf", vf, "-frames:v", "1", "-q:v", "2",
                    "-y", str(dst)], capture_output=True, timeout=60)
    return dst if dst.exists() else None


def sheet(images, dst: pathlib.Path, cols=1):
    if not images:
        return None
    args = []
    for p in images:
        args += ["-i", str(p)]
    n = len(images)
    filt = "".join(f"[{i}:v]" for i in range(n)) + f"vstack=inputs={n}[o]"
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                    *args, "-filter_complex", filt, "-map", "[o]",
                    "-q:v", "3", "-y", str(dst)], capture_output=True,
                   timeout=180)
    return dst if dst.exists() else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("channels", nargs="*", type=int)
    ap.add_argument("--known", action="store_true",
                    help="הערוצים המזוהים — אמת המידה ללוגו")
    ap.add_argument("--near", action="store_true",
                    help="שכני ערוצי הספורט (12245-12289)")
    ap.add_argument("--sleep", type=float, default=4.0,
                    help="השהיה בין ערוצים. אל תוריד — הספק חונק")
    ap.add_argument("--shots", type=int, default=3)
    a = ap.parse_args()

    if not shutil.which("ffmpeg"):
        print("❌ ffmpeg אינו מותקן")
        sys.exit(1)

    nums = list(a.channels)
    if a.known:
        nums = sorted(KNOWN) + nums
    if a.near:
        nums += NEAR
    if not nums:
        print(__doc__)
        print("❌ בחר מה לבדוק: --known / --near / מספרים")
        sys.exit(1)
    seen, nums = set(), [n for n in nums if not (n in seen or seen.add(n))]

    host_path = provider_from_catalog()
    print(f"ספק: {host_path}")
    print(f"{len(nums)} ערוצים · {a.shots} פריימים לכל אחד · "
          f"השהיה {a.sleep}ש'\n")

    OUT.mkdir(parents=True, exist_ok=True)
    work = OUT / "raw"
    work.mkdir(exist_ok=True)

    strips = []
    for i, n in enumerate(nums, 1):
        label = f"{n}" + (f"  = {KNOWN[n]}" if n in KNOWN else "")
        frames = grab(host_path, n, work, a.shots)
        mark = "✓" if frames else "✗"
        print(f"  {i:3}/{len(nums)}  {mark} {label}"
              f"   ({len(frames)} פריימים)", flush=True)
        for j, f in enumerate(frames):
            s = strip_and_label(f, label.replace("'", ""), work / f"s_{n}_{j}.jpg")
            if s:
                strips.append(s)
        time.sleep(a.sleep)

    if not strips:
        print("\n❌ לא נתפס אף פריים. הספק אולי חונק — נסה שוב מאוחר יותר.")
        return

    made = []
    for k in range(0, len(strips), 8):
        dst = OUT / f"sheet_{k // 8 + 1:02d}.jpg"
        if sheet(strips[k:k + 8], dst):
            made.append(dst)

    print()
    print("─" * 56)
    for p in made:
        print(f"  {p}   ({p.stat().st_size // 1024}KB)")
    print("─" * 56)
    print("שלח לי את הגיליונות ואחזיר מי מי.")
    print("מה שמחפשים: ה-5 המשופע הכחול, ולצידו GOLD / STARS / LIVE.")
    print('"ישיר" לבדו אינו שם ערוץ — כל ערוץ מציג אותו בשידור חי.')


if __name__ == "__main__":
    main()
