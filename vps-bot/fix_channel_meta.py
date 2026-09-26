#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_channel_meta.py — לוגו ו-slug לערוצים החדשים, וחיפוש מזהי EPG.

שני חלקים נפרדים:

--thumbs   קובע thumbnail_url ו-custom_slug לערוצי ספורט 5 שהוספנו.
           ה-slug אינו קוסמטי: לוח השידורים נשלף לפי /epg/<slug>.json,
           ובלעדיו לערוץ אין לוח גם אם המזהה קיים אצל וואלה.
           הלוגואים נלקחים מאותו מאגר ציבורי שהקטלוג כבר משתמש בו
           (tv-logo/tv-logos) ומאומתים ב-HTTP לפני הכתיבה.

--scan-all שואל את כל ארבעת המקורות של epg_build.py אילו ערוצים קיימים,
           ומדפיס שורה מוכנה ל-MAP לכל שם שמתאים ל---pattern. אפשר גם כל
           מקור לחוד: --epg-scan (וואלה), --free-scan, --yes-scan, --hot-scan.

           מי נגיש מאיפה — זה לא אותו דבר לכל המקורות:
             וואלה  · פתוח מכל מקום. הפרמטר provider הוא מספר (3=yes, 2=hot);
                      שליחת "yes"/"hot" מחזירה 400 — זו הייתה טעות שלי ולא
                      חסימה גיאוגרפית.
             FreeTV · פתוח מכל מקום, בלי הרשמה.
             HOT    · מחזיר 302 בלופ לכל מי שאינו דפדפן אמיתי. חייב לרוץ
                      מהשרת.
             yes    · אינו בקשת רשת בכלל אלא תצלום שנאסף מהדפדפן ויושב ב-
                      data/yes-epg.json, כי Akamai חוסמת שם. חייב את השרת.

           לכן כדי לכסות את כל הארבעה — להריץ מהשרת.

--list     שמות כל הערוצים בכל מקור שיש לו שמות, בלי סינון. כשחיפוש לפי
           תבנית לא מוצא כלום, זו התשובה לשאלה "אז מה כן יש שם".

--hot-hunt HOT הוא המקור היחיד שאינו מחזיר שמות ערוצים בכלל — רק channelID
           וכותרות. נמדד: 20,663 תוכניות, 0 שמות. לכן חיפוש לפי שם ערוץ
           שם חסר טעם, וזיהוי נעשה לפי *תוכן*: ערוץ UFC משדר תוכניות
           שבשמן UFC, וערוץ HBO משדר את הסדרות של HBO. זו אותה שיטה שבה
           זוהו המזהים שכבר ב-MAP (קומיט 579943f).
           הדירוג הוא שיעור מתוך הלוח ולא מספר התאמות, כדי שערוץ שהקרין
           פעם אחת סרט מאותו סוג לא ייראה כמו הערוץ עצמו.
           --hot-dump <channelID> מדפיס לוח מלא של מזהה אחד, לזיהוי בעין.

--hot-fingerprint
           חיפוש לפי חתימה עובד רק אם ניחשתי נכון מה הערוץ משדר. חתימת
           ה-HBO שכתבתי החזירה 0 מתוך 41,326 תוכניות — וזו עדות על החתימה,
           לא על הערוץ. טביעת אצבע אינה מניחה כלום: לכל אחד מ-208 הערוצים
           מודפסות הכותרות שחוזרות בו, והזיהוי נעשה בעין.
           הסדר הוא לפי ריכוזיות — איזה שיעור מהלוח תופסות שלוש הכותרות
           החוזרות ביותר — כך שערוץ סדרות עולה למעלה וערוץ סרטים מתחלפים
           יורד למטה. --unmapped מסתיר את מה שכבר ממופה אצלנו.

           יום של HOT הוא כ-9.5MB, ולכן התשובה נשמרת ב-data/hot-epg-raw.json
           לשש שעות. כמה סריקות בזו אחר זו אינן מורידות שוב.

--hot-hbo  בונה את חתימת ה-HBO **מהנתונים של TMDB** ולא מהזיכרון: שולף את
           רשימת הסדרות של HBO ושל Max לפי שיוך הרשת, בעברית ובאנגלית, ומחפש
           אותן בכותרות *וגם בתקצירים* של HOT. הפלט מציג גם דוגמאות מהרשימה
           שנשלפה, כדי שאם מזהה הרשת שגוי זה ייראה ולא ייחשב לתשובה.
           דורש TMDB_API_KEY בסביבה או ב-/opt/zovex-bot/.env. המפתח אינו
           מודפס בשום מצב.

    python3 fix_channel_meta.py --hot-hbo
    python3 fix_channel_meta.py --hot-fingerprint --unmapped
    python3 fix_channel_meta.py --hot-hunt ufc
    python3 fix_channel_meta.py --hot-hunt hbo --days 2
    python3 fix_channel_meta.py --hot-dump 215
    python3 fix_channel_meta.py --list
    python3 fix_channel_meta.py --scan-all --pattern 'hbo|סלקום|ufc|לחימה'
    python3 fix_channel_meta.py --epg-scan
    python3 fix_channel_meta.py --thumbs --check
    python3 fix_channel_meta.py --thumbs
    python3 fix_channel_meta.py --thumbs --revert
