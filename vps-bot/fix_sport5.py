#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_sport5.py — מסדר את כל משפחת ספורט 5 מהספק שאומת בפריימים.

כל הכתובות כאן זוהו ויזואלית: נמשך פריים מכל ערוץ והלוגו בפינה
אישר מי הוא. אין כאן ניחוש לפי מספר.

מה מתוקן:
  ספורט 5        → :86/live/120  (המקור שאומת ידנית עם שמע תקין)
  ספורט 5 גולד   → s/124         (הכתובת הקודמת נשברה בגלל
                                  ?utm_source=chatgpt שנדבק בהעתקה —
                                  זו הסיבה ל-TimeoutError בבדיקה)
  ספורט 5 סטארס  → s/123
  ספורט 5 לייב   → s/122
מה נוסף:
  ספורט 5 מקס    → s/102
  ספורט 5 פלוס   → s/121

    python3 fix_sport5.py --check     # מראה, לא נוגע
    python3 fix_sport5.py
    python3 fix_sport5.py --revert
"""
import argparse, json, os, sys, shutil, time, uuid
from datetime import datetime
from pathlib import Path

DATA = Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
VERSION = DATA / "content_version.txt"
BACKUP = CONTENT.with_name("content.json.bak_sport5")
# הקטלוג שומר %BASE% ולא דומיין מלא — main.py:3115 מחליף אותו ב-
# STREAM_PUBLIC_BASE בזמן ההגשה. כתיבת דומיין קשיח הייתה עובדת היום
# ונשברת ביום שהדומיין משתנה, בעוד שאר הקטלוג מתעדכן לבד.
BASE = "%BASE%"

# הפורמט :7070/playlist.m3u8 מוגש ישירות, בלי _fix — כך כבר עובדים
# אצלך ספורט 6 (s/103) וספורט 2 (s/118) מאותו שער בדיוק.
G7 = "tv.embyil.tv:7070/p/embyil/s/{n}/playlist.m3u8"
G86 = "tv.embyil.tv:86/live/{n}/chunks.m3u8"


def url(tmpl: str, n: int) -> str:
    return f"{BASE}/hls-relay/" + tmpl.format(n=n)


# (שם בקטלוג, כתובת חדשה)
UPDATE = [
    ("ספורט 5",       url(G86, 120)),
    ("ספורט 5 גולד",  url(G7, 124)),
    ("ספורט 5 סטארס", url(G7, 123)),
    ("ספורט 5 לייב",  url(G7, 122)),
]
ADD = [
    ("ספורט 5 מקס",  url(G7, 102)),
    ("ספורט 5 פלוס", url(G7, 121)),
]
TEMPLATE_FROM = "ספורט 6"      # ערוץ עובד מאותו שער — משמש כתבנית


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


def main() -> None:
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
        sys.exit(f"לא נמצא: {CONTENT}")
    items = json.loads(CONTENT.read_text(encoding="utf-8"))
    by_title = {}
    for i in items:
        t = (i.get("title") or "").strip()
        by_title.setdefault(t, i)

    tmpl = by_title.get(TEMPLATE_FROM)
    if tmpl is None:
        sys.exit(f"✗ לא מצאתי את {TEMPLATE_FROM!r} לשמש כתבנית לערוצים חדשים")

    print(f"קטלוג: {len(items)} פריטים\n")
    changes, adds, missing = [], [], []

    for title, new_url in UPDATE:
        it = by_title.get(title)
        if it is None:
            missing.append(title)
            continue
        old = it.get("video_url") or ""
        if old != new_url:
            changes.append((it, title, old, new_url))

    for title, new_url in ADD:
        if title in by_title:
            it = by_title[title]
            if (it.get("video_url") or "") != new_url:
                changes.append((it, title, it.get("video_url") or "", new_url))
        else:
            adds.append((title, new_url))

    print("=" * 68)
    if changes:
        print(f"מתעדכנים: {len(changes)}")
        for _, t, old, new in changes:
            print(f"\n  {t}")
            print(f"     מ:  {old[-72:] if old else '(ריק)'}")
            print(f"     ל:  {new[-72:]}")
            if "utm_source" in old:
                print("     ← הכתובת הקודמת הכילה ?utm_source — זו הייתה התקלה")
    if adds:
        print(f"\nנוספים: {len(adds)}")
        for t, u in adds:
            print(f"  {t:<16} {u[-62:]}")
    if missing:
        print(f"\n⚠ לא נמצאו בקטלוג (לא ייווצרו): {', '.join(missing)}")
    print("=" * 68)

    if not changes and not adds:
        print("אין מה לשנות — הכול כבר מעודכן.")
        return

    if a.check:
        print("\n--check: שום דבר לא נכתב.")
        return

    shutil.copy2(CONTENT, BACKUP)
    for it, _, _, new in changes:
        it["video_url"] = new
    now = datetime.utcnow().isoformat()
    for title, new_url in adds:
        e = dict(tmpl)                       # מעתיקים ערוץ עובד כדי שכל
        e["id"] = f"live_{uuid.uuid4()}"     # השדות הנדרשים יהיו קיימים
        e["title"] = title
        e["video_url"] = new_url
        e.pop("custom_slug", None)
        # שדות שחייבים להתאפס: בלעדיהם הערוץ החדש יורש את הלוגו של
        # התבנית, ו-video_id שלה משמש בקוד כנפילה-אחורה ל-video_url.
        e["thumbnail_url"] = ""
        e.pop("video_id", None)
        e.pop("tmdb_id", None)
        e["created_date"] = now + "Z"
        e["added_at"] = now
        items.append(e)

    atomic_write(CONTENT, json.dumps(items, ensure_ascii=False, indent=2))
    try:
        v = int(VERSION.read_text().strip()) + 1 if VERSION.exists() else 1
    except Exception:
        v = int(time.time())
    atomic_write(VERSION, str(v))

    print(f"\n✓ עודכנו {len(changes)} · נוספו {len(adds)}")
    print(f"  גיבוי: {BACKUP}")
    print(f"  content_version → {v}")
    print("  האתר והאפליקציה ירעננו לבד — בלי restart, בלי לנתק צופים.")


if __name__ == "__main__":
    main()
