#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
טריילר ידני: שדה trailer_url על הפריט, ורשימת מה שחסר לפאנל.

למה צריך: הטריילר האוטומטי תלוי ב-tmdb_id, ולתוכן ישראלי רבות אין טריילר
ב-TMDB גם כשהמזהה קיים. קישור ידני פותר כל מקרה כזה מיד, בלי להמתין
להשלמה ובלי להיות תלוי בצד שלישי.

שתי תוספות:
  • /content/trailer/{id} מעדיף trailer_url של הפריט על פני TMDB. ידני
    תמיד גובר — אם מישהו טרח להזין קישור, הוא יודע טוב יותר.
  • /panel/no-trailer מחזיר את מה שאין לו טריילר, כדי שיהיה מה לערוך.
    הסדרות מקובצות לפי שם: אין טעם ברשימה של 424 פרקים לאותה סדרה.

    python3 fix_manual_trailer.py --check
    python3 fix_manual_trailer.py
    python3 fix_manual_trailer.py --revert
"""
import argparse, datetime, glob, os, pathlib, shutil, sys

TARGET = pathlib.Path(os.environ.get("BOT_PY", "/opt/zovex-bot/main.py"))
MARK = "no-trailer"

A_PICK = '''@api.get("/content/trailer/{item_id}")
async def content_trailer(item_id: str):
    item = next((m for m in load_content() if str(m.get("id")) == str(item_id)), None)
    if not item:
        return JSONResponse({"key": None, "reason": "no_item"})
    tid = item.get("tmdb_id")'''

B_PICK = '''_YT_RE = re.compile(
    r"(?:youtu\\.be/|youtube(?:-nocookie)?\\.com/(?:watch\\?v=|embed/|shorts/|v/))"
    r"([A-Za-z0-9_-]{6,})")

def _yt_key(url: str):
    """מפתח יוטיוב מתוך קישור בכל צורה, או None. מקבל גם מפתח חשוף, כדי
    שהדבקה של המזהה בלבד תעבוד ולא תיראה כמו תקלה."""
    u = (url or "").strip()
    if not u:
        return None
    m = _YT_RE.search(u)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{8,}", u):
        return u
    return None


def _has_trailer(item: dict, tdb: dict) -> bool:
    """האם לפריט יש טריילר — ידני או כזה שכבר נמצא ונשמר במטמון."""
    if _yt_key(item.get("trailer_url")):
        return True
    tid = item.get("tmdb_id")
    if not tid:
        return False
    kind = "tv" if item.get("series_name") else "movie"
    hit = tdb.get(f"{kind}:{tid}")
    return bool(hit and hit.get("key"))


@api.get("/panel/no-trailer")
async def panel_no_trailer(request: Request, password: str = ""):
    """מה שאין לו טריילר. סדרות מקובצות לפי שם — רשימה של 424 פרקים לאותה
    סדרה אינה רשימת עבודה, היא רעש."""
    check_panel_password(request, password)
    tdb = _load_trailers()
    movies, series = [], {}
    for m in load_content():
        if m.get("is_live") or _has_trailer(m, tdb):
            continue
        sn = (m.get("series_name") or "").strip()
        if sn:
            e = series.setdefault(sn, {"series_name": sn, "id": m.get("id"),
                                       "category": m.get("category"),
                                       "tmdb_id": m.get("tmdb_id"), "episodes": 0,
                                       "thumbnail_url": m.get("thumbnail_url")})
            e["episodes"] += 1
        else:
            movies.append({"id": m.get("id"), "title": m.get("title"),
                           "year": m.get("year"), "category": m.get("category"),
                           "tmdb_id": m.get("tmdb_id"),
                           "thumbnail_url": m.get("thumbnail_url")})
    movies.sort(key=lambda x: str(x.get("title") or ""))
    ser = sorted(series.values(), key=lambda x: -x["episodes"])
    return JSONResponse({"movies": movies, "series": ser,
                         "counts": {"movies": len(movies), "series": len(ser)}})


@api.get("/content/trailer/{item_id}")
async def content_trailer(item_id: str):
    item = next((m for m in load_content() if str(m.get("id")) == str(item_id)), None)
    if not item:
        return JSONResponse({"key": None, "reason": "no_item"})
    # ידני גובר על TMDB: מי שהזין קישור בפאנל יודע טוב יותר מהתאמה אוטומטית,
    # וזו גם הדרך היחידה לתת טריילר לפריט שאין לו tmdb_id בכלל.
    manual = _yt_key(item.get("trailer_url"))
    if manual:
        return JSONResponse({"key": manual, "manual": True},
                            headers={"Cache-Control": "public, max-age=3600"})
    tid = item.get("tmdb_id")'''


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
        baks = sorted(glob.glob(str(TARGET) + ".bak-mtrailer-*"))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], TARGET)
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}\n   צריך: systemctl restart zovex-bot")
        return

    src = TARGET.read_text(encoding="utf-8")
    if MARK in src:
        print("✓ כבר מוחל. לא שונה כלום.")
        return
    if "_load_trailers" not in src:
        _fail("fix_add_trailers.py עוד לא הוחל — צריך אותו קודם.")
    if src.count(A_PICK) != 1:
        _fail(f"נמצאו {src.count(A_PICK)} עוגנים, ציפינו ל-1.")

    out = src.replace(A_PICK, B_PICK)
    try:
        compile(out, str(TARGET), "exec")
    except SyntaxError as e:
        _fail(f"לא עובר קומפילציה: {e}")
    for n in ("import re", "check_panel_password", "load_content", "JSONResponse", "Request"):
        if n.replace("import ", "") not in src:
            _fail(f"main.py חסר {n}")

    if a.check:
        print("✓ העוגן מתאים, הקומפילציה עוברת, וכל השמות קיימים. לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-mtrailer-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print(f"✓ הוחל. גיבוי: {os.path.basename(bak)}")
    print("   צריך: systemctl restart zovex-bot")


if __name__ == "__main__":
    main()