"""
import argparse, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

DATA = Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
VERSION = DATA / "content_version.txt"
BACKUP = CONTENT.with_name("content.json.bak_meta")
LOGOS = "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel"

# (שם בקטלוג, slug, כתובת לוגו)
# ה-slug נבחר בהתאמה לדפוס הקיים: sport5 / 5gold / 5STARS.
META = [
    ("ספורט 5 פלוס", "5plus", f"{LOGOS}/5plus-il.png"),
    # אין לוגו נפרד ל-Max במאגר. עד שיהיה — אותו לוגו של ספורט 5,
    # שכבר מוגש אצלך ועובד. עדיף מרובע ריק, ואפשר להחליף בפאנל.
    ("ספורט 5 מקס", "5max", "/zovex/live-logos/sport5.png?v=2"),
]

# provider הוא מספר ולא מילה: 3=yes, 2=hot. שליחת "yes"/"hot" מחזירה 400,
# וזו הייתה הטעות בגרסה הראשונה — לא חסימה גיאוגרפית כפי שהנחתי.
# מועתק מ-fetch_walla ב-epg_build.py, שעובד בפועל.
WALLA = "https://dal.walla.co.il/tv/list?provider={p}"
PROVIDERS = {3: "yes", 2: "hot"}
UA_STR = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def http_ok(url: str) -> bool:
    if url.startswith("/"):
        return True            # נתיב מקומי באתר — נבדק ע"י הדפדפן
    r = subprocess.run(["curl", "-sS", "-m", "15", "-o", "/dev/null",
                        "-w", "%{http_code}", url], capture_output=True, text=True)
    return (r.stdout or "").strip() == "200"


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True); raise


def epg_scan(pattern: str) -> None:
    """מדפיס channel_code לכל ערוץ ששמו מתאים, להשלמה ל-MAP."""
    import urllib.request
    rx = re.compile(pattern, re.I)
    found = []
    for code, label in PROVIDERS.items():
        try:
            req = urllib.request.Request(
                WALLA.format(p=code),
                headers={"User-Agent": UA_STR,
                         "Referer": "https://tv-guide.walla.co.il/"})
            with urllib.request.urlopen(req, timeout=40) as r:
                data = json.loads(r.read()).get("data", [])
        except Exception as e:
            print(f"  {label} (provider={code}): נכשל — {type(e).__name__}: {e}")
            continue
        print(f"  {label} (provider={code}): {len(data)} ערוצים")
        for ch in data:
            if not isinstance(ch, dict):
                continue
            cc = ch.get("channel_code")
            nm = (ch.get("channel_name") or ch.get("name")
                  or ch.get("title") or "").strip()
            if cc is None or not nm:
                continue
            if rx.search(nm):
                n = len(ch.get("schedule") or [])
                found.append((nm, cc, label, n))

    if not found:
        print("\nאין התאמה. הרחב עם --pattern, למשל --pattern '5|ספורט'")
        return
    print(f"\n{len(found)} התאמות — להוסיף ל-MAP ב-epg_build.py:\n")
    seen = set()
    for nm, cc, prov, n in sorted(found, key=lambda x: x[0]):
        if (nm, cc) in seen:
            continue
        seen.add((nm, cc))
        note = f"# {nm}  [{prov}, {n} תוכניות]"
        print(f'    "<slug>": ("w", {cc}),'.ljust(32) + note)
    print("\nהחלף <slug> ב-custom_slug של הערוץ אצלנו (למשל 5plus, 5max).")


HOT_API = ("https://www.hot.net.il/HotCmsApiFront/api/"
           "ProgramsSchedual/GetProgramsSchedual")

def _hot_day(day: str) -> dict:
    """יום אחד מלוח השידורים של HOT. HOT מפנה בלופ מחוץ לישראל, ולכן זה
    חייב לרוץ מהשרת — בשונה מוואלה, שם ה-400 היה פרמטר שגוי שלי."""
    import urllib.request
    body = json.dumps({"ProgramsStartDateTime": f"{day} 00:00:00",
                       "ProgramsEndDateTime": f"{day} 23:59:59"}).encode()
    req = urllib.request.Request(
        HOT_API, data=body, method="POST",
        headers={"User-Agent": UA_STR, "Content-Type": "application/json",
                 "Referer": "https://www.hot.net.il/heb/tv/tvguide/"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


HOT_CACHE_HOURS = 6

def hot_programs(days: int = 1) -> list:
    """כל התוכניות של HOT ל-days ימים, עם מטמון על הדיסק.

    יום אחד הוא כ-9.5MB, ולכן כל סריקה חוזרת הייתה מורידה הכל מחדש. המטמון
    הוא בן 6 שעות, וכך אפשר להריץ כמה חיפושים בזה אחר זה בלי לחכות.
    """
    from datetime import datetime, timedelta
    cache = DATA / "hot-epg-raw.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < HOT_CACHE_HOURS * 3600:
        try:
            got = json.loads(cache.read_text(encoding="utf-8"))
            if got.get("days", 0) >= days and got.get("programs"):
                age = (time.time() - cache.stat().st_mtime) / 3600
                print(f"  (מטמון מלפני {age:.1f} שעות · {len(got['programs'])} תוכניות)")
                return got["programs"]
        except Exception:
            pass
    progs, today = [], datetime.now().date()
    for i in range(days):
        day = (today + timedelta(days=i)).strftime("%Y/%m/%d")
        try:
            res = _hot_day(day)
        except Exception as e:
            print(f"  HOT {day} נכשל — {type(e).__name__}: {e}")
            continue
        progs += (res.get("data") or {}).get("programsDetails") or []
    if progs:
        try:
            DATA.mkdir(parents=True, exist_ok=True)
            atomic_write(cache, json.dumps({"days": days, "programs": progs},
                                           ensure_ascii=False))
        except Exception as e:
            print(f"  (לא הצלחתי לשמור מטמון: {e})")
    return progs


def _our_hot_ids() -> dict:
    """{channelID של HOT: slug אצלנו} מתוך ה-MAP, אם epg_build נגיש."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import epg_build as E
    except Exception:
        return {}
    out = {}
    for slug, v in E.MAP.items():
        for src, cid in (v if isinstance(v, list) else [v]):
            if src == "h":
                out.setdefault(str(cid), []).append(slug)
    return {k: ", ".join(v) for k, v in out.items()}


