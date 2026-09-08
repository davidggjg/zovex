#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
תיקון נקודתי: gdown.download נכשל עם "unexpected keyword argument 'fuzzy'".

הפרמטר fuzzy לא קיים בגרסת gdown שרצה בשרת. במקום להסתמך עליו, מחלצים את
מזהה הקובץ מקישור ה-Drive ומשתמשים בכתובת הישירה uc?id=<id> — הצורה
הקלאסית של gdown, שעובדת בכל גרסה ומטפלת גם באישור "האם להוריד" של קבצים
גדולים.

מחליף רק את הפונקציה _blocking_drive_download ב-main.py.

    python3 fix_drive_gdown.py --check
    python3 fix_drive_gdown.py
    python3 fix_drive_gdown.py --revert
    python3 fix_drive_gdown.py --dir .
"""
import argparse, datetime, glob, os, pathlib, shutil, sys

OLD = '''def _blocking_drive_download(url: str, outdir: str):
    import gdown
    return gdown.download(url, output=outdir + "/", fuzzy=True, quiet=True)'''

NEW = '''def _blocking_drive_download(url: str, outdir: str):
    import re as _re, gdown
    # מחלצים את מזהה הקובץ מכל צורה נפוצה של קישור Drive ומשתמשים ב-uc?id=,
    # במקום fuzzy=True שלא קיים בכל גרסה. gdown מטפל באישור של קבצים גדולים.
    m = (_re.search(r"/d/([A-Za-z0-9_-]{20,})", url)
         or _re.search(r"[?&]id=([A-Za-z0-9_-]{20,})", url))
    src = f"https://drive.google.com/uc?id={m.group(1)}" if m else url
    return gdown.download(src, output=outdir + "/", quiet=True)'''

MARK = 'import re as _re, gdown'


def _fail(m):
    print(f"❌ {m}")
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/opt/zovex-bot")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    target = pathlib.Path(a.dir) / "main.py"
    if not target.exists():
        _fail(f"{target} לא נמצא")

    if a.revert:
        baks = sorted(glob.glob(str(target) + ".bak-gdown-*"))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], target)
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}")
        print("   צריך: systemctl restart zovex-bot")
        return

    src = target.read_text(encoding="utf-8")
    if MARK in src:
        print("✓ התיקון כבר מוחל. לא שונה כלום.")
        return
    if src.count(OLD) != 1:
        _fail(f"נמצאו {src.count(OLD)} התאמות לפונקציה, ציפינו ל-1 — הקובץ לא מה שציפינו לו.")

    out = src.replace(OLD, NEW)
    try:
        compile(out, str(target), "exec")
    except SyntaxError as e:
        _fail(f"לא עובר קומפילציה: {e}")

    if a.check:
        print("✓ הפונקציה נמצאה והתוצאה עוברת קומפילציה. לא שונה כלום (--check).")
        return

    bak = f"{target}.bak-gdown-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(target, bak)
    target.write_text(out, encoding="utf-8")
    print(f"✓ הוחל. גיבוי: {os.path.basename(bak)}")
    print("   צריך: systemctl restart zovex-bot")


if __name__ == "__main__":
    main()
