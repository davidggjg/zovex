#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""match_providers — ערוץ שבור אצל ספק אחד, ועובד אצל אחר.

## למה

44 ערוצים מקבלים ‎403 direct‎, ו-55 עובדים. ספורט, ילדים וחדשות הם
ערוצים שכמעט כל ספק מחזיק — ולכן סביר שחלק מ-44 השבורים קיימים גם
אצל הספקים שכן עונים.

זה הדבר היחיד שנשאר שתלוי בנו ולא בספק שבחו"ל.

## שלוש תוצאות, ולכל אחת משמעות אחרת

**① "כבר מכוסה"** — הערוץ קיים בקטלוג **פעמיים**, גם אצל ספק עובד.
אין מה לעשות: העותק העובד כבר מוגש, והשבור מוסתר. זו התוצאה הטובה,
והיא גם הסבירה ביותר.

**② "יש מקביל"** — הערוץ קיים אצל ספק עובד תחת שם דומה, ואומת שהוא
באמת מגיש playlist. אפשר להפנות את השבור אליו.

**③ "אין מקביל"** — אין לו תחליף אצל אף ספק עובד. הוא ממתין לספק.

## השמירה מפני התאמה שגויה

"ספורט 5" ו"ספורט 6" הם שמות דומים מאוד ו**אינם** אותו ערוץ. לכן אחרי
הנרמול, אם בשני השמות יש ספרות — הן חייבות להיות **זהות**. בלי הכלל
הזה כל ערוץ ממוספר היה מתחלף בשכן שלו, וזה גרוע בהרבה מערוץ שבור:
הצופה מקבל תוכן אחר בלי לדעת.

## מה הוא עושה ומה לא

**רק מדווח, ואינו כותב.** כתיבה ישירה ל-content.json עוקפת את
‎base_version‎ של הפאנל — הנעילה שמונעת דריסת עריכה מקבילה. ההחלפה
עצמה נעשית ב-‎import_m3u.py‎, שעובר דרך הפאנל כמו שצריך.

    python3 match_providers.py                 # דוח בלבד
    python3 match_providers.py --min 0.8       # סף דמיון
    python3 match_providers.py --selftest

