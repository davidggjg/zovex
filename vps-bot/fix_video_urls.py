#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מנקה כתובות וידאו פגומות בקטלוג, ומדווח על מה שאי אפשר לתקן.

הרקע: בדיקה של הקטלוג המלא (11,845 פריטים) מצאה פריטים שלא יכולים להתנגן
לעולם — לא באתר ולא באפליקציה, כי שניהם בונים את הקישור מאותו שדה.

מה שניתן לשחזור בוודאות ומתוקן כאן:

    <iframe src="…"></iframe>   הודבק קוד ההטמעה במקום הכתובת. ב"פאוור קאפל"
                                7 פרקים שמורים כתובת נקייה ו-3 כ-iframe שלם —
                                אותו יעד בדיוק, ולכן זה שחזור ולא ניחוש.
    ttps:// · ttp://            נבלעה ה-h הראשונה (9 פרקים ב"הכבוד של אשרף").
    &amp;                       נשמר HTML-escaped במקום &.

מה ש*לא* מתוקן, כי אין ממה לשחזר — רק מדווח:

    video_url ריק               61 פרקים ב"וואן פיס". שאר 1,108 הפרקים תקינים,
                                כלומר חסר רק הקישור לאותם פרקים.
    מזהה חשוף בלי מבנה          כ-20 פרקים ב"קופה ראשית" ששמורים כ-"809157".
                                שאר 86 הפרקים שם משתמשים ב-r.il.cdn-redge.media,
                                כלומר זה מקור אחר לגמרי ואי אפשר להסיק ממנו.

בטוח: ברירת המחדל היא הרצה יבשה שלא כותבת כלום. --apply מגבה ואז כותב.

    python3 fix_video_urls.py             # מראה מה היה משתנה
    python3 fix_video_urls.py --apply     # מתקן בפועל
"""
import argparse, collections, datetime, json, pathlib, re, shutil, sys

DATA = pathlib.Path("/opt/zovex-bot/data")
CONTENT = DATA / "content.json"

IFRAME_RX = re.compile(r'<iframe[^>]*\ssrc=["\']([^"\']+)["\']', re.I)
SCHEME_RX = re.compile(r'^(ttps?)://', re.I)
# מזהה שאינו כתובת ואינו המבנה התקין של קלטורה (partner/uiconf/entry)
KALTURA_TRIPLE = re.compile(r'^\d+/\d+/[A-Za-z0-9_]+$')


def clean(v):
    """מחזיר (כתובת_נקייה, מה_תוקן) — או (המקור, None) אם לא נגענו."""
    if not isinstance(v, str):
        return v, None
    out, what = v.strip(), []
    m = IFRAME_RX.search(out)
    if m:
        out = m.group(1).strip()
        what.append("iframe")
    m = SCHEME_RX.match(out)
    if m:
        out = ("https://" if m.group(1).lower() == "ttps" else "http://") + out[len(m.group(0)):]
        what.append("סכימה")
    if "&amp;" in out:
        out = out.replace("&amp;", "&")
        what.append("&amp;")
    return out, (" + ".join(what) if what and out != v.strip() else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="לכתוב בפועל")
    a = ap.parse_args()

    if not CONTENT.exists():
        sys.exit(f"לא נמצא {CONTENT}")
    raw = json.loads(CONTENT.read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else raw.get("movies", [])
    print(f"קטלוג: {len(items)} פריטים\n")

    fixed, kinds = [], collections.Counter()
    for m in items:
        for field in ("video_url", "video_id"):
            v = m.get(field)
            new, what = clean(v)
            if what:
                kinds[what] += 1
                fixed.append((m.get("series_name") or m.get("title") or "?", field,
                              str(v)[:44], str(new)[:44]))
                if a.apply:
                    m[field] = new

    print(f"── ניתן לתיקון: {len(fixed)} ──")
    for k, n in kinds.most_common():
        print(f"   {k:16} {n}")
    for name, field, before, after in fixed[:8]:
        print(f"   {name[:22]:22} {field}\n      לפני: {before}\n      אחרי: {after}")
    if len(fixed) > 8:
        print(f"   … ועוד {len(fixed) - 8}")

    # דיווח על מה שאינו ניתן לתיקון — כדי שיהיה ברור מה דורש טיפול ידני
    # מסווגים לפי הערך *אחרי* הניקוי, גם בהרצה יבשה. אחרת פריט שהתיקון
    # האוטומטי מטפל בו נספר גם כאן, והרשימה "דורש טיפול ידני" מנפחת את
    # עצמה בדיוק במה שאינו דורש טיפול ידני.
    empty, bare = collections.Counter(), collections.Counter()
    for m in items:
        v, _ = clean(str(m.get("video_url") or m.get("video_id") or ""))
        v = v.strip()
        name = m.get("series_name") or m.get("title") or "?"
        if not v:
            empty[name] += 1
        elif not v.startswith(("http://", "https://", "file://", "%BASE%")) \
                and not KALTURA_TRIPLE.match(v):
            bare[name] += 1

    print(f"\n── דורש טיפול ידני: אין ממה לשחזר ──")
    print(f"   כתובת ריקה ({sum(empty.values())} פריטים):")
    for n, c in empty.most_common(6):
        print(f"      {n[:34]:34} {c}")
    print(f"   מזהה חשוף בלי מבנה ({sum(bare.values())} פריטים):")
    for n, c in bare.most_common(6):
        print(f"      {n[:34]:34} {c}")

    if not a.apply:
        print("\n(הרצה יבשה — לא נכתב כלום. להחלה: --apply)")
        return
    if not fixed:
        print("\nאין מה לתקן.")
        return

    bak = CONTENT.with_suffix(f".json.bak-urls-{datetime.datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(CONTENT, bak)
    CONTENT.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n✅ תוקנו {len(fixed)} שדות.")
    print(f"   גיבוי: {bak.name}")
    print("   הרץ:   systemctl restart zovex-bot")


if __name__ == "__main__":
    main()
