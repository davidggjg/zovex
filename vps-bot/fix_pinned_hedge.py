#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_pinned_hedge — גידור בלוקים בהזרמה המוצמדת (Hedged Requests).

## התקלה (נמדד בשרת החי)
בלוק שנתקע בהזרמה המוצמדת מחכה ל-BLOCK_TIMEOUT, ו-_get_block מנסה שוב
**על אותו חיבור** עד 4 פעמים. חיבור תקוע נשאר תקוע, ולכן הצופה ראה עצירות
של 5–14 שניות (bench_stream: 2–4 מתוך 11 טווחים).

## הפתרון — "The Tail at Scale" (Dean & Barroso, Google 2013)
בלוק שלא הגיע תוך STREAM_PIN_HEDGE_DELAY (ברירת מחדל 2.5ש) נשלח במקביל
**לבוט אחר** (לעולם לא לאותו חיבור — MadelineProto #1948: ערימת בקשות על
socket אחד חוסמת את כולם), והראשון שמגיע מנצח; השני מבוטל.
  · upload.getFile הוא קריאה בלבד — כפילות אינה מזיקה.
  · תקציב: לכל זרם לכל היותר ~רבע מהבלוקים מגודרים (לפחות 3).
  · בוט הגיבוי מוכן רק כשצריך (שליפת הודעה + חיבור media אחד), ונשמר לזרם.
  · STREAM_PIN_HEDGE_DELAY=0 מכבה. מונים: GET /stream/hedge-stats

    MAIN_PY=... python3 fix_pinned_hedge.py [--check|--revert]
