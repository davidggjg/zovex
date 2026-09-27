#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_opengop_route — שלושת הערוצים שנשארו, אל מסלול ההמרה.

## מה נמדד

מנתח ה-bitstream (‎h264_analyze.py‎) סרק את כל 105 ערוצי השידור החי
ומצא עשרה שהמקור שלהם open-GOP — אפס IDR, פריימי I עם recovery point
SEI, ו-‎frame_mbs_only=0‎ (קידוד שדות). MSE, שעליו רץ Shaka בכל דפדפן,
מחייב IDR כדי להתחיל, ולכן הם נתקעים על 0:00 **בלי לזרוק שגיאה**.

שבעה מהם כבר עוברים דרך ‎/hls-relay/_fix/‎, ואחרי ‎fix_verify_output‎ הם
תוקנו מעצמם: ‎_fix‎ סורק את הפלט שהוא ייצר, מוצא אפס IDR, זורק את
פרופיל ההעתקה ועובר לקידוד מלא.

אומת בפועל על ספורט 5 פלוס דרך ‎_fix‎ אחרי הפאץ':

    slices=2000 · IDR=30 · frame_mbs_only=1 · 1280x720 · profile=Main

כלומר לא רק נקודות כניסה — הזרם גם הפך פרוגרסיבי.

שלושה נשארו על המסלול הרגיל, ולכן ההמרה לא חלה עליהם:

    Hotril · HOTGOLD · 5plus

הסקריפט הזה מעביר את שלושתם, ואת שלושתם בלבד, אל ‎_fix‎.

## למה בקטלוג ולא בקוד

ההפניה האוטומטית (‎fix_live_autofix‎) נועדה לעשות את זה לבד, והיא אינה
נורית — ‎_hls_no_idr‎ מחזירה False בשרת מסיבה שלא הצלחתי לקבוע.
שינוי הכתובת בקטלוג אינו תלוי בה בכלל, ולכן הוא עובד עכשיו. כשההפניה
תתוקן היא פשוט לא תצטרך לעשות כלום עבור שלושת אלה.

## מה הוא נוגע בו

* ‎data/content.json‎ בלבד, ורק בשדה ‎video_url‎ של שלושת הסלאגים.
* גיבוי מלא לפני כתיבה, וכתיבה אטומית.
* ‎content_version‎ מקודם, אחרת הלקוחות לא ימשכו את הקטלוג החדש.
* ‎--revert‎ מחזיר את הגיבוי.

**אינו** נוגע ב-main.py, בשירות, ב-EPG, בהיסטוריה או בכל שדה אחר.

## מה לצפות

הבקשה הראשונה לערוץ כזה יכולה לקחת זמן או להיכשל: ‎_fix‎ מנסה קודם
העתקה, מאמת, זורק, ומתחיל קידוד מלא — והכל בתוך בקשה אחת. נמדד: ניסיון
ראשון החזיר 302, והשני והשלישי 200 בתוך שניות. כלומר הצופה הראשון
עלול לראות כשלון ומי שינסה אחריו יקבל ערוץ מנגן. זה פחות טוב ממושלם
ואמור להשתפר, אבל הוא עדיף על ערוץ שלא מנגן בכלל.

    python3 fix_opengop_route.py --check
    python3 fix_opengop_route.py
    python3 fix_opengop_route.py --revert
"""
import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

DATA = Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
VERSION = DATA / "content_version.txt"
BACKUP = CONTENT.with_name("content.json.bak_opengop_route")

# נמדדו כ-open-GOP ונשארו על המסלול הרגיל. שלושה, ובמפורש — לא תבנית,
# כדי ששינוי בקטלוג לא יגרור ערוצים שלא נבדקו.
SLUGS = ["Hotril", "HOTGOLD", "5plus"]


def mask(u: str) -> str:
    u = re.sub(r"(/hls-relay/)(_fix/)?[^/\s]+", r"\1\2<ספק>", u)
    return re.sub(r"\b[A-Z0-9]{8,}\b", "<אסימון>", u)


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def to_fix(url: str):
    """מחזיר את הכתובת דרך _fix, או None אם אין מה לשנות."""
    p = urlparse(url)
    if not p.path.startswith("/hls-relay/"):
        return None
    if p.path.startswith("/hls-relay/_fix/"):
        return None                     # כבר שם
    new_path = p.path.replace("/hls-relay/", "/hls-relay/_fix/", 1)
    return url.replace(p.path, new_path, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    if a.revert:
        if not BACKUP.exists():
            sys.exit(f"אין גיבוי ב-{BACKUP}")
        shutil.copy2(BACKUP, CONTENT)
        print(f"✓ שוחזר מ-{BACKUP}")
        return
    if not CONTENT.exists():
        sys.exit(f"לא נמצא {CONTENT} — הרץ מהשרת.")

    items = json.loads(CONTENT.read_text(encoding="utf-8"))
    live = {i.get("custom_slug"): i for i in items if i.get("is_live")}

    plan, skip, missing = [], [], []
    for s in SLUGS:
        it = live.get(s)
        if it is None:
            missing.append(s)
            continue
        new = to_fix(it.get("video_url") or "")
        if new is None:
            skip.append(s)
        else:
            plan.append((it, s, it["video_url"], new))

    print("=" * 62)
    for _, s, old, new in plan:
        print(f"\n  {s}")
        print(f"     {mask(old)}")
        print(f"  →  {mask(new)}")
    if skip:
        print(f"\n  ● כבר דרך _fix, אין מה לשנות: {', '.join(skip)}")
    if missing:
        print(f"\n  ⚠ לא נמצאו בקטלוג: {', '.join(missing)}")
    print("\n" + "=" * 62)

    if not plan:
        print("אין מה לשנות.")
        return
    if a.check:
        print("--check: שום דבר לא נכתב.")
        return

    shutil.copy2(CONTENT, BACKUP)
    for it, _s, _old, new in plan:
        it["video_url"] = new
    atomic_write(CONTENT, json.dumps(items, ensure_ascii=False, indent=2))

    # בלי קידום הגרסה הלקוחות ימשיכו להגיש את הקטלוג הישן מהמטמון
    try:
        v = int(VERSION.read_text().strip()) + 1 if VERSION.exists() else 1
    except Exception:
        v = int(time.time())
    atomic_write(VERSION, str(v))

    print(f"✓ עודכנו {len(plan)} ערוצים · גיבוי: {BACKUP} · גרסה {v}")
    print()
    print("הבקשה הראשונה לכל אחד מהם עשויה לקחת זמן: _fix מנסה קודם")
    print("העתקה, מאמת, זורק ומתחיל קידוד מלא. הבקשה שאחריה מהירה.")
    print()
    print("לאמת שהפלט באמת נגיש בדפדפן:")
    print("  python3 h264_analyze.py 'https://zovex.duckdns.org/hls-relay/_fix/...'")
    print("  ומחפשים IDR גדול מאפס ו-frame_mbs_only=1")


if __name__ == "__main__":
    main()
