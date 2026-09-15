#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tmdb_enrich — השלב שממלא בפועל תיאור, שם באנגלית, שנה וקטגוריה.

זה השלישי מתוך שלושה, והוא שסוגר את המעגל:

    1. tmdb_ai_match.py   מודל בוחר tmdb_id מתוך מועמדים אמיתיים
    2. tmdb_apply.py      כותב את ה-tmdb_id לקטלוג
    3. tmdb_enrich.py     ← כאן. מושך מ-TMDB ומשלים את השדות

למה זה נדרש בנפרד: tmdb_apply כותב **רק** את המזהה. בלי השלב הזה יש
בקטלוג מספר ואין תיאור. ומה שנמדד בקטלוג:

    description  חסר ברוב הפריטים
    en_title     1,190 מתוך 13,172   (9%)
    year         4,951                (37%)

הטריילרים דווקא לא צריכים שדה: השרת מגיש אותם ב-/content/trailer/<id>
ופותר אותם מה-tmdb_id בעצמו, כך שברגע שהמזהה קיים הטריילר עובד.

עיקרון: **שום דבר לא נדרס.** פריט שכבר יש לו תיאור נשאר איתו. --force
קיים למי שרוצה אחרת, והוא לא ברירת המחדל בכוונה.

יעילות: 215 פרקים של אותה סדרה שולחים בקשה אחת, לא 215. המטמון הוא לפי
(סוג, מזהה), ולכן העלות נמדדת בסדרות ולא בפרקים.

    python3 tmdb_enrich.py --check              # מה היה קורה
    python3 tmdb_enrich.py --limit 30 --check   # טעימה
    python3 tmdb_enrich.py
    python3 tmdb_enrich.py --revert

