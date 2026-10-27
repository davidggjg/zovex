#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# ספסל לבוטים איטיים — הוצאה זמנית, לא מחיקה.
#
# ## מה נמדד
#
# אותו קובץ, אותו רגע, 4 חיבורים לכל בוט:
#
#   @Hrxhxbot 6.78 MB/s · @Zovfxhbot 1.86 · @Movergbot 0.25 ·
#   @Zfugbbot 0.08 · שניים ב-timeout
#
# פער של פי 85. התוכן נע בין 50MB ל-4GB; סרט 4GB בשעתיים צורך ~0.55 MB/s,
# כלומר בוט שנותן 0.08 אינו מסוגל להחזיק **אפילו צופה אחד**.
#
# ## למה זה לא נתפס
#
# ‎cooldown‎ מופעל רק על *שגיאה*. בוט שמעביר בייטים ב-0.08 MB/s מחזיר
# תוצאה תקינה ולא זורק חריגה — ולכן נראה למערכת בריא לגמרי וממשיך לקבל
# צופים. איטיות פשוט לא נחשבה כשל.
#
# ## למה ספסל ולא הוצאה
#
# 50 אדמינים לערוץ ו-20 בוטים לחשבון ב-BotFather. מחיקת בוט איטי היא
# ויתור קבוע על משאב נדיר — ומיותר: מהשטח מדווח שבוט חדש מוגבל להעברות
# ל-20 דקות עד 24 שעות, כלומר חלק מהאיטיים יתאוששו לבד. הספסל מחזיר
# אותם אוטומטית ובודק שוב.
#
# ## שלוש רשתות ביטחון
#
# 1. **מינימום בייטים.** בקשת 64KB (קריאת moov) נותנת MB/s נמוך בגלל
#    השהיית הרשת ולא בגלל הבוט. רק מדגם מעל 1MB נספר.
# 2. **שלוש פגיעות ברצף.** מדידה בודדת לא מספיקה; רעש רגעי לא מעניש.
# 3. **רצפת בריכה.** בוט לא יישלח לספסל אם יישארו פחות מ-MIN_FAST_KEEP
#    בוטים זמינים. בלי זה ערב גרוע היה מרוקן את הבריכה כולה.
#
# הבחירה גם מעדיפה מעתה בוטים מעל הרצפה כשיש כאלה — "הטוב מבין שניים
# אקראיים" חלש מדי בפער של פי 85.
#
#   python3 patch_slow_bench.py [נתיב ל-main.py]
#   python3 patch_slow_bench.py --revert
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
MARK = "slow_bench"

OLD_CONST = '''BOT_SPEED_ALPHA = 0.3          # משקל המדידה האחרונה בממוצע הנע

def note_bot_speed(bot, mb_per_sec: float):
    prev = bot.get("speed")
    bot["speed"] = (mb_per_sec if prev is None
                    else prev * (1 - BOT_SPEED_ALPHA) + mb_per_sec * BOT_SPEED_ALPHA)'''

NEW_CONST = '''BOT_SPEED_ALPHA = 0.3          # משקל המדידה האחרונה בממוצע הנע

# [slow_bench] רצפת תפוקה לבוט.
#
# התוכן נע בין 50MB ל-4GB. סרט 4GB בשעתיים צורך ~0.55 MB/s, ולכן בוט
# מתחת ל-0.6 אינו מסוגל להחזיק אפילו צופה אחד של התוכן הכבד ביותר.
# זו רצפה שנגזרת מהקטלוג, לא מספר שרירותי.
SLOW_FLOOR = float(os.environ.get("STREAM_SLOW_FLOOR", "0.6"))

# מדגם קטן מדי אינו עדות. בקשת 64KB (קריאת moov) מחזירה MB/s נמוך בגלל
# השהיית הרשת ולא בגלל הבוט; בלי הסף הזה בוט מהיר היה נענש על כך שהגיש
# בקשה קטנה.
SLOW_MIN_BYTES = int(os.environ.get("STREAM_SLOW_MIN_BYTES", str(1024 * 1024)))

# כמה מדידות איטיות *ברצף* לפני ספסל. מדידה בודדת היא רעש.
SLOW_STRIKES = int(os.environ.get("STREAM_SLOW_STRIKES", "3"))

# זמן הספסל, מוכפל בכל חזרה עד לתקרה. בוט שהתאושש חוזר מיד; בוט שאיטי
# באופן קבוע (DC רחוק) שוקע לבדיקות נדירות במקום להיעלם לתמיד.
SLOW_BENCH_SECS = int(os.environ.get("STREAM_SLOW_BENCH", "240"))
SLOW_BENCH_MAX = int(os.environ.get("STREAM_SLOW_BENCH_MAX", "1800"))

# רצפת בריכה: לעולם לא לשלוח לספסל אם יישארו פחות מכך זמינים. בערב גרוע
# בלי זה הספסל היה מרוקן את הבריכה כולה ומשבית את השירות.
MIN_FAST_KEEP = int(os.environ.get("STREAM_MIN_FAST_KEEP", "3"))

_benched_total = 0


def note_bot_speed(bot, mb_per_sec: float, nbytes: int = None):
    global _benched_total
    prev = bot.get("speed")
    bot["speed"] = (mb_per_sec if prev is None
                    else prev * (1 - BOT_SPEED_ALPHA) + mb_per_sec * BOT_SPEED_ALPHA)

    # [slow_bench] איטיות היא כשל — עד כה היא לא נחשבה ככזה.
    #
    # cooldown הופעל רק על שגיאה, ולכן בוט שהעביר בייטים ב-0.08 MB/s
    # נראה בריא והמשיך לקבל צופים. כאן איטיות מתמשכת מפעילה את אותו
    # מנגנון הקירור שכבר קיים.
    if nbytes is None or nbytes < SLOW_MIN_BYTES:
        return                      # מדגם קטן מדי — לא עדות
    if mb_per_sec >= SLOW_FLOOR:
        bot["slow"] = 0
        return
    bot["slow"] = bot.get("slow", 0) + 1
    if bot["slow"] < SLOW_STRIKES:
        return
    now = time.time()
    others = sum(1 for b in _stream_bots
                 if b is not bot and b["cooldown_until"] < now)
    if others < MIN_FAST_KEEP:
        return                      # רצפת בריכה — עדיף איטי מכלום
    bot["slow"] = 0
    n = bot.get("benched", 0)
    secs = min(SLOW_BENCH_MAX, SLOW_BENCH_SECS * (2 ** min(n, 3)))
    bot["benched"] = n + 1
    bot["cooldown_until"] = now + secs
    _benched_total += 1
    log.warning("🪑 בוט %s לספסל — %.2f MB/s מתחת ל-%.2f (ספסל %d, %ds)",
                bot["name"], mb_per_sec, SLOW_FLOOR, n + 1, secs)'''

