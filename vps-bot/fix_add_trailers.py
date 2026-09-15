#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מוסיף נקודת קצה /content/trailer/{id} שמחזירה מפתח טריילר מיוטיוב.

למה בשרת ולא באפליקציה: מפתח ה-TMDB חייב להישאר בשרת. אפליקציה שמחזיקה
אותו חושפת אותו לכל מי שפותח את ה-APK.

המטמון ממופתח לפי tmdb_id ולא לפי מזהה פריט — כל 72 הפרקים של סדרה
חולקים את אותו טריילר, וכך 8,479 פרקים עולים 118 קריאות בלבד.

יש גם מטמון שלילי: פריט שאין לו טריילר נרשם ככזה, אחרת כל פתיחה של אותו
סרט הייתה שולחת שוב בקשה ל-TMDB ומחזירה שוב כלום. נבדק מחדש כל שבועיים,
כי טריילר יכול להתווסף מאוחר.

    python3 fix_add_trailers.py --check
    python3 fix_add_trailers.py
    python3 fix_add_trailers.py --revert
"""
import argparse, datetime, glob, os, pathlib, shutil, sys

TARGET = pathlib.Path(os.environ.get("BOT_PY", "/opt/zovex-bot/main.py"))
MARK = "/content/trailer/"

ANCHOR = '@api.get("/content/item/{item_id}")'

BLOCK = '''# ── טריילרים ─────────────────────────────────────────────────────────────────
# מפתח יוטיוב לכל פריט שיש לו tmdb_id. המטמון ממופתח לפי ("movie"|"tv", tmdb_id)
# ולא לפי מזהה הפריט, כי כל פרקי הסדרה חולקים טריילר אחד.

TRAILERS_FILE = DATA_DIR / "trailers.json"
TRAILER_MISS_TTL = 14 * 24 * 3600      # בדיקה חוזרת לפריט בלי טריילר

def _load_trailers() -> dict:
    try:
        return json.loads(TRAILERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_trailers(db: dict) -> None:
    try:
        TRAILERS_FILE.write_text(json.dumps(db, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log.warning("שמירת trailers.json נכשלה: %s", e)

def _pick_trailer(results: list):
    """הטוב ביותר מבין הסרטונים: טריילר רשמי, אחר כך טריילר, אחר כך טיזר.
    רק יוטיוב — ה-CDN של TMDB עצמו לא מגיש וידאו, וספקים אחרים לא ניתנים
    להטמעה אצלנו."""
    yt = [v for v in results if (v.get("site") or "").lower() == "youtube" and v.get("key")]
    for want_official in (True, False):
        for want_type in ("Trailer", "Teaser", "Clip"):
            for v in yt:
                if v.get("type") == want_type and bool(v.get("official")) == want_official:
                    return v
    return yt[0] if yt else None


@api.get("/content/trailer/{item_id}")
async def content_trailer(item_id: str):
    item = next((m for m in load_content() if str(m.get("id")) == str(item_id)), None)
    if not item:
        return JSONResponse({"key": None, "reason": "no_item"})
    tid = item.get("tmdb_id")
    if not tid or not TMDB_API_KEY:
        return JSONResponse({"key": None, "reason": "no_tmdb_id"})
    kind = "tv" if item.get("series_name") else "movie"
    ck = f"{kind}:{tid}"

    db = _load_trailers()
    hit = db.get(ck)
    if hit and (hit.get("key") or (time.time() - hit.get("at", 0)) < TRAILER_MISS_TTL):
        return JSONResponse({"key": hit.get("key"), "cached": True},
                            headers={"Cache-Control": "public, max-age=86400"})

    best = None
    try:
        async with httpx.AsyncClient(timeout=12) as cx:
            # עברית קודם (יש תוכן עם טריילר מדובב), ואם אין — אנגלית.
            for lang in ("he", "en-US"):
                r = await cx.get(f"https://api.themoviedb.org/3/{kind}/{tid}/videos",
                                 params={"api_key": TMDB_API_KEY, "language": lang})
                if r.status_code != 200:
                    continue
                best = _pick_trailer(r.json().get("results") or [])
                if best:
                    break
    except Exception as e:
        log.info("trailer: שגיאה ב-TMDB עבור %s: %s", ck, e)
        # לא נרשם למטמון: תקלת רשת אינה "אין טריילר".
        return JSONResponse({"key": None, "reason": "tmdb_error"})

    key = best.get("key") if best else None
    db[ck] = {"key": key, "at": time.time()}
    _save_trailers(db)
    return JSONResponse({"key": key}, headers={"Cache-Control": "public, max-age=86400"})


'''


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
        baks = sorted(glob.glob(str(TARGET) + ".bak-trailers-*"))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], TARGET)
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}\n   צריך: systemctl restart zovex-bot")
        return

    src = TARGET.read_text(encoding="utf-8")
    if MARK in src:
        print("✓ הטריילרים כבר קיימים. לא שונה כלום.")
        return
    if src.count(ANCHOR) != 1:
        _fail(f"נמצאו {src.count(ANCHOR)} עוגנים, ציפינו ל-1.")

    out = src.replace(ANCHOR, BLOCK + ANCHOR)
    try:
        compile(out, str(TARGET), "exec")
    except SyntaxError as e:
        _fail(f"לא עובר קומפילציה: {e}")

    # compile() בודק תחביר בלבד. הבלוק מסתמך על שמות שמוגדרים למעלה בקובץ,
    # ושם חסר מפיל את השירות רק בזמן הייבוא — כלומר האתר כולו יורד.
    for n in ("httpx", "json", "time", "log", "DATA_DIR", "TMDB_API_KEY",
              "load_content", "JSONResponse"):
        if n not in src:
            _fail(f"main.py חסר {n} — הבלוק היה נופל בזמן ריצה.")

    if a.check:
        print("✓ העוגן מתאים, הקומפילציה עוברת, וכל השמות קיימים. לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-trailers-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print(f"✓ הוחל. גיבוי: {os.path.basename(bak)}")
    print("   צריך: systemctl restart zovex-bot")


if __name__ == "__main__":
    main()
