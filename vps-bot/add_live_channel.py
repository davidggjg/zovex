#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מוסיף ערוץ חי לקטלוג — בבטחה, ובלי לגעת בשאר התוכן.

## למה סקריפט ולא עריכה ידנית

`content.json` הוא מקור האמת לכל התוכן. `/content/save` מקבל את **המערך
המלא** — כלומר כל שמירה דורסת הכל. שמירה מטאב ישן מוחקת עבודה של אחרים,
ולכן קיים שם מנגנון נעילה אופטימית (`base_version`) שדוחה שמירה אם התוכן
השתנה בינתיים. הסקריפט הזה משתמש בו כמו שצריך: קורא, מוסיף פריט אחד, ומחזיר
עם הגרסה שקרא. אם מישהו ערך בזמן הזה — השמירה נדחית ולא נדרס דבר.

הפריט נבנה **בדיוק** במבנה של ערוץ חי קיים. שמונה שדות משותפים לכל 102
הערוצים: title · video_url · thumbnail_url · custom_slug · category ·
is_live · id · created_date.

    python3 add_live_channel.py --url "https://…/12255/index.m3u8" \
                                --title "ספורט 5 לייב" --slug 5LIVE
    python3 add_live_channel.py … --dry-run      # מראה ולא שומר
    python3 add_live_channel.py … --thumb "https://…png"

