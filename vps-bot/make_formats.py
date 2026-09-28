#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_formats — בונה את קובץ התבניות ל-hunt_channels מהקטלוג החי.

## למה

‎hunt_channels.py‎ צריך ‎--formats fmt.txt‎: שורה לכל תבנית כתובת של
ספק, עם ‎{n}‎ במקום מספר הערוץ. לכתוב אותן ביד פירושו להעתיק מארחים
ואסימוני גישה למסך ולהדבקה — ואלה בדיוק הערכים שאסור שיסתובבו.

הקטלוג כבר מכיל את כל התבניות האלה, בכתובות של הערוצים שעובדים היום.
הסקריפט מוציא אותן משם, מחליף את המספר ב-‎{n}‎, ומסיר כפילויות.
כלומר התבניות נשארות על השרת ואינן עוברות דרך אף מקום אחר.

**הפלט למסך ממוסך.** שם המארח והאסימון מוחלפים, כך שאפשר להעתיק את
מה שמודפס. הקובץ עצמו, שנשאר על השרת, מכיל את הערכים האמיתיים.

    python3 make_formats.py                 → /tmp/hunt/fmt.txt
    python3 make_formats.py --out x.txt
    python3 make_formats.py --min 2         רק תבניות עם 2+ ערוצים

ואז:

    python3 hunt_channels.py --formats /tmp/hunt/fmt.txt --from 1 --to 600

