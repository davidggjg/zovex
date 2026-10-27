#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# סורק העשרה: תיאורים, פוסטרים, וסיווג קטגוריות.
#
# ## מה הוא עושה
#
# עובר על הקטלוג לאט, יחידה-יחידה (סרט = יחידה, סדרה שלמה = יחידה אחת),
# ולכל אחת:
#
#   1. **תיאור חסר** — נמשך מ-TMDB. TMDB מחזיר תיאור עברי כשיש; כשאין,
#      התיאור האנגלי מתורגם דרך Groq. זה הפער שדווח: "יש מלא דברים
#      שהתיאורים שלהם באנגלית וזה לא מושך לי אותם".
#   2. **פוסטר חסר** — נמשך מ-TMDB.
#   3. **קטגוריה** — מחושבת מז'אנר ומוצא, ונשמרת כ**הצעה בלבד**.
#
# ## מה הוא לא עושה
#
# לא דורס שום שדה שכבר מלא. לא משנה קטגוריות בפועל. לא רץ מעצמו —
# רק כשמפעילים אותו מפורשות.
#
# ## הקטגוריות המוגנות
#
# נמדד על הקטלוג החי: 12 קטגוריות, ושלוש מהן אינן ז'אנר —
# ‎מארוול‎ (זיכיון, 54 סרטים), ‎שידורים חיים‎, ו-‎סדרות טורקיות‎/
# ‎סרטים ישראלים‎ (מוצא). סיווג לפי ז'אנר היה מרוקן אותן לתוך "סרטים".
# לכן הסורק נוגע **רק** בפריטים שיושבים בקטגוריות הגנריות, ומציע **רק**
# קטגוריות שכבר קיימות בקטלוג — הוא לא ממציא חדשות.
#
# ## ההרחבות למיפוי הקיים
#
# ‎_auto_category‎ מכירה IL רק לסדרות ולא מכירה TR בכלל. נוסף:
# מוצא TR → ‎סדרות טורקיות‎, ומוצא IL בסרט → ‎סרטים ישראלים‎.
#
#   python3 patch_enrich.py [נתיב ל-main.py]
#   python3 patch_enrich.py --revert
# ─────────────────────────────────────────────────────────────────────────────
import io
import os
import py_compile
import shutil
import sys
import time

P = "/opt/zovex-bot/main.py"
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if args:
    P = args[0]
REVERT = "--revert" in sys.argv
MARK = "enrich_scan"

ANCHOR = '''@api.get("/content/trailer/{item_id}")'''

