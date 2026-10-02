#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""import_m3u — קובץ רשימה מהספק, אל הקטלוג.

## למה זה הכלי שמחזיר את 44 הערוצים

‎find_gateway‎ הוכיח שכל בקשה מתחת ל-‎/p/‎ מקבלת ‎403 direct‎ **בלי
תלות במזהה, בשם השער או בשם הקובץ**. כלומר אין אות הצלחה, ולכן אין
סריקה שתמצא דבר — גם אם ננחש את הקישור החדש הנכון, נקבל 403 ולא נדע
שפגענו.

מה שכן פותר את זה הוא קובץ ‎m3u‎ מהספק: הוא מכיל את הקישורים החדשים
**עם** מה שמאשר אותם, ואת השמות. בקשה אחת ממנו בוואטסאפ, והיא עונה על
כל 44 הערוצים בבת אחת.

## מה הוא עושה

1. קורא את הקובץ (או כתובת) ומפרק ל-(שם, קישור).
2. אומר אילו מארחים צריכים רישום ברלֵיי — בלעדיו הערוץ לא יוגש.
3. **מאמת בפועל** שהקישורים מגישים playlist, ולא רק שהם כתובים.
4. משווה לקטלוג לפי שם, ומפריד:
   · ‎תוקן‎  — הערוץ קיים אצלנו והקישור בקובץ **שונה**. זה התיקון.
   · ‎זהה‎   — הקישור כבר נכון, אין מה לעשות.
   · ‎חדש‎   — בקובץ ולא אצלנו.
   · ‎חסר‎   — אצלנו ולא בקובץ. הספק הפסיק לשדר אותו.
5. ‎--apply‎ מעדכן, דרך הפאנל ועם ‎base_version‎ — כלומר אם מישהו
   עורך במקביל, השמירה נדחית ולא נדרסת עבודה.

## הכלל שמונע החלפת תוכן

"ספורט 5" ו"ספורט 6" דומים ב-0.9 ואינם אותו ערוץ. לכן אם בשני השמות
יש ספרות, הן חייבות להיות **זהות**. ערוץ שבור גרוע; ערוץ שמשדר משהו
אחר בלי שהצופה יודע — גרוע בהרבה.

## חשוב

**אל תדביק את תוכן הקובץ בצ'אט.** הוא מכיל את פרטי הגישה שלך. שמור
אותו על השרת והפנה אליו — הכלי קורא אותו שם, והפלט שלו ממוסך.

    python3 import_m3u.py --file /root/list.m3u            # דוח בלבד
    python3 import_m3u.py --file /root/list.m3u --probe-all
    python3 import_m3u.py --file /root/list.m3u --apply
    python3 import_m3u.py --file /root/list.m3u --apply --add-new
    python3 import_m3u.py --selftest
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
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from urllib.parse import urlparse

DATA = pathlib.Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
ENV = pathlib.Path("/opt/zovex-bot/.env")
LOCAL = "http://127.0.0.1:8000"
CURL = ["curl", "-sS", "--noproxy", "127.0.0.1"]
LIVE_CATEGORY = "שידורים חיים"
BASE_TOKEN = "%BASE%"
RELAY = re.compile(r"/hls-relay/(?:_fix/)?([^/?]+)/([^?]+)")
UA = "VLC/3.0.20 LibVLC/3.0.20"

_NOISE = {"hd", "fhd", "uhd", "sd", "4k", "1080", "720", "ערוץ", "channel",
          "tv", "live", "il", "israel", "ישראל", "חי"}
_GENERIC = {"com", "net", "org", "www", "live", "stream", "iptv", "tv",
            "index", "playlist", "chunks", "m3u8", "http", "https", "pw"}


# ── מיסוך ────────────────────────────────────────────────────────────────

def labels(host: str) -> set:
    return {w for w in re.split(r"[.\-_:]+", host.lower())
            if len(w) >= 3 and not w.isdigit() and w not in _GENERIC}


def mask_url(u: str) -> str:
    """כתובת להדפסה: מארח, שם ספק בנתיב ואסימונים מוסרים."""
    p = urlparse(u if "://" in u else "http://" + u)
    host = p.hostname or ""
    path = (p.path or "") + (f"?{p.query}" if p.query else "")
    for w in sorted(labels(host), key=len, reverse=True):
        path = re.sub(re.escape(w), "<שם>", path, flags=re.I)
    path = re.sub(r"((?:token|auth|key|sig|secret|pass(?:word)?|"
                  r"user(?:name)?)=)([^&]+)", r"\1<סוד>", path, flags=re.I)
    path = re.sub(r"\b(?=[A-Za-z0-9]{10,}\b)(?=[A-Za-z0-9]*\d)"
                  r"[A-Za-z0-9]+\b", "<אסימון>", path)
    port = f":{p.port}" if p.port else ""
    return f"<ספק{port}>{path[:54]}"


