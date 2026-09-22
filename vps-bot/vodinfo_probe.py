#!/usr/bin/env python3
"""vodinfo_probe — למה חלק מהפריטים מחזירים "לא ניתן לנגן".

קורא בלבד. לא כותב כלום ולא נוגע בשירות.

## מה נמדד מבחוץ

מדגם אקראי מהקטלוג, קריאה ל-/vodinfo דרך האינטרנט:

    16 פריטים, 4 במקביל
    12 ענו תוך 1.6-5.9 שניות
     4 נפלו ב-"Connection reset by peer" אחרי 11.1 שניות

ארבעתם באותו זמן בדיוק — 11.1, 11.1, 11.3, 11.3 — וזה לא נראה כמו
עומס אלא כמו תקרה. שלושה מהם ענו תוך 2-3 שניות בניסיון חוזר.

ובקרה: ארבע משיכות של מקטעי וידאו גדולים במקביל, 9-10 שניות כל אחת,
עברו כולן. כלומר זו לא הרשת, לא הדרך, ולא עצם המקביליות.

## למה זה חשוב

כשהקריאה נופלת, האפליקציה והאתר נפלו אחורה ל-/vh **בניחוש**. ל-AVI
ול-MKV בלי Cues זה נתיב שאינו יכול לנגן, ולכן תקלת רשת חולפת הפכה פריט
תקין ל"לא הצלחתי לנגן את הפריט הזה". בצד הלקוח כבר הוספתי שלושה
ניסיונות, אבל זה מטפל בתסמין. הכלי הזה מחפש את השורש.

## מה הוא מפריד

לכל פריט שתי קריאות: אחת **ישר לאפליקציה** על 127.0.0.1 (בלי nginx
ובלי TLS), ואחת דרך https כמו שצופה אמיתי מגיע.

    שתיהן נופלות          → הבעיה באפליקציה עצמה (בריכת הבוטים/טלגרם)
    רק דרך https נופלת    → הבעיה ב-nginx או ב-TLS שלפניו
    שתיהן עוברות          → זה תלוי-עומס; הרץ עם --concurrency 4

    python3 vodinfo_probe.py
    python3 vodinfo_probe.py --items 20 --concurrency 4
"""
import argparse
import json
import os
import random
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/opt/zovex-bot/data"))
PORT = int(os.environ.get("PORT", 8000))
PUBLIC = os.environ.get("ZOVEX_PUBLIC", "https://zovex.duckdns.org")
STREAM_RE = re.compile(r"^(.*)/stream/(-?\d+)/(\d+)(\?.*)?$")


def catalog(n):
    f = DATA_DIR / "content.json"
    if not f.exists():
        print(f"❌ לא נמצא {f}")
        return []
    try:
        items = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ content.json לא נקרא: {e}")
        return []
    out = []
    for it in items:
        m = STREAM_RE.match(str(it.get("video_url", "")))
        if m:
            out.append((it.get("series_name") or it.get("title") or "?",
                        m.group(2), m.group(3), m.group(4) or ""))
    random.shuffle(out)
    return out[:n]


def call(url):
    """(שניות, קוד, שגיאה). קוד '000' = לא התקבלה תשובה בכלל."""
    t0 = time.time()
    p = subprocess.run(
        ["curl", "-sS", "-m", "90", "-o", "/dev/null", "-w", "%{http_code}", url],
        capture_output=True, text=True)
    return (time.time() - t0, (p.stdout or "000").strip(),
            (p.stderr or "").strip().replace("\n", " ")[:60])


def probe(item):
    title, chat, msg, q = item
    # פנימי: בלי חתימה — הקריאה מ-127.0.0.1 היא ממילא מקומית, אבל אם
    # השרת דורש חתימה גם ממנה, ה-q של הקטלוג עובר כמו שהוא.
    inner = f"http://127.0.0.1:{PORT}/vodinfo/{chat}/{msg}{q}"
    outer = f"{PUBLIC}/vodinfo/{chat}/{msg}{q}"
    return title, msg, call(inner), call(outer)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", type=int, default=12)
    ap.add_argument("--concurrency", type=int, default=1,
                    help="1 = אחד-אחד (ברירת מחדל, הכי עדין לשרת)")
    a = ap.parse_args()

    items = catalog(a.items)
    if not items:
        return 1
    print(f"בודקת {len(items)} פריטים · {a.concurrency} במקביל")
    print(f"פנימי: 127.0.0.1:{PORT}   ·   חיצוני: {PUBLIC}\n")
    print(f"{'פריט':26} {'פנימי':>16}  {'חיצוני':>16}")
    print("─" * 64)

    rows = []
    with ThreadPoolExecutor(max_workers=max(1, a.concurrency)) as ex:
        for title, msg, (it_s, it_c, it_e), (ot_s, ot_c, ot_e) in ex.map(probe, items):
            rows.append((it_c, ot_c, it_e, ot_e))
            print(f"{str(title)[:26]:26} {it_s:6.1f}s {it_c:>6}  "
                  f"{ot_s:6.1f}s {ot_c:>6}")
            for tag, err in (("פנימי", it_e), ("חיצוני", ot_e)):
                if err:
                    print(f"{'':26}   ↳ {tag}: {err}")

    inner_bad = sum(1 for i, o, _, _ in rows if i != "200")
    outer_bad = sum(1 for i, o, _, _ in rows if o != "200")
    both_bad = sum(1 for i, o, _, _ in rows if i != "200" and o != "200")
    print("\n" + "─" * 64)
    print(f"נכשלו: פנימי {inner_bad}/{len(rows)}  ·  חיצוני {outer_bad}/{len(rows)}"
          f"  ·  שניהם {both_bad}")
    print("\nמסקנה:")
    if not inner_bad and not outer_bad:
        print("  הכל עבר. אם זה קרה בייצור — זה תלוי-עומס:")
        print("  הרץ שוב עם  --concurrency 4  --items 20")
    elif both_bad and both_bad == outer_bad:
        print("  נופל כבר באפליקציה עצמה, לפני nginx. החשוד הוא הנתיב")
        print("  שמושך את הקובץ מטלגרם (בריכת הבוטים), לא השרת שמגיש.")
        print("  הצעד הבא:  journalctl -u zovex-bot --since -10min | tail -60")
    elif outer_bad and not inner_bad:
        print("  האפליקציה עונה, והנפילה קורית בדרך החוצה — nginx או TLS.")
        print("  הצעד הבא:  tail -40 /var/log/nginx/error.log")
    else:
        print("  תמונה מעורבת. שלח לי את הפלט כמו שהוא.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