OLD_PICK1 = '''    free = [b for b in _stream_bots
            if b["cooldown_until"] < now and b["name"] not in busy]
    if not free:
        return await pick_stream_bot()'''
NEW_PICK1 = '''    free = [b for b in _stream_bots
            if b["cooldown_until"] < now and b["name"] not in busy]
    if not free:
        return await pick_stream_bot()
    # [slow_bench] מעל הרצפה קודם. "הטוב מבין שניים אקראיים" חלש מדי
    # כשהפער בין הבוטים הוא פי 85 — הוא עדיין ניתב צופים לבוט של 0.08.
    _fast = [b for b in free if _bot_score(b) >= SLOW_FLOOR]
    if _fast:
        free = _fast'''

OLD_PICK2 = '''        healthy = [b for b in _stream_bots if b["cooldown_until"] < now]
        pool = healthy or _stream_bots'''
NEW_PICK2 = '''        healthy = [b for b in _stream_bots if b["cooldown_until"] < now]
        # [slow_bench] אותה העדפה גם כאן; נפילה חזרה לכל השאר אם אין.
        _fast = [b for b in healthy if _bot_score(b) >= SLOW_FLOOR]
        pool = _fast or healthy or _stream_bots'''

OLD_CALL1 = '''            note_bot_speed(bot, (total / 1024 / 1024) / elapsed)'''
NEW_CALL1 = '''            note_bot_speed(bot, (total / 1024 / 1024) / elapsed, total)'''

OLD_CALL2 = '''            note_bot_speed(bot, (served / 1024 / 1024) / el)'''
NEW_CALL2 = '''            note_bot_speed(bot, (served / 1024 / 1024) / el, served)'''

OLD_DBG = '''        "edge_filling": len(_edge_filling),'''
NEW_DBG = '''        "edge_filling": len(_edge_filling),
        # [slow_bench] כמה פעמים בוט נשלח לספסל, וכמה יושבים בו עכשיו.
        "benched_total": _benched_total,
        "benched_now": sum(1 for b in _stream_bots
                           if b["cooldown_until"] > time.time()),
        "bot_speeds": {b["name"]: (round(b["speed"], 2)
                                   if b.get("speed") is not None else None)
                       for b in _stream_bots},'''

PAIRS = [(OLD_CONST, NEW_CONST), (OLD_PICK1, NEW_PICK1), (OLD_PICK2, NEW_PICK2),
         (OLD_CALL1, NEW_CALL1), (OLD_CALL2, NEW_CALL2), (OLD_DBG, NEW_DBG)]


def main():
    d = os.path.dirname(P) or "."
    if REVERT:
        bak = sorted((f for f in os.listdir(d)
                      if f.startswith("main_before_slowbench_")), reverse=True)
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

    for i, (old, _) in enumerate(PAIRS, 1):
        n = s.count(old)
        if n != 1:
            sys.exit(f"❌ קטע {i} מתוך {len(PAIRS)} לא נמצא בדיוק פעם אחת "
                     f"({n}). לא נגעתי בכלום — שלח לי את הפלט.")

    bak = f"{d}/main_before_slowbench_{time.strftime('%Y%m%d-%H%M%S')}.py"
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
    print(f"  רצפה {os.environ.get('STREAM_SLOW_FLOOR', '0.6')} MB/s, "
          f"3 פגיעות ברצף, ספסל 4 דק' (מוכפל)")
    print("  benched_total / benched_now / bot_speeds ב-/debug/caches")


if __name__ == "__main__":
    main()
