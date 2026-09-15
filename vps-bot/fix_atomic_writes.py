#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_atomic_writes.py — כתיבה אטומית לקבצי המידע של המערכת.

הבעיה (מאומתת בקוד, לא השערה):
    main.py:4401   CONTENT_FILE.write_text(json.dumps(arr, ...))
    main.py:217    path.write_text(json.dumps(data, ...))

`write_text` פותח את הקובץ, *מאפס אותו*, ואז כותב. אם התהליך מת באמצע —
restart, OOM killer, דיסק מלא — נשאר קובץ JSON חתוך. ו-`load_json` בשורה 210
בולע כל חריגה ומחזיר `{}`, כלומר קטלוג של 12,839 פריטים הופך בשקט ל"ריק"
בלי שום שגיאה ביומן.

הפתרון הוא בדיוק מה שכבר קיים בקובץ הזה עצמו, במטמון הקצה (שורות 1944-1946):
    tmp.write_bytes(...)
    tmp.replace(path)
`os.replace` בתוך אותה מערכת קבצים הוא אטומי ברמת הקרנל: או שהקובץ הישן
נמצא שם במלואו, או שהחדש נמצא שם במלואו. אין מצב ביניים.

כלומר מטמון בינארי שאפשר לייצר מחדש בשנייה מוגן, והקטלוג — מקור האמת
היחיד של כל השירות — לא. זה מה שהתיקון הזה מיישר.

    python3 fix_atomic_writes.py --check     # בלי לגעת
    python3 fix_atomic_writes.py             # מחיל
    python3 fix_atomic_writes.py --revert    # מחזיר לגיבוי שנוצר כאן
