#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_slugs — כתובות באנגלית אמיתית במקום תעתיק עברי.

## מה נמדד

מתוך 13,192 פריטים, **4,251** נושאים סלאג שהוא תעתיק אות-אות מעברית
ולא תרגום:

    hmchtrt   ← המחתרת          (באמת: Underground)
    htyrvn    ← הטירון          (באמת: The Rookie)
    hbvrr     ← הבורר           (באמת: The Arbitrator)
    kvkb-ksf  ← כוכב כסף        (באמת: Silver Star)
    drgvn-bvl ← דרגון בול       (באמת: Dragon Ball)

זה שליש מהקטלוג עם כתובות חסרות משמעות. המקור הוא כפתור "תרגום אוטומטי
לכתובות URL" בפאנל, ששאל מודל שפה על "slug" וקיבל תעתיק — כלומר כלי
קיים שעושה את הדבר הלא נכון, לא באג מסתורי.

## למה זה לא צריך AI

ל-3,158 מהם **כבר יש `en_title` נכון מ-TMDB**. הכתובת היא המרה
טריוויאלית שלו, ולכן הכלי הזה דטרמיניסטי לגמרי: אפס קריאות רשת, אפס
מפתחות, אפס עלות, ואפס סיכון להזיה. מה שאין לו en_title פשוט לא נוגעים
בו — הוא ימתין לשלב ה-TMDB/ג'מיני, ואז הרצה חוזרת תתפוס אותו.

## מה הוא לא עושה

סלאג תקין לא משתנה. `dragon-ball-super` נשאר כמו שהוא. הכלי נוגע רק
במה שחסר או מתועתק, כי שינוי כתובת תקינה שובר קישורים קיימים בלי תמורה.

## אזהרה אמיתית

שינוי סלאג **משנה את הכתובת**. מי שקישר ל-‎/hmchtrt יקבל 404. במקרה
הזה זה זניח — אף אחד לא מקשר לג'יבריש — אבל אחרי ההרצה צריך לבנות
מחדש את העמודים המוקדמים ואת ה-sitemap, אחרת הם יצביעו לכתובות ישנות.

    python3 fix_slugs.py --check
    python3 fix_slugs.py
    python3 fix_slugs.py --revert