קריאה בלבד: לא נוגע בקטלוג, לא בשירות ולא בקבצים של הערוצים.
"""
import argparse
import json
import os
import pathlib
import re
import sys
from collections import Counter

DATA = pathlib.Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"

# ‎/hls-relay/<host>/<path>‎ או ‎/hls-relay/_fix/<host>/<path>‎.
#
# ‎search‎ ולא ‎match‎, ובלי עיגון להתחלה: הקטלוג שומר קישורים עם מציין
# המקום ‎%BASE%‎ בראש (הוא מוחלף בכתובת האמיתית רק בהגשה), ויש גם
# פריטים עם כתובת מוחלטת. עיגון ל-‎^/hls-relay‎ מצא **אפס** תבניות על
# קטלוג מלא של ערוצים חיים — ניחשתי את הצורה במקום לקרוא אותה.
RELAY = re.compile(r"/hls-relay/(?:_fix/)?([^/?]+)/([^?]+)")
# מקטע נתיב שהוא מספר בלבד — מזהה הערוץ. ‎/live/330/chunks.m3u8‎ ⇒ 330
NUMSEG = re.compile(r"/(\d{1,6})(?=/)")


# מילים שמופיעות בשמות מארחים ואינן מזהות ספק
_GENERIC = {"com", "net", "org", "www", "live", "stream", "iptv",
            "http", "https", "index", "playlist", "chunks", "m3u8"}


def _labels(host: str) -> set:
    """המילים שמזהות את הספק בשם המארח שלו.

    הן מופיעות לא רק במארח אלא גם **בתוך הנתיב** — שער בשם
    ‎/p/<שם-הספק>/s/{n}/‎ הוא צורה נפוצה. מיסוך שהסתיר רק את המארח
    השאיר אותן על המסך, וזה נתפס רק אחרי שהפלט כבר הודפס.
    """
    out = set()
    for w in re.split(r"[.\-_:]+", host.lower()):
        if len(w) >= 3 and not w.isdigit() and w not in _GENERIC:
            out.add(w)
    return out


def mask(s: str) -> str:
    """להדפסה בלבד: מסתיר מארח ואסימון.

    הגרסה הראשונה חתכה ‎^[^/]+‎, וזה תפס רק את ‎https:‎ — המארח נשאר
    על המסך במלואו. נתפס בבדיקה, לפני שהודפס משהו אמיתי.
    """
    return mask_at(s, "ספק")


def mask_at(s: str, tag: str) -> str:
    """כמו mask, עם תגית מארח משלה."""
    g = re.match(r"^[a-z]+://([^/:]+)", s)
    host = g.group(1) if g else ""
    s = re.sub(r"^[a-z]+://[^/]+", f"<{tag}>", s)
    for w in sorted(_labels(host), key=len, reverse=True):
        s = re.sub(re.escape(w), "<שם>", s, flags=re.I)
    return re.sub(r"\b[A-Za-z0-9]{10,}\b", "<אסימון>", s)


def mask_any(s: str) -> str:
    """מיסוך לכל קישור, גם כזה שאינו תבנית — לדוגמאות האבחון."""
    g = re.search(r"/hls-relay/(?:_fix/)?([^/?]+)", s)
    host = g.group(1).split(":")[0] if g else ""
    s = re.sub(r"(/hls-relay/(?:_fix/)?)[^/?]+", r"\1<ספק>", s)
    s = re.sub(r"^[a-z]+://[^/]+", "<מארח>", s)
    for w in sorted(_labels(host), key=len, reverse=True):
        s = re.sub(re.escape(w), "<שם>", s, flags=re.I)
    return re.sub(r"\b[A-Za-z0-9]{16,}\b", "<אסימון>", s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/hunt/fmt.txt")
    ap.add_argument("--min", type=int, default=1,
                    help="מינימום ערוצים לתבנית כדי שתיכלל")
    a = ap.parse_args()

    try:
        data = json.loads(CONTENT.read_text(encoding="utf-8"))
    except Exception as e:                                   # noqa: BLE001
        sys.exit(f"לא ניתן לקרוא את {CONTENT}: {e}")
    items = data if isinstance(data, list) else data.get("movies", [])

    seen = Counter()
    for m in items:
        url = (m.get("video_url") or "").strip()
        g = RELAY.search(url)
        if not g:
            continue
        host, path = g.group(1), g.group(2)
        # רק המקטע המספרי **האחרון** מוחלף: בנתיב כמו
        # ‎/p/<שער>/s/103/playlist.m3u8‎ יש מספר אחד, אבל בתבניות אחרות
        # יכול להופיע מספר גם בשם השער — והמזהה הוא תמיד האחרון.
        hits = list(NUMSEG.finditer("/" + path))
        if not hits:
            continue
        last = hits[-1]
        tmpl_path = ("/" + path)[:last.start(1)] + "{n}" \
            + ("/" + path)[last.end(1):]
        seen[f"{host}{tmpl_path}"] += 1

    picked = [(t, c) for t, c in seen.most_common() if c >= a.min]
    if not picked:
        # "לא נמצא" בלי לומר מה כן יש שולח לחפש במקום הלא נכון. כאן
        # מודפסות דוגמאות ממוסכות, כדי שאפשר יהיה לראות את הצורה
        # האמיתית במקום לנחש אותה — וזו בדיוק הטעות שהביאה לכאן.
        print("לא נמצאה אף תבנית. כך נראים הקישורים בקטלוג:\n")
        shown = 0
        for m in items:
            v = (m.get("video_url") or "").strip()
            if not v or shown >= 8:
                continue
            print("  " + mask_any(v))
            shown += 1
        print(f"\n  (מתוך {len(items)} פריטים)")
        print("\nאם אין ביניהם /hls-relay — הערוצים החיים אינם בקטלוג הזה.")
        sys.exit(1)

    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # ‎hunt_channels‎ בונה כתובת מלאה, ולכן צריך סכימה. הרלֵיי מחזיק את
    # הסכימה והפורט האמיתיים ב-relay_hosts.json, ולא מנחשים אותם —
    # הניחוש הזה כבר עלה סריקה שלמה ב-scan_all.
    try:
        origins = json.loads((DATA / "relay_hosts.json").read_text("utf-8"))
    except Exception:
        origins = {}

    lines = []
    for t, _c in picked:
        host = t.split("/", 1)[0].split(":")[0]
        o = origins.get(host) or {}
        scheme = o.get("scheme") or "http"
        port = o.get("port")
        netloc = t.split("/", 1)[0]
        if port and ":" not in netloc:
            if not (scheme == "https" and port == 443) \
                    and not (scheme == "http" and port == 80):
                netloc = f"{netloc}:{port}"
        lines.append(f"{scheme}://{netloc}/{t.split('/', 1)[1]}")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # תגית קבועה לכל מארח. בלעדיה שתי תבניות באותה **צורה** על שני
    # ספקים שונים מודפסות כשתי שורות זהות לחלוטין, ואי אפשר לדעת
    # לאיזו מהן להתכוון — וזה בדיוק מה שקרה בפלט הראשון.
    tags = {}
    for t, _c in picked:
        h = t.split("/", 1)[0].split(":")[0]
        tags.setdefault(h, f"ספק{len(tags) + 1}")

    print(f"נמצאו {len(picked)} תבניות ב-{len(items)} פריטי קטלוג:\n")
    for i, ((t, c), full) in enumerate(zip(picked, lines), 1):
        h = t.split("/", 1)[0].split(":")[0]
        known = "✓" if h in origins else "⚠"
        print(f"  {i}. {known} {c:>4} ערוצים   {mask_at(full, tags[h])}")
    if any(t.split("/", 1)[0].split(":")[0] not in origins for t, _ in picked):
        print("\n  ⚠ = המארח אינו ב-relay_hosts.json, ולכן הסכימה והפורט")
        print("      הם ניחוש (http:80). ייתכן שהסריקה עליו תחזיר אפס.")
    print(f"\nנשמר: {out}")
    print("\nעכשיו:")
    print(f"  python3 hunt_channels.py --formats {out} --from 1 --to 600")
    return 0


if __name__ == "__main__":
    sys.exit(main())
