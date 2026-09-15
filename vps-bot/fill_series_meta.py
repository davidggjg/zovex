#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fill_series_meta.py — משלים פוסטר וקטגוריה חסרים בתוך סדרה.

הבעיה: מיזוג סדרות מביא פרקים שהגיעו ממקור אחר, ולהם אין בהכרח פוסטר
או קטגוריה. כרטיס הסדרה במסך הבית לוקח את התמונה מפריט אחד — ואם הוא
נופל על פרק בלי פוסטר, הסדרה מוצגת בלי תמונה בכלל. באותו אופן, פרק
בקטגוריה אחרת גורם לסדרה להופיע פעמיים בשורות שונות.

בסוניק בום: 30 פרקים מתוך 47 עם פוסטר. 17 הפרקים שמוזגו מהסדרה "1"
הגיעו בלי.

הכלי לוקח את הערך הנפוץ ביותר בסדרה ומשלים אותו למי שחסר. הוא **לא**
דורס ערך קיים — פרק עם פוסטר משלו נשאר איתו.

    python3 fill_series_meta.py --series "סוניק בום" --check
    python3 fill_series_meta.py --series "סוניק בום"
    python3 fill_series_meta.py --all --check      # כל הסדרות בקטלוג
    python3 fill_series_meta.py --revert
"""
import argparse, json, os, shutil, sys, time
from collections import Counter
from pathlib import Path

DATA = Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
VERSION = DATA / "content_version.txt"
BACKUP = CONTENT.with_name("content.json.bak_fillmeta")
FIELDS = ("thumbnail_url", "category", "description", "year")


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True); raise


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--fields", default=",".join(FIELDS),
                    help="אילו שדות להשלים, מופרדים בפסיק")
    a = ap.parse_args()

    if a.revert:
        if not BACKUP.exists():
            sys.exit(f"אין גיבוי ב-{BACKUP}")
        shutil.copy2(BACKUP, CONTENT)
        print(f"✓ שוחזר מ-{BACKUP}")
        return
    if not a.series and not a.all:
        sys.exit("צריך --series <שם> או --all")
    if not CONTENT.exists():
        sys.exit(f"לא נמצא: {CONTENT}")

    fields = [f.strip() for f in a.fields.split(",") if f.strip()]
    items = json.loads(CONTENT.read_text(encoding="utf-8"))

    groups = {}
    for i in items:
        sn = (i.get("series_name") or "").strip()
        if not sn:
            continue
        if a.series and sn != a.series.strip():
            continue
        groups.setdefault(sn, []).append(i)

    if not groups:
        sys.exit(f"לא נמצאה סדרה {a.series!r}" if a.series else "אין סדרות")

    changes = []
    report = []
    for sn, eps in sorted(groups.items()):
        row = {"name": sn, "n": len(eps), "fixed": {}}
        for f in fields:
            vals = [i.get(f) for i in eps if i.get(f) not in (None, "", 0)]
            missing = [i for i in eps if i.get(f) in (None, "", 0)]
            if not vals or not missing:
                continue
            # הערך הנפוץ ביותר, לא הראשון: פרק בודד עם ערך שגוי לא יקבע
            # לכל הסדרה. זה בדיוק מה שקרה בכפילויות הקטגוריה.
            best = Counter(map(str, vals)).most_common(1)[0][0]
            real = next(v for v in vals if str(v) == best)
            row["fixed"][f] = (len(missing), real)
            for i in missing:
                changes.append((i, f, real))
        if row["fixed"]:
            report.append(row)

    print(f"קטלוג: {len(items)} פריטים · נבדקו {len(groups)} סדרות\n")
    if not report:
        print("אין מה להשלים — לכל פרק יש את כל השדות.")
        return

    print("=" * 66)
    for r in report:
        print(f"\n  {r['name']}  ({r['n']} פרקים)")
        for f, (cnt, val) in r["fixed"].items():
            sval = str(val)
            if len(sval) > 54:
                sval = sval[:51] + "…"
            print(f"     {f:<15} חסר ב-{cnt:>3} → {sval}")
    print("\n" + "=" * 66)
    print(f"{len(changes)} שדות יושלמו ב-{len(report)} סדרות")

    if a.check:
        print("\n--check: שום דבר לא נכתב.")
        return

    shutil.copy2(CONTENT, BACKUP)
    for i, f, v in changes:
        i[f] = v
    atomic_write(CONTENT, json.dumps(items, ensure_ascii=False, indent=2))
    try:
        ver = int(VERSION.read_text().strip()) + 1 if VERSION.exists() else 1
    except Exception:
        ver = int(time.time())
    atomic_write(VERSION, str(ver))
    print(f"\n✓ הושלמו {len(changes)} שדות · גיבוי: {BACKUP} · גרסה {ver}")
    print("  בלי restart. האתר והאפליקציה ירעננו לבד.")


if __name__ == "__main__":
    main()
