#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_known — מה הספק עונה על הערוצים שאנחנו **יודעים** שעבדו.

## למה זה ולא עוד סריקה

סריקה שמחזירה אפס אינה אומרת למה. "לא נמצא ערוץ" הוא אותו פלט בדיוק
כשהספק חסם אותנו, כשהמספרים השתנו, כשהחשבון פג, וכשהוא באמת נפל —
וארבע הסיבות דורשות ארבע פעולות שונות לגמרי.

הסקריפט לוקח את הערוצים שכבר בקטלוג — כלומר כאלה שעבדו — ושואל עליהם
ישירות. התשובה מפרידה בין המקרים:

    403 / 401 על הכל     הגישה נשללה. החשבון, ה-IP או האסימון.
    404 על הכל           המזהים כבר לא קיימים. הספק שינה מבנה.
    200 עם playlist ריק  הספק עונה ואינו משדר. תקלה אצלם, לרוב זמנית.
    timeout / סירוב      השרת שלהם לא שם.
    חלק עובד             לא "הכל נפל" — וזו כבר שאלה אחרת.

## מהשרת, ולא מבחוץ

הפורטים של הספק חסומים מבחוץ, ולשרת יש גישה ישירה כי הוא ממילא מרלה
אותו. הרצה מהמחשב הביתי הייתה מחזירה timeout על הכל ונראית כמו ספק
שנפל — מסקנה שגויה שנראית ודאית.

**הפלט ממוסך**: מארח, שם ספק בנתיב ואסימון אינם מודפסים.

    python3 probe_known.py               # עד 12 ערוצים מכל תבנית
    python3 probe_known.py --each 30
    python3 probe_known.py --like live   # רק תבניות שמכילות 'live'

קריאה בלבד.
"""
import argparse
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict

DATA = pathlib.Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
RELAY = re.compile(r"/hls-relay/(?:_fix/)?([^/?]+)/([^?]+)")
UA = ("Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

_GENERIC = {"com", "net", "org", "www", "live", "stream", "iptv",
            "index", "playlist", "chunks", "m3u8"}


def _labels(host: str) -> set:
    return {w for w in re.split(r"[.\-_:]+", host.lower())
            if len(w) >= 3 and not w.isdigit() and w not in _GENERIC}


def mask(s: str, host: str, tag: str) -> str:
    s = re.sub(r"^[a-z]+://[^/]+", f"<{tag}>", s)
    for w in sorted(_labels(host), key=len, reverse=True):
        s = re.sub(re.escape(w), "<שם>", s, flags=re.I)
    return re.sub(r"\b[A-Za-z0-9]{10,}\b", "<אסימון>", s)


def origins():
    try:
        return json.loads((DATA / "relay_hosts.json").read_text("utf-8"))
    except Exception:
        return {}


def full_url(host: str, path: str, org: dict) -> str:
    base = host.split(":")[0]
    o = org.get(base) or {}
    scheme = o.get("scheme") or "http"
    port = o.get("port")
    netloc = host
    if port and ":" not in netloc and not (
            (scheme == "https" and port == 443)
            or (scheme == "http" and port == 80)):
        netloc = f"{netloc}:{port}"
    return f"{scheme}://{netloc}/{path}"


def ask(url: str, timeout: float):
    """(תיאור, בתים). לעולם לא זורק — הכישלון **הוא** התשובה."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(65536)
            if r.status != 200:
                return f"{r.status}", len(body)
            txt = body.decode("utf-8", "ignore")
            if "#EXTM3U" not in txt:
                return "200 לא-playlist", len(body)
            segs = len([l for l in txt.splitlines()
                        if l.strip() and not l.startswith("#")])
            return (f"200 · {segs} מקטעים" if segs else "200 · ריק"), len(body)
    except urllib.error.HTTPError as e:
        try:
            n = len(e.read(4096))
        except Exception:
            n = 0
        return f"{e.code}", n
    except Exception as e:                                   # noqa: BLE001
        return type(e).__name__, 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--each", type=int, default=12)
    ap.add_argument("--like", default="")
    ap.add_argument("--timeout", type=float, default=12.0)
    a = ap.parse_args()

    try:
        data = json.loads(CONTENT.read_text(encoding="utf-8"))
    except Exception as e:                                   # noqa: BLE001
        sys.exit(f"לא ניתן לקרוא את {CONTENT}: {e}")
    items = data if isinstance(data, list) else data.get("movies", [])

    org = origins()
    groups = defaultdict(list)
    for m in items:
        g = RELAY.search((m.get("video_url") or "").strip())
        if not g:
            continue
        host, path = g.group(1), g.group(2)
        shape = re.sub(r"/\d{1,6}(?=/)", "/{n}", "/" + path)
        groups[(host, shape)].append(path)

    if not groups:
        sys.exit("אין ערוצים חיים בקטלוג.")

    tags, overall = {}, Counter()
    for i, ((host, shape), paths) in enumerate(
            sorted(groups.items(), key=lambda kv: -len(kv[1])), 1):
        base = host.split(":")[0]
        tags.setdefault(base, f"ספק{len(tags) + 1}")
        tag = tags[base]
        sample = paths[:a.each]
        line = mask(full_url(host, shape.lstrip("/"), org), base, tag)
        if a.like and a.like.lower() not in line.lower() \
                and a.like.lower() not in shape.lower():
            continue
        print(f"\n{i}. {line}   ({len(paths)} בקטלוג, נבדקים {len(sample)})")
        c = Counter()
        for p in sample:
            what, n = ask(full_url(host, p, org), a.timeout)
            c[what] += 1
            overall[what] += 1
        for what, n in c.most_common():
            print(f"      {n:>3} × {what}")

    print("\n" + "=" * 52)
    print("סך הכל:")
    for what, n in overall.most_common():
        print(f"  {n:>4} × {what}")
    print()
    if not overall:
        print("לא נבדק כלום.")
    elif all(k.startswith(("403", "401")) for k in overall):
        print("הגישה נשללה על **כל** מה שנבדק — לא תקלה זמנית.")
        print("החשבון, ה-IP או האסימון. פנייה לספק, לא תיקון בקוד.")
    elif all(k.startswith("404") for k in overall):
        print("הכל 404: המזהים כבר לא קיימים. הספק שינה מבנה או מספור,")
        print("וצריך למפות מחדש — סקריפט הסריקה של אותו ספק, ואז הזיהוי")
        print("לפי פריימים (ls scan_*.py identify_*.py).")
    elif all("ריק" in k for k in overall):
        print("הספק עונה ואינו משדר. זו תקלה אצלם, לרוב זמנית —")
        print("שווה לבדוק שוב בעוד שעה לפני שנוגעים במשהו.")
    elif all(k in ("timeout", "URLError", "TimeoutError", "socket.timeout")
             or not k[:1].isdigit() for k in overall):
        print("השרת שלהם אינו עונה בכלל. נפילה — ממתינים.")
    elif any("מקטעים" in k for k in overall):
        print("חלק מהערוצים **כן** עובדים. זה לא 'הכל נפל',")
        print("וצריך להסתכל על ההבדל ביניהם ולא על הספק כולו.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
