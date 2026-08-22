#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מריצים על השרת. מראה מה נמחק לאחרונה מהאתר, ע"י השוואת content.json הנוכחי
לגיבויים האוטומטיים (content_backups/). מזהה לפי id: פריט שהיה בגיבוי ואיננו
עכשיו = נמחק. בדיקה בלבד, לא משנה כלום.

שימוש:  python3 whats_deleted.py            # 40 המחיקות האחרונות
        python3 whats_deleted.py 200        # עד 200
        DATA_DIR=/path python3 whats_deleted.py
"""
import json, os, sys, time, re, glob
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/opt/zovex-bot/data"))
CONTENT  = DATA_DIR / "content.json"
BAK_DIR  = DATA_DIR / "content_backups"
LIMIT    = int(sys.argv[1]) if len(sys.argv) > 1 else 40

def load(p):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: return []

def ids_map(items):
    m = {}
    for x in items:
        i = x.get("id")
        if i: m[i] = x
    return m

def label(x):
    t = (x.get("title") or x.get("series_name") or "?").strip()
    y = x.get("year") or ""
    c = x.get("category") or ""
    return f"{t} ({y}) [{c}]"

def main():
    if not CONTENT.exists():
        raise SystemExit(f"❌ לא נמצא {CONTENT}")
    cur = ids_map(load(CONTENT))
    cur_ids = set(cur)

    # גיבויים לפי זמן (חדש→ישן). חילוץ חותמת הזמן משם הקובץ.
    baks = []
    for f in glob.glob(str(BAK_DIR / "content_*.json")):
        m = re.search(r"content_(\d+)", os.path.basename(f))
        if m: baks.append((int(m.group(1)), f))
    baks.sort(reverse=True)
    if not baks:
        raise SystemExit("אין גיבויים בתיקייה " + str(BAK_DIR))

    print(f"תוכן נוכחי: {len(cur_ids)} פריטים | {len(baks)} גיבויים "
          f"(מ-{time.strftime('%d/%m %H:%M', time.localtime(baks[-1][0]))} "
          f"עד {time.strftime('%d/%m %H:%M', time.localtime(baks[0][0]))})")
    print("=" * 60)

    # פריט נמחק = קיים בגיבוי כלשהו אך לא בנוכחי. מדווחים לפי הגיבוי האחרון
    # שבו נראה (כלומר בערך מתי נמחק), החל מהמחיקות הכי טריות.
    reported = set()
    shown = 0
    prev_ids = cur_ids
    for ts, f in baks:  # חדש→ישן
        bak = ids_map(load(f))
        # פריטים שהיו בגיבוי הזה ונעלמו עד הנוכחי, ושעדיין לא דווחו
        gone = [i for i in bak if i not in cur_ids and i not in reported]
        # מתוכם: אלה שנעלמו *אחרי* הגיבוי הזה (כלומר היו כאן, אין בנוכחי)
        if gone:
            when = time.strftime("%d/%m/%Y %H:%M", time.localtime(ts))
            for i in gone:
                if shown >= LIMIT: break
                print(f"🗑  נמחק אחרי {when}: {label(bak[i])}")
                reported.add(i); shown += 1
        if shown >= LIMIT:
            print(f"\n… (מוצגות {LIMIT} הראשונות; הרץ עם מספר גדול יותר לעוד)")
            break
    if not reported:
        print("✅ לא נמצאו מחיקות — כל הפריטים שבגיבויים קיימים גם עכשיו.")
    else:
        print("=" * 60)
        print(f"סה\"כ נמצאו {len(reported)} פריטים שנמחקו (בטווח הגיבויים).")
        print("לשחזור פריט: אפשר להעתיק אותו מקובץ הגיבוי הרלוונטי ב-" + str(BAK_DIR))

if __name__ == "__main__":
    main()
