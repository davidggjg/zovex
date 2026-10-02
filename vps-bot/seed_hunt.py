#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""seed_hunt — מקישור אחד עובד, אל כל הערוצים. בלי לנחש.

## למה לא עוד סריקה עיוורת

הספק אמר שהחליף חוות שרתים ו"סיבב" את הקישורים — אולי מספרים, אולי גם
אותיות. ‎hunt_channels‎ סרק 1,200 מספרים והחזיר 0 עונים, וזה לא היה
במקרה: הוא סרק את **המארח הישן**, זה שמחזיר 403 גם על קישורים שעבדו
אתמול. סריקה שמתחילה בכתובת שגויה תיתן אפס על כל מספר, לנצח.

ושתי מגבלות שאין להתגבר עליהן בכוח:

* **403 אינו "מספר שגוי".** מספר שגוי מחזיר 404 או playlist ריק. 403
  אומר שהבקשה הגיעה, זוהתה ונדחתה — ואותה תשובה תתקבל על כל מספר.
* **אותיות מפוצצות את הסריקה.** בקצב של ‎hunt_channels‎ (4 במקביל,
  0.15ש׳ ⇒ ‎26.7‎ בקשות לשנייה), נמדד ולא מוערך:

      3 ספרות              1,000   פחות מדקה
      4 ספרות             10,000   6 דקות
      4 תווים a-z0-9   1,679,616   17.5 שעות
      4 עם רישיות     14,776,336   6.4 ימים
      5 תווים a-z0-9  60,466,176   26 ימים

  כלומר שלוש ספרות הן כלום, וכל תו **אות** מכפיל פי 3.6. ואפילו
  ה-17.5 שעות אינן באמת אפשרות: זו הלמות רצופה על ספק שממילא מסרב
  לנו, והדרך המהירה ביותר לעבור מחסימה זמנית לחסימה קבועה.

## מה כן עובד

קישור **אחד** עובד, עדכני, מהספק. מתוכו הסקריפט מוציא את כל השאר:

1. **מאמת** שהוא באמת מחזיר playlist. קישור מת כבסיס הוא בדיוק הטעות
   שהביאה לסריקה של 1,200 כלומים.
2. **מפרק** אותו: סכימה, מארח, פורט, נתיב, ומזהה הערוץ בתוכו — כולל
   האלפבית והאורך שלו בפועל.
3. **מבקש את הרשימה המלאה.** לרוב שערי ה-IPTV יש נתיב שמחזיר את כל
   הערוצים בבת אחת, והפרטים לגישה כבר נמצאים בקישור עצמו. בקשה אחת
   במקום מיליון — **וגם השמות מגיעים איתה**, כך שאין צורך בפריימים
   ובזיהוי ידני בכלל.
4. ואם אין רשימה — סורק רק את **השכנות** של המזהה שעבד, ומכין
   ‎fmt.txt‎ ל-‎hunt_channels‎ שימשיך משם עם הפריימים.

## שימוש

    python3 seed_hunt.py --link 'http://HOST:PORT/live/u/p/412.m3u8'
    python3 seed_hunt.py --link '...' --span 300     # ±300 סביב המזהה
    python3 seed_hunt.py --link '...' --list-only    # רק הרשימה
    python3 seed_hunt.py --selftest                  # בלי רשת

**הפלט ממוסך**: מארח, שם ספק, שם משתמש, סיסמה ואסימונים אינם מודפסים.
הקבצים נשארים על השרת בלבד.

