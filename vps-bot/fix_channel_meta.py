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
           חייב לרוץ **מהשרת**: וואלה חוסם לפי מדינה, ומחוץ לישראל
           הבקשה חוזרת 400. זה מה שחסם אותי מלעשות את זה מרחוק.
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

WALLA = "https://dal.walla.co.il/tv/list?provider={p}"


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
    import urllib.request
    found = {}
    for prov in ("yes", "hot"):
        req = urllib.request.Request(
            WALLA.format(p=prov),
            headers={"Referer": "https://tv-guide.walla.co.il/",
                     "User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode("utf-8", "replace")
        except Exception as e:
            print(f"  {prov}: נכשל — {type(e).__name__}: {e}")
            continue
        try:
            data = json.loads(raw)
        except Exception:
            print(f"  {prov}: תשובה לא JSON — {raw[:120]}")
            continue
        if isinstance(data, dict) and data.get("code") == 400:
            print(f"  {prov}: וואלה החזיר 400. אם זה קורה על השרת — "
                  f"ייתכן ששינו את הכתובת או דורשים כותרת נוספת.")
            continue

        rx = re.compile(pattern, re.I)
        def walk(o):
            if isinstance(o, dict):
                nm = o.get("name") or o.get("title") or o.get("channel_name") or ""
                cid = o.get("id") or o.get("channel_id") or o.get("channelId")
                if nm and cid is not None and rx.search(str(nm)):
                    found[(str(cid), str(nm))] = prov
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(data)

    if not found:
        print("\nלא נמצא אף ערוץ מתאים. נסה תבנית רחבה יותר עם --pattern")
        return
    print(f"\n{len(found)} התאמות — להשלמה ל-MAP ב-epg_build.py:\n")
    for (cid, nm), prov in sorted(found.items(), key=lambda x: x[0][1]):
        src = "w"
        print(f'    "<slug>": ("{src}", {cid}),'.ljust(34) + f"# {nm}  [{prov}]")


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
        print("שואל את וואלה (חייב לרוץ מהשרת — הם חוסמים לפי מדינה)\n")
        epg_scan(a.pattern)
        if a.thumbs:
            print()
    if a.thumbs:
        do_thumbs(a.check)
    if not (a.thumbs or a.epg_scan):
        ap.print_help()


if __name__ == "__main__":
    main()
