#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_ninjago_naruto_merge — נינג'גו ואז נארוטו הועלו עם אותו שם סדרה,
וכל הפרקים משני התכנים התמזגו לכרטיס אחד.

## מה נמצא (על content.json החי, 2026-10-11)

288 פרקים תחת series_name="נינג'גו: עליית הדרקונים", tmdb_id=0 לכולם —
העלאה ידנית/drive, לא דרך tmdb_search, ולכן בלי זיהוי TMDB בכלל.

שני אותות בלתי-תלויים לגמרי זה בזה, ששניהם מצביעים בדיוק על אותו
גבול, בלי אף חריגה אחת:

1. channel_msg_id: 60 הפריטים הראשונים (18798–18839) — ה-id שלהם
   נושא "nyng-gv" (התעתיק של "נינג'גו"). 228 הפריטים הבאים
   (18858–19085) — "nrvtv" (התעתיק של "נארוטו") או id גנרי.

2. category: כבר נקבעה נכון לכל פריט *בנפרד* בזמן ההעלאה, בלי שום
   קשר ל-series_name המשותף — 60/60 "סדרות לילדים" (נינג'גו האמיתי),
   228/228 "אנימה" (נארוטו האמיתי). מסכימה במדויק עם האות הראשון.

(גם מספרי העונות תומכים: 220 מתוך ה-228 הם season_number=1 — תואם את
220 הפרקים של נארוטו המקורי כסדרה רציפה; נינג'גו האמיתי מסתכם
ב-60 פרקים דרך 5 עונות (1,2,3,16,17) — סביר למיני-סדרה.)

## מה משתנה

ל-228 הפריטים (category="אנימה" תחת ה-series_name המשותף):
series_name ו-title → "נארוטו", custom_slug → תעתיק עקבי ("nrvtv",
אותה שיטה שה-id-ים הקיימים כבר השתמשו בה — כל הפרקים חולקים slug
סדרה אחד, זה תקין ומתוכנן, לא הבאג). thumbnail_url מנוקה: היה הפוסטר
של נינג'גו מודבק על תוכן של נארוטו — ריק עדיף על תמונה שגויה; הלקוח
כבר מטפל בפריט בלי תמונה (ראה buildSeriesMap/MovieCard). תוצאה צפויה:
כרטיס "נארוטו" יופיע בלי פוסטר עד שמישהו יקבע אחד ידנית בפאנל —
זה מכוון, לא תקלה חדשה.

**לא נוגעים**: id של כל פריט (מפתח ראשי; שינוי שלו היה מנתק favorites/
history/progress — גם אם לא סביר על תוכן בן כמה שעות). 60 פריטי
"סדרות לילדים" (נינג'גו האמיתי) — כבר נכונים, לא נוגעים בהם כלל.

## בטיחות

לפני כל כתיבה: שני האותות (channel_msg_id, category) נבדקים מחדש
ועל מנת להסכים *במדויק* — אחרת עוצר בלי לגעת בכלום, לא מנחש. גיבוי
כפול: קובץ ‎.bak‎ ייעודי לביטול מיידי, ועוד עותק בתיקיית
content_backups/ (אותו מקום שבו save_content כבר שומר). כתיבה
אטומית, והעלאת מונה הגרסה כדי שלקוחות ירעננו.

    python3 fix_ninjago_naruto_merge.py --check
    python3 fix_ninjago_naruto_merge.py
    python3 fix_ninjago_naruto_merge.py --revert

אין צורך ב-restart — content.json נקרא מהדיסק לפי mtime+size, ומתבטל
אוטומטית כשהקובץ משתנה.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/opt/zovex-bot/data"))
PATH = DATA_DIR / "content.json"
VERSION_FILE = DATA_DIR / "content_version.txt"
BAK = DATA_DIR / "content.json.bak_ninjago_naruto_merge"

OLD_SERIES = "נינג'גו: עליית הדרקונים"
NEW_SERIES = "נארוטו"
TARGET_CATEGORY = "אנימה"
OTHER_CATEGORY = "סדרות לילדים"
MSG_ID_BOUNDARY = 18858  # ← גבול מאומת מול /content/lite החי, ראה תיעוד למעלה

# אותו תעתיק בדיוק כמו ב-main.py (_HE_TRANSLIT/_slug_base), כדי שה-slug
# החדש יהיה עקבי עם כל slug אחר בקטלוג.
_HE_TRANSLIT = {
    "א": "", "ב": "b", "ג": "g", "ד": "d", "ה": "h", "ו": "v", "ז": "z", "ח": "ch",
    "ט": "t", "י": "y", "כ": "k", "ך": "k", "ל": "l", "מ": "m", "ם": "m", "נ": "n",
    "ן": "n", "ס": "s", "ע": "", "פ": "p", "ף": "p", "צ": "tz", "ץ": "tz", "ק": "k",
    "ר": "r", "ש": "sh", "ת": "t",
}


def _translit_he(s):
    return "".join(_HE_TRANSLIT.get(c, c) for c in (s or ""))


def _slug_base(title):
    src = _translit_he(title) if re.search(r"[א-ת]", title or "") else (title or "")
    return re.sub(r"[^a-zA-Z0-9]+", "-", src).strip("-").lower()


NEW_SLUG = _slug_base(NEW_SERIES)


def atomic_write_text(path: Path, text: str, encoding="utf-8"):
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding=encoding) as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def validate_split(data: list) -> list:
    """בודק ששני האותות עדיין מסכימים *במדויק* על אותה קבוצת פריטים.
    לא מתקן כלום אם המצב השתנה מאז שנבדק — עוצר ומדווח."""
    same_series = [e for e in data if e.get("series_name") == OLD_SERIES]
    if not same_series:
        sys.exit(f"✗ אין אף פריט עם series_name={OLD_SERIES!r}. "
                  "כבר תוקן בעבר, או שהשם השתנה. לא נוגע בכלום.")

    by_msgid = {e.get("id") for e in same_series
                if (e.get("channel_msg_id") or 0) >= MSG_ID_BOUNDARY}
    by_cat = {e.get("id") for e in same_series if e.get("category") == TARGET_CATEGORY}
    if by_msgid != by_cat:
        only_msgid = by_msgid - by_cat
        only_cat = by_cat - by_msgid
        sys.exit("✗ שני האותות כבר לא מסכימים (השתנה משהו מאז שנבדק) — "
                  f"{len(only_msgid)} רק לפי msg_id, {len(only_cat)} רק לפי "
                  "category. לא נוגע בכלום, תבדוק ידנית.")

    unexpected = [e for e in same_series
                  if e.get("category") not in (TARGET_CATEGORY, OTHER_CATEGORY)]
    if unexpected:
        sys.exit(f"✗ {len(unexpected)} פריטים עם category לא-צפוי "
                  f"({sorted({e.get('category') for e in unexpected})}) — עוצר.")

    targets = [e for e in same_series if e.get("id") in by_cat]
    kept = len(same_series) - len(targets)
    print(f"קבוצה: {len(same_series)} פריטים תחת {OLD_SERIES!r}.")
    print(f"  → {kept} פריטים ({OTHER_CATEGORY}) נשארים — נינג'גו האמיתי, לא נוגעים.")
    print(f"  → {len(targets)} פריטים ({TARGET_CATEGORY}) מתוקנים ל-{NEW_SERIES!r}.")
    return targets


def main():
    if "--revert" in sys.argv:
        if not BAK.exists():
            sys.exit(f"✗ אין גיבוי ב-{BAK}")
        atomic_write_text(PATH, BAK.read_text(encoding="utf-8"))
        try:
            v = int(VERSION_FILE.read_text(encoding="utf-8").strip() or "0")
            VERSION_FILE.write_text(str(v + 1), encoding="utf-8")
        except Exception:
            pass
        print(f"✓ שוחזר מ-{BAK}")
        return

    if not PATH.exists():
        sys.exit(f"✗ לא נמצא {PATH} (אפשר DATA_DIR=...)")
    raw = PATH.read_text(encoding="utf-8")
    data = json.loads(raw)

    targets = validate_split(data)
    with_bad_thumb = sum(1 for e in targets if e.get("thumbnail_url"))
    print(f"custom_slug חדש: {NEW_SLUG!r}")
    print(f"thumbnail_url ינוקה ב-{with_bad_thumb} פריטים (היה הפוסטר של נינג'גו).")
    print("דוגמה (3 ראשונים):", [e.get("id") for e in targets[:3]])

    if "--check" in sys.argv:
        print()
        print("--check: שום דבר לא נכתב.")
        return

    target_ids = {e.get("id") for e in targets}
    changed = 0
    for e in data:
        if e.get("id") in target_ids:
            e["series_name"] = NEW_SERIES
            e["title"] = NEW_SERIES
            e["custom_slug"] = NEW_SLUG
            e["thumbnail_url"] = ""
            changed += 1
    if changed != len(targets):
        sys.exit(f"✗ מספר השינויים בפועל ({changed}) לא תואם למתוכנן "
                  f"({len(targets)}) — עוצר בלי לכתוב.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BAK.write_text(raw, encoding="utf-8")
    try:
        bdir = DATA_DIR / "content_backups"
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / f"content_{int(time.time())}.json").write_text(raw, encoding="utf-8")
    except Exception as e:
        print(f"⚠ גיבוי בתיקיית content_backups נכשל (ממשיכים, הגיבוי הייעודי קיים): {e}")

    atomic_write_text(PATH, json.dumps(data, ensure_ascii=False, indent=2))
    try:
        v = int(VERSION_FILE.read_text(encoding="utf-8").strip() or "0")
    except Exception:
        v = 0
    VERSION_FILE.write_text(str(v + 1), encoding="utf-8")

    print()
    print(f"✓ תוקנו {changed} פרקים ל-{NEW_SERIES!r}. גיבוי: {BAK}")
    print("אין צורך ב-restart. רענן את הפאנל/האתר/האפליקציה.")
    print(f"לביטול: python3 {Path(__file__).name} --revert")


if __name__ == "__main__":
    main()