קריאה בלבד: לא נוגע בקטלוג, בשירות ולא מריץ restart.
"""
import argparse
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

OUT = pathlib.Path(os.environ.get("SEED_OUT", "/tmp/hunt"))
UA = "VLC/3.0.20 LibVLC/3.0.20"

_GENERIC = {"com", "net", "org", "www", "live", "stream", "iptv", "tv",
            "index", "playlist", "chunks", "m3u8", "ts", "hls", "http"}

# מקטעי **מבנה** בנתיב של הספק. אינם שם משתמש וסיסמה, גם כשהם יושבים
# בדיוק במקום שבו הם מופיעים בשערים אחרים.
_STRUCT = {"s", "p", "c", "d", "v", "e", "ch", "id", "live", "stream",
           "hls", "play", "gate", "portal", "api", "get", "gw", "mono"}

# מזהה הערוץ בשאילתה, לשערים שאינם שמים אותו בנתיב. העיגון ל-‎^‎ או
# ל-‎&‎ הוא מה שמונע התאמה בתוך ‎username=‎.
_QUERY_ID = re.compile(
    r"(?:^|&)((?:stream_?id|channel_?id|channel|id|ch|num)=)"
    r"([A-Za-z0-9_-]{1,24})(?=&|$)", re.I)

# נתיבי "תן לי הכל" של שערי IPTV נפוצים. הראשון שעונה — מנצח.
_LIST_PATHS = [
    ("player_api.php", {"action": "get_live_streams"}),
    ("panel_api.php", {}),
    ("get.php", {"type": "m3u_plus", "output": "ts"}),
    ("enigma2.php", {"action": "get_live_streams"}),
]


def labels(host: str) -> set:
    return {w for w in re.split(r"[.\-_:]+", host.lower())
            if len(w) >= 3 and not w.isdigit() and w not in _GENERIC}


def mask(s: str, host: str, secrets=()) -> str:
    """להדפסה בלבד. גם שם המשתמש והסיסמה — הם חלק מהנתיב כאן."""
    for sec in sorted({x for x in secrets if x and len(x) >= 3},
                      key=len, reverse=True):
        s = s.replace(sec, "<סוד>")
    s = re.sub(r"[a-z]+://[^/\s\"']+", "<ספק>", s)
    for w in sorted(labels(host), key=len, reverse=True):
        s = re.sub(re.escape(w), "<שם>", s, flags=re.I)
    s = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "<כתובת-ip>", s)
    s = re.sub(r"((?:token|auth|key|sig|secret|pass(?:word)?|"
               r"user(?:name)?)[\"']?\s*[=:]\s*[\"']?)([^\s&\"',}]+)",
               r"\1<סוד>", s, flags=re.I)
    return re.sub(r"\b(?=[A-Za-z0-9]{10,}\b)(?=[A-Za-z0-9]*\d)"
                  r"[A-Za-z0-9]+\b", "<אסימון>", s)


def ask(url: str, timeout=12.0, nbytes=1 << 20):
    """(קוד, גוף). לעולם לא זורק."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(nbytes).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read(4096).decode("utf-8", "replace")
        except Exception:                                     # noqa: BLE001
            return e.code, ""
    except Exception as e:                                    # noqa: BLE001
        return type(e).__name__, ""


def is_playlist(body: str) -> bool:
    return "#EXTM3U" in body or "#EXT-X-" in body


# ── פירוק הקישור ──────────────────────────────────────────────────────────

