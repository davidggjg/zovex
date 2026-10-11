#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_ninjago_season_split — נינג'גו הועלה עם 5 מספרי עונה גולמיים (1,2,3,
16,17) במקום 3 עונות נקיות — נראה "לא מסודר" (דיווח צופה: עונה 1 מכילה
רק 3 פרקים).

## מה נמצא (אחרי fix_ninjago_naruto_merge, שכבר הפריד את נארוטו)

60 הפרקים האמיתיים של נינג'גו: עליית הדרקונים נושאים season_number
מתוך {1, 2, 3, 16, 17}. דוד אישר: אמורות להיות 3 עונות, 20 פרקים כל
אחת (60 בסך הכל — תואם בדיוק).

נבדק מול episode_number בפועל:

    season=1   ⊇ {1,2,4}                      (3 פרקים)
    season=16  ⊇ {3,5,6,7,8,9,10,...,20}       (17 פרקים)
    1 ∪ 16 = {1..20} *בדיוק*, 1 ∩ 16 = {} — חפיפה אפס.

    season=2   ⊇ {11,12,...,20}                (10 פרקים)
    season=17  ⊇ {1,2,...,10}                  (10 פרקים)
    2 ∪ 17 = {1..20} *בדיוק*, 2 ∩ 17 = {} — חפיפה אפס.

    season=3   = {1..20} כבר שלמה בפני עצמה.

גם נבדק: בין כל 60 הפרקים, אין אף file_unique_id כפול — אלה קבצים
שונים לגמרי, לא אותו פרק שהועלה פעמיים תחת שני מספרים. כלומר: עונה
אחת אמיתית בת 20 פרקים התפצלה לשני "עונות" גולמיות כי חלק מהפרקים
הועלו/כותרו בנפרד ממקור אחר של אותה עונה ממש — לא טעות בנתונים,
רק כותרת לא עקבית בקבצים המקוריים.

## מה משתנה

season_number: 1→1, 16→1 (מתמזגות לעונה 1, 20 פרקים). 2→2, 17→2
(מתמזגות לעונה 2, 20 פרקים). 3 נשארת 3, בלי שינוי. סדר העונות נקבע
לפי channel_msg_id — הקבוצה שהועלתה ראשונה (1+16) היא עונה 1, השנייה
(2+17) עונה 2, השלישית (3) עונה 3.

**לא נוגעים**: id של כל פרק (מפתח ראשי, אותו נימוק כמו ב-
fix_ninjago_naruto_merge — גם אם ה-id עצמו מכיל "s16e9" והעונה
בפועל הפכה ל-1, זה קוסמטי בלבד; season_number הוא השדה שבאמת קובע
את הקיבוץ בבורר העונות). שום פרק של נארוטו (series_name שונה).

## בטיחות

לפני כל כתיבה: נבדק מחדש, על הנתונים האמיתיים, שהחפיפה עדיין אפס
ושאין file_unique_id כפול — אחרת עוצר ולא מנחש. גיבוי כפול (קובץ
ייעודי + עותק ב-content_backups/), כתיבה אטומית, העלאת מונה הגרסה.

    python3 fix_ninjago_season_split.py --check
    python3 fix_ninjago_season_split.py
    python3 fix_ninjago_season_split.py --revert