הסיסמה נקראת מ-PANEL_PASSWORD או מ-/opt/zovex-bot/.env.
"""
import argparse, json, pathlib, re, subprocess, sys, time, uuid

LOCAL = "http://127.0.0.1:8000"
ENV = pathlib.Path("/opt/zovex-bot/.env")
CURL = ["curl", "-sS", "--noproxy", "127.0.0.1"]
LIVE_CATEGORY = "שידורים חיים"


def panel_password():
    import os
    p = os.environ.get("PANEL_PASSWORD", "").strip()
    if p:
        return p
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("PANEL_PASSWORD="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def get_content():
    """המערך והגרסה. הגרסה מגיעה בכותרת X-Content-Version ולא בגוף."""
    r = subprocess.run(CURL + ["-D", "/tmp/_ch_hdr", "--max-time", "180",
                               f"{LOCAL}/content"], capture_output=True)
    ver = None
    try:
        for line in pathlib.Path("/tmp/_ch_hdr").read_text(
                encoding="latin1", errors="replace").splitlines():
            if line.lower().startswith("x-content-version:"):
                ver = int(line.split(":", 1)[1].strip())
    except Exception:
        pass
    try:
        return json.loads(r.stdout), ver
    except json.JSONDecodeError as e:
        print(f"❌ לא הצלחתי לקרוא את הקטלוג: {e}")
        sys.exit(1)


def check_url(url: str):
    """שהערוץ באמת מחזיר playlist **עם תוכן**. מחזיר (תקין, הסבר).

    לא מספיק לבדוק שהתשובה מתחילה ב-#EXTM3U. ספק שנפל מחזיר 200 עם כותרת
    תקינה לגמרי ואפס מקטעים:

        #EXTM3U
        #EXT-X-VERSION:3
        #EXT-X-MEDIA-SEQUENCE:0
        #EXT-X-TARGETDURATION:0

    זה נתפס בשטח ב-06/09 — הבדיקה הישנה אישרה את זה בתור "חי", והערוץ היה
    נכנס לקטלוג מת. הסימן הוא TARGETDURATION:0 ואפס שורות שאינן הערה.

    שורה שאינה מתחילה ב-# היא או מקטע (playlist מדיה) או וריאנט
    (playlist ראשי) — שניהם תקינים, ולכן מספיק לספור אותן."""
    out = subprocess.run(["curl", "-sS", "--max-time", "40", url],
                         capture_output=True).stdout[:20000]
    if not out.startswith(b"#EXTM3U"):
        return False, "התשובה אינה playlist כלל"
    lines = [l.strip() for l in out.splitlines()[1:] if l.strip()]
    body = [l for l in lines if not l.startswith(b"#")]
    if not body:
        return False, ("ה-playlist ריק — כותרת תקינה ואפס מקטעים. "
                       "זה ספק שנפל, לא קישור שגוי")
    return True, f"{len(body)} מקטעים"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--slug", default="")
    ap.add_argument("--thumb", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="להוסיף גם אם הערוץ ריק כרגע (ספק שנפל זמנית)")
    a = ap.parse_args()

    print("── בודקת שהערוץ חי ──")
    ok, why = check_url(a.url)
    if ok:
        print(f"   ✓ {why}")
    elif a.force:
        print(f"   ⚠ {why}")
        print("   --force — מוסיפים בכל זאת. הערוץ יהיה מת עד שהספק יחזור.")
    else:
        print(f"❌ {why}")
        print("   הקישור נשמר בקטלוג כפי שהוא, והאתר מנגן דרכו — ערוץ ריק")
        print("   עכשיו יהיה ערוץ מת לכל הצופים.")
        print("   אם אתה יודע שזה זמני: להוסיף --force")
        sys.exit(1)

    movies, ver = get_content()
    live = [m for m in movies if m.get("category") == LIVE_CATEGORY]
    print(f"── הקטלוג: {len(movies)} פריטים · {len(live)} ערוצים חיים · "
          f"גרסה {ver} ──")

    n = re.search(r"/(\d+)(?:/|$)", a.url.split("?")[0].rstrip("/")
                  .replace("/index.m3u8", ""))
    for m in movies:
        if str(m.get("video_url", "")).split("?")[0] == a.url.split("?")[0]:
            print(f"❌ הקישור כבר בקטלוג בשם {m.get('title')!r}")
            sys.exit(1)
        if m.get("title") == a.title and m.get("category") == LIVE_CATEGORY:
            print(f"❌ כבר קיים ערוץ חי בשם {a.title!r}")
            sys.exit(1)

    entry = {
        "title": a.title,
        "video_url": a.url,
        "video_id": None,
        "thumbnail_url": a.thumb,
        "custom_slug": a.slug or (n.group(1) if n else ""),
        "category": LIVE_CATEGORY,
        "type": None,
        "series_name": None,
        "season_number": None,
        "episode_number": None,
        "episode_title": None,
        "year": None,
        "description": "",
        "id": str(uuid.uuid4()),
        "created_date": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "is_live": True,
    }
    print("── הפריט שיתווסף ──")
    print(json.dumps(entry, ensure_ascii=False, indent=1))

    if a.dry_run:
        print("\n(--dry-run — לא נשמר כלום)")
        return

    pwd = panel_password()
    if not pwd:
        print("❌ לא נמצאה PANEL_PASSWORD")
        sys.exit(1)

    body = json.dumps({"password": pwd, "movies": movies + [entry],
                       "base_version": ver}, ensure_ascii=False)
    tmp = pathlib.Path("/tmp/_ch_body.json")
    tmp.write_text(body, encoding="utf-8")
    out = subprocess.run(CURL + ["--max-time", "300", "-H",
                                 "Content-Type: application/json",
                                 "--data-binary", f"@{tmp}",
                                 f"{LOCAL}/content/save"],
                         capture_output=True, text=True).stdout
    tmp.unlink(missing_ok=True)
    try:
        res = json.loads(out)
    except json.JSONDecodeError:
        print(f"❌ תשובה לא צפויה: {out[:300]}")
        sys.exit(1)
    if not res.get("ok"):
        print(f"❌ {res.get('detail') or res}")
        sys.exit(1)

    print(f"\n✅ נשמר. {res['count']} פריטים · גרסה {res['version']}")
    print("   content.json גובה אוטומטית לפני השמירה.")
    print(f"\n   לבטל: להסיר את הפריט {entry['id']} מהפאנל")


if __name__ == "__main__":
    main()