def split_link(link: str) -> dict:
    """מפרק קישור ערוץ למה שצריך כדי לבנות אחרים כמוהו.

    מזהה הערוץ הוא **המקטע האחרון שאינו קבוע** — בפועל: הסיומת מוסרת,
    ואז נבחר המקטע האחרון שנראה כמזהה. ‎/live/u/p/412.m3u8‎ ⇒ 412,
    ‎/p/gate/s/412/index.m3u8‎ ⇒ 412.
    """
    u = urllib.parse.urlsplit(link)
    if not u.scheme or not u.netloc:
        raise ValueError("זה אינו קישור מלא (חסר http:// או מארח)")
    segs = [s for s in u.path.split("/") if s]
    if not segs:
        raise ValueError("בקישור אין נתיב — אין מה לגזור ממנו")

    # קבצים קבועים בסוף אינם המזהה
    fixed = {"index.m3u8", "chunks.m3u8", "playlist.m3u8", "master.m3u8",
             "tracks-v1a1", "index.ts", "live.m3u8", "mono.m3u8"}
    cand = [i for i in range(len(segs)) if segs[i].lower() not in fixed]

    # המזהה: המקטע האחרון שהוא מספר, ואם אין — האחרון אחרי הסרת סיומת
    idx, ident = None, None
    for i in reversed(cand):
        stem = re.sub(r"\.(m3u8|ts|mpd)$", "", segs[i], flags=re.I)
        if stem.isdigit():
            idx, ident = i, stem
            break
    if idx is None:
        for i in reversed(cand):
            stem = re.sub(r"\.(m3u8|ts|mpd)$", "", segs[i], flags=re.I)
            if re.fullmatch(r"[A-Za-z0-9_-]{1,24}", stem) \
                    and stem.lower() not in _GENERIC:
                idx, ident = i, stem
                break

    where = "path"
    if idx is None:
        # יש שערים שמעבירים את המזהה בשאילתה ולא בנתיב. חיפוש בנתיב
        # בלבד דחה קישור כזה כ"לא זוהה מזהה" — נתפס בבדיקה העצמית.
        mq = _QUERY_ID.search(u.query or "")
        if not mq:
            raise ValueError("לא זוהה מזהה ערוץ — לא בנתיב ולא בשאילתה")
        where, ident = "query", mq.group(2)
        # החלפה **במקום המדויק** ולא דרך parse_qs: parse_qs מאבד את סדר
        # הפרמטרים, והתבנית חייבת להרכיב בחזרה את הקישור המקורי כמו שהוא.
        query = (u.query[:mq.start(2)] + "{n}" + u.query[mq.end(2):])
        suffix = ""
        template = f"{u.scheme}://{u.netloc}/{'/'.join(segs)}?{query}"
    else:
        suffix = segs[idx][len(ident):]          # ".m3u8" או ""
        tmpl_segs = list(segs)
        tmpl_segs[idx] = "{n}" + suffix
        template = f"{u.scheme}://{u.netloc}/" + "/".join(tmpl_segs)
        if u.query:
            template += "?" + u.query

    # פרטי גישה: בשאילתה, או כזוג מקטעים בנתיב (‎/live/user/pass/id‎)
    q = urllib.parse.parse_qs(u.query)
    user = (q.get("username") or q.get("user") or [None])[0]
    pwd = (q.get("password") or q.get("pass") or [None])[0]
    if not user and where == "path" and idx >= 2:
        a, b = segs[idx - 2], segs[idx - 1]
        # ‎/p/gate/s/412/index.m3u8‎ נקרא כ-user=gate, pass=s — כלומר
        # הסקריפט היה שולח את מבנה הנתיב של הספק כפרטי גישה ומקבל
        # סירוב, ומדווח "אין רשימה". מקטעי מבנה הם קצרים וקבועים, ולכן
        # הם נפסלים בשמם ולא באורכם: ‎bob‎ הוא שם משתמש לגיטימי בן 3.
        if not a.isdigit() and not b.isdigit() \
                and a.lower() not in _STRUCT and b.lower() not in _STRUCT \
                and a.lower() not in _GENERIC and len(a) >= 3:
            user, pwd = a, b

    kind = ("ספרות" if ident.isdigit()
            else "אותיות" if ident.isalpha() else "אותיות וספרות")
    return {"scheme": u.scheme, "netloc": u.netloc,
            "host": u.netloc.split(":")[0], "segs": segs, "idx": idx,
            "ident": ident, "suffix": suffix, "template": template,
            "query": u.query, "user": user, "pwd": pwd,
            "kind": kind, "len": len(ident)}


def human_time(seconds: float) -> str:
    """יחידה שמתאימה לגודל. ‎:,.0f‎ בימים הדפיס "כ-1 ימים" על 0.73 יום —
    כלומר עיגל כלפי מעלה וגם בחר יחידה שגויה, ושני הדברים משנים את
    המסקנה שהמשתמש מסיק מהמספר."""
    if seconds < 90:
        return f"{seconds:.0f} שניות"
    if seconds < 5400:
        return f"{seconds / 60:.0f} דקות"
    if seconds < 36 * 3600:
        return f"{seconds / 3600:.1f} שעות"
    return f"{seconds / 86400:.1f} ימים"