אין צורך ב-restart.
"""
import json
import os
import sys
import time
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/opt/zovex-bot/data"))
PATH = DATA_DIR / "content.json"
VERSION_FILE = DATA_DIR / "content_version.txt"
BAK = DATA_DIR / "content.json.bak_ninjago_season_split"

SERIES = "נינג'גו: עליית הדרקונים"
# (עונה-יעד נקייה) -> {מספרי העונה הגולמיים שמתמזגים לתוכה}
MERGE_MAP = {1: {1, 16}, 2: {2, 17}, 3: {3}}
RAW_SEASONS = {raw for raws in MERGE_MAP.values() for raw in raws}


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


def validate_merge(data: list) -> dict:
    """בודק מחדש שההנחות עדיין נכונות: לכל זוג עונות גולמיות שמתמזגות
    יחד — איחוד episode_number הוא בדיוק 1..20, חפיפה אפס, ואין
    file_unique_id כפול בכל הקבוצה. עוצר בלי לכתוב אם משהו לא תואם."""
    items = [e for e in data if e.get("series_name") == SERIES]
    if not items:
        sys.exit(f"✗ אין אף פריט עם series_name={SERIES!r}. לא נוגע בכלום.")

    unexpected_seasons = {e.get("season_number") for e in items} - RAW_SEASONS
    if unexpected_seasons:
        sys.exit(f"✗ נמצאו מספרי עונה לא-צפויים {unexpected_seasons} — "
                  "המצב השתנה מאז שנבדק. לא נוגע בכלום.")

    fuids = [e.get("file_unique_id") for e in items]
    if len(fuids) != len(set(fuids)):
        sys.exit("✗ נמצא file_unique_id כפול — זה עלול להיות מיזוג שגוי. עוצר.")

    plan = {}  # id -> עונה חדשה
    for clean, raws in MERGE_MAP.items():
        group = [e for e in items if e.get("season_number") in raws]
        eps = [e.get("episode_number") for e in group]
        if sorted(eps) != list(range(1, 21)):
            sys.exit(f"✗ עונות גולמיות {raws} לא מכסות בדיוק 1..20 "
                      f"(בפועל: {sorted(set(eps))}) — עוצר, לא מנחש.")
        if len(eps) != len(set(eps)):
            sys.exit(f"✗ עונות גולמיות {raws} — יש episode_number כפול "
                      "בתוך הקבוצה. עוצר.")
        for e in group:
            plan[e.get("id")] = clean

    print(f"סדרה: {SERIES!r} — {len(items)} פרקים.")
    for clean, raws in sorted(MERGE_MAP.items()):
        n = sum(1 for v in plan.values() if v == clean)
        print(f"  → עונה {clean}: ממוזגת מעונות גולמיות {sorted(raws)} ({n} פרקים).")
    return plan


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
    raw_text = PATH.read_text(encoding="utf-8")
    data = json.loads(raw_text)

    plan = validate_merge(data)
    already = sum(1 for e in data if e.get("id") in plan
                  and e.get("season_number") == plan[e.get("id")])
    to_change = len(plan) - already
    print(f"צריך לשנות season_number ב-{to_change} פרקים "
          f"({already} כבר עם המספר הנכון — עונה 3 לא זזה).")

    if "--check" in sys.argv:
        print()
        print("--check: שום דבר לא נכתב.")
        return

    changed = 0
    for e in data:
        new_season = plan.get(e.get("id"))
        if new_season is not None and e.get("season_number") != new_season:
            e["season_number"] = new_season
            changed += 1
    if changed != to_change:
        sys.exit(f"✗ מספר השינויים בפועל ({changed}) לא תואם למתוכנן "
                  f"({to_change}) — עוצר בלי לכתוב.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BAK.write_text(raw_text, encoding="utf-8")
    try:
        bdir = DATA_DIR / "content_backups"
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / f"content_{int(time.time())}.json").write_text(raw_text, encoding="utf-8")
    except Exception as e:
        print(f"⚠ גיבוי בתיקיית content_backups נכשל (ממשיכים, הגיבוי הייעודי קיים): {e}")

    atomic_write_text(PATH, json.dumps(data, ensure_ascii=False, indent=2))
    try:
        v = int(VERSION_FILE.read_text(encoding="utf-8").strip() or "0")
    except Exception:
        v = 0
    VERSION_FILE.write_text(str(v + 1), encoding="utf-8")

    print()
    print(f"✓ מוזגו {changed} פרקים לשלוש עונות נקיות (1,2,3 × 20). גיבוי: {BAK}")
    print("אין צורך ב-restart. רענן את הפאנל/האתר/האפליקציה.")
    print(f"לביטול: python3 {Path(__file__).name} --revert")


if __name__ == "__main__":
    main()
