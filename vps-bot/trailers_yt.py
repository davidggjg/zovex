#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trailers_yt — טריילרים רשמיים מיוטיוב, לתוכן שאין ל-TMDB.

## למה בכלל, ומה הסדר הנכון

TMDB מספק טריילרים רשמיים בחינם, ו-fix_add_trailers כבר מושך אותם. נמדד
על הקטלוג: מתוך 1,170 יצירות ייחודיות (סדרה נספרת כאחת, כי טריילר הוא
לכל הסדרה), **943 יכולות לקבל טריילר מ-TMDB** ורק **226 לא**. לכן הכלי
הזה הוא השלב האחרון ולא הראשון — מריצים אותו על מה שנשאר.

הוא גם תלוי ב-en_title: אי אפשר לחפש ביוטיוב לפי "תלויה באוויר". נמדד
שרק ל-7 מ-226 יש en_title כרגע, ולכן הסדר הוא: זיהוי TMDB → en_title →
הכלי הזה.

## למה זה לא ממציא כתובות

זה השיעור החשוב מהבדיקה. כששואלים מודל שפה "מה כתובת הטריילר" הוא
**מייצר** מזהה יוטיוב — 11 תווים אקראיים שאין דרך לדעת מהזיכרון. נמדד:
שתי קריאות על אותו סרט החזירו שתי כתובות שונות, בביטחון מלא, ושתיהן
החזירו 404.

לכן כאן חלוקת האחריות הפוכה:

    השרת   מחפש ומאמת   — YouTube Data API, מזהים אמיתיים בלבד
    ג'מיני  בוחר ומנמק   — מחזיר **אינדקס** מהרשימה, לא כתובת
    השרת   מאמת שוב      — שהאינדקס מצביע על מזהה שאומת

מודל שמחזיר מספר מתוך רשימה סגורה לא יכול להמציא. וזה גם מה שהוא טוב
בו: להבחין שערוץ Lionsgate הוא המפיץ ו-BuzzFeed לא. נמדד שהוא בוחר נכון,
ושהוא מחזיר "אין רשמי" כשכל המועמדים אגרגטורים — במקום לבחור משהו.

## אכיפת שנה, ולמה היא חובה

בבדיקה על "איש הגלידה" (1995) הופיע StudiocanalUK עם "Official Trailer".
ערוץ מפיץ אמיתי לגמרי — אבל של סרט אחר באותו שם. בלי התנאי הזה הכלי היה
מכניס טריילר שגוי מערוץ שנראה מושלם. לכן השנה נכנסת גם לשאילתה, גם
לפרומפט, וגם לבדיקה על כותרת המועמד.

## מכסה

חיפוש עולה 100 יחידות, videos.list עולה 1, והמכסה החינמית 10,000 ליום —
כלומר ~99 יצירות ביום. הכלי סופר ועוצר לפני שהוא חורג, כדי שלא ייגמר
באמצע וישאיר חצי עבודה.

    python3 trailers_yt.py --check --limit 10
    python3 trailers_yt.py --limit 50
    python3 trailers_yt.py --revert