"""
import argparse, importlib.util, json, os, re, shutil, sys, time
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load_enrich():
    """CONTENT/VERSION ו-atomic_write מגיעים מ-tmdb_enrich, כמו בשאר הכלים.
    כאן לא נדרש מפתח TMDB — עובדים רק ממה שכבר בקטלוג."""
    p = os.path.join(_HERE, "tmdb_enrich.py")
    if not os.path.exists(p):
        sys.exit(f"לא נמצא {p} — הכלי הזה מייבא ממנו.")
    spec = importlib.util.spec_from_file_location("_tmdb_enrich", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


VOWELS = set("aeiou")


def is_transliteration(slug: str) -> bool:
    """סלאג שנוצר מתעתיק עברי, ולא מתרגום.

    הסימן הוא היעדר תנועות: עברית נכתבת בלי ניקוד, ולכן תעתיק אות-אות
    מייצר רצפי עיצורים (hmchtrt, drgvn-bvl). מילה אנגלית אמיתית כמעט
    תמיד נושאת תנועות. הסף 0.18 נבחר אחרי מדידה על הקטלוג המלא: הוא
    תופס את התעתיקים ולא נוגע בשמות אנגליים קצרים.

    מתחת ל-4 אותיות לא מכריעים — ‎'tv'‎ או ‎'gt'‎ הם קיצורים לגיטימיים.
    """
    if not slug:
        return False
    letters = [c for c in slug.lower() if c.isalpha()]
    if len(letters) < 4:
        return False
    return sum(c in VOWELS for c in letters) / len(letters) < 0.18


def slugify(title: str) -> str:
    """שם באנגלית → כתובת. חייב להיות בטוח ל-URL, כי הוא **הופך** לכתובת:
    האתר משתמש ב-custom_slug מילה במילה."""
    if not title:
        return ""
    s = title.lower()
    # גרש נמחק ולא הופך למקף: Tom Clancy's → tom-clancys, לא tom-clancy-s
    s = s.replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def group_key(it: dict):
    """סדרה = מפתח אחד לכל הפרקים, כדי שלכל הסדרה תהיה כתובת אחת.
    פריט בודד = המזהה שלו."""
    sn = (it.get("series_name") or "").strip()
    return ("series", sn) if sn else ("item", it.get("id"))


def pick_en_title(items: list) -> str:
    """ה-en_title של הקבוצה. ברוב ולא בראשון: פרק חריג עם שם שגוי לא
    אמור לקבוע את הכתובת של סדרה שלמה."""
    names = [(m.get("en_title") or "").strip() for m in items]
    names = [n for n in names if n]
    if not names:
        return ""
    return Counter(names).most_common(1)[0][0]


def plan(items: list):
    """מחזיר (changes, skipped, stat). changes = [(item, old, new)]"""
    groups = {}
    for it in items:
        if it.get("is_live"):
            continue
        groups.setdefault(group_key(it), []).append(it)

    changes, skipped, stat = [], [], Counter()

    # מעבר ראשון: מי בכלל ישתנה. זה חייב להיקבע לפני חישוב הכתובות
    # התפוסות, כי "תפוס" הוא **כל סלאג של פריט שלא נוגעים בו** — ולא רק
    # סלאג תקין. ריצה יבשה על הקטלוג האמיתי תפסה את זה: ערוץ חי בשם
    # 'hop' נותר עם הסלאג שלו, וסרט קיבל את אותה כתובת ודרס אותו.
    # אותו דבר לקבוצה שמדולגת מחוסר en_title — הסלאג המתועתק שלה נשאר,
    # ולכן הוא תפוס בדיוק כמו כל אחר.
    fixable = {}
    for key, g in sorted(groups.items(), key=lambda kv: str(kv[0])):
        cur = [(m.get("custom_slug") or "").strip() for m in g]
        if not any((not s) or is_transliteration(s) for s in cur):
            stat["קבוצות שהסלאג בהן תקין"] += 1
            continue
        en = pick_en_title(g)
        if not en:
            stat["אין en_title — ממתין ל-TMDB"] += 1
            skipped.append((key, "אין en_title"))
            continue
        base = slugify(en)
        if not base:
            stat["en_title לא הניב כתובת"] += 1
            skipped.append((key, f"en_title={en!r} לא ניתן להמרה"))
            continue
        fixable[key] = base

    # כל סלאג שיישאר בקטלוג אחרי התיקון — כולל שידורים חיים וכולל
    # קבוצות שדולגו — חוסם כתובת חדשה.
    taken = set()
    for it in items:
        if group_key(it) in fixable and not it.get("is_live"):
            continue
        s = (it.get("custom_slug") or "").strip()
        if s:
            taken.add(s)

    for key, base in fixable.items():
        g = groups[key]

        # התנגשות: שם אנגלי זהה לשתי יצירות שונות. מפרידים בשנה, ואם גם
        # היא זהה או חסרה — במונה. עדיף כתובת ארוכה מכתובת שדורסת אחרת.
        new = base
        if new in taken:
            yr = next((m.get("year") for m in g if m.get("year")), None)
            if yr:
                new = f"{base}-{yr}"
            n = 2
            while new in taken:
                new = f"{base}-{n}"
                n += 1
            stat["התנגשויות שפורקו"] += 1
        taken.add(new)

        for m in g:
            old = (m.get("custom_slug") or "").strip()
            if old != new:
                changes.append((m, old, new))
        stat["קבוצות שתוקנו"] += 1

    stat["פריטים שישתנו"] = len(changes)
    return changes, skipped, stat


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--show", type=int, default=25, help="כמה דוגמאות להציג")
    a = ap.parse_args()

    E = _load_enrich()
    CONTENT, VERSION = E.CONTENT, E.VERSION
    BACKUP = CONTENT.with_name("content.json.bak_slugs")

    if a.revert:
        if not BACKUP.exists():
            sys.exit(f"אין גיבוי ב-{BACKUP}")
        shutil.copy2(BACKUP, CONTENT)
        print(f"✓ שוחזר מ-{BACKUP}")
        print("  צריך לבנות מחדש את האתר — הכתובות חזרו לקודמות.")
        return

    if not CONTENT.exists():
        sys.exit(f"לא נמצא: {CONTENT}")
    items = json.loads(CONTENT.read_text(encoding="utf-8"))
    changes, skipped, stat = plan(items)

    print(f'סה"כ פריטים: {len(items)}')
    for k, v in stat.most_common():
        print(f"  {k}: {v}")

    if changes:
        print("\n── דוגמאות ──")
        seen = set()
        for m, old, new in changes:
            k = m.get("series_name") or m.get("title")
            if k in seen:
                continue
            seen.add(k)
            print(f"  {old or '(ריק)':26} → {new:34} [{k}]")
            if len(seen) >= a.show:
                break

    if not changes:
        print("\nאין מה לשנות.")
        return

    if a.check:
        print(f"\n--check: לא נכתב כלום. {len(changes)} פריטים היו משתנים.")
        return

    shutil.copy2(CONTENT, BACKUP)
    for m, _old, new in changes:
        m["custom_slug"] = new
    E.atomic_write(CONTENT, json.dumps(items, ensure_ascii=False, indent=2))
    try:
        v = int(VERSION.read_text().strip()) + 1 if VERSION.exists() else 1
    except Exception:
        v = int(time.time())
    E.atomic_write(VERSION, str(v))
    print(f"\n✓ עודכנו {len(changes)} פריטים · גיבוי: {BACKUP} · גרסה {v}")
    print("  חשוב: הכתובות השתנו. צריך לבנות ולפרוס מחדש את האתר,")
    print("  אחרת העמודים המוקדמים וה-sitemap מצביעים לכתובות הישנות.")
    print("  לביטול: python3 fix_slugs.py --revert")


if __name__ == "__main__":
    main()