# ── התאמת שמות ───────────────────────────────────────────────────────────

def norm(s: str) -> str:
    s = (s or "").lower().replace("־", " ").replace("-", " ")
    s = re.sub(r"[\"'`׳״()\[\]|/]", " ", s)
    return " ".join(t for t in re.split(r"\s+", s)
                    if t and t not in _NOISE).strip()


def digits(s: str) -> list:
    return re.findall(r"\d+", norm(s))


def same_channel(a: str, b: str, min_ratio: float) -> float:
    """0 = לא אותו ערוץ. הכלל הקשה: ספרות שונות ⇒ 0."""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    da, db = digits(a), digits(b)
    if bool(da) != bool(db) or (da and db and da != db):
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    if ta and (ta <= tb or tb <= ta):
        return 0.95
    r = difflib.SequenceMatcher(None, na, nb).ratio()
    return r if r >= min_ratio else 0.0


# ── פירוק m3u ────────────────────────────────────────────────────────────

def parse_m3u(text: str):
    """[(שם, קישור, לוגו, קבוצה)] — מדלג על שורות בלי זוג שלם."""
    out = []
    name = logo = group = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("#EXTINF"):
            name = line.split(",", 1)[1].strip() if "," in line else None
            g = re.search(r'tvg-logo="([^"]*)"', line, re.I)
            logo = g.group(1) if g else None
            g = re.search(r'group-title="([^"]*)"', line, re.I)
            group = g.group(1) if g else None
        elif line.upper().startswith("#EXTGRP"):
            group = line.split(":", 1)[1].strip() if ":" in line else group
        elif line.startswith("#"):
            continue
        elif name:
            out.append((name, line, logo, group))
            name = logo = group = None
    return out


def relay_url(u: str) -> str:
    """קישור ישיר ⇒ הצורה שהקטלוג שומר, דרך הרלֵיי שלנו."""
    p = urlparse(u)
    host = (p.hostname or "").lower()
    if not host:
        return ""
    scheme = p.scheme if p.scheme in ("http", "https") else "http"
    port = p.port or (443 if scheme == "https" else 80)
    default = (scheme == "https" and port == 443) or \
              (scheme == "http" and port == 80)
    netloc = host if default else f"{host}:{port}"
    path = (p.path or "/").lstrip("/")
    q = f"?{p.query}" if p.query else ""
    return f"{BASE_TOKEN}/hls-relay/{netloc}/{path}{q}"


def origin_of(u: str):
    p = urlparse(u)
    host = (p.hostname or "").lower()
    scheme = p.scheme if p.scheme in ("http", "https") else "http"
    return host, scheme, (p.port or (443 if scheme == "https" else 80))


# ── רשת ──────────────────────────────────────────────────────────────────

def serves(u: str, timeout=10.0):
    """(תיאור, מגיש?) — בקשה ישירה אל הספק."""
    host, scheme, port = origin_of(u)
    p = urlparse(u)
    path = (p.path or "/") + (f"?{p.query}" if p.query else "")
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
        body = r.read(4096).decode("utf-8", "replace")
        conn.close()
        if r.status != 200:
            note = " ".join(body.split())[:30]
            return f"{r.status}" + (f" · {note}" if note else ""), False
        if "#EXTM3U" not in body and "#EXT-X-" not in body:
            return "200 אבל אינו playlist", False
        segs = len([x for x in body.splitlines()
                    if x.strip() and not x.startswith("#")])
        # ספק שנפל מחזיר 200 עם כותרת תקינה ואפס מקטעים — נתפס בשטח
        return (f"200 ✓ {segs} מקטעים" if segs else "200 אבל ריק"), bool(segs)
    except Exception as e:                                    # noqa: BLE001
        return type(e).__name__, False
    finally:
        try:
            if sock:
                sock.close()
        except Exception:                                     # noqa: BLE001
            pass