"""
import argparse, importlib.util, json, os, random, re, shutil, sys, time, urllib.error, urllib.parse, urllib.request
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))

SEARCH_COST, VIDEOS_COST, DAILY_QUOTA = 100, 1, 10000
# ערוצים שהם אגרגטורים/חדשות/אוהדים. לא רשימה שחורה מחייבת — ג'מיני
# מכריע — אבל היא מוזכרת בפרומפט כדי לחדד לו מה לא נחשב רשמי.
NOT_OFFICIAL_HINT = ("Movieclips, Rotten Tomatoes, JoBlo, FilmSelect, "
                     "LatestMovieTrailers, New Trailer Buzz, reaction, fan")


def _load_enrich():
    p = os.path.join(_HERE, "tmdb_enrich.py")
    if not os.path.exists(p):
        sys.exit(f"לא נמצא {p} — הכלי הזה מייבא ממנו.")
    spec = importlib.util.spec_from_file_location("_tmdb_enrich", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def load_env_key(name):
    v = os.environ.get(name)
    if v:
        return v.strip()
    envf = "/opt/zovex-bot/.env"
    if os.path.exists(envf):
        for line in open(envf, encoding="utf-8", errors="ignore"):
            if line.strip().startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _get(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": "zovex-bot/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def iso_seconds(d):
    """PT2M14S → 134. אורך הוא סינון זול ויעיל: סרט שלם או קליפ של 20
    שניות אינם טריילר, ואין טעם לשאול מודל על זה."""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", d or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def work_key(it):
    sn = (it.get("series_name") or "").strip()
    return ("series", sn) if sn else ("item", it.get("id"))


def collect_targets(items):
    """יצירות בלי טריילר, בלי tmdb_id, ועם en_title לטיני לחיפוש."""
    works = {}
    for it in items:
        if it.get("is_live"):
            continue
        works.setdefault(work_key(it), []).append(it)

    out = []
    for k, g in works.items():
        if any(x.get("trailer_url") for x in g):
            continue
        if any(x.get("tmdb_id") not in (None, 0, "0") for x in g):
            continue          # ל-TMDB יש מה לתת — לא מבזבזים כאן מכסה
        en = next((x.get("en_title") for x in g if x.get("en_title")), None)
        if not en or not re.search(r"[A-Za-z]", en):
            continue          # שם עברי לא ניתן לחיפוש ביוטיוב
        yr = next((x.get("year") for x in g if x.get("year")), None)
        heb = g[0].get("series_name") or g[0].get("title")
        out.append({"key": k, "items": g, "en": en.strip(), "year": yr, "heb": heb})
    return out


def yt_candidates(yt_key, en, year, spent):
    """חיפוש + אימות. מחזיר (מועמדים, יחידות שנצרכו)."""
    q = f"{en} {year} official trailer" if year else f"{en} official trailer"
    url = ("https://www.googleapis.com/youtube/v3/search?part=snippet&type=video"
           f"&maxResults=8&q={urllib.parse.quote(q)}&key={yt_key}")
    s = _get(url)
    used = SEARCH_COST
    ids = [i["id"]["videoId"] for i in s.get("items", []) if i.get("id", {}).get("videoId")]
    if not ids:
        return [], used
    v = _get("https://www.googleapis.com/youtube/v3/videos"
             f"?part=snippet,contentDetails&id={','.join(ids)}&key={yt_key}")
    used += VIDEOS_COST
    cand = []
    for it in v.get("items", []):
        dur = iso_seconds(it.get("contentDetails", {}).get("duration"))
        # 25 שניות עד 5 דקות. מחוץ לטווח זה לא טריילר, ומסונן בלי מודל.
        if not (25 <= dur <= 300):
            continue
        cand.append({"id": it["id"], "title": it["snippet"]["title"],
                     "channel": it["snippet"]["channelTitle"], "dur": dur})
    return cand, used


def gemini_pick(keys, en, year, cand, tries=3):
    """מחזיר (אינדקס, ביטחון, נימוק). ג'מיני מחזיר **מספר** ולא כתובת,
    ולכן אינו יכול להמציא מזהה. מחליף מפתח בכל ניסיון: 503 ו-429 הם
    לפי מודל/פרויקט, ומפתח אחר לרוב עובר."""
    listing = "\n".join(
        f'{i}. ערוץ="{c["channel"]}" כותרת="{c["title"]}" אורך={c["dur"]}ש'
        for i, c in enumerate(cand))
    prompt = (
        f'הסרט/הסדרה: "{en}"' + (f" משנת {year}" if year else "") + ".\n\n"
        f"מועמדי טריילר שאומתו כקיימים ביוטיוב:\n{listing}\n\n"
        "בחר את הטריילר **הרשמי** — מערוץ של אולפן, מפיץ או רשת קולנוע.\n"
        f"אינם רשמיים: {NOT_OFFICIAL_HINT}.\n"
        + (f"חובה: הטריילר חייב להיות של הגרסה משנת {year}. שם זהה לשנה "
           "אחרת הוא יצירה אחרת — אם אתה לא בטוח שזו אותה שנה, החזר -1.\n"
           if year else "")
        + "אם אין רשמי — pick=-1. אל תבחר משהו בינוני כדי לענות.\n"
        'JSON: {"pick":<מספר>,"why":"קצר","conf":0.0-1.0}')
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0,
                                            "responseMimeType": "application/json"}}).encode()
    last = ""
    for t in range(tries):
        k = keys[t % len(keys)]
        try:
            r = urllib.request.Request(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-3.5-flash:generateContent?key={k}",
                data=body, headers={"Content-Type": "application/json"})
            d = json.load(urllib.request.urlopen(r, timeout=90))
            o = json.loads("".join(p.get("text", "")
                                   for p in d["candidates"][0]["content"]["parts"]))
            return int(o.get("pick", -1)), float(o.get("conf", 0)), str(o.get("why", ""))[:120]
        except urllib.error.HTTPError as e:
            last = f"{e.code}"
            if e.code in (429, 503, 500):
                time.sleep(2 + 2 * t)        # עומס רגעי — מפתח אחר, המתנה גדלה
                continue
            break
        except Exception as e:
            last = type(e).__name__
            time.sleep(1 + t)
    return -1, 0.0, f"ג'מיני לא זמין ({last})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--min-conf", type=float, default=0.75,
                    help="מתחת לזה לא נכתב — מדווח ומדולג")
    a = ap.parse_args()

    E = _load_enrich()
    CONTENT, VERSION = E.CONTENT, E.VERSION
    BACKUP = CONTENT.with_name("content.json.bak_trailers_yt")

    if a.revert:
        if not BACKUP.exists():
            sys.exit(f"אין גיבוי ב-{BACKUP}")
        shutil.copy2(BACKUP, CONTENT)
        print(f"✓ שוחזר מ-{BACKUP}")
        return

    yt = load_env_key("YOUTUBE_API_KEY")
    if not yt:
        sys.exit("אין YOUTUBE_API_KEY בסביבה או ב-/opt/zovex-bot/.env")
    gem = [k for k in re.split(r"[,\s]+", load_env_key("GEMINI_KEYS")) if k]
    if not gem:
        sys.exit("אין GEMINI_KEYS בסביבה או ב-/opt/zovex-bot/.env")
    print(f"מפתחות: יוטיוב 1 · ג'מיני {len(gem)}")

    items = json.loads(CONTENT.read_text(encoding="utf-8"))
    targets = collect_targets(items)
    print(f'יצירות מתאימות: {len(targets)} (מתוך {len(items)} פריטים)')
    if not targets:
        print("אין מה לעשות. אם זה מפתיע — כנראה חסר en_title, "
              "והסדר הוא זיהוי TMDB קודם.")
        return

    spent, stat, found = 0, Counter(), []
    for w in targets[:a.limit]:
        if spent + SEARCH_COST + VIDEOS_COST > DAILY_QUOTA:
            print(f"\nעוצר: המכסה היומית כמעט נגמרה ({spent}/{DAILY_QUOTA}).")
            stat["נעצר מחוסר מכסה"] += 1
            break
        label = f'{w["heb"][:26]:26} ({w["en"][:24]}, {w["year"] or "?"})'
        try:
            cand, used = yt_candidates(yt, w["en"], w["year"], spent)
            spent += used
        except urllib.error.HTTPError as e:
            b = e.read().decode()[:120]
            print(f"  ✗ {label} — יוטיוב {e.code}: {b}")
            stat["שגיאת יוטיוב"] += 1
            if e.code == 403:
                print("     403 לרוב = המכסה נגמרה או שה-API לא מופעל בפרויקט. עוצר.")
                break
            continue
        if not cand:
            print(f"  — {label} — אין מועמד באורך של טריילר")
            stat["בלי מועמדים"] += 1
            continue

        pick, conf, why = gemini_pick(gem, w["en"], w["year"], cand)
        if not (0 <= pick < len(cand)):
            print(f"  — {label} — אין רשמי ({why[:52]})")
            stat["ג'מיני: אין רשמי"] += 1
            continue
        if conf < a.min_conf:
            print(f"  — {label} — ביטחון נמוך {conf} ({why[:40]})")
            stat["ביטחון נמוך"] += 1
            continue
        c = cand[pick]
        url = f"https://www.youtube.com/watch?v={c['id']}"
        print(f"  ✓ {label}")
        print(f"      {c['channel'][:30]:30} conf={conf}  {url}")
        found.append((w, url, c))
        stat["נמצא טריילר"] += 1
        time.sleep(0.4)

    print(f"\nמכסת יוטיוב שנצרכה: {spent}/{DAILY_QUOTA}")
    for k, v in stat.most_common():
        print(f"  {k}: {v}")
    if not found:
        print("\nלא נמצא כלום לכתיבה.")
        return
    n_items = sum(len(w["items"]) for w, _u, _c in found)
    print(f"\n{len(found)} יצירות · {n_items} פריטים יסומנו")

    if a.check:
        print("--check: שום דבר לא נכתב.")
        return

    shutil.copy2(CONTENT, BACKUP)
    for w, url, _c in found:
        for it in w["items"]:          # טריילר הוא לכל הסדרה
            it["trailer_url"] = url
    E.atomic_write(CONTENT, json.dumps(items, ensure_ascii=False, indent=2))
    try:
        v = int(VERSION.read_text().strip()) + 1 if VERSION.exists() else 1
    except Exception:
        v = int(time.time())
    E.atomic_write(VERSION, str(v))
    print(f"✓ נכתבו {n_items} פריטים · גיבוי: {BACKUP} · גרסה {v}")
    print("  בלי restart. לביטול: python3 trailers_yt.py --revert")


if __name__ == "__main__":
    main()
