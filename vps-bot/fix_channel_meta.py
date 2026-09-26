#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_channel_meta.py — לוגו ו-slug לערוצים החדשים, וחיפוש מזהי EPG.

שני חלקים נפרדים:

--thumbs   קובע thumbnail_url ו-custom_slug לערוצי ספורט 5 שהוספנו.
           ה-slug אינו קוסמטי: לוח השידורים נשלף לפי /epg/<slug>.json,
           ובלעדיו לערוץ אין לוח גם אם המזהה קיים אצל וואלה.
           הלוגואים נלקחים מאותו מאגר ציבורי שהקטלוג כבר משתמש בו
           (tv-logo/tv-logos) ומאומתים ב-HTTP לפני הכתיבה.

--scan-all שואל את כל ארבעת המקורות של epg_build.py אילו ערוצים קיימים,
           ומדפיס שורה מוכנה ל-MAP לכל שם שמתאים ל---pattern. אפשר גם כל
           מקור לחוד: --epg-scan (וואלה), --free-scan, --yes-scan, --hot-scan.

           מי נגיש מאיפה — זה לא אותו דבר לכל המקורות:
             וואלה  · פתוח מכל מקום. הפרמטר provider הוא מספר (3=yes, 2=hot);
                      שליחת "yes"/"hot" מחזירה 400 — זו הייתה טעות שלי ולא
                      חסימה גיאוגרפית.
             FreeTV · פתוח מכל מקום, בלי הרשמה.
             HOT    · מחזיר 302 בלופ לכל מי שאינו דפדפן אמיתי. חייב לרוץ
                      מהשרת.
             yes    · אינו בקשת רשת בכלל אלא תצלום שנאסף מהדפדפן ויושב ב-
                      data/yes-epg.json, כי Akamai חוסמת שם. חייב את השרת.

           לכן כדי לכסות את כל הארבעה — להריץ מהשרת.

    python3 fix_channel_meta.py --scan-all --pattern 'hbo|סלקום|ufc|לחימה'
    python3 fix_channel_meta.py --epg-scan
    python3 fix_channel_meta.py --thumbs --check
    python3 fix_channel_meta.py --thumbs
    python3 fix_channel_meta.py --thumbs --revert