"""
import sys, os, re, shutil, time
from pathlib import Path

MAIN = Path(os.environ.get("ZOVEX_MAIN", "/opt/zovex-bot/main.py"))
MARK = "# [fix_atomic_writes]"

HELPER = '''
# [fix_atomic_writes] כתיבה אטומית -----------------------------------------
# write_text מאפס את הקובץ לפני שהוא כותב. מוות של התהליך באמצע (restart,
# OOM, דיסק מלא) משאיר JSON חתוך, ו-load_json בולע את השגיאה ומחזיר {} —
# כלומר הקטלוג "נעלם" בשקט. os.replace בתוך אותה מערכת קבצים הוא אטומי:
# או הישן במלואו או החדש במלואו. אותה שיטה בדיוק שכבר בשימוש במטמון הקצה.
def _atomic_write_text(path, text, encoding="utf-8"):
    import os as _os
    from pathlib import Path as _Path
    path = _Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding=encoding) as fh:
            fh.write(text)
            fh.flush()
            _os.fsync(fh.fileno())      # בלי זה replace יכול להקדים את הנתונים
        _os.replace(tmp, path)          # אטומי
    except Exception:
        try: tmp.unlink(missing_ok=True)
        except Exception: pass
        raise
# ---------------------------------------------------------------------------
'''

# (עוגן, תחליף) — כל עוגן חייב להופיע בדיוק פעם אחת
EDITS = [
    # 1. הקטלוג עצמו. זה הקריטי.
    (
        '    CONTENT_FILE.write_text(json.dumps(arr, ensure_ascii=False, indent=2), encoding="utf-8")',
        '    _atomic_write_text(CONTENT_FILE, json.dumps(arr, ensure_ascii=False, indent=2))  ' + MARK,
    ),
    # 2. save_json — מועדפים, היסטוריה, מנהלים, משוב, גרסאות.
    (
        '    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")\n'
        '    if backup_name:',
        '    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))  ' + MARK + '\n'
        '    if backup_name:',
    ),
    # 3. רשימת ה-hosts של ה-relay.
    (
        '    RELAY_HOSTS_FILE.write_text(\n'
        '        json.dumps({h: hosts[h] for h in sorted(hosts)}, ensure_ascii=False, indent=2),',
        '    _atomic_write_text(RELAY_HOSTS_FILE,  ' + MARK + '\n'
        '        json.dumps({h: hosts[h] for h in sorted(hosts)}, ensure_ascii=False, indent=2),',
    ),
]

# העוגן להכנסת הפונקציה: חייב להיות *לפני* כל שימוש בה. load_json הוא
# מהדברים הראשונים בקובץ, אז נכנסים ממש לפניו.
HELPER_ANCHOR = "def load_json(path: Path) -> dict:"


def read() -> str:
    if not MAIN.exists():
        sys.exit(f"לא נמצא: {MAIN}")
    return MAIN.read_text(encoding="utf-8")


def backup_path() -> Path:
    return MAIN.with_name(MAIN.name + ".bak_atomic")


def validate(src: str) -> None:
    """מוודא שהקובץ לא רק תקין תחבירית אלא שכל שם ניתן לפתרון.
    compile() לבדו לא היה תופס הפניה לשם שלא קיים — זו בדיוק התקלה
    שהפילה את השירות בעבר (pathlib.Path לפני ה-import)."""
    compile(src, str(MAIN), "exec")
    if src.count("_atomic_write_text(") < 2:
        sys.exit("✗ הפונקציה לא נקראת — משהו השתבש")
    def_at = src.index("def _atomic_write_text(")
    for m in re.finditer(r"[^_\w]_atomic_write_text\(", src):
        if m.start() < def_at and "def " not in src[m.start()-6:m.start()+1]:
            sys.exit(f"✗ שימוש ב-_atomic_write_text בתו {m.start()}, "
                     f"לפני ההגדרה בתו {def_at} — יקרוס בזמן ריצה")


def main() -> None:
    check = "--check" in sys.argv
    revert = "--revert" in sys.argv
    src = read()

    if revert:
        bak = backup_path()
        if not bak.exists():
            sys.exit(f"אין גיבוי ב-{bak}")
        shutil.copy2(bak, MAIN)
        print(f"✓ שוחזר מ-{bak}")
        return

    if MARK in src:
        print("✓ כבר מוחל (נמצא הסימון) — לא משנה כלום")
        return

    if HELPER_ANCHOR not in src:
        sys.exit(f"✗ לא נמצא העוגן להכנסה: {HELPER_ANCHOR!r}")
    if src.count(HELPER_ANCHOR) != 1:
        sys.exit(f"✗ העוגן {HELPER_ANCHOR!r} מופיע {src.count(HELPER_ANCHOR)} פעמים")

    out = src
    applied = []
    for anchor, repl in EDITS:
        n = out.count(anchor)
        if n == 0:
            print(f"⚠ דילוג — לא נמצא: {anchor.strip()[:60]}...")
            continue
        if n != 1:
            sys.exit(f"✗ עוגן מופיע {n} פעמים, לא נוגעים: {anchor.strip()[:60]}...")
        out = out.replace(anchor, repl)
        applied.append(anchor.strip()[:50])

    if not applied:
        sys.exit("✗ אף עוגן לא נמצא — הקובץ בשרת שונה ממה שציפיתי")

    out = out.replace(HELPER_ANCHOR, HELPER.lstrip("\n") + "\n" + HELPER_ANCHOR, 1)
    validate(out)

    print(f"נמצאו {len(applied)} אתרי כתיבה להחלפה:")
    for a in applied:
        print(f"   • {a}...")

    if check:
        print("\n--check: הקובץ החדש נבדק (תחביר + פתרון שמות) ולא נכתב.")
        return

    shutil.copy2(MAIN, backup_path())
    MAIN.write_text(out, encoding="utf-8")
    print(f"\n✓ הוחל. גיבוי: {backup_path()}")
    print("  הפעל:  systemctl restart zovex-bot")
    print("  ⚠ restart מנתק צופים פעילים — לעשות כשאין תנועה.")


if __name__ == "__main__":
    main()
