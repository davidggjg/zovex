#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""why_403 — מה הספק **אומר** כשהוא מסרב, ולא רק באיזה קוד.

## למה זה, ולא עוד סריקה

‎probe_known‎ ענה "22 × 403" והוא צדק. אבל הוא מנה את הקודים וזרק את
התשובות:

    except urllib.error.HTTPError as e:
        n = len(e.read(4096))          # ← הגוף נמדד ונזרק
        return f"{e.code}", n

וזו בדיוק השורה שעלתה לנו שבוע. שרתי IPTV כותבים את הסיבה **בגוף
ובכותרות**: "המנוי פג", "חריגה ממספר החיבורים", "ה-IP חסום", או הפניה
לכתובת חדשה. ארבע הודעות שונות, אותו קוד 403 בדיוק, וארבע פעולות
שונות לגמרי.

הספק אמר שהחליף חוות שרתים ו"סיבב" את הקישורים — מספרים, אותיות או
פורמט. **אבל סריקה לא תבדיל בין זה ובין חסימה**: מספר שגוי מחזיר 404
או playlist ריק, לא 403. 403 על כתובת שעבדה אתמול אומר שהבקשה הגיעה,
זוהתה, ונדחתה. כלומר הוא ענה — והוא אומר משהו. הסקריפט הזה קורא את זה.

## מה נבדק

לכל מארח: כמה כתובות שעבדו מהקטלוג, ועוד בקשה לשורש המארח. לכל אחת
נרשמים הקוד, **כל** כותרות התשובה, ותחילת הגוף.

תשובות זהות מקובצות, כך שהפלט הוא כמה בלוקים ולא עשרים.

