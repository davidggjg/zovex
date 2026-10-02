#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_headers — מה הבקשה צריכה לשאת כדי שהספק יענה.

## מה שגוף התשובה אמר

‎dns_check‎ הראה שחמישה resolvers מסכימים על אותה כתובת, כלומר DNS
אינו הסיבה. והוא הראה גם את גוף ה-403, שהוא מילה אחת:

    direct

חסימת IP אינה כותבת "direct". חסימת מנוי אינה כותבת "direct". מילה
אחת כזאת אומרת דבר מדויק: **הבקשה הגיעה ישירות** — בלי מה שהם מצפים
שיישא אותה. כלומר הם בודקים את הבקשה עצמה, לא את מי ששלח אותה.

וזה מצוין, כי זה הדבר היחיד בכל הסיפור שאנחנו שולטים בו לגמרי.

## מה נבדק

ערוץ אחד שמחזיר 403, עם צירופי כותרות שונים — ‎User-Agent‎ של נגנים
ואפליקציות שונות, ‎Referer‎, ‎Origin‎, ‎Accept‎ ו-‎Range‎. אם צירוף
אחד מחזיר playlist, זה **כל** התיקון: הרלֵיי כבר שולח כותרות ל-ffmpeg
ולמסלול הרגיל, וצריך רק להוסיף שם את הצירוף הזה.

כל בקשה נשלחת פעם אחת, עם המתנה ביניהן. אין כאן כוח גס ואין ניחוש של
סודות — רק השאלה "באיזו צורה אתם מצפים שהבקשה תיראה", שעל רובה
אפליקציות נגינה עונות בלי לחשוב.

## ומה הוא **לא** עושה

אינו מנסה סיסמאות, אינו מנחש אסימונים ואינו סורק. אם התשובה היא
שנדרש אסימון שאין לנו — הוא יאמר את זה ויעצור, כי זה מה שהמידע אומר.

    python3 probe_headers.py
    python3 probe_headers.py --host 2        # רק ספק 2 מהרשימה
    python3 probe_headers.py --selftest      # בלי רשת