"""
import os, re, shutil, sys
PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
MARKER = "[fix_pinned_hedge]"

HELPERS = r'''# ── [fix_pinned_hedge] גידור בלוקים בהזרמה המוצמדת ──────────────────────────
PIN_HEDGE_DELAY = float(os.environ.get("STREAM_PIN_HEDGE_DELAY", "2.5"))
_pin_hedge = {"launched": 0, "won": 0, "lost": 0, "no_backup": 0}


async def _pin_backup(chat_id, message_id, exclude):
    """בוט גיבוי: בוט *אחר*, ההודעה דרכו (file_reference הוא לכל חשבון),
    וחיבור media יחיד. None אם אין בוט מתאים."""
    bot = await pick_stream_bot_for(chat_id, message_id, exclude=exclude)
    if bot is None:
        return None
    msg = await _get_bot_msg_fast(bot, chat_id, message_id)
    if msg is None:
        return None
    media = msg.video or msg.audio or msg.document or msg.video_note
    if not media:
        return None
    dc_id, location = _file_location(media)
    sessions, _g = await get_media_session_pool_gen(
        bot["client"], bot["name"], dc_id, 1, block=False)
    if not sessions:
        sessions, _g = await get_media_session_pool_gen(
            bot["client"], bot["name"], dc_id, 1, block=True)
    if not sessions:
        return None
    return {"name": bot["name"], "session": sessions[0], "location": location}


async def _pin_race(task, i, ctx):
    """מחכה לבלוק i. אם לא הגיע תוך PIN_HEDGE_DELAY — אותו בלוק מבוט הגיבוי,
    והראשון שמחזיר בייטים מנצח. בלי גידור (כבוי/נגמר התקציב/אין גיבוי) —
    בדיוק ההתנהגות הקודמת: ‎await task‎."""
    hb = ctx["hb"]
    if PIN_HEDGE_DELAY <= 0 or hb["dead"] or hb["n"] >= max(3, i // 4 + 1):
        return await task
    done, _ = await asyncio.wait({task}, timeout=PIN_HEDGE_DELAY)
    if done:
        return task.result()
    if hb["t"] is None:
        hb["t"] = asyncio.create_task(ctx["make_backup"]())
    if hb["src"] is None:
        done, _ = await asyncio.wait({task, hb["t"]},
                                     return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            return task.result()
        try:
            hb["src"] = hb["t"].result()
        except Exception:
            hb["src"] = None
        if hb["src"] is None:
            hb["dead"] = True
            _pin_hedge["no_backup"] += 1
            return await task
    hb["n"] += 1
    _pin_hedge["launched"] += 1
    h = asyncio.create_task(ctx["fetch"](hb["src"], i))
    racers = {task, h}
    while racers:
        done, racers = await asyncio.wait(racers, return_when=asyncio.FIRST_COMPLETED)
        for d in done:
            if d.cancelled() or d.exception() is not None or not d.result():
                continue
            for r in racers:
                r.cancel()
                r.add_done_callback(lambda t: t.cancelled() or t.exception())
            if d is h:
                _pin_hedge["won"] += 1
                log.info("pinned hedge: %s הקדים את %s בבלוק %d",
                         hb["src"]["name"], ctx["primary"], i)
            else:
                _pin_hedge["lost"] += 1
            return d.result()
    return await task          # שניהם נכשלו — הכשל של המקורי עולה כרגיל


@api.get("/stream/hedge-stats")
async def stream_hedge_stats():
    """[fix_pinned_hedge] כמה פעמים הגידור הופעל וכמה פעמים הוא הקדים."""
    return {**_pin_hedge, "delay": PIN_HEDGE_DELAY}


'''

EDITS = [
 ("אתחול",
  "    pending = []\n    marked = False",
  "    pending = []\n    _hb = {\"t\": None, \"src\": None, \"dead\": False, \"n\": 0}   # [fix_pinned_hedge]\n    marked = False"),
 ("הקשר",
  "        nxt = 0\n        while nxt < depth:",
  "        _hctx = {\"hb\": _hb, \"primary\": name,   # [fix_pinned_hedge]\n"
  "                 \"make_backup\": lambda: _pin_backup(chat_id, message_id, set(tried) | {name}),\n"
  "                 \"fetch\": lambda src, i: _get_block(src[\"session\"], src[\"location\"],\n"
  "                     first + i * MEDIA_CHUNK, MEDIA_CHUNK, src[\"name\"], BLOCK_TIMEOUT)}\n\n"
  "        nxt = 0\n        while nxt < depth:"),
 ("המתנה מגודרת",
  "            chunk = await pending.pop(0)\n",
  "            chunk = await _pin_race(pending.pop(0), i, _hctx)   # [fix_pinned_hedge]\n"),
 ("ניקוי",
  "    finally:\n        for t in pending:",
  "    finally:\n        if _hb[\"t\"] is not None and not _hb[\"t\"].done():   # [fix_pinned_hedge]\n"
  "            _hb[\"t\"].cancel()\n"
  "            _hb[\"t\"].add_done_callback(lambda t: t.cancelled() or t.exception())\n"
  "        for t in pending:"),
]
HDR = "async def _pinned_stream(chat_id, message_id, start, end, tried):"


def span(src):
    s = src.index(HDR)
    m = re.compile(r"\n(?=(?:@api\.|async def |def |class )\S)").search(src, s + len(HDR))
    return s, (m.start() if m else len(src))


def apply(src):
    if MARKER in src:
        print("✓ כבר מותקן"); return src
    assert src.count(HDR) == 1, "_pinned_stream לא נמצא"
    s, e = span(src)
    body = src[s:e]
    for name, a, n in EDITS:
        c = body.count(a)
        assert c == 1, f"עוגן '{name}' בתוך _pinned_stream: נמצא {c}"
        body = body.replace(a, n, 1)
    out = src[:s] + HELPERS + body + src[e:]
    compile(out, "main.py", "exec")
    return out


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read(); bak = PATH + ".bak_pinned_hedge"
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        shutil.copy2(bak, PATH); print("✓ שוחזר"); return 0
    out = apply(src)
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    if MARKER in src: return 0
    shutil.copy2(PATH, bak); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", bak); return 0


if __name__ == "__main__": sys.exit(main())
