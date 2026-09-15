#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מוסיף לשרת מועדפים למשתמש — GET/POST/DELETE על /api/favorites.

למה בשרת ולא באפליקציה: מועדפים שנשמרים מקומית נעלמים בהתקנה מחדש ולא
עוברים בין מכשירים. יש כבר זהות משתמש (x-user-id) ו-history.json שעובד
בדיוק ככה, אז מועדפים נבנים באותו דפוס ובאותו מנגנון שמירה.

    python3 fix_add_favorites.py --check
    python3 fix_add_favorites.py
    python3 fix_add_favorites.py --revert
"""
import argparse, datetime, glob, os, pathlib, shutil, sys

TARGET = pathlib.Path(os.environ.get("BOT_PY", "/opt/zovex-bot/main.py"))
MARK = '/api/favorites'

A_FILE = 'HISTORY_FILE  = DATA_DIR / "history.json"\n'
B_FILE = ('HISTORY_FILE  = DATA_DIR / "history.json"\n'
          'FAVORITES_FILE = DATA_DIR / "favorites.json"\n')

A_HF = '        ("history.json", HISTORY_FILE),\n'
B_HF = ('        ("history.json", HISTORY_FILE),\n'
        '        ("favorites.json", FAVORITES_FILE),\n')

A_EP = "# ── Stream helpers ────────────────────────────────────────────────────────────"

B_EP = '''# ── מועדפים ──────────────────────────────────────────────────────────────────
# אותו מבנה כמו history.json: {user_id: [פריט, ...]}. הפריט נושא כותרת
# ותמונה כדי שמסך המועדפים יצייר מיד, בלי לחפש כל פריט בקטלוג המלא.

class FavoriteItem(BaseModel):
    media_id: str
    title: str = ""
    thumbnail_url: Optional[str] = ""


@api.get("/api/favorites")
async def get_favorites(x_user_id: str = Header(..., description="Google User ID")):
    db = load_json(FAVORITES_FILE)
    return db.get(x_user_id, [])


@api.post("/api/favorites")
async def add_favorite(item: FavoriteItem,
                       x_user_id: str = Header(..., description="Google User ID")):
    db = load_json(FAVORITES_FILE)
    lst = db.get(x_user_id) or []
    # הסרה לפני הוספה: לחיצה חוזרת מרעננת את הפריט במקום לשכפל אותו.
    lst = [f for f in lst if f.get("media_id") != item.media_id]
    lst.insert(0, {
        "media_id": item.media_id,
        "title": item.title or "",
        "thumbnail_url": item.thumbnail_url or "",
        "added_at": time.time(),
    })
    db[x_user_id] = lst[:500]
    save_json(FAVORITES_FILE, db, "favorites.json")
    return {"ok": True, "count": len(db[x_user_id])}


@api.delete("/api/favorites/{media_id}")
async def remove_favorite(media_id: str,
                          x_user_id: str = Header(..., description="Google User ID")):
    db = load_json(FAVORITES_FILE)
    lst = db.get(x_user_id) or []
    n = len(lst)
    db[x_user_id] = [f for f in lst if f.get("media_id") != media_id]
    if len(db[x_user_id]) != n:
        save_json(FAVORITES_FILE, db, "favorites.json")
    return {"ok": True, "removed": n - len(db[x_user_id])}


# ── Stream helpers ────────────────────────────────────────────────────────────'''


def _fail(m):
    print(f"❌ {m}"); sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    if not TARGET.exists():
        _fail(f"{TARGET} לא נמצא")

    if a.revert:
        baks = sorted(glob.glob(str(TARGET) + ".bak-favorites-*"))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], TARGET)
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}\n   צריך: systemctl restart zovex-bot")
        return

    src = TARGET.read_text(encoding="utf-8")
    if MARK in src:
        print("✓ המועדפים כבר קיימים. לא שונה כלום.")
        return
    for tok in ("HISTORY_FILE", "load_json", "save_json", "BaseModel", "Header", "Optional"):
        if tok not in src:
            _fail(f"main.py חסר {tok} — הקובץ לא מה שציפינו לו.")
    for name, anc in (("הגדרת הקובץ", A_FILE), ("נקודות הקצה", A_EP)):
        if src.count(anc) != 1:
            _fail(f"{name}: נמצאו {src.count(anc)} עוגנים, ציפינו ל-1.")

    out = src.replace(A_FILE, B_FILE).replace(A_EP, B_EP)
    # גיבוי ל-HuggingFace קיים רק אם הוגדר; אם העוגן לא שם, מדלגים בשקט.
    if out.count(A_HF) == 1:
        out = out.replace(A_HF, B_HF)
        print("  ✓ נוסף גם לרשימת הגיבוי ל-Dataset")

    try:
        compile(out, str(TARGET), "exec")
    except SyntaxError as e:
        _fail(f"לא עובר קומפילציה: {e}")

    # compile() בודק תחביר בלבד ולא פתירת שמות. הבלוק המוזרק מסתמך על שמות
    # שמוגדרים למעלה בקובץ — אם אחד מהם חסר, השירות ייפול רק בזמן הייבוא,
    # כלומר האתר כולו יורד. לכן בודקים כאן במפורש.
    missing = [n for n in ("time", "BaseModel", "Header", "Optional",
                           "load_json", "save_json", "api", "DATA_DIR")
               if f"\n{n} " not in out and f"import {n}" not in out
               and f"def {n}" not in out and f"class {n}" not in out
               and f", {n}" not in out and f"{n} =" not in out]
    if missing:
        _fail(f"שמות שהבלוק צריך ולא נמצאו בקובץ: {missing}")

    if a.check:
        print("✓ העוגנים מתאימים, הקומפילציה עוברת, וכל השמות קיימים. לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-favorites-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print(f"✓ הוחל. גיבוי: {os.path.basename(bak)}")
    print("   צריך: systemctl restart zovex-bot")


if __name__ == "__main__":
    main()
