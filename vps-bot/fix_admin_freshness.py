#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_admin_freshness — באנר "עודכן לפני X" בראש הפאנל, ו-no-cache.

## הבעיה שזה פותר

דוד החיל פאצ' ל-admin.html, רענן, וראה את הגרסה הישנה — בכמה דפדפנים.
הסיבה: /admin מוגש **בלי שום כותרת Cache-Control**, ולכן כל דפדפן רשאי
לשמור אותו לכמה שירצה. אותה הערה כבר קיימת ב-fix_html_cache.sh לגבי
index.html. התוצאה היא שאין שום דרך לדעת אם מה שרואים על המסך הוא הקובץ
שבשרת או עותק מלפני שעה — וזה בזבז מחזור עבודה שלם.

שני תיקונים, ושניהם נדרשים:

  • **no-store** על התשובה — הדפדפן לא ישמור אותה יותר. זה השורש.
  • **באנר** שאומר מתי admin.html עודכן בפועל. זה האימות: אם הבאנר מראה
    זמן ישן, זה עותק ישן — בלי לנחש ובלי לפתוח DevTools.

## למה גם באנר, אם no-store כבר פותר

כי no-store מטפל בדפדפן, אבל לא בשאר השרשרת — proxy, CDN, או דפדפן
שמתעלם. הבאנר מודד את **הקובץ עצמו** בצד השרת, ולכן הוא אומר את האמת
בלי קשר למי שמר מה בדרך. ובנוסף הוא שימושי בפני עצמו: אחרי כל פאצ'
רואים מיד שהוא נכנס.

## שעתיים

הבאנר מוצג רק אם הקובץ עודכן בשעתיים האחרונות, כבקשתו — אחרי זה הוא
נעלם מעצמו ולא הופך לרעש קבוע בממשק.

    python3 fix_admin_freshness.py --check
    python3 fix_admin_freshness.py
    python3 fix_admin_freshness.py --revert
ואחריו:  systemctl restart zovex-bot
"""
import argparse, ast, os, shutil, sys
from pathlib import Path

MAIN = Path(os.environ.get("ZOVEX_MAIN", "/opt/zovex-bot/main.py"))
BAK = MAIN.with_name(MAIN.name + ".bak_freshness")
MARK = "# [fix_admin_freshness]"

ANCHOR = '''    if ADMIN_HTML_FILE.exists():
        return HTMLResponse(ADMIN_HTML_FILE.read_text(encoding="utf-8"))
'''

INSERT = '''    if ADMIN_HTML_FILE.exists():
        ''' + MARK + '''
        # באנר "עודכן לפני X" + no-store. ראה fix_admin_freshness.py:
        # /admin הוגש בלי Cache-Control, דפדפנים שמרו אותו, ופאצ' שהוחל
        # נראה כאילו לא נכנס. הבאנר מודד את הקובץ בצד השרת ולכן אומר את
        # האמת גם אם משהו בדרך שמר עותק.
        _html = ADMIN_HTML_FILE.read_text(encoding="utf-8")
        try:
            _age = time.time() - ADMIN_HTML_FILE.stat().st_mtime
            if _age < 7200:                      # שעתיים, ואז נעלם מעצמו
                # דקות תמיד, ולא "לפני שעה": הבאנר מוצג רק עד שעתיים,
                # ו"לפני 90 דקות" מדויק יותר מ"לפני שעה" — וזה כל הערך
                # שלו. "לפני 1 דקות" הוא שגוי בעברית, ולכן יחיד בנפרד.
                _m = int(_age // 60)
                _when = ("עכשיו" if _m < 1 else
                         "לפני דקה" if _m == 1 else
                         "לפני %d דקות" % _m)
                _bar = (
                    '<div style="position:sticky;top:0;z-index:9999;'
                    'background:#1a7a3a;color:#fff;font:700 12px system-ui;'
                    'padding:7px 12px;text-align:center;direction:rtl">'
                    'הפאנל עודכן ' + _when + ' · אם זה נראה ישן — Ctrl+Shift+R'
                    '</div>')
                if "<body" in _html:
                    _i = _html.index(">", _html.index("<body")) + 1
                    _html = _html[:_i] + _bar + _html[_i:]
                else:
                    _html = _bar + _html
        except Exception:
            pass                                 # באנר הוא נוחות, לא תלות
        return HTMLResponse(_html, headers={
            "Cache-Control": "no-store, must-revalidate",
            "Pragma": "no-cache",
        })
'''


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True); raise


def validate(src: str, patched: bool = True) -> None:
    """חייב להתקמפל. ב-revert משחזרים מקור שאין בו את הסימון, ולכן שם
    בודקים רק קומפילציה."""
    compile(src, str(MAIN), "exec")
    tree = ast.parse(src)
    names = [n.name for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if "admin_page" not in names:
        sys.exit("אימות נכשל: admin_page נעלמה — לא כותב.")
    if patched and "ADMIN_HTML_FILE.stat()" not in src:
        sys.exit("אימות נכשל: ההזרקה לא נמצאת — לא כותב.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    if not MAIN.exists():
        sys.exit(f"לא נמצא {MAIN}. הגדר ZOVEX_MAIN אם הנתיב שונה.")
    src = MAIN.read_text(encoding="utf-8")

    if a.revert:
        if not BAK.exists():
            sys.exit(f"אין גיבוי ב-{BAK}")
        orig = BAK.read_text(encoding="utf-8")
        validate(orig, patched=False)
        atomic_write(MAIN, orig)
        print(f"✓ שוחזר מ-{BAK} (בית-בית)")
        print("  הרץ: systemctl restart zovex-bot")
        return

    if MARK in src:
        print("כבר מותקן. אין מה לעשות.")
        return

    # time נדרש להזרקה. הוא מיובא ב-main.py, אבל בודקים ולא מניחים.
    if not any(l.strip() in ("import time", "import time, os") or
               l.strip().startswith("import time")
               for l in src.splitlines()[:80]):
        print("אזהרה: לא זיהיתי 'import time' בראש הקובץ — בודק בכל הקובץ...")
        if "import time" not in src:
            sys.exit("אין import time ב-main.py — לא כותב (ההזרקה תלויה בו).")

    n = src.count(ANCHOR)
    if n != 1:
        sys.exit(f"העוגן נמצא {n} פעמים (ציפיתי 1) — הקוד השתנה, לא כותב.")

    new = src.replace(ANCHOR, INSERT, 1)
    if MARK not in new:
        sys.exit("ההוספה לא נתפסה — לא כותב.")
    validate(new)

    added = new.count("\n") - src.count("\n")
    print(f"עוגן: 1 · שורות שיתווספו: {added}")
    print("  באנר: מוצג רק אם admin.html עודכן בשעתיים האחרונות")
    print("  כותרות: Cache-Control: no-store — הדפדפן לא ישמור יותר")
    if a.check:
        print("--check: שום דבר לא נכתב. היעד:", MAIN)
        return

    shutil.copy2(MAIN, BAK)
    atomic_write(MAIN, new)
    if MARK not in MAIN.read_text(encoding="utf-8"):
        shutil.copy2(BAK, MAIN)
        sys.exit("הכתיבה לא אומתה — שוחזר.")
    print(f"✓ הוחל · גיבוי: {BAK}")
    print("  הרץ עכשיו: systemctl restart zovex-bot")
    print("  לביטול:    python3 fix_admin_freshness.py --revert")


if __name__ == "__main__":
    main()
