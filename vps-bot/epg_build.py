#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בונה לוח שידורים (EPG) לערוצי השידור החי ומגיש אותו כקובץ מטמון epg.json.

מקורות:
  • וואלה  (dal.walla.co.il) — בקשה אחת ל-yes ואחת ל-HOT מחזירה את הלוח של
    *כל* הערוצים בבת אחת. זהו המקור העיקרי.
  • isramedia (www.isramedia.net) — משלים ערוצים שוואלה מפספסת (ספורט 2/3/4,
    ערוץ 24, C14). בקשה per-ערוץ, HTML בקידוד windows-1255.

מפתח לכל ערוץ = ה-slug (custom_slug) שלנו, כדי שהאתר/אפליקציה יתאימו לפי slug.
הזמנים נשמרים כ-epoch (שניות UTC) — הלקוח מחשב "עכשיו/הבא" מול השעון שלו, כך
שהלוח נשאר טרי גם בין ריצות. מריצים כל 2-3 שעות (cron / systemd timer).

הרצה:  python3 epg_build.py            → כותב /opt/zovex-bot/data/epg.json
        python3 epg_build.py --stdout   → מדפיס סיכום בלבד
"""
import json, re, sys, time, pathlib, urllib.request, urllib.parse
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
    IL = ZoneInfo("Asia/Jerusalem")
except Exception:                                  # פייתון ישן / בלי tzdata
    IL = None

DATA = pathlib.Path("/opt/zovex-bot/data")
# נכתב לתיקיית האתר הסטטית — nginx מגיש אותה ישירות תחת /epg.json (בלי proxy,
# בלי שינוי קוד בשרת). אם התיקייה לא קיימת (בדיקה מקומית) — נופל ל-DATA.
SITE = pathlib.Path("/opt/zovex-site")
OUT  = (SITE / "epg.json") if SITE.is_dir() else (DATA / "epg.json")

# ── מיפוי: slug שלנו → (מקור, מזהה) ─────────────────────────────────────
# 'w' = קוד וואלה ; 'i' = מזהה isramedia. ערוץ שאינו כאן — אין לו לוח לינארי
# (VOD / סרטים רצופים / ניש) ופשוט לא יוצג לו לוח.
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
    # דרמות טורקיות / ויוה
    "viva-istanbul": ("w", 208), "viva-vintage": ("w", 4358),
    "viva-telenovelas": ("w", 3588), "viva-premium": ("w", 4433),
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"

def _get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

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

# ── בנייה ────────────────────────────────────────────────────────────────
def build():
    walla = fetch_walla()
    print(f"וואלה: {len(walla)} ערוצים", file=sys.stderr)
    channels, w_hit, i_hit, empty = {}, 0, 0, 0
    isra_cache = {}
    for slug, (src, cid) in MAP.items():
        if src == "w":
            progs = walla.get(cid, [])
            if progs: w_hit += 1
        else:
            if cid not in isra_cache:
                isra_cache[cid] = fetch_isra(cid)
            progs = isra_cache[cid]
            if progs: i_hit += 1
        if not progs:
            empty += 1
        channels[slug] = {"source": "walla" if src == "w" else "isramedia",
                          "programs": progs}
    doc = {"generated": int(time.time()), "channels": channels}
    return doc, (w_hit, i_hit, empty)

def main():
    doc, (w_hit, i_hit, empty) = build()
    if "--stdout" in sys.argv:
        print(json.dumps({k: len(v["programs"]) for k, v in doc["channels"].items()},
                         ensure_ascii=False, indent=1))
    else:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        tmp = OUT.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        tmp.replace(OUT)                            # כתיבה אטומית
    total = sum(len(v["programs"]) for v in doc["channels"].values())
    print(f"נכתב {OUT.name}: {len(doc['channels'])} ערוצים "
          f"(וואלה {w_hit}, isramedia {i_hit}, ריקים {empty}) · {total} תוכניות")

if __name__ == "__main__":
    main()
