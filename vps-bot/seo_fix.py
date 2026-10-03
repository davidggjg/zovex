#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""seo_fix — כתובות באנגלית, פוסטרים וקטגוריות, מ-TMDB.

## מה נמדד על הקטלוג החי לפני שנכתב

    264 פריטים בלי custom_slug   → כתובת ‎/%D7%A9%D7%97%D7%A7-...‎
    140 slugs שהם **תעתיק**      → ‎hmtym-hmhlkym‎ במקום השם האמיתי
    107 פריטים בלי תמונה
     10 פריטים בלי שם בכלל       → ‎/-a3987a/‎ (דולגו כבר בסייטמאפ)

התעתיק אינו תקלה אקראית: ‎main.py‎ נופל ל-‎_HE_TRANSLIT‎ כשההתאמה
ל-TMDB נכשלת. כלומר ‎hmtym-hmhlkym‎ פירושו "לא מצאנו את זה", ולא "זה
השם". חיפוש מדויק יותר מחזיר את השם האמיתי.

## מה הוא עושה

לכל פריט שחסר לו משהו — מחפש ב-TMDB לפי שם ושנה, ומציע:

* **slug** מהשם האנגלי (‎en_title‎), לא תעתיק
* **פוסטר** לפריטים בלי תמונה
* **קטגוריה** לפי ‎_auto_category‎ — אותו כלל בדיוק שבשרת, ולא עותק
  שני שיתפצל ממנו

## ההתאמה, ולמה היא שמרנית

שם עברי שחוזר מ-TMDB זהה לשם אצלנו ⇒ ודאי. שנה תואמת מחזקת. כל השאר
מדווח כ"לבדיקה" ו**אינו מוחל**: slug שגוי הוא כתובת שגויה שגוגל
יאנדקס, וזה גרוע מכתובת מכוערת.

## הכתובת הישנה אינה הולכת לאיבוד

שינוי slug משנה כתובת שגוגל כבר הכיר. לכן ה-slug הישן נשמר בפריט
תחת ‎old_slugs‎, והבנייה מייצרת עבורו דף עם ‎canonical‎ אל החדש —
כך הדירוג עובר במקום להימחק.

    python3 seo_fix.py                    # דוח בלבד
    python3 seo_fix.py --only slug        # slug / image / category
    python3 seo_fix.py --limit 40
    python3 seo_fix.py --apply
    python3 seo_fix.py --selftest

קריאה בלבד עד ‎--apply‎. ההחלה עוברת דרך הפאנל עם ‎base_version‎,
כך שעריכה מקבילה נדחית ולא נדרסת.
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

LOCAL = "http://127.0.0.1:8000"
CURL = ["curl", "-sS", "--noproxy", "127.0.0.1"]
ENV = pathlib.Path("/opt/zovex-bot/.env")
TMDB_IMG = "https://image.tmdb.org/t/p/w500"
LIVE_CATEGORY = "שידורים חיים"

_KEEP = re.compile(r"[^\w֐-׿]+", re.U)
_ARTICLE = re.compile(r"^(?:the|a|an)\s+", re.I)


