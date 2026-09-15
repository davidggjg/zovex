#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מוסיף שפה לתוכן עצמו: /content/item/{id}?lang=en מחזיר שם ותקציר באנגלית.

למה לא תרגום מכונה: ל-12,700 פריטים אין שום דרך סבירה לתרגם ידנית, ותרגום
אוטומטי של תקצירים נותן טקסט גרוע. TMDB כבר מחזיק את אותו סרט בעברית
ובאנגלית — זה תוכן רשמי, לא תרגום — וברגע שלפריט יש tmdb_id שתי הגרסאות
זמינות בחינם.

לכן זה תלוי ישירות בהשלמת ה-tmdb_id (tmdb_backfill.py): היום רק 435 פריטים
מזוהים, ולכן רק להם תהיה אנגלית. אחרי ההשלמה — לרובם.

המטמון ממופתח לפי (סוג, tmdb_id), כך שכל פרקי הסדרה חולקים ערך אחד.

    python3 fix_content_lang.py --check
    python3 fix_content_lang.py
    python3 fix_content_lang.py --revert
"""
import argparse, datetime, glob, os, pathlib, shutil, sys

TARGET = pathlib.Path(os.environ.get("BOT_PY", "/opt/zovex-bot/main.py"))
MARK = "_localized_fields"

ANCHOR = '''@api.get("/content/item/{item_id}")
async def content_item(item_id: str):
    """פריט בודד עם כל השדות — משמש למשיכת התיאור כשפותחים סרט/סדרה."""
    e = (await _items_by_id_async(get_content_version())).get(item_id)
    if e is None:
        raise HTTPException(404, "not found")
    return JSONResponse(e, headers={"Cache-Control": "public, max-age=300"})'''

BLOCK = '''# ── תוכן באנגלית ─────────────────────────────────────────────────────────────
# TMDB מחזיק את אותו סרט בכמה שפות. זה תוכן רשמי ולא תרגום מכונה, ולכן זו
# הדרך הנכונה לתת שם ותקציר באנגלית במקום לתרגם 12,700 תקצירים.
# תלוי ב-tmdb_id: פריט בלי מזהה יישאר בעברית.

LOCALE_EN_FILE = DATA_DIR / "locale_en.json"
LOCALE_MISS_TTL = 14 * 24 * 3600

def _load_locale_en() -> dict:
    try:
        return json.loads(LOCALE_EN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_locale_en(db: dict) -> None:
    try:
        LOCALE_EN_FILE.write_text(json.dumps(db, ensure_ascii=False), encoding="utf-8")
    except Exception as ex:
        log.warning("שמירת locale_en.json נכשלה: %s", ex)

async def _localized_fields(item: dict) -> dict:
    """{title, description} באנגלית, או {} כשאין. לא זורק לעולם: כשל כאן
    צריך להשאיר את הפריט בעברית, לא להפיל את פתיחת הסרט."""
    tid = item.get("tmdb_id")
    if not tid or not TMDB_API_KEY:
        return {}
    kind = "tv" if item.get("series_name") else "movie"
    ck = f"{kind}:{tid}"
    db = _load_locale_en()
    hit = db.get(ck)
    if hit and (hit.get("title") or hit.get("description")
                or (time.time() - hit.get("at", 0)) < LOCALE_MISS_TTL):
        return {k: v for k, v in hit.items() if k in ("title", "description") and v}
    try:
        async with httpx.AsyncClient(timeout=12) as cx:
            r = await cx.get(f"https://api.themoviedb.org/3/{kind}/{tid}",
                             params={"api_key": TMDB_API_KEY, "language": "en-US"})
            if r.status_code != 200:
                return {}
            j = r.json()
    except Exception as ex:
        log.info("locale_en: שגיאה עבור %s: %s", ck, ex)
        return {}          # תקלת רשת אינה "אין אנגלית" — לא נרשם למטמון
    out = {}
    ttl = (j.get("title") or j.get("name") or "").strip()
    ov = (j.get("overview") or "").strip()
    if ttl:
        out["title"] = ttl
    if ov:
        out["description"] = ov
    db[ck] = dict(out, at=time.time())
    _save_locale_en(db)
    return out


@api.get("/content/item/{item_id}")
async def content_item(item_id: str, lang: str = "he"):
    """פריט בודד עם כל השדות — משמש למשיכת התיאור כשפותחים סרט/סדרה.
    lang=en מחליף שם ותקציר בגרסה האנגלית של TMDB כשהיא קיימת."""
    e = (await _items_by_id_async(get_content_version())).get(item_id)
    if e is None:
        raise HTTPException(404, "not found")
    if lang == "en":
        # עותק ולא המקור: המילון הזה משותף לכל הבקשות, ושינוי במקום היה
        # מרעיל את הקטלוג באנגלית גם למי שביקש עברית.
        e = dict(e)
        loc = await _localized_fields(e)
        if loc.get("title"):
            e["title"] = loc["title"]
        elif (e.get("en_title") or "").strip():
            e["title"] = e["en_title"].strip()
        if loc.get("description"):
            e["description"] = loc["description"]
    return JSONResponse(e, headers={"Cache-Control": "public, max-age=300",
                                    "Vary": "Accept-Language"})'''


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
        baks = sorted(glob.glob(str(TARGET) + ".bak-lang-*"))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], TARGET)
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}\n   צריך: systemctl restart zovex-bot")
        return

    src = TARGET.read_text(encoding="utf-8")
    if MARK in src:
        print("✓ הלוקליזציה כבר קיימת. לא שונה כלום.")
        return
    if src.count(ANCHOR) != 1:
        _fail(f"נמצאו {src.count(ANCHOR)} עוגנים, ציפינו ל-1.")

    out = src.replace(ANCHOR, BLOCK)
    try:
        compile(out, str(TARGET), "exec")
    except SyntaxError as e:
        _fail(f"לא עובר קומפילציה: {e}")
    for n in ("httpx", "json", "time", "log", "DATA_DIR", "TMDB_API_KEY", "JSONResponse"):
        if n not in src:
            _fail(f"main.py חסר {n} — הבלוק היה נופל בזמן ריצה.")

    if a.check:
        print("✓ העוגן מתאים, הקומפילציה עוברת, וכל השמות קיימים. לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-lang-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print(f"✓ הוחל. גיבוי: {os.path.basename(bak)}")
    print("   צריך: systemctl restart zovex-bot")


if __name__ == "__main__":
    main()
