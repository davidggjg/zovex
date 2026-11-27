#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_stall_trace — מכשיר הקלטה לתקיעות הזרמה (לא משנה התנהגות).

לכל ניסיון משיכת בלוק מטלגרם נרשם: בוט, DC, מזהה חיבור, מספר ניסיון,
זמן המתנה בשער הקצב, זמן הקריאה לטלגרם, ותוצאה (ok/timeout/conn/flood).
ניסיונות איטיים (>1ש) או כושלים נשמרים בטבעת של 2000, יחד עם מונים.
  GET /debug/stalls   (רק מהשרת עצמו, 127.0.0.1)  ← סיכום + אירועים אחרונים
STREAM_TRACE=0 מכבה. עלות: כמה מיקרו-שניות לבלוק.
    python3 fix_stall_trace.py [--check|--revert]   ·   אחרי: systemctl restart zovex-bot"""
import os, re, shutil, sys
PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
MARKER = "[fix_stall_trace]"

A0 = '''async def _get_block(session: Session, location, offset: int, limit: int,
                     owner: str = None, timeout: float = None) -> bytes:'''
N0 = '''# [fix_stall_trace] הקלטת ניסיונות משיכה
import collections as _st_col
STREAM_TRACE = os.environ.get("STREAM_TRACE", "1") not in ("0", "false", "no")
_st_ring = _st_col.deque(maxlen=2000)
_st_cnt = {"attempts": 0, "ok": 0, "timeout": 0, "conn": 0, "flood": 0, "slow_ok": 0,
           "retry_same_session": 0, "gate_wait_over_1s": 0,
           "lat": {"<0.5": 0, "0.5-1": 0, "1-2": 0, "2-5": 0, ">5": 0}}
_st_bot = {}

def _st_rec(session, owner, attempt, gate, call, outcome, err=""):
    if not STREAM_TRACE:
        return
    try:
        c = _st_cnt
        c["attempts"] += 1
        c[outcome] = c.get(outcome, 0) + 1
        if attempt > 0:
            c["retry_same_session"] += 1
        if gate > 1:
            c["gate_wait_over_1s"] += 1
        tot = gate + call
        b = "<0.5" if call < .5 else "0.5-1" if call < 1 else "1-2" if call < 2 else "2-5" if call < 5 else ">5"
        c["lat"][b] += 1
        if outcome == "ok" and tot > 1:
            c["slow_ok"] += 1
        bs = _st_bot.setdefault(owner or "?", {"n": 0, "bad": 0, "slow": 0})
        bs["n"] += 1
        if outcome != "ok": bs["bad"] += 1
        elif tot > 1: bs["slow"] += 1
        if outcome != "ok" or tot > 1:
            alive = None
            try:
                alive = _sess_alive(session)       # מ-fix_dead_sessions אם מותקן
            except Exception:
                pass
            _st_ring.append({"t": round(time.time(), 2), "bot": owner, "dc": getattr(session, "dc_id", None),
                             "sess": id(session) % 100000, "try": attempt, "gate": round(gate, 2),
                             "call": round(call, 2), "res": outcome, "alive": alive, "err": err[:80]})
    except Exception:
        pass

async def _get_block(session: Session, location, offset: int, limit: int,
                     owner: str = None, timeout: float = None) -> bytes:'''

A1 = '''            if owner:
                await _rate_gate(owner)
            # timeout חל רק על הקריאה לטלגרם'''
N1 = '''            _st_t0 = time.monotonic()                    # [fix_stall_trace]
            if owner:
                await _rate_gate(owner)
            _st_t1 = time.monotonic()
            # timeout חל רק על הקריאה לטלגרם'''

A2 = '''            r = await (asyncio.wait_for(call, timeout=timeout) if timeout else call)
            return getattr(r, "bytes", b"")
        except FloodWait as e:'''
N2 = '''            r = await (asyncio.wait_for(call, timeout=timeout) if timeout else call)
            _st_rec(session, owner, attempt, _st_t1 - _st_t0, time.monotonic() - _st_t1, "ok")
            return getattr(r, "bytes", b"")
        except FloodWait as e:
            _st_rec(session, owner, attempt, 0, 0, "flood", f"wait={e.value}")'''

A3 = '''        except (OSError, ConnectionError, EOFError, asyncio.TimeoutError) as e:
            last = e
            if attempt == BLOCK_RETRIES - 1:'''
N3 = '''        except (OSError, ConnectionError, EOFError, asyncio.TimeoutError) as e:
            last = e
            try:
                _st_rec(session, owner, attempt, _st_t1 - _st_t0, time.monotonic() - _st_t1,
                        "timeout" if isinstance(e, asyncio.TimeoutError) else "conn", type(e).__name__)
            except NameError:
                pass
            if attempt == BLOCK_RETRIES - 1:'''

TAIL = '''# [fix_stall_trace] נקודת קצה לסיכום (מקומית בלבד)
@api.get("/debug/stalls")
async def _debug_stalls(request: Request, last: int = 60):
    if not is_local_request(request):
        raise HTTPException(status_code=404)
    bots = sorted(_st_bot.items(), key=lambda kv: -(kv[1]["bad"] * 5 + kv[1]["slow"]))[:15]
    dcs = {}
    for e in _st_ring:
        k = str(e.get("dc")); d = dcs.setdefault(k, {"events": 0, "timeouts": 0, "dead": 0})
        d["events"] += 1
        if e["res"] == "timeout": d["timeouts"] += 1
        if e.get("alive") is False: d["dead"] += 1
    return {"counters": _st_cnt, "worst_bots": bots, "by_dc": dcs,
            "env": {"BLOCK_TIMEOUT": BLOCK_TIMEOUT, "BLOCK_RETRIES": BLOCK_RETRIES,
                    "MEDIA_CONNS": STREAM_MEDIA_CONNS, "PIPELINE_DEPTH": PIPELINE_DEPTH},
            "recent": list(_st_ring)[-max(1, min(last, 500)):]}'''

def _tail_insert(src, block):
    m = re.search(r"^if __name__ == [\"']__main__[\"']\s*:", src, re.M)
    if m: return src[:m.start()] + block + "\n\n" + src[m.start():]
    return src.rstrip("\n") + "\n\n" + block + "\n"

EDITS = [("הגדרות", A0, N0), ("שער קצב", A1, N1), ("הצלחה", A2, N2), ("כשל", A3, N3)]

def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read()
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        out = src.replace("\n\n" + TAIL + "\n", "\n", 1).replace(TAIL, "", 1)
        for _, a, n in EDITS: out = out.replace(n, a, 1)
        compile(out, "main.py", "exec")
        shutil.copy2(PATH, PATH + ".bak_trace"); open(PATH, "w", encoding="utf-8").write(out); print("✓ שוחזר"); return 0
    if MARKER in src: print("✓ כבר מותקן"); return 0
    out = src
    for nm, a, n in EDITS:
        c = out.count(a); assert c == 1, f"עוגן '{nm}': נמצא {c} — שלח לי: grep -n '_get_block\\|_rate_gate(owner)' {PATH}"
        out = out.replace(a, n, 1)
    out = _tail_insert(out, TAIL); compile(out, "main.py", "exec")
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    shutil.copy2(PATH, PATH + ".bak_trace"); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", PATH + ".bak_trace"); return 0
if __name__ == "__main__": sys.exit(main())
