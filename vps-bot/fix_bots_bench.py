#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_bots_bench — בדיקת מהירות אמיתית לכל בוט בבריכה (localhost בלבד).

המספר בפאנל הוא ממוצע של (בייטים שהוגשו / משך הצפייה) — כלומר קצב הצפייה
של הצופה ולא יכולת הבוט, ו-0 על כל כשל. כאן כל בוט, *בתורו*, מושך N מגה
מסרט אמיתי דרך חיבור media יחיד, ונמדדת המהירות שלו בפועל, זמן ההכנה
(שליפת ההודעה + חיבור), ומצבו: חנוק/כשלים/שגיאת טלגרם.

בוט אחד בכל פעם עם הפסקה קצרה — לא פותחים עשרות חיבורים בבת אחת.
    GET /stream/bots-bench?chat=-100…&msg=123&mb=4      (localhost בלבד)
    MAIN_PY=... python3 fix_bots_bench.py [--check|--revert]
"""
import os, shutil, sys
PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
MARKER = "[fix_bots_bench]"
ANCHOR = '@api.get("/stream/tune")'
CODE = r'''# ── [fix_bots_bench] בדיקת מהירות אמיתית לכל בוט ─────────────────────────────
@api.get("/stream/bots-bench")
async def stream_bots_bench(request: Request, chat: int, msg: int, mb: int = 4,
                            timeout: float = 12):
    if not is_local_request(request):
        raise HTTPException(status_code=403, detail="localhost only")
    mb = max(1, min(int(mb), 16))
    out = []
    for b in list(_stream_bots):
        now = time.time()
        r = {"name": b.get("name"), "who": b.get("who", ""), "kind": b.get("kind", ""),
             "choked_for": max(0, int(b.get("cooldown_until", 0) - now)),
             "fails": b.get("fails", 0), "peer_ok": b.get("peer_ok", True)}
        t0 = time.time()
        try:
            m = await asyncio.wait_for(_get_bot_msg_fast(b, chat, msg), timeout)
            if m is None:
                raise RuntimeError("שליפת ההודעה נכשלה")
            media = m.video or m.audio or m.document or m.video_note
            if not media:
                raise RuntimeError("אין מדיה בהודעה")
            dc, loc = _file_location(media)
            r["dc"] = dc
            sessions, _g = await asyncio.wait_for(
                get_media_session_pool_gen(b["client"], b["name"], dc, 1, block=True),
                timeout + 5)
            if not sessions:
                raise RuntimeError("אין חיבור media")
            r["setup_s"] = round(time.time() - t0, 2)
            t1, got = time.time(), 0
            for i in range(mb):
                chunk = await _get_block(sessions[0], loc, i * MEDIA_CHUNK,
                                         MEDIA_CHUNK, None, timeout)
                if not chunk:
                    break
                got += len(chunk)
            r["mbps"] = round(got / 1048576 / max(time.time() - t1, 1e-6), 2)
            r["mb"] = round(got / 1048576, 1)
        except FloodWait as e:
            r["err"] = f"FloodWait {e.value}s"
        except Exception as e:
            r["err"] = f"{type(e).__name__}: {e}"[:140]
        out.append(r)
        await asyncio.sleep(0.4)
    return {"mb": mb, "bots": out}


'''


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read(); bak = PATH + ".bak_bots_bench"
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        shutil.copy2(bak, PATH); print("✓ שוחזר"); return 0
    if MARKER in src: print("✓ כבר מותקן"); return 0
    assert src.count(ANCHOR) == 1, "עוגן לא נמצא"
    out = src.replace(ANCHOR, CODE + ANCHOR, 1)
    compile(out, "main.py", "exec")
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    shutil.copy2(PATH, bak); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", bak); return 0


if __name__ == "__main__": sys.exit(main())