# ── חתימת HBO מתוך TMDB ולא מתוך הזיכרון שלי ─────────────────────────────
# החתימה שכתבתי ביד החזירה 0 מתוך 41,326 תוכניות, וזה מלמד שניחשתי לא נכון
# אילו סדרות משודרות שם. TMDB מחזיק את השיוך של סדרה לרשת, ולכן אפשר לשלוף
# את רשימת הסדרות של HBO ושל Max *מהנתונים* — כולל השם העברי, שהוא מה שיופיע
# בלוח של HOT. זו עדות ולא ניחוש.
TMDB_API = "https://api.themoviedb.org/3"
TMDB_NETWORKS = {49: "HBO", 3186: "Max"}
ENV_PATHS = ["/opt/zovex-bot/.env", ".env"]

def _tmdb_key() -> str:
    """המפתח מהסביבה או מ-.env. **אינו מודפס בשום מצב.**"""
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


def hbo_titles(pages: int = 5) -> list:
    """שמות הסדרות של HBO ושל Max לפי TMDB, בעברית ובאנגלית."""
    import urllib.request, urllib.parse
    key = _tmdb_key()
    if not key:
        print("  אין TMDB_API_KEY בסביבה ולא ב-.env — אי אפשר לבנות חתימה מהנתונים.")
        return []
    out, sample = set(), {}
    for net, label in TMDB_NETWORKS.items():
        for lang in ("he-IL", "en-US"):
            for page in range(1, pages + 1):
                q = urllib.parse.urlencode({
                    "api_key": key, "with_networks": net, "language": lang,
                    "sort_by": "popularity.desc", "page": page})
                try:
                    req = urllib.request.Request(f"{TMDB_API}/discover/tv?{q}",
                                                 headers={"User-Agent": UA_STR})
                    with urllib.request.urlopen(req, timeout=40) as r:
                        res = json.loads(r.read())
                except Exception as e:
                    print(f"  TMDB {label}/{lang} עמוד {page} נכשל — {type(e).__name__}")
                    break
                rows = res.get("results") or []
                for s in rows:
                    for k in ("name", "original_name"):
                        t = (s.get(k) or "").strip()
                        # שמות קצרים מדי הופכים לרעש: "Max" או "בית" יתפסו
                        # חצי מהלוח של כל ערוץ.
                        if len(t) >= 5:
                            out.add(t)
                            s6 = sample.setdefault(label, [])
                            if page == 1 and len(s6) < 6 and t not in s6:
                                s6.append(t)
                if page >= (res.get("total_pages") or 1):
                    break
    print(f"  נבנתה חתימה מ-{len(out)} שמות סדרות לפי TMDB")
    # מדפיסים דוגמאות כדי שאם מזהה הרשת שגוי זה ייראה כאן ולא ייחשב לתשובה.
    for label, ex in sample.items():
        print(f"    {label}: {' · '.join(ex[:6])}")
    if not sample:
        print("    ⚠ לא חזרו שמות בכלל — בדוק שמזהי הרשתות נכונים.")
    return sorted(out)