def norm(s: str) -> str:
    """אותו נרמול כמו tmdb_names.norm — שם אחד, כלל אחד."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = _KEEP.sub(" ", s.lower())
    s = re.sub(r"\s{2,}", " ", s).strip()
    return _ARTICLE.sub("", s).strip()


def slugify(en: str) -> str:
    """שם אנגלי ⇒ slug. רק ASCII, בלי רצפי מקפים."""
    s = unicodedata.normalize("NFKD", en or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return re.sub(r"-{2,}", "-", s)[:60]


def vowel_ratio(slug: str) -> float:
    s = re.sub(r"[^a-z]", "", (slug or "").lower())
    # רק aeiou. ‎y‎ **אינה** נספרת כאן במכוון: עם ‎y‎ הסף הפסיק
    # לתפוס תעתיקים אמיתיים כמו ‎khrf-ayn‎ (כהרף עין), וזו החמצה
    # שמשאירה ג'יבריש באוויר. ההטיה היא לכיוון התפיסה — ראה
    # looks_transliterated.
    return (sum(c in "aeiou" for c in s) / len(s)) if s else 1.0


def looks_transliterated(slug: str) -> bool:
    """‎hmtym-hmhlkym‎ מול ‎the-walking-dead‎.

    תעתיק מעברית משמיט תנועות, ולכן יחס התנועות שלו נמוך בהרבה מכל
    מילה אנגלית. הסף 0.22 נבחר על הנתונים בפועל: הוא תופס 140 מתוך
    2,113 ואינו תופס שמות אנגליים קצרים כמו ‎girls‎ או ‎lolly‎.

    **זהו מסנן מועמדים ולא פסק דין.** הוא רק קובע את מי לבדוק מול
    TMDB, והחלפת ה-slug קורית רק אם TMDB מחזיר שם **אחר**. לכן מילה
    נדירה שתיתפס כאן בטעות (‎rhythm‎, ‎crypt‎) עולה חיפוש אחד ולא
    משנה כלום — ועדיף כך מאשר להחמיץ תעתיק אמיתי.
    """
    s = re.sub(r"[^A-Za-z]", "", (slug or "").lower())
    if len(s) < 4:
        return False                       # קצר מדי מכדי להחליט
    # מילה אנגלית בת 4 אותיות ומעלה כמעט תמיד נושאת תנועה. ‎y‎ נחשבת
    # כאן כתנועה כדי לא לסמן ‎myth‎ או ‎lynx‎ בטעות.
    #
    # בלי הענף הזה ‎hnmlt‎ (הנמלט) נפל בין הכיסאות: 5 אותיות, אפס
    # תנועות, והמגן על מילים קצרות פסל אותו. נתפס בבדיקה העצמית.
    if not any(c in "aeiouy" for c in s):
        return True
    if len(s) < 6:
        return False
    return vowel_ratio(slug) < 0.22


def tmdb_key() -> str:
    k = os.environ.get("TMDB_API_KEY", "").strip()
    if k:
        return k
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8",
                                  errors="replace").splitlines():
            if line.strip().startswith("TMDB_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def panel_password() -> str:
    p = os.environ.get("PANEL_PASSWORD", "").strip()
    if p:
        return p
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8",
                                  errors="replace").splitlines():
            if line.strip().startswith("PANEL_PASSWORD="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def auto_category(it: dict) -> str:
    """העתק מדויק של ‎_auto_category‎ שב-main.py (ראה שם את הנימוקים)."""
    g = set(it.get("genre_ids") or [])
    origin = {str(x).upper() for x in (it.get("origin") or [])}
    lang = (it.get("lang") or "").lower()
    is_tv = it.get("type") == "tv"
    is_anim = 16 in g
    is_jp = ("JP" in origin) or (lang == "ja")
    is_il = ("IL" in origin) or (lang == "he")
    if is_tv:
        if is_anim and is_jp:
            return "אנימה"
        if is_il:
            return "סדרות ישראליות"
        if 27 in g:
            return "אימה"
        if (10762 in g) or (10751 in g):
            return "סדרות לילדים"
        return "סדרות"
    if is_anim and is_jp:
        return "אנימה"
    if 27 in g:
        return "אימה"
    if is_anim or (10751 in g):
        return "סרטים לילדים (מתאים גם למשפחה)"
    return "סרטים"


def tmdb_search(key: str, query: str, year: str = "", timeout=12):
    """אותם פרמטרים כמו בשרת. [(תוצאה)] עד 6, מדורג לפי שנה."""
    if not key or not query:
        return []
    he_out, en_out, en_map = [], [], {}
    for lang in ("he", "en-US"):
        q = urllib.parse.urlencode({"api_key": key, "query": query,
                                    "language": lang,
                                    "include_adult": "false"})
        try:
            with urllib.request.urlopen(
                    "https://api.themoviedb.org/3/search/multi?" + q,
                    timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
        except Exception:                                     # noqa: BLE001
            continue
        for it in data.get("results", []):
            mt = it.get("media_type")
            if mt not in ("movie", "tv"):
                continue
            title = it.get("title") or it.get("name") or ""
            orig = it.get("original_title") or it.get("original_name") or ""
            tid = it.get("id")
            if not tid:
                continue
            if lang == "en-US":
                en_map[(tid, mt)] = title or orig
            bucket = en_out if lang == "en-US" else he_out
            if not title or any(o["tmdb_id"] == tid and o["type"] == mt
                                for o in bucket):
                continue
            date = it.get("release_date") or it.get("first_air_date") or ""
            bucket.append({
                "tmdb_id": tid, "type": mt, "title": title,
                "year": (date or "")[:4],
                "poster": (TMDB_IMG + it["poster_path"])
                          if it.get("poster_path") else "",
                "original": orig,
                "genre_ids": it.get("genre_ids") or [],
                "origin": it.get("origin_country") or [],
                "lang": (it.get("original_language") or "").lower(),
            })
    out = he_out or en_out
    for o in out:
        o["en_title"] = en_map.get((o["tmdb_id"], o["type"])) \
            or o.get("original") or o["title"]
    if year:
        def rank(o):
            oy = o.get("year") or ""
            if oy == year:
                return 0
            try:
                return 1 if abs(int(oy) - int(year)) <= 1 else 2
            except Exception:                                 # noqa: BLE001
                return 3
        out.sort(key=rank)
    return out[:6]


def pick(results, title: str, year: str):
    """(תוצאה, ודאות). ‎None‎ כשאין התאמה שאפשר לסמוך עליה."""
    nt = norm(title)
    if not nt:
        return None, ""
    for o in results:
        if norm(o.get("title")) == nt:
            if year and o.get("year") == year:
                return o, "ודאי (שם ושנה)"
            return o, "ודאי (שם)"
    for o in results:
        if norm(o.get("en_title")) == nt or norm(o.get("original")) == nt:
            return o, "ודאי (שם מקור)"
    if year:
        same = [o for o in results if o.get("year") == year]
        if len(same) == 1:
            return same[0], "לבדיקה (שנה בלבד)"
    if len(results) == 1:
        return results[0], "לבדיקה (תוצאה יחידה)"
    return None, ""


def get_content():
    hdr = pathlib.Path("/tmp/_seo_hdr")
    r = subprocess.run(CURL + ["-D", str(hdr), "--max-time", "180",
                               f"{LOCAL}/content"], capture_output=True)
    ver = None
    try:
        for line in hdr.read_text(encoding="latin1",
                                  errors="replace").splitlines():
            if line.lower().startswith("x-content-version:"):
                ver = int(line.split(":", 1)[1].strip())
    except Exception:                                         # noqa: BLE001
        pass
    try:
        return json.loads(r.stdout), ver
    except json.JSONDecodeError as e:
        sys.exit(f"❌ לא ניתן לקרוא את הקטלוג: {e}")


def title_of(e):
    return (e.get("series_name") or e.get("title") or "").strip()


def selftest() -> int:
    bad = 0

    def chk(ok, what):
        nonlocal bad
        if not ok:
            bad += 1
        print(f"{'✓' if ok else '✗'} {what}")

    # ① slug מהשם האנגלי
    chk(slugify("The Walking Dead") == "the-walking-dead", "slug בסיסי")
    chk(slugify("Supa Strikas!") == "supa-strikas", "סימני פיסוק יורדים")
    chk(slugify("X-Men: Days of Future Past")
        == "x-men-days-of-future-past", "נקודתיים ומקף")
    chk(slugify("Pokémon") == "pokemon", "ניקוד מוסר")
    chk(slugify("  a   b  ") == "a-b", "בלי רצף מקפים")
    chk(slugify("") == "", "ריק")

    # ② זיהוי תעתיק — הכלל שקובע מה בכלל נוגעים בו
    for s in ("hmtym-hmhlkym", "svpr-stryykh", "mkvnt-mlchmh", "hnmlt"):
        chk(looks_transliterated(s), f"‏{s} מזוהה כתעתיק")
    for s in ("the-walking-dead", "girls", "lolly", "supa-strikas",
              "x-men-days-of-future-past", "Sport6"):
        chk(not looks_transliterated(s), f"‏{s} **אינו** תעתיק")

    # ③ ההתאמה — שמרנית במכוון
    res = [{"title": "המתים המהלכים", "en_title": "The Walking Dead",
            "year": "2010", "original": "The Walking Dead"},
           {"title": "משהו אחר", "en_title": "Other", "year": "2015",
            "original": "Other"}]
    o, conf = pick(res, "המתים המהלכים", "2010")
    chk(o and o["en_title"] == "The Walking Dead" and "ודאי" in conf,
        f"שם ושנה ⇒ {conf}")
    o, conf = pick(res, "המתים המהלכים", "")
    chk(o and "ודאי" in conf, "שם בלבד ⇒ ודאי")
    o, conf = pick(res, "שם שלא קיים", "1999")
    chk(o is None, "שם שאינו ברשימה ⇒ אין התאמה")
    o, conf = pick([], "משהו", "2000")
    chk(o is None, "בלי תוצאות ⇒ אין התאמה")
    o, conf = pick(res, "משהו אחר", "2015")
    chk(o and o["year"] == "2015", "התאמה שנייה ברשימה")
    o, conf = pick([res[0]], "שם אחר לגמרי", "")
    chk(o is not None and "לבדיקה" in conf,
        "תוצאה יחידה ⇒ מסומנת לבדיקה ולא כוודאית")

    # ④ הקטגוריה — אותו כלל כמו בשרת
    chk(auto_category({"type": "tv", "genre_ids": [16], "origin": ["JP"]})
        == "אנימה", "אנימציה יפנית ⇒ אנימה")
    chk(auto_category({"type": "tv", "genre_ids": [10762]})
        == "סדרות לילדים", "תיוג ילדים ⇒ סדרות לילדים")
    chk(auto_category({"type": "tv", "genre_ids": [16]}) == "סדרות",
        "אנימציה לא-יפנית בלי תיוג ילדים נשארת סדרות")
    chk(auto_category({"type": "tv", "origin": ["IL"]})
        == "סדרות ישראליות", "מוצא ישראלי")
    chk(auto_category({"type": "movie", "genre_ids": [27]}) == "אימה",
        "אימה")
    chk(auto_category({"type": "movie", "genre_ids": []}) == "סרטים",
        "ברירת מחדל")

    print("\n" + ("✓ הכל עבר" if not bad else f"✗ {bad} נכשלו"))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", choices=["", "slug", "image",
                                                   "category"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--all", action="store_true",
                    help="לעבור על **כל** הקטלוג ולא רק על פריטים פגומים. "
                         "דרוש כדי לתפוס קטגוריה שגויה בפריט שה-slug "
                         "והתמונה שלו תקינים (~2,250 יחידות, כ-20 דקות)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--gap", type=float, default=0.3)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    key = tmdb_key()
    if not key:
        sys.exit("❌ אין TMDB_API_KEY (סביבה או .env)")

    movies, ver = get_content()
    print(f"הקטלוג: {len(movies):,} פריטים · גרסה {ver}\n")

    # יחידה = סדרה (לפי שם) או סרט בודד. ל-slug ולקטגוריה זו היחידה
    # הנכונה: כל פרקי הסדרה חולקים כתובת וקטגוריה אחת.
    units = {}
    for e in movies:
        if e.get("category") == LIVE_CATEGORY or e.get("is_live"):
            continue
        t = title_of(e)
        if not t:
            continue
        u = units.setdefault(t, {"rows": [], "is_series":
                                 bool((e.get("series_name") or "").strip())})
        u["rows"].append(e)

    # ‎--only category‎ מחייב מעבר מלא: אחרת היה בודק רק פריטים שכבר
    # פגומים במשהו אחר, וזה בדיוק לא מה שנשאל.
    full = a.all or a.only == "category"
    todo = []
    for t, u in units.items():
        first = u["rows"][0]
        cs = (first.get("custom_slug") or "").strip()
        need = []
        if not cs:
            need.append("slug-חסר")
        elif looks_transliterated(cs):
            need.append("slug-תעתיק")
        if not any((r.get("thumbnail_url") or "").strip() for r in u["rows"]):
            need.append("תמונה")
        # מעבר מלא: גם יחידה ללא פגם נבדקת, כי קטגוריה שגויה אינה
        # "פגם" שאפשר לראות מהנתון שלנו — רק TMDB יודע שסופר סטרייקה
        # היא סדרת ילדים. בלי זה נבדקו רק פריטים שנתפסו ממילא מסיבה
        # אחרת, וזו הייתה הגבלה שלא נאמרה.
        if need or full:
            todo.append((t, u, need, cs))

    if a.only in ("slug", "image"):
        want = {"slug": ("slug-חסר", "slug-תעתיק"),
                "image": ("תמונה",)}[a.only]
        todo = [x for x in todo if any(n in want for n in x[2])]
    if a.limit:
        todo = todo[:a.limit]

    mode = "כל הקטלוג" if full else "פריטים פגומים בלבד"
    eta = len(todo) * (a.gap + 0.35) / 60
    print(f"{len(todo):,} יחידות · {mode} · כ-{eta:.0f} דקות\n" + "=" * 68)

    plan, review = [], []
    for i, (t, u, need, cs) in enumerate(todo, 1):
        first = u["rows"][0]
        yr = str(first.get("year") or "")
        res = tmdb_search(key, t, yr)
        o, conf = pick(res, t, yr)
        time.sleep(a.gap)
        if not o:
            review.append((t, need, cs, None, "לא נמצא ב-TMDB"))
            continue
        new_slug = slugify(o.get("en_title") or "")
        new_cat = auto_category(o)
        cur_cat = first.get("category") or ""
        ch = []
        if new_slug and new_slug != cs and ("slug-חסר" in need
                                            or "slug-תעתיק" in need):
            ch.append(("slug", cs or "—", new_slug))
        if "תמונה" in need and o.get("poster"):
            ch.append(("תמונה", "—", o["poster"].rsplit("/", 1)[-1]))
        if new_cat and new_cat != cur_cat:
            ch.append(("קטגוריה", cur_cat, new_cat))
        if a.only:
            keep = {"slug": "slug", "image": "תמונה",
                    "category": "קטגוריה"}[a.only]
            ch = [c for c in ch if c[0] == keep]
        if not ch:
            continue
        row = (t, u, o, ch, conf)
        (plan if conf.startswith("ודאי") else review).append(row)
        mark = "✓" if conf.startswith("ודאי") else "?"
        print(f"\n{mark} {t[:42]}   [{conf}]")
        for what, old, new in ch:
            print(f"     {what:<9} {str(old)[:26]:<26} → {new}")

    print("\n" + "=" * 68)
    print(f"{len(plan)} ודאיים · {len(review)} לבדיקה ידנית")
    if review:
        print("\nלבדיקה (לא יוחל):")
        for r in review[:15]:
            print(f"  {str(r[0])[:44]:<44} {r[-1] if len(r) == 5 else ''}")
        if len(review) > 15:
            print(f"  ... ועוד {len(review) - 15}")
    if not plan:
        print("\nאין שינוי ודאי להחיל.")
        return 0
    if not a.apply:
        print("\nזהו דוח בלבד. להחיל את הוודאיים:")
        print("  python3 seo_fix.py --apply")
        return 0

    pwd = panel_password()
    if not pwd:
        sys.exit("❌ לא נמצאה PANEL_PASSWORD")

    n = 0
    for t, u, o, ch, _conf in plan:
        new_slug = slugify(o.get("en_title") or "")
        new_cat = auto_category(o)
        for r in u["rows"]:
            old = (r.get("custom_slug") or "").strip()
            for what, _a, _b in ch:
                if what == "slug" and new_slug:
                    if old and old != new_slug:
                        # הכתובת הישנה נשמרת, כדי שהבנייה תייצר לה דף
                        # עם canonical אל החדשה — אחרת גוגל מאבד את מה
                        # שכבר אינדקס.
                        olds = r.get("old_slugs") or []
                        if old not in olds:
                            olds.append(old)
                        r["old_slugs"] = olds
                    r["custom_slug"] = new_slug
                elif what == "תמונה" and o.get("poster"):
                    if not (r.get("thumbnail_url") or "").strip():
                        r["thumbnail_url"] = o["poster"]
                elif what == "קטגוריה" and new_cat:
                    r["category"] = new_cat
        n += 1

    body = json.dumps({"password": pwd, "movies": movies,
                       "base_version": ver}, ensure_ascii=False)
    tmp = pathlib.Path("/tmp/_seo_body.json")
    tmp.write_text(body, encoding="utf-8")
    r = subprocess.run(CURL + ["-X", "POST", "-H",
                               "Content-Type: application/json",
                               "--data-binary", f"@{tmp}", "--max-time", "300",
                               f"{LOCAL}/content/save"], capture_output=True)
    out = r.stdout.decode("utf-8", "replace")
    tmp.unlink(missing_ok=True)
    if '"ok"' in out or '"version"' in out or '"saved"' in out:
        print(f"\n✓ {n} יחידות עודכנו.")
        print("עכשיו בנה מחדש את האתר כדי שהכתובות ייווצרו:")
        print("  cd /opt/zovex-bot && bash update_all.sh")
    else:
        print(f"\n❌ השמירה נדחתה: {out[:200]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
