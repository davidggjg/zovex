#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · ניקוי הקטלוג: כפילויות וקטגוריות שגויות.
#
# ברירת המחדל היא **הדמיה בלבד**. בלי ‎--apply‎ שום דבר לא נכתב.
#
#   python3 catalog_fix.py                 # מראה מה היה קורה + דוח CSV
#   python3 catalog_fix.py --apply         # מבצע, אחרי גיבוי
#   python3 catalog_fix.py --restore       # מחזיר מהגיבוי האחרון של הסקריפט
#
# ## מה הוא מזהה ככפילות
#
# ארבעה כללים, כולם ניתנים להוכחה מהנתונים ולא ניחוש על תוכן:
#
#   1. אותו קובץ בטלגרם — אותו ערוץ ואותו מזהה הודעה, או אותו
#      file_unique_id. שתי רשומות שמצביעות לאותם בתים בדיוק.
#   2. אותה כתובת וידאו, אחרי הסרת exp/sig שמשתנים בכל חתימה.
#   3. אותו פרק: אותה סדרה, אותה עונה, אותו מספר פרק.
#   4. אותו סרט: אותו tmdb_id, או אותו שם ואותה שנה.
#
# כלל 3 תופס גם רשומות שמצביעות לקבצים שונים. זו עדיין כפילות:
# המשתמש רואה את אותו פרק פעמיים. נבדק על מדגם — אלה פרקים שנוספו
# פעמיים ממקורות שונים, לרוב אחד בעברית ואחד באנגלית.
#
# ## מי נשאר
#
# הרשומה המלאה ביותר, לפי ניקוד: tmdb_id, תמונה, שנה, תיאור, שם
# אנגלי, קישור לטריילר, ומספר השדות המלאים. בתיקו — הוותיקה.
# כך לא מאבדים מטא-דאטה שנאספה.
#
# ## קטגוריות
#
# רק מה שהנתונים סותרים בעצמם: פרק שהקטגוריה שלו שונה מזו של רוב
# הפרקים האחרים באותה סדרה (לפחות 75% מהם, ולפחות שלושה פרקים).
# "משפחת סימפסון" היא המקרה הגדול: 41 פרקים ב"סרטים" מול 345
# ב"סדרות".
#
# קטגוריות ז'אנר — "מארוול", "אימה" — אינן נוגעות לכלל הזה, כי הן
# מחזיקות סרטים וסדרות גם יחד לפי תכנון.
#
# ## בטיחות
#
#   · גיבוי מלא לפני כל כתיבה, עם חותמת זמן.
#   · מסרב אם ההסרה גדולה מ-10% מהקטלוג.
#   · מסרב אם content.json השתנה בין הקריאה לכתיבה (הבוט כתב באמצע).
#   · שידורים חיים אינם נמחקים לעולם.
#   · כתיבה אטומית דרך קובץ זמני, ואז בדיקה שהקובץ נקרא ושלם.
#   · content_version.txt מקודם — בלי זה האפליקציה והאתר ממשיכים
#     להגיש את הגרסה הישנה מהמטמון שלהם. זה בדיוק מה שקרה בשחזור
#     הקטלוג, והאפליקציה נשארה ריקה אחרי שהכל כבר תוקן.
# ─────────────────────────────────────────────────────────────────────────────
import collections
import csv
import json
import os
import re
import shutil
import sys
import time
import unicodedata
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/opt/zovex-bot/data"))
CONTENT = DATA_DIR / "content.json"
VERSION_FILE = DATA_DIR / "content_version.txt"
BAK_DIR = DATA_DIR / "catalog_fix_backups"
REPORT = DATA_DIR / "catalog_fix_report.csv"
MAX_REMOVE_FRACTION = 0.10
MIN_SERIES_MAJORITY = 0.75
MIN_SERIES_SIZE = 3

APPLY = "--apply" in sys.argv
RESTORE = "--restore" in sys.argv