def hot_hbo(days: int = 1, pages: int = 5, top: int = 10) -> None:
    """מחפש את HOT HBO בלוח של HOT לפי רשימת הסדרות של הרשת מ-TMDB."""
    titles = hbo_titles(pages)
    if not titles:
        return
    rx = re.compile("|".join(re.escape(t) for t in titles), re.I)
    by_ch, hits = {}, {}
    for p in hot_programs(days):
        cid = str(p.get("channelID"))
        t = (p.get("programTitle") or "").strip()
        by_ch.setdefault(cid, []).append(t)
        # גם התקציר, כי HOT כותב את השם הלועזי שם גם כשהכותרת מתורגמת
        blob = f"{t} {(p.get('synopsis') or '')}"
        m = rx.search(blob)
        if m:
            hits.setdefault(cid, []).append(f"{t} → {m.group(0)}")
    if not by_ch:
        print("  לא התקבלו נתונים מ-HOT.")
        return
    if not hits:
        print(f"\n  אף אחד מ-{len(by_ch)} ערוצי HOT אינו משדר סדרה של HBO או Max.")
        print("  הפעם זו תשובה על הערוץ ולא על החתימה: הרשימה באה מ-TMDB.")
        print("  המשמעות: ל-HOT HBO אין לוח לינארי ב-HOT, וכנראה הוא VOD.")
        return
    rank = sorted(((len(v) / len(by_ch[c]), len(v), len(by_ch[c]), c)
                   for c, v in hits.items()), reverse=True)
    print(f"\n  {len(rank)} ערוצים עם סדרות של HBO/Max, לפי שיעור מתוך הלוח:\n")
    for pct, n, tot, cid in rank[:top]:
        print(f'    "hot-hbo": ("h", "{cid}"),'.ljust(36)
              + f"# {n}/{tot} = {pct*100:.0f}% · {hits[cid][0][:52]}")
    print("\n  שיעור גבוה = זה HOT HBO. שיעור נמוך = ערוץ שקנה סדרה אחת.")


def hot_fingerprint(days: int = 1, only_unmapped: bool = False, top: int = 3) -> None:
    """טביעת אצבע לכל אחד מ-208 ערוצי HOT: הכותרות שחוזרות בו הרבה.

    למה זה הכלי הנכון ל-HOT HBO: חיפוש לפי חתימת תוכן עובד רק אם ניחשתי
    נכון מה הערוץ משדר, וחתימת ה-HBO שכתבתי החזירה 0 מתוך 41,326 תוכניות —
    זה אומר שהחתימה שלי הייתה שגויה, לא שהערוץ אינו קיים. טביעת אצבע אינה
    מניחה כלום: היא מציגה את הלוח עצמו, והזיהוי נעשה בעין.

    הסדר אינו לפי מזהה אלא לפי *ריכוזיות* — איזה שיעור מהלוח תופסות שלוש
    הכותרות החוזרות ביותר. ערוץ סדרות יוצא גבוה, ערוץ סרטים מתחלפים נמוך.
    """
    from collections import Counter
    progs = hot_programs(days)
    if not progs:
        print("  לא התקבלו נתונים מ-HOT.")
        return
    ours = _our_hot_ids()
    by = {}
    for p in progs:
        by.setdefault(str(p.get("channelID")), []).append(
            (p.get("programTitle") or "").strip())
    rows = []
    for cid, titles in by.items():
        if only_unmapped and cid in ours:
            continue
        c = Counter(t for t in titles if t)
        best = c.most_common(top)
        conc = sum(n for _, n in best) / max(len(titles), 1)
        rows.append((conc, cid, len(titles), best))
    rows.sort(reverse=True)
    print(f"  HOT: {len(by)} ערוצים · {len(progs)} תוכניות · "
          f"{len(ours)} מזהים כבר ב-MAP שלנו")
    print(f"  מוצגים {len(rows)} ערוצים"
          + (" שאינם ממופים אצלנו" if only_unmapped else "") + ", לפי ריכוזיות:\n")
    for conc, cid, n, best in rows:
        tag = f"  ← {ours[cid]}" if cid in ours else ""
        titles = " · ".join(f"{t[:26]}×{k}" for t, k in best)
        print(f"    {cid:>5} [{n:>4}] {conc*100:>3.0f}%  {titles}{tag}")
    print("\n  מזהה שהלוח שלו הוא סדרות HBO — זה HOT HBO. שלח לי את השורה.")
    print("  לוח מלא של מזהה אחד:  --hot-dump <channelID> --days 1")


