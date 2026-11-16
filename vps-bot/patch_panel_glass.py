#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_panel_glass — שכבת עיצוב Apple (זכוכית) לפאנל הניהול.
מכניס <style id="zv-glass"> (מהקובץ panel_glass.css) לפני ‎</head>‎. CSS בלבד:
אין נגיעה ב-HTML ובפונקציות. חוזר על עצמו בבטחה: החלה שנייה מחליפה את השכבה
בגרסה החדשה. admin.html בלבד — אין restart.
    PANEL=... CSS=... python3 patch_panel_glass.py [--check|--revert]"""
import os, re, shutil, sys
PATH = os.environ.get("PANEL", "/opt/zovex-bot/admin.html")
CSS = os.environ.get("CSS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel_glass.css"))
BLOCK_RE = re.compile(r'\n?<meta name="color-scheme"[^>]*>\n<style id="zv-glass">.*?</style>\n?', re.S)

def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read()
    if arg == "--revert":
        out = BLOCK_RE.sub("", src)
        if out == src: print("אין מה לשחזר"); return 0
        shutil.copy2(PATH, PATH + ".bak_glass"); open(PATH, "w", encoding="utf-8").write(out)
        print("✓ השכבה הוסרה"); return 0
    css = open(CSS, encoding="utf-8").read()
    assert "</style>" not in css, "CSS לא תקין"
    base = BLOCK_RE.sub("", src)
    assert base.count("</head>") == 1, "‎</head>‎ לא נמצא פעם אחת"
    block = f'\n<meta name="color-scheme" content="light">\n<style id="zv-glass">\n{css}</style>\n'
    out = base.replace("</head>", block + "</head>", 1)
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    shutil.copy2(PATH, PATH + ".bak_glass"); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ שכבת העיצוב הוחלה" + (" (עודכנה)" if base != src else "")); return 0

if __name__ == "__main__": sys.exit(main())
