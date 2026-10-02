#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_channel — האם ערוץ מסוים עובד, עכשיו, לפי שם.

    python3 check_channel.py "ספורט 6"
    python3 check_channel.py ספורט            # כל מי שבשמו "ספורט"
    python3 check_channel.py --all            # כל הערוצים החיים
    python3 check_channel.py --selftest

## למה כלי ולא בדיקה חד-פעמית

"ספורט 6 עובד?" היא שאלה שחוזרת על כל ערוץ בנפרד, ואי אפשר לענות עליה
מבחוץ: הפורטים של הספק חסומים, ולשרת יש גישה כי הוא ממילא מרלה אותו.

הכלי שואל את **המקור** ישירות — כלומר התשובה היא על הספק, לא על
המטמון שלנו ולא על סימון "לא עונה" שאנחנו עצמנו הדבקנו. אם המקור מגיש
playlist, הערוץ עובד; אם הוא מחזיר 403, הוא לא, וזה לא משנה מה
האפליקציה מראה.

הפלט כולל את **מספר הספק** באותו מספור של ‎dns_check‎, כי זו לרוב כל
התשובה: ערוצים על ספק 1 ו-4 עובדים, ו-44 על הספק האחד שמחזיר
‎403 direct‎ אינם — וזה נקבע לפי על איזה שרת הערוץ יושב ולא לפי הערוץ
עצמו.

## אם השם לא נמצא

מודפסים שמות אמיתיים מהקטלוג. "לא נמצא" בלי לומר מה כן יש שולח לחפש
במקום הלא נכון — וזו טעות שכבר עלתה לי סבב שלם ב-‎make_formats‎.

**הפלט ממוסך** (מארח, שם ספק ואסימונים). שמות הערוצים מודפסים כמו
שהם, כי הם בדיוק מה שנשאל.

קריאה בלבד.
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
from collections import defaultdict

DATA = pathlib.Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
RELAY = re.compile(r"/hls-relay/(?:_fix/)?([^/?]+)/([^?]+)")
LIVE_CATEGORY = "שידורים חיים"
UA = "VLC/3.0.20 LibVLC/3.0.20"

_GENERIC = {"com", "net", "org", "www", "live", "stream", "iptv", "tv",
            "index", "playlist", "chunks", "m3u8", "http", "https", "pw"}


def labels(host: str) -> set:
    return {w for w in re.split(r"[.\-_:]+", host.lower())
            if len(w) >= 3 and not w.isdigit() and w not in _GENERIC}


def mask(s: str, host: str) -> str:
    s = re.sub(r"[a-z]+://[^/\s\"']+", "<ספק>", s)
    for w in sorted(labels(host), key=len, reverse=True):
        s = re.sub(re.escape(w), "<שם>", s, flags=re.I)
    s = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "<כתובת-ip>", s)
    return re.sub(r"\b(?=[A-Za-z0-9]{10,}\b)(?=[A-Za-z0-9]*\d)"
                  r"[A-Za-z0-9]+\b", "<אסימון>", s)


def title_of(e: dict) -> str:
    """השם, מאיזה שדה שהוא קיים בו. הקטלוג אינו עקבי בין פריטים."""
    for k in ("title", "name", "channel", "caption"):
        v = e.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def is_live(e: dict) -> bool:
    return e.get("category") == LIVE_CATEGORY or bool(e.get("is_live"))