TMDB_API_KEY נקרא מהסביבה או מ-/opt/zovex-bot/.env.
"""
import argparse, json, os, shutil, sys, time
import urllib.parse, urllib.request
from collections import Counter
from pathlib import Path

TMDB = "https://api.themoviedb.org/3"
DATA = Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
VERSION = DATA / "content_version.txt"
BACKUP = CONTENT.with_name("content.json.bak_enrich")
ENV_PATHS = ["/opt/zovex-bot/.env", ".env"]

# ז'אנרים של TMDB → הקטגוריות שקיימות אצלנו בפועל. רק מה שחד-משמעי:
# קטגוריה שגויה גרועה מקטגוריה חסרה, ולכן מה שלא ברשימה לא נוגעים בו.
GENRE_CAT = {
    16: "אנימה",          # Animation — מצטלב עם שפת המקור, ראה למטה
    10751: "סרטים לילדים (מתאים גם למשפחה)",
    27: "אימה",
}


def load_key() -> str:
    v = os.environ.get("TMDB_API_KEY", "").strip()
    if v:
        return v
    for p in ENV_PATHS:
        try:
            for line in open(p, encoding="utf-8", errors="replace"):
                if line.strip().startswith("TMDB_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("'\"")
        except Exception:
            continue
    return ""


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True); raise


# Cloudflare יושב לפני Groq וחוסם את ה-User-Agent שברירת המחדל של urllib
# שולחת ("Python-urllib/3.x"). זה חוזר כ-403 עם "error code: 1010", שנראה
# כמו מפתח פסול אבל אינו: אותה בקשה בדיוק עם UA רגיל מחזירה 200. נמדד
# בשלושה ניסיונות — ברירת מחדל נכשלת, curl/8.5.0 ו-zovex-bot/1.0 עוברים.
UA = "zovex-bot/1.0"


def get(url: str, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch(key: str, kind: str, tid) -> dict:
    """פרטי פריט בשתי שפות. עברית לתיאור, אנגלית לשם ולנפילה-אחורה."""
    out = {}
    for lang, tag in (("he-IL", "he"), ("en-US", "en")):
        q = urllib.parse.urlencode({"api_key": key, "language": lang})
        try:
            out[tag] = get(f"{TMDB}/{kind}/{tid}?{q}")
        except Exception:
            out[tag] = {}
    return out


def plan_item(it: dict, d: dict, force: bool) -> dict:
    """מה היה משתנה בפריט הזה. לא כותב — רק מחשב."""
    he, en = d.get("he") or {}, d.get("en") or {}
    new = {}

    def put(field, val):
        if val in (None, "", 0):
            return
        cur = it.get(field)
        if force or cur in (None, "", 0):
            if str(cur) != str(val):
                new[field] = val

    # תיאור: עברית אם יש, אחרת אנגלית. TMDB מחזיר overview ריק כשאין
    # תרגום, ולכן הבדיקה היא על תוכן ולא על קיום המפתח.
    put("description", (he.get("overview") or "").strip()
        or (en.get("overview") or "").strip())
    put("en_title", (en.get("name") or en.get("title") or "").strip())
    date = (he.get("first_air_date") or he.get("release_date")
            or en.get("first_air_date") or en.get("release_date") or "")
    if date[:4].isdigit():
        put("year", date[:4])
    poster = he.get("poster_path") or en.get("poster_path")
    if poster:
        put("thumbnail_url", f"https://image.tmdb.org/t/p/w500{poster}")

    # קטגוריה רק כשהיא חד-משמעית, ורק אם אין. אנימציה נחשבת "אנימה" רק
    # כשמדובר בהפקה יפנית — אחרת דיסני היה נוחת באנימה.
    if not it.get("category") or force:
        gids = {g.get("id") for g in (en.get("genres") or he.get("genres") or [])}
        langs = {en.get("original_language"), he.get("original_language")}
        cat = None
        if 16 in gids:
            cat = "אנימה" if "ja" in langs else "סרטים לילדים (מתאים גם למשפחה)"
        else:
            for gid, c in GENRE_CAT.items():
                if gid in gids and gid != 16:
                    cat = c
                    break
        if cat:
            put("category", cat)
    return new


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="לדרוס גם ערכים קיימים (ברירת המחדל: לא)")
    ap.add_argument("--limit", type=int, default=0,
                    help="לעבד רק N יחידות (טעימה)")
    ap.add_argument("--sleep", type=float, default=0.06)
    a = ap.parse_args()

    if a.revert:
        if not BACKUP.exists():
            sys.exit(f"אין גיבוי ב-{BACKUP}")
        shutil.copy2(BACKUP, CONTENT)
        print(f"✓ שוחזר מ-{BACKUP}")
        return
    key = load_key()
    if not key:
        sys.exit("אין TMDB_API_KEY בסביבה או ב-/opt/zovex-bot/.env")
    if not CONTENT.exists():
        sys.exit(f"לא נמצא: {CONTENT}")

    items = json.loads(CONTENT.read_text(encoding="utf-8"))
    # קיבוץ לפי (סוג, מזהה) — סדרה שלמה היא בקשה אחת
    groups = {}
    for it in items:
        tid = it.get("tmdb_id")
        if not tid or it.get("is_live"):
            continue
        kind = "tv" if (it.get("series_name") or "").strip() else "movie"
        groups.setdefault((kind, str(tid)), []).append(it)

    keys = list(groups)
    if a.limit:
        keys = keys[:a.limit]
    print(f"קטלוג: {len(items)} פריטים · {len(groups)} יחידות עם tmdb_id")
    print(f"מעבד {len(keys)} יחידות · "
          f"{sum(len(groups[k]) for k in keys)} פריטים\n")

    changes, fields, failed = [], Counter(), 0
    t0 = time.time()
    for n, k in enumerate(keys, 1):
        kind, tid = k
        d = fetch(key, kind, tid)
        if not (d.get("he") or d.get("en")):
            failed += 1
        for it in groups[k]:
            new = plan_item(it, d, a.force)
            if new:
                changes.append((it, new))
                fields.update(new)
        print(f"\r  {n}/{len(keys)}".ljust(22), end="", flush=True)
        if a.sleep:
            time.sleep(a.sleep)
    print(f"\n\nלקח {time.time()-t0:.0f} שניות · {failed} יחידות לא נענו\n"
          + "=" * 62)

    if not changes:
        print("אין מה להשלים.")
        return
    print(f"\n{len(changes)} פריטים ישתנו. לפי שדה:")
    for f, c in fields.most_common():
        print(f"   {f:<16} {c:>6}")
    print("\nדוגמאות:")
    for it, new in changes[:6]:
        name = (it.get("series_name") or it.get("title") or "?").strip()
        bits = ", ".join(f"{f}={str(v)[:40]}" for f, v in new.items())
        print(f"   {name[:26]:<28} {bits[:92]}")

    print("\n" + "=" * 62)
    if a.check:
        print("--check: שום דבר לא נכתב.")
        return

    shutil.copy2(CONTENT, BACKUP)
    for it, new in changes:
        it.update(new)
    atomic_write(CONTENT, json.dumps(items, ensure_ascii=False, indent=2))
    try:
        v = int(VERSION.read_text().strip()) + 1 if VERSION.exists() else 1
    except Exception:
        v = int(time.time())
    atomic_write(VERSION, str(v))
    print(f"✓ עודכנו {len(changes)} פריטים · גיבוי: {BACKUP} · גרסה {v}")
    print("  בלי restart. הטריילרים יעבדו מעצמם דרך /content/trailer.")


if __name__ == "__main__":
    main()
