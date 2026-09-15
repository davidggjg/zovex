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

--epg-scan שואל את וואלה אילו ערוצים קיימים ומדפיס מזהה לכל שם שמתאים.
           הפרמטר provider הוא מספר (3=yes, 2=hot). שליחת "yes"/"hot"
           מחזירה 400 — זו הייתה הטעות שלי, לא חסימה גיאוגרפית.
           הפלט נועד להשלמה ל-MAP ב-epg_build.py.

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
    progs = (res.get("data") or {}).get("programsDetails") or []
    names = {}
    for p in progs:
        cid = p.get("channelID")
        nm = p.get("channelName") or p.get("channel_name") or ""
        if cid is not None and nm:
            names[str(cid)] = nm
    print(f"  HOT: {len(progs)} תוכניות · {len(names)} ערוצים")
    rx = re.compile(pattern, re.I)
    hits = [(nm, cid) for cid, nm in names.items() if rx.search(nm)]
    if not hits:
        print("\nאין התאמה. הרחב עם --pattern")
        return
    print(f"\n{len(hits)} התאמות — להוסיף ל-MAP ב-epg_build.py:\n")
    for nm, cid in sorted(hits):
        print(f'    "<slug>": ("h", "{cid}"),'.ljust(34) + f"# {nm}")


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
    if a.epg_scan:
        print("שואל את וואלה\n")
        epg_scan(a.pattern)
        if a.thumbs:
            print()
    if a.hot_scan:
        hot_scan(a.pattern)
    if a.thumbs:
        do_thumbs(a.check)
    if not (a.thumbs or a.epg_scan or a.hot_scan):
        ap.print_help()


if __name__ == "__main__":
    main()