def panel_password() -> str:
    p = os.environ.get("PANEL_PASSWORD", "").strip()
    if p:
        return p
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8",
                                  errors="replace").splitlines():
            if line.strip().startswith("PANEL_PASSWORD="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def get_content():
    hdr = pathlib.Path("/tmp/_im_hdr")
    r = subprocess.run(CURL + ["-D", str(hdr), "--max-time", "180",
                               f"{LOCAL}/content"], capture_output=True)
    ver = None
    try:
        for line in hdr.read_text(encoding="latin1",
                                  errors="replace").splitlines():
            if line.lower().startswith("x-content-version:"):
                ver = int(line.split(":", 1)[1].strip())
    except Exception:
        pass
    try:
        return json.loads(r.stdout), ver
    except json.JSONDecodeError as e:
        sys.exit(f"❌ לא ניתן לקרוא את הקטלוג: {e}")


def relay_hosts() -> dict:
    try:
        return json.loads((DATA / "relay_hosts.json").read_text("utf-8"))
    except Exception:
        return {}


def register_host(host: str, scheme: str, port: int, pwd: str) -> bool:
    body = json.dumps({"password": pwd, "action": "add", "host": host,
                       "scheme": scheme, "port": port})
    tmp = pathlib.Path("/tmp/_im_host.json")
    tmp.write_text(body, encoding="utf-8")
    r = subprocess.run(CURL + ["-X", "POST", "-H", "Content-Type: application/json",
                               "--data-binary", f"@{tmp}",
                               f"{LOCAL}/api/relay/hosts"],
                       capture_output=True)
    ok = b'"hosts"' in r.stdout
    if not ok:
        print(f"      ✗ רישום נכשל: "
              f"{r.stdout.decode('utf-8', 'replace')[:120]}")
    return ok


# ── בדיקה עצמית ─────────────────────────────────────────────────────────

def selftest() -> int:
    bad = 0

    def chk(ok, what):
        nonlocal bad
        if not ok:
            bad += 1
        print(f"{'✓' if ok else '✗'} {what}")

    # ① פירוק m3u
    txt = ('#EXTM3U\n'
           '#EXTINF:-1 tvg-logo="http://x/l.png" group-title="ספורט",ספורט 6\n'
           'http://h.tv:7070/p/g/s/103/playlist.m3u8\n'
           '#EXTINF:-1,ילדים\n'
           'https://h.tv/p/g/s/77/playlist.m3u8\n'
           '#EXTINF:-1,שבור בלי כתובת\n'
           '#EXTM3U-garbage\n')
    rows = parse_m3u(txt)
    chk(len(rows) == 2, f"שני זוגות שלמים ⇒ {len(rows)}")
    chk(rows[0][0] == "ספורט 6", "שם")
    chk(rows[0][3] == "ספורט", "קבוצה")
    chk(rows[0][2] == "http://x/l.png", "לוגו")
    chk(rows[1][0] == "ילדים", "זוג שני")
    chk(parse_m3u("") == [], "קובץ ריק")
    chk(parse_m3u("#EXTINF:-1,א\n") == [], "שם בלי כתובת מדולג")

    # ② בניית כתובת הרלֵיי — פורט מופיע רק כשאינו ברירת מחדל
    chk(relay_url("http://h.tv:7070/p/g/s/103/playlist.m3u8")
        == "%BASE%/hls-relay/h.tv:7070/p/g/s/103/playlist.m3u8", "פורט מפורש")
    chk(relay_url("https://h.tv/a/b.m3u8")
        == "%BASE%/hls-relay/h.tv/a/b.m3u8", "‏443 אינו מודפס")
    chk(relay_url("http://h.tv:80/a.m3u8")
        == "%BASE%/hls-relay/h.tv/a.m3u8", "‏80 אינו מודפס")
    chk(relay_url("http://h.tv/a.m3u8?t=1")
        == "%BASE%/hls-relay/h.tv/a.m3u8?t=1", "שאילתה נשמרת")
    chk(relay_url("לא-כתובת") == "", "קלט פגום")
    chk(origin_of("https://h.tv:7070/x") == ("h.tv", "https", 7070), "מקור")
    chk(origin_of("http://h.tv/x") == ("h.tv", "http", 80), "פורט ברירת מחדל")

    # ③ הכלל הקשה
    chk(same_channel("ספורט 5", "ספורט 6", 0.8) == 0.0, "‏5 ≠ 6")
    chk(same_channel("ספורט", "ספורט 6", 0.8) == 0.0, "מספר באחד בלבד")
    chk(same_channel("ערוץ 13", "ערוץ 13 HD", 0.8) == 1.0,
        "אותו מספר, רעש שונה ⇒ התאמה מלאה")
    chk(same_channel("ספורט 6", "ספורט 6 פלוס", 0.8) >= 0.9, "תת-קבוצה")

    # ④ מיסוך — כולל שם ספק בתוך הנתיב ואסימון בשאילתה
    m = mask_url("https://tv.acme-iptv.tv:7070/p/acme-iptv/s/103/"
                 "playlist.m3u8?token=AB12CD34EF")
    chk("acme" not in m, f"שם הספק אינו בפלט ⇒ {m[:44]}")
    chk("AB12CD34EF" not in m, "אסימון אינו בפלט")
    chk("103" in m, "המזהה נשאר קריא")
    chk("7070" in m, "והפורט")

    print("\n" + ("✓ הכל עבר" if not bad else f"✗ {bad} נכשלו"))
    return 1 if bad else 0


# ── ראשי ────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="")
    ap.add_argument("--url", default="")
    ap.add_argument("--min", type=float, default=0.82)
    ap.add_argument("--probe", type=int, default=6,
                    help="כמה קישורים לאמת (0 = ללא)")
    ap.add_argument("--probe-all", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--add-new", action="store_true")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--gap", type=float, default=0.25)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.file and not a.url:
        sys.exit("צריך --file <נתיב> או --url <כתובת רשימה>")

    if a.file:
        try:
            text = pathlib.Path(a.file).read_text(encoding="utf-8",
                                                  errors="replace")
        except Exception as e:                                # noqa: BLE001
            sys.exit(f"❌ {a.file}: {e}")
    else:
        r = subprocess.run(["curl", "-fsSL", "--max-time", "120", a.url],
                           capture_output=True)
        text = r.stdout.decode("utf-8", "replace")
        if not text.strip():
            sys.exit("❌ הכתובת לא החזירה כלום")

    rows = parse_m3u(text)
    if not rows:
        sys.exit("❌ לא נמצא אף ערוץ בקובץ. זהו קובץ m3u תקין?")
    print(f"בקובץ: {len(rows)} ערוצים\n")

    # ── מארחים ───────────────────────────────────────────────────────
    hosts = defaultdict(int)
    info = {}
    for _n, u, _l, _g in rows:
        h, sch, pt = origin_of(u)
        if h:
            hosts[(h, sch, pt)] += 1
            info[h] = (sch, pt)
    known = relay_hosts()
    print("מארחים בקובץ:")
    need = []
    for (h, sch, pt), c in sorted(hosts.items(), key=lambda kv: -kv[1]):
        reg = h in known
        print(f"  <ספק:{pt}>  {c:>4} ערוצים   "
              f"{'✓ רשום ברלֵיי' if reg else '⚠ אינו רשום'}")
        if not reg:
            need.append((h, sch, pt))
    if need:
        print("\n  ⚠ מארח שאינו רשום — הרלֵיי יסרב להגיש ממנו.")
        print("    ‎--apply‎ ירשום אותו (דרך הפאנל, כמו בממשק).")

    # ── אימות ────────────────────────────────────────────────────────
    sample = rows if a.probe_all else rows[:max(0, a.probe)]
    live_ok = 0
    if sample:
        print(f"\nמאמת {len(sample)} קישורים מול הספק:\n")
        for n, u, _l, _g in sample:
            what, ok = serves(u, a.timeout)
            live_ok += ok
            print(f"  {'✓' if ok else '✗'} {n[:30]:<30} {what}")
            time.sleep(a.gap)
        if not live_ok:
            print("\n  ✗ אף קישור לא הגיש playlist.")
            print("    הקובץ אינו עובד מהשרת הזה — אין טעם להחיל אותו.")
            print("    אם הוא כן עובד מהטלפון שלך, זה אומר שההרשאה")
            print("    קשורה ל-IP, ואז צריך לבקש ממנו לאשר את ה-IP.")
            if a.apply:
                return 1
        else:
            print(f"\n  ✓ {live_ok}/{len(sample)} מגישים.")

    # ── השוואה לקטלוג ────────────────────────────────────────────────
    movies, ver = get_content()
    live = [m for m in movies if m.get("category") == LIVE_CATEGORY
            or m.get("is_live")]
    print(f"\nבקטלוג: {len(movies)} פריטים · {len(live)} ערוצים חיים · "
          f"גרסה {ver}\n" + "=" * 62)

    def title_of(e):
        for k in ("title", "name"):
            v = e.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    fix, same, new = [], [], []
    used = set()
    for n, u, logo, _g in rows:
        want = relay_url(u)
        if not want:
            continue
        best, score = None, 0.0
        for m in live:
            if id(m) in used:
                continue
            s = same_channel(n, title_of(m), a.min)
            if s > score:
                best, score = m, s
        if not best:
            new.append((n, u, logo))
        else:
            used.add(id(best))
            cur = (best.get("video_url") or "").strip()
            (same if cur == want else fix).append((best, n, u, want, cur))

    missing = [m for m in live if id(m) not in used]

    if fix:
        print(f"\n① תוקן — {len(fix)} ערוצים שהקישור שלהם משתנה:\n")
        for m, n, _u, want, _cur in fix[:40]:
            print(f"   {title_of(m)[:26]:<26} → {mask_url(want)}")
        if len(fix) > 40:
            print(f"   ... ועוד {len(fix) - 40}")
    if same:
        print(f"\n② זהה — {len(same)} ערוצים שהקישור שלהם כבר נכון.")
    if new:
        print(f"\n③ חדש — {len(new)} ערוצים שאינם אצלנו:\n")
        for n, _u, _l in new[:25]:
            print(f"   {n}")
        if len(new) > 25:
            print(f"   ... ועוד {len(new) - 25}")
        print("\n   ‎--add-new‎ יוסיף אותם.")
    if missing:
        print(f"\n④ חסר — {len(missing)} ערוצים אצלנו שאינם בקובץ:\n")
        for m in missing[:25]:
            print(f"   {title_of(m)}")
        if len(missing) > 25:
            print(f"   ... ועוד {len(missing) - 25}")
        print("\n   הספק אינו משדר אותם יותר. הם יישארו מוסתרים.")

    print("\n" + "=" * 62)
    print(f"סיכום: {len(fix)} לתיקון · {len(same)} זהים · {len(new)} חדשים "
          f"· {len(missing)} חסרים")

    if not a.apply:
        print("\nזהו דוח בלבד. להחיל:")
        print(f"  python3 import_m3u.py --file {a.file or a.url} --apply"
              + ("" if not new else " --add-new"))
        return 0
    if not fix and not (a.add_new and new):
        print("\nאין מה להחיל.")
        return 0

    pwd = panel_password()
    if not pwd:
        sys.exit("❌ לא נמצאה PANEL_PASSWORD")

    for h, sch, pt in need:
        print(f"\nרושם מארח <ספק:{pt}> ברלֵיי...")
        if not register_host(h, sch, pt, pwd):
            sys.exit("❌ רישום המארח נכשל — לא משנה את הקטלוג.")
        print("   ✓ נרשם")

    n_fix = 0
    for m, _n, _u, want, _cur in fix:
        m["video_url"] = want
        m["video_id"] = None
        n_fix += 1

    added = []
    if a.add_new:
        for n, u, logo in new:
            added.append({
                "title": n, "video_url": relay_url(u), "video_id": None,
                "thumbnail_url": logo or "", "custom_slug": "",
                "category": LIVE_CATEGORY, "type": None, "series_name": None,
                "season_number": None, "episode_number": None,
                "episode_title": None, "year": None, "description": "",
                "id": str(uuid.uuid4()),
                "created_date": time.strftime("%Y-%m-%dT%H:%M:%S.000Z",
                                              time.gmtime()),
                "is_live": True})

    body = json.dumps({"password": pwd, "movies": movies + added,
                       "base_version": ver}, ensure_ascii=False)
    tmp = pathlib.Path("/tmp/_im_body.json")
    tmp.write_text(body, encoding="utf-8")
    r = subprocess.run(CURL + ["-X", "POST", "-H",
                               "Content-Type: application/json",
                               "--data-binary", f"@{tmp}", "--max-time", "300",
                               f"{LOCAL}/content/save"], capture_output=True)
    out = r.stdout.decode("utf-8", "replace")
    tmp.unlink(missing_ok=True)
    if '"ok"' in out or '"saved"' in out or '"version"' in out:
        print(f"\n✓ {n_fix} קישורים תוקנו"
              + (f" · {len(added)} ערוצים נוספו" if added else ""))
        print("✓ הלקוחות ירעננו מעצמם תוך דקות")
        print("\nלבדיקה:  python3 check_channel.py --all")
    else:
        print(f"\n❌ השמירה נדחתה: {out[:200]}")
        print("   אם זה base_version — מישהו ערך במקביל. הרץ שוב.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
