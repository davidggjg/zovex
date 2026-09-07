#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בודק אם נשארו קבצים זמניים של העלאות, ומנקה אותם.

## מה הקוד באמת עושה היום

המחיקה עצמה תקינה. ב-_saved_send היא יושבת ב-finally, כלומר גם העלאה
שנכשלה מוחקת אחריה:

    finally:
        path.unlink(missing_ok=True)

אבל יש שני חורים, ושניהם רלוונטיים בדיוק להיום:

1. **הטאטוא רץ רק כשמתחילה העלאה חדשה.** אם הועלה קובץ ונשארה שארית,
   היא תישאר שם עד שמישהו יעלה משהו אחר. בלי העלאה נוספת — לנצח.

2. **הפעלה מחדש באמצע העלאה מייתמת את הקובץ.** רשימת המשימות יושבת
   בזיכרון התהליך בלבד, ולכן אחרי restart אין מי שיקרא ל-_saved_send,
   ואין מי שימחק. היום הפעלנו מחדש שלוש פעמים.

ובנוסף, `SAVED_STALE_SEC = 6 שעות` — גם כשהטאטוא כן רץ, שארית טרייה
יותר מזה לא נמחקת.

מדובר בקבצים של גיגה־בייטים בודדים כל אחד, על אותו דיסק שמגיש את האתר.

    python3 check_saved_tmp.py             # רק מראה. לא נוגע בכלום
    python3 check_saved_tmp.py --clean     # מוחק שאריות מעל שעתיים
    python3 check_saved_tmp.py --clean --older 30m
    python3 check_saved_tmp.py --clean --force   # גם קבצים טריים
"""
import argparse, os, pathlib, shutil, sys, time

DATA_DIR = pathlib.Path(os.environ.get("DATA_DIR", "/opt/zovex-bot/data"))
TMP = DATA_DIR / "saved_uploads"

# מתחת לזה לא מוחקים בלי --force: קובץ שנכתב עכשיו הוא כמעט תמיד העלאה
# שרצה ברגע זה, ומחיקה שלו הורגת אותה.
FRESH_SEC = 30 * 60


def human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.1f}{u}" if u != "B" else f"{n}B"
        n /= 1024


def age(sec):
    if sec < 60:
        return f"{int(sec)} שנ׳"
    if sec < 3600:
        return f"{int(sec // 60)} דק׳"
    if sec < 86400:
        return f"{sec / 3600:.1f} שע׳"
    return f"{sec / 86400:.1f} ימים"


def parse_older(s):
    s = s.strip().lower()
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if s and s[-1] in mult:
        return float(s[:-1]) * mult[s[-1]]
    return float(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--older", default="2h",
                    help="גיל מינימלי למחיקה. 30m / 2h / 1d")
    ap.add_argument("--force", action="store_true",
                    help="למחוק גם קבצים טריים — יהרוג העלאה שרצה")
    a = ap.parse_args()

    if not TMP.exists():
        print(f"התיקייה {TMP} לא קיימת — אין שאריות.")
        return

    du = shutil.disk_usage(str(TMP))
    print(f"תיקייה: {TMP}")
    print(f"דיסק:   {human(du.used)} בשימוש · {human(du.free)} פנוי "
          f"מתוך {human(du.total)}\n")

    now = time.time()
    files = []
    for p in sorted(TMP.glob("*")):
        try:
            st = p.stat()
        except OSError:
            continue
        files.append((p, st.st_size, now - st.st_mtime))

    if not files:
        print("✓ אין שום קובץ זמני. הכול נוקה.")
        return

    limit = parse_older(a.older)
    total = sum(f[1] for f in files)
    print(f"{len(files)} קבצים · {human(total)} סה\"כ\n")
    todo = []
    for p, size, old in files:
        fresh = old < FRESH_SEC
        pick = old >= limit and (not fresh or a.force)
        if fresh and not a.force:
            tag = "◀ נכתב עכשיו — כנראה העלאה פעילה"
        elif old < limit:
            tag = f"(צעיר מ-{a.older})"
        else:
            tag = "← שארית"
        if pick:
            todo.append((p, size))
        print(f"  {human(size):>9}  לפני {age(old):<10} {p.name[:52]}  {tag}")

    if not a.clean:
        print()
        if todo:
            print(f"למחיקה: {len(todo)} קבצים, {human(sum(s for _, s in todo))}")
            print("להרצה:  python3 check_saved_tmp.py --clean")
        else:
            print("אין מה למחוק לפי הכללים הנוכחיים.")
        return

    if not todo:
        print("\nאין מה למחוק.")
        return

    freed = 0
    print()
    for p, size in todo:
        try:
            p.unlink()
            freed += size
            print(f"  ✓ נמחק {p.name[:60]}")
        except OSError as e:
            print(f"  ✗ {p.name[:50]}: {e}")
    print(f"\nשוחררו {human(freed)}.")


if __name__ == "__main__":
    main()