BLOCK = r'''# ═══════════════════════════════════════════════════════════════════════════
# [enrich_scan] סורק העשרה — תיאורים, פוסטרים, והצעות קטגוריה
# ═══════════════════════════════════════════════════════════════════════════
#
# רץ רק כשמפעילים אותו. ממלא **רק שדות ריקים**, ואת הקטגוריות הוא רק
# מציע — שינוי של אלפי פריטים בשקט אינו הפיך בפועל.

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
# השהיה בין יחידות. ברירת המחדל איטית בכוונה: 23,107 פריטים הם ~3,340
# יחידות (סדרה נספרת פעם אחת), ובשתי שניות ליחידה זה כשעתיים — בלי להעמיס
# על השרת ובלי להתקרב למגבלות של TMDB.
ENRICH_DELAY = float(os.environ.get("ENRICH_DELAY", "2.0"))
ENRICH_SAVE_EVERY = int(os.environ.get("ENRICH_SAVE_EVERY", "25"))
RECAT_FILE = DATA_DIR / "recat_suggestions.json"
ENRICH_STATE = {"running": False, "done": 0, "total": 0, "filled_desc": 0,
                "filled_poster": 0, "translated": 0, "suggestions": 0,
                "skipped_no_tmdb": 0, "errors": 0, "stop": False,
                "started": 0.0, "last": ""}

# קטגוריות שאינן ז'אנר. סיווג לפי ז'אנר היה מרוקן אותן לתוך "סרטים".
PROTECTED_CATS = {"מארוול", "שידורים חיים", "סדרות טורקיות",
                  "סרטים ישראלים", "סדרות ישראליות"}
# רק מכאן מותר להזיז. פריט בקטגוריה אחרת לא ייגע בו.
GENERIC_CATS = {"סרטים", "סדרות", "סרטים לילדים (מתאים גם למשפחה)",
                "סרטים לילדים", "סדרות לילדים", "אנימה", "אימה", ""}


async def _tmdb_details(tid, kind: str) -> dict:
    """פרטי פריט מ-TMDB: ז'אנרים, מוצא, שפה, תקציר ופוסטר.

    התקציר מבוקש קודם בעברית. TMDB מחזיר מחרוזת ריקה כשאין תרגום, ואז
    נמשך האנגלי — וזה מה שעובר תרגום אצלנו.
    """
    if not tid or not TMDB_API_KEY or kind not in ("movie", "tv"):
        return {}
    out = {}
    try:
        async with httpx.AsyncClient(timeout=20) as cx:
            r = await cx.get(f"https://api.themoviedb.org/3/{kind}/{tid}",
                             params={"api_key": TMDB_API_KEY, "language": "he-IL"})
            if r.status_code != 200:
                return {}
            d = r.json()
            out["overview_he"] = (d.get("overview") or "").strip()
            out["genre_ids"] = [g.get("id") for g in (d.get("genres") or [])]
            out["origin"] = d.get("origin_country") or (
                [d.get("original_language", "").upper()] if kind == "movie" else [])
            out["lang"] = d.get("original_language") or ""
            out["poster"] = d.get("poster_path") or ""
            out["backdrop"] = d.get("backdrop_path") or ""
            out["type"] = kind
            if not out["overview_he"]:
                r2 = await cx.get(f"https://api.themoviedb.org/3/{kind}/{tid}",
                                  params={"api_key": TMDB_API_KEY,
                                          "language": "en-US"})
                if r2.status_code == 200:
                    out["overview_en"] = (r2.json().get("overview") or "").strip()
    except Exception as e:
        log.warning("enrich: tmdb details %s/%s נכשל: %s", kind, tid, e)
    return out


async def _groq_translate(text: str) -> str:
    """מתרגם תקציר לעברית. מחזיר מחרוזת ריקה בכל כשל — ואז לא נכתב כלום.

    עדיף שדה ריק על תרגום שגוי: ריק אפשר למלא מחר, טקסט שגוי יושב באתר.
    """
    if not GROQ_API_KEY or not text:
        return ""
    try:
        async with httpx.AsyncClient(timeout=40) as cx:
            r = await cx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={"model": GROQ_MODEL, "temperature": 0.2,
                      "messages": [
                          {"role": "system",
                           "content": "אתה מתרגם תקצירי סרטים וסדרות לעברית. "
                                      "החזר אך ורק את התרגום, בלי הקדמה, בלי "
                                      "מרכאות ובלי הערות. שמור על אורך דומה."},
                          {"role": "user", "content": text[:1500]}]})
            if r.status_code != 200:
                log.warning("enrich: groq %s", r.status_code)
                return ""
            return (r.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        log.warning("enrich: groq נכשל: %s", e)
        return ""


def _suggest_category(det: dict, is_series: bool, existing: set) -> str:
    """קטגוריה מוצעת — רק אחת שכבר קיימת בקטלוג.

    ‎_auto_category‎ מכירה IL רק לסדרות ואינה מכירה TR. כאן מורחב לפי
    הקטגוריות שנמדדו בפועל בקטלוג.
    """
    origin = {str(x).upper() for x in (det.get("origin") or [])}
    lang = (det.get("lang") or "").lower()
    if is_series and ("TR" in origin or lang == "tr"):
        cand = "סדרות טורקיות"
    elif not is_series and ("IL" in origin or lang == "he"):
        cand = "סרטים ישראלים"
    else:
        cand = _auto_category({"genre_ids": det.get("genre_ids") or [],
                               "origin": list(origin), "lang": lang,
                               "type": "tv" if is_series else "movie"})
    return cand if cand in existing else ""


async def _enrich_loop():
    """[enrich_scan] הלולאה עצמה. יחידה = סרט, או סדרה שלמה."""
    st = ENRICH_STATE
    try:
        content = load_content()
        existing = {str(m.get("category") or "").strip()
                    for m in content if m.get("category")}
        units, seen = [], set()
        for m in content:
            if m.get("is_live"):
                continue
            sn = str(m.get("series_name") or "").strip()
            key = ("s", sn) if sn else ("m", m.get("id"))
            if key in seen:
                continue
            seen.add(key)
            units.append((key, m))
        st["total"] = len(units)
        sugg = load_json(RECAT_FILE) or {}
        changed = 0

        for idx, (key, rep) in enumerate(units):
            if st["stop"]:
                break
            st["done"] = idx + 1
            st["last"] = str(rep.get("series_name") or rep.get("title") or "")
            tid = rep.get("tmdb_id")
            if not tid:
                st["skipped_no_tmdb"] += 1
                await asyncio.sleep(0)
                continue
            is_series = key[0] == "s"
            det = await _tmdb_details(tid, "tv" if is_series else "movie")
            if not det:
                st["errors"] += 1
                await asyncio.sleep(ENRICH_DELAY)
                continue

            desc = det.get("overview_he") or ""
            if not desc and det.get("overview_en"):
                desc = await _groq_translate(det["overview_en"])
                if desc:
                    st["translated"] += 1
            poster = (TMDB_IMG + det["poster"]) if det.get("poster") else ""

            # כתיבה רק לשדות ריקים. סדרה — לכל פרקיה.
            for m in content:
                if is_series:
                    if str(m.get("series_name") or "").strip() != key[1]:
                        continue
                elif m.get("id") != key[1]:
                    continue
                if desc and not str(m.get("description") or "").strip():
                    m["description"] = desc
                    st["filled_desc"] += 1
                    changed += 1
                if poster and not str(m.get("thumbnail_url") or "").strip():
                    m["thumbnail_url"] = poster
                    st["filled_poster"] += 1
                    changed += 1

            cur = str(rep.get("category") or "").strip()
            if cur in GENERIC_CATS and cur not in PROTECTED_CATS:
                cand = _suggest_category(det, is_series, existing)
                if cand and cand != cur:
                    sugg[f"{key[0]}:{key[1]}"] = {
                        "kind": key[0], "name": st["last"], "from": cur,
                        "to": cand, "tmdb_id": tid}
                    st["suggestions"] = len(sugg)

            if changed >= ENRICH_SAVE_EVERY:
                save_content(content)
                save_json(RECAT_FILE, sugg)
                changed = 0
            await asyncio.sleep(ENRICH_DELAY)

        if changed:
            save_content(content)
        save_json(RECAT_FILE, sugg)
        log.info("enrich: הסתיים — %d תיאורים, %d פוסטרים, %d הצעות",
                 st["filled_desc"], st["filled_poster"], st["suggestions"])
    except Exception as e:
        log.exception("enrich: נפל: %s", e)
        st["errors"] += 1
    finally:
        st["running"] = False


@api.post("/panel/enrich/start")
async def panel_enrich_start(req: PoolPwReq, request: Request):
    check_panel_password(request, req.password)
    if ENRICH_STATE["running"]:
        return JSONResponse({"ok": False, "reason": "כבר רץ"})
    for k in ("done", "total", "filled_desc", "filled_poster", "translated",
              "suggestions", "skipped_no_tmdb", "errors"):
        ENRICH_STATE[k] = 0
    ENRICH_STATE.update(running=True, stop=False, started=time.time(), last="")
    asyncio.create_task(_enrich_loop())
    return JSONResponse({"ok": True})


@api.post("/panel/enrich/stop")
async def panel_enrich_stop(req: PoolPwReq, request: Request):
    check_panel_password(request, req.password)
    ENRICH_STATE["stop"] = True
    return JSONResponse({"ok": True})


@api.post("/panel/enrich/status")
async def panel_enrich_status(req: PoolPwReq, request: Request):
    check_panel_password(request, req.password)
    st = dict(ENRICH_STATE)
    st["groq"] = bool(GROQ_API_KEY)
    st["tmdb"] = bool(TMDB_API_KEY)
    el = time.time() - st["started"] if st["started"] else 0
    st["elapsed"] = int(el)
    if st["done"] and st["total"] and st["running"]:
        st["eta"] = int(el / st["done"] * (st["total"] - st["done"]))
    return JSONResponse(st)


@api.post("/panel/recat/list")
async def panel_recat_list(req: PoolPwReq, request: Request):
    check_panel_password(request, req.password)
    s = load_json(RECAT_FILE) or {}
    return JSONResponse({"count": len(s),
                         "items": sorted(s.values(),
                                         key=lambda x: (x["to"], x["name"]))})


@api.post("/panel/recat/apply")
async def panel_recat_apply(req: PoolPwReq, request: Request):
    """מחיל את ההצעות, ושומר יומן ביטול לפני כל שינוי."""
    check_panel_password(request, req.password)
    sugg = load_json(RECAT_FILE) or {}
    if not sugg:
        return JSONResponse({"ok": False, "reason": "אין הצעות"})
    content = load_content()
    undo, n = [], 0
    for m in content:
        sn = str(m.get("series_name") or "").strip()
        k = f"s:{sn}" if sn else f"m:{m.get('id')}"
        s = sugg.get(k)
        if not s:
            continue
        cur = str(m.get("category") or "").strip()
        if cur != s["from"]:
            continue          # השתנה בינתיים — לא דורסים
        undo.append({"id": m.get("id"), "category": cur})
        m["category"] = s["to"]
        n += 1
    save_json(DATA_DIR / "recat_undo.json", undo)
    save_content(content)
    save_json(RECAT_FILE, {})
    return JSONResponse({"ok": True, "changed": n, "undo_saved": len(undo)})


@api.post("/panel/recat/undo")
async def panel_recat_undo(req: PoolPwReq, request: Request):
    check_panel_password(request, req.password)
    undo = load_json(DATA_DIR / "recat_undo.json") or []
    if not undo:
        return JSONResponse({"ok": False, "reason": "אין מה לבטל"})
    by_id = {u["id"]: u["category"] for u in undo}
    content = load_content()
    n = 0
    for m in content:
        if m.get("id") in by_id:
            m["category"] = by_id[m["id"]]
            n += 1
    save_content(content)
    save_json(DATA_DIR / "recat_undo.json", [])
    return JSONResponse({"ok": True, "restored": n})


@api.get("/content/trailer/{item_id}")'''


