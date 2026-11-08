#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · השלמת פוסטרים והעברת תוכן ישראלי לקטגוריה שלו, לפי TMDB.
#
# ברירת המחדל היא **הדמיה בלבד**. בלי ‎--apply‎ שום דבר לא נכתב.
#
#   python3 catalog_tmdb.py --posters            # הדמיה
#   python3 catalog_tmdb.py --israeli            # הדמיה
#   python3 catalog_tmdb.py --posters --israeli --apply
#   python3 catalog_tmdb.py --restore
#
# ## פוסטרים
#
# נמדד בקטלוג החי: 1,294 פריטים בלי פוסטר, ו-1,271 מהם פרקים של **37
# סדרות בלבד** — "טיטוף" לבדה היא 316 פרקים. לכן מחפשים כל סדרה פעם
# אחת ומחילים את הפוסטר שלה על כל פרקיה: כ-60 קריאות ל-TMDB במקום
# 1,294.
#
# tmdb_id נכתב רק עם ‎--set-tmdb‎. בלי זה נכתב פוסטר בלבד, כי מזהה
# שגוי גורר אחריו תיאור, טריילר וקטגוריה שגויים — ואילו פוסטר שגוי
# הוא תמונה אחת שקל להחליף.
#
# ## ישראלי
#
# ‎original_language == "he"‎ או ‎IL‎ ברשימת המדינות. זו שפת **המקור**:
# סדרה טורקית מדובבת לעברית נשארת "tr" ולא תיפול לכאן בטעות — וזה
# בדיוק ההבדל בין השדה הזה לבין ניחוש לפי שם עברי.
#
# התנועה היא בכיוון אחד בלבד ובין זוגות קבועים:
#
#     סרטים  →  סרטים ישראלים
#     סדרות  →  סדרות ישראליות
#
# שום פריט לא יוצא מקטגוריה ישראלית, ושום קטגוריה אחרת (אנימה,
# מארוול, אימה, ילדים, טורקיות) אינה נוגעת. פריט בלי tmdb_id אינו
# מוכרע ואינו נוגע.
#
# ## בטיחות
#
# גיבוי לפני כל כתיבה · כתיבה אטומית עם אימות קריאה · סירוב אם
# content.json השתנה בזמן הריצה · ‎--restore‎ · קידום
# content_version.txt, שבלעדיו האתר והאפליקציה ממשיכים להגיש
# מהמטמון · מטמון תשובות TMDB על הדיסק, כך שהרצה חוזרת כמעט אינה
# פונה לרשת.
# ─────────────────────────────────────────────────────────────────────────────
import argparse
import collections
import csv
import json
import os
import re
import shutil
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/opt/zovex-bot/data"))
CONTENT = DATA_DIR / "content.json"
VERSION_FILE = DATA_DIR / "content_version.txt"
BAK_DIR = DATA_DIR / "catalog_tmdb_backups"
CACHE_FILE = DATA_DIR / "tmdb_cache.json"
REPORT = DATA_DIR / "catalog_tmdb_report.csv"
IMG = "https://image.tmdb.org/t/p/w500"
TMDB = os.environ.get("TMDB_BASE", "https://api.themoviedb.org/3")

ISRAELI_OF = {"סרטים": "סרטים ישראלים", "סדרות": "סדרות ישראליות"}

ap = argparse.ArgumentParser()
ap.add_argument("--posters", action="store_true")
ap.add_argument("--israeli", action="store_true")
ap.add_argument("--set-tmdb", action="store_true",
                help="לכתוב גם tmdb_id שנמצא בחיפוש (ברירת מחדל: לא)")
ap.add_argument("--apply", action="store_true")
ap.add_argument("--restore", action="store_true")
ap.add_argument("--limit", type=int, default=0, help="לעצור אחרי N קריאות רשת")
args = ap.parse_args()


