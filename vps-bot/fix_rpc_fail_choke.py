#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_rpc_fail_choke — בוט עם חיבור טלגרם תקול לא מודח, וממשיך להיבחר שוב
ושוב. זה מה שגרם לתקיעות/503 לסירוגין ב"מיניונים ומפלצות" (ובכל תוכן אחר
שנתקל באותו בוט).

## מה נמצא (על content חי, 2026-10-11)

בדקתי את קישור ההזרמה האמיתי של "מיניונים ומפלצות" ישירות, שוב ושוב — 24
בקשות על פני כמה סבבים, כ-25%-50% מהן נתקעו ל-14-28 שניות או נכשלו לגמרי.
בשתי הפעמים שתפסתי 503 בפועל, הגוף היה זהה:

    ChannelsGetMessages נכשל (בוט bot_2): rpcDoRequest: retryUntilAck:
    retry limit reached after 5 attempts

**אותו בוט בדיוק (bot_2), פעמיים תוך כ-10 דקות** — לא "טלגרם באופן כללי".

הסיבה: ‎_get_bot_msg_fast‎ (בוחר-בוט → שולף הודעה, עם תקציב ‎MSG_FETCH_BUDGET‎
ל-choke מיידי) תופס רק ‎asyncio.TimeoutError‎:

    except asyncio.TimeoutError:
        ...
        _mark_choked(bot, 30, hard=True)
        return None