def main():
    d = os.path.dirname(P) or "."
    if REVERT:
        bak = sorted((f for f in os.listdir(d)
                      if f.startswith("main_before_enrich_")), reverse=True)
        if not bak:
            sys.exit("❌ אין גיבוי לשחזר")
        shutil.copy(os.path.join(d, bak[0]), P)
        print(f"✓ שוחזר מ-{bak[0]}")
        return
    try:
        s = io.open(P, encoding="utf-8").read()
    except OSError as e:
        sys.exit(f"❌ לא נפתח {P}: {e}")
    if MARK in s:
        print("✓ כבר מתוקן — מדלג")
        return
    for need in ("def _auto_category", "TMDB_IMG", "def save_json",
                 "def load_json", "import httpx", "class PoolPwReq"):
        if need not in s:
            sys.exit(f"❌ לא נמצא '{need}' ב-main.py — לא נגעתי בכלום")
    if s.count(ANCHOR) != 1:
        sys.exit(f"❌ העוגן נמצא {s.count(ANCHOR)} פעמים. לא נגעתי בכלום.")
    bak = f"{d}/main_before_enrich_{time.strftime('%Y%m%d-%H%M%S')}.py"
    shutil.copy(P, bak)
    io.open(P, "w", encoding="utf-8").write(s.replace(ANCHOR, BLOCK, 1))
    try:
        py_compile.compile(P, doraise=True)
    except Exception as e:
        shutil.copy(bak, P)
        sys.exit(f"❌ לא עובר קומפילציה — שוחזר.\n   {e}")
    print(f"✓ הוחל. גיבוי: {bak}")
    print("  /panel/enrich/start|stop|status  ·  /panel/recat/list|apply|undo")


if __name__ == "__main__":
    main()