## מה הפלט אומר

    "expired" / "subscription"     החשבון פג. תשלום, לא קוד.
    "max" / "connections"          חריגה בחיבורים — זמני.
    "banned" / "ip"                ה-IP של השרת חסום.
    Location: / "moved"            יש כתובת חדשה, והיא **כאן**.
    גוף ריק + 403                  חסימה יבשה בלי הודעה.
    כותרת CDN (cf-ray וכו')        נדחה בקצה, לפני השרת שלהם.

## ממוסך

מארח, שם הספק בנתיב ואסימונים מוחלפים — גם בכתובת **וגם בגוף**, כי
הודעת שגיאה של ספק מצטטת לא פעם את הכתובת המלאה עם האסימון בתוכה.

    python3 why_403.py
    python3 why_403.py --each 3 --bytes 1500
    python3 why_403.py --selftest      # בודק את המיסוך ואת הסיווג

קריאה בלבד: לא נוגע בקטלוג, בשירות או בקבצים.
"""
import argparse
import json
import os
import pathlib
import re
import socket
import sys
import urllib.error
import urllib.request
from collections import OrderedDict, defaultdict

DATA = pathlib.Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
RELAY = re.compile(r"/hls-relay/(?:_fix/)?([^/?]+)/([^?]+)")
UA = ("Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

_GENERIC = {"com", "net", "org", "www", "live", "stream", "iptv",
            "index", "playlist", "chunks", "m3u8", "http", "https"}

# כותרות שמעידות על שכבת קצה ולא על השרת של הספק
_EDGE = ("cf-ray", "cf-cache-status", "x-sucuri-id", "x-akamai",
         "x-cdn", "x-cache", "fastly-debug-digest", "x-amz-cf-id")

# מה לחפש בגוף ובכותרות. הסדר הוא סדר העדיפות בהסקה.
_SIGNS = [
    ("expired",     ("expired", "expire", "subscription", "renew",
                     "פג", "חידוש"),
     "המנוי פג או לא שולם. זו פעולה אצל הספק, לא בקוד."),
    ("connections", ("max connection", "maximum", "too many",
                     "connection limit", "concurrent"),
     "חריגה ממספר החיבורים המותר. זמני — וייתכן שזה אנחנו, "
     "אם הרלֵיי פותח יותר זרמים במקביל ממה שהחשבון מתיר."),
    ("banned",      ("banned", "ban", "blacklist", "blocked", "abuse",
                     "חסום"),
     "ה-IP של השרת חסום אצלם במפורש. פנייה לספק עם כתובת ה-IP."),
    ("auth",        ("unauthorized", "invalid", "wrong", "credential",
                     "username", "password", "auth"),
     "פרטי הגישה אינם תקפים. הם שונו — צריך את החדשים."),
    ("moved",       ("moved", "new server", "new url", "migrat",
                     "עבר", "הועבר", "כתובת חדשה"),
     "הם אומרים שהכתובת עברה. הכתובת החדשה היא מה שצריך, "
     "ואין שום סריקה שתמצא אותה."),
    ("notfound",    ("not found", "no such", "unknown stream"),
     "הזרם אינו קיים בשם הזה — כלומר מספור או פורמט שהשתנו, "
     "וכאן סריקה **כן** מתאימה."),
]


def labels(host: str) -> set:
    return {w for w in re.split(r"[.\-_:]+", host.lower())
            if len(w) >= 3 and not w.isdigit() and w not in _GENERIC}


def mask(s: str, host: str) -> str:
    """להדפסה. מוחל גם על גוף התשובה, לא רק על הכתובת.

    הודעת שגיאה של ספק מצטטת לא פעם את הכתובת המלאה שביקשנו, עם
    האסימון בתוכה — כלומר הגוף הוא מקום דליפה בדיוק כמו הכתובת.
    """
    s = re.sub(r"[a-z]+://[^/\s\"']+", "<ספק>", s)
    for w in sorted(labels(host), key=len, reverse=True):
        s = re.sub(re.escape(w), "<שם>", s, flags=re.I)
    s = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "<כתובת-ip>", s)
    # כל מה שיושב אחרי שם של פרמטר סודי — בלי קשר לצורה שלו
    s = re.sub(r"((?:token|auth|key|sig|secret|pass(?:word)?|user(?:name)?)"
               r"[\"']?\s*[=:]\s*[\"']?)([^\s&\"',}]+)",
               r"\1<אסימון>", s, flags=re.I)
    # ואסימון לפי צורה. ‎{10,}‎ של תווי אלפאנומריה בלבד תפס גם
    # ‎subscription‎ וגם ‎application‎ — כלומר מחק דווקא את ההודעה שבגללה
    # הרצנו את הסקריפט. אסימון אמיתי מערבב ספרות ואותיות, או שהוא ארוך
    # מכל מילה באנגלית.
    s = re.sub(r"\b(?=[A-Za-z0-9]{10,}\b)(?=[A-Za-z0-9]*\d)"
               r"[A-Za-z0-9]+\b", "<אסימון>", s)
    return re.sub(r"\b[A-Za-z0-9]{20,}\b", "<אסימון>", s)


def classify(blob: str):
    """(תג, הסבר) לפי מה שנמצא בטקסט, או None."""
    low = blob.lower()
    for tag, words, why in _SIGNS:
        if any(w in low for w in words):
            return tag, why
    return None


def origins() -> dict:
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


def ask(url: str, timeout: float, nbytes: int) -> dict:
    """לעולם לא זורק. הכישלון הוא התשובה, וגם לו יש כותרות."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"code": str(r.status),
                    "headers": dict(r.headers.items()),
                    "body": r.read(nbytes).decode("utf-8", "replace")}
    except urllib.error.HTTPError as e:
        try:
            body = e.read(nbytes).decode("utf-8", "replace")
        except Exception:
            body = ""
        return {"code": str(e.code),
                "headers": dict(e.headers.items()) if e.headers else {},
                "body": body}
    except Exception as e:                                   # noqa: BLE001
        return {"code": type(e).__name__, "headers": {}, "body": ""}


def resolved(host: str) -> str:
    try:
        ips = sorted({ai[4][0] for ai in socket.getaddrinfo(
            host.split(":")[0], None)})
    except Exception as e:                                   # noqa: BLE001
        return f"אינו נפתר ({type(e).__name__})"
    out = []
    for ip in ips:
        try:
            out.append(f"{ip} ({socket.gethostbyaddr(ip)[0]})")
        except Exception:                                    # noqa: BLE001
            out.append(ip)
    return ", ".join(out)


