#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בונה לוח שידורים (EPG) לערוצי השידור החי ומגיש אותו כקובץ מטמון epg.json.

מקורות:
  • וואלה  (dal.walla.co.il) — בקשה אחת ל-yes ואחת ל-HOT מחזירה את הלוח של
    *כל* הערוצים בבת אחת. זהו המקור העיקרי.
  • isramedia (www.isramedia.net) — משלים ערוצים שוואלה מפספסת (ספורט 2/3/4,
    ערוץ 24, C14). בקשה per-ערוץ, HTML בקידוד windows-1255.
  • HOT (www.hot.net.il) — 208 ערוצים, יומיים קדימה, בשתי בקשות. נמשך
    אוטומטית. הם חוסמים גישה מחוץ לישראל (302 לדף הבית לכל בקשה, גם
    ל-robots.txt), אבל מהשרת שלנו ברמת גן זה עובר — נמדד 9.5MB תשובה.
  • yes (svc.yes.co.il) — תצלום ידני. Akamai חוסם שם כל גישה שאינה דפדפן
    אמיתי, כולל חיקוי טביעת TLS, ולכן הקובץ נאסף מהדפדפן (yes_harvest.js).
    התצלום מחזיק כיומיים, ולכן הוא לעולם לא המקור היחיד לערוץ — ראה FALLBACK.

מפתח לכל ערוץ = ה-slug (custom_slug) שלנו, כדי שהאתר/אפליקציה יתאימו לפי slug.
הזמנים נשמרים כ-epoch (שניות UTC) — הלקוח מחשב "עכשיו/הבא" מול השעון שלו, כך
שהלוח נשאר טרי גם בין ריצות. מריצים כל 2-3 שעות (cron / systemd timer).

הרצה:  python3 epg_build.py            → כותב /opt/zovex-bot/data/epg.json
        python3 epg_build.py --stdout   → מדפיס סיכום בלבד