"""
import argparse, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

DATA = Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
VERSION = DATA / "content_version.txt"
BACKUP = CONTENT.with_name("content.json.bak_meta")
LOGOS = "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel"

# (שם בקטלוג, slug, כתובת לוגו)
# ה-slug נבחר בהתאמה לדפוס הקיים: sport5 / 5gold / 5STARS.
META = [
    ("ספורט 5 פלוס", "5plus", f"{LOGOS}/5plus-il.png"),
    # אין לוגו נפרד ל-Max במאגר. עד שיהיה — אותו לוגו של ספורט 5,
    # שכבר מוגש אצלך ועובד. עדיף מרובע ריק, ואפשר להחליף בפאנל.
    ("ספורט 5 מקס", "5max", "/zovex/live-logos/sport5.png?v=2"),
]

# provider הוא מספר ולא מילה: 3=yes, 2=hot. שליחת "yes"/"hot" מחזירה 400,
# וזו הייתה הטעות בגרסה הראשונה — לא חסימה גיאוגרפית כפי שהנחתי.
# מועתק מ-fetch_walla ב-epg_build.py, שעובד בפועל.
WALLA = "https://dal.walla.co.il/tv/list?provider={p}"
PROVIDERS = {3: "yes", 2: "hot"}
UA_STR = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def http_ok(url: str) -> bool:
    if url.startswith("/"):
        return True            # נתיב מקומי באתר — נבדק ע"י הדפדפן
    r = subprocess.run(["curl", "-sS", "-m", "15", "-o", "/dev/null",
                        "-w", "%{http_code}", url], capture_output=True, text=True)
    return (r.stdout or "").strip() == "200"


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True); raise


def epg_scan(pattern: str) -> None:
    """מדפיס channel_code לכל ערוץ ששמו מתאים, להשלמה ל-MAP."""
    import urllib.request
    rx = re.compile(pattern, re.I)
    found = []
    for code, label in PROVIDERS.items():
        try:
            req = urllib.request.Request(
                WALLA.format(p=code),
                headers={"User-Agent": UA_STR,
                         "Referer": "https://tv-guide.walla.co.il/"})
            with urllib.request.urlopen(req, timeout=40) as r:
                data = json.loads(r.read()).get("data", [])
        except Exception as e:
            print(f"  {label} (provider={code}): נכשל — {type(e).__name__}: {e}")
            continue
        print(f"  {label} (provider={code}): {len(data)} ערוצים")
        for ch in data:
            if not isinstance(ch, dict):
                continue
            cc = ch.get("channel_code")
            nm = (ch.get("channel_name") or ch.get("name")
                  or ch.get("title") or "").strip()
            if cc is None or not nm:
                continue
            if rx.search(nm):
                n = len(ch.get("schedule") or [])
                found.append((nm, cc, label, n))

    if not found:
        print("\nאין התאמה. הרחב עם --pattern, למשל --pattern '5|ספורט'")
        return
    print(f"\n{len(found)} התאמות — להוסיף ל-MAP ב-epg_build.py:\n")
    seen = set()
    for nm, cc, prov, n in sorted(found, key=lambda x: x[0]):
        if (nm, cc) in seen:
            continue
        seen.add((nm, cc))
        note = f"# {nm}  [{prov}, {n} תוכניות]"
        print(f'    "<slug>": ("w", {cc}),'.ljust(32) + note)
    print("\nהחלף <slug> ב-custom_slug של הערוץ אצלנו (למשל 5plus, 5max).")


def hot_scan(pattern: str) -> None:
    """מדפיס channelID לכל ערוץ של HOT ששמו מתאים. HOT מפנה בלופ
    מחוץ לישראל, ולכן זה חייב לרוץ מהשרת — בשונה מוואלה, שם ה-400
    היה פרמטר שגוי שלי ולא חסימה."""
    import urllib.request
    from datetime import datetime
    api = ("https://www.hot.net.il/HotCmsApiFront/api/"
           "ProgramsSchedual/GetProgramsSchedual")
    day = datetime.now().strftime("%Y/%m/%d")
    body = json.dumps({"ProgramsStartDateTime": f"{day} 00:00:00",
                       "ProgramsEndDateTime": f"{day} 23:59:59"}).encode()
    req = urllib.request.Request(
        api, data=body, method="POST",
        headers={"User-Agent": UA_STR, "Content-Type": "application/json",
                 "Referer": "https://www.hot.net.il/heb/tv/tvguide/"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            res = json.loads(r.read())
    except Exception as e:
        print(f"  HOT נכשל — {type(e).__name__}: {e}")
        return
    data = res.get("data") or {}
    progs = data.get("programsDetails") or []
    names = {}
    for p in progs:
        cid = p.get("channelID")
        nm = (p.get("channelName") or p.get("channel_name")
              or p.get("channelTitle") or "")
        if cid is not None and nm:
            names[str(cid)] = nm
    # לא בטוח ששם הערוץ יושב על התוכנית. אם לא — מחפשים רשימת ערוצים נפרדת
    # בתשובה, ואם גם היא אינה שם, מדפיסים את מבנה התשובה כדי שאפשר יהיה
    # לכתוב את הקוד הנכון בלי לנחש.
    if not names:
        for k, v in data.items():
            if not isinstance(v, list) or not v or not isinstance(v[0], dict):
                continue
            for row in v:
                cid = (row.get("channelID") or row.get("channelId")
                       or row.get("id"))
                nm = (row.get("channelName") or row.get("name")
                      or row.get("title") or "")
                if cid is not None and nm:
                    names[str(cid)] = nm
            if names:
                print(f"  (שמות הערוצים נלקחו מ-data['{k}'])")
                break
    print(f"  HOT: {len(progs)} תוכניות · {len(names)} ערוצים")
    if not names:
        print(f"  ⚠ לא נמצאו שמות ערוצים. מפתחות data: {list(data)}")
        if progs:
            print(f"     שדות בתוכנית: {list(progs[0])}")
        print("     שלח לי את שתי השורות האלה ואכתוב את הקוצר הנכון.")
        return
    rx = re.compile(pattern, re.I)
    hits = [(nm, cid) for cid, nm in names.items() if rx.search(nm)]
    if not hits:
        print(f"  אין התאמה מבין {len(names)} ערוצי HOT. הרחב עם --pattern")
        return
    print(f"\n  {len(hits)} התאמות — להוסיף ל-MAP ב-epg_build.py:\n")
    for nm, cid in sorted(hits):
        print(f'    "<slug>": ("h", "{cid}"),'.ljust(36) + f"# {nm}")


def yes_scan(pattern: str) -> None:
    """מחפש בתצלום של yes שיושב על השרת. אין כאן בקשת רשת — הקובץ נאסף
    מהדפדפן ע"י yes_harvest.js, כי Akamai חוסמת שם כל גישה שאינה דפדפן."""
    f = DATA / "yes-epg.json"
    if not f.exists():
        print(f"  yes: אין תצלום ב-{f} — הרץ את yes_harvest.js בדפדפן")
        return
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  yes: קריאת {f.name} נכשלה — {e}")
        return
    chans = raw.get("channels") or {}
    print(f"  yes: {len(chans)} ערוצים בתצלום")
    rx = re.compile(pattern, re.I)
    hits = [(str(ch.get("name") or ""), cid, len(ch.get("programs") or []))
            for cid, ch in chans.items() if rx.search(str(ch.get("name") or ""))]
    if not hits:
        print(f"  אין התאמה מבין {len(chans)} ערוצי yes. הרחב עם --pattern")
        return
    print(f"\n  {len(hits)} התאמות — להוסיף ל-MAP ב-epg_build.py:\n")
    for nm, cid, n in sorted(hits):
        print(f'    "<slug>": ("y", "{cid}"),'.ljust(36) + f"# {nm}  [{n} תוכניות]")


