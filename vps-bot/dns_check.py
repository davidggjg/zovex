#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dns_check — האם אנחנו מדברים בכלל עם השרת של הספק?

## שתי עובדות ששינו את האבחנה

**① אצל לקוח רגיל הזרם נמשך מה-IP של הצופה.** אפליקציות ואתרים אחרים
שעובדים עם הספק אינם מרלים — כל מכשיר פונה אליו ישירות. אצלנו השרת
מושך, וכל התנועה יוצאת מ-IP אחד. כלומר מבחינת הספק יש כתובת אחת
שפותחת עשרות ערוצים במקביל, כל היום. זה נראה בדיוק כמו גרידה או
מכירה חוזרת, וזו סיבה מצוינת לחסום **אותנו** בלי לחסום אף לקוח אחר.

**② המדריך של הספק עצמו ממליץ להחליף DNS ל-1.1.1.1** "כפתרון תקלות
גלישה". זה אומר שספקיות האינטרנט בארץ חוסמות את השמות שלו בשכבת
ה-DNS. ואם ה-resolver שהשרת שלנו משתמש בו מחזיר תשובה חסומה, אנחנו
לא מדברים עם הספק בכלל — אנחנו מדברים עם **דף חסימה**.

ודף חסימה מחזיר 403.

כלומר כל 22 ה-403 שספרנו יכולים לא להיות הספק. הם יכולים להיות שכבת
חסימה בדרך, ואנחנו ייחסנו אותם לו. זה בדיוק סוג הטעות שבה "ודאות"
מתבררת כשגויה, וזה נבדק בשתי דקות.

## מה הסקריפט עושה

1. שואל על כל מארח **חמישה resolvers**: זה של המערכת, ‎1.1.1.1‎,
   ‎1.0.0.1‎, ‎8.8.8.8‎, ‎9.9.9.9‎.
2. משווה. תשובות שונות ⇒ מישהו בדרך משנה אותן.
3. לכל IP שהתקבל, מבקש ערוץ שעבד **ישירות מאותו IP**, עם ה-Host
   וה-SNI הנכונים. כלומר עוקף את ה-resolver לגמרי ושואל כל שרת בנפרד.
4. אומר איזה IP מגיש playlist ואיזה מחזיר 403.

## מה אפשר להסיק

    כל ה-resolvers מסכימים + 403      לא DNS. זה ה-IP או החשבון.
    תשובות שונות + אחד מהם מגיש       מצאנו. דיברנו עם השרת הלא נכון.
    המערכת לא פותרת בכלל              השם חסום אצל ה-resolver שלנו.
    כל ה-IP מחזירים 403               ה-IP שלנו חסום אצל הספק.

    python3 dns_check.py
    python3 dns_check.py --selftest     # בלי רשת

**קריאה בלבד.** אינו משנה resolver, אינו נוגע ב-‎/etc/resolv.conf‎,
ב-‎/etc/hosts‎, בחומת האש או בשירות. אם יימצא תיקון — הוא יודפס
כפקודה, ואתה תריץ אותה.