"""
import json, re, sys, time, pathlib, urllib.request, urllib.parse
from datetime import datetime, timedelta
try:
    from zoneinfo import ZoneInfo
    IL = ZoneInfo("Asia/Jerusalem")
except Exception:                                  # פייתון ישן / בלי tzdata
    IL = None

DATA = pathlib.Path("/opt/zovex-bot/data")
# נכתב *מחוץ* לתיקיית האתר בכוונה: פריסת אתר מריצה
#     find /opt/zovex-site -mindepth 1 -delete
# ולכן קובץ שיושב שם נמחק בכל פריסה, ו-nginx מתחיל להחזיר את index.html
# במקום הלוח (נתפס בפועל). כאן הוא שורד פריסות; nginx מגיש אותו דרך
#     location = /epg.json { alias /opt/zovex-bot/data/epg.json; }
OUT = DATA / "epg.json"

# ── מיפוי: slug שלנו → (מקור, מזהה) ─────────────────────────────────────
# 'w' = קוד וואלה ; 'i' = מזהה isramedia ; 'h' = מזהה ערוץ ב-HOT ;
# 'y' = מזהה ערוץ בתצלום של yes.
#
# אפשר לתת *רשימה* של מקורות במקום אחד, והם ינוסו לפי הסדר: הראשון שיש לו
# תוכניות שעוד לא הסתיימו — מנצח. כך תצלום yes מספק את הכותרות המפורטות
# שלו כל עוד הוא טרי, וכשהוא מתיישן HOT נכנס תחתיו מעצמו בלי שנגע בכלום.
#
# ערוץ שאינו כאן — אין לו לוח לינארי (VOD / סרטים רצופים / ניש) ופשוט לא
# יוצג לו לוח.
MAP = {
    # חדשות וערוצים
    "mako12": ("w", 3819), "reshet13": ("w", 3826), "kan11": ("w", 3787),
    "makan-33": ("w", 3789), "channel9": ("w", 3714),
    "channel-24": ("i", 24), "c14": ("i", 14),
    # yes
    "yes-drama": ("w", 3045), "yes-comedy": ("w", 3555), "yes-action": ("w", 3046),
    "yes-doco": ("w", 301),
    # HOT
    "hot-comedy": ("w", 3727), "HOT3": ("w", 353), "HOTGOLD": ("w", 3587),
    "Hotbod": ("w", 349), "hot-drama": ("w", 3585), "hot-zone": ("w", 3579),
    # ספורט
    "One1": ("w", 3550), "One2": ("w", 4259),
    "sport-1": ("w", 3540), "sport-2": ("i", 91), "sport-3": ("i", 14950),
    "sport-4": ("i", 14951), "sport5": ("w", 521), "5gold": ("w", 66),
    "5STARS": ("w", 4271), "eurosport-2": ("w", 3536),
    # ילדים
    "nickelodeon": ("w", 517), "teen-nick": ("w", 3724), "nick-jr": ("w", 3639),
    "junior": ("w", 188), "disney-junior": ("w", 3672), "Disney": ("w", 3064),
    "baby": ("w", 3158), "lolly": ("w", 350), "hop": ("w", 212),
    # דוקו ולייף-סטייל
    "discovery": ("w", 3661), "natgeo": ("w", 149), "natgeo-wild": ("w", 3051),
    "history": ("w", 207), "food-network-hd": ("w", 543), "health": ("w", 544),
    "good-life": ("w", 198), "yam-tichoni": ("w", 3766), "e-channel": ("w", 334),
    "zoom-tv": ("w", 3635),
    # סרטים ובידור
    "cellcom1": ("w", 3678), "bollywood": ("w", 3175),
    "bait-plus": ("w", 504),
    # דרמות טורקיות / ויוה
    "viva-istanbul": ("w", 208), "viva-vintage": ("w", 4358),
    "viva-telenovelas": ("w", 3588), "viva-premium": ("w", 4433),

    # ── yes עם HOT מתחתיו ──────────────────────────────────────────────
    # שני המקורות אומתו זה מול זה: הושוו שמות התוכניות באותן שעות, וההתאמה
    # יצאה 78%–100% בכל אחד מאלה (רובם 100%), כלומר זה ודאי אותו ערוץ ולא
    # דמיון שמות. yes ראשון כי הכותרות שלו מפורטות יותר ("החתן - פרק 35"
    # מול "החתן" ב-HOT); HOT נכנס לבד כשהתצלום מתיישן.
    "Dramottorki": [("y", "CH70"), ("h", "551")],
    "Torki2": [("y", "CH80"), ("h", "615")],
    "turkish-drama-3": [("y", "CH77"), ("h", "655")],
    "turkish-plus": [("y", "PT60"), ("h", "333")],
    "turkish-plus-2": [("y", "TV20"), ("h", "038")],
    "turkish-plus-3": [("y", "CH75"), ("h", "584")],
    "indian-drama-1": [("y", "CN19"), ("h", "698")],
    "indian-drama-2": [("y", "CN20"), ("h", "699")],
    "spanish-drama-1": [("y", "CN30"), ("h", "673")],
    "spanish-drama-2": [("y", "CN31"), ("h", "730")],
    "star-channel": [("y", "CH19"), ("h", "600")],
    "knesset": [("y", "TV89"), ("h", "788")],
    "channel-98": [("y", "TV43"), ("h", "086")],
    "i24": [("y", "CN28"), ("h", "702")],
    "kaneducation": [("y", "CH57"), ("h", "484")],
    "Oneedge": [("y", "CHN3"), ("h", "642")],
    # ספורט 6: אותו ערוץ, אבל HOT מתאר גס ("ל. איטלקית") איפה ש-yes נותן
    # את המשחק עצמו ("יובנטוס - פארמה"). לכן HOT רק כרשת ביטחון.
    "Sport6": [("y", "CN48"), ("h", "154")],

    # ── yes בלבד ───────────────────────────────────────────────────────
    # אין להם מקביל ברשימת הערוצים של HOT.
    "yes-movies-action": ("y", "YSA2"), "yes-movies-comedy-fhd": ("y", "YSA3"),
    "yes-movies-drama-fhd": ("y", "YSA1"), "yes-movies-kids-fhd": ("y", "YSA4"),
    "yes-israeli": ("y", "YSAU"), "wiz": ("y", "CH13"),

    # ── מקור HOT ('h') ─────────────────────────────────────────────────
    # קריוקי היה ממופה בטעות ל-Music IL של yes (0% התאמה בהצלבה) — כאן
    # הוא מקבל את ערוץ הקריוקי האמיתי.
    "karaoke": ("h", "761"),
    # ערוצי HOT שלא היה להם לוח בשום מקור אחר.
    "HOT8": ("h", "286"),
    "Hotcinema": ("h", "129"), "Hotcinema2": ("h", "130"),
    "Hotcinema3": ("h", "131"), "Hotcinema4": ("h", "228"),
    # "HOT ריל" ו-"HOT Real" הם אותו ערוץ אצלנו פעמיים.
    "hot-real": ("h", "555"), "Hotril": ("h", "555"),
    # "הוט משפחה גיבוי" הוא גיבוי של אותו ערוץ.
    "hotfrns": ("h", "606"), "hot-family-backup": ("h", "606"),
}

# הלוח של yes נאסף מהדפדפן ונשמר כאן. ראה yes_harvest.js.
YES_FILE = DATA / "yes-epg.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"

def _get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def _post_json(url, payload, headers=None, timeout=90):
    body = json.dumps(payload).encode()
    h = {"User-Agent": UA, "Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def _il_epoch(s):
    """'2026-08-27 00:50:00' (שעון ישראל) → epoch שניות UTC."""
    dt = datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S")
    if IL:
        return int(dt.replace(tzinfo=IL).timestamp())
    return int(dt.timestamp())                     # fallback: הנחת שעון-מקומי=IL

# ── וואלה ────────────────────────────────────────────────────────────────
def fetch_walla():
    """מחזיר {code: [ {start,end,title,desc}... ]} לשני הספקים."""
    out = {}
    for prov in (3, 2):                            # 3=yes, 2=hot
        try:
            raw = _get(f"https://dal.walla.co.il/tv/list?provider={prov}",
                       headers={"User-Agent": UA,
                                "Referer": "https://tv-guide.walla.co.il/"})
            data = json.loads(raw).get("data", [])
        except Exception as e:
            print(f"  ⚠ וואלה provider={prov} נכשל: {e}", file=sys.stderr); continue
        for ch in data:
            code = ch.get("channel_code")
            progs = []
            for p in (ch.get("schedule") or []):
                try:
                    progs.append({
                        "start": _il_epoch(p["start_time"]),
                        "end":   _il_epoch(p["end_time"]),
                        "title": (p.get("title_name") or "").strip(),
                        "desc":  (p.get("synopsis") or "").strip(),
                    })
                except Exception:
                    continue
            if code is not None:
                out[code] = progs
    return out

# ── isramedia ────────────────────────────────────────────────────────────
_ISRA_ROW = re.compile(
    r'<time[^>]*datetime="([^"]+)"[^>]*>\s*(\d{2}:\d{2})\s*</time>'   # זמן מוחלט
    r'.*?tvguideshowname[^>]*>([^<]+)<',                              # שם התוכנית
    re.S)

def _iso_epoch(s):
    # '2026-08-27T03:10:00+03:00' → epoch
    try:
        return int(datetime.fromisoformat(s).timestamp())
    except Exception:
        return None

def fetch_isra(cid):
    path = urllib.parse.quote(f"/לוח-שידורים/{cid}/x")
    try:
        raw = _get(f"https://www.isramedia.net{path}").decode("windows-1255", "replace")
    except Exception as e:
        print(f"  ⚠ isramedia {cid} נכשל: {e}", file=sys.stderr); return []
    rows = []
    for dt, _disp, name in _ISRA_ROW.findall(raw):
        ep = _iso_epoch(dt)
        if ep:
            rows.append({"start": ep, "title": name.strip(), "desc": ""})
    rows.sort(key=lambda r: r["start"])
    for i, r in enumerate(rows):                    # end = תחילת הבא
        r["end"] = rows[i + 1]["start"] if i + 1 < len(rows) else r["start"] + 3600
    return rows

# ── HOT ──────────────────────────────────────────────────────────────────
HOT_API = ("https://www.hot.net.il/HotCmsApiFront/api/"
           "ProgramsSchedual/GetProgramsSchedual")
HOT_DAYS = 2

def fetch_hot(want=None):
    """מחזיר {channelID: [ {start,end,title,desc}... ]} מהלוח של HOT.

    בקשה אחת ליום מחזירה את *כל* הערוצים (כ-20,000 תוכניות, 9.5MB), ולכן
    מסננים מיד ל-want כדי לא להחזיק את הכל בזיכרון. הזמנים שם הם שעון
    ישראל בפורמט '2026/08/30 03:00:00'.
    """
    out = {}
    today = (datetime.now(IL) if IL else datetime.now()).date()
    for i in range(HOT_DAYS):
        day = (today + timedelta(days=i)).strftime("%Y/%m/%d")
        try:
            res = _post_json(HOT_API,
                             {"ProgramsStartDateTime": f"{day} 00:00:00",
                              "ProgramsEndDateTime":   f"{day} 23:59:59"},
                             headers={"Referer": "https://www.hot.net.il/heb/tv/tvguide/"})
        except Exception as e:
            print(f"  ⚠ HOT {day} נכשל: {e}", file=sys.stderr); continue
        for p in ((res.get("data") or {}).get("programsDetails") or []):
            cid = p.get("channelID")
            if want and cid not in want:
                continue
            try:
                out.setdefault(cid, []).append({
                    "start": _il_epoch(p["programStartTime"].replace("/", "-")),
                    "end":   _il_epoch(p["programEndTime"].replace("/", "-")),
                    "title": (p.get("programTitle") or "").strip(),
                    "desc":  (p.get("synopsis") or "").strip(),
                })
            except Exception:
                continue
    for cid, progs in out.items():
        seen, uniq = set(), []
        for p in sorted(progs, key=lambda x: x["start"]):
            k = (p["start"], p["title"])
            if k not in seen:
                seen.add(k); uniq.append(p)
        out[cid] = uniq
    return out

# ── בנייה ────────────────────────────────────────────────────────────────
def load_yes():
    """קורא את הלוח של yes שנאסף מהדפדפן. מחזיר {channel_id: [תוכניות]}.

    הזמנים שם הם ISO ב-UTC ('2026-08-30T03:00:00Z') — ממירים ל-epoch כמו
    בשאר המקורות, כדי שהלקוח יקבל מבנה אחיד.
    """
    if not YES_FILE.exists():
        return {}
    try:
        raw = json.loads(YES_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ⚠ קריאת {YES_FILE.name} נכשלה: {e}", file=sys.stderr)
        return {}
    out = {}
    for cid, ch in (raw.get("channels") or {}).items():
        progs = []
        for p in ch.get("programs") or []:
            try:
                s = datetime.fromisoformat(p["start"].replace("Z", "+00:00"))
                e = datetime.fromisoformat(p["end"].replace("Z", "+00:00"))
                progs.append({"start": int(s.timestamp()), "end": int(e.timestamp()),
                              "title": (p.get("title") or "").strip(),
                              "desc": (p.get("desc") or "").strip()})
            except Exception:
                continue
        if progs:
            out[cid] = sorted(progs, key=lambda x: x["start"])
    return out


NAMES = {"w": "walla", "i": "isramedia", "y": "yes", "h": "hot"}

def _fresh(progs):
    """יש כאן לוח שימושי? כלומר תוכנית אחת לפחות שעוד לא הסתיימה.

    לא מספיק לשאול 'יש תוכניות' — תצלום yes ממשיך להחזיר תוכניות גם אחרי
    שהתיישן, כולן בעבר. במצב כזה הערוץ ייראה ריק למשתמש, ולכן צריך ליפול
    למקור הבא ולא להיתקע על הראשון.
    """
    now = time.time()
    return any(p.get("end", 0) > now for p in progs)


def build():
    walla = fetch_walla()
    yes = load_yes()
    # מושכים מ-HOT רק את הערוצים שבאמת ממופים אליו
    want = {cid for v in MAP.values()
            for src, cid in (v if isinstance(v, list) else [v]) if src == "h"}
    hot = fetch_hot(want)
    print(f"וואלה: {len(walla)} · yes: {len(yes)} · HOT: {len(hot)}/{len(want)} ערוצים",
          file=sys.stderr)

    channels, hits, empty, fell = {}, {k: 0 for k in NAMES}, 0, 0
    isra_cache = {}

    def get(src, cid):
        if src == "w":
            return walla.get(cid, [])
        if src == "y":
            return yes.get(cid, [])
        if src == "h":
            return hot.get(cid, [])
        if cid not in isra_cache:
            isra_cache[cid] = fetch_isra(cid)
        return isra_cache[cid]

    for slug, val in MAP.items():
        chain = val if isinstance(val, list) else [val]
        progs, used = [], chain[0][0]
        for n, (src, cid) in enumerate(chain):
            progs = get(src, cid)
            used = src
            if _fresh(progs):
                if n:
                    fell += 1
                break
        if _fresh(progs):
            hits[used] += 1
        else:
            empty += 1
        channels[slug] = {"source": NAMES[used], "programs": progs}
    doc = {"generated": int(time.time()), "channels": channels}
    return doc, (hits, empty, fell)

MERGE_KEEP_HOURS = 8      # כמה אחורה שומרים תוכניות שהסתיימו


def merge_previous(doc):
    """ממזג את הבנייה הקודמת לתוך החדשה.

    וואלה מגישה את לוח *היום*, והתוכנית הראשונה מתחילה אחרי חצות (נמדד:
    00:06 בערוץ ויוה, 01:10 בספורט 1). לכן מיד אחרי חצות התוכנית שרצה
    בפועל — זו שהתחילה אתמול — כבר לא נמצאת בנתונים, ו"עכשיו" יוצא ריק
    לשעה ויותר. מיזוג עם הקובץ הקודם סוגר את החור בלי אף בקשה נוספת.
    """
    if not OUT.exists():
        return doc
    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return doc
    cutoff = time.time() - MERGE_KEEP_HOURS * 3600
    for slug, ch in doc["channels"].items():
        prev = (old.get("channels", {}).get(slug) or {}).get("programs") or []
        if not prev:
            continue
        seen = {(p["start"], p["title"]) for p in ch["programs"]}
        extra = [p for p in prev
                 if p.get("end", 0) > cutoff and (p["start"], p["title"]) not in seen]
        if extra:
            ch["programs"] = sorted(ch["programs"] + extra, key=lambda p: p["start"])
    return doc


def main():
    doc, (hits, empty, fell) = build()
    doc = merge_previous(doc)
    if "--stdout" in sys.argv:
        print(json.dumps({k: len(v["programs"]) for k, v in doc["channels"].items()},
                         ensure_ascii=False, indent=1))
    else:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        tmp = OUT.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        tmp.replace(OUT)                            # כתיבה אטומית
    total = sum(len(v["programs"]) for v in doc["channels"].values())
    print(f"נכתב {OUT.name}: {len(doc['channels'])} ערוצים (וואלה {hits['w']}, "
          f"isramedia {hits['i']}, yes {hits['y']}, HOT {hits['h']}, ריקים {empty})"
          + (f" · {fell} ערוצים נפלו למקור גיבוי" if fell else "")
          + f" · {total} תוכניות")

if __name__ == "__main__":
    main()
