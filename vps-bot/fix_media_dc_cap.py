#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_media_dc_cap — תקרת חיבורים לכל DC + פסק זמן לפתיחת חיבור.

## נמדד בשרת החי
  64 חיבורים פעילים ל-149.154.164.250 (DC4 media) ו-393 תקועים ב-SYN-SENT
  אליו; 42,741 "Connection failed" בשעה. סרט ששמור ב-DC4 לא נפתח כלל.
  64 עגול = תקרה של טלגרם לחיבורים מכתובת אחת. 40 בוטים × בריכה + חיבורי
  גידור עברו אותה.
## שורש הלולאה
  ‎_make_media_session‎ קורא ‎session.start()‎ בלי פסק זמן, ו-Session.start של
  Pyrogram מנסה שוב בלולאה אינסופית בלי השהיה על OSError.
## התיקון
  1. STREAM_MEDIA_DC_CAP (48): לא נפתח חיבור חדש ל-DC שכבר בתקרה — הבקשה
     עוברת לבוט שכבר מחובר (המסלול הקיים כשבריכה ריקה).
  2. STREAM_MEDIA_CONNECT_TIMEOUT (15ש) על פתיחת חיבור; בביטול ה-Session
     נעצר ומשחרר את ה-socket.
  3. בוט הגיבוי של הגידור רק מבריכה קיימת — אין בנייה מול הצופה.
  4. GET /stream/media-caps — חיבורים לכל DC ומונים.
דורש fix_pinned_hedge.   MAIN_PY=... python3 fix_media_dc_cap.py [--check|--revert]
"""
import os, re, shutil, sys
PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
MARKER = "[fix_media_dc_cap]"
SIG = "async def _make_media_session(client, dc_id: int, _retry: bool = True):"

E_HOME = ("        await session.start()\n        return session\n",
          "        try:\n            await session.start()\n"
          "        except asyncio.CancelledError:   # [fix_media_dc_cap] משחרר socket\n"
          "            await _stop_quiet(session)\n            raise\n"
          "        return session\n")
E_FOREIGN = ("    try:\n        await session.start()\n    except Exception:\n",
             "    try:\n        await session.start()\n"
             "    except asyncio.CancelledError:   # [fix_media_dc_cap] משחרר socket\n"
             "        await _stop_quiet(session)\n        raise\n"
             "    except Exception:\n")

WRAPPER = r'''

# ── [fix_media_dc_cap] תקרה לכל DC + פסק זמן לפתיחת חיבור ───────────────────
MEDIA_DC_CAP = int(os.environ.get("STREAM_MEDIA_DC_CAP", "48"))
MEDIA_CONNECT_TIMEOUT = float(os.environ.get("STREAM_MEDIA_CONNECT_TIMEOUT", "15"))
_media_connecting: dict = {}
_media_cap_stats = {"refused": 0, "timeouts": 0}


async def _stop_quiet(sess):
    try:
        await sess.stop()
    except Exception:
        pass


def _dc_session_count(dc_id: int) -> int:
    live = sum(len(e.get("pool") or []) for (o, d), e in list(_media_sessions.items())
               if d == dc_id)
    return live + _media_connecting.get(dc_id, 0)


_make_media_session_raw = _make_media_session


async def _make_media_session(client, dc_id: int, *a, **kw):
    """כמו המקור, אבל: לא מעל MEDIA_DC_CAP חיבורים ל-DC, ולא יותר מ-
    MEDIA_CONNECT_TIMEOUT שניות לפתיחה. כשל עולה כחריגה רגילה, ומי שקרא
    (בניית בריכה) כבר יודע לטפל בה: בריכה ריקה → בוט אחר."""
    if _dc_session_count(dc_id) >= MEDIA_DC_CAP:
        _media_cap_stats["refused"] += 1
        raise RuntimeError(f"תקרת חיבורים ל-DC{dc_id} ({MEDIA_DC_CAP})")
    _media_connecting[dc_id] = _media_connecting.get(dc_id, 0) + 1
    try:
        return await asyncio.wait_for(_make_media_session_raw(client, dc_id, *a, **kw),
                                      MEDIA_CONNECT_TIMEOUT)
    except asyncio.TimeoutError:
        _media_cap_stats["timeouts"] += 1
        raise RuntimeError(f"חיבור ל-DC{dc_id} לא נפתח תוך {MEDIA_CONNECT_TIMEOUT:.0f}ש")
    finally:
        _media_connecting[dc_id] = max(0, _media_connecting.get(dc_id, 1) - 1)


@api.get("/stream/media-caps")
async def stream_media_caps():
    """[fix_media_dc_cap] חיבורי media לכל DC מול התקרה."""
    dcs = sorted({d for (o, d) in list(_media_sessions.keys())} | set(_media_connecting))
    return {"cap": MEDIA_DC_CAP, "connect_timeout": MEDIA_CONNECT_TIMEOUT,
            "per_dc": {f"DC{d}": _dc_session_count(d) for d in dcs}, **_media_cap_stats}
'''

E_BACKUP = ('    sessions, _g = await get_media_session_pool_gen(\n'
            '        bot["client"], bot["name"], dc_id, 1, block=False)\n'
            '    if not sessions:\n'
            '        sessions, _g = await get_media_session_pool_gen(\n'
            '            bot["client"], bot["name"], dc_id, 1, block=True)\n',
            '    # [fix_media_dc_cap] רק בריכה קיימת: בנייה מול הצופה פותחת חיבורים\n'
            '    # חדשים ל-DC שאולי כבר בתקרה. בריכה חסרה נבנית ברקע לפעם הבאה.\n'
            '    sessions, _g = await get_media_session_pool_gen(\n'
            '        bot["client"], bot["name"], dc_id, 1, block=False)\n')


def apply(src):
    if MARKER in src:
        print("✓ כבר מותקן"); return src
    assert "[fix_pinned_hedge]" in src, "fix_pinned_hedge לא מותקן — התקן אותו קודם"
    assert src.count(SIG) == 1, f"_make_media_session הסופי: נמצא {src.count(SIG)}"
    s = src.index(SIG)
    m = re.compile(r"\n(?=(?:@api\.|async def |def |class |[A-Za-z_][A-Za-z_0-9]* *=|# ──)\S)").search(src, s + len(SIG))
    e = m.start() if m else len(src)
    body = src[s:e]
    for name, (a, n) in (("start ביתי", E_HOME), ("start זר", E_FOREIGN)):
        assert body.count(a) == 1, f"עוגן '{name}': נמצא {body.count(a)}"
        body = body.replace(a, n, 1)
    out = src[:s] + body + WRAPPER + src[e:]
    assert out.count(E_BACKUP[0]) == 1, "עוגן _pin_backup לא נמצא"
    out = out.replace(E_BACKUP[0], E_BACKUP[1], 1)
    compile(out, "main.py", "exec")
    return out


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read(); bak = PATH + ".bak_media_dc_cap"
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        shutil.copy2(bak, PATH); print("✓ שוחזר"); return 0
    out = apply(src)
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    if MARKER in src: return 0
    shutil.copy2(PATH, bak); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", bak); return 0


if __name__ == "__main__": sys.exit(main())
