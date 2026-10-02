#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""find_gateway — לחפש את **המקום** החדש, לא את המספר.

## למה הסריקה הקודמת הייתה הכלי הלא נכון

‎hunt_channels‎ שאל 1,200 פעמים "אולי הערוץ הוא מספר אחר?" וקיבל אפס.
אבל הספק לא אמר שהמספרים זזו — הוא אמר שהם **החליפו חוות שרתים**. ואם
הכתובת, הפורט או צורת הנתיב השתנו, אז כל מספר שננסה על הכתובת הישנה
יקבל את אותה תשובה. סרקנו מיליון דלתות בבניין הלא נכון.

ארבעה שלבים, כ-70 בקשות בסך הכל, וכל אחד עונה על שאלה אחרת.

## שלב א — השאלה שמפרידה הכל (2 בקשות)

הנתיב הישן מחזיר ‎403 direct‎. השאלה היא מה מחזיר נתיב שבטוח **אינו
קיים**:

    שונה (403 לעומת 404)   הנתיב הישן **קיים**, והוא רק מסורב.
                            כלומר המספור לא השתנה, וסריקה היא בזבוז.
    זהה (403 על שניהם)      "direct" היא תשובה גורפת ואינה אומרת דבר
                            על קיום. אז השלבים הבאים רלוונטיים.

שתי בקשות שקובעות אם כל השאר שווה משהו. לא עשינו אותן, וזו הייתה
הטעות המרכזית.

## שלב ב — איזה שער זה בכלל (~12)

שערי IPTV חושפים נתיבי גילוי. התשובות שלהם אומרות **איזה סוג** שער
עומד שם עכשיו — Xtream, Stalker או משהו אחר. אחרי החלפת חווה זה הדבר
שסביר שהשתנה, וזה משנה את צורת הקישור כולה.

## שלב ג — אותו מספר, עטיפה אחרת (~25)

אם המספרים נשארו והעטיפה זזה — ‎index.m3u8‎ במקום ‎playlist.m3u8‎,
רמה פחות בנתיב, סיומת אחרת — זה נמצא כאן, ב-25 בקשות.

## שלב ד — פורטים (~15)

הם מגישים על 86 ו-7070. החלפת חווה מזיזה פורטים כמעט תמיד. 15 פורטים
נפוצים הם 15 בקשות, לא מיליון.

## מה הוא לא עושה

אינו מנחש סיסמאות, אינו מנסה אסימונים, ואינו סורק מרחב מזהים. כל
שאלה כאן היא "באיזו **צורה** אתם מגישים", ועל זה שרת עונה מעצמו. בקשה
אחת לכל מועמד, עם הפוגה.

    python3 find_gateway.py              # כל השבורים
    python3 find_gateway.py --host 3     # ספק מסוים
    python3 find_gateway.py --phase a    # רק שלב א
    python3 find_gateway.py --selftest

