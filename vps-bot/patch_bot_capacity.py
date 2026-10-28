#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# המדד שעליו נשען הספסל אינו מודד קיבולת — והוא צבע כמעט כל בוט ככתום.
#
# ## הטעות
#
#     note_bot_speed(bot, (served / 1024 / 1024) / el)
#
# ‎served‎ הוא בייטים שהוגשו ל-HTTP. בהזרמת וידאו **הנגן קובע את הקצב**:
# הוא מושך בקצב הסרט, לא מהר ככל האפשר, והלחץ החוזר של ה-TCP עוצר את
# הגנרטור. סרט 2GB בשעתיים הוא 0.28 MB/s, וזה בדיוק מה שיימדד — גם אם
# הבוט מסוגל לפי עשרים.
#
# כלומר ‎speed‎ מודד את **קצב הצריכה של הנגן**, לא את יכולת הבוט. הרצפה
# שנקבעה (0.6) גבוהה מקצב הביט של רוב הקטלוג, ולכן סימנה בוטים בריאים
# לגמרי כאיטיים ושלחה אותם לספסל.
#
# נמדד בפאנל: 24 בוטים בין 0.01 ל-0.57, ואחד על 5.94 — ההבדל היחיד הוא
# שהאחרון הגיש משיכה מהירה (מילוי מטמון) ולא צפייה.
#
# ## התיקון
#
# מדידה **פעילה**: כל PROBE_INTERVAL נבדק בוט אחד — נמשכים ממנו PROBE_MB
# מהר ככל האפשר, בדיוק כמו /speedtest/bots. זו קיבולת אמיתית, והיא זו
# שמחליטה על ספסל ועל בחירה.
#
# ‎speed‎ (הפסיבי) נשאר לתצוגה בלבד — הוא עדיין מועיל כדי לראות מה קורה —
# אבל הוא כבר לא מעניש אף אחד.
#
# בוט אחד בכל מחזור, ולא כולם: בדיקה בו-זמנית של 30 בוטים היא בדיוק
# העומס שאנחנו מנסים למנוע.
#
#   python3 patch_bot_capacity.py [נתיב ל-main.py]
#   python3 patch_bot_capacity.py --revert
# ─────────────────────────────────────────────────────────────────────────────
import io
import os
import py_compile
import shutil
import sys
import time

P = "/opt/zovex-bot/main.py"
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if args:
    P = args[0]
REVERT = "--revert" in sys.argv
MARK = "bot_capacity"

# ── 1. המדידה הפסיבית מפסיקה להעניש ───────────────────────────────────────
OLD_SLOW = '''    if nbytes is None or nbytes < SLOW_MIN_BYTES:
        return                      # מדגם קטן מדי — לא עדות
    if mb_per_sec >= SLOW_FLOOR:
        bot["slow"] = 0
        return'''
NEW_SLOW = '''    # [bot_capacity] המדידה הפסיבית אינה מודדת קיבולת.
    #
    # ‎served/elapsed‎ בהזרמת וידאו הוא קצב הצריכה של **הנגן**, לא יכולת
    # הבוט: הנגן מושך בקצב הסרט והלחץ החוזר של ה-TCP עוצר את הגנרטור.
    # סרט 2GB בשעתיים הוא 0.28 MB/s, ולכן רצפה של 0.6 סימנה בוטים בריאים
    # לגמרי כאיטיים. נמדד בפאנל: 24 בוטים בין 0.01 ל-0.57.
    #
    # ההחלטה על ספסל עברה למדידה פעילה (_capacity_probe), שמושכת מהר ככל
    # האפשר ולכן באמת מודדת קיבולת. כאן נשמר רק הערך לתצוגה.
    return'''

