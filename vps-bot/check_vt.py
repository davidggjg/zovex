#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_vt — למה פריט VOD לא מתנגן, עם הקוד האמיתי ולא עם ניחוש.

## למה

הנגן מדווח ‎manifestLoadError‎ על **ארבעה** מצבים שונים לגמרי, ולכל
אחד תיקון אחר:

    503   תקרת ההמרות (VT_MAX_CONCURRENT=2) — צופה שלישי נדחה
    502   ffmpeg יצא — בעיה בקובץ המקור
    504   ההמרה לא התחילה תוך 15 שניות
    403   חתימה או hotlink

הכלי שואל את ‎/vt/‎ ישירות מהשרת ומדפיס את הקוד ואת גוף התשובה.

## מה נמדד כאן לפני שנכתב

AVI שומר את טבלת האינדקס (‎idx1‎) **בסוף הקובץ**. נמדד על AVI אמיתי
מול שרת שמתעד כל בקשת Range: ffprobe עושה 5 נסיעות הלוך-חזור, ובהן
**2 קפיצות לזנב** כדי לקרוא את האינדקס. על קובץ של ג'יגות שנמשך
מטלגרם, אלה הנסיעות היקרות.

ונמדד גם ההפך: ההמרה עצמה **עובדת** — מקטע ראשון אחרי 3.7 שניות. כלומר
AVI אינו שבור מהותית, ולכן אסור להניח שזו הסיבה בלי לראות את הקוד.

(ו-‎-fflags +ignidx‎ נבדק ו**לא** עזר: אותן 5 בקשות בדיוק.)

    python3 check_vt.py "פופר"        # לפי שם
    python3 check_vt.py --sample 8     # כמה פריטים אקראיים
    python3 check_vt.py --selftest

**זהירות**: כל בדיקה של ‎/vt/‎ מפעילה המרה אמיתית, והתקרה היא 2
במקביל. לכן הבדיקות רצות אחת-אחת עם הפוגה — סורק מקבילי היה יוצר את
ה-503 שהוא אמור למדוד.

