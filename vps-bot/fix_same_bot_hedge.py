#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_same_bot_hedge — גידור בלוקים בתוך אותו בוט (Hedged Requests).

ראיות (zv-stalls בשרת החי): 6.5% מהבלוקים נתקעים 5ש על חיבור *חי*, ומיד
אחר כך אותו חיבור עונה תוך ~1.1ש. כלומר טלגרם "בולעת" בקשה בודדת. שער הקצב
לא אשם (0), חיבורים מתים לא אשמים (alive=True). 88% מהבלוקים חוזרים <2ש.

השיטה ("The Tail at Scale", Google 2013): בלוק שלא חזר תוך
STREAM_SAME_HEDGE_DELAY (2.0ש ≈ האחוזון ה-88-90) נשלח במקביל על חיבור
*אחר שכבר פתוח* של אותו בוט; הראשון שמחזיר בייטים מנצח, השני מבוטל.
  · אפס חיבורים חדשים, אפס בוטים נוספים (בניגוד לגידור הקודם שבנה
    חיבורים לבוט אחר וגרם לסחרור).
  · upload.getFile קריאה בלבד — כפילות לא מזיקה. עובר בשער הקצב של הבוט.
  · תקציב: לכל היותר 20% מהבלוקים (+5) מגודרים. מעבר לזה — כמו קודם.
  · STREAM_SAME_HEDGE_DELAY=0 מכבה. מונים ב-zv-stalls (hedge_*).
    python3 fix_same_bot_hedge.py [--check|--revert]   ·   אחרי: systemctl restart zovex-bot"""
import os, shutil, sys
PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
MARKER = "[fix_same_bot_hedge]"

A0 = "async def _pinned_stream(chat_id, message_id, start, end, tried):"
N0 = '''# [fix_same_bot_hedge] גידור בלוק על חיבור אחר של אותו בוט
SAME_HEDGE_DELAY = float(os.environ.get("STREAM_SAME_HEDGE_DELAY", "2.0"))
SAME_HEDGE_SHARE = float(os.environ.get("STREAM_SAME_HEDGE_SHARE", "0.2"))
_sh = {"blocks": 0, "launched": 0, "won": 0, "lost": 0, "no_alt": 0, "over_budget": 0}

def _sh_alive(s):
    f = globals().get("_sess_alive")
    try:
        return f(s) if f else True
    except Exception:
        return True

def _sh_cnt(k):
    _sh[k] = _sh.get(k, 0) + 1
    c = globals().get("_st_cnt")
    if isinstance(c, dict):
        c["hedge_" + k] = c.get("hedge_" + k, 0) + 1

async def _hedged_get(sessions, i, location, offset, limit, owner, timeout):
    n = len(sessions)
    pick = globals().get("_pick_alive")
    primary = pick(sessions, i) if pick else sessions[i % n]
    _sh["blocks"] += 1
    t1 = asyncio.create_task(_get_block(primary, location, offset, limit, owner, timeout))
    if SAME_HEDGE_DELAY <= 0 or n < 2:
        return await t1
    done, _ = await asyncio.wait({t1}, timeout=SAME_HEDGE_DELAY)
    if done:
        return t1.result()
    if _sh["launched"] >= SAME_HEDGE_SHARE * _sh["blocks"] + 5:
        _sh_cnt("over_budget")
        return await t1
    alt = None
    for k in range(1, n):
        s = sessions[(i + k) % n]
        if s is not primary and _sh_alive(s):
            alt = s
            break
    if alt is None:
        _sh_cnt("no_alt")
        return await t1
    _sh_cnt("launched")
    t2 = asyncio.create_task(_get_block(alt, location, offset, limit, owner, timeout))
    pending = {t1, t2}
    first_err = None
    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                if t.cancelled():
                    continue
                e = t.exception()
                if e is None and t.result():
                    _sh_cnt("won" if t is t2 else "lost")
                    return t.result()
                if e is not None and first_err is None:
                    first_err = e
        if first_err is not None:
            raise first_err
        return t1.result() if not t1.cancelled() else b""
    finally:
        for t in (t1, t2):
            if not t.done():
                t.cancel()
                t.add_done_callback(lambda x: x.cancelled() or x.exception())

async def _pinned_stream(chat_id, message_id, start, end, tried):'''

VARIANTS = [
    ('''            return asyncio.create_task(_get_block(
                _pick_alive(sessions, i), location,   # [fix_dead_sessions]
                first + i * MEDIA_CHUNK, MEDIA_CHUNK, name, BLOCK_TIMEOUT))''',),
    ('''            return asyncio.create_task(_get_block(
                sessions[i % len(sessions)], location,
                first + i * MEDIA_CHUNK, MEDIA_CHUNK, name, BLOCK_TIMEOUT))''',),
]
N1 = '''            return asyncio.create_task(_hedged_get(          # [fix_same_bot_hedge]
                sessions, i, location,
                first + i * MEDIA_CHUNK, MEDIA_CHUNK, name, BLOCK_TIMEOUT))'''

def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read()
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        orig = VARIANTS[0][0] if "def _pick_alive" in src else VARIANTS[1][0]
        out = src.replace(N1, orig, 1).replace(N0, A0, 1); compile(out, "main.py", "exec")
        shutil.copy2(PATH, PATH + ".bak_samehedge"); open(PATH, "w", encoding="utf-8").write(out); print("✓ שוחזר"); return 0
    if MARKER in src: print("✓ כבר מותקן"); return 0
    assert src.count(A0) == 1, "עוגן _pinned_stream לא נמצא"
    hit = [v[0] for v in VARIANTS if src.count(v[0]) == 1]
    assert hit, f"עוגן שיגור הבלוק לא נמצא — שלח לי: grep -n -A2 'create_task(_get_block' {PATH}"
    out = src.replace(hit[0], N1, 1).replace(A0, N0, 1); compile(out, "main.py", "exec")
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    shutil.copy2(PATH, PATH + ".bak_samehedge"); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", PATH + ".bak_samehedge"); return 0
if __name__ == "__main__": sys.exit(main())
