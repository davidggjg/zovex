#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_panel_links — טאב קישורים בפאנל (panel_links.js).
מכניס <script id="zv-links"> לפני ‎</body>‎. מוסיף טאב "קישורים"; עוטף את showTab.
    PANEL=... JS=... python3 patch_panel_links.py [--check|--revert]"""
import os, re, shutil, sys
PATH = os.environ.get("PANEL", "/opt/zovex-bot/admin.html")
JS = os.environ.get("JS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel_links.js"))
RE = re.compile(r'\n?<script id="zv-links">.*?</script>\n?', re.S)
def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read()
    if arg == "--revert":
        out = RE.sub("", src)
        if out == src: print("אין מה לשחזר"); return 0
        shutil.copy2(PATH, PATH + ".bak_links"); open(PATH, "w", encoding="utf-8").write(out); print("✓ הוסר"); return 0
    js = open(JS, encoding="utf-8").read(); assert "</script>" not in js
    base = RE.sub("", src); assert base.count("</body>") == 1
    assert "function showTab" in base and "function mutate" in base, "הפאנל לא מכיל showTab/mutate"
    out = base.replace("</body>", f'\n<script id="zv-links">\n{js}</script>\n</body>', 1)
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    shutil.copy2(PATH, PATH + ".bak_links"); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ טאב הקישורים הוחל" + (" (עודכן)" if base != src else "")); return 0
if __name__ == "__main__": sys.exit(main())