# ── 2. הבדיקה הפעילה ───────────────────────────────────────────────────────
OLD_ANCHOR = '''async def pick_stream_bot():'''
NEW_ANCHOR = '''# [bot_capacity] מדידה פעילה של קיבולת, בוט אחד בכל מחזור.
PROBE_INTERVAL = float(os.environ.get("STREAM_PROBE_INTERVAL", "90"))
PROBE_MB = float(os.environ.get("STREAM_PROBE_MB", "2"))
_probe_msg = {"chat": None, "msg": None}


async def _capacity_probe_loop():
    """מודד קיבולת אמיתית: מושך PROBE_MB מהר ככל האפשר, בוט אחד בכל פעם.

    זה ההבדל מהמדידה הפסיבית — כאן אין נגן שמאט את הקצב, ולכן התוצאה היא
    מה שהבוט **מסוגל** לתת ולא מה שבמקרה התבקש ממנו.

    בוט אחד בכל מחזור ולא כולם: בדיקה בו-זמנית של 30 בוטים היא בדיוק
    העומס שאנחנו מנסים למנוע. במחזור של 90 שניות כל בוט נבדק בערך פעם
    ב-45 דקות כשיש 30 בוטים.
    """
    await asyncio.sleep(60)          # לתת לבריכה לעלות קודם
    while True:
        try:
            await asyncio.sleep(PROBE_INTERVAL)
            if not _stream_bots or not STREAM_CHANNEL_ID:
                continue
            if _probe_msg["msg"] is None:
                for e in load_content():
                    m = re.search(r"/stream/(-?\\d+)/(\\d+)",
                                  str(e.get("video_url") or ""))
                    if m:
                        _probe_msg["chat"] = int(m.group(1))
                        _probe_msg["msg"] = int(m.group(2))
                        break
            if _probe_msg["msg"] is None:
                continue
            now = time.time()
            # הוותיק ביותר קודם; בוט בקירור מדולג — אין טעם להעיר אותו
            cand = [b for b in _stream_bots if b["cooldown_until"] < now]
            if not cand:
                continue
            bot = min(cand, key=lambda b: b.get("cap_at", 0.0))
            want = int(PROBE_MB * 1024 * 1024)
            msg = await _get_bot_msg_fast(bot, _probe_msg["chat"],
                                          _probe_msg["msg"])
            media = msg and (msg.video or msg.document or msg.audio)
            if not media:
                continue
            dc_id, location = _file_location(media)
            sessions, _g = await get_media_session_pool_gen(
                bot["client"], bot["name"], dc_id, max(1, STREAM_MEDIA_CONNS),
                block=False)
            if not sessions:
                continue
            per = -(-want // len(sessions))
            t0 = time.time()
            parts = await asyncio.wait_for(asyncio.gather(
                *[_band_fetch(sessions[i], location, i * per,
                              min(want, (i + 1) * per) - 1, bot["name"])
                  for i in range(len(sessions)) if i * per < want],
                return_exceptions=True), timeout=45)
            got = sum(len(p) for p in parts if isinstance(p, (bytes, bytearray)))
            el = max(0.001, time.time() - t0)
            cap = round(got / 1024 / 1024 / el, 2)
            bot["cap"] = cap
            bot["cap_at"] = time.time()
            if cap < SLOW_FLOOR:
                others = sum(1 for b in _stream_bots
                             if b is not bot and b["cooldown_until"] < time.time()
                             and b.get("cap", 99) >= SLOW_FLOOR)
                if others >= MIN_FAST_KEEP:
                    n = bot.get("benched", 0)
                    secs = min(SLOW_BENCH_MAX, SLOW_BENCH_SECS * (2 ** min(n, 3)))
                    bot["benched"] = n + 1
                    bot["cooldown_until"] = time.time() + secs
                    log.warning("🪑 %s לספסל — קיבולת %.2f MB/s (%ds)",
                                bot["name"], cap, secs)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("capacity probe: %s", e)


_probe_started = False


def _start_capacity_probe():
    """מופעל פעם אחת, בעצלתיים — אין כאן hook של startup."""
    global _probe_started
    if _probe_started:
        return
    _probe_started = True
    asyncio.create_task(_capacity_probe_loop())


async def pick_stream_bot():
    # [bot_capacity] הפעלה עצלה — אין hook של startup, וזו הפונקציה שנקראת
    # בכל הזרמה. אחרי הקריאה הראשונה זו בדיקת דגל בלבד.
    _start_capacity_probe()'''