הפלט ממוסך. שמות ערוצים מודפסים — הם מה שנשאל.
"""
import argparse
import difflib
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

# מילים שאינן מזהות ערוץ ולכן אינן נספרות בהשוואה
_NOISE = {"hd", "fhd", "uhd", "sd", "4k", "1080", "720", "ערוץ", "channel",
          "tv", "live", "il", "israel", "ישראל", "חי"}

_GENERIC = {"com", "net", "org", "www", "live", "stream", "iptv", "tv",
            "index", "playlist", "chunks", "m3u8", "http", "https", "pw"}


def labels(host: str) -> set:
    return {w for w in re.split(r"[.\-_:]+", host.lower())
            if len(w) >= 3 and not w.isdigit() and w not in _GENERIC}


def mask(s: str, host: str) -> str:
    s = re.sub(r"[a-z]+://[^/\s\"']+", "<ספק>", s)
    for w in sorted(labels(host), key=len, reverse=True):
        s = re.sub(re.escape(w), "<שם>", s, flags=re.I)
    return re.sub(r"\b(?=[A-Za-z0-9]{10,}\b)(?=[A-Za-z0-9]*\d)"
                  r"[A-Za-z0-9]+\b", "<אסימון>", s)


def title_of(e: dict) -> str:
    for k in ("title", "name", "channel", "caption"):
        v = e.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def is_live(e: dict) -> bool:
    return e.get("category") == LIVE_CATEGORY or bool(e.get("is_live"))


def norm(s: str) -> str:
    """נרמול שם לצורך השוואה. מסיר רעש, מקפים וסימני ציטוט."""
    s = (s or "").lower().replace("־", " ").replace("-", " ")
    s = re.sub(r"[\"'`׳״()\[\]|/]", " ", s)
    toks = [t for t in re.split(r"\s+", s) if t and t not in _NOISE]
    return " ".join(toks).strip()


def digits(s: str) -> list:
    """הספרות בשם, כרשימה. ‎"ספורט 6"‎ ⇒ ['6']."""
    return re.findall(r"\d+", norm(s))


def same_channel(a: str, b: str, min_ratio: float) -> float:
    """ציון התאמה 0..1. 0 = לא אותו ערוץ.

    הכלל הקשה: אם בשני השמות יש ספרות, הן חייבות להיות זהות.
    ‎"ספורט 5"‎ ו-‎"ספורט 6"‎ דומים ב-0.9 ואינם אותו ערוץ בכלל.
    """
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    da, db = digits(a), digits(b)
    if da and db and da != db:
        return 0.0
    # מספר באחד ולא בשני ("ספורט" מול "ספורט 6") — לא מתאימים
    if bool(da) != bool(db):
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    if ta and (ta <= tb or tb <= ta):
        return 0.95
    r = difflib.SequenceMatcher(None, na, nb).ratio()
    return r if r >= min_ratio else 0.0


def ask(scheme: str, host: str, port: int, path: str, timeout=10.0):
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
        ok = r.status == 200 and ("#EXTM3U" in body or "#EXT-X-" in body)
        return (f"{r.status}" if not ok else "200 ✓"), ok
    except Exception as e:                                    # noqa: BLE001
        return type(e).__name__, False
    finally:
        try:
            if sock:
                sock.close()
        except Exception:                                     # noqa: BLE001
            pass


def url_parts(netloc: str, path: str, org: dict):
    host = netloc.split(":")[0]
    o = org.get(host) or {}
    scheme = o.get("scheme") or "http"
    port = int(netloc.split(":")[1]) if ":" in netloc else \
        int(o.get("port") or (443 if scheme == "https" else 80))
    return scheme, host, port, "/" + path


def selftest() -> int:
    bad = 0

    def chk(ok, what):
        nonlocal bad
        if not ok:
            bad += 1
        print(f"{'✓' if ok else '✗'} {what}")

    # ① נרמול
    chk(norm("ערוץ ספורט 6 HD") == "ספורט 6", f"נרמול ⇒ {norm('ערוץ ספורט 6 HD')!r}")
    chk(norm("Sport 6 FHD") == "sport 6", "רעש אנגלי מוסר")
    chk(norm("ספורט-6") == "ספורט 6", "מקף")
    chk(norm("  ") == "", "ריק")

    # ② הכלל הקשה: מספרים שונים = לא אותו ערוץ
    chk(same_channel("ספורט 5", "ספורט 6", 0.8) == 0.0,
        "‏ספורט 5 ≠ ספורט 6 — הכלל שמונע החלפת תוכן")
    chk(same_channel("ספורט 1", "ספורט 11", 0.8) == 0.0, "‏1 ≠ 11")
    chk(same_channel("ספורט", "ספורט 6", 0.8) == 0.0,
        "מספר באחד ולא בשני")
    chk(same_channel("ערוץ 13", "ערוץ 13 HD", 0.8) == 1.0,
        "אותו מספר, רעש שונה ⇒ התאמה מלאה")
    chk(same_channel("ספורט 6", "ספורט 6", 0.8) == 1.0, "זהה")
    chk(same_channel("ספורט 6 פלוס", "ספורט 6", 0.8) >= 0.9,
        "תת-קבוצה של אסימונים")
    chk(same_channel("ילדים", "חדשות", 0.8) == 0.0, "שמות שונים לגמרי")
    chk(same_channel("", "ספורט", 0.8) == 0.0, "שם ריק")
    # ושיבוש קל כן מתאים
    chk(same_channel("דיסקברי", "דיסקוברי", 0.75) > 0,
        "כתיב שונה מתאים מעל הסף")
    chk(same_channel("דיסקברי", "דיסקוברי", 0.99) == 0.0,
        "ומתחת לסף — לא")

    # ③ ספרות
    chk(digits("ספורט 6") == ["6"], "חילוץ ספרות")
    chk(digits("ערוץ 13 HD") == ["13"], "‏HD אינו ספרה")
    chk(digits("ילדים") == [], "בלי ספרות")

    # ④ שידור חי ומיסוך
    chk(is_live({"category": LIVE_CATEGORY}) and not is_live({"category": "x"}),
        "זיהוי שידור חי")
    m = mask("https://tv.acme-iptv.tv:86/p/acme/s/1/i.m3u8", "tv.acme-iptv.tv")
    chk("acme" not in m, "מארח אינו בפלט")

    print("\n" + ("✓ הכל עבר" if not bad else f"✗ {bad} נכשלו"))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=float, default=0.82, help="סף דמיון")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--gap", type=float, default=0.3)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    try:
        raw = CONTENT.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as e:                                    # noqa: BLE001
        sys.exit(f"לא ניתן לקרוא את {CONTENT}: {e}")
    items = data if isinstance(data, list) else data.get("movies", [])
    live = [e for e in items if is_live(e)]
    if not live:
        sys.exit("אין שידורים חיים בקטלוג.")

    try:
        org = json.loads((DATA / "relay_hosts.json").read_text("utf-8"))
    except Exception:
        org = {}

    byhost = defaultdict(list)
    for e in live:
        g = RELAY.search((e.get("video_url") or "").strip())
        if g:
            byhost[g.group(1)].append((e, g.group(1), g.group(2)))
    order = sorted(byhost.items(), key=lambda kv: -len(kv[1]))

    # ── מי עובד ומי לא ───────────────────────────────────────────────
    print("בודק איזה ספק מגיש:\n")
    health = {}
    for i, (netloc, rows) in enumerate(order, 1):
        _e, _nl, path = rows[0]
        sch, host, port, p = url_parts(netloc, path, org)
        what, ok = ask(sch, host, port, p, a.timeout)
        health[netloc] = ok
        print(f"  ספק {i}  {mask(host, host):<18} {len(rows):>3} ערוצים   "
              f"{'✓ מגיש' if ok else '✗ ' + what}")
        time.sleep(a.gap)

    good_hosts = [nl for nl, ok in health.items() if ok]
    bad_hosts = [nl for nl, ok in health.items() if not ok]
    if not bad_hosts:
        print("\nכל הספקים מגישים — אין מה להחליף.")
        return 0
    if not good_hosts:
        print("\nאף ספק אינו מגיש. אין ממה להציל, וזה כנראה אנחנו ולא הם.")
        return 1

    pool = [(e, nl, pth) for nl in good_hosts for e, _n, pth in byhost[nl]]
    broken = [(e, nl, pth) for nl in bad_hosts for e, _n, pth in byhost[nl]]
    print(f"\n{len(broken)} שבורים · {len(pool)} זמינים אצל ספקים עובדים\n")
    print("=" * 66)

    covered, matched, orphan = [], [], []
    for e, nl, _pth in broken:
        t = title_of(e)
        if not t:
            orphan.append((e, "(בלי שם)", None))
            continue
        best, score = None, 0.0
        for ge, gnl, gpth in pool:
            s = same_channel(t, title_of(ge), a.min)
            if s > score:
                best, score = (ge, gnl, gpth), s
        if not best:
            orphan.append((e, t, None))
        elif score >= 0.999 and norm(title_of(best[0])) == norm(t):
            covered.append((e, t, best))
        else:
            matched.append((e, t, best, score))

    # ── ① כבר מכוסה ──────────────────────────────────────────────────
    if covered:
        print(f"\n① כבר מכוסה — {len(covered)} ערוצים קיימים בקטלוג גם אצל "
              f"ספק עובד:\n")
        for _e, t, best in covered:
            print(f"   {t:<30} ← כבר מוגש מספק אחר")
        print("\n   אין מה לעשות: העותק העובד כבר מוגש, והשבור מוסתר.")

    # ── ② יש מקביל, ואומת ────────────────────────────────────────────
    plan = []
    if matched:
        print(f"\n② יש מקביל — {len(matched)} ערוצים. מאמת שהם באמת "
              f"מגישים:\n")
        for e, t, best, score in matched:
            ge, gnl, gpth = best
            sch, host, port, p = url_parts(gnl, gpth, org)
            what, ok = ask(sch, host, port, p, a.timeout)
            print(f"   {t:<26} → {title_of(ge):<24} "
                  f"({score:.2f})  {'✓' if ok else '✗ ' + what}")
            if ok:
                plan.append((e, ge))
            time.sleep(a.gap)

    # ── ③ אין מקביל ──────────────────────────────────────────────────
    if orphan:
        print(f"\n③ אין מקביל — {len(orphan)} ערוצים ממתינים לספק:\n")
        for _e, t, _x in orphan[:20]:
            print(f"   {t}")
        if len(orphan) > 20:
            print(f"   ... ועוד {len(orphan) - 20}")

    print("\n" + "=" * 66)
    print(f"סיכום: {len(covered)} כבר מכוסים · {len(plan)} ניתנים להחלפה "
          f"· {len(orphan)} ממתינים")

    if not plan:
        print("\nאין מה להחיל.")
        return 0
    print("\nזהו דוח בלבד — הכלי הזה אינו כותב.")
    print("ההחלפה עצמה נעשית דרך import_m3u.py, שעובר בפאנל עם")
    print("base_version — כלומר עריכה מקבילה אינה נדרסת. כתיבה ישירה")
    print("ל-content.json עוקפת את הנעילה הזאת, ולכן הוסרה מכאן.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