FTV_LIVES = "https://web.freetv.tv/api/products/lives?platform=BROWSER&maxResults=200"

def free_scan(pattern: str) -> None:
    """רשימת הערוצים של FreeTV. פתוחה, בלי הרשמה ובלי חסימה גיאוגרפית —
    זה המקור היחיד מהארבעה שאפשר לשאול גם מחוץ לישראל."""
    import urllib.request
    try:
        req = urllib.request.Request(FTV_LIVES, headers={"User-Agent": UA_STR})
        with urllib.request.urlopen(req, timeout=60) as r:
            items = json.loads(r.read()).get("items") or []
    except Exception as e:
        print(f"  FreeTV נכשל — {type(e).__name__}: {e}")
        return
    print(f"  FreeTV: {len(items)} ערוצים")
    rx = re.compile(pattern, re.I)
    hits = [((c.get("title") or "").strip(), c.get("id")) for c in items
            if rx.search((c.get("title") or ""))]
    if not hits:
        print(f"  אין התאמה מבין {len(items)} ערוצי FreeTV. הרחב עם --pattern")
        return
    print(f"\n  {len(hits)} התאמות — להוסיף ל-MAP ב-epg_build.py:\n")
    for nm, cid in sorted(hits):
        print(f'    "<slug>": ("f", {cid}),'.ljust(36) + f"# FreeTV {nm}")


