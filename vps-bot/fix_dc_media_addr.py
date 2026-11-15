#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_dc_media_addr — הורדות מ-DC4 דרך הכתובת הרגילה שלו במקום כתובת ה-media.

## נמדד בשרת החי
  ‎149.154.164.250‎ (כתובת ה-media של DC4) לא עונה גם בחיבור TCP ישיר מהשרת,
  שעה שלמה, בעוד ‎149.154.167.91‎ (הכתובת הרגילה של DC4) וכל השאר עונות.
  טלגרם חסם את הכתובת שלנו מול נקודת הכניסה הזו אחרי סערת חיבורים. רוב
  הקבצים בערוץ ב-DC4, ולכן כמעט שום סרט לא נפתח.
## התיקון
  Pyrogram בוחר כתובת לפי טבלה (DataCenter.PROD_MEDIA). DC שמוסר ממנה
  משתמש בכתובת הרגילה שלו — שירות לגיטימי של טלגרם להורדות, אותו DC, אותם
  חשבונות. נשלט ב-TG_MEDIA_DC_SKIP (ברירת מחדל "4"; ריק = כבוי).

    MAIN_PY=... python3 fix_dc_media_addr.py [--check|--revert]
"""
import os, shutil, sys
PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
MARKER = "[fix_dc_media_addr]"
ANCHOR = 'logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")\n'
INSERT = ANCHOR + r'''
# ── [fix_dc_media_addr] DC שכתובת ה-media שלו חסומה → הכתובת הרגילה ─────────
try:
    from pyrogram.session.internals.data_center import DataCenter as _TgDC
    for _d in [int(x) for x in os.environ.get("TG_MEDIA_DC_SKIP", "4").split(",") if x.strip()]:
        _TgDC.PROD_MEDIA.pop(_d, None)
        getattr(_TgDC, "PROD_IPV6_MEDIA", {}).pop(_d, None)
    logging.getLogger(__name__).info("media DCs: %s", dict(_TgDC.PROD_MEDIA))
except Exception as _e:
    logging.getLogger(__name__).warning("fix_dc_media_addr: %s", _e)
'''


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read(); bak = PATH + ".bak_dc_media_addr"
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        shutil.copy2(bak, PATH); print("✓ שוחזר"); return 0
    if MARKER in src: print("✓ כבר מותקן"); return 0
    assert src.count(ANCHOR) == 1, f"עוגן לא נמצא ({src.count(ANCHOR)})"
    assert src.index(ANCHOR) > src.index("import os"), "os לא מיובא לפני העוגן"
    out = src.replace(ANCHOR, INSERT, 1)
    compile(out, "main.py", "exec")
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    shutil.copy2(PATH, bak); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", bak); return 0


if __name__ == "__main__": sys.exit(main())