# הקצב בפועל של hunt_channels: Semaphore(4) ובתוכו sleep(0.15)
SCAN_RATE = 4 / 0.15


def space_size(ident: str) -> int:
    """כמה בדיקות תדרוש סריקה עיוורת של מזהה בצורה הזאת."""
    n = len(ident)
    if ident.isdigit():
        return 10 ** n
    alpha = 0
    if re.search(r"[a-z]", ident):
        alpha += 26
    if re.search(r"[A-Z]", ident):
        alpha += 26
    if re.search(r"\d", ident):
        alpha += 10
    return max(alpha, 1) ** n


# ── הרשימה המלאה ──────────────────────────────────────────────────────────

def try_list(info: dict, timeout: float):
    """הנתיב שמחזיר את כל הערוצים. (תיאור, פריטים) או None."""
    if not info["user"] or not info["pwd"]:
        return None
    base = f"{info['scheme']}://{info['netloc']}"
    for path, extra in _LIST_PATHS:
        q = {"username": info["user"], "password": info["pwd"], **extra}
        url = f"{base}/{path}?" + urllib.parse.urlencode(q)
        code, body = ask(url, timeout)
        if code != 200 or not body.strip():
            continue
        items = parse_list(body)
        if items:
            return path, items
    return None


def parse_list(body: str):
    """JSON של get_live_streams, או m3u עם ‎#EXTINF‎. [(שם, מזהה)]."""
    body = body.strip()
    if body[:1] in "[{":
        try:
            data = json.loads(body)
        except Exception:                                     # noqa: BLE001
            return []
        rows = data if isinstance(data, list) else \
            (data.get("available_channels") or data.get("live_streams") or [])
        if isinstance(rows, dict):
            rows = list(rows.values())
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            name = r.get("name") or r.get("title") or r.get("epg_channel_id")
            sid = r.get("stream_id") or r.get("num") or r.get("id")
            if name and sid is not None:
                out.append((str(name).strip(), str(sid)))
        return out
    if "#EXTINF" in body:
        out = []
        name = None
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("#EXTINF"):
                name = line.split(",", 1)[-1].strip() if "," in line else None
            elif line and not line.startswith("#") and name:
                sid = re.sub(r"\.(m3u8|ts)$", "", line.rstrip("/").split("/")[-1])
                out.append((name, sid))
                name = None
        return out
    return []


# ── בדיקה עצמית ───────────────────────────────────────────────────────────