def do_thumbs(check: bool) -> None:
    if not CONTENT.exists():
        sys.exit(f"לא נמצא: {CONTENT}")
    items = json.loads(CONTENT.read_text(encoding="utf-8"))
    by_title = {}
    for i in items:
        by_title.setdefault((i.get("title") or "").strip(), i)

    plan, missing = [], []
    for title, slug, logo in META:
        it = by_title.get(title)
        if it is None:
            missing.append(title)
            continue
        ok = http_ok(logo)
        cur_t = it.get("thumbnail_url") or ""
        cur_s = it.get("custom_slug") or ""
        if not ok:
            print(f"⚠ הלוגו של {title} לא נגיש ({logo}) — מדלג על התמונה")
        new = {}
        if ok and cur_t != logo:
            new["thumbnail_url"] = logo
        if cur_s != slug:
            new["custom_slug"] = slug
        if new:
            plan.append((it, title, new, cur_t, cur_s))

    print("=" * 62)
    for _, title, new, cur_t, cur_s in plan:
        print(f"\n  {title}")
        if "thumbnail_url" in new:
            print(f"     לוגו:  {cur_t or '(ריק)'}")
            print(f"        →   {new['thumbnail_url']}")
        if "custom_slug" in new:
            print(f"     slug:  {cur_s or '(ריק)'}  →  {new['custom_slug']}")
    if missing:
        print(f"\n⚠ לא בקטלוג: {', '.join(missing)}")
    print("\n" + "=" * 62)
    if not plan:
        print("אין מה לשנות.")
        return
    if check:
        print("--check: שום דבר לא נכתב.")
        return

    shutil.copy2(CONTENT, BACKUP)
    for it, _, new, _, _ in plan:
        it.update(new)
    atomic_write(CONTENT, json.dumps(items, ensure_ascii=False, indent=2))
    try:
        v = int(VERSION.read_text().strip()) + 1 if VERSION.exists() else 1
    except Exception:
        v = int(time.time())
    atomic_write(VERSION, str(v))
    print(f"✓ עודכנו {len(plan)} ערוצים · גיבוי: {BACKUP} · גרסה {v}")
    print("  הלוגו יופיע מיד. הלוח יופיע רק אחרי שה-slug ייכנס ל-MAP")
    print("  ב-epg_build.py וה-EPG ייבנה מחדש.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--thumbs", action="store_true")
    ap.add_argument("--epg-scan", action="store_true")
    ap.add_argument("--hot-scan", action="store_true",
                    help="רשימת הערוצים של HOT. חוסם מחוץ לישראל — להריץ מהשרת")
    ap.add_argument("--yes-scan", action="store_true",
                    help="התצלום של yes שיושב על השרת")
    ap.add_argument("--free-scan", action="store_true",
                    help="רשימת הערוצים של FreeTV. פתוחה מכל מקום")
    ap.add_argument("--scan-all", action="store_true",
                    help="כל ארבעת המקורות בזה אחר זה")
    ap.add_argument("--pattern", default=r"ספורט\s*5|sport\s*5|5\s*(plus|max|\+)")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    if a.revert:
        if not BACKUP.exists():
            sys.exit(f"אין גיבוי ב-{BACKUP}")
        shutil.copy2(BACKUP, CONTENT)
        print(f"✓ שוחזר מ-{BACKUP}")
        return
    scans = [(a.epg_scan or a.scan_all, "וואלה", epg_scan),
             (a.free_scan or a.scan_all, "FreeTV", free_scan),
             (a.yes_scan or a.scan_all, "yes", yes_scan),
             (a.hot_scan or a.scan_all, "HOT", hot_scan)]
    ran = False
    for on, label, fn in scans:
        if not on:
            continue
        ran = True
        print(f"\n{'─' * 62}\n{label}  ·  תבנית: {a.pattern}\n{'─' * 62}")
        try:
            fn(a.pattern)
        except Exception as e:
            print(f"  {label} נפל — {type(e).__name__}: {e}")
    if a.thumbs:
        if ran:
            print()
        do_thumbs(a.check)
        ran = True
    if not ran:
        ap.print_help()


if __name__ == "__main__":
    main()