def load_key():
    k = os.environ.get("TMDB_API_KEY", "").strip()
    if k:
        return k
    for p in ("/opt/zovex-bot/.env", ".env"):
        try:
            for line in Path(p).read_text(encoding="utf-8").splitlines():
                if line.startswith("TMDB_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    return ""


# ── רשת ─────────────────────────────────────────────────────────────────────
#
# מטמון על הדיסק: הרצה חוזרת, וגם הרצה של --apply אחרי ההדמיה, אינן
# פונות שוב לאותן כתובות. בלי זה כל בדיקה חוזרת הייתה עוד אלף קריאות.
_cache = {}
_calls = [0]


def cache_load():
    global _cache
    try:
        _cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        _cache = {}


def cache_save():
    try:
        CACHE_FILE.write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print("אזהרה: שמירת המטמון נכשלה: %s" % e)


def api(path, **params):
    key = load_key()
    if not key:
        sys.exit("❌ TMDB_API_KEY חסר — לא ב-env ולא ב-/opt/zovex-bot/.env")
    params["api_key"] = key
    url = "%s/%s?%s" % (TMDB, path.lstrip("/"), urllib.parse.urlencode(params))
    ck = url.replace(key, "KEY")
    if ck in _cache:
        return _cache[ck]
    if args.limit and _calls[0] >= args.limit:
        return None
    for attempt in range(4):
        try:
            _calls[0] += 1
            with urllib.request.urlopen(url, timeout=30) as r:
                d = json.loads(r.read().decode())
            _cache[ck] = d
            time.sleep(0.06)      # ~16 קריאות לשנייה, הרבה מתחת למגבלה
            return d
        except Exception as e:
            code = getattr(e, "code", None)
            if code == 404:
                _cache[ck] = None
                return None
            if code == 401:
                sys.exit("❌ TMDB דחה את המפתח (401)")
            time.sleep(1.5 * (attempt + 1))
    print("   אזהרה: נכשל %s" % ck[:80])
    return None


def norm(s):
    s = unicodedata.normalize("NFKC", str(s or "")).lower().strip()
    s = re.sub(r"[֑-ׇ]", "", s)
    s = "".join(c if c.isalnum() else " " for c in s)
    return re.sub(r"\s+", " ", s).strip()


def is_episode(i):
    return (bool(i.get("series_name"))
            and i.get("season_number") not in (None, "")
            and i.get("episode_number") not in (None, ""))


def is_israeli(det):
    if not det:
        return False
    if str(det.get("original_language") or "").lower() == "he":
        return True
    cc = set(det.get("origin_country") or [])
    cc |= {c.get("iso_3166_1") for c in (det.get("production_countries") or [])}
    return "IL" in cc


def details(kind, tid):
    return api("%s/%s" % (kind, tid))


def search(kind, title, year=None):
    """חיפוש ב-TMDB. מחזיר תוצאה רק אם השם תואם באמת.

    התאמה חלקית היא מה שמדביק פוסטר של סרט אחר, ולכן נדרש שהשם
    המנורמל יהיה זהה או שאחד יכיל את השני.
    """
    p = {"query": title, "include_adult": "false"}
    if year:
        p["year" if kind == "movie" else "first_air_date_year"] = year
    d = api("search/%s" % kind, **p)
    if not d or not d.get("results"):
        d = api("search/%s" % kind, query=title, include_adult="false")
    if not d or not d.get("results"):
        return None
    want = norm(title)
    for r in d["results"][:5]:
        for fld in ("name", "original_name", "title", "original_title"):
            got = norm(r.get(fld))
            if got and (got == want or want in got or got in want):
                return r
    return None


rows = []


def add(action, reason, it, new_field, new_value, extra=""):
    rows.append({"פעולה": action, "סיבה": reason, "id": it.get("id"),
                 "כותרת": it.get("title"), "סדרה": it.get("series_name"),
                 "קטגוריה": it.get("category"), "שדה": new_field,
                 "ערך_חדש": str(new_value)[:120], "פרטים": extra})


def bump():
    try:
        cur = int(VERSION_FILE.read_text().strip() or "0")
    except Exception:
        cur = 0
    VERSION_FILE.write_text(str(cur + 1), encoding="utf-8")
    return cur + 1


def main():
    if args.restore:
        baks = sorted(BAK_DIR.glob("content_*.json")) if BAK_DIR.exists() else []
        if not baks:
            sys.exit("אין גיבוי של הסקריפט ב-%s" % BAK_DIR)
        shutil.copy2(baks[-1], CONTENT)
        print("✅ שוחזר מ-%s · גרסת תוכן %s" % (baks[-1], bump()))
        return
    if not (args.posters or args.israeli):
        sys.exit("בחר לפחות אחד:  --posters  --israeli")
    if not CONTENT.exists():
        sys.exit("לא נמצא %s" % CONTENT)

    stat_before = CONTENT.stat()
    arr = json.loads(CONTENT.read_text(encoding="utf-8"))
    if not isinstance(arr, list) or not arr:
        sys.exit("content.json אינו רשימה תקינה")
    print("קטלוג: %d פריטים" % len(arr))
    cache_load()
    changes = collections.Counter()

    # ── פוסטרים ────────────────────────────────────────────────────────────
    if args.posters:
        missing = [i for i in arr if not str(i.get("thumbnail_url") or "").strip()]
        print("\nפוסטרים חסרים: %d" % len(missing))

        # פרקים: חיפוש אחד לכל סדרה, ואז הפוסטר על כל פרקיה.
        by_series = collections.defaultdict(list)
        singles = []
        for i in missing:
            (by_series[i["series_name"]] if is_episode(i) else singles).append(i)
        print("   מהם פרקים של %d סדרות, ועוד %d פריטים בודדים"
              % (len(by_series), len(singles)))

        for name, items in sorted(by_series.items(), key=lambda kv: -len(kv[1])):
            tid = next((x.get("tmdb_id") for x in items if x.get("tmdb_id")), None)
            det = details("tv", tid) if tid else None
            if not det:
                hit = search("tv", name)
                if not hit:
                    print("   ✗ לא נמצאה: %s (%d פרקים)" % (name, len(items)))
                    continue
                det, tid = hit, hit.get("id")
            poster = det.get("poster_path")
            if not poster:
                print("   ✗ בלי פוסטר ב-TMDB: %s" % name)
                continue
            url = IMG + poster
            for x in items:
                x["_new_thumb"] = url
                changes["poster"] += 1
                add("פוסטר", "פוסטר הסדרה מ-TMDB", x, "thumbnail_url", url,
                    "tmdb=%s" % tid)
                if args.set_tmdb and not x.get("tmdb_id"):
                    x["_new_tmdb"] = tid
            print("   ✓ %-28s %4d פרקים  tmdb=%s" % (str(name)[:28], len(items), tid))

        for x in singles:
            tid, det = x.get("tmdb_id"), None
            kind = "tv" if x.get("series_name") else "movie"
            if tid:
                det = details(kind, tid) or details(
                    "tv" if kind == "movie" else "movie", tid)
            if not det:
                det = search(kind, x.get("title") or "", x.get("year"))
            if not det or not det.get("poster_path"):
                continue
            x["_new_thumb"] = IMG + det["poster_path"]
            changes["poster"] += 1
            add("פוסטר", "התאמה לפי שם ושנה", x, "thumbnail_url", x["_new_thumb"],
                "tmdb=%s" % det.get("id"))
            if args.set_tmdb and not x.get("tmdb_id") and det.get("id"):
                x["_new_tmdb"] = det["id"]

    # ── ישראלי ─────────────────────────────────────────────────────────────
    if args.israeli:
        cand = [i for i in arr if i.get("category") in ISRAELI_OF and i.get("tmdb_id")]
        print("\nמועמדים לבדיקת מקור: %d" % len(cand))
        # פרקים של אותה סדרה חולקים tmdb_id — קריאה אחת לכל מזהה.
        per_id = collections.defaultdict(list)
        for i in cand:
            per_id[(("tv" if is_episode(i) else "movie"), i["tmdb_id"])].append(i)
        print("   מזהים ייחודיים לבדיקה: %d" % len(per_id))
        for (kind, tid), items in per_id.items():
            det = details(kind, tid)
            if det is None:
                det = details("tv" if kind == "movie" else "movie", tid)
            if not is_israeli(det):
                continue
            for x in items:
                tgt = ISRAELI_OF[x["category"]]
                x["_new_cat"] = tgt
                changes["israeli"] += 1
                add("קטגוריה", "TMDB: שפת מקור/מדינה ישראל", x, "category", tgt,
                    "tmdb=%s lang=%s" % (tid, det.get("original_language")))
        cache_save()

    cache_save()
    print("\nקריאות ל-TMDB בריצה הזו: %d" % _calls[0])
    print("פוסטרים להשלמה: %d · העברות לקטגוריה ישראלית: %d"
          % (changes["poster"], changes["israeli"]))
    if args.israeli:
        mv = sum(1 for r in rows if r["פעולה"] == "קטגוריה" and r["קטגוריה"] == "סרטים")
        sr = changes["israeli"] - mv
        print("   סרטים → סרטים ישראלים: %d · סדרות → סדרות ישראליות: %d" % (mv, sr))

    if rows:
        with open(REPORT, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print("דוח מלא: %s (%d שורות)" % (REPORT, len(rows)))

    if not rows:
        print("\n✅ אין מה לשנות.")
        return
    if not args.apply:
        print("\nזו הדמיה בלבד. שום דבר לא נכתב.")
        print("לביצוע: הוסף --apply")
        return

    st = CONTENT.stat()
    if (st.st_mtime, st.st_size) != (stat_before.st_mtime, stat_before.st_size):
        sys.exit("❌ content.json השתנה בזמן הריצה — לא נוגעים. הרץ שוב.")

    BAK_DIR.mkdir(parents=True, exist_ok=True)
    bak = BAK_DIR / ("content_%s.json" % time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(CONTENT, bak)
    print("גיבוי: %s" % bak)

    for i in arr:
        if "_new_thumb" in i:
            i["thumbnail_url"] = i.pop("_new_thumb")
        if "_new_tmdb" in i:
            i["tmdb_id"] = i.pop("_new_tmdb")
        if "_new_cat" in i:
            i["category"] = i.pop("_new_cat")

    tmp = CONTENT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(arr, ensure_ascii=False, indent=2), encoding="utf-8")
    if len(json.loads(tmp.read_text(encoding="utf-8"))) != len(arr):
        tmp.unlink(missing_ok=True)
        sys.exit("❌ הקובץ שנכתב אינו תקין — לא הוחלף")
    os.replace(tmp, CONTENT)
    print("✅ בוצע. %d פריטים. גרסת תוכן: %s" % (len(arr), bump()))
    print("   לשחזור:  python3 %s --restore" % sys.argv[0])


if __name__ == "__main__":
    main()