def selftest() -> int:
    bad = 0

    def chk(ok, what):
        nonlocal bad
        if not ok:
            bad += 1
        print(f"{'✓' if ok else '✗'} {what}")

    # ① פירוק: ארבע צורות נתיב שנראו בפועל
    for link, want_id, want_tmpl_end, want_user in (
        ("http://h.example.tv:8080/live/bob/s3cret/412.m3u8",
         "412", "/live/bob/s3cret/{n}.m3u8", "bob"),
        ("http://h.example.tv:8080/p/gate/s/412/index.m3u8",
         "412", "/p/gate/s/{n}/index.m3u8", None),
        ("http://h.example.tv/bob/s3cret/412",
         "412", "/bob/s3cret/{n}", "bob"),
        ("http://h.example.tv/stream?id=412&username=bob&password=s3cret",
         "412", None, "bob"),
    ):
        try:
            i = split_link(link)
        except ValueError as e:
            chk(False, f"פירוק {link[:44]} — {e}")
            continue
        ok = i["ident"] == want_id
        if want_tmpl_end:
            ok = ok and i["template"].endswith(want_tmpl_end)
        chk(ok, f"מזהה {i['ident']!r} · תבנית …{i['template'][-30:]}")
        chk(i["user"] == want_user,
            f"שם משתמש {'זוהה' if want_user else 'אין'} ⇒ {i['user']!r}")

    # ② התבנית שנבנתה מחזירה את הקישור המקורי כשמציבים בה את המזהה
    for link in ("http://h.example.tv:8080/live/bob/s3cret/412.m3u8",
                 "http://h.example.tv:8080/p/gate/s/412/index.m3u8",
                 "http://h.example.tv/bob/s3cret/412"):
        i = split_link(link)
        chk(i["template"].replace("{n}", i["ident"]) == link,
            "התבנית משוחזרת לקישור המקורי בדיוק")

    # ③ קישור פסול נדחה, ולא "מצליח" בשקט
    for bad_link, why in (("לא-קישור", "בלי סכימה"),
                          ("http://h.example.tv", "בלי נתיב"),
                          ("http://h.example.tv/", "נתיב ריק")):
        try:
            split_link(bad_link)
            chk(False, f"{why} — נדחה")
        except ValueError:
            chk(True, f"{why} — נדחה")

    # ④ גודל מרחב החיפוש: המספר שקובע אם סריקה אפשרית בכלל
    chk(space_size("412") == 1000, "3 ספרות = 1,000")
    chk(space_size("4a12") == 36 ** 4, "4 אלפאנומריים = 1,679,616")
    chk(space_size("aB3x") == 62 ** 4, "עם רישיות = 14,776,336")

    # ⑤ קריאת הרשימה — JSON ו-m3u
    js = json.dumps([{"name": "Sport 1", "stream_id": 412},
                     {"name": "Kids", "stream_id": "77"},
                     {"nope": 1}])
    chk(parse_list(js) == [("Sport 1", "412"), ("Kids", "77")],
        "רשימת JSON נקראת, ופריט פגום מדולג")
    m3u = ("#EXTM3U\n#EXTINF:-1 tvg-id=\"x\",Sport 1\n"
           "http://h/live/bob/s3cret/412.m3u8\n"
           "#EXTINF:-1,Kids\nhttp://h/live/bob/s3cret/77.m3u8\n")
    chk(parse_list(m3u) == [("Sport 1", "412"), ("Kids", "77")],
        "רשימת m3u נקראת")
    chk(parse_list("") == [] and parse_list("גיבריש") == [],
        "גוף ריק או זבל ⇒ רשימה ריקה, לא קריסה")
    chk(parse_list('{"user_info":{}}') == [],
        "‏JSON בלי ערוצים ⇒ ריק")

    # ⑥ מיסוך: שם משתמש וסיסמה הם חלק מהנתיב, ואסור שיודפסו
    i = split_link("http://tv.acme-iptv.tv:8080/live/bob/s3cret/412.m3u8")
    m = mask(i["template"], i["host"], (i["user"], i["pwd"]))
    for leak in ("bob", "s3cret", "acme-iptv", "tv.acme"):
        chk(leak not in m, f"‏{leak!r} אינו בפלט")
    chk("{n}" in m, "התבנית עצמה נשארה מזוהה")

    print("\n" + ("✓ הכל עבר" if not bad else f"✗ {bad} נכשלו"))
    return 1 if bad else 0