קריאה בלבד: לא נוגע בקטלוג, בשירות ולא בהגדרות.
"""
import argparse
import http.client
import json
import os
import pathlib
import re
import socket
import ssl
import sys
import time
from collections import OrderedDict, defaultdict

DATA = pathlib.Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
RELAY = re.compile(r"/hls-relay/(?:_fix/)?([^/?]+)/([^?]+)")

_GENERIC = {"com", "net", "org", "www", "live", "stream", "iptv", "tv",
            "index", "playlist", "chunks", "m3u8", "http", "https", "pw"}

# ── ה-User-Agent שאפליקציות נגינה אמיתיות שולחות ─────────────────────────
UAS = OrderedDict([
    ("ריק", None),
    ("VLC", "VLC/3.0.20 LibVLC/3.0.20"),
    ("VLC-אנדרואיד", "VLC/3.5.4 LibVLC/3.5.4 (Android)"),
    ("ExoPlayer", "ExoPlayerLib/2.19.1 (Linux; Android 12) "
                  "ExoPlayerLib/2.19.1"),
    ("okhttp", "okhttp/4.12.0"),
    ("ffmpeg", "Lavf/60.16.100"),
    ("Kodi", "Kodi/20.2 (Linux; Android 12) "
             "inputstream.adaptive/20.3.5"),
    ("TiviMate", "TiviMate/4.7.0 (Android 12)"),
    ("כרום-נייד", "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"),
    ("כרום-שולחני", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"),
])


def labels(host: str) -> set:
    return {w for w in re.split(r"[.\-_:]+", host.lower())
            if len(w) >= 3 and not w.isdigit() and w not in _GENERIC}


def mask(s: str, host: str) -> str:
    s = re.sub(r"[a-z]+://[^/\s\"']+", "<ספק>", s)
    for w in sorted(labels(host), key=len, reverse=True):
        s = re.sub(re.escape(w), "<שם>", s, flags=re.I)
    s = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "<כתובת-ip>", s)
    s = re.sub(r"((?:token|auth|key|sig|secret|pass(?:word)?|"
               r"user(?:name)?)[\"']?\s*[=:]\s*[\"']?)([^\s&\"',}]+)",
               r"\1<סוד>", s, flags=re.I)
    return re.sub(r"\b(?=[A-Za-z0-9]{10,}\b)(?=[A-Za-z0-9]*\d)"
                  r"[A-Za-z0-9]+\b", "<אסימון>", s)


def header_sets(host: str, scheme: str, port: int):
    """[(שם, dict)]. השמות הם מה שיודפס, ולכן הם בעברית."""
    root = f"{scheme}://{host}" + (
        "" if port in (80, 443) else f":{port}")
    out = []
    for ua_name, ua in UAS.items():
        h = {}
        if ua:
            h["User-Agent"] = ua
        out.append((f"UA={ua_name}", dict(h)))

    # ועכשיו הכותרות שבודקות "מאיפה באת" — על גבי שני UA מציאותיים
    for ua_name in ("VLC", "כרום-נייד"):
        base = {"User-Agent": UAS[ua_name]}
        out += [
            (f"UA={ua_name} + Referer=שורש",
             {**base, "Referer": root + "/"}),
            (f"UA={ua_name} + Origin=שורש",
             {**base, "Origin": root}),
            (f"UA={ua_name} + Referer+Origin",
             {**base, "Referer": root + "/", "Origin": root}),
            (f"UA={ua_name} + Accept=m3u",
             {**base, "Accept": "application/vnd.apple.mpegurl,"
                                "application/x-mpegURL,*/*"}),
            (f"UA={ua_name} + Range=0-",
             {**base, "Range": "bytes=0-"}),
            (f"UA={ua_name} + Connection=keep-alive",
             {**base, "Connection": "keep-alive",
              "Accept-Encoding": "identity"}),
        ]
    return out


def fetch(host: str, port: int, scheme: str, path: str, hdrs: dict,
          timeout=10.0):
    """(קוד-או-שגיאה, גוף-מקוצר, playlist?)"""
    sock = None
    try:
        sock = socket.create_connection((host, port), timeout)
        if scheme == "https":
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            sock = ctx.wrap_socket(sock, server_hostname=host)
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.sock = sock
        conn.putrequest("GET", path, skip_host=True,
                        skip_accept_encoding=True)
        conn.putheader("Host", host if port in (80, 443)
                       else f"{host}:{port}")
        for k, v in hdrs.items():
            conn.putheader(k, v)
        conn.endheaders()
        r = conn.getresponse()
        body = r.read(4096).decode("utf-8", "replace")
        conn.close()
        pl = "#EXTM3U" in body or "#EXT-X-" in body
        return str(r.status), body, pl
    except Exception as e:                                    # noqa: BLE001
        return type(e).__name__, "", False
    finally:
        try:
            if sock:
                sock.close()
        except Exception:                                     # noqa: BLE001
            pass


def origins() -> dict:
    try:
        return json.loads((DATA / "relay_hosts.json").read_text("utf-8"))
    except Exception:
        return {}


def selftest() -> int:
    bad = 0

    def chk(ok, what):
        nonlocal bad
        if not ok:
            bad += 1
        print(f"{'✓' if ok else '✗'} {what}")

    sets = header_sets("tv.acme-iptv.tv", "https", 86)
    names = [n for n, _ in sets]
    chk(len(sets) == len(UAS) + 12, f"{len(sets)} צירופי כותרות")
    chk(len(set(names)) == len(names), "אין שם צירוף כפול")
    chk(sets[0][1] == {}, "הראשון הוא בקשה חשופה, בלי שום כותרת")

    # הפורט חייב להיכנס ל-Referer כשהוא אינו 80/443 — שרת שמשווה
    # מחרוזות היה דוחה ‎https://host/‎ מול ‎https://host:86/‎
    ref = dict(sets)["UA=VLC + Referer=שורש"]["Referer"]
    chk(":86" in ref, f"הפורט בתוך ה-Referer ⇒ {ref.replace('acme-iptv','X')}")
    ref80 = dict(header_sets("h.test", "http", 80))[
        "UA=VLC + Referer=שורש"]["Referer"]
    chk(":80" not in ref80, "ופורט 80 אינו מופיע")

    # כל צירוף הוא עותק משלו: dict משותף היה נדבק בין בדיקות
    a = dict(sets)["UA=VLC"]
    a["X"] = "1"
    chk("X" not in dict(header_sets("h.test", "http", 80))["UA=VLC"],
        "שינוי בצירוף אחד אינו מדביק את האחרים")

    # ומיסוך
    m = mask("https://tv.acme-iptv.tv:86/p/acme/s/1/i.m3u8?token=AB12CD34EF",
             "tv.acme-iptv.tv")
    chk("acme" not in m, "שם הספק אינו בפלט")
    chk("AB12CD34EF" not in m, "אסימון אינו בפלט")

    print("\n" + ("✓ הכל עבר" if not bad else f"✗ {bad} נכשלו"))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", type=int, default=0,
                    help="לבדוק רק ספק אחד לפי מספרו בפלט")
    ap.add_argument("--gap", type=float, default=0.6,
                    help="המתנה בין בקשות")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    try:
        data = json.loads(CONTENT.read_text(encoding="utf-8"))
    except Exception as e:                                    # noqa: BLE001
        sys.exit(f"לא ניתן לקרוא את {CONTENT}: {e}")
    items = data if isinstance(data, list) else data.get("movies", [])

    org = origins()
    byhost = defaultdict(list)
    for m in items:
        g = RELAY.search((m.get("video_url") or "").strip())
        if g:
            byhost[g.group(1)].append(g.group(2))
    order = sorted(byhost.items(), key=lambda kv: -len(kv[1]))
    if not order:
        sys.exit("אין ערוצים עם כתובת רלֵיי בקטלוג.")

    wins = []
    for idx, (netloc, paths) in enumerate(order, 1):
        if a.host and idx != a.host:
            continue
        host = netloc.split(":")[0]
        o = org.get(host) or {}
        scheme = o.get("scheme") or "http"
        port = int(netloc.split(":")[1]) if ":" in netloc else \
            int(o.get("port") or (443 if scheme == "https" else 80))
        path = "/" + paths[0]

        # בדיקה אחת: האם הספק הזה בכלל שבור
        code, body, pl = fetch(host, port, scheme, path,
                               {"User-Agent": UAS["VLC"]}, a.timeout)
        print(f"\n{'=' * 62}\nספק {idx}  ({len(paths)} ערוצים)  "
              f"{mask(host, host)} · {scheme}:{port}")
        if pl:
            print("  ✓ עובד כבר עכשיו — אין מה לבדוק כאן.")
            continue
        print(f"  ✗ {code}" + (f" · {mask(body.strip()[:120], host)}"
                               if body.strip() else " · גוף ריק"))

        sets = header_sets(host, scheme, port)
        print(f"\n  {len(sets)} צירופי כותרות:\n")
        groups = OrderedDict()
        for name, hdrs in sets:
            c, b, ok = fetch(host, port, scheme, path, hdrs, a.timeout)
            tag = "200 · playlist ✓" if ok else \
                (f"{c} · {b.strip()[:40]}" if b.strip() else str(c))
            groups.setdefault(tag, []).append(name)
            print(f"    {'✓' if ok else '·'} {name:<34} {tag}")
            if ok:
                wins.append((idx, name, hdrs))
            time.sleep(a.gap)

        print("\n  סיכום לספק הזה:")
        for tag, who in groups.items():
            print(f"    {len(who):>2} × {tag}")

    print(f"\n{'=' * 62}")
    if wins:
        print("יש צירוף שעובד:\n")
        seen = set()
        for _i, name, hdrs in wins:
            if name in seen:
                continue
            seen.add(name)
            print(f"  {name}")
            for k, v in hdrs.items():
                print(f"      {k}: {v[:70]}")
        print("\nזה כל התיקון. הרלֵיי כבר מעביר כותרות לשני המסלולים")
        print("(הרגיל ול-ffmpeg), וצריך להוסיף שם את הצירוף הזה.")
        print("תגיד לי איזה צירוף עבד ואני כותב את הפאצ' עם --check.")
    else:
        print("אף צירוף כותרות לא עבר.")
        print()
        print("כלומר הם אינם בודקים UA או Referer, והתשובה 'direct'")
        print("מתייחסת למשהו שאינו בכותרות — כמעט תמיד אסימון או מזהה")
        print("בנתיב עצמו, שנוצר אצלם בכל פתיחת ערוץ.")
        print()
        print("את זה אי אפשר לנחש ואין טעם לסרוק: כל נתיב שנבדוק יקבל")
        print("את אותה תשובה. מה שצריך הוא קישור אחד עובד — ואם יש לך")
        print("אזור אישי באתר שלהם, הוא נמצא שם בלי לחכות לאף אחד:")
        print("  python3 seed_hunt.py --link '<הקישור>'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