# ── 3. הבחירה לפי קיבולת ולא לפי קצב הנגן ─────────────────────────────────
OLD_SCORE = '''def _bot_score(bot) -> float:
    # בוט שטרם נמדד מקבל ציון ביניים כדי שייבחר וייבדק, אבל לא יגבר על מוכח
    return bot["speed"] if bot.get("speed") is not None else 1.0'''
NEW_SCORE = '''def _bot_score(bot) -> float:
    """[bot_capacity] הציון הוא **קיבולת** שנמדדה פעילות, לא קצב הנגן.

    ‎speed‎ נשאר לתצוגה: בהזרמה הוא משקף את קצב הצריכה של הנגן, ולכן בוט
    מצוין שמגיש סרט בקצב הביט שלו נראה בו "איטי".
    """
    cap = bot.get("cap")
    if cap is not None:
        return cap
    # בוט שטרם נמדד מקבל ציון ביניים כדי שייבחר וייבדק, אבל לא יגבר על מוכח
    return 1.0'''

# ── 4. הפעלת הלולאה ────────────────────────────────────────────────────────
OLD_PING = '''        "edge_filling": len(_edge_filling),'''
NEW_PING = '''        "edge_filling": len(_edge_filling),
        # [bot_capacity] קיבולת שנמדדה פעילות — זה המספר שקובע
        "bot_caps": {b["name"]: b.get("cap") for b in _stream_bots},'''

PAIRS = [(OLD_SLOW, NEW_SLOW), (OLD_ANCHOR, NEW_ANCHOR),
         (OLD_SCORE, NEW_SCORE), (OLD_PING, NEW_PING)]


def main():
    d = os.path.dirname(P) or "."
    if REVERT:
        bak = sorted((f for f in os.listdir(d)
                      if f.startswith("main_before_botcap_")), reverse=True)
        if not bak:
            sys.exit("❌ אין גיבוי לשחזר")
        shutil.copy(os.path.join(d, bak[0]), P)
        print(f"✓ שוחזר מ-{bak[0]}")
        return
    try:
        s = io.open(P, encoding="utf-8").read()
    except OSError as e:
        sys.exit(f"❌ לא נפתח {P}: {e}")
    if MARK in s:
        print("✓ כבר מתוקן — מדלג")
        return
    for need in ("def _band_fetch", "def _mark_choked", "SLOW_FLOOR",
                 "MIN_FAST_KEEP", "def _get_bot_msg_fast"):
        if need not in s:
            sys.exit(f"❌ לא נמצא '{need}' — הרץ קודם את deploy_bots_health.sh")
    for i, (old, _) in enumerate(PAIRS, 1):
        if s.count(old) != 1:
            sys.exit(f"❌ קטע {i} נמצא {s.count(old)} פעמים. לא נגעתי בכלום.")
    bak = f"{d}/main_before_botcap_{time.strftime('%Y%m%d-%H%M%S')}.py"
    shutil.copy(P, bak)
    out = s
    for old, new in PAIRS:
        out = out.replace(old, new, 1)
    io.open(P, "w", encoding="utf-8").write(out)
    try:
        py_compile.compile(P, doraise=True)
    except Exception as e:
        shutil.copy(bak, P)
        sys.exit(f"❌ לא עובר קומפילציה — שוחזר.\n   {e}")
    print(f"✓ הוחל. גיבוי: {bak}")
    print("  ספסל ובחירה לפי קיבולת שנמדדה פעילות, לא לפי קצב הנגן")


if __name__ == "__main__":
    main()
