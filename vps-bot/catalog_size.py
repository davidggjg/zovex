#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# כמה נפח יש בתוכן שאנחנו באמת מגישים.
#
# ## מה נספר, ומה לא
#
# רק מה שמופיע בקטלוג שהאתר והאפליקציה מושכים (/content/lite), ורק פריטים
# שמוגשים דרך ‎/stream/‎ — כלומר קבצים שיושבים בטלגרם. מה שיושב בערוץ
# האחסון ואינו בקטלוג לא נספר, וכך גם שידורים חיים: הם כתובות חיצוניות
# ולא קבצים, ואין להם גודל.
#
# ## מאיפה הגדלים
#
# מ-‎data/stream_meta.json‎, שהשרת כבר ממלא לכל פריט שמישהו פתח. לכן ריצת
# ברירת המחדל מיידית, לא נוגעת בטלגרם, ולא מוסיפה שום עומס.
#
# הכיסוי כמעט לעולם אינו מלא — פריט שאיש לא פתח מעולם אינו במטמון.
# הסקריפט אומר במפורש כמה הוא יודע וכמה הוא משלים בהערכה, ולא מציג
# הערכה כאילו הייתה מדידה. ‎--fill‎ משלים את החסר מול טלגרם, לאט.
#
#   python3 catalog_size.py              # מיידי, מהמטמון
#   python3 catalog_size.py --fill 500   # משלים 500 פריטים חסרים
#   python3 catalog_size.py --fill all   # משלים הכל (שעות)
# ─────────────────────────────────────────────────────────────────────────────
import json
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict

BASE = os.environ.get("SIZE_BASE", "http://127.0.0.1:8000")
META = os.environ.get("SIZE_META", "/opt/zovex-bot/data/stream_meta.json")
PAUSE = float(os.environ.get("SIZE_PAUSE", "0.3"))

STREAM_RE = re.compile(r"/stream/(-?\d+)/(\d+)(\?[^\"'\s<>\\]*)?")
GB = 1024 ** 3


def human(n):
    return f"{n / GB:,.1f} GB" if n >= GB else f"{n / 1024 / 1024:,.0f} MB"


def catalog():
    """(chat, msg, qs) ייחודיים מהקטלוג, בסדר התצוגה."""
    try:
        raw = urllib.request.urlopen(BASE + "/content/lite", timeout=240).read()
    except Exception as e:
        sys.exit(f"לא הצלחתי לקרוא את הקטלוג מ-{BASE}: {e}")
    body = raw.decode("utf-8", "replace")
    seen, out = set(), []
    for chat, msg, qs in STREAM_RE.findall(body):
        if (chat, msg) in seen:
            continue
        seen.add((chat, msg))
        out.append((chat, msg, qs or ""))
    # ספירת פריטים חיים, רק כדי לדווח מה הוצא מהחשבון ולא להשאיר פער
    # בלתי מוסבר בין מספר הפריטים בקטלוג למספר שנספר כאן.
    try:
        live = sum(1 for e in json.loads(body) if e.get("is_live"))
    except Exception:
        live = -1
    try:
        total_entries = len(json.loads(body))
    except Exception:
        total_entries = -1
    return out, live, total_entries


def fetch_size(chat, msg, qs):
    req = urllib.request.Request(f"{BASE}/stream/{chat}/{msg}{qs}")
    req.add_header("Range", "bytes=0-0")
    with urllib.request.urlopen(req, timeout=90) as r:
        cr = r.headers.get("Content-Range", "")
    return int(cr.rsplit("/", 1)[1]) if "/" in cr else 0


def main():
    fill = 0
    if "--fill" in sys.argv:
        v = sys.argv[sys.argv.index("--fill") + 1]
        fill = 10 ** 9 if v == "all" else int(v)

    items, live, entries = catalog()
    try:
        meta = json.load(open(META, encoding="utf-8"))
    except Exception as e:
        sys.exit(f"לא נפתח {META}: {e}")

    known, missing = {}, []
    for chat, msg, qs in items:
        m = meta.get(f"{chat}:{msg}")
        if m and m.get("size"):
            known[(chat, msg)] = int(m["size"])
        else:
            missing.append((chat, msg, qs))

    if fill and missing:
        todo = missing[:fill]
        print(f"משלים {len(todo)} פריטים חסרים מול טלגרם — זה לוקח זמן.\n")
        got = 0
        for i, (chat, msg, qs) in enumerate(todo, 1):
            try:
                sz = fetch_size(chat, msg, qs)
                if sz:
                    known[(chat, msg)] = sz
                    got += 1
            except Exception:
                pass
            if i % 25 == 0:
                print(f"   {i}/{len(todo)} · הושלמו {got}")
            time.sleep(PAUSE)
        missing = [x for x in missing if (x[0], x[1]) not in known]
        print()

    n_known = len(known)
    n_all = len(items)
    total = sum(known.values())
    avg = total / n_known if n_known else 0

    print("═" * 58)
    print("נפח התוכן שמוגש באתר ובאפליקציה")
    print("═" * 58)
    if entries >= 0:
        print(f"פריטים בקטלוג:        {entries:,}")
    if live >= 0:
        print(f"  מתוכם שידורים חיים: {live:,}  (כתובות חיצוניות, בלי נפח)")
    print(f"  קבצים מטלגרם:       {n_all:,}")
    print()
    print(f"נמדדו בפועל:          {n_known:,} מתוך {n_all:,} "
          f"({100 * n_known / max(n_all, 1):.0f}%)")
    print(f"נפח מדוד:             {human(total)}")
    if n_known:
        print(f"גודל ממוצע לפריט:     {human(avg)}")
    print()

    if missing:
        est = total + avg * len(missing)
        print(f"⚠️  ל-{len(missing):,} פריטים אין גודל במטמון — איש לא פתח אותם.")
        print(f"    הערכה לסך הכל (לפי הממוצע): ~{human(est)}")
        print(f"    זו הערכה ולא מדידה. למדידה מלאה:  "
              f"python3 {os.path.basename(__file__)} --fill all")
    else:
        print("✓ כיסוי מלא — זו מדידה ולא הערכה.")

    if known:
        print()
        big = sorted(known.items(), key=lambda kv: -kv[1])[:5]
        print("חמשת הגדולים:")
        for (chat, msg), sz in big:
            nm = (meta.get(f"{chat}:{msg}") or {}).get("name") or f"{chat}/{msg}"
            print(f"   {human(sz):>10}  {nm[:52]}")

        buckets = defaultdict(int)
        for sz in known.values():
            if sz < GB:
                buckets["עד 1GB"] += 1
            elif sz < 2 * GB:
                buckets["1–2GB"] += 1
            elif sz < 5 * GB:
                buckets["2–5GB"] += 1
            else:
                buckets["מעל 5GB"] += 1
        print("\nפיזור גדלים:")
        for k in ("עד 1GB", "1–2GB", "2–5GB", "מעל 5GB"):
            if buckets[k]:
                print(f"   {k:>8}  {buckets[k]:,}")


if __name__ == "__main__":
    main()