def hot_scan(pattern: str) -> None:
    """מדפיס channelID לכל ערוץ של HOT ששמו מתאים — אם בכלל יש שמות.

    נמדד בפועל: התשובה מכילה 'programsDetails' בלבד, וכל תוכנית נושאת
    channelID **בלי שם ערוץ**. לכן המסלול הזה בדרך כלל אינו מוצא כלום,
    וזיהוי ערוץ ב-HOT נעשה לפי תוכן — ראה hot_hunt.
    """
    from datetime import datetime
    day = datetime.now().strftime("%Y/%m/%d")
    try:
        res = _hot_day(day)
    except Exception as e:
        print(f"  HOT נכשל — {type(e).__name__}: {e}")
        return
    data = res.get("data") or {}
    progs = data.get("programsDetails") or []
    names = {}
    for p in progs:
        cid = p.get("channelID")
        nm = (p.get("channelName") or p.get("channel_name")
              or p.get("channelTitle") or "")
        if cid is not None and nm:
            names[str(cid)] = nm
    # לא בטוח ששם הערוץ יושב על התוכנית. אם לא — מחפשים רשימת ערוצים נפרדת
    # בתשובה, ואם גם היא אינה שם, מדפיסים את מבנה התשובה כדי שאפשר יהיה
    # לכתוב את הקוד הנכון בלי לנחש.
    if not names:
        for k, v in data.items():
            if not isinstance(v, list) or not v or not isinstance(v[0], dict):
                continue
            for row in v:
                cid = (row.get("channelID") or row.get("channelId")
                       or row.get("id"))
                nm = (row.get("channelName") or row.get("name")
                      or row.get("title") or "")
                if cid is not None and nm:
                    names[str(cid)] = nm
            if names:
                print(f"  (שמות הערוצים נלקחו מ-data['{k}'])")
                break
    print(f"  HOT: {len(progs)} תוכניות · {len(names)} ערוצים")
    if not names:
        print(f"  HOT אינו מחזיר שמות ערוצים — מפתחות data: {list(data)}")
        if progs:
            print(f"     שדות בתוכנית: {list(progs[0])}")
        print("     זה מצב תקין ולא תקלה: זיהוי ערוץ ב-HOT נעשה לפי תוכן.")
        print("     השתמש ב---hot-hunt, שמחפש בכותרות התוכניות עצמן.")
        return
    rx = re.compile(pattern, re.I)
    hits = [(nm, cid) for cid, nm in names.items() if rx.search(nm)]
    if not hits:
        print(f"  אין התאמה מבין {len(names)} ערוצי HOT. הרחב עם --pattern")
        return
    print(f"\n  {len(hits)} התאמות — להוסיף ל-MAP ב-epg_build.py:\n")
    for nm, cid in sorted(hits):
        print(f'    "<slug>": ("h", "{cid}"),'.ljust(36) + f"# {nm}")


# ── זיהוי ערוץ ב-HOT לפי תוכן ────────────────────────────────────────────
# HOT אינו מחזיר שמות ערוצים בכלל, ולכן חיפוש לפי שם הערוץ אינו אפשרי שם.
# כך זוהו גם המזהים שכבר ב-MAP (קומיט 579943f): לא לפי דמיון שמות אלא לפי
# הצלבת כותרות תוכניות באותן שעות. hot_hunt עושה את אותו הדבר הפוך —
# מחפש חתימת תוכן בכותרות ומדווח אילו channelID מכילים אותה.
#
# למה זה עובד לערוצים שאין להם מקור אחר: ערוץ UFC משדר תוכניות שבשמן UFC,
# וערוץ HBO משדר את הסדרות של HBO. זו עדות ישירה לזהות הערוץ, ולא ניחוש.
HOT_SIGNATURES = {
    "ufc": r"\bUFC\b|אוקטגון|קרב ראווה|Dana White",
    "hbo": (r"משחקי הכ[וח]|Game of Thrones|יורופוריה|Euphoria|"
            r"ה?לוואיט לוטוס|White Lotus|The Last of Us|האחרונים מבין|"
            r"וסטוורלד|Westworld|סוקסשן|Succession|בית הדרקון|House of the Dragon|"
            r"צ'רנוביל|Chernobyl|בארי|Barry|האנטורא?ז'|Entourage|"
            r"סקס והעיר הגדולה|Sex and the City|הסופרנוס|Sopranos|"
            r"בוארדווק|Boardwalk|True Detective|הבלש האמיתי|HBO"),
    "kids": (r"פ?פא פיג|Peppa|בלואי|Bluey|פו הדב|דורה|Dora|"
             r"פו?קימון|Pokemon|סטיץ'|במבה|ילדותי|מיקי מאוס|Mickey"),
}

