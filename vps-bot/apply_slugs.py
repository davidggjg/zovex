#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מריצים על השרת. מוסיף slug אנגלי (custom_slug) ל-228 סרטים שהיו בלי, לפי id.
בטוח: מזהה לפי id (לא לפי שם/גרסה), מגבה לפני, ומכווץ (bump) את גרסת התוכן כדי
לרענן את המטמון של /content. לא נוגע בשום פריט שלא ברשימת התיקון.

שימוש:
    python3 apply_slugs.py                # DATA_DIR ברירת מחדל /opt/zovex-bot/data
    DATA_DIR=/path python3 apply_slugs.py
"""
import json, os, time
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/opt/zovex-bot/data"))
CONTENT  = DATA_DIR / "content.json"
VERSION  = DATA_DIR / "content_version.txt"
BAK_DIR  = DATA_DIR / "content_backups"
PATCH    = Path(__file__).parent / "slug_patch.json"

def main():
    if not CONTENT.exists():
        raise SystemExit(f"❌ לא נמצא {CONTENT} — קבע DATA_DIR נכון")
    patch = json.loads(PATCH.read_text(encoding="utf-8"))          # {id: slug}
    items = json.loads(CONTENT.read_text(encoding="utf-8"))

    # גיבוי בטיחות
    BAK_DIR.mkdir(parents=True, exist_ok=True)
    bak = BAK_DIR / f"content_{int(time.time())}_preslug.json"
    bak.write_text(CONTENT.read_text(encoding="utf-8"), encoding="utf-8")

    applied = 0; missing = 0
    seen = set()
    for it in items:
        i = it.get("id")
        if i in patch:
            it["custom_slug"] = patch[i]
            applied += 1; seen.add(i)
    missing = [i for i in patch if i not in seen]

    # כתיבה חזרה באותו פורמט של save_content (indent=2, בלי escape ל-unicode)
    CONTENT.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    # bump גרסה כדי שהמטמון של /content יתרענן מיד (בלי restart)
    try:
        cur = int(VERSION.read_text(encoding="utf-8").strip())
    except Exception:
        cur = 0
    VERSION.write_text(str(cur + 1), encoding="utf-8")

    print(f"✅ הוחלו {applied} slugים | פריטים סה\"כ {len(items)} | גרסה {cur} → {cur+1}")
    print(f"   גיבוי: {bak}")
    if missing:
        print(f"⚠️ {len(missing)} מזהים בתיקון לא נמצאו בתוכן (אולי נמחקו): {missing[:10]}...")

if __name__ == "__main__":
    main()