הפלט ממוסך. קריאה בלבד.
"""
import argparse
import http.client
import json
import os
import pathlib
import re
import secrets
import socket
import ssl
import sys
import time
from collections import OrderedDict, defaultdict

DATA = pathlib.Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
RELAY = re.compile(r"/hls-relay/(?:_fix/)?([^/?]+)/([^?]+)")
UA = "VLC/3.0.20 LibVLC/3.0.20"

_GENERIC = {"com", "net", "org", "www", "live", "stream", "iptv", "tv",
            "index", "playlist", "chunks", "m3u8", "http", "https", "pw"}

# נתיבי גילוי של שערי IPTV נפוצים
DISCOVER = [
    "/", "/index.php", "/player_api.php", "/panel_api.php", "/get.php",
    "/xmltv.php", "/enigma2.php", "/portal.php", "/c/", "/live/",
    "/stalker_portal/server/load.php", "/server/load.php",
]

# פורטים שמגישים IPTV בפועל
PORTS = [80, 443, 8080, 8000, 8081, 8880, 2082, 2086, 2095, 2096,
         25461, 25500, 9981, 7070, 86, 88, 8888]

# שמות קובץ שמסיימים נתיב HLS
FILES = ["index.m3u8", "playlist.m3u8", "master.m3u8", "chunks.m3u8",
         "live.m3u8", "mono.m3u8", "index.ts", "tracks-v1a1/mono.m3u8"]

# עטיפות נתיב נפוצות, עם {n} במקום המזהה
WRAPS = ["live/{n}", "hls/{n}", "stream/{n}", "ch/{n}", "{n}",
         "live/{n}/index", "iptv/{n}"]


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


def loc_of(ct: str) -> str:
    """ה-Location מתוך מה ש-ask החזיר (‎"<סוג> → <כתובת>"‎), או ריק."""
    return ct.split("→", 1)[1].strip() if "→" in ct else ""


def redirect_note(loc: str, probed_host: str, probed_port: int) -> str:
    """מה אומרת הפניה, בלי להדפיס את המארח עצמו.

    ‎mask‎ מחליף כל כתובת ב-‎<ספק>‎, ולכן הפניה הודפסה כ-
    ‎"→ <ספק>/p/g/s/103/index.m3u8"‎ — כלומר הסתיר בדיוק את הדבר
    היחיד שבגללו מדפיסים אותה. הפתרון אינו להסיר את המיסוך אלא לפרק
    את הכתובת ולומר **מה השתנה בה**: זה מספיק כדי לדעת אם יש כאן
    כתובת חדשה, ואינו מפרסם את התשתית שלהם.
    """
    g = re.match(r"^([a-z]+)://([^/:]+)(?::(\d+))?(/.*)?$", loc.strip(),
                 re.I)
    if not g:
        return f"הפניה יחסית: {loc.strip()[:60]}"
    scheme, host2, port2, path2 = g.group(1), g.group(2), g.group(3), \
        g.group(4) or "/"
    port2 = int(port2) if port2 else (443 if scheme == "https" else 80)
    same_host = host2.lower() == probed_host.lower()
    bits = []
    if not same_host:
        # לא מדפיסים את השם, אבל כן את מה שמאפשר להחליט: האם זה אותו
        # דומיין עם תת-שם אחר, או מארח אחר לגמרי.
        p1 = probed_host.lower().split(".")
        p2 = host2.lower().split(".")
        if len(p1) >= 2 and len(p2) >= 2 and p1[-2:] == p2[-2:]:
            bits.append("תת-שם אחר באותו דומיין")
        else:
            bits.append("**מארח אחר לגמרי**")
    else:
        bits.append("אותו מארח")
    bits.append(f"פורט {port2}" + (" (אותו)" if port2 == probed_port else ""))
    bits.append(scheme.lower())
    # הנתיב ממוסך גם הוא. הגרסה הקודמת הסתירה את המארח והדפיסה את
    # הנתיב כמו שהוא — ושם הספק יושב **בתוך הנתיב** (‎/p/<שם>/s/..‎),
    # כך שהוא הודפס במלואו. זו אותה טעות בדיוק שתוקנה ב-make_formats
    # ותועדה שם, וחזרתי עליה כאן.
    safe = path2
    for w in sorted(labels(probed_host) | labels(host2), key=len,
                    reverse=True):
        safe = re.sub(re.escape(w), "<שם>", safe, flags=re.I)
    safe = re.sub(r"\b(?=[A-Za-z0-9]{10,}\b)(?=[A-Za-z0-9]*\d)"
                  r"[A-Za-z0-9]+\b", "<אסימון>", safe)
    bits.append(f"נתיב {safe[:46]}")
    return " · ".join(bits)


def ident_of(path: str) -> str:
    """מזהה הערוץ בנתיב — המקטע המספרי האחרון."""
    hits = re.findall(r"/(\d{1,6})(?=/|\.|$)", "/" + path)
    return hits[-1] if hits else ""


def path_variants(path: str, ident: str):
    """[(תיאור, נתיב)] — אותו מזהה, עטיפות וסיומות אחרות."""
    out, seen = [], set()

    def add(why, p):
        p = p.lstrip("/")
        if p and p != path and p not in seen:
            seen.add(p)
            out.append((why, p))

    segs = [s for s in path.split("/") if s]
    # ① אותו נתיב, שם קובץ אחר
    if segs and ("." in segs[-1] or segs[-1].endswith("m3u8")):
        stem = "/".join(segs[:-1])
        for f in FILES:
            add("שם קובץ", f"{stem}/{f}")
        add("בלי קובץ", stem + "/")
    # ② רמה אחת פחות בנתיב, סביב המזהה
    if ident:
        for i, s in enumerate(segs):
            if s == ident:
                add("בלי הרמה שמעל", "/".join(segs[:i - 1] + segs[i:])
                    if i >= 1 else "/".join(segs[i:]))
                add("מזהה עם סיומת", "/".join(segs[:i] + [ident + ".m3u8"]))
                break
        # ③ עטיפות אחרות לגמרי
        for w in WRAPS:
            base = w.replace("{n}", ident)
            add("עטיפה", f"{base}/index.m3u8")
            add("עטיפה", f"{base}.m3u8")
    return out


def ask(scheme: str, host: str, port: int, path: str, timeout=8.0):
    """(קוד, גוף, סוג-תוכן). לעולם לא זורק."""
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
        body = r.read(1024).decode("utf-8", "replace")
        ct = r.getheader("Content-Type") or ""
        loc = r.getheader("Location") or ""
        conn.close()
        return str(r.status), body, (ct + (f" → {loc}" if loc else ""))
    except Exception as e:                                    # noqa: BLE001
        return type(e).__name__, "", ""
    finally:
        try:
            if sock:
                sock.close()
        except Exception:                                     # noqa: BLE001
            pass


def is_pl(body: str) -> bool:
    return "#EXTM3U" in body or "#EXT-X-" in body


def short(code: str, body: str) -> str:
    b = " ".join(body.split())[:46]
    return f"{code}" + (f" · {b}" if b else "")


def selftest() -> int:
    bad = 0

    def chk(ok, what):
        nonlocal bad
        if not ok:
            bad += 1
        print(f"{'✓' if ok else '✗'} {what}")

    # ① חילוץ המזהה
    chk(ident_of("p/g/s/412/index.m3u8") == "412", "מזהה מתוך נתיב")
    chk(ident_of("live/bob/pass/412.m3u8") == "412", "מזהה לפני סיומת")
    chk(ident_of("p/g/s/412/chunks.m3u8") == "412", "לא תופס מספר מהקובץ")
    chk(ident_of("a/b/c.m3u8") == "", "בלי מזהה מספרי")

    # ② וריאנטים: אותו מזהה, צורות אחרות — ובלי כפילויות ובלי המקור
    p = "p/g/s/412/index.m3u8"
    v = path_variants(p, "412")
    paths = [x[1] for x in v]
    chk(len(paths) == len(set(paths)), f"{len(paths)} וריאנטים, בלי כפילות")
    chk(p not in paths, "הנתיב המקורי אינו ברשימה — אין טעם לבדוק אותו שוב")
    chk("p/g/s/412/playlist.m3u8" in paths, "שם קובץ אחר")
    chk("p/g/s/412/master.m3u8" in paths, "master")
    chk("live/412/index.m3u8" in paths, "עטיפה אחרת")
    chk("412.m3u8" in paths, "מזהה בשורש")
    chk(all("412" in x or x.endswith("/") for x in paths),
        "כל וריאנט נושא את אותו מזהה")
    chk(len(paths) < 40, f"וריאנטים מוגבלים ({len(paths)}) — לא סריקה")

    # ③ נתיב בלי מזהה אינו מייצר עטיפות מופרכות
    v2 = [x[1] for x in path_variants("a/b/c.m3u8", "")]
    chk(all("{n}" not in x for x in v2), "בלי מזהה — בלי תבניות פתוחות")

    # ④ הפניה: מה שהודפס קודם כ-"<ספק>/..." ולכן לא אמר כלום
    chk(loc_of("text/html → http://x.tv/a") == "http://x.tv/a", "חילוץ Location")
    chk(loc_of("text/html") == "", "בלי Location")
    H = "tv.acme-iptv.tv"
    n = redirect_note("http://new-farm.other-co.net:9090/p/g/s/103/i.m3u8",
                      H, 7070)
    chk("מארח אחר לגמרי" in n, f"מארח אחר מזוהה ⇒ {n[:46]}")
    chk("9090" in n, "והפורט החדש נאמר במפורש")
    chk("new-farm" not in n and "other-co" not in n,
        "אבל שם המארח עצמו אינו מודפס")
    # והנתיב — שם הספק יושב **בתוכו**, וזה מה שדלף בהרצה אמיתית
    leak = redirect_note(f"https://{H}:443/p/acme-iptv/s/103/playlist.m3u8",
                         H, 7070)
    chk("acme" not in leak, f"שם הספק בתוך הנתיב מוסתר ⇒ {leak[-30:]}")
    chk("<שם>" in leak, "ומסומן ככזה")
    chk("103" in leak and "playlist" in leak,
        "אבל המזהה והצורה נשארים קריאים — בלעדיהם אין בשביל מה להדפיס")
    chk("<אסימון>" in redirect_note(
        f"https://{H}:443/p/x/s/AB12CD34EF99/i.m3u8", H, 7070),
        "אסימון בנתיב מוסתר")
    n2 = redirect_note(f"https://cdn2.acme-iptv.tv:7070/x", H, 7070)
    chk("תת-שם אחר באותו דומיין" in n2, f"תת-שם ⇒ {n2[:40]}")
    n3 = redirect_note(f"https://{H}:8443/p/g/s/103/i.m3u8", H, 7070)
    chk("אותו מארח" in n3 and "8443" in n3, f"אותו מארח, פורט אחר ⇒ {n3[:40]}")
    chk("(אותו)" in redirect_note(f"https://{H}:7070/x", H, 7070),
        "אותו פורט מסומן ככזה")
    chk("יחסית" in redirect_note("/somewhere/else.m3u8", H, 7070),
        "הפניה יחסית אינה מקריסה")

    # ⑤ מיסוך
    m = mask("https://tv.acme-iptv.tv:86/p/acme/s/1/i.m3u8?token=AB12CD34EF",
             "tv.acme-iptv.tv")
    chk("acme" not in m and "AB12CD34EF" not in m, "מארח ואסימון אינם בפלט")
    chk("direct" in mask("direct", "tv.acme-iptv.tv"),
        "הודעת הספק נשארת קריאה")

    print("\n" + ("✓ הכל עבר" if not bad else f"✗ {bad} נכשלו"))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", type=int, default=0)
    ap.add_argument("--phase", default="abcd",
                    help="אילו שלבים להריץ, למשל 'a' או 'ac'")
    ap.add_argument("--gap", type=float, default=0.35)
    ap.add_argument("--timeout", type=float, default=8.0)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    try:
        data = json.loads(CONTENT.read_text(encoding="utf-8"))
    except Exception as e:                                    # noqa: BLE001
        sys.exit(f"לא ניתן לקרוא את {CONTENT}: {e}")
    items = data if isinstance(data, list) else data.get("movies", [])

    try:
        org = json.loads((DATA / "relay_hosts.json").read_text("utf-8"))
    except Exception:
        org = {}

    byhost = defaultdict(list)
    for m in items:
        g = RELAY.search((m.get("video_url") or "").strip())
        if g:
            byhost[g.group(1)].append(g.group(2))
    order = sorted(byhost.items(), key=lambda kv: -len(kv[1]))

    found = []
    for idx, (netloc, paths) in enumerate(order, 1):
        if a.host and idx != a.host:
            continue
        host = netloc.split(":")[0]
        o = org.get(host) or {}
        scheme = o.get("scheme") or "http"
        port = int(netloc.split(":")[1]) if ":" in netloc else \
            int(o.get("port") or (443 if scheme == "https" else 80))
        path = paths[0]
        ident = ident_of(path)

        code, body, _ct = ask(scheme, host, port, "/" + path, a.timeout)
        print(f"\n{'=' * 64}\nספק {idx}  ({len(paths)} ערוצים)  "
              f"{mask(host, host)} · {scheme}:{port}")
        if is_pl(body):
            print("  ✓ עובד — אין מה לחפש כאן.")
            continue
        print(f"  הנתיב הידוע: {short(code, body)}")
        print(f"  המזהה בנתיב: {ident or '(אין מספרי)'}")

        # ── שלב א: 403 לעומת 404 ────────────────────────────────────────
        if "a" in a.phase:
            print(f"\n  ── שלב א · האם הנתיב הישן בכלל קיים " + "─" * 22)
            bogus = f"zovex-{secrets.token_hex(6)}/does-not-exist.m3u8"
            bc, bb, _ = ask(scheme, host, port, "/" + bogus, a.timeout)
            print(f"    נתיב ידוע:  {short(code, body)}")
            print(f"    נתיב מומצא: {short(bc, bb)}")
            same = (code == bc and " ".join(body.split())[:60]
                    == " ".join(bb.split())[:60])
            if same:
                print("\n    ⇒ **אותה תשובה בדיוק.** כלומר 'direct' היא תשובה")
                print("      גורפת ואינה אומרת דבר על קיום הנתיב. אי אפשר")
                print("      להסיק מכאן שהמספור השתנה — ולכן שלבים ב-ד הם")
                print("      החיפוש הנכון, וסריקת מספרים אינה.")
            else:
                print("\n    ⇒ **תשובות שונות.** הנתיב הישן מקבל יחס אחר")
                print("      מנתיב שאינו קיים — כלומר הוא **קיים**, והוא רק")
                print("      מסורב. המספור לא השתנה, וכל סריקה היא בזבוז.")
                print("      מה שחסר הוא הרשאה, לא כתובת.")
                found.append((idx, "exists-refused"))
            time.sleep(a.gap)

        # ── שלב ב: איזה שער ─────────────────────────────────────────────
        if "b" in a.phase:
            print(f"\n  ── שלב ב · איזה שער עומד שם " + "─" * 29)
            seen = OrderedDict()
            for d in DISCOVER:
                c, b, ct = ask(scheme, host, port, d, a.timeout)
                tag = short(c, b)
                mark = " ←" if c not in ("404", "403") and not c[0].isalpha() \
                    else ""
                print(f"    {d:<34} {tag}{mark}")
                # כל Location, בכל קוד. בגרסה הראשונה זה הודפס רק על 200,
                # ולכן 301 על פורט 80 הודפס בלי לומר **לאן** — והכתובת
                # שאליה מפנים היא בדיוק מה שהכלי נועד למצוא.
                if loc_of(ct):
                    print(f"        ↳ {redirect_note(loc_of(ct), host, port)}")
                elif ct and c == "200":
                    print(f"        {mask(ct, host)[:70]}")
                seen[d] = c
                time.sleep(a.gap)
            live = [d for d, c in seen.items()
                    if c not in ("404", "403") and c[:1].isdigit()]
            if live:
                print(f"\n    ⇒ {len(live)} נתיבי גילוי עונים אחרת מ-403/404.")
                print("      אלה המקומות שבהם השער מזדהה, והם הדרך הנכונה")
                print("      להבין מה צורת הקישור החדשה.")
                found.append((idx, "discover"))

        # ── שלב ג: אותו מזהה, עטיפה אחרת ───────────────────────────────
        if "c" in a.phase and ident:
            vs = path_variants(path, ident)
            print(f"\n  ── שלב ג · אותו מזהה, {len(vs)} עטיפות " + "─" * 18)
            hit = []
            for why, p in vs:
                c, b, _ = ask(scheme, host, port, "/" + p, a.timeout)
                ok = is_pl(b)
                if ok or c not in ("403", "404"):
                    print(f"    {'✓' if ok else '·'} {why:<16} "
                          f"{mask('/' + p, host)[:40]:<40} {short(c, b)}")
                if ok:
                    hit.append(p)
                time.sleep(a.gap)
            if hit:
                print(f"\n    ⇒ **{len(hit)} עטיפות מגישות playlist.**")
                for p in hit[:5]:
                    print(f"      {mask('/' + p, host)}")
                found.append((idx, "wrap"))
            else:
                print("    — אף עטיפה לא הגישה playlist.")

        # ── שלב ד: פורטים ──────────────────────────────────────────────
        if "d" in a.phase:
            print(f"\n  ── שלב ד · {len(PORTS)} פורטים " + "─" * 28)
            opens = []
            for p in PORTS:
                if p == port:
                    continue
                for sch in (("https", "http") if p in (443, 8443) else
                            ("http", "https")):
                    c, b, ct = ask(sch, host, p, "/" + path, a.timeout)
                    if c[:1].isdigit():
                        ok = is_pl(b)
                        print(f"    {'✓' if ok else '·'} {sch}:{p:<6} "
                              f"{short(c, b)}")
                        # ← זה מה שהוחמץ: 301 בלי Location אינו אומר כלום,
                        #   ו-Location **הוא** הכתובת החדשה אם יש כזאת.
                        if loc_of(ct):
                            print(f"        ↳ "
                                  f"{redirect_note(loc_of(ct), host, p)}")
                            found.append((idx, "redirect"))
                        opens.append((p, sch, c, ok))
                        if ok:
                            found.append((idx, "port"))
                        break
                time.sleep(a.gap)
            good = [x for x in opens if x[3]]
            if good:
                print(f"\n    ⇒ **פורט אחר מגיש playlist**: "
                      f"{', '.join(f'{s}:{p}' for p, s, _c, _o in good)}")
            elif opens:
                print(f"\n    — {len(opens)} פורטים פתוחים, אף אחד לא מגיש.")
            else:
                print("    — אין פורט פתוח נוסף.")

    print(f"\n{'=' * 64}")
    kinds = {k for _i, k in found}
    if "redirect" in kinds and not ({"wrap", "port"} & kinds):
        print("יש הפניה (301/302) עם כתובת יעד — השורה עם ה-← למעלה.")
        print("אם היא מצביעה למארח או לפורט אחר, זו הכתובת החדשה,")
        print("וצריך לבדוק אותה. שלח לי אותה כמו שהיא.")
        print()
    if "wrap" in kinds or "port" in kinds:
        print("יש צורה שעובדת. זה בדיוק מה שחיפשנו — שלח לי את השורות")
        print("עם ה-✓ ואני מעדכן את הקישורים בקטלוג.")
    elif "discover" in kinds:
        print("השער מזדהה בנתיבי הגילוי. שלח לי את שלב ב כפי שהוא —")
        print("משם אפשר להבין את צורת הקישור בלי לנחש.")
    elif "exists-refused" in kinds:
        print("הנתיבים הישנים **קיימים** ורק מסורבים. כלומר אין כתובת")
        print("חדשה למצוא, ואין סריקה שתעזור — מה שחסר הוא הרשאה.")
        print("זו גם התשובה לשאלה 'אולי נסרוק יותר טוב': לא, אין מה")
        print("לסרוק. צריך הרשאה, ואותה רק הוא יכול לתת.")
    else:
        print("אף שלב לא מצא צורה עובדת, והשער אינו מזדהה באף נתיב.")
        print("זה עצמו מידע: אין כאן כתובת חלופית שאפשר לגלות מבחוץ.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