def norm(s):
    """נרמול שמרני: שומר כל אות או ספרה בכל שפה.

    גרסה מוקדמת השאירה עברית ולטינית בלבד, וכל שם בסינית או בהינדית
    הפך למחרוזת ריקה — ואז כל הסרטים ההודיים מאותה שנה נראו כאותו
    סרט. אסור שניקוי ימחק פריטים על סמך טעות כזו.
    """
    s = unicodedata.normalize("NFKC", str(s or "")).lower().strip()
    s = re.sub(r"[֑-ׇ]", "", s)
    s = "".join(c if c.isalnum() else " " for c in s)
    return re.sub(r"\s+", " ", s).strip()


def is_episode(i):
    return (bool(i.get("series_name"))
            and i.get("season_number") not in (None, "")
            and i.get("episode_number") not in (None, ""))


def canon_url(u):
    u = (u or "").strip()
    if not u:
        return None
    m = re.search(r"/stream/(-?\d+)/(\d+)", u)
    if m:
        return "tg:%s/%s" % m.groups()
    u = re.sub(r"[?&](exp|sig|t)=[^&]*", "", u)
    return u.rstrip("?&").lower() or None


def score(i):
    """כמה הרשומה 'שלמה'. הגבוהה ביותר נשארת."""
    s = 0
    for field, w in (("tmdb_id", 40), ("thumbnail_url", 25), ("description", 20),
                     ("year", 10), ("en_title", 8), ("trailer_url", 5),
                     ("episode_title", 5), ("custom_slug", 3), ("media_kind", 3)):
        if i.get(field) not in (None, "", [], {}):
            s += w
    s += sum(1 for v in i.values() if v not in (None, "", [], {}))
    return s


def keep_of(group):
    """הרשומה שנשארת: המלאה ביותר, ובתיקו — הוותיקה."""
    return sorted(group, key=lambda i: (-score(i), str(i.get("created_date") or ""),
                                        str(i.get("id") or "")))[0]


def keys_for(i):
    """כל מפתחות הזיהוי של פריט. שניים שחולקים מפתח הם אותו דבר."""
    ks = []
    if i.get("file_unique_id"):
        ks.append(("קובץ זהה בטלגרם", "uid:%s" % i["file_unique_id"]))
    if i.get("channel_id") and i.get("channel_msg_id"):
        ks.append(("אותה הודעה בערוץ", "msg:%s/%s" % (i["channel_id"], i["channel_msg_id"])))
    cu = canon_url(i.get("video_url"))
    if cu:
        ks.append(("אותה כתובת וידאו", "url:%s" % cu))
    if is_episode(i):
        ks.append(("אותו פרק", "ep:%s|%s|%s|%s" % (
            norm(i["series_name"]), i["season_number"], i["episode_number"],
            i.get("episode_number_end") or "")))
    elif not i.get("series_name") and i.get("season_number") in (None, ""):
        # כללי הסרטים חלים רק על מה שאינו שייך לסדרה בכלל.
        #
        # נמדד: ל"כוננות שיא" יש שישה פרקים באותה עונה עם אותו tmdb_id
        # ואותו שם, וחמישה מהם בלי מספר פרק — הודעות 5106 עד 5111
        # בערוץ, כלומר שישה קבצים שונים. הכלל "אותו tmdb" היה מוחק
        # ארבעה פרקים אמיתיים. פריט עם series_name או season_number
        # הוא פרק שחסרה לו מטא-דאטה, לא סרט כפול.
        if i.get("tmdb_id"):
            ks.append(("אותו סרט (tmdb)", "tmdb:%s" % i["tmdb_id"]))
        for fld in ("title", "en_title"):
            t = norm(i.get(fld))
            if t and i.get("year"):
                ks.append(("אותו סרט (שם+שנה)", "mv:%s|%s" % (t, i["year"])))
    return ks