הפלט ממוסך: מארח, שם ספק ואסימונים אינם מודפסים. כתובות ה-IP **כן**
מודפסות חלקית, כי בלעדיהן אין מה להשוות.
"""
import argparse
import http.client
import json
import os
import pathlib
import re
import socket
import ssl
import struct
import sys
from collections import defaultdict

DATA = pathlib.Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
RELAY = re.compile(r"/hls-relay/(?:_fix/)?([^/?]+)/([^?]+)")
UA = "VLC/3.0.20 LibVLC/3.0.20"

RESOLVERS = [("מערכת", None), ("1.1.1.1", "1.1.1.1"), ("1.0.0.1", "1.0.0.1"),
             ("8.8.8.8", "8.8.8.8"), ("9.9.9.9", "9.9.9.9")]

_GENERIC = {"com", "net", "org", "www", "live", "stream", "iptv", "tv",
            "index", "playlist", "chunks", "m3u8", "http", "https"}


def labels(host: str) -> set:
    return {w for w in re.split(r"[.\-_:]+", host.lower())
            if len(w) >= 3 and not w.isdigit() and w not in _GENERIC}


def mask(s: str, host: str) -> str:
    s = re.sub(r"[a-z]+://[^/\s\"']+", "<ספק>", s)
    for w in sorted(labels(host), key=len, reverse=True):
        s = re.sub(re.escape(w), "<שם>", s, flags=re.I)
    return re.sub(r"\b(?=[A-Za-z0-9]{10,}\b)(?=[A-Za-z0-9]*\d)"
                  r"[A-Za-z0-9]+\b", "<אסימון>", s)


def dim(ip: str) -> str:
    """‏IP חייב להיות ניתן להשוואה, ולכן אינו ממוסך לגמרי — אבל גם אין
    צורך לפרסם את הכתובת המלאה של השרת של הספק."""
    p = ip.split(".")
    return f"{p[0]}.{p[1]}.x.{p[3]}" if len(p) == 4 else ip


# ── DNS גולמי, בלי תלויות ────────────────────────────────────────────────

def _qname(host: str) -> bytes:
    out = b""
    for part in host.rstrip(".").split("."):
        b = part.encode("idna") if any(ord(c) > 127 for c in part) \
            else part.encode()
        out += bytes([len(b)]) + b
    return out + b"\x00"


def _skip_name(buf: bytes, i: int) -> int:
    """מדלג על שם, כולל מצביעי דחיסה. בלי זה הניתוח נופל על כל תשובה
    אמיתית — שרתי DNS דוחסים שמות כמעט תמיד."""
    while True:
        if i >= len(buf):
            raise ValueError("חבילה קטועה")
        n = buf[i]
        if n == 0:
            return i + 1
        if n & 0xC0 == 0xC0:
            return i + 2                      # מצביע — השם נגמר כאן
        i += 1 + n


def dns_a(host: str, server: str | None, timeout=4.0):
    """רשומות A של host. (רשימת IP, שגיאה-או-None)."""
    if server is None:
        try:
            return sorted({ai[4][0] for ai in socket.getaddrinfo(
                host, None, socket.AF_INET)}), None
        except Exception as e:                                # noqa: BLE001
            return [], type(e).__name__
    pkt = (struct.pack(">HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0)
           + _qname(host) + struct.pack(">HH", 1, 1))
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        try:
            s.sendto(pkt, (server, 53))
            buf, _ = s.recvfrom(4096)
        finally:
            s.close()
    except Exception as e:                                    # noqa: BLE001
        return [], type(e).__name__

    return _parse_a(buf)


def _parse_a(buf: bytes):
    """ניתוח תשובת DNS. (רשימת IP, שגיאה-או-None).

    פונקציה אחת, ולא עוד העתק בבדיקה: בגרסה הראשונה הבדיקה הריצה
    שכפול של הלוגיקה הזאת, כלומר אימתה את ההעתק ולא את מה שרץ בפועל.
    """
    if len(buf) < 12:
        return [], "תשובה קצרה"
    _id, flags, qd, an, _ns, _ar = struct.unpack(">HHHHHH", buf[:12])
    rcode = flags & 0xF
    if rcode == 3:
        return [], "NXDOMAIN"
    if rcode != 0:
        return [], f"rcode={rcode}"
    i = 12
    try:
        for _ in range(qd):
            i = _skip_name(buf, i) + 4
        ips = []
        for _ in range(an):
            i = _skip_name(buf, i)
            if i + 10 > len(buf):
                break
            rtype, _cls, _ttl, rdlen = struct.unpack(">HHIH", buf[i:i + 10])
            i += 10
            if rtype == 1 and rdlen == 4:
                ips.append(".".join(str(b) for b in buf[i:i + 4]))
            i += rdlen
    except (ValueError, struct.error) as e:
        return [], f"חבילה פגומה ({type(e).__name__})"
    return sorted(set(ips)), (None if ips else "אין רשומת A")


# ── בקשה אל IP מסוים, עם ה-Host הנכון ───────────────────────────────────

def fetch_via(ip: str, host: str, port: int, scheme: str, path: str,
              timeout=10.0):
    """(תיאור, גוף-מקוצר). פונה ל-IP הזה ומציג את עצמו כ-host."""
    # השקע נפתח **ביד** אל ה-IP, ורק אחר כך נמסר לחיבור.
    #
    # הגרסה הראשונה בנתה HTTPSConnection(ip) ואז הציבה ‎conn.host = host‎
    # כדי לקבל SNI. אבל ‎connect()‎ קורא ‎_create_connection((self.host,
    # self.port))‎ — כלומר ההצבה הזאת מחזירה את החיבור לפתיחה **לפי שם**,
    # דרך ה-resolver, שזה בדיוק מה שהסקריפט נועד לעקוף. הבדיקה היחידה
    # שהריצה את המסלול הזה הייתה ב-http, ולכן זה לא נראה.
    try:
        sock = socket.create_connection((ip, port), timeout)
        if scheme == "https":
            ctx = ssl.create_default_context()
            # התעודה אינה הנושא כאן, והשאלה היא מי עונה. אימות היה
            # מפיל דווקא את המקרה המעניין — שרת שמציג תעודה לא נכונה.
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            # SNI לפי השם, כי שרת עם כמה אתרים מגיש אחרת ברירת מחדל
            sock = ctx.wrap_socket(sock, server_hostname=host)
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.sock = sock                  # מוגדר ⇒ connect() לא ייקרא
        conn.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", host if port in (80, 443)
                       else f"{host}:{port}")
        conn.putheader("User-Agent", UA)
        conn.endheaders()
        r = conn.getresponse()
        body = r.read(4096).decode("utf-8", "replace")
        conn.close()
        if r.status == 200:
            if "#EXTM3U" in body or "#EXT-X-" in body:
                return "200 · playlist ✓", ""
            return f"200 · לא playlist ({len(body)}ב)", body[:200]
        loc = r.getheader("Location") or ""
        return (f"{r.status}" + (f" → {loc[:40]}" if loc else ""),
                body[:200])
    except Exception as e:                                    # noqa: BLE001
        return type(e).__name__, ""


def origins() -> dict:
    try:
        return json.loads((DATA / "relay_hosts.json").read_text("utf-8"))
    except Exception:
        return {}


# ── בדיקה עצמית ─────────────────────────────────────────────────────────

def selftest() -> int:
    bad = 0

    def chk(ok, what):
        nonlocal bad
        if not ok:
            bad += 1
        print(f"{'✓' if ok else '✗'} {what}")

    # ① בניית שם
    chk(_qname("a.bc") == b"\x01a\x02bc\x00", "בניית QNAME")
    chk(_qname("a.bc.") == b"\x01a\x02bc\x00", "נקודה בסוף אינה משנה")

    # ② דילוג על שם — כולל מצביע דחיסה, שהוא המקרה שקורה בפועל
    # ‎\x01a\x02bc\x00‎ הוא 6 בתים (1+1, 1+2, אפס מסיים), ולכן המצביע
    # הבא יושב על 6. כתבתי 7, הבדיקה נפלה, והיא צדקה.
    chk(_skip_name(b"\x01a\x02bc\x00ZZ", 0) == 6, "דילוג על שם מלא")
    chk(_skip_name(b"\xc0\x0cZZ", 0) == 2, "דילוג על מצביע דחיסה")
    chk(len(_qname("a.bc")) == 6, "ואורך השם עצמו תואם")

    def answer(ips, *, rcode=0, compressed=True, cname=False):
        """תשובת DNS אמיתית למדי, לבדיקת הניתוח."""
        head = struct.pack(">HHHHHH", 0x1234, 0x8180 | rcode, 1,
                           len(ips) + (1 if cname else 0), 0, 0)
        body = _qname("x.test") + struct.pack(">HH", 1, 1)
        name = b"\xc0\x0c" if compressed else _qname("x.test")
        if cname:
            tgt = _qname("y.test")
            body += name + struct.pack(">HHIH", 5, 1, 60, len(tgt)) + tgt
        for ip in ips:
            body += name + struct.pack(">HHIH", 1, 1, 60, 4) \
                + bytes(int(x) for x in ip.split("."))
        return head + body

    got, err = _parse_a(answer(["203.0.113.5", "203.0.113.6"]))
    chk(got == ["203.0.113.5", "203.0.113.6"] and err is None,
        f"שתי רשומות A עם דחיסה ⇒ {got}")
    got, _ = _parse_a(answer(["203.0.113.5"], compressed=False))
    chk(got == ["203.0.113.5"], "גם בלי דחיסה")
    got, _ = _parse_a(answer(["203.0.113.9"], cname=True))
    chk(got == ["203.0.113.9"], "שרשרת CNAME ⇒ ה-A שבסופה")
    got, err = _parse_a(answer([], rcode=3))
    chk(got == [] and err == "NXDOMAIN", "NXDOMAIN מזוהה בשמו")
    got, err = _parse_a(b"\x12\x34")
    chk(got == [] and err is not None, "חבילה קטועה אינה מקריסה")

    # ③ מיסוך ועמעום
    chk(dim("203.0.113.77") == "203.0.x.77", "‏IP מעומעם אך בר-השוואה")
    chk(dim("::1") == "::1", "‏IPv6 נשאר כמו שהוא")
    m = mask("http://tv.acme-iptv.tv:8080/p/acme-iptv/s/1/i.m3u8",
             "tv.acme-iptv.tv")
    chk("acme-iptv" not in m, "שם הספק אינו בפלט")

    print("\n" + ("✓ הכל עבר" if not bad else f"✗ {bad} נכשלו"))
    return 1 if bad else 0


# ── ראשי ────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
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
    if not byhost:
        sys.exit("אין ערוצים עם כתובת רלֵיי בקטלוג.")

    verdicts = []
    for idx, (netloc, paths) in enumerate(
            sorted(byhost.items(), key=lambda kv: -len(kv[1])), 1):
        host = netloc.split(":")[0]
        o = org.get(host) or {}
        scheme = o.get("scheme") or "http"
        port = int(o.get("port") or (443 if scheme == "https" else 80))
        if ":" in netloc:
            port = int(netloc.split(":")[1])
        path = "/" + paths[0]

        print(f"\n{'=' * 62}\nספק {idx}   ({len(paths)} ערוצים בקטלוג)")
        print(f"  שם: {mask(host, host)}   ·   {scheme}:{port}")

        print("\n  מה כל resolver עונה:")
        seen = {}
        for label, srv in RESOLVERS:
            ips, err = dns_a(host, srv, min(a.timeout, 5.0))
            seen[label] = ips
            shown = ", ".join(dim(i) for i in ips) if ips else f"— {err}"
            print(f"    {label:<9} {shown}")

        sets = {label: tuple(v) for label, v in seen.items() if v}
        allips = sorted({i for v in seen.values() for i in v})
        if not allips:
            print("\n  ⇒ אף resolver לא פתר את השם. זו אינה תקלת ערוצים:")
            print("    השם עצמו אינו נפתר, ולכן שום בקשה לא הגיעה לספק.")
            verdicts.append("noresolve")
            continue

        disagree = len(set(sets.values())) > 1
        print("\n  " + ("⚠ ה-resolvers **אינם** מסכימים — מישהו בדרך "
                        "משנה את התשובה." if disagree
                        else "כולם מסכימים על אותן כתובות."))

        print(f"\n  ועכשיו ערוץ שעבד, ישירות מכל כתובת "
              f"({len(allips)} כתובות):")
        results = {}
        for ip in allips:
            what, body = fetch_via(ip, host, port, scheme, path, a.timeout)
            who = [lbl for lbl, v in seen.items() if ip in v]
            results[ip] = what
            print(f"    {dim(ip):<17} {what:<28} ({', '.join(who)})")
            if body.strip():
                print(f"        {mask(body.strip()[:160], host)}")

        good = [ip for ip, w in results.items() if "playlist ✓" in w]
        if good:
            verdicts.append("found")
            print(f"\n  ⇒ **{len(good)} כתובות כן מגישות playlist.**")
            srcs = sorted({lbl for ip in good
                           for lbl, v in seen.items() if ip in v})
            print(f"    הן מגיעות מ: {', '.join(srcs)}")
            if "מערכת" not in srcs:
                print("    וה-resolver של המערכת **אינו** מחזיר אותן.")
                print("\n    כלומר כל הזמן דיברנו עם השרת הלא נכון, וה-403")
                print("    לא היה הספק. התיקון הוא ב-resolver של השרת:")
                print(f"\n      # לבדיקה מהירה, בלי לשנות הגדרות:")
                print(f"      echo '{good[0]} {host}' >> /etc/hosts")
                print(f"      systemctl restart zovex-bot")
                print(f"\n    ואם זה עובד — עדיף resolver קבוע במקום /etc/hosts,")
                print(f"    כי ה-IP של הספק ישתנה והשורה הזאת תישאר ותשבור.")
        elif all(str(w).startswith(("403", "401")) for w in results.values()):
            verdicts.append("blocked")
            print("\n  ⇒ **כל** הכתובות מחזירות 403, גם אלה שמ-1.1.1.1.")
            print("    כלומר זה לא DNS: הבקשה מגיעה לספק והוא דוחה אותה.")
            print("    ומכיוון שאצל לקוח רגיל הזרם נמשך מה-IP שלו ואצלנו")
            print("    מ-IP אחד שפותח עשרות ערוצים — סביר שחסמו את ה-IP")
            print("    של השרת, ולא את החשבון.")
        else:
            verdicts.append("mixed")
            print("\n  ⇒ תשובות מעורבות. הטבלה למעלה היא המידע;")
            print("    אין כאן מסקנה אחת, וכדאי להריץ שוב בעוד שעה.")

    print(f"\n{'=' * 62}")
    if "found" in verdicts:
        print("יש כתובת שעובדת. זה הדבר היחיד שצריך לפעול עליו עכשיו.")
    elif verdicts and all(v == "blocked" for v in verdicts):
        print("‏DNS אינו הסיבה. הבקשות מגיעות ונדחות — וזה ה-IP של השרת.")
        print("אפשרויות, בסדר העדפה:")
        print("  1. לשאול אותו בהודעה אם ה-IP של השרת נחסם (אין צורך")
        print("     שיהיה בארץ בשביל לבדוק את זה).")
        print("  2. python3 why_403.py — ההודעה שלו תאמר אם זה IP או חשבון.")
        print("  3. להוריד את מספר הזרמים המקבילים שהרלֵיי מחזיק.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
