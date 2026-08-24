#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מחיל את תיקון "בוט עם session תקוע" על main.py החי.

הבעיה שנמדדה: 9 מתוך 21 בוטים לא מחזירים תשובה מ-get_messages, נתקעים
20 שניות בכל בחירה, וחוזרים לרוטציה כל 30 שניות לנצח. ~43% מהחלונות שילמו
את המחיר → 6 MB/s צנחו מתחת ל-0.03.

בטוח להרצה חוזרת: מזהה מה כבר הוחל ומדלג. שומר גיבוי, מוודא קומפילציה,
ומשחזר אוטומטית אם משהו נשבר.
"""
import hashlib, pathlib, py_compile, re, shutil, sys, time

P = pathlib.Path("/opt/zovex-bot/main.py")
s = P.read_text(encoding="utf-8")
orig = s
done, skipped = [], []

CHOKE  = 'CHOKE_AFTER_FAILS = int(os.environ.get("STREAM_CHOKE_AFTER_FAILS", "3"))\n\n# עונש מתגבר. cooldown קבוע של 30 שניות נראה הגיוני, אבל מול בוט שה-session\n# שלו *תקוע* הוא אסון: הבוט חוזר לתור כל חצי דקה, כל בחירה בו שורפת את מלוא\n# תקציב שליפת ההודעה, והוא לעולם לא יוצא מהמשחק. נמדד בשרת: 9 מתוך 21 בוטים\n# תקועים ← ~43% מהחלונות שילמו 20 שניות ← 6 MB/s צנחו מתחת ל-0.03.\n# עם הכפלה פי 4 בכל חניקה רצופה (30ש\' → 2ד\' → 8ד\' → 30ד\') בוט מת יוצא\n# מהרוטציה תוך כדקתיים, בעוד בוט שנתקל ברעש רגעי חוזר מיד אחרי 30 שניות.\nCHOKE_BACKOFF_MAX = int(os.environ.get("STREAM_CHOKE_BACKOFF_MAX", "1800"))\n\ndef _mark_ok(bot):\n    """משיכה הצליחה — מאפסים את מונה הכשלים הרצופים ואת דרגת העונש."""\n    if bot.get("fails"):\n        bot["fails"] = 0\n    if bot.get("chokes"):\n        bot["chokes"] = 0\n\ndef _mark_choked(bot, seconds, err=None, hard=False, escalate=True):\n    # "Peer id invalid" הוא לא חניקה אלא בוט ששכח את הערוץ: cooldown לבדו לא\n    # יעזור לו, הוא פשוט ייכשל שוב בעוד 30 שניות. מסמנים אותו כדי ש-\n    # peer_retry_loop ינסה לזהות עבורו את הערוץ מחדש.\n    peer_bad = err is not None and "peer id invalid" in str(err).lower()\n    if peer_bad:\n        bot["peer_ok"] = False\n    # FloodWait ו-peer פגום הם ודאיים — מדיחים מיד. כל השאר צריך לחזור על עצמו.\n    if not (hard or peer_bad):\n        bot["fails"] = bot.get("fails", 0) + 1\n        if bot["fails"] < CHOKE_AFTER_FAILS:\n            log.info("בוט %s נכשל (%d/%d) — עדיין בשירות",\n                     bot["name"], bot["fails"], CHOKE_AFTER_FAILS)\n            return\n        bot["fails"] = 0\n    # FloodWait מגיע עם זמן ההמתנה שטלגרם עצמו ביקש — אותו לא מכפילים.\n    n = bot.get("chokes", 0)\n    if escalate:\n        bot["chokes"] = n + 1\n        seconds = min(CHOKE_BACKOFF_MAX, int(seconds * (4 ** min(n, 5))))\n    bot["cooldown_until"] = time.time() + seconds\n    log.warning("🥵 בוט %s נחנק (חניקה %d) — cooldown %ds",\n                bot["name"], n + 1 if escalate else n, seconds)\n\n'
FAST   = '# תקציב שליפת ההודעה בכל מסלול הזרמה. ל-_get_bot_msg יש timeout של 20 שניות,\n# והוא נספר *מחוץ* לתקציב החלון — כלומר בוט עם session תקוע גבה 20 שניות מלאות\n# לפני שהחלון בכלל התחיל, ובמסלולי הגיבוי (לולאה על 4 בוטים) עד 80 שניות\n# לבקשה אחת. ההודעה שמורה במטמון 15 דקות ובוט בריא מחזיר אותה ממנו מיידית\n# (וגם קר — פחות משתי שניות), ולכן 8 שניות הן מרווח נדיב לכל בוט חי.\nMSG_FETCH_BUDGET = float(os.environ.get("STREAM_MSG_FETCH_BUDGET", "8"))\n\n\nasync def _get_bot_msg_fast(bot, chat_id, message_id):\n    """כמו _get_bot_msg אבל עם תקציב קצר, וחניקה מיידית של בוט שנתקע.\n\n    session תקוע לא מחזיר שגיאה — הוא פשוט לא חוזר, ולכן הוא מתחזה ל"בוט איטי"\n    ולא מודח לעולם. נמדד בשרת: 9 מתוך 21 בוטים במצב הזה ניתבו אליהם ~43%\n    מהחלונות, וכל אחד שילם את מלוא ה-timeout. מחזיר None אם הבוט נתקע.\n    """\n    try:\n        return await asyncio.wait_for(\n            _get_bot_msg(bot, chat_id, message_id), timeout=MSG_FETCH_BUDGET)\n    except asyncio.TimeoutError:\n        # חניקה מיידית (hard) בלי לחכות לשלושה כשלים: עם העונש המתגבר, טעות\n        # על בוט בריא עולה 30 שניות בלבד, בעוד ההמתנה לשלוש מכות עלתה יותר\n        # מדקה של צפייה תקועה בכל סיבוב.\n        log.warning("שליפת ההודעה מ-%s נתקעה (%.0fs) — חונק", bot["name"], MSG_FETCH_BUDGET)\n        note_bot_speed(bot, 0.0)\n        _mark_choked(bot, 30, hard=True)\n        return None\n\n\n'
REVIVE = '# כל כמה זמן לנסות להחיות בוטים מודחים. הבדיקה רצה *מחוץ* למסלול הצפייה,\n# כך שהצופה לעולם לא משלם על ניסיון החייאה.\nREVIVE_EVERY = int(os.environ.get("STREAM_REVIVE_EVERY", "120"))\nREVIVE_AFTER_CHOKES = int(os.environ.get("STREAM_REVIVE_AFTER_CHOKES", "2"))\n\n\nasync def revive_stream_pool():\n    """מחזיר לחיים בוטים שה-session שלהם תקוע.\n\n    למה זה נדרש: cooldown (גם מתגבר) רק *מסתיר* בוט מת — הוא לא מתקן אותו.\n    בלי החייאה הבריכה שוחקת מ-21 בוטים ל-12 עד ה-restart הבא, וכל בוט שנשחק\n    מגדיל את העומס על הנותרים. חיבור MTProto תקוע לא מחזיר שגיאה שאפשר לתפוס\n    (הוא פשוט לא חוזר), ולכן אין ל-Pyrogram סיכוי לזהות אותו לבד — הדרך היחידה\n    היא stop()+start() שבונים session טרי.\n    """\n    if not STREAM_CHANNEL_ID:\n        return\n    while True:\n        await asyncio.sleep(REVIVE_EVERY)\n        for b in list(_stream_bots):\n            if b.get("chokes", 0) < REVIVE_AFTER_CHOKES:\n                continue\n            name = b["name"]\n            try:\n                # קודם בדיקה זולה: אולי הוא כבר התאושש מעצמו וחבל להפיל session.\n                await asyncio.wait_for(b["client"].get_me(), timeout=10)\n                b["chokes"] = 0\n                b["fails"] = 0\n                b["cooldown_until"] = 0.0\n                log.info("✅ %s התאושש — חזר לרוטציה", name)\n                continue\n            except Exception:\n                pass\n            log.warning("♻️ %s תקוע — מרים session מחדש", name)\n            try:\n                # stop() על לקוח תקוע עלול להיתקע בעצמו — עוטפים בתקציב.\n                await asyncio.wait_for(b["client"].stop(), timeout=20)\n            except Exception:\n                pass\n            try:\n                await asyncio.wait_for(b["client"].start(), timeout=POOL_START_TIMEOUT)\n                # ה-session החדש לא מכיר את הערוץ, וה-file_reference הישן שייך\n                # ל-session שמת — שניהם חייבים להיבנות מחדש, אחרת הבוט "עלה"\n                # אבל ייכשל בכל משיכה.\n                b["peer_ok"] = await _resolve_peer(b["client"], name)\n                for k in [k for k in _bot_msg_cache if k[0] == name]:\n                    _bot_msg_cache.pop(k, None)\n                b["chokes"] = 0\n                b["fails"] = 0\n                b["speed"] = None\n                b["cooldown_until"] = 0.0\n                log.info("✅ %s הורם מחדש וחזר לרוטציה", name)\n            except Exception as e:\n                # נשאר מודח; הסבב הבא ינסה שוב.\n                log.warning("⚠️ הרמת %s נכשלה: %s: %s", name, type(e).__name__, e)\n            await asyncio.sleep(2)   # לא מציפים את טלגרם בהתחברויות\n\n\n'

# ── 1. עונש מתגבר + איפוס דרגת החניקה ──────────────────────────────────────
if "CHOKE_BACKOFF_MAX" in s:
    skipped.append("עונש מתגבר")
else:
    a = s.index("CHOKE_AFTER_FAILS = int(")
    b = s.index("# cache של אובייקט ההודעה", a)
    s = s[:a] + CHOKE + s[b:]
    done.append("עונש מתגבר (30ש' -> 2ד' -> 8ד' -> 30ד')")

# ── 2. FloodWait לא מוכפל ───────────────────────────────────────────────────
old_fw = "_mark_choked(bot, e.value, hard=True)"
if old_fw in s:
    n = s.count(old_fw)
    s = s.replace(old_fw, "_mark_choked(bot, e.value, hard=True, escalate=False)")
    done.append("FloodWait ללא הכפלה (%d מקומות)" % n)
else:
    skipped.append("FloodWait ללא הכפלה")

# ── 3. תקציב קצר לשליפת ההודעה + חניקה מיידית ──────────────────────────────
if "_get_bot_msg_fast" in s:
    skipped.append("תקציב שליפת הודעה")
else:
    s = s.replace("def _purge_msg_cache", FAST + "def _purge_msg_cache", 1)
    done.append("תקציב שליפת הודעה (8 שניות)")

# ── 4. שלושת מסלולי ההזרמה עוברים לעוזר החדש ───────────────────────────────
subs = [
    ("            msg = await _get_bot_msg(bot, chat_id, message_id)\n"
     "            if msg:\n",
     "            msg = await _get_bot_msg_fast(bot, chat_id, message_id)\n"
     "            if msg:\n", "channel_get_media"),
    ("            msg = await _get_bot_msg(bot, chat_id, message_id)\n"
     "            if msg is None:\n"
     "                _mark_choked(bot, 15)\n"
     "                continue\n"
     "            off_chunks = pos // CHUNK\n",
     "            msg = await _get_bot_msg_fast(bot, chat_id, message_id)\n"
     "            if msg is None:\n"
     "                continue          # כבר נחנק בתוך _get_bot_msg_fast אם נתקע\n"
     "            off_chunks = pos // CHUNK\n", "channel_stream_range"),
    ("            msg = await _get_bot_msg(bot, chat_id, message_id)\n"
     "            if msg is None:\n"
     "                _mark_choked(bot, 15)\n"
     "                continue\n"
     "\n"
     "            async def _pull():\n",
     "            msg = await _get_bot_msg_fast(bot, chat_id, message_id)\n"
     "            if msg is None:\n"
     "                continue          # כבר נחנק בתוך _get_bot_msg_fast אם נתקע\n"
     "\n"
     "            async def _pull():\n", "_fetch_subrange"),
    ("    dc_id = gen = None\n"
     "    try:\n"
     "        msg = await _get_bot_msg(bot, chat_id, message_id)\n",
     "    dc_id = gen = None\n"
     "    try:\n"
     "        msg = await _get_bot_msg_fast(bot, chat_id, message_id)\n",
     "_media_bands_fetch"),
]
for old, new, label in subs:
    if new in s:
        skipped.append(label)
    elif old in s:
        s = s.replace(old, new, 1)
        done.append(label + " -> עוזר מהיר")
    else:
        print("### לא נמצא הקטע של %s — עוצר בלי לשנות כלום ###" % label)
        sys.exit(1)

# ── 5. לולאת ההחייאה ────────────────────────────────────────────────────────
if "revive_stream_pool" in s:
    skipped.append("לולאת החייאה")
else:
    s = s.replace("async def stop_stream_pool():", REVIVE + "async def stop_stream_pool():", 1)
    anchor = "    asyncio.create_task(peer_retry_loop())"
    i = s.index(anchor)
    j = s.index("\n", i) + 1
    s = s[:j] + "    asyncio.create_task(revive_stream_pool())  # מרים מחדש בוטים עם session תקוע\n" + s[j:]
    done.append("לולאת החייאה (כל 2 דקות)")

if s == orig:
    print("הכל כבר מוחל — אין מה לעשות.")
    sys.exit(0)

bak = P.with_name("main_before_evict_%d.py" % time.time())
shutil.copy2(P, bak)
P.write_text(s, encoding="utf-8")
try:
    py_compile.compile(str(P), doraise=True)
except Exception as e:
    shutil.copy2(bak, P)
    print("### הקומפילציה נכשלה — שוחזר הגיבוי ###")
    print(e)
    sys.exit(1)

print("הוחל:")
for d in done:
    print("   + " + d)
for k in skipped:
    print("   = " + k + " (כבר היה)")
print("\n   גיבוי: " + bak.name)
print("\n   עכשיו:  sudo systemctl restart zovex-bot")