def selftest() -> int:
    bad = 0

    def chk(ok, what):
        nonlocal bad
        if not ok:
            bad += 1
        print(f"{'✓' if ok else '✗'} {what}")

    host = "tv.example-provider.tv"
    # ① המארח אינו שורד מיסוך, גם כשהוא בתוך גוף התשובה
    body = ('Error: stream http://tv.example-provider.tv:8080/'
            'p/example-provider/s/412/index.m3u8 is not available '
            'for 203.0.113.77 (token ABCDEF1234567890)')
    m = mask(body, host)
    for leak in ("example-provider", "203.0.113.77", "ABCDEF1234567890",
                 "tv.example"):
        chk(leak not in m, f"‏{leak!r} אינו בפלט")
    chk("<ספק>" in m and "<כתובת-ip>" in m, "המיסוך סימן משהו")

    # ② מיסוך שאינו מוחק את ההודעה עצמה — אחרת אין בשביל מה להריץ.
    #    ‎{10,}‎ אלפאנומרי תפס קודם גם ‎subscription‎ וגם ‎application‎,
    #    כלומר מחק את המילים שבגללן הרצנו.
    chk("not available" in m, "הטקסט המשמעותי נשאר קריא")
    words = ("subscription", "application", "unauthorized", "connections",
             "credentials", "maintenance")
    keep = mask("Your subscription is unauthorized; "
                "application/json; max connections; credentials; "
                "server maintenance", host)
    for w in words:
        chk(w in keep, f"המילה {w!r} לא מוסתרה")

    # ③ ואסימון לפי שם הפרמטר, גם כשצורתו נראית כמילה
    for raw, gone in (("token=SECRETVALUE", "SECRETVALUE"),
                      ("password: hunter2seven", "hunter2seven"),
                      ("&auth=abcdefghij&x=1", "abcdefghij"),
                      ('"key":"QQ7HJ2LMN4PRS8TV"', "QQ7HJ2LMN4PRS8TV")):
        chk(gone not in mask(raw, host), f"‏{raw!r} מוסתר")
    # וצורה מעורבת ארוכה, בלי שם פרמטר
    chk("6d0bbf6ce770183c" not in mask("key 6d0bbf6ce770183c here", host),
        "אסימון hex מוסתר לפי צורה")

    # ③ הסיווג מפריד בין המקרים
    for text, want in (
            ("Your subscription has expired", "expired"),
            ("Max connections reached", "connections"),
            ("Your IP has been banned", "banned"),
            ("Invalid username or password", "auth"),
            ("This server moved to a new url", "moved"),
            ("404 not found", "notfound"),
            ("", None),
            ("<html><body>Forbidden</body></html>", None)):
        got = classify(text)
        tag = got[0] if got else None
        chk(tag == want, f"סיווג {text[:34]!r} ⇒ {tag}")

    # ④ "Forbidden" לבדו אינו מסווג — וזה מכוון: הוא אינו אומר למה,
    #    ולהמציא לו סיבה זה בדיוק מה שהסקריפט נועד למנוע.
    chk(classify("Forbidden") is None, "‏Forbidden יבש נשאר בלי הסבר")

    print("\n" + ("✓ הכל עבר" if not bad else f"✗ {bad} נכשלו"))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--each", type=int, default=3,
                    help="כמה כתובות לבדוק לכל מארח")
    ap.add_argument("--bytes", type=int, default=800,
                    help="כמה בתים לקרוא מהגוף")
    ap.add_argument("--timeout", type=float, default=12.0)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    try:
        data = json.loads(CONTENT.read_text(encoding="utf-8"))
    except Exception as e:                                   # noqa: BLE001
        sys.exit(f"לא ניתן לקרוא את {CONTENT}: {e}")
    items = data if isinstance(data, list) else data.get("movies", [])

    org = origins()
    byhost = defaultdict(list)
    for m in items:
        g = RELAY.search((m.get("video_url") or "").strip())
        if g:
            byhost[g.group(1)].append(g.group(2))
    if not byhost:
        sys.exit("אין ערוצים עם כתובת רלֵיי בקטלוג.")

    found = []
    for i, (host, paths) in enumerate(
            sorted(byhost.items(), key=lambda kv: -len(kv[1])), 1):
        base = host.split(":")[0]
        print(f"\n{'=' * 60}\nספק {i}   ({len(paths)} ערוצים בקטלוג)")
        print(f"  שם:  {mask(base, base)}")
        print(f"  IP:  {resolved(host)}")

        # הכתובות שעבדו, ועוד השורש — לפעמים דווקא הוא מחזיר הודעה
        urls = [full_url(host, p, org) for p in paths[:a.each]]
        urls.append(full_url(host, "", org))

        # תשובות זהות מקובצות: אותו קוד, אותו גוף, אותן כותרות מעניינות
        groups = OrderedDict()
        for u in urls:
            r = ask(u, a.timeout, a.bytes)
            key = (r["code"], r["body"].strip()[:400],
                   r["headers"].get("Server", ""),
                   r["headers"].get("Location", ""))
            groups.setdefault(key, []).append((u, r))

        for (code, _b, _s, _l), rows in groups.items():
            u, r = rows[0]
            print(f"\n  ── {len(rows)} × {code} " + "─" * 34)
            print(f"     {mask(u, base)}")

            hdrs = r["headers"]
            edge = [k for k in hdrs if k.lower() in _EDGE]
            for k in ("Server", "Location", "Content-Type",
                      "Content-Length", "WWW-Authenticate",
                      "X-Powered-By", "Retry-After"):
                if hdrs.get(k):
                    print(f"     {k}: {mask(str(hdrs[k]), base)}")
            if edge:
                print(f"     כותרות קצה: {', '.join(sorted(edge))}")

            body = r["body"].strip()
            if body:
                txt = mask(body, base)
                txt = re.sub(r"\s*\n\s*", "\n       ", txt.strip())
                print(f"     גוף ({len(r['body'])} בתים):\n       {txt}")
            else:
                print("     גוף: ריק")

            blob = body + " " + " ".join(f"{k}: {v}" for k, v in hdrs.items())
            got = classify(blob)
            if got:
                found.append((code, *got))
                print(f"\n     ⇒ {got[1]}")
            elif code == "403" and not body:
                found.append((code, "silent",
                              "403 בלי שום הודעה ובלי Location. זו חסימה "
                              "יבשה — הבקשה הגיעה, זוהתה ונדחתה, והם לא "
                              "אומרים למה. מספור שהשתנה היה מחזיר 404."))
                print(f"\n     ⇒ {found[-1][2]}")

    print(f"\n{'=' * 60}\nמה זה אומר\n")
    if not found:
        print("אף תשובה לא נשאה הודעה שאפשר לסווג. הגוף והכותרות למעלה")
        print("הם כל מה שהם אמרו — שווה להעביר אותם לספק כפי שהם.")
    else:
        seen = set()
        for code, tag, why in found:
            if tag in seen:
                continue
            seen.add(tag)
            print(f"  [{code} · {tag}] {why}\n")
        if "notfound" in seen:
            print("  סריקה מתאימה כאן. התבניות יוצאות מהקטלוג:")
            print("    python3 make_formats.py")
            print("    python3 hunt_channels.py --formats /tmp/hunt/fmt.txt "
                  "--from 1 --to 600")
        elif seen & {"expired", "banned", "auth", "moved", "silent"}:
            print("  סריקה **לא** תעזור: 403 אומר שהבקשה זוהתה ונדחתה,")
            print("  ולא שהמספר שגוי. כל מספר אחר יקבל את אותה תשובה.")
            print("  מה שצריך מהספק הוא קישור אחד עובד — ומתוכו:")
            print("    python3 seed_hunt.py --link '<הקישור>'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
