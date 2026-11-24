#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_dead_sessions — לא לשלוח בקשות לחיבור media מת.

נמדד בשרת: כל קפיצה לוקחת 0.6–1.8ש או ~5.7ש, כמעט כלום באמצע. ביומן:
"Send exception … TCPTransport closed=True … handler is closed" חוזר על
*אותם* חיבורים כל 5 שניות. כלומר הבריכה מחזיקה חיבור שמת (או שהספרייה
באמצע restart שלו), הסבב sessions[i % n] שולח אליו בלוק, והבלוק ממתין את
כל STREAM_BLOCK_TIMEOUT לפני ניסיון חוזר. ה-cooldown נגד סחרור (120ש)
מונע הפלה של הבריכה, כך שהחיבור המת נשאר ואוכל 5ש מבקשה אחרי בקשה.

התיקון: בכל שיגור בלוק בוחרים חיבור *חי* מהבריכה (writer פתוח, הסשן
started). לא בונים חיבורים ולא מפילים בריכות — אפס סיכון לסופת חיבורים.
אם אי אפשר לקבוע (גרסת ספרייה אחרת) — מתנהג בדיוק כמו קודם.
STREAM_SKIP_DEAD=0 מכבה.
    python3 fix_dead_sessions.py [--check|--revert]   ·   אחרי: systemctl restart zovex-bot"""
import os, shutil, sys
PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
MARKER = "[fix_dead_sessions]"

A1 = '''BLOCK_TIMEOUT = float(os.environ.get("STREAM_BLOCK_TIMEOUT", "12"))'''
N1 = '''BLOCK_TIMEOUT = float(os.environ.get("STREAM_BLOCK_TIMEOUT", "12"))

# [fix_dead_sessions] בחירת חיבור media חי בלבד
STREAM_SKIP_DEAD = os.environ.get("STREAM_SKIP_DEAD", "1") not in ("0", "false", "no")
_dead_skips = {"skipped": 0, "all_dead": 0}

def _sess_alive(s) -> bool:
    """False רק כשבטוח שהחיבור מת/באמצע restart. כל ספק ⇒ True (כמו קודם)."""
    try:
        ev = getattr(s, "is_started", None)
        if ev is not None and hasattr(ev, "is_set") and not ev.is_set():
            return False
        conn = getattr(s, "connection", None)
        proto = getattr(conn, "protocol", None) if conn is not None else None
        w = getattr(proto, "writer", None) if proto is not None else None
        if w is not None and hasattr(w, "is_closing") and w.is_closing():
            return False
        return True
    except Exception:
        return True

def _pick_alive(sessions, i):
    n = len(sessions)
    if not STREAM_SKIP_DEAD or n <= 1:
        return sessions[i % n]
    for k in range(n):
        s = sessions[(i + k) % n]
        if _sess_alive(s):
            if k:
                _dead_skips["skipped"] += 1
            return s
    _dead_skips["all_dead"] += 1
    return sessions[i % n]'''

A2 = '''                sessions[i % len(sessions)], location,'''
N2 = '''                _pick_alive(sessions, i), location,   # [fix_dead_sessions]'''

def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read()
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        out = src.replace(N2, A2, 1).replace(N1, A1, 1); compile(out, "main.py", "exec")
        shutil.copy2(PATH, PATH + ".bak_deadsess"); open(PATH, "w", encoding="utf-8").write(out); print("✓ שוחזר"); return 0
    if MARKER in src: print("✓ כבר מותקן"); return 0
    for nm, a in (("BLOCK_TIMEOUT", A1), ("סבב חיבורים", A2)):
        c = src.count(a); assert c == 1, f"עוגן '{nm}': נמצא {c} פעמים — שלח לי: grep -n 'BLOCK_TIMEOUT\\|i % len(sessions)' {PATH}"
    out = src.replace(A1, N1, 1).replace(A2, N2, 1); compile(out, "main.py", "exec")
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    shutil.copy2(PATH, PATH + ".bak_deadsess"); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", PATH + ".bak_deadsess"); return 0
if __name__ == "__main__": sys.exit(main())
