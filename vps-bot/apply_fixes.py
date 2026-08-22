#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מריצים על השרת. מתקן *רק* שלושה שדות: custom_slug, thumbnail_url, description.
מזהה לפי id, מגבה לפני, ולא נוגע בשום שדה אחר ובשום פריט שלא ברשימת התיקון.

שימוש:  python3 apply_fixes.py   |   DATA_DIR=/path python3 apply_fixes.py
"""
import json, os, time
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/opt/zovex-bot/data"))
CONTENT  = DATA_DIR / "content.json"
VERSION  = DATA_DIR / "content_version.txt"
BAK_DIR  = DATA_DIR / "content_backups"
PATCH    = Path(__file__).parent / "full_patch.json"

ALLOWED_FIELDS = {"custom_slug", "thumbnail_url", "description"}

def main():
    if not CONTENT.exists():
        raise SystemExit(f"❌ לא נמצא {CONTENT} — קבע DATA_DIR נכון")
    patch = json.loads(PATCH.read_text(encoding="utf-8"))
    items = json.loads(CONTENT.read_text(encoding="utf-8"))

    for pid, fields in patch.items():
        bad = set(fields) - ALLOWED_FIELDS
        if bad:
            raise SystemExit(f"❌ שדה לא מורשה {bad} עבור {pid} — עצירה")

    BAK_DIR.mkdir(parents=True, exist_ok=True)
    bak = BAK_DIR / f"content_{int(time.time())}_prefix3.json"
    bak.write_text(CONTENT.read_text(encoding="utf-8"), encoding="utf-8")

    n = {"custom_slug": 0, "thumbnail_url": 0, "description": 0}
    seen = set()
    for it in items:
        i = it.get("id")
        if i in patch:
            for k, v in patch[i].items():
                it[k] = v; n[k] += 1
            seen.add(i)
    missing = [i for i in patch if i not in seen]

    CONTENT.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        cur = int(VERSION.read_text(encoding="utf-8").strip())
    except Exception:
        cur = 0
    VERSION.write_text(str(cur + 1), encoding="utf-8")

    print(f"✅ תיאורים: {n['description']} | פוסטרים: {n['thumbnail_url']} | סלאגים: {n['custom_slug']}")
    print(f"   פריטים סה\"כ {len(items)} | גרסה {cur}→{cur+1} | גיבוי: {bak.name}")
    if missing:
        print(f"⚠️ {len(missing)} מזהים לא נמצאו (אולי נמחקו): {missing[:6]}...")

if __name__ == "__main__":
    main()