def hot_hunt(sig: str, days: int = 1, top: int = 8) -> None:
    """מדפיס אילו channelID ב-HOT משדרים תוכניות שמתאימות לחתימת תוכן.

    sig הוא שם מ-HOT_SIGNATURES או ביטוי רגולרי משלך.
    """
    rx = re.compile(HOT_SIGNATURES.get(sig.lower(), sig), re.I)
    by_ch, hits = {}, {}
    for p in hot_programs(days):
        cid = str(p.get("channelID"))
        title = (p.get("programTitle") or "").strip()
        by_ch.setdefault(cid, []).append(title)
        if title and rx.search(title):
            hits.setdefault(cid, []).append(title)
    if not by_ch:
        print("  לא התקבלו נתונים מ-HOT.")
        return
    print(f"  HOT: {len(by_ch)} ערוצים · {sum(len(v) for v in by_ch.values())} תוכניות")
    print(f"  חתימה: {rx.pattern[:70]}{'…' if len(rx.pattern) > 70 else ''}")
    if not hits:
        print("\n  אף ערוץ ב-HOT אינו משדר תוכניות שמתאימות לחתימה.")
        print("  זו תשובה אמיתית: הערוץ אינו בלוח של HOT, ואין להמציא לו קוד.")
        return
    # הדירוג הוא *שיעור* ולא מספר: ערוץ עם 3 מתוך 5 תוכניות הוא הערוץ
    # המבוקש, וערוץ עם 3 מתוך 200 רק שידר פעם אחת סרט מאותו סוג.
    rank = sorted(((len(v) / len(by_ch[c]), len(v), len(by_ch[c]), c)
                   for c, v in hits.items()), reverse=True)
    print(f"\n  {len(rank)} ערוצים עם התאמה, לפי שיעור מתוך הלוח שלהם:\n")
    for pct, n, tot, cid in rank[:top]:
        print(f'    "<slug>": ("h", "{cid}"),'.ljust(36)
              + f"# {n}/{tot} = {pct*100:.0f}% · לדוגמה: {hits[cid][0][:40]}")
    print("\n  שיעור גבוה = זה הערוץ. שיעור נמוך = הוא רק שידר פעם תוכנית כזו.")
    print("  הדפסת הלוח המלא של מזהה מסוים:  --hot-dump <channelID>")


def hot_dump(cid: str, days: int = 1) -> None:
    """מדפיס את הלוח המלא של channelID אחד ב-HOT, כדי לזהות אותו בעין."""
    rows = []
    for p in hot_programs(days):
        if str(p.get("channelID")) == str(cid):
            rows.append(((p.get("programStartTime") or "")[5:16],
                         (p.get("programTitle") or "").strip(),
                         (p.get("synopsis") or "").strip()[:60]))
    rows.sort()
    if not rows:
        print(f"  אין תוכניות ל-channelID {cid}.")
        return
    print(f"  channelID {cid} · {len(rows)} תוכניות\n")
    for t, title, syn in rows:
        print(f"    {t}  {title[:44]:<44} {syn}")


def list_names() -> None:
    """מדפיס את שמות הערוצים בכל מקור שיש לו שמות, בלי סינון.

    כשחיפוש לפי תבנית לא מוצא כלום, השאלה הבאה היא תמיד 'אז מה כן יש שם' —
    וזו התשובה. HOT אינו כאן כי אין לו שמות בכלל.
    """
    import urllib.request
    print("\n  ── וואלה ──")
    for code, label in PROVIDERS.items():
        try:
            req = urllib.request.Request(
                WALLA.format(p=code),
                headers={"User-Agent": UA_STR,
                         "Referer": "https://tv-guide.walla.co.il/"})
            with urllib.request.urlopen(req, timeout=40) as r:
                data = json.loads(r.read()).get("data", [])
        except Exception as e:
            print(f"     provider={code} נכשל — {e}")
            continue
        print(f"     provider={code} ({label}) · {len(data)} ערוצים")
        for ch in sorted(data, key=lambda c: str(c.get("channel_name") or "")):
            print(f"       {str(ch.get('channel_code')):<7} "
                  f"{(ch.get('channel_name') or '').strip()}")
    print("\n  ── FreeTV ──")
    try:
        req = urllib.request.Request(FTV_LIVES, headers={"User-Agent": UA_STR})
        with urllib.request.urlopen(req, timeout=60) as r:
            items = json.loads(r.read()).get("items") or []
        print(f"     {len(items)} ערוצים")
        for c in sorted(items, key=lambda x: str(x.get("title"))):
            print(f"       {c.get('id'):<9} {(c.get('title') or '').strip()}")
    except Exception as e:
        print(f"     נכשל — {e}")
    print("\n  ── yes (התצלום שעל השרת) ──")
    f = DATA / "yes-epg.json"
    if not f.exists():
        print(f"     אין תצלום ב-{f}")
        return
    try:
        chans = (json.loads(f.read_text(encoding="utf-8")).get("channels") or {})
    except Exception as e:
        print(f"     קריאה נכשלה — {e}")
        return
    print(f"     {len(chans)} ערוצים")
    for cid, ch in sorted(chans.items(), key=lambda kv: str(kv[1].get("name"))):
        print(f"       {cid:<7} {str(ch.get('name') or '').strip():<40} "
              f"[{len(ch.get('programs') or [])} תוכניות]")


