#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""add_diag_stream_timing — תיעוד זמנים זמני בנתיב ההזרמה, לאבחון דיווחים
מהשטח על צפייה שלוקחת המון זמן להתחיל בתוכן "קר" (לא נצפה ב-15 הדקות
האחרונות, ראה _BOT_MSG_TTL).

## רקע

הקוד הזה כבר נכתב בקומיט d00d88d בריפו — אבל main.py בריפו הוא רק
גיבוי חד-כיווני מהשרת (backup_to_git.sh), ו-deploy_all.sh לא מושך את
main.py עצמו, אז הקומיט ההוא אף פעם לא הגיע לשרת. זה סקריפט פריסה
תקני לאותו שינוי, בנוי אוטומטית מתוך ה-diff של הקומיט
(git diff 97cda3f..d00d88d -- vps-bot/main.py) כדי שהטקסט יהיה זהה
ב-100% למה שכבר נכתב.

בלתי-תלוי לגמרי ב-add_tmdb_backdrop_cast.py — נוגע באזור אחר לחלוטין
בקובץ (channel_get_media/channel_stream_range, סביב שורה 1440, מול
TMDB סביב שורה 4150+) — אפשר להחיל את שני הסקריפטים בכל סדר, או רק
אחד מהם.

## מה זה מוסיף

רק log.info/log.warning + מדידת זמן (t0=time.time(), attempt) סביב
בחירת בוט ומשיכת ההודעה/ה-stream ב-channel_get_media ו-
channel_stream_range. **אפס שינוי בהתנהגות** — שום החלטה, timeout,
retry או ניתוק לא משתנים; רק מה שכבר קורה נרשם עם זמן וניסיון מספור.
כולל: "[diag_stream_timing] channel_get_media ... נמצא דרך <בוט>",
"stream_range ... בייט ראשון אחרי Xs", ושגיאת "חסרים בייטים" הקיימת
מקבלת גם היא %.2fs/ניסיונות בסוף השורה.

אפשר להסיר את כל זה בבטחה כשהאבחון מסתיים — כל שורה מתויגת
"[diag_stream_timing]" ב-grep.

## בטיחות

כל אחד מ-4 העוגנים אומת שהוא מופיע **פעם אחת בדיוק** ב-main.py החי
(גיבוי 97cda3f). לפני כתיבה: קומפילציה מלאה לקובץ המתוקן.

**דורש restart** — main.py נטען פעם אחת בעליית התהליך. הסקריפט לא
מפעיל restart לבד:

    python3 add_diag_stream_timing.py --check
    python3 add_diag_stream_timing.py
    systemctl restart zovex-bot     # ← נדרש כדי שהתיעוד יתחיל להירשם
    python3 add_diag_stream_timing.py --revert    # (משחזר; restart שוב אחרי)
