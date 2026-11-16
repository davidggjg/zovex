#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_smart_uploads — העלאות חכמות מהבוט (זיהוי סדרה + חלון בחירה + פוסטר TMDB).
מכניס <script id="zv-smart-uploads"> (מ-panel_smart_uploads.js) לפני ‎</body>‎.
עוטף את addSeriesUploads/loadUploads הקיימים בלי לשנות אותם. החלה חוזרת מעדכנת.
    PANEL=... JS=... python3 patch_smart_uploads.py [--check|--revert]"""
import os, re, shutil, sys
PATH = os.environ.get("PANEL", "/opt/zovex-bot/admin.html")
JS = os.environ.get("JS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel_smart_uploads.js"))
RE = re.compile(r'\n?<script id="zv-smart-uploads">.*?</script>\n?', re.S)
def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read()
    if arg == "--revert":
        out = RE.sub("", src)
        if out == src: print("אין מה לשחזר"); return 0
        shutil.copy2(PATH, PATH + ".bak_smart"); open(PATH, "w", encoding="utf-8").write(out); print("✓ הוסר"); return 0
    js = open(JS, encoding="utf-8").read(); assert "</script>" not in js
    base = RE.sub("", src); assert base.count("</body>") == 1, "‎</body>‎ לא נמצא פעם אחת"
    assert "function addSeriesUploads" in base and "function loadUploads" in base, "הפאנל לא מכיל את פונקציות ההעלאות"
    out = base.replace("</body>", f'\n<script id="zv-smart-uploads">\n{js}</script>\n</body>', 1)
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    shutil.copy2(PATH, PATH + ".bak_smart"); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ העלאות חכמות הוחלו" + (" (עודכן)" if base != src else "")); return 0
if __name__ == "__main__": sys.exit(main())