def yes_scan(pattern: str) -> None:
    """מחפש בתצלום של yes שיושב על השרת. אין כאן בקשת רשת — הקובץ נאסף
    מהדפדפן ע"י yes_harvest.js, כי Akamai חוסמת שם כל גישה שאינה דפדפן."""
    f = DATA / "yes-epg.json"
    if not f.exists():
        print(f"  yes: אין תצלום ב-{f} — הרץ את yes_harvest.js בדפדפן")
        return
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  yes: קריאת {f.name} נכשלה — {e}")
        return
    chans = raw.get("channels") or {}
    print(f"  yes: {len(chans)} ערוצים בתצלום")
    rx = re.compile(pattern, re.I)
    hits = [(str(ch.get("name") or ""), cid, len(ch.get("programs") or []))
            for cid, ch in chans.items() if rx.search(str(ch.get("name") or ""))]
    if not hits:
        print(f"  אין התאמה מבין {len(chans)} ערוצי yes. הרחב עם --pattern")
        return
    print(f"\n  {len(hits)} התאמות — להוסיף ל-MAP ב-epg_build.py:\n")
    for nm, cid, n in sorted(hits):
        print(f'    "<slug>": ("y", "{cid}"),'.ljust(36) + f"# {nm}  [{n} תוכניות]")


FTV_LIVES = "https://web.freetv.tv/api/products/lives?platform=BROWSER&maxResults=200"

def free_scan(pattern: str) -> None:
    """רשימת הערוצים של FreeTV. פתוחה, בלי הרשמה ובלי חסימה גיאוגרפית —
    זה המקור היחיד מהארבעה שאפשר לשאול גם מחוץ לישראל."""
    import urllib.request
    try:
        req = urllib.request.Request(FTV_LIVES, headers={"User-Agent": UA_STR})
        with urllib.request.urlopen(req, timeout=60) as r:
            items = json.loads(r.read()).get("items") or []
    except Exception as e:
        print(f"  FreeTV נכשל — {type(e).__name__}: {e}")
        return
    print(f"  FreeTV: {len(items)} ערוצים")
    rx = re.compile(pattern, re.I)
    hits = [((c.get("title") or "").strip(), c.get("id")) for c in items
            if rx.search((c.get("title") or ""))]
    if not hits:
        print(f"  אין התאמה מבין {len(items)} ערוצי FreeTV. הרחב עם --pattern")
        return
    print(f"\n  {len(hits)} התאמות — להוסיף ל-MAP ב-epg_build.py:\n")
    for nm, cid in sorted(hits):
        print(f'    "<slug>": ("f", {cid}),'.ljust(36) + f"# FreeTV {nm}")