קריאה בלבד.
"""
import argparse
import json
import random
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit, parse_qs

LOCAL = "http://127.0.0.1:8000"
CURL = ["curl", "-sS", "--noproxy", "127.0.0.1"]
STREAM = re.compile(r"/stream/(-?\d+)/(\d+)")


def vt_url_from_stream(url: str) -> str:
    """‎/stream/<chat>/<msg>?exp=&sig=‎ ⇒ ‎/vt/<chat>/<msg>/index.m3u8?...‎

    שני הנתיבים נחתמים באותה פונקציה (‎_stream_sig‎), ולכן אותה חתימה
    תקפה לשניהם — זה מה שמאפשר לבדוק בלי לגעת ב-SIGN_SECRET.
    """
    m = STREAM.search(url or "")
    if not m:
        return ""
    u = urlsplit(url)
    q = parse_qs(u.query)
    exp = (q.get("exp") or [""])[0]
    sig = (q.get("sig") or [""])[0]
    tail = f"?exp={exp}&sig={sig}" if exp and sig else ""
    return f"/vt/{m.group(1)}/{m.group(2)}/index.m3u8{tail}"


def title_of(e: dict) -> str:
    for k in ("title", "name"):
        v = e.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().replace("-", " ")).strip()


def ask(path: str, timeout=40, base: str = ""):
    """(קוד, גוף מקוצר). ‎base‎ ריק = השרת המקומי; אחרת דרך nginx.

    ההבחנה הזאת היא כל העניין: בדיקה ל-127.0.0.1 **עוקפת את nginx**,
    את TLS ואת כל שכבת הקצה. האפליקציה מגיעה מבחוץ, ולכן "עובד מהשרת"
    אינו אומר "עובד לאפליקציה" — וזה בדיוק הפער שנמדד כאן.
    """
    cmd = (CURL if not base else ["curl", "-sS"])
    r = subprocess.run(
        cmd + ["-o", "/tmp/_vt_body", "-w", "%{http_code}",
               "--max-time", str(timeout), (base or LOCAL) + path],
        capture_output=True)
    code = r.stdout.decode().strip() or "?"
    try:
        with open("/tmp/_vt_body", "rb") as fh:
            body = fh.read(400).decode("utf-8", "replace")
    except Exception:
        body = ""
    return code, " ".join(body.split())[:160]


MEANING = {
    "200": "✓ ההמרה עובדת. אם בנגן זה עדיין נכשל — הבעיה בלקוח ולא כאן.",
    "503": "תקרת ההמרות. VT_MAX_CONCURRENT=2, וצופה שלישי נדחה. "
           "זה תיקון של הגדרה, לא של קוד.",
    "502": "ffmpeg יצא. הקובץ עצמו — קודק, קובץ קטוע, או מקור שלא נמשך.",
    "504": "ההמרה לא הספיקה להתחיל תוך 15 שניות. על קובץ גדול שנמשך "
           "מטלגרם זה הסביר ביותר, וזה מה שצריך להרחיב או לייעל.",
    "403": "חתימה או hotlink. לא קשור ל-AVI.",
    "404": "הפריט אינו קיים במסלול הזה.",
}


def selftest() -> int:
    bad = 0

    def chk(ok, what):
        nonlocal bad
        if not ok:
            bad += 1
        print(f"{'✓' if ok else '✗'} {what}")

    u = "https://z.example/stream/-1003936100530/9530?exp=1791069854&sig=abc123"
    got = vt_url_from_stream(u)
    chk(got == "/vt/-1003936100530/9530/index.m3u8?exp=1791069854&sig=abc123",
        f"גזירת כתובת ההמרה ⇒ {got}")
    chk(vt_url_from_stream(
        "https://z.example/stream/-100/7").startswith("/vt/-100/7/"),
        "בלי חתימה — עדיין נבנה")
    chk(vt_url_from_stream("https://z.example/hls-relay/h/x.m3u8") == "",
        "כתובת שאינה /stream מוחזרת ריקה")
    chk(vt_url_from_stream("") == "" and vt_url_from_stream(None) == "",
        "קלט ריק")
    # מזהה צ'אט שלילי חייב לשרוד — זה הפורמט של טלגרם
    chk("-1003936100530" in got, "מזהה צ'אט שלילי נשמר")
    chk(norm("מר פופר  והפינגווינים") == "מר פופר והפינגווינים", "נרמול")

    print("\n" + ("✓ הכל עבר" if not bad else f"✗ {bad} נכשלו"))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?", default="")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--gap", type=float, default=3.0,
                    help="הפוגה בין בדיקות — כל אחת מפעילה המרה")
    ap.add_argument("--timeout", type=float, default=40)
    ap.add_argument("--public", action="store_true",
                    help="דרך nginx מבחוץ, כמו האפליקציה — ולא ל-127.0.0.1")
    ap.add_argument("--both", action="store_true",
                    help="שתי הדרכים, זו מול זו")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.name and not a.sample:
        sys.exit('צריך שם: python3 check_vt.py "פופר"   (או --sample 8)')

    r = subprocess.run(CURL + ["--max-time", "180", f"{LOCAL}/content"],
                       capture_output=True)
    try:
        items = json.loads(r.stdout)
    except Exception as e:                                    # noqa: BLE001
        sys.exit(f"❌ לא ניתן לקרוא את הקטלוג: {e}")
    if isinstance(items, dict):
        items = items.get("movies", [])

    vod = [e for e in items
           if not (e.get("is_live") or e.get("category") == "שידורים חיים")
           and STREAM.search(e.get("video_url") or "")]
    if not vod:
        sys.exit("אין פריטי VOD עם כתובת /stream בקטלוג.")

    if a.name:
        n = norm(a.name)
        hits = [e for e in vod if n in norm(title_of(e))]
        if not hits:
            print(f"לא נמצא פריט ששמו מכיל {a.name!r}. דוגמאות מהקטלוג:\n")
            for e in vod[:12]:
                print("  " + title_of(e))
            return 1
    else:
        hits = random.sample(vod, min(a.sample, len(vod)))

    def public_base(url: str) -> str:
        u = urlsplit(url or "")
        return f"{u.scheme}://{u.netloc}" if u.scheme and u.netloc else ""

    modes = [("מקומי (עוקף nginx)", "")]
    if a.public or a.both:
        pb = public_base((hits[0] or {}).get("video_url"))
        if not pb:
            sys.exit("❌ אין בקטלוג כתובת מוחלטת — אי אפשר לבדוק מבחוץ")
        modes = ([("מקומי (עוקף nginx)", "")] if a.both else []) + \
                [("ציבורי (דרך nginx, כמו האפליקציה)", pb)]

    print(f"{len(hits)} פריטים · כל בדיקה מפעילה המרה אמיתית, "
          f"אחת-אחת עם {a.gap:.0f}ש׳ הפוגה\n" + "=" * 60)
    codes = {}
    for i, e in enumerate(hits, 1):
        path = vt_url_from_stream(e.get("video_url"))
        t = title_of(e) or "(בלי שם)"
        print(f"\n{i}. {t[:40]}")
        for label, base in modes:
            t0 = time.time()
            code, body = ask(path, a.timeout, base)
            dt = time.time() - t0
            codes[code] = codes.get(code, 0) + 1
            tag = "✓" if code == "200" else "✗"
            print(f"   {tag} {label:<36} {code}  ({dt:.1f}ש)"
                  + (f"  {body[:70]}" if body and code != "200" else ""))
            if len(modes) > 1:
                time.sleep(1.0)
        if i < len(hits):
            time.sleep(a.gap)

    print("\n" + "=" * 60)
    for c, n in sorted(codes.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>3} × {c}   {MEANING.get(c, '')}")
    print()
    if set(codes) == {"200"} and len(modes) > 1:
        print("עובד גם מבחוץ דרך nginx. כלומר הבעיה אינה בשרת ואינה בקצה —")
        print("היא בנגן של האפליקציה: מה הוא מבקש, כמה זמן הוא מחכה, ואיך")
        print("הוא מתנהג כשהמניפסט לוקח ~7 שניות להיבנות.")
    elif set(codes) == {"200"}:
        print("עובד מהשרת. אבל זה **עקף את nginx** — הרץ עם --both כדי")
        print("לראות אם זה עובד גם מבחוץ, כמו שהאפליקציה מבקשת.")
    elif "504" in codes:
        print("504 הוא הסביר ביותר לקובץ גדול: לפני שההמרה מתחילה רצה")
        print("ffprobe, ועל AVI הוא עושה 5 נסיעות — ובהן 2 קפיצות לזנב")
        print("הקובץ לקריאת האינדקס. נמדד. זה מה שצריך לקצר.")
    elif "503" in codes:
        print("503 = התקרה, לא הקובץ. VT_MAX_CONCURRENT=2 מוגדר נמוך,")
        print("וכל צופה שלישי נדחה בלי קשר לסיומת.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
