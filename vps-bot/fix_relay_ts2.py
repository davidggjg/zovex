#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_relay_ts2 — מצב TS: חיבור אחד לספק, בלי נפילה לזרם גולמי.

נמדד על השרת החי: בדיקת החיות של fix_relay_ts נכשלה ב-ReadError, ובאותה
שנייה המסלול הרגיל קיבל 200 מאותו ספק. חשבון IPTV מסחרי מוגבל לרוב לחיבור
אחד: הבדיקה + ffmpeg = שני חיבורים, והנפילה למסלול הרגיל תפסה את החיבור
היחיד עם זרם TS שהנגן לא מנגן — ושוב הבדיקה נכשלה. לולאה.

  · במצב TS אין בדיקה מקדימה — ffmpeg מתחבר פעם אחת, ומועד היעד הקיים
    (סגמנט ראשון) הוא שמגלה כשל, עם stderr של ffmpeg ביומן.
  · במצב TS כשל מחזיר 502 ולא מפנה לזרם הגולמי.
ערוצים רגילים (בלי ‎/__ts.m3u8‎) — בדיוק כמו קודם.

דורש fix_relay_ts.   MAIN_PY=... python3 fix_relay_ts2.py [--check|--revert]
"""
import os, re, shutil, sys
PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
MARKER = "[fix_relay_ts2]"

A1 = '    if _is_ts:\n        return await _hls_ts_alive(host, _upath)\n'
N1 = ('    if _is_ts:\n'
      '        # [fix_relay_ts2] בלי בדיקה מקדימה: חשבון מוגבל לחיבור אחד, ובדיקה\n'
      '        # + ffmpeg הם שניים. ffmpeg מתחבר פעם אחת; מועד היעד מגלה כשל.\n'
      '        return True, ""\n')

HELPER = '''def _hls_fix_fallback(host: str, path: str, status_code: int = 302):
    """[fix_relay_ts2] נפילה מהמרה שנכשלה. ערוץ רגיל → המסלול הרגיל, כמו
    תמיד. זרם TS → 502: הזרם הגולמי לא מתנגן בנגן ממילא, ובקשה אליו הייתה
    תופסת את החיבור היחיד של החשבון ומפילה את הניסיון הבא."""
    upath, is_ts = _hls_src_path(path)
    if is_ts:
        raise HTTPException(502, "hls_fix: זרם ה-TS לא הומר — ראה hls_fix ביומן")
    return RedirectResponse(f"/hls-relay/{host}/{upath}", status_code=status_code)


'''
OLD_REDIR = 'RedirectResponse(f"/hls-relay/{host}/{_hls_src_path(path)[0]}"'
NEW_REDIR = '_hls_fix_fallback(host, path'


def apply(src):
    if MARKER in src:
        print("✓ כבר מותקן"); return src
    assert "[fix_relay_ts]" in src, "fix_relay_ts לא מותקן — התקן אותו קודם"
    assert src.count(A1) == 1, "עוגן בדיקת החיות לא נמצא"
    out = src.replace(A1, N1, 1)
    n = out.count(OLD_REDIR)
    assert n == 3, f"ציפינו ל-3 הפניות במסלול ההמרה, נמצאו {n}"
    out = out.replace(OLD_REDIR, NEW_REDIR)
    h = '@api.get("/hls-relay/_fix/{host}/{path:path}")'
    assert out.count(h) == 1
    out = out.replace(h, HELPER + h, 1)
    compile(out, "main.py", "exec")
    return out


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read(); bak = PATH + ".bak_relay_ts2"
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        shutil.copy2(bak, PATH); print("✓ שוחזר"); return 0
    out = apply(src)
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    if MARKER in src: return 0
    shutil.copy2(PATH, bak); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", bak); return 0


if __name__ == "__main__": sys.exit(main())
