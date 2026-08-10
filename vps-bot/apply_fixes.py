#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מריצים על השרת. מתקן *רק* שני שדות: custom_slug (2 סרטים בלי slug אנגלי)
ו-thumbnail_url (189 פריטים בלי פוסטר). מזהה לפי id, מגבה לפני, לא נוגע בשום
שדה אחר ובשום פריט שלא ברשימת התיקון.

שימוש:  python3 apply_fixes.py
        DATA_DIR=/path python3 apply_fixes.py
"""
import json, os, time
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/opt/zovex-bot/data"))
CONTENT  = DATA_DIR / "content.json"
VERSION  = DATA_DIR / "content_version.txt"
BAK_DIR  = DATA_DIR / "content_backups"
PATCH    = Path(__file__).parent / "poster_slug_patch.json"

ALLOWED_FIELDS = {"custom_slug", "thumbnail_url"}   # נגיעה מותרת רק בשניים האלה

def main():
    if not CONTENT.exists():
        raise SystemExit(f"❌ לא נמצא {CONTENT} — קבע DATA_DIR נכון")
    patch = json.loads(PATCH.read_text(encoding="utf-8"))
    items = json.loads(CONTENT.read_text(encoding="utf-8"))

    # הגנה: הפאץ' מכיל רק את השדות המותרים
    for pid, fields in patch.items():
        bad = set(fields) - ALLOWED_FIELDS
        if bad:
            raise SystemExit(f"❌ הפאץ' מכיל שדה לא מורשה {bad} עבור {pid} — עצירה")

    BAK_DIR.mkdir(parents=True, exist_ok=True)
    bak = BAK_DIR / f"content_{int(time.time())}_prefix.json"
    bak.write_text(CONTENT.read_text(encoding="utf-8"), encoding="utf-8")

    slug_n = poster_n = 0
    seen = set()
    for it in items:
        i = it.get("id")
        if i in patch:
            f = patch[i]
            if "custom_slug" in f:
                it["custom_slug"] = f["custom_slug"]; slug_n += 1
            if "thumbnail_url" in f:
                it["thumbnail_url"] = f["thumbnail_url"]; poster_n += 1
            seen.add(i)
    missing = [i for i in patch if i not in seen]

    CONTENT.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        cur = int(VERSION.read_text(encoding="utf-8").strip())
    except Exception:
        cur = 0
    VERSION.write_text(str(cur + 1), encoding="utf-8")

    print(f"✅ סלאגים: {slug_n} | פוסטרים: {poster_n} | פריטים סה\"כ {len(items)} | גרסה {cur}→{cur+1}")
    print(f"   גיבוי: {bak}")
    if missing:
        print(f"⚠️ {len(missing)} מזהים לא נמצאו בתוכן (אולי נמחקו): {missing[:6]}...")

if __name__ == "__main__":
    main()
