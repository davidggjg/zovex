#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_app_tokens — מחבר את zv_tokens.py (אימות אפליקציות בסגנון MSL) ל-main.py.
שורת חיבור אחת לפני FeedbackSendReq. מתחיל במצב monitor (רק רושם, לא חוסם).
    python3 fix_app_tokens.py [--check|--revert]   ·   אחרי: systemctl restart zovex-bot"""
import os, shutil, sys
PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
MARKER = "[fix_app_tokens]"
A = "class FeedbackSendReq(BaseModel):"
N = '''# [fix_app_tokens] אימות אפליקציות: /auth/session + חתימת בקשות + /admin/tokens
try:
    import zv_tokens as _zv_tokens
    _zv_tokens.install(api, check_panel_password, _client_ip, is_local_request)
except Exception as _e:   # כשל במודול לעולם לא מפיל את השרת
    print("zv_tokens לא נטען:", _e)

class FeedbackSendReq(BaseModel):'''
def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read()
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        out = src.replace(N, A, 1); compile(out, "main.py", "exec")
        shutil.copy2(PATH, PATH + ".bak_tokens"); open(PATH, "w", encoding="utf-8").write(out); print("✓ שוחזר"); return 0
    if MARKER in src: print("✓ כבר מותקן"); return 0
    assert src.count(A) == 1, "עוגן FeedbackSendReq לא נמצא פעם אחת"
    out = src.replace(A, N, 1); compile(out, "main.py", "exec")
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    shutil.copy2(PATH, PATH + ".bak_tokens"); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", PATH + ".bak_tokens"); return 0
if __name__ == "__main__": sys.exit(main())
