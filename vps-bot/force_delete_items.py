#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מוחק פריטים מ-content.json לפי מזהה — ישירות בשרת, כשמחיקה בפאנל לא נתפסה.

## למה זה נדרש

דוד ראה באפליקציה שני פריטים ("חנשי פרק 3", "חנשי פרק תשע") שהוא מחק בפאנל
וש"עדיין לא נמחקו". נמדד מול השרת: שניהם עדיין קיימים ב-content.json. כלומר
המחיקה בפאנל לא נשמרה — לא שהאפליקציה מחזיקה מטמון. לכן שום עדכון אפליקציה
לא יעלים אותם: השרת ממשיך להגיש אותם כי הם אמיתיים אצלו.

(למה המחיקה בפאנל לא נתפסה — לא ידוע בוודאות. שני חשודים: EDITOR_MAX_DELETE
או נעילת הגרסה האופטימית, ששניהם דוחים שמירה בשקט יחסי. הסקריפט הזה עוקף את
שניהם כי הוא כותב את הקובץ ישירות, אבל שומר על אותה בטיחות.)

## מה הוא עושה, בדיוק כמו save_content

  1. גיבוי מלא של content.json לתיקיית הגיבויים (לפני כל נגיעה).
  2. הסרת הפריטים שה-id שלהם ברשימה.
  3. כתיבה חזרה, ואז העלאת מונה הגרסה — כדי שהאפליקציה והאתר ירעננו מיד.
     בלי זה, השרת היה ממשיך להגיש את הגוף השמור מהמטמון עד שהמונה זז.

השרת קורא את content.json מחדש בכל בנייה (load_content), ולכן אפשר לכתוב
בזמן שהוא רץ — אין צורך להפעיל אותו מחדש. רק המונה חייב לזוז, וזה מה שהשלב
השלישי עושה.

    python3 force_delete_items.py --list חנשי           # רק מראה מה יימחק
    python3 force_delete_items.py --id adc088ca-... --id 8284d5d9-...
    python3 force_delete_items.py --id adc088ca-... --dry-run
"""
import argparse, json, os, pathlib, sys, time

DATA_DIR = pathlib.Path(os.environ.get("DATA_DIR", "/opt/zovex-bot/data"))
CONTENT_FILE = DATA_DIR / "content.json"
BAK_DIR = DATA_DIR / "content_backups"
VERSION_FILE = DATA_DIR / "content_version.txt"


def load():
    return json.loads(CONTENT_FILE.read_text(encoding="utf-8"))


def bump_version():
    try:
        cur = int(VERSION_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        cur = 0
    VERSION_FILE.write_text(str(cur + 1), encoding="utf-8")
    return cur + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", action="append", default=[],
                    help="מזהה פריט למחיקה. אפשר לחזור על הדגל.")
    ap.add_argument("--list", metavar="SUBSTR",
                    help="רק להציג פריטים שהכותרת שלהם מכילה את המחרוזת. לא מוחק.")
    ap.add_argument("--dry-run", action="store_true",
                    help="להראות מה היה נמחק, בלי לגעת בקובץ.")
    a = ap.parse_args()

    if not CONTENT_FILE.exists():
        print(f"❌ לא נמצא {CONTENT_FILE}")
        sys.exit(1)

    items = load()
    print(f"בקובץ כרגע: {len(items)} פריטים\n")

    # מצב תצוגה — לאיתור מזהים לפי שם
    if a.list:
        n = 0
        for e in items:
            title = (e.get("title") or "") + " " + (e.get("series_name") or "")
            if a.list in title:
                n += 1
                print(f"  id={e.get('id')}  {e.get('title')!r}  "
                      f"[{e.get('category')}]  פוסטר={'כן' if e.get('thumbnail_url') else 'לא'}")
        print(f"\n{n} התאמות. למחיקה: הוסף --id <המזהה> לכל אחד.")
        return

    if not a.id:
        print("לא צוין --id. דוגמה:")
        print("   python3 force_delete_items.py --list חנשי")
        print("   python3 force_delete_items.py --id adc088ca-... --id 8284d5d9-...")
        return

    wanted = set(a.id)
    matched = [e for e in items if str(e.get("id")) in wanted]
    found_ids = {str(e.get("id")) for e in matched}
    missing = wanted - found_ids

    if not matched:
        print("❌ אף אחד מהמזהים לא נמצא בקובץ. לא נוגעים בכלום.")
        for m in missing:
            print(f"   לא נמצא: {m}")
        sys.exit(1)

    print("יימחקו:")
    for e in matched:
        print(f"  ✗ id={e.get('id')}  {e.get('title')!r}  [{e.get('category')}]")
    if missing:
        print("\nלא נמצאו (מדולגים):")
        for m in missing:
            print(f"  · {m}")

    remaining = [e for e in items if str(e.get("id")) not in found_ids]
    assert len(remaining) == len(items) - len(matched)

    if a.dry_run:
        print(f"\n(dry-run) היו נשארים {len(remaining)} פריטים. לא נכתב כלום.")
        return

    # 1) גיבוי לפני נגיעה — בדיוק כמו save_content
    BAK_DIR.mkdir(parents=True, exist_ok=True)
    bak = BAK_DIR / f"content_{int(time.time())}.json"
    bak.write_text(CONTENT_FILE.read_text(encoding="utf-8"), encoding="utf-8")

    # 2) כתיבה
    CONTENT_FILE.write_text(json.dumps(remaining, ensure_ascii=False, indent=2),
                            encoding="utf-8")

    # 3) העלאת מונה הגרסה — כך המטמון בשרת נפסל והלקוחות מרעננים מיד
    v = bump_version()

    print(f"\n✓ נמחקו {len(matched)} פריטים. נשארו {len(remaining)}.")
    print(f"✓ גיבוי: {bak.name}")
    print(f"✓ גרסת תוכן חדשה: {v}")
    print("\nבדיקה:")
    print("   curl -s https://zovex.duckdns.org/content/version")
    print("אין צורך בהפעלה מחדש — השרת קורא את הקובץ מחדש לבד.")


if __name__ == "__main__":
    main()