def do_thumbs(check: bool) -> None:
    if not CONTENT.exists():
        sys.exit(f"לא נמצא: {CONTENT}")
    items = json.loads(CONTENT.read_text(encoding="utf-8"))
    by_title = {}
    for i in items:
        by_title.setdefault((i.get("title") or "").strip(), i)

    plan, missing = [], []
    for title, slug, logo in META:
        it = by_title.get(title)
        if it is None:
            missing.append(title)
            continue
        ok = http_ok(logo)
        cur_t = it.get("thumbnail_url") or ""
        cur_s = it.get("custom_slug") or ""
        if not ok:
            print(f"⚠ הלוגו של {title} לא נגיש ({logo}) — מדלג על התמונה")
        new = {}
        if ok and cur_t != logo:
            new["thumbnail_url"] = logo
        if cur_s != slug:
            new["custom_slug"] = slug
        if new:
            plan.append((it, title, new, cur_t, cur_s))

    print("=" * 62)
    for _, title, new, cur_t, cur_s in plan:
        print(f"\n  {title}")
        if "thumbnail_url" in new:
            print(f"     לוגו:  {cur_t or '(ריק)'}")
            print(f"        →   {new['thumbnail_url']}")
        if "custom_slug" in new:
            print(f"     slug:  {cur_s or '(ריק)'}  →  {new['custom_slug']}")
    if missing:
        print(f"\n⚠ לא בקטלוג: {', '.join(missing)}")
    print("\n" + "=" * 62)
    if not plan:
        print("אין מה לשנות.")
        return
    if check:
        print("--check: שום דבר לא נכתב.")
        return

    shutil.copy2(CONTENT, BACKUP)
    for it, _, new, _, _ in plan:
        it.update(new)
    atomic_write(CONTENT, json.dumps(items, ensure_ascii=False, indent=2))
    try:
        v = int(VERSION.read_text().strip()) + 1 if VERSION.exists() else 1
    except Exception:
        v = int(time.time())
    atomic_write(VERSION, str(v))
    print(f"✓ עודכנו {len(plan)} ערוצים · גיבוי: {BACKUP} · גרסה {v}")
    print("  הלוגו יופיע מיד. הלוח יופיע רק אחרי שה-slug ייכנס ל-MAP")
    print("  ב-epg_build.py וה-EPG ייבנה מחדש.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--thumbs", action="store_true")
    ap.add_argument("--epg-scan", action="store_true")
    ap.add_argument("--hot-scan", action="store_true",
                    help="רשימת הערוצים של HOT. חוסם מחוץ לישראל — להריץ מהשרת")
    ap.add_argument("--yes-scan", action="store_true",
                    help="התצלום של yes שיושב על השרת")
    ap.add_argument("--free-scan", action="store_true",
                    help="רשימת הערוצים של FreeTV. פתוחה מכל מקום")
    ap.add_argument("--scan-all", action="store_true",
                    help="כל ארבעת המקורות בזה אחר זה")
    ap.add_argument("--list", action="store_true",
                    help="שמות כל הערוצים בכל מקור שיש לו שמות, בלי סינון")
    ap.add_argument("--hot-hunt", metavar="SIG",
                    help="מזהה ערוץ ב-HOT לפי תוכן: ufc / hbo / kids, או רגקס")
    ap.add_argument("--hot-dump", metavar="CHANNELID",
                    help="הלוח המלא של channelID אחד ב-HOT")
    ap.add_argument("--hot-fingerprint", action="store_true",
                    help="טביעת אצבע לכל ערוצי HOT — הכותרות שחוזרות בכל אחד")
    ap.add_argument("--unmapped", action="store_true",
                    help="עם --hot-fingerprint: רק ערוצים שאינם ב-MAP שלנו")
    ap.add_argument("--hot-hbo", action="store_true",
                    help="מחפש את HOT HBO לפי רשימת הסדרות של הרשת מ-TMDB")
    ap.add_argument("--days", type=int, default=1,
                    help="כמה ימים למשוך מ-HOT (ברירת מחדל 1)")
    ap.add_argument("--pattern", default=r"ספורט\s*5|sport\s*5|5\s*(plus|max|\+)")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    if a.revert:
        if not BACKUP.exists():
            sys.exit(f"אין גיבוי ב-{BACKUP}")
        shutil.copy2(BACKUP, CONTENT)
        print(f"✓ שוחזר מ-{BACKUP}")
        return
    ran = False
    if a.list:
        print(f"\n{'─' * 62}\nכל הערוצים בכל המקורות\n{'─' * 62}")
        list_names()
        ran = True
    if a.hot_hunt:
        print(f"\n{'─' * 62}\nHOT · זיהוי לפי תוכן: {a.hot_hunt}\n{'─' * 62}")
        try:
            hot_hunt(a.hot_hunt, a.days)
        except Exception as e:
            print(f"  נפל — {type(e).__name__}: {e}")
        ran = True
    if a.hot_dump:
        print(f"\n{'─' * 62}\nHOT · הלוח של {a.hot_dump}\n{'─' * 62}")
        try:
            hot_dump(a.hot_dump, a.days)
        except Exception as e:
            print(f"  נפל — {type(e).__name__}: {e}")
        ran = True
    if a.hot_hbo:
        print(f"\n{'─' * 62}\nHOT HBO · חתימה מתוך TMDB\n{'─' * 62}")
        try:
            hot_hbo(a.days)
        except Exception as e:
            print(f"  נפל — {type(e).__name__}: {e}")
        ran = True
    if a.hot_fingerprint:
        print(f"\n{'─' * 62}\nHOT · טביעת אצבע לכל הערוצים\n{'─' * 62}")
        try:
            hot_fingerprint(a.days, a.unmapped)
        except Exception as e:
            print(f"  נפל — {type(e).__name__}: {e}")
        ran = True

    scans = [(a.epg_scan or a.scan_all, "וואלה", epg_scan),
             (a.free_scan or a.scan_all, "FreeTV", free_scan),
             (a.yes_scan or a.scan_all, "yes", yes_scan),
             (a.hot_scan or a.scan_all, "HOT", hot_scan)]
    for on, label, fn in scans:
        if not on:
            continue
        ran = True
        print(f"\n{'─' * 62}\n{label}  ·  תבנית: {a.pattern}\n{'─' * 62}")
        try:
            fn(a.pattern)
        except Exception as e:
            print(f"  {label} נפל — {type(e).__name__}: {e}")
    if a.thumbs:
        if ran:
            print()
        do_thumbs(a.check)
        ran = True
    if not ran:
        ap.print_help()


if __name__ == "__main__":
    main()