"""
import os
import re
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_add_diag_stream_timing"
MARK = "[diag_stream_timing]"

EDITS = [
    ('channel_get_media: תיעוד זמנים', '\nasync def channel_get_media(chat_id, message_id):\n    """מחזיר את ה-media של ההודעה מהערוץ (metadata בלבד — אין בעיית reference)."""\n    for _ in range(min(max(1, len(_stream_bots)), 5)):\n        bot = await pick_stream_bot_for(chat_id, message_id)\n        if bot is None:\n            return None\n        try:\n            msg = await _get_bot_msg_fast(bot, chat_id, message_id)\n            if msg:\n                return msg.video or msg.audio or msg.document or msg.video_note\n        except FloodWait as e:\n            _mark_choked(bot, e.value, hard=True, escalate=False)\n        except Exception as e:\n            log.warning("channel_get_media שגיאה (%s): %s", chat_id, e)\n            _mark_choked(bot, 30, e)\n    return None\n\nasync def channel_stream_range(chat_id, message_id, start, end):', '\nasync def channel_get_media(chat_id, message_id):\n    """מחזיר את ה-media של ההודעה מהערוץ (metadata בלבד — אין בעיית reference)."""\n    # [diag_stream_timing] ראה ההסבר המלא ב-channel_stream_range. זו קריאה\n    # *נפרדת* לאותו (chat_id, message_id) — כלומר מחיר ה"קור" עלול להיגבות\n    # כאן *וגם* שוב ב-channel_stream_range לאותה בקשה בדיוק. התיעוד כאן\n    # יראה אם זה אכן קורה פעמיים.\n    t0 = time.time()\n    attempt = 0\n    for _ in range(min(max(1, len(_stream_bots)), 5)):\n        attempt += 1\n        bot = await pick_stream_bot_for(chat_id, message_id)\n        if bot is None:\n            log.warning("[diag_stream_timing] channel_get_media %s/%s: אין בוט זמין "\n                       "(ניסיון %d, %.2fs)", chat_id, message_id, attempt, time.time() - t0)\n            return None\n        try:\n            msg = await _get_bot_msg_fast(bot, chat_id, message_id)\n            if msg:\n                log.info("[diag_stream_timing] channel_get_media %s/%s: נמצא דרך %s "\n                         "(ניסיון %d, %.2fs)", chat_id, message_id, bot["name"], attempt,\n                         time.time() - t0)\n                return msg.video or msg.audio or msg.document or msg.video_note\n        except FloodWait as e:\n            _mark_choked(bot, e.value, hard=True, escalate=False)\n        except Exception as e:\n            log.warning("channel_get_media שגיאה (%s): %s", chat_id, e)\n            _mark_choked(bot, 30, e)\n    log.warning("[diag_stream_timing] channel_get_media %s/%s: נכשל אחרי %d ניסיונות "\n               "(%.2fs)", chat_id, message_id, attempt, time.time() - t0)\n    return None\n\nasync def channel_stream_range(chat_id, message_id, start, end):', 1),
    ('channel_stream_range: אתחול מדידה', '    (file_reference תקף רק בהקשר שלו). בוט שנחנק בהתחלה → עוברים לבא."""\n    CHUNK = PYROGRAM_CHUNK_SIZE\n    pos = start\n    for _ in range(min(max(1, len(_stream_bots)), 4)):\n        bot = await pick_stream_bot_for(chat_id, message_id)\n        if bot is None:\n            break', '    (file_reference תקף רק בהקשר שלו). בוט שנחנק בהתחלה → עוברים לבא."""\n    CHUNK = PYROGRAM_CHUNK_SIZE\n    pos = start\n    # [diag_stream_timing] תיעוד זמנים זמני — לאבחון דיווחים מהשטח על צפייה\n    # שלוקחת המון זמן להתחיל בתוכן "קר" (לא נצפה ב-15 הדקות האחרונות, ראה\n    # _BOT_MSG_TTL). רק log.info, אפס שינוי בהתנהגות. אפשר להסיר כשהאבחון\n    # מסתיים — חפש "diag_stream_timing".\n    t0 = time.time()\n    attempt = 0\n    for _ in range(min(max(1, len(_stream_bots)), 4)):\n        attempt += 1\n        bot = await pick_stream_bot_for(chat_id, message_id)\n        if bot is None:\n            break', 1),
    ('channel_stream_range: תיעוד בוט+בייט ראשון', '            msg = await _get_bot_msg_fast(bot, chat_id, message_id)\n            if msg is None:\n                continue          # כבר נחנק בתוך _get_bot_msg_fast אם נתקע\n            off_chunks = pos // CHUNK\n            produced = off_chunks * CHUNK\n            async for chunk in bot["client"].stream_media(msg, offset=off_chunks):\n                c_start = produced\n                c_end = produced + len(chunk)\n                lo = max(pos, c_start) - c_start', '            msg = await _get_bot_msg_fast(bot, chat_id, message_id)\n            if msg is None:\n                continue          # כבר נחנק בתוך _get_bot_msg_fast אם נתקע\n            log.info("[diag_stream_timing] stream_range %s/%s: הודעה נמצאה דרך %s "\n                     "(ניסיון %d, %.2fs)", chat_id, message_id, bot["name"], attempt,\n                     time.time() - t0)\n            off_chunks = pos // CHUNK\n            produced = off_chunks * CHUNK\n            first_chunk = True\n            async for chunk in bot["client"].stream_media(msg, offset=off_chunks):\n                if first_chunk:\n                    log.info("[diag_stream_timing] stream_range %s/%s: בייט ראשון "\n                             "אחרי %.2fs", chat_id, message_id, time.time() - t0)\n                    first_chunk = False\n                c_start = produced\n                c_end = produced + len(chunk)\n                lo = max(pos, c_start) - c_start', 1),
    ('channel_stream_range: תיעוד בכשל הסופי', '            if pos > start:\n                break\n    if pos <= end:\n        log.error("channel stream: חסרים %d בייטים — מנתק כדי שהנגן יבקש שוב",\n                  end - pos + 1)\n        raise StreamGap(f"missing {end - pos + 1} bytes")\n\n# ── הזרמה מקבילה (FastTelethon-style, בטוח) ─────────────────────────────────', '            if pos > start:\n                break\n    if pos <= end:\n        log.error("channel stream: חסרים %d בייטים אחרי %.2fs (%d ניסיונות) — "\n                  "מנתק כדי שהנגן יבקש שוב",\n                  end - pos + 1, time.time() - t0, attempt)\n        raise StreamGap(f"missing {end - pos + 1} bytes")\n\n# ── הזרמה מקבילה (FastTelethon-style, בטוח) ─────────────────────────────────', 1),
]


def validate(out: str) -> None:
    """קומפילציה מלאה (העוגנים עצמם כבר הבטיחו טקסט מדויק — הסיכון כאן
    הוא רק הזחה/תחביר, לא לוגיקה חדשה שצריך לבדוק התנהגותית: זה
    log.info/log.warning בלבד, אפס שינוי בהתנהגות)."""
    try:
        compile(out, PATH, "exec")
    except SyntaxError as e:
        sys.exit(f"✗ הקובץ המתוקן לא מתקמפל: {e}")

    assert MARK in out, "התגית [diag_stream_timing] חסרה"
    assert out.count(MARK) == 7, f"ציפיתי ל-7 מופעים של {MARK!r} (1 תגובה + 6 שורות log), יש {out.count(MARK)}"
    assert "t0 = time.time()" in out, "אתחול t0 חסר"
    assert re.search(r"attempt\s*=\s*0", out), "אתחול attempt חסר"
    assert "בייט ראשון" in out, "תיעוד הבייט הראשון חסר"
    assert 'end - pos + 1, time.time() - t0, attempt' in out, \
        "שורת 'חסרים בייטים' לא קיבלה את פרטי הזמן/ניסיונות"
    # שלוש ההתייחסויות הקיימות ל-"channel stream: חסרים" ו-FastTelethon
    # עדיין שם, בלי שהעריכה גלשה/מחקה קוד שכן.
    assert out.count('async def channel_get_media(chat_id, message_id):') == 1
    assert out.count('async def channel_stream_range(chat_id, message_id, start, end):') == 1
    assert "# ── הזרמה מקבילה (FastTelethon-style, בטוח) ─" in out


def main() -> None:
    if not os.path.exists(PATH):
        sys.exit(f"אין קובץ ב-{PATH} (אפשר MAIN_PY=...)")
    with open(PATH, encoding="utf-8") as fh:
        src = fh.read()

    if "--revert" in sys.argv:
        if not os.path.exists(BAK):
            sys.exit(f"אין גיבוי ב-{BAK}")
        shutil.copy2(BAK, PATH)
        print(f"✓ שוחזר מ-{BAK}")
        print("⚠ דורש restart כדי שהשחזור ייכנס לתוקף: systemctl restart zovex-bot")
        return

    if MARK in src:
        print("כבר מותקן.")
        return

    out = src
    for label, a, n, want in EDITS:
        got = out.count(a)
        if got != want:
            sys.exit(f"✗ העוגן '{label}' נמצא {got} פעמים (צפוי {want}) — לא נוגע בכלום.")
        out = out.replace(a, n)

    validate(out)
    print(f"✓ כל הבדיקות עברו ({len(EDITS)} עריכות)")
    if "--check" in sys.argv:
        print("--check: שום דבר לא נכתב.")
        return

    shutil.copy2(PATH, BAK)
    with open(PATH, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(f"✓ הוחל. גיבוי: {BAK}")
    print()
    print("⚠ דורש restart כדי שהתיעוד יתחיל להירשם (main.py נטען פעם אחת")
    print("  בעליית התהליך) — תבחר מתי, לא בהכרח עכשיו:")
    print("  systemctl restart zovex-bot")


if __name__ == "__main__":
    main()