def norm(s: str) -> str:
    """להשוואה סלחנית: רווחים כפולים, מקפים וגרשיים אינם אמורים להכשיל.

    ‎"ספורט 6"‎, ‎"ספורט-6"‎ ו-‎"ספורט  6"‎ הם אותו ערוץ מבחינת מי ששואל.
    """
    s = (s or "").lower().replace("־", " ").replace("-", " ")
    s = re.sub(r"[\"'`׳״]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def matches(e: dict, needle: str) -> bool:
    n = norm(needle)
    return bool(n) and n in norm(title_of(e))


def origins() -> dict:
    try:
        return json.loads((DATA / "relay_hosts.json").read_text("utf-8"))
    except Exception:
        return {}


def full_url(netloc: str, path: str, org: dict) -> str:
    host = netloc.split(":")[0]
    o = org.get(host) or {}
    scheme = o.get("scheme") or "http"
    port = int(netloc.split(":")[1]) if ":" in netloc else \
        int(o.get("port") or (443 if scheme == "https" else 80))
    return f"{scheme}://{host}:{port}/{path}"


def ask(scheme: str, host: str, port: int, path: str, timeout=10.0):
    """(תיאור, עובד?). לעולם לא זורק."""
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
        conn.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", host if port in (80, 443) else f"{host}:{port}")
        conn.putheader("User-Agent", UA)
        conn.endheaders()
        r = conn.getresponse()
        body = r.read(2048).decode("utf-8", "replace")
        conn.close()
        if r.status == 200 and ("#EXTM3U" in body or "#EXT-X-" in body):
            segs = len([l for l in body.splitlines()
                        if l.strip() and not l.startswith("#")])
            return (f"עובד ✓  ({segs} מקטעים)" if segs
                    else "200 אבל playlist ריק"), bool(segs)
        if r.status == 200:
            return f"200 אבל אינו playlist ({len(body)}ב)", False
        note = body.strip()[:40]
        return f"{r.status}" + (f" · {note}" if note else ""), False
    except Exception as e:                                    # noqa: BLE001
        return type(e).__name__, False
    finally:
        try:
            if sock:
                sock.close()
        except Exception:                                     # noqa: BLE001
            pass


def selftest() -> int:
    bad = 0

    def chk(ok, what):
        nonlocal bad
        if not ok:
            bad += 1
        print(f"{'✓' if ok else '✗'} {what}")

    # ① השם נמצא מאיזה שדה שהוא בו
    chk(title_of({"title": "ספורט 6"}) == "ספורט 6", "שדה title")
    chk(title_of({"name": "ספורט 6"}) == "ספורט 6", "שדה name")
    chk(title_of({"title": "  ", "name": "ילדים"}) == "ילדים",
        "שדה ריק מדולג")
    chk(title_of({}) == "" and title_of({"title": None}) == "", "בלי שם")

    # ② השוואה סלחנית — אותו ערוץ בכמה כתיבים
    for t in ("ספורט 6", "ספורט-6", "ספורט  6", "ערוץ ספורט 6 HD"):
        chk(matches({"title": t}, "ספורט 6"), f"‏{t!r} נמצא")
    chk(matches({"title": "ספורט 6"}, "ספורט"), "חיפוש חלקי")
    chk(not matches({"title": "ספורט 5"}, "ספורט 6"), "‏5 אינו 6")
    chk(not matches({"title": "ספורט 6"}, ""), "חיפוש ריק אינו מתאים להכל")
    chk(matches({"title": "Sport 6"}, "sport 6"), "רישיות אינן משנות")

    # ③ שידור חי מזוהה בשתי הדרכים
    chk(is_live({"category": LIVE_CATEGORY}), "לפי קטגוריה")
    chk(is_live({"is_live": True}), "לפי דגל")
    chk(not is_live({"category": "סרטים"}), "סרט אינו שידור חי")

    # ④ מיסוך
    m = mask("https://tv.acme-iptv.tv:86/p/acme/s/412/i.m3u8?token=AB12CD34EF",
             "tv.acme-iptv.tv")
    chk("acme" not in m and "AB12CD34EF" not in m, "מארח ואסימון אינם בפלט")

    print("\n" + ("✓ הכל עבר" if not bad else f"✗ {bad} נכשלו"))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?", default="", help="שם או חלק ממנו")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.name and not a.all:
        sys.exit('צריך שם: python3 check_channel.py "ספורט 6"   (או --all)')

    try:
        data = json.loads(CONTENT.read_text(encoding="utf-8"))
    except Exception as e:                                    # noqa: BLE001
        sys.exit(f"לא ניתן לקרוא את {CONTENT}: {e}")
    items = data if isinstance(data, list) else data.get("movies", [])
    live = [e for e in items if is_live(e)]
    if not live:
        sys.exit("אין שידורים חיים בקטלוג.")

    # מספור הספקים — אותו סדר כמו dns_check, כדי שאפשר יהיה להצליב
    counts = defaultdict(int)
    for e in live:
        g = RELAY.search((e.get("video_url") or "").strip())
        if g:
            counts[g.group(1)] += 1
    rank = {nl: i for i, (nl, _c) in enumerate(
        sorted(counts.items(), key=lambda kv: -kv[1]), 1)}

    hits = live if a.all else [e for e in live if matches(e, a.name)]
    if not hits:
        print(f'לא נמצא ערוץ ששמו מכיל {a.name!r}.\n')
        print("כך נראים שמות הערוצים בקטלוג:")
        for e in live[:14]:
            t = title_of(e)
            if t:
                print(f"  {t}")
        print(f"\n  (מתוך {len(live)} שידורים חיים)")
        return 1

    org = origins()
    print(f"{len(hits)} ערוצים תואמים:\n")
    ok_n = 0
    for e in hits:
        t = title_of(e) or "(בלי שם)"
        g = RELAY.search((e.get("video_url") or "").strip())
        if not g:
            print(f"  {t:<28} — אינו דרך הרלֵיי (כתובת חיצונית)")
            continue
        netloc, path = g.group(1), g.group(2)
        host = netloc.split(":")[0]
        url = full_url(netloc, path, org)
        scheme = url.split("://")[0]
        port = int(url.split("://")[1].split("/")[0].split(":")[1])
        what, good = ask(scheme, host, port, "/" + path, a.timeout)
        ok_n += bool(good)
        print(f"  {t:<28} ספק {rank.get(netloc, '?')}   {what}")
        time.sleep(0.25)

    print(f"\n{'=' * 50}")
    if ok_n == len(hits):
        print("עובד. אם באפליקציה זה לא מתנגן — זו בעיה אצלנו ולא אצל")
        print("הספק, ושווה להסתכל ביומן על הערוץ הזה.")
    elif ok_n:
        print(f"{ok_n} מתוך {len(hits)} עובדים. ההבדל הוא כמעט תמיד")
        print("על איזה ספק הערוץ יושב — ראה את מספר הספק בכל שורה.")
    else:
        print("אינו עובד — המקור עצמו אינו מגיש. זה אצל הספק, ולא")
        print("משנה מה האפליקציה מראה.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