def find_duplicates(arr):
    """איחוד קבוצות: פריטים שמחוברים דרך מפתח משותף נופלים לאותה קבוצה."""
    parent = list(range(len(arr)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    by_key = collections.defaultdict(list)
    reason = {}
    for idx, i in enumerate(arr):
        if i.get("is_live"):
            continue          # שידורים חיים לא נמחקים לעולם
        for label, k in keys_for(i):
            by_key[k].append(idx)
            reason[k] = label
    for k, idxs in by_key.items():
        for j in idxs[1:]:
            union(idxs[0], j)

    groups = collections.defaultdict(list)
    for idx, i in enumerate(arr):
        if i.get("is_live"):
            continue
        groups[find(idx)].append(idx)
    out = []
    for root, idxs in groups.items():
        if len(idxs) > 1:
            shared = [reason[k] for k, v in by_key.items()
                      if len(v) > 1 and find(v[0]) == root]
            out.append((idxs, sorted(set(shared))))
    return out


def main():
    if RESTORE:
        baks = sorted(BAK_DIR.glob("content_*.json")) if BAK_DIR.exists() else []
        if not baks:
            sys.exit("אין גיבוי של הסקריפט ב-%s" % BAK_DIR)
        last = baks[-1]
        shutil.copy2(last, CONTENT)
        bump()
        print("✅ שוחזר מ-%s" % last)
        return

    if not CONTENT.exists():
        sys.exit("לא נמצא %s — זה לא שרת ZOVEX, או ש-DATA_DIR שונה" % CONTENT)
    stat_before = CONTENT.stat()
    arr = json.loads(CONTENT.read_text(encoding="utf-8"))
    if not isinstance(arr, list) or not arr:
        sys.exit("content.json אינו רשימה או שהוא ריק — לא נוגעים בכלום")
    print("קטלוג: %d פריטים" % len(arr))

    rows = []
    drop = set()

    # ── כפילויות ───────────────────────────────────────────────────────────
    dup_groups = find_duplicates(arr)
    by_reason = collections.Counter()
    for idxs, reasons in dup_groups:
        group = [arr[j] for j in idxs]
        keep = keep_of(group)
        # סימון מפורש כששתי הרשומות מצביעות לקבצים שונים: אלה המקרים
        # שכדאי לעבור עליהם בדוח לפני --apply, כי שם טעות עולה בתוכן
        # ולא רק ברשומה כפולה.
        diff_files = len({canon_url(x.get("video_url")) for x in group}) > 1
        tag = "  [קבצים שונים]" if diff_files else ""
        for j in idxs:
            it = arr[j]
            if it is keep:
                continue
            drop.add(j)
            by_reason[" + ".join(reasons) + tag] += 1
            rows.append({
                "פעולה": "מחיקה", "סיבה": " + ".join(reasons) + tag,
                "id": it.get("id"), "כותרת": it.get("title"),
                "סדרה": it.get("series_name"), "עונה": it.get("season_number"),
                "פרק": it.get("episode_number"), "קטגוריה": it.get("category"),
                "נשאר_במקום": keep.get("id"), "ערך_חדש": "",
                "נוצר": it.get("created_date"),
            })

    # ── קטגוריות ───────────────────────────────────────────────────────────
    by_series = collections.defaultdict(list)
    for idx, i in enumerate(arr):
        if idx in drop or not is_episode(i):
            continue
        by_series[norm(i["series_name"])].append(idx)

    cat_fix = {}
    for _, idxs in by_series.items():
        if len(idxs) < MIN_SERIES_SIZE:
            continue
        cats = collections.Counter(arr[j].get("category") for j in idxs)
        main_cat, n = cats.most_common(1)[0]
        if not main_cat or n / len(idxs) < MIN_SERIES_MAJORITY:
            continue
        for j in idxs:
            if arr[j].get("category") != main_cat:
                cat_fix[j] = main_cat
                it = arr[j]
                rows.append({
                    "פעולה": "קטגוריה", "סיבה": "רוב פרקי הסדרה (%d מתוך %d) ב\"%s\""
                                                % (n, len(idxs), main_cat),
                    "id": it.get("id"), "כותרת": it.get("title"),
                    "סדרה": it.get("series_name"), "עונה": it.get("season_number"),
                    "פרק": it.get("episode_number"), "קטגוריה": it.get("category"),
                    "נשאר_במקום": "", "ערך_חדש": main_cat,
                    "נוצר": it.get("created_date"),
                })

    no_cat = [idx for idx, i in enumerate(arr)
              if idx not in drop and not i.get("category")]

    # ── סיכום ──────────────────────────────────────────────────────────────
    print()
    print("כפילויות למחיקה: %d" % len(drop))
    for r, n in by_reason.most_common():
        print("   %-46s %5d" % (r[:46], n))
    print("תיקוני קטגוריה: %d" % len(cat_fix))
    for c, n in collections.Counter(cat_fix.values()).most_common(8):
        print("   → %-42s %5d" % (c, n))
    if no_cat:
        print("בלי קטגוריה (לא נוגעים, רק מדווחים): %d" % len(no_cat))
        for idx in no_cat[:5]:
            print("   id=%s  %s" % (arr[idx].get("id"), arr[idx].get("title")))

    if rows:
        with open(REPORT, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print("\nדוח מלא: %s (%d שורות)" % (REPORT, len(rows)))

    if not drop and not cat_fix:
        print("\n✅ אין מה לתקן.")
        return

    frac = len(drop) / len(arr)
    print("\nאחרי הניקוי: %d פריטים (הסרה של %.1f%%)" % (len(arr) - len(drop), frac * 100))
    if frac > MAX_REMOVE_FRACTION:
        sys.exit("❌ ההסרה גדולה מ-%d%% — עצירה. זה נראה כמו באג ולא כמו ניקוי."
                 % int(MAX_REMOVE_FRACTION * 100))

    if not APPLY:
        print("\nזו הדמיה בלבד. שום דבר לא נכתב.")
        print("לביצוע:  python3 %s --apply" % sys.argv[0])
        return

    # ── ביצוע ──────────────────────────────────────────────────────────────
    st = CONTENT.stat()
    if (st.st_mtime, st.st_size) != (stat_before.st_mtime, stat_before.st_size):
        sys.exit("❌ content.json השתנה בזמן הריצה — הבוט כתב אליו. לא נוגעים; הרץ שוב.")

    BAK_DIR.mkdir(parents=True, exist_ok=True)
    bak = BAK_DIR / ("content_%s.json" % time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(CONTENT, bak)
    print("גיבוי: %s" % bak)

    for j, c in cat_fix.items():
        arr[j]["category"] = c
    out = [i for j, i in enumerate(arr) if j not in drop]

    tmp = CONTENT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    check = json.loads(tmp.read_text(encoding="utf-8"))
    if len(check) != len(out):
        tmp.unlink(missing_ok=True)
        sys.exit("❌ הקובץ שנכתב אינו תקין — לא הוחלף")
    os.replace(tmp, CONTENT)
    v = bump()
    print("✅ בוצע. %d פריטים. גרסת תוכן: %s" % (len(out), v))
    print("   לשחזור:  python3 %s --restore" % sys.argv[0])


def bump():
    """קידום מונה גרסת התוכן.

    בלי זה האתר והאפליקציה ממשיכים להגיש מהמטמון שלהם לפי ETag,
    והתיקון לא נראה. קרה בדיוק כך בשחזור הקטלוג.
    """
    try:
        cur = int(VERSION_FILE.read_text().strip() or "0")
    except Exception:
        cur = 0
    VERSION_FILE.write_text(str(cur + 1), encoding="utf-8")
    return cur + 1


if __name__ == "__main__":
    main()
