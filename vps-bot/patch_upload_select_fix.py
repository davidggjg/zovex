#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_upload_select_fix — יישור הצ'קבוקס בבחירת הממתינים.

הגרסה הראשונה הגדילה את הצ'קבוקס עם transform:scale(1.4) — שמגדיל אותו
ויזואלית בלי לתפוס מקום אמיתי בשורה, ולכן הוא "נדבק לצד" וחופף. כאן:
  · מוסיפים מחלקת CSS .uplsel (גודל קבוע, יישור נקי, accent-color).
  · מורידים את ה-style המוטבע משני הצ'קבוקסים.

העריכה של פריט בודד לא הושפעה ולא משתנה — הכפתורים "ערוך"/"ערוך+הוסף"/
"הוסף סדרה שלמה" עובדים בדיוק כמו קודם. admin.html בלבד, אין restart.

מיועד לשרת שכבר הוחל עליו patch_upload_select.py. אם הקובץ כבר מתוקן
(יש בו .uplsel) — יוצא בלי לגעת.

    python3 patch_upload_select_fix.py --check
    python3 patch_upload_select_fix.py
    python3 patch_upload_select_fix.py --revert
"""
import os, shutil, sys

PATH = os.environ.get("PANEL", "/opt/zovex-bot/admin.html")
MARKER = ".uplsel {"

A_CSS = r'''  .item .meta .s { color:#86868b; font-size:12px; }'''
N_CSS = r'''  .item .meta .s { color:#86868b; font-size:12px; }
  .uplsel { width:20px; height:20px; flex:none; margin:0; accent-color:#5e5ce6; cursor:pointer; }'''

A_STY = r''' style="margin-left:8px;transform:scale(1.4)" title="סמן לאיחוד ידני">'''
N_STY = r''' title="סמן לאיחוד ידני">'''


def apply(src: str) -> str:
    if MARKER in src:
        print("✓ כבר מתוקן"); return src
    assert A_CSS in src, "לא נמצא עוגן ה-CSS (.item .meta .s)"
    out = src.replace(A_CSS, N_CSS, 1)
    nsty = out.count(A_STY)
    assert nsty == 2, f"ציפינו ל-2 צ'קבוקסים לתיקון, נמצאו {nsty} — ודא ש-patch_upload_select הוחל"
    out = out.replace(A_STY, N_STY)
    return out


def revert(src: str) -> str:
    out = src.replace(N_STY, A_STY)          # מחזיר את ה-style המוטבע
    out = out.replace(N_CSS, A_CSS, 1)       # מסיר את מחלקת ה-CSS
    return out


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read()
    if arg == "--revert":
        if MARKER not in src:
            print("אין מה לשחזר"); return 0
        shutil.copy2(PATH, PATH + ".bak_upload_fix")
        open(PATH, "w", encoding="utf-8").write(revert(src))
        print("✓ שוחזר"); return 0
    out = apply(src)
    if arg == "--check":
        print("✓ בדיקה עברה"); return 0
    if MARKER in src:
        return 0
    shutil.copy2(PATH, PATH + ".bak_upload_fix")
    open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", PATH + ".bak_upload_fix"); return 0


if __name__ == "__main__":
    sys.exit(main())