# ── ראשי ──────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--link", help="קישור ערוץ אחד, עובד ועדכני")
    ap.add_argument("--span", type=int, default=200,
                    help="כמה סביב המזהה לסרוק אם אין רשימה")
    ap.add_argument("--list-only", action="store_true")
    ap.add_argument("--timeout", type=float, default=12.0)
    ap.add_argument("--out", default="")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if not a.link:
        sys.exit("צריך --link עם קישור אחד עובד (או --selftest)")

    try:
        info = split_link(a.link.strip().strip('"\''))
    except ValueError as e:
        sys.exit(f"✗ {e}")
    host, sec = info["host"], (info["user"], info["pwd"])

    print("הקישור, כפי שהוא מפורק:")
    print(f"  מארח:   {mask(info['netloc'], host, sec)}")
    print(f"  מזהה:   {info['ident']}  ({info['kind']}, "
          f"{info['len']} תווים)")
    print(f"  תבנית:  {mask(info['template'], host, sec)}")
    print(f"  גישה:   {'בקישור' if info['user'] else 'לא נמצאה בקישור'}")

    # ── 1. הקישור עצמו חייב לעבוד ─────────────────────────────────────
    print("\nבודק שהקישור חי...")
    code, body = ask(a.link, a.timeout)
    if not (code == 200 and is_playlist(body)):
        print(f"  ✗ הקישור אינו מחזיר playlist (תשובה: {code})")
        if body.strip():
            print("    " + mask(body.strip()[:300], host, sec))
        print("\nזה עוצר כאן, במתכוון. סריקה שמתחילה בקישור מת מחזירה")
        print("אפס על כל מספר — וזה בדיוק מה שקרה בסריקה של 1,200.")
        print("צריך קישור שעובד **עכשיו**, מהספק.")
        return 1
    print(f"  ✓ 200, playlist תקין ({len(body)} בתים)")

    outdir = pathlib.Path(a.out) if a.out else OUT
    outdir.mkdir(parents=True, exist_ok=True)

    # ── 2. הרשימה המלאה, אם יש ────────────────────────────────────────
    print("\nמבקש את הרשימה המלאה מהשער...")
    got = try_list(info, a.timeout)
    if got:
        path, items = got
        print(f"  ✓ {len(items):,} ערוצים, עם שמות — בבקשה אחת.")
        chan = outdir / "channels.json"
        urls = []
        for name, sid in items:
            urls.append({"name": name,
                         "url": info["template"].replace("{n}", sid)})
        chan.write_text(json.dumps(urls, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        print(f"  נשמר: {chan}")
        print("\n  דוגמה (ממוסך):")
        for row in urls[:8]:
            print(f"    {row['name'][:34]:<34} "
                  f"{mask(row['url'], host, sec)}")
        print("\n  כאן אין צורך בפריימים ובזיהוי ידני בכלל — השמות")
        print("  הגיעו מהספק. הקובץ מוכן להזרמה לקטלוג.")
        return 0

    print("  — אין נתיב רשימה שעונה (או שאין פרטי גישה בקישור).")
    if a.list_only:
        return 1

    # ── 3. ואם לא — שכנות בלבד, עם המספר על השולחן ────────────────────
    size = space_size(info["ident"])
    print(f"\nמרחב המזהים בצורה הזאת: {size:,} אפשרויות.")
    if not info["ident"].isdigit():
        print("  המזהה אינו מספרי, ולכן סריקה עיוורת היא הדבר הלא נכון:")
        print(f"  בקצב של hunt_channels זה {human_time(size / SCAN_RATE)} "
              "של בקשות רצופות —")
        print("  והמחיר האמיתי אינו הזמן אלא שזו הלמות על ספק שממילא")
        print("  מסרב לנו, כלומר הדרך הקצרה מחסימה זמנית לקבועה.")
        print("  מה שצריך הוא הרשימה מהספק, לא עוד זמן מעבד.")
        return 1

    n = int(info["ident"])
    lo, hi = max(1, n - a.span), n + a.span
    fmt = outdir / "fmt.txt"
    fmt.write_text(info["template"] + "\n", encoding="utf-8")
    print(f"\nנשמרה תבנית אחת: {fmt}")
    print(f"עכשיו — סריקת שכנות בלבד ({hi - lo + 1:,} בדיקות, לא "
          f"{size:,}):\n")
    print(f"  python3 hunt_channels.py --formats {fmt} "
          f"--from {lo} --to {hi} --skip-known")
    print("\nזה מושך פריים מכל ערוץ שעונה ומרכיב גיליונות לזיהוי לפי")
    print("הלוגו — בדיוק הכלי מהפעם הקודמת.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