כשל RPC *אמיתי* (לא timeout — Pyrogram עצמו מיצה 5 ניסיונות פנימיים ואז
זרק) **לא נתפס כאן בכלל**. הוא בורח מהפונקציה הזו, ו-‎channel_get_media‎
שקורא לה תופס אותו ברמה גבוהה יותר (‎except Exception‎) — אבל רק *אחרי*
שהבוט כבר נבחר ונכשל, ובלי ה-choke המיידי (‎hard=True‎) שמגיע ל-timeout.
בוט עם session תקוע ברמת ה-RPC (לא רק "לא עונה בזמן") ממשיך לחזור לתור
כל עוד לא נצברו 3 כשלים *רצופים* ברמת ‎channel_get_media‎ — בדיוק הדפוס
שהערות הקוד הקיימות כבר מתעדות עבור timeout ("נמדד: 9 מתוך 21 בוטים
תקועים ← ~43% מהחלונות שילמו 20 שניות"), רק שכאן זה לא timeout.

## מה משתנה

‎_get_bot_msg_fast‎ מקבלת עוד שתי ענפי except, **באותו מקום שבו כבר נתפס
timeout** — לא ברמה גבוהה יותר:

* ‎except FloodWait: raise‎ — ממשיכה לברוח כרגיל. יש לה כבר טיפול ייעודי
  אצל הקורא (‎channel_get_media‎), שמשתמש ב-‎e.value‎ (זמן ההמתנה שטלגרם
  עצמו ביקש) — לא נוגעים בזה.
* ‎except Exception‎ — כל כשל RPC אחר מטופל **בדיוק כמו timeout**: חניקה
  מיידית (‎hard=True‎) ו-‎return None‎, כדי שהקורא יעבור לבוט הבא מיד,
  באותו קצב שכבר קיים לכשל-תקוע. לא ממציא מנגנון חדש — מיישר כשל-RPC
  לטיפול שכבר קיים ועובד לכשל-timeout.

## בטיחות

עוגן ייחודי (נבדק: מופיע פעם אחת בדיוק ב-main.py החי). לפני כתיבה:
קומפילציה מלאה, ובדיקה התנהגותית אמיתית (לא רק "הטקסט נמצא") של שלושת
הענפים — timeout עדיין חונק מיידית בדיוק כמו קודם, כשל RPC כללי עכשיו
*גם* חונק מיידית, ו-FloodWait ממשיך לברוח בלי להיבלע.

**דורש restart** (שינוי קוד ב-main.py). הסקריפט לא מפעיל אותו לבד:

    python3 fix_rpc_fail_choke.py --check
    python3 fix_rpc_fail_choke.py
    systemctl restart zovex-bot     # ← נדרש כדי שהתיקון ייכנס לתוקף
    python3 fix_rpc_fail_choke.py --revert    # (משחזר; restart שוב אחרי)
"""
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_fix_rpc_fail_choke"
MARK = "[fix_rpc_fail_choke]"

EDITS = [
    ('_get_bot_msg_fast: לתפוס כשל RPC, לא רק timeout', 'async def _get_bot_msg_fast(bot, chat_id, message_id):\n    """כמו _get_bot_msg אבל עם תקציב קצר, וחניקה מיידית של בוט שנתקע.\n\n    session תקוע לא מחזיר שגיאה — הוא פשוט לא חוזר, ולכן הוא מתחזה ל"בוט איטי"\n    ולא מודח לעולם. נמדד בשרת: 9 מתוך 21 בוטים במצב הזה ניתבו אליהם ~43%\n    מהחלונות, וכל אחד שילם את מלוא ה-timeout. מחזיר None אם הבוט נתקע.\n    """\n    try:\n        return await asyncio.wait_for(\n            _get_bot_msg(bot, chat_id, message_id), timeout=MSG_FETCH_BUDGET)\n    except asyncio.TimeoutError:\n        # חניקה מיידית (hard) בלי לחכות לשלושה כשלים: עם העונש המתגבר, טעות\n        # על בוט בריא עולה 30 שניות בלבד, בעוד ההמתנה לשלוש מכות עלתה יותר\n        # מדקה של צפייה תקועה בכל סיבוב.\n        log.warning("שליפת ההודעה מ-%s נתקעה (%.0fs) — חונק", bot["name"], MSG_FETCH_BUDGET)\n        note_bot_speed(bot, 0.0)\n        _mark_choked(bot, 30, hard=True)\n        return None', 'async def _get_bot_msg_fast(bot, chat_id, message_id):\n    """כמו _get_bot_msg אבל עם תקציב קצר, וחניקה מיידית של בוט שנתקע.\n\n    session תקוע לא מחזיר שגיאה — הוא פשוט לא חוזר, ולכן הוא מתחזה ל"בוט איטי"\n    ולא מודח לעולם. נמדד בשרת: 9 מתוך 21 בוטים במצב הזה ניתבו אליהם ~43%\n    מהחלונות, וכל אחד שילם את מלוא ה-timeout. מחזיר None אם הבוט נתקע.\n\n    [fix_rpc_fail_choke] עד כה רק asyncio.TimeoutError נתפס כאן — כשל RPC\n    אמיתי (Pyrogram מיצה את הניסיונות הפנימיים שלו, למשל "retryUntilAck:\n    retry limit reached") ברח בלי לחנוק את הבוט, אז בוט תקול המשיך\n    להיבחר שוב ושוב. נמדד בשרת: אותו בוט ספציפי הופיע פעמיים תוך 10\n    דקות עם בדיוק השגיאה הזו. FloodWait ממשיך לברוח כרגיל — יש לה\n    טיפול ייעודי אצל הקורא (channel_get_media), עם זמן ההמתנה שטלגרם\n    עצמו ביקש.\n    """\n    try:\n        return await asyncio.wait_for(\n            _get_bot_msg(bot, chat_id, message_id), timeout=MSG_FETCH_BUDGET)\n    except asyncio.TimeoutError:\n        # חניקה מיידית (hard) בלי לחכות לשלושה כשלים: עם העונש המתגבר, טעות\n        # על בוט בריא עולה 30 שניות בלבד, בעוד ההמתנה לשלוש מכות עלתה יותר\n        # מדקה של צפייה תקועה בכל סיבוב.\n        log.warning("שליפת ההודעה מ-%s נתקעה (%.0fs) — חונק", bot["name"], MSG_FETCH_BUDGET)\n        note_bot_speed(bot, 0.0)\n        _mark_choked(bot, 30, hard=True)\n        return None\n    except FloodWait:\n        raise\n    except Exception as e:\n        log.warning("שליפת ההודעה מ-%s נכשלה (%s) — חונק", bot["name"], e)\n        note_bot_speed(bot, 0.0)\n        _mark_choked(bot, 30, hard=True)\n        return None', 1),
]


def validate(out: str) -> None:
    """קומפילציה מלאה + בדיקה התנהגותית אמיתית של שלושת הענפים ב-
    _get_bot_msg_fast המתוקנת: timeout עדיין חונק מיידית (ללא שינוי),
    כשל RPC כללי עכשיו *גם* חונק מיידית (החדש), ו-FloodWait ממשיך
    לברוח בלי שום דבר יבלע אותה (ללא שינוי)."""
    try:
        compile(out, PATH, "exec")
    except SyntaxError as e:
        sys.exit(f"✗ הקובץ המתוקן לא מתקמפל: {e}")

    assert MARK in out, "התגית [fix_rpc_fail_choke] חסרה"
    assert "except FloodWait:\n        raise" in out, "FloodWait לא ממשיכה לברוח"
    assert out.count("_mark_choked(bot, 30, hard=True)") == 2, \
        "ציפיתי לשני מופעים של חניקה מיידית (timeout + RPC כללי)"

    _test_get_bot_msg_fast(out)


def _test_get_bot_msg_fast(out: str) -> None:
    import asyncio
    import types
    import unittest.mock as mock

    start = out.index("async def _get_bot_msg_fast(")
    lines = out[start:].splitlines(keepends=True)
    body = [lines[0]]
    for ln in lines[1:]:
        if ln.strip() == "" or ln[:1] in (" ", "\t"):
            body.append(ln)
            continue
        break
    fn_src = "".join(body)

    class FloodWait(Exception):
        def __init__(self, value):
            self.value = value
            super().__init__(f"FloodWait {value}")

    choked = []           # (seconds, hard) שנקראו בפועל
    speeds = []

    def fake_mark_choked(bot, seconds, err=None, hard=False, escalate=True):
        choked.append((seconds, hard))

    def fake_note_bot_speed(bot, speed):
        speeds.append(speed)

    async def get_msg_ok(bot, chat_id, message_id):
        return "THE_MESSAGE"

    async def get_msg_hang(bot, chat_id, message_id):
        await asyncio.sleep(10)   # יותר מ-MSG_FETCH_BUDGET שבבדיקה

    async def get_msg_rpc_fail(bot, chat_id, message_id):
        raise RuntimeError(
            "ChannelsGetMessages נכשל (בוט bot_2): rpcDoRequest: "
            "retryUntilAck: retry limit reached after 5 attempts")

    async def get_msg_flood(bot, chat_id, message_id):
        raise FloodWait(17)

    ns = {
        "asyncio": asyncio,
        "log": mock.MagicMock(),
        "MSG_FETCH_BUDGET": 0.05,
        "_mark_choked": fake_mark_choked,
        "note_bot_speed": fake_note_bot_speed,
        "FloodWait": FloodWait,
    }
    bot = {"name": "bot_2"}

    async def run_all():
        # 1) הצלחה רגילה — לא נוגעים בה
        ns["_get_bot_msg"] = get_msg_ok
        exec(compile(fn_src, "<fn>", "exec"), ns)
        r = await ns["_get_bot_msg_fast"](bot, -1, 1)
        assert r == "THE_MESSAGE", "מסלול הצלחה נשבר"
        assert choked == [], "לא אמורה להיות חניקה על הצלחה"

        # 2) timeout — עדיין חונק מיידית (hard=True), כמו קודם
        choked.clear()
        ns["_get_bot_msg"] = get_msg_hang
        r = await ns["_get_bot_msg_fast"](bot, -1, 1)
        assert r is None, "timeout אמור להחזיר None"
        assert choked == [(30, True)], f"timeout אמור לחנוק מיידית, קיבלתי {choked}"

        # 3) כשל RPC כללי (לא timeout, לא FloodWait) — *חדש*: גם חונק מיידית
        choked.clear()
        ns["_get_bot_msg"] = get_msg_rpc_fail
        r = await ns["_get_bot_msg_fast"](bot, -1, 1)
        assert r is None, "כשל RPC אמור להחזיר None (לא לזרוק הלאה)"
        assert choked == [(30, True)], \
            f"כשל RPC אמור לחנוק מיידית בדיוק כמו timeout, קיבלתי {choked}"

        # 4) FloodWait — ממשיכה לברוח, לא נבלעת כאן, לא חונקת מכאן בכלל
        choked.clear()
        ns["_get_bot_msg"] = get_msg_flood
        try:
            await ns["_get_bot_msg_fast"](bot, -1, 1)
            raise AssertionError("FloodWait הייתה אמורה להיזרק הלאה, לא להיבלע")
        except FloodWait as e:
            assert e.value == 17, "FloodWait.value השתנה בדרך"
        assert choked == [], "FloodWait לא אמורה לגרום לחניקה כאן — זה תפקיד הקורא"

    asyncio.run(run_all())


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
    print("⚠ דורש restart כדי שהתיקון ייכנס לתוקף (main.py נטען פעם אחת")
    print("  בעליית התהליך):")
    print("  systemctl restart zovex-bot")


if __name__ == "__main__":
    main()
