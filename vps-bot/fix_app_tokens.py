#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_app_tokens — מחבר את zv_tokens.py (אימות אפליקציות בסגנון MSL) ל-main.py.
שורת חיבור אחת לפני FeedbackSendReq. מתחיל במצב monitor (רק רושם, לא חוסם).
    python3 fix_app_tokens.py [--check|--revert]   ·   אחרי: systemctl restart zovex-bot"""
import os, re, shutil, sys
PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
MARKER = "[fix_app_tokens]"
N = '''# [fix_app_tokens] אימות אפליקציות: /auth/session + חתימת בקשות + /admin/tokens
try:
    import zv_tokens as _zv_tokens
    _zv_tokens.install(api, check_panel_password, _client_ip, is_local_request)
except Exception as _e:   # כשל במודול לעולם לא מפיל את השרת
    print("zv_tokens לא נטען:", _e)'''
def _insert_tail(src, block):
    m = re.search(r'^if __name__ == ["\']__main__["\']\s*:', src, re.M)
    if m: return src[:m.start()] + block + "\n\n" + src[m.start():]
    return src.rstrip("\n") + "\n\n" + block + "\n"
def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read()
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        out = src.replace(N + "\n\n", "", 1).replace("\n\n" + N + "\n", "\n", 1).replace(N, "", 1); compile(out, "main.py", "exec")
        shutil.copy2(PATH, PATH + ".bak_tokens"); open(PATH, "w", encoding="utf-8").write(out); print("✓ שוחזר"); return 0
    if MARKER in src: print("✓ כבר מותקן"); return 0
    for need in ("def check_panel_password", "def _client_ip", "def is_local_request", "api = FastAPI"):
        assert need in src, f"חסר {need} ב-main.py"
    out = _insert_tail(src, N); compile(out, "main.py", "exec")
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    shutil.copy2(PATH, PATH + ".bak_tokens"); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", PATH + ".bak_tokens"); return 0
if __name__ == "__main__": sys.exit(main())
