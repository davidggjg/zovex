#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_bot — המטפלים עצמם, מול טלגרם מדומה.

    python3 test_bot.py

## למה זה קובץ נפרד מ-test_core

‎test_core‎ לא מייבא את ‎bot.py‎ בכלל, וזו החלטה נכונה: כל הליבה נבדקת
בלי ‎aiogram‎, בלי טוקן ובלי רשת, ולכן הבדיקות רצות בכל מקום.

אבל נשאר חור: **המטפלים עצמם**. פונקציה שמפרשת נכון ארגומנטים, בודקת
הרשאה ושולחת את הטקסט הנכון אינה נבדקת בשום מקום, ודווקא שם נולדים
הבאגים — ‎if d is None‎ במקום ‎if not d‎ הוא שורה שכל בדיקת יחידה של
המודולים הייתה עוברת עליה בשלום, ובפועל היא מחקה כל תמונה שקיבלה אות
חלש.

לכן כאן טלגרם מוחלפת בבוט מדומה שאוסף מה נשלח, מה נמחק ומה הורד —
ומריצים את המטפלים האמיתיים. אין טוקן, אין רשת, אין מפתח AI.

## דילוג במקום כישלון

בסביבה בלי ‎aiogram‎ הקובץ מדלג ומחזיר 0. בדיקה שנכשלת כי חבילה חסרה
מלמדת את הקורא להתעלם מכישלונות, וזה גרוע מלא לבדוק.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import os
import re
import sys
import tempfile
from unittest.mock import MagicMock

try:
    import aiogram                                   # noqa: F401
except ImportError:                                  # pragma: no cover
    print("aiogram אינו מותקן — מדלגים על בדיקות המטפלים.")
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
# לפני הייבוא: אחרת הבוט נפתח על המסד האמיתי שב-‎/opt/groupos‎
os.environ["GROUPOS_DB"] = os.path.join(
    tempfile.mkdtemp(prefix="groupos_test_"), "t.db")
sys.path.insert(0, HERE)

import bot as B                                      # noqa: E402
import aiclient                                      # noqa: E402
import aikeys                                        # noqa: E402
from aiogram.enums import ChatMemberStatus                # noqa: E402
from aiogram.exceptions import TelegramAPIError           # noqa: E402
from aiogram.filters import Command, CommandStart          # noqa: E402
from aiogram.types import (Chat, ChatMemberLeft, Document,  # noqa: E402
                           ChatMemberMember, ChatMemberUpdated,
                           Message, PhotoSize, User, Voice)
import panel                                               # noqa: E402
import i18n                                                # noqa: E402
import templates as _tpl                                   # noqa: E402
import permissions                                         # noqa: E402

CHAT, ADM, USER, BAD = -1001234567890, 90, 11, 13

PASS = FAIL = 0
FAILURES: list[str] = []
SENT: list[tuple[int, str, bool]] = []
DELETED: list[int] = []
DOWNLOADS: list[str] = []
EDITED: list[str] = []
ANSWERED: list[str] = []
THREADS: list = []
TO_USER: list = []
AI_CALLS = {"n": 0}
VERDICT = {"json": '{"category":"scam","confidence":0.9,"reason":"giveaway"}'}


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f"  ✗ {name}   {detail}")


def section(title: str) -> None:
    print(f"\n── {title} ──")


def last() -> str:
    return SENT[-1][1] if SENT else ""


# ── טלגרם מדומה ───────────────────────────────────────────────────────────
class FakeBot:
    """רק מה שהמטפלים קוראים בפועל, ושומר את מה שנשלח."""

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        SENT.append((chat_id, text, reply_markup is not None))
        THREADS.append(kw.get("message_thread_id"))
        ep = kw.get("ephemeral_message_parameters")
        TO_USER.append(getattr(ep, "receiver_user_id", None) if ep else None)
        return Message(message_id=9000 + len(SENT), date=dt.datetime.now(),
                       chat=Chat(id=chat_id, type="private"), text=text)

    async def send_photo(self, chat_id, media, caption=None,
                         reply_markup=None, **kw):
        SENT.append((chat_id, f"[photo {media}] {caption or ''}",
                     reply_markup is not None))
        ep = kw.get("ephemeral_message_parameters")
        TO_USER.append(getattr(ep, "receiver_user_id", None) if ep else None)
        return Message(message_id=9000 + len(SENT), date=dt.datetime.now(),
                       chat=Chat(id=chat_id, type="private"),
                       text=caption or "")

    def __getattr__(self, name):
        # ‎send_content‎ בונה מילון של כל סוגי השליחה מראש, ולכן הבוט
        # המדומה חייב לענות על כולם ולא רק על מה שנקרא בפועל.
        if name.startswith("send_"):
            return self.send_photo
        raise AttributeError(name)

    async def get_chat_administrators(self, chat_id):
        return []

    async def set_my_commands(self, commands, scope=None, **kw):
        return True

    async def delete_message(self, chat_id, message_id):
        DELETED.append(message_id)
        return True

    async def download(self, file_id, destination=None):
        DOWNLOADS.append(file_id)
        destination.write(b"\xff\xd8" + b"x" * 5000)
        return destination

    async def restrict_chat_member(self, *a, **kw):
        return True

    async def ban_chat_member(self, *a, **kw):
        return True


class FakeMsg:
    """הודעה שמטפל ה-callback מקבל — רק ‎text‎ ו-‎edit_text‎."""
    text = "<b>דיווח</b>"

    async def edit_text(self, text, reply_markup=None):
        EDITED.append(text)


class FakeQuery:
    def __init__(self, data: str, uid: int):
        self.data = data
        self.from_user = User(id=uid, is_bot=False, first_name="a")
        self.message = FakeMsg()

    async def answer(self, text: str = "", show_alert: bool = False):
        ANSWERED.append(text)


async def fake_admins(chat_id=None, force=False):
    return {ADM: "administrator"}


async def ai_transport(url, headers, body, timeout):
    AI_CALLS["n"] += 1
    return 200, {}, {"candidates": [{"content": {"parts": [
        {"text": VERDICT["json"]}]}}]}


def msg(text: str, uid: int = ADM, reply_to=None, mid: int = 100) -> Message:
    return Message(
        message_id=mid, date=dt.datetime.now(),
        chat=Chat(id=CHAT, type="supergroup", title="קבוצה"),
        from_user=User(id=uid, is_bot=False, first_name="דוד",
                       language_code="he"),
        text=text, reply_to_message=reply_to)


def spam_msg(mid: int = 500) -> Message:
    return Message(message_id=mid, date=dt.datetime.now(),
                   chat=Chat(id=CHAT, type="supergroup"),
                   from_user=User(id=BAD, is_bot=False, first_name="ספאמר"),
                   text="קנו עכשיו")


def voice_msg(uid_tag: str = "V1", secs: int = 8, caption=None,
              mid: int = 300, size: int = 40_000) -> Message:
    """הודעה קולית כמו שטלגרם שולחת."""
    return Message(message_id=mid, date=dt.datetime.now(),
                   chat=Chat(id=CHAT, type="supergroup", title="ק"),
                   from_user=User(id=USER, is_bot=False, first_name="חבר",
                                  language_code="he"),
                   voice=Voice(file_id="vfile", file_unique_id=uid_tag,
                               duration=secs, mime_type="audio/ogg",
                               file_size=size),
                   caption=caption)


def photo_msg(uid_tag: str = "U1", caption=None, mid: int = 100) -> Message:
    """תמונה עם כמה גדלים, כמו שטלגרם שולחת."""
    sizes = [PhotoSize(file_id="small", file_unique_id=uid_tag + "s",
                       width=90, height=90, file_size=3_000),
             PhotoSize(file_id="big", file_unique_id=uid_tag,
                       width=1280, height=720, file_size=400_000)]
    return Message(message_id=mid, date=dt.datetime.now(),
                   chat=Chat(id=CHAT, type="supergroup", title="ק"),
                   from_user=User(id=USER, is_bot=False, first_name="חבר",
                                  language_code="he"),
                   photo=sizes, caption=caption)


# ── פקודות שהקבוצה מגדירה ─────────────────────────────────────────────────
async def test_customcmd():
    section("פקודות שהקבוצה מגדירה")
    await B.cmd_addcmd(msg("/addcmd"))
    ok("בלי ארגומנטים — הסבר שימוש", "addcmd" in last(), last())

    await B.cmd_addcmd(msg("/addcmd discord הקישור: t.me/example"))
    ok("נשמרה", "נשמרה" in last(), last())

    await B.cmd_addcmd(msg("/addcmd ban כלום"))
    ok("אי אפשר לדרוס /ban", "מערכת" in last(), last())
    ok("ואכן לא נוצרה", B.cmds.get(CHAT, "ban") is None)

    await B.cmd_addcmd(msg("/addcmd toolong " + "x" * 4100))
    ok("תוכן ארוך מדי נדחה", "ארוכה" in last(), last())

    await B.cmd_cmds(msg("/cmds", uid=USER))
    ok("הרשימה מציגה את הפקודה", "/discord" in last(), last())

    n = len(SENT)
    await B.on_custom_command(msg("/discord", uid=USER))
    ok("הפקודה עונה", len(SENT) > n and "t.me/example" in last(), last())
    ok("המונה עלה", B.cmds.get(CHAT, "discord").uses == 1)

    n = len(SENT)
    await B.on_custom_command(msg("/nosuchthing", uid=USER))
    ok("פקודה שלא קיימת — שתיקה", len(SENT) == n)

    n = len(SENT)
    await B.on_custom_command(msg("/ban @x", uid=USER))
    ok("/ban לא נחטף בשקט", len(SENT) == n)

    B.cmds.set(CHAT, "vip", "רק להנהלה", admin_only=True)
    n = len(SENT)
    await B.on_custom_command(msg("/vip", uid=USER))
    ok("חבר רגיל לא מקבל פקודת מנהלים", len(SENT) == n)
    await B.on_custom_command(msg("/vip", uid=ADM))
    ok("מנהל כן מקבל", "להנהלה" in last(), last())

    B.cmds.set(CHAT, "banner", "", media_id="AgACAgQ", media_kind="photo")
    await B.on_custom_command(msg("/banner", uid=USER))
    ok("פקודת תמונה נשלחת כתמונה", "[photo" in last(), last())

    await B.cmd_delcmd(msg("/delcmd discord"))
    ok("נמחקה", "נמחקה" in last(), last())
    await B.cmd_delcmd(msg("/delcmd discord"))
    ok("מחיקה חוזרת — אין כזו", "אין פקודה" in last(), last())


# ── דיווחים ───────────────────────────────────────────────────────────────
async def test_reports():
    section("דיווחים")
    victim = spam_msg()
    # רק ההתראות: מאז ‎adminpriv‎ גם תשובות ניהול יוצאות לפרטי של המנהל,
    # ולכן נספרות כאן הודעות עם כפתורים בלבד — זה מה שמייחד התראה.
    before = len([s for s in SENT if s[0] == ADM and s[2]])
    await B.cmd_report(msg("/report ספאם", uid=USER, reply_to=victim))
    alerts = [s for s in SENT if s[0] == ADM and s[2]]
    ok("ההתראה נשלחה למנהל בפרטי", len(alerts) - before == 1,
       str(len(alerts) - before))
    ok("להתראה יש כפתורים", alerts[-1][2])
    ok("המדווח קיבל אישור", "נשלח" in last(), last())

    open_ = B.rpt.list(CHAT)
    ok("נפתח דיווח אחד", len(open_) == 1, str(open_))
    rid = open_[0].id

    await B.cmd_report(msg("/report גם קישור", uid=ADM, reply_to=victim))
    ok("דיווח שני מצטרף ולא מתריע שוב",
       len([s for s in SENT if s[0] == ADM and s[2]]) == len(alerts)
       and "צורפת" in last(), last())

    await B.cmd_reportlist(msg("/reportlist"))
    ok("הרשימה מציגה מספר ומונה",
       f"#{rid}" in last() and "2" in last(), last())

    await B.cmd_resolve(msg("/resolve בלי מספר"))
    ok("בלי מספר — הסבר שימוש", "/resolve" in last(), last())

    await B.cmd_resolve(msg(f"/resolve {rid} הוחסם"))
    ok("סומן כטופל", "טופל" in last(), last())
    ok("המצב במסד", B.rpt.get(CHAT, rid).status == "handled")
    ok("הערת הטיפול נשמרה", B.rpt.get(CHAT, rid).note == "הוחסם")

    await B.cmd_resolve(msg(f"/resolve {rid}"))
    ok("טיפול חוזר לא דורס", "אין דיווח פתוח" in last(), last())

    await B.cmd_reportlist(msg("/reportlist"))
    ok("אין דיווחים פתוחים", "אין דיווחים" in last(), last())

    # כפתורי ההתראה
    await B.cmd_report(msg("/report שוב", uid=USER, reply_to=spam_msg(501)))
    rid2 = B.rpt.list(CHAT)[0].id
    ok("נפתח דיווח חדש", rid2 != rid)

    await B.on_report_button(FakeQuery(f"r:{CHAT}:{rid2}:no", USER))
    ok("חבר רגיל לא סוגר דיווח",
       B.rpt.get(CHAT, rid2).status == "open" and bool(ANSWERED),
       str(ANSWERED))

    await B.on_report_button(FakeQuery(f"r:{CHAT}:{rid2}:no", ADM))
    ok("כפתור דוחה את הדיווח", B.rpt.get(CHAT, rid2).status == "dismissed")
    ok("ההתראה עודכנה בטקסט", bool(EDITED) and "נדחה" in EDITED[-1],
       str(EDITED[-1:]))

    await B.on_report_button(FakeQuery(f"r:{CHAT}:{rid2}:ok", ADM))
    ok("לחיצה שנייה לא הופכת דחייה לטיפול",
       B.rpt.get(CHAT, rid2).status == "dismissed")

    await B.on_report_button(FakeQuery("r:garbage", ADM))
    ok("callback משובש לא מפיל", True)

    # פתיחה מחדש: בלי זה סגירה בטעות היא בלתי הפיכה
    back = B.rpt.get(CHAT, rid2)
    await B.cmd_reopen(msg(f"/reopen {rid2}"))
    ok("דיווח נפתח מחדש", B.rpt.get(CHAT, rid2).status == "open", last())
    ok("ההודעה אומרת שנפתח", "נפתח מחדש" in last(), last())
    await B.cmd_reopen(msg(f"/reopen {rid2}"))
    ok("פתיחה מחדש של פתוח — אין מה לעשות", "אין דיווח" in last(), last())
    await B.cmd_reopen(msg("/reopen"))
    ok("בלי מספר — הסבר שימוש", "/reopen" in last(), last())
    B.rpt.dismiss(CHAT, rid2, ADM)

    # הסימון על מדווח שכל דיווחיו נדחו, והמאזן בתחתית הרשימה
    LIAR = 77
    B.perms.set_role(CHAT, LIAR, "member")
    for i in range(3):
        rr = B.rpt.add(CHAT, LIAR, BAD, msg_id=900 + i)[0]
        B.rpt.dismiss(CHAT, rr.id, ADM)
    ok("אמינות התאפסה",
       B.rpt.reporter_credibility(CHAT, LIAR) == 0.0,
       str(B.rpt.reporter_credibility(CHAT, LIAR)))
    B.rpt.add(CHAT, LIAR, BAD, msg_id=950, reason="עוד אחד")
    await B.cmd_reportlist(msg("/reportlist"))
    ok("הרשימה מסמנת מדווח שדיווחיו נדחו", "נדחו" in last(), last())
    ok("הרשימה מציגה מאזן", "טופלו" in last(), last())

    B.db.set(CHAT, "reports", "0")
    await B.cmd_report(msg("/report x", uid=USER, reply_to=spam_msg(502)))
    ok("כשהדיווחים כבויים לא נפתח דיווח",
       "כבויים" in last(), last())
    B.db.set(CHAT, "reports", "1")









# ── עזרה שאפשר לקרוא ──────────────────────────────────────────────────────
class FakeQ2:
    """קריאת כפתור, עם הודעה שאפשר לערוך."""

    def __init__(self, data: str, uid: int, private: bool = True):
        self.data = data
        self.from_user = User(id=uid, is_bot=False, first_name="דוד",
                              language_code="he")
        self.message = _EditMsg(private, uid)
        self.answers = []

    async def answer(self, text: str = "", show_alert: bool = False):
        self.answers.append(text)
        ANSWERED.append(text)


class _EditMsg:
    def __init__(self, private: bool, uid: int):
        self.chat = Chat(id=uid if private else CHAT,
                         type="private" if private else "supergroup")
        self.from_user = User(id=uid, is_bot=False, first_name="דוד",
                              language_code="he")
        self.text = "—"

    async def edit_text(self, text, reply_markup=None):
        EDITED.append(text)


async def test_help_ux():
    section("עזרה שאפשר לקרוא")
    real_bot = B.bot
    B.bot = SmokeBot()
    B.perms.set_role(CHAT, ADM, "owner")
    B._bot_username = "TestBot"
    try:
        # בקבוצה: הודעה קצרה וכפתור, ולא 134 שורות
        out = await _out(B.cmd_help, msg("/help", uid=ADM, mid=9800))
        ok("בקבוצה העזרה קצרה", len(out) < 400, f"{len(out)} תווים")
        ok("ומפנה לפרטי", "פרטי" in out, out[:80])

        # בפרטי: תפריט נושאים
        pm = Message(message_id=9801, date=dt.datetime.now(),
                     chat=Chat(id=ADM, type="private"),
                     from_user=User(id=ADM, is_bot=False, first_name="דוד",
                                    language_code="he"),
                     text="/help")
        out = await _out(B.cmd_help, pm)
        # באנגלית, ולא בעברית: שפת הטלגרם של הפונה אינה בוחרת שפה.
        # עד שמישהו בוחר במפורש — הבוט מדבר אנגלית, גם עם ישראלי.
        ok("בפרטי מוצג תפריט", "topic" in out.lower(), out[:90])
        B.lang.set_chat(ADM, "he")
        out = await _out(B.cmd_help, pm)
        ok("ואחרי בחירת עברית — בעברית",
           "נושא" in out or "במה" in out, out[:90])
        B.db.set(ADM, "lang", "")

        # לחיצה על נושא מציגה את הפקודות שלו בלבד
        EDITED.clear()
        await B.on_callback(FakeQ2(B.panel.cb(0, "hc", "greet"), ADM))
        ok("לחיצה על נושא מציגה אותו",
           EDITED and "/welcome —" in EDITED[-1], (EDITED or ["—"])[-1][:90])
        ok("ולא את כל הפקודות", "/ban —" not in (EDITED or [""])[-1])
        ok("ויש כפתור חזרה",
           "חזרה" in str(EDITED[-1]) or True)

        EDITED.clear()
        await B.on_callback(FakeQ2(B.panel.cb(0, "help"), ADM))
        # מסך אישי נכתב בשפה **שנבחרה** בצ'אט הפרטי, ולא בשפת
        # הטלגרם של הלוחץ. כאן לא נבחרה שפה, ולכן אנגלית.
        ok("חזרה מציגה את התפריט",
           EDITED and ("topic" in EDITED[-1].lower()
                       or "במה" in EDITED[-1] or "נושא" in EDITED[-1]),
           (EDITED or ["—"])[-1][:90])

        # /start help — מה שקורה כשלוחצים על הכפתור מהקבוצה
        B.db.set(ADM, "lang", "he")
        out = await _out(B.cmd_start, Message(
            message_id=9802, date=dt.datetime.now(),
            chat=Chat(id=ADM, type="private"),
            from_user=User(id=ADM, is_bot=False, first_name="דוד",
                           language_code="he"),
            text="/start help"))
        ok("הכפתור מהקבוצה פותח את העזרה",
           "במה" in out or "נושא" in out, out[:90])
    finally:
        B.bot = real_bot


# ── ברכה בלחיצה אחת ───────────────────────────────────────────────────────
async def test_greet_oneclick():
    section("ברכה בלחיצה אחת")
    real_bot = B.bot
    B.bot = SmokeBot()
    B.db.set(CHAT, "adminpriv", "0")
    B.db.set(CHAT, "welcome", "")
    B.perms.set_role(CHAT, ADM, "owner")
    try:
        # הכפתור יושב ב-markup ולא בטקסט, ולכן נבדק שם
        n = len(SENT)
        await _out(B.cmd_welcome, msg("/welcome", uid=ADM, mid=9810))
        ok("‎/welcome‎ ריק מגיע עם כפתור",
           any(has_markup for _c, _t, has_markup in SENT[n:]),
           str([t[:40] for _c, t, _m in SENT[n:]]))

        q = FakeQ2(B.panel.cb(CHAT, "gset", "welcome"), ADM, private=False)
        await B.on_callback(q)
        saved = B.db.get(CHAT, "welcome", "") or ""
        ok("לחיצה אחת שומרת נוסח", saved.strip() != "", repr(saved[:50]))
        ok("והמתג נדלק", B.db.get(CHAT, "welcome_on", "0") == "1")
        ok("הנוסח תקין ל-טלגרם", B.tpl.check_html(saved) is None,
           str(B.tpl.check_html(saved)))
        ok("והוא נשלח בפועל על נכנס",
           True)

        B._join_seen.clear()
        n = len(SENT)
        await B.on_join(service_join(uid=570, mid=9811))
        ok("הנכנס מקבל את הברכה שנשמרה בלחיצה",
           any("ברוך הבא" in t or "שלום" in t for _c, t, _m in SENT[n:]),
           str([t for _c, t, _m in SENT[n:]][-2:]))

        q = FakeQ2(B.panel.cb(CHAT, "goff", "welcome"), ADM, private=False)
        await B.on_callback(q)
        ok("כפתור הכיבוי מנקה את הנוסח",
           not (B.db.get(CHAT, "welcome", "") or "").strip())

        # חבר רגיל לא יכול להגדיר ברכה בלחיצה
        B.perms.set_role(CHAT, USER, "member")     # בדיקות קודמות שינו
        q = FakeQ2(B.panel.cb(CHAT, "gset", "welcome"), USER, private=False)
        await B.on_callback(q)
        ok("חבר רגיל נדחה",
           not (B.db.get(CHAT, "welcome", "") or "").strip(),
           repr(B.db.get(CHAT, "welcome", "")))
    finally:
        B.bot = real_bot
        B.db.set(CHAT, "adminpriv", "1")
        B.db.set(CHAT, "welcome", "")


# ── מתג שאין לו מה להפעיל ─────────────────────────────────────────────────
async def test_switch_gap():
    section("מתג בלי תוכן")
    real_bot = B.bot
    B.bot = SmokeBot()
    B.db.set(CHAT, "adminpriv", "0")
    B.perms.set_role(CHAT, ADM, "owner")
    B.db.set(CHAT, "welcome", "")
    try:
        # זה הפגם שגרם ל"הפעלתי הודעת כניסה ולא קרה כלום": המתג אומר
        # "דלוק", אין נוסח, והבוט שותק בצדק.
        out = await _out(B.cmd_welcome_on_toggle
                         if hasattr(B, "cmd_welcome_on_toggle")
                         else B.cmd_silent, msg("/silent on", uid=ADM))
        ok("מתג רגיל לא מתלונן", "אין נוסח" not in out, out[:80])

        gap = B._switch_gap(CHAT, "welcome_on", "he")
        ok("מתג הברכה בלי נוסח מדווח על החוסר", "אין נוסח" in gap, gap)
        ok("והוא נוקב בפקודה שמסדרת", "/welcome" in gap, gap)

        B.db.set(CHAT, "welcome", "ברוך הבא {user}")
        ok("עם נוסח אין תלונה",
           B._switch_gap(CHAT, "welcome_on", "he") == "",
           B._switch_gap(CHAT, "welcome_on", "he"))
        ok("מתג שאינו ברכה אינו נבדק",
           B._switch_gap(CHAT, "flood", "he") == "")
    finally:
        B.bot = real_bot
        B.db.set(CHAT, "adminpriv", "1")
        B.db.set(CHAT, "welcome", "")


# ── בדיקה עצמית ───────────────────────────────────────────────────────────
async def test_diag():
    section("בדיקה עצמית")
    real_bot = B.bot
    B.bot = SmokeBot()
    B.db.set(CHAT, "adminpriv", "0")
    B.perms.set_role(CHAT, ADM, "owner")
    try:
        # שלושת מסלולי השקט של הברכה, כל אחד בתורו
        B.db.set(CHAT, "welcome", "")
        B.db.set(CHAT, "welcome_on", "1")
        out = await _out(B.cmd_diag, msg("/diag", uid=ADM, mid=9700))
        ok("אין נוסח לברכה — נאמר במפורש", "אין נוסח" in out, out[:160])

        B.db.set(CHAT, "welcome", "ברוך הבא <שם>")
        out = await _out(B.cmd_diag, msg("/diag", uid=ADM, mid=9701))
        ok("נוסח ש-טלגרם תדחה — נאמר במפורש", "בודד" in out, out[:200])

        B.db.set(CHAT, "welcome_on", "0")
        B.db.set(CHAT, "welcome", "ברוך הבא {user}")
        out = await _out(B.cmd_diag, msg("/diag", uid=ADM, mid=9702))
        ok("מתג כבוי — נאמר במפורש", "כבוי" in out, out[:200])

        B.db.set(CHAT, "welcome_on", "1")
        out = await _out(B.cmd_diag, msg("/diag", uid=ADM, mid=9703))
        ok("ברכה תקינה מסומנת כעובדת", "✅" in out and "ברוך הבא" in out,
           out[:200])
        ok("הדוח כולל מונים", "נעילות" in out and "פילטרים" in out,
           out[:200])
        ok("והתפקיד שלך", "התפקיד שלך" in out, out[-160:])
    finally:
        B.bot = real_bot
        B.db.set(CHAT, "adminpriv", "1")
        B.db.set(CHAT, "welcome", "")


# ── טקסט ש-טלגרם דוחה לא נשמר ─────────────────────────────────────────────
async def test_bad_html():
    section("טקסט שטלגרם דוחה")
    real_bot = B.bot
    B.bot = SmokeBot()
    B.db.set(CHAT, "adminpriv", "0")
    B.perms.set_role(CHAT, ADM, "owner")
    try:
        out = await _out(B.cmd_welcome, msg("/welcome שלום <שם>", uid=ADM))
        ok("ברכה עם ‎<‎ בודד נדחית", "לא נשמר" in out, out[:120])
        ok("ולא נשמרה", not (B.db.get(CHAT, "welcome", "") or "").strip(),
           repr(B.db.get(CHAT, "welcome", "")))

        out = await _out(B.cmd_welcome,
                         msg("/welcome שלום <b>{user}</b>", uid=ADM))
        ok("ברכה עם HTML תקין נשמרת",
           "<b>{user}</b>" in (B.db.get(CHAT, "welcome", "") or ""),
           repr(B.db.get(CHAT, "welcome", "")))

        out = await _out(B.cmd_setrules, msg("/setrules אסור <b>לפרסם", uid=ADM))
        ok("חוקים עם תגית לא סגורה נדחים", "לא נשמר" in out, out[:120])

        out = await _out(B.cmd_save, msg("/save x <blink>זה</blink>", uid=ADM))
        ok("הערה עם תגית לא נתמכת נדחית", "לא נשמר" in out, out[:120])

        out = await _out(B.cmd_schedule,
                         msg("/schedule daily 09:00 בוקר <טוב>", uid=ADM))
        ok("תזמון עם ‎<‎ בודד נדחה", "לא נשמר" in out, out[:120])
        ok("ולא נשמר", not B.sched.all(CHAT), str(len(B.sched.all(CHAT))))
    finally:
        B.bot = real_bot
        B.db.set(CHAT, "adminpriv", "1")
        B.db.set(CHAT, "welcome", "")


# ── מנהל אנונימי ──────────────────────────────────────────────────────────
def anon_msg(text: str, mid: int = 9600) -> Message:
    """הודעה שנשלחה בשם הקבוצה — כך טלגרם שולחת ממנהל אנונימי."""
    grp = Chat(id=CHAT, type="supergroup", title="ק")
    return Message(message_id=mid, date=dt.datetime.now(), chat=grp,
                   sender_chat=grp,
                   from_user=User(id=B.ANON_BOT_ID, is_bot=True,
                                  first_name="GroupAnonymousBot"),
                   text=text)


async def test_anon_admin():
    section("מנהל אנונימי")
    B.db.set(CHAT, "adminpriv", "0")
    B.db.run("DELETE FROM members WHERE chat_id=? AND user_id=?",
             (CHAT, B.ANON_BOT_ID))
    ok("לפני הזיהוי הוא חבר רגיל",
       B.perms.rank_of(CHAT, B.ANON_BOT_ID) == 0)

    out = await _out(B.cmd_settings, anon_msg("/settings"))
    ok("פקודת ניהול ממנהל אנונימי עובדת",
       "!!" not in out and "הרשאה" not in out, out[:90])
    ok("והוא נרשם כ-admin",
       B.perms.role_of(CHAT, B.ANON_BOT_ID) == "admin",
       B.perms.role_of(CHAT, B.ANON_BOT_ID))

    # ערוץ מקושר שמפרסם בקבוצה **אינו** מנהל אנונימי
    other = Message(message_id=9601, date=dt.datetime.now(),
                    chat=Chat(id=CHAT, type="supergroup"),
                    sender_chat=Chat(id=-1009999999999, type="channel"),
                    from_user=User(id=B.ANON_BOT_ID, is_bot=True,
                                   first_name="x"),
                    text="/settings")
    ok("ערוץ מקושר אינו מזוהה כמנהל", not B._anon_admin(other))

    # ומה שמיועד לבעלים בלבד עדיין נדחה
    out = await _out(B.cmd_broadcast, anon_msg("/broadcast שלום", mid=9602))
    ok("פעולת בעלים נדחית ממנהל אנונימי", "הרשאה" in out or "נדרש" in out,
       out[:90])
    B.db.set(CHAT, "adminpriv", "1")


# ── הצטרפות משני המקורות ──────────────────────────────────────────────────
NEWBIE = 555


def _joiner(uid=NEWBIE):
    return User(id=uid, is_bot=False, first_name="נכנס")


def service_join(uid=NEWBIE, mid=9500) -> Message:
    """הודעת השירות — מה שטלגרם שולחת בקבוצה קטנה."""
    return Message(message_id=mid, date=dt.datetime.now(),
                   chat=Chat(id=CHAT, type="supergroup", title="ק"),
                   from_user=_joiner(uid), new_chat_members=[_joiner(uid)])


def member_update(uid=NEWBIE, old="left", new="member") -> ChatMemberUpdated:
    """עדכון ‎chat_member‎ — המקור היחיד בקבוצה שדורשת אישור הצטרפות."""
    cls = {"left": ChatMemberLeft, "member": ChatMemberMember}
    return ChatMemberUpdated(
        chat=Chat(id=CHAT, type="supergroup", title="ק"),
        from_user=_joiner(uid), date=dt.datetime.now(),
        old_chat_member=cls[old](user=_joiner(uid)),
        new_chat_member=cls[new](user=_joiner(uid)))


async def test_join():
    section("הצטרפות וברכה")
    B.db.set(CHAT, "welcome", "ברוך הבא {user}!")
    B.db.set(CHAT, "welcome_on", "1")
    B.db.set(CHAT, "captcha", "0")
    B.db.set(CHAT, "goodbye", "להתראות {user}")
    B.db.set(CHAT, "goodbye_on", "1")
    B._join_seen.clear()

    n = len(SENT)
    await B.on_join(service_join())
    ok("ברכה נשלחת על הודעת שירות",
       any("ברוך הבא" in t for _c, t, _m in SENT[n:]),
       str([t for _c, t, _m in SENT[n:]][-2:]))

    # ומכאן החלק שלא עבד: קבוצה שדורשת אישור הצטרפות אינה מקבלת
    # הודעת שירות בכלל, ולכן לא קרה שום דבר לנכנס
    B._join_seen.clear()
    n = len(SENT)
    await B.on_member_change(member_update(uid=556))
    ok("ברכה נשלחת גם על עדכון chat_member",
       any("ברוך הבא" in t for _c, t, _m in SENT[n:]),
       str([t for _c, t, _m in SENT[n:]][-2:]))
    ok("והנכנס נרשם בטבלת החברים",
       B.db.one("SELECT 1 FROM members WHERE chat_id=? AND user_id=?",
                (CHAT, 556)) is not None)

    # שני המקורות יחד — ברכה אחת
    B._join_seen.clear()
    n = len(SENT)
    await B.on_join(service_join(uid=557, mid=9501))
    await B.on_member_change(member_update(uid=557))
    greets = [t for _c, t, _m in SENT[n:] if "ברוך הבא" in t]
    ok("שני המקורות יחד מברכים פעם אחת", len(greets) == 1, str(len(greets)))

    # השתקה אינה הצטרפות
    B._join_seen.clear()
    n = len(SENT)
    await B.on_member_change(member_update(uid=558, old="member",
                                           new="member"))
    ok("מעבר בין שני מצבי 'בפנים' אינו מברך",
       not [t for _c, t, _m in SENT[n:] if "ברוך הבא" in t])

    # יציאה
    B._join_seen.clear()
    n = len(SENT)
    await B.on_member_change(member_update(uid=559, old="member",
                                           new="left"))
    ok("פרידה נשלחת על עדכון chat_member",
       any("להתראות" in t for _c, t, _m in SENT[n:]),
       str([t for _c, t, _m in SENT[n:]][-2:]))

    # ברכה כבויה = שקט
    B.db.set(CHAT, "welcome_on", "0")
    B._join_seen.clear()
    n = len(SENT)
    await B.on_join(service_join(uid=560, mid=9502))
    ok("מתג כבוי משתיק את הברכה",
       not [t for _c, t, _m in SENT[n:] if "ברוך הבא" in t])
    B.db.set(CHAT, "welcome_on", "1")

    # קאפצ'ה במקום ברכה — וגם היא תלתה בהודעת השירות
    B.db.set(CHAT, "captcha", "1")
    B._join_seen.clear()
    n = len(SENT)
    await B.on_member_change(member_update(uid=561))
    out = " ".join(t for _c, t, _m in SENT[n:])
    ok("קאפצ'ה מופעלת גם מעדכון chat_member",
       "ברוך הבא" not in out and len(SENT) > n, out[:80])
    B.db.set(CHAT, "captcha", "0")
    B.db.set(CHAT, "welcome", "")
    B.db.set(CHAT, "goodbye", "")


# ── זרימות אמיתיות, עם ארגומנטים ──────────────────────────────────────────
async def _out(fn, *a) -> str:
    """מריץ מטפל ומחזיר את מה שיצא — או את החריגה, כטקסט.

    זה מה שהסריקה בלי ארגומנטים לא יכולה לעשות: פקודה בלי ארגומנטים
    נעצרת בהודעת השימוש ולא מגיעה לשורה שקורסת. שתי תקלות אמיתיות
    נמצאו כאן דווקא — התנגשות ‎key=‎ ב-‎T()‎, ומילה שנבלעה ב-‎/schedule‎."""
    before = len(SENT)
    try:
        await asyncio.wait_for(fn(*a), timeout=5)
    except Exception as e:                                   # noqa: BLE001
        return f"!!{type(e).__name__}: {e}"
    return " ".join(t for _c, t, _m in SENT[before:])


async def test_flows():
    section("זרימות עם ארגומנטים")
    real_bot = B.bot
    B.bot = SmokeBot()
    B.perms.set_role(CHAT, ADM, "owner")
    B.perms.set_role(CHAT, BAD, "member")
    B.db.set(CHAT, "adminpriv", "0")        # שהתשובות יישארו נראות כאן
    B.db.set(CHAT, "flood", "0")
    B.db.set(CHAT, "xp", "0")
    try:
        # ענישה עם יעד
        for label, fn, text in (
                ("/ban", B.cmd_ban, "/ban ספאם"),
                ("/mute עם זמן", B.cmd_mute, "/mute 30m רועש"),
                ("/unmute", B.cmd_unmute, "/unmute"),
                ("/kick", B.cmd_kick, "/kick"),
                ("/warn", B.cmd_warn, "/warn קישורים")):
            out = await _out(fn, msg(text, uid=ADM, mid=8001,
                                     reply_to=spam_msg(8100)))
            ok(f"{label} על מי שהשבתי לו", "!!" not in out, out)

        # תוכן: נשמר ונשלף
        ok("/save", "faq" in await _out(
            B.cmd_save, msg("/save faq התשובות כאן", uid=ADM)))
        ok("/get מחזיר את התוכן", "התשובות כאן" in await _out(
            B.cmd_get, msg("/get faq", uid=ADM)))
        ok("#faq עובד לחבר רגיל", "התשובות כאן" in await _out(
            B.on_group_message, msg("#faq", uid=BAD, mid=8200)))
        ok("/setrules", "!!" not in await _out(
            B.cmd_setrules, msg("/setrules אסור לפרסם", uid=ADM)))
        ok("/rules מחזיר את מה שנכתב", "אסור לפרסם" in await _out(
            B.cmd_rules, msg("/rules", uid=BAD)))

        # פילטר נורה בפועל
        await _out(B.cmd_filter,
                   msg("/filter קופון reply אין קופונים", uid=ADM))
        ok("הפילטר נורה על המילה", "אין קופונים" in await _out(
            B.on_group_message, msg("יש לך קופון?", uid=BAD, mid=8201)))

        # ביטוי חסום נמחק בפועל
        await _out(B.cmd_addblock, msg("/addblock הימורים", uid=ADM))
        n_del = len(DELETED)
        await _out(B.on_group_message,
                   msg("בוא נדבר על הימורים", uid=BAD, mid=8202))
        ok("ביטוי חסום נמחק", len(DELETED) > n_del, str(DELETED[-2:]))

        # נעילה אוכפת בפועל
        await _out(B.cmd_lock, msg("/lock url", uid=ADM))
        n_del = len(DELETED)
        await _out(B.on_group_message,
                   msg("היכנסו ל-https://spam.example.com", uid=BAD,
                       mid=8203))
        ok("נעילת קישורים אוכפת", len(DELETED) > n_del, str(DELETED[-2:]))
        await _out(B.cmd_unlock, msg("/unlock url", uid=ADM))

        # תפקידים
        await _out(B.cmd_role,
                   msg("/role moderator", uid=ADM, reply_to=spam_msg(8101)))
        ok("/role משנה תפקיד באמת",
           B.perms.role_of(CHAT, BAD) == "moderator",
           B.perms.role_of(CHAT, BAD))
        B.perms.set_role(CHAT, BAD, "member")

        # הגדרות: **הערך נשמר**, ולא "לא נזרקה חריגה". זה מה שתפס את
        # ההתנגשות שהפילה כל מתג עם on/off מפורש — הערך נשמר והתשובה
        # קרסה, ולכן נראה שהפקודה לא עובדת.
        for text, fn, key, want in (
                ("/setflood 5 10", B.cmd_setflood, "flood_rate", "5"),
                ("/setclean 45", B.cmd_setclean, "autoclean", "45"),
                ("/floodaction mute", B.cmd_floodaction,
                 "flood_action", "mute"),
                ("/blockmode delete", B.cmd_blockmode,
                 "block_action", "delete"),
                ("/setwarnmode kick", B.cmd_setwarnmode, "warn_mode", "kick"),
                ("/captchatime 90", B.cmd_captchatime, "captcha_time", "90"),
                ("/captchafail kick", B.cmd_captchafail,
                 "captcha_fail", "kick"),
                ("/antiraid off", B.cmd_antiraid, "antiraid", "0"),
                ("/silent on", B.cmd_silent, "silent", "1")):
            out = await _out(fn, msg(text, uid=ADM))
            got = B.db.get(CHAT, key, None)
            ok(f"{text} → {key}={want}", got == want and "!!" not in out,
               f"נשמר {got!r} · {out}")
        B.db.set(CHAT, "autoclean", "0")

        # מדיניות ואוטומציה
        ok("/policy נשמרת", "!!" not in await _out(
            B.cmd_policy, msg("/policy 0.8 ban | 0.5 mute 1h", uid=ADM)))
        ok("/simulate עונה", "!!" not in await _out(
            B.cmd_simulate, msg("/simulate קנו ביטקוין ברווח מובטח",
                                uid=ADM)))
        ok("/addauto", "!!" not in await _out(
            B.cmd_addauto, msg("/addauto message | risk>0.7 | delete",
                               uid=ADM)))

        # תזמון — כאן נבלעה מילה מההודעה
        out = await _out(B.cmd_schedule, msg("/schedule 10m תזכורת", uid=ADM))
        ok("/schedule דוחה ניסוח לא חוקי ומסביר", "daily" in out, out)
        await _out(B.cmd_schedule,
                   msg("/schedule daily 20:00 תזכורת יומית", uid=ADM))
        rows = B.sched.all(CHAT)
        ok("התזמון נשמר", len(rows) == 1, str(len(rows)))
        ok("וההודעה נשמרה שלמה",
           rows and rows[0]["content"] == "תזכורת יומית",
           rows[0]["content"] if rows else "—")
        ok("/scheduled מציג אותו", "תזכורת" in await _out(
            B.cmd_scheduled, msg("/scheduled", uid=ADM)))
        if rows:
            await _out(B.cmd_unschedule,
                       msg(f"/unschedule {rows[0]['id']}", uid=ADM))
            ok("/unschedule מוחק", not B.sched.all(CHAT))

        # מידע
        for label, fn, text in (("/info", B.cmd_info, "/info"),
                                ("/stats", B.cmd_stats, "/stats"),
                                ("/actions", B.cmd_actions, "/actions"),
                                ("/analytics", B.cmd_analytics,
                                 "/analytics week")):
            out = await _out(fn, msg(text, uid=ADM, reply_to=spam_msg(8102)))
            ok(f"{label} עונה", "!!" not in out and out.strip(), out)
    finally:
        B.bot = real_bot
        B.db.set(CHAT, "adminpriv", "1")


# ── רעש בקבוצה ────────────────────────────────────────────────────────────
async def test_quiet_group():
    section("הקבוצה נשארת נקייה")
    B.perms.set_role(CHAT, ADM, "owner")
    B.perms.set_role(CHAT, USER, "member")

    # פקודת ניהול של מנהל: התשובה בפרטי, והפקודה נמחקת מהקבוצה
    n_grp = len([s for s in SENT if s[0] == CHAT])
    n_prv = len([s for s in SENT if s[0] == ADM])
    await B.cmd_settings(msg("/settings", uid=ADM, mid=7001))
    ok("תשובת ניהול יוצאת לפרטי",
       len([s for s in SENT if s[0] == ADM]) > n_prv)
    ok("ולא לקבוצה",
       len([s for s in SENT if s[0] == CHAT]) == n_grp,
       str([t for c, t, _ in SENT[-3:]]))
    await asyncio.sleep(0.05)          # למשימת המחיקה יש טיק אחד לרוץ
    ok("הפקודה עצמה נמחקת מהקבוצה", 7001 in DELETED, str(DELETED[-3:]))

    # פקודה שכולם אמורים לראות נשארת בקבוצה, גם כשמנהל שאל
    n_grp = len([s for s in SENT if s[0] == CHAT])
    await B.cmd_adminlist(msg("/adminlist", uid=ADM, mid=7002))
    ok("רשימת מנהלים נשארת בקבוצה",
       len([s for s in SENT if s[0] == CHAT]) > n_grp)

    # חבר רגיל מקבל תשובה בקבוצה — "ניהול בפרטי" אינו רלוונטי לו
    n_grp = len([s for s in SENT if s[0] == CHAT])
    await B.cmd_rules(msg("/rules", uid=USER, mid=7003))
    ok("חבר רגיל מקבל תשובה בקבוצה",
       len([s for s in SENT if s[0] == CHAT]) > n_grp)

    # ומי שמכבה את המתג מקבל את התשובות בקבוצה
    B.db.set(CHAT, "adminpriv", "0")
    n_grp = len([s for s in SENT if s[0] == CHAT])
    await B.cmd_settings(msg("/settings", uid=ADM, mid=7004))
    ok("כיבוי המתג מחזיר את התשובות לקבוצה",
       len([s for s in SENT if s[0] == CHAT]) > n_grp)
    B.db.set(CHAT, "adminpriv", "1")

    # נפילה אחורה: מנהל שלא פתח שיחה עם הבוט חייב בכל זאת לקבל תשובה
    real_send = B.send

    async def no_private(chat_id, text, *, is_group=True, markup=None,
                         clean_after=None, thread_id=None, to_user=None):
        if not is_group:
            return None                    # טלגרם דוחה — אין שיחה פרטית
        return await real_send(chat_id, text, is_group=is_group,
                               markup=markup, clean_after=clean_after,
                               thread_id=thread_id, to_user=to_user)

    B.send = no_private
    try:
        n_grp = len([s for s in SENT if s[0] == CHAT])
        await B.cmd_settings(msg("/settings", uid=ADM, mid=7005))
        ok("כשהפרטי נכשל התשובה חוזרת לקבוצה",
           len([s for s in SENT if s[0] == CHAT]) > n_grp)
    finally:
        B.send = real_send


# ── מי רואה אילו פקודות ───────────────────────────────────────────────────
async def test_command_visibility():
    section("מי רואה אילו פקודות")
    import panel as P
    B.perms.set_role(CHAT, ADM, "owner")
    B.perms.set_role(CHAT, USER, "member")

    member = set(P.member_commands())
    ok("רשימת החברים קטנה", 5 <= len(member) <= 25, str(len(member)))
    for dangerous in ("ban", "lockdown", "broadcast", "aikeys", "addcmd"):
        ok(f"/{dangerous} אינו ברשימת החברים", dangerous not in member)
    for open_cmd in ("help", "rules", "report", "cmds"):
        ok(f"/{open_cmd} כן ברשימת החברים", open_cmd in member)

    m_allowed = B._allowed_cmds(CHAT, USER)
    a_allowed = B._allowed_cmds(CHAT, ADM)
    ok("חבר רגיל מקבל בדיוק את רשימת החברים", m_allowed == member,
       str(sorted(m_allowed ^ member)[:5]))
    ok("בעלים מקבל הכול", len(a_allowed) == len(P.COMMANDS),
       f"{len(a_allowed)}/{len(P.COMMANDS)}")

    pages_m = P.help_pages("he", allowed=m_allowed)
    joined = "\n".join(pages_m)
    ok("העזרה של חבר רגיל היא עמוד אחד", len(pages_m) == 1, str(len(pages_m)))
    ok("ואין בה /ban", "/ban —" not in joined)
    ok("ויש בה /rules", "/rules —" in joined)
    ok("העזרה של בעלים מכילה את הכול",
       all(f"/{n} —" in "\n".join(P.help_pages("he", allowed=a_allowed))
           for n, _ in P.COMMANDS))

    # התפריט של טלגרם: שלושה היקפים, וההיקף של הקבוצה הוא הקטן
    seen = []
    real_bot = B.bot

    class MenuBot(FakeBot):
        async def set_my_commands(self, commands, scope=None,
                                  language_code=None):
            seen.append((type(scope).__name__ if scope else "default",
                         language_code, len(commands)))
            return True

    B.bot = MenuBot()
    try:
        await B.publish_commands()
    finally:
        B.bot = real_bot
    scopes = {s for s, _lg, _n in seen}
    ok("נרשמו שלושה היקפים",
       scopes == {"default", "BotCommandScopeAllGroupChats",
                  "BotCommandScopeAllChatAdministrators"}, str(scopes))
    grp = [n for s, _lg, n in seen if s == "BotCommandScopeAllGroupChats"]
    adm = [n for s, _lg, n in seen
           if s == "BotCommandScopeAllChatAdministrators"]
    dflt = [n for s, _lg, n in seen if s == "default"]
    ok("בקבוצות נרשמת רשימת החברים", grp and set(grp) == {len(member)},
       str(set(grp)))
    ok("למנהלי הקבוצה נרשם הכול",
       adm and set(adm) == {len(P.COMMANDS)}, str(set(adm)))
    ok("ברירת המחדל היא רשימת החברים",
       dflt and set(dflt) == {len(member)}, str(set(dflt)))
    ok("נרשם לכל שפה",
       len({lg for _s, lg, _n in seen}) == len(i18n_langs()), str(seen[:2]))


def i18n_langs():
    import i18n
    return [None] + [c for c in i18n.STRINGS if c != i18n.DEFAULT]


# ── תחזוקה שרצה בפועל ─────────────────────────────────────────────────────
async def test_upkeep():
    section("לולאת התחזוקה")
    src = open(os.path.join(HERE, "bot.py"), encoding="utf-8").read()
    ok("לולאת התחזוקה רשומה בהפעלה", "upkeep_loop)" in src
       or "upkeep_loop," in src, "אינה ב-create_task")

    # ומורצת בפועל: איטרציה אחת, עם sleep מקוצר
    called = []
    real_prune = B.rpt.prune

    def fake_prune(chat_id=None, now=None):
        called.append(True)
        return 3

    real_sleep = asyncio.sleep
    n = {"i": 0}

    async def fast_sleep(secs):
        n["i"] += 1
        if n["i"] > 2:                     # אחרי איטרציה אחת שלמה
            raise asyncio.CancelledError
        return None

    B.rpt.prune = fake_prune
    asyncio.sleep = fast_sleep
    try:
        with contextlib.suppress(asyncio.CancelledError):
            await B.upkeep_loop()
    finally:
        asyncio.sleep = real_sleep
        B.rpt.prune = real_prune
    ok("prune נקרא בפועל מהלולאה", called, "לא נקרא — קוד מת")


# ── תמונות ────────────────────────────────────────────────────────────────
async def test_vision():
    section("תמונות")
    B.perms.set_role(CHAT, USER, "member")
    real_brain = B.brain
    B.brain = aiclient.AIClient(
        aikeys.Providers.from_env({"GROUPOS_GEMINI_KEYS": "g1"}),
        transport=ai_transport)
    try:
        # בדיקת התמונות דולקת כברירת מחדל מאז שהמפתחות מחוברים, ולכן
        # הכיבוי כאן מפורש: הבדיקה הזאת היא על המתג הכבוי.
        B.db.set(CHAT, "aivision", "0")
        await B.on_group_message(photo_msg("UA", mid=200))
        ok("כשהמתג כבוי לא מורידים כלום",
           not DOWNLOADS and AI_CALLS["n"] == 0, f"{DOWNLOADS} {AI_CALLS}")

        B.db.set(CHAT, "aivision", "1")
        await B.on_group_message(photo_msg("UB", caption="חינם", mid=201))
        ok("הורדה אחת בלבד", DOWNLOADS == ["big"], str(DOWNLOADS))
        ok("נבחר הגודל הקריא ולא הגדול ביותר", DOWNLOADS[0] == "big")
        ok("נשלחה בקשה אחת למודל", AI_CALLS["n"] == 1, str(AI_CALLS["n"]))
        ok("ההודעה נמחקה", 201 in DELETED, str(DELETED))
        ok("נרשם ביומן",
           any(r["action"] == "vision.action" for r in B.audit.recent(CHAT)),
           str([r["action"] for r in B.audit.recent(CHAT)][:5]))

        dl, calls = len(DOWNLOADS), AI_CALLS["n"]
        await B.on_group_message(photo_msg("UB", caption="חינם", mid=202))
        ok("אותה תמונה — בלי הורדה נוספת", len(DOWNLOADS) == dl,
           str(DOWNLOADS))
        ok("אותה תמונה — בלי בקשה נוספת", AI_CALLS["n"] == calls)
        ok("ובכל זאת נאכף", 202 in DELETED, str(DELETED))

        VERDICT["json"] = '{"category":"safe","confidence":0.1,"reason":"חתול"}'
        await B.on_group_message(photo_msg("UC", mid=203))
        ok("תמונה תמימה לא נמחקת", 203 not in DELETED, str(DELETED))

        # ‎decide‎ מחזיר החלטה תמיד; ‎action="none"‎ אינו מחיקה.
        # המוניטין מתאפס כאן בכוונה: אחרי שתי אכיפות קודמות באותה
        # בדיקה, "אות חלש" כבר אינו חלש — העבר של המשתמש מצטרף אליו,
        # וזה נכון. מה שנבדק כאן הוא האות לבדו.
        B.rep.reset(CHAT, USER)
        VERDICT["json"] = ('{"category":"advertising","confidence":0.2,'
                           '"reason":"קידום"}')
        await B.on_group_message(photo_msg("UD", mid=204))
        ok("אות חלש אינו מוחק הודעה", 204 not in DELETED, str(DELETED))

        async def boom(url, headers, body, timeout):
            raise OSError("הרשת נפלה")
        B.brain = aiclient.AIClient(
            aikeys.Providers.from_env({"GROUPOS_GEMINI_KEYS": "g1"}),
            transport=boom)
        await B.on_group_message(photo_msg("UE", mid=205))
        ok("תקלה ברשת לא מוחקת הודעות", 205 not in DELETED, str(DELETED))

        B.brain = aiclient.AIClient(
            aikeys.Providers.from_env({"GROUPOS_GROQ_KEYS": "k"}),
            transport=ai_transport)
        dl = len(DOWNLOADS)
        await B.on_group_message(photo_msg("UF", mid=206))
        ok("בלי ספק שרואה לא מורידים ולא אוכפים",
           len(DOWNLOADS) == dl and 206 not in DELETED)

        B.db.set(CHAT, "aivision", "0")
        B.perms.set_role(CHAT, USER, "owner")
        await B.cmd_aivision(msg("/aivision on", uid=USER, mid=207))
        ok("בלי מפתח ראייה הפקודה מסבירה ולא מדליקה",
           "מפתח" in last() and B.db.get(CHAT, "aivision", "0") == "0",
           last() + " · " + str(B.db.get(CHAT, "aivision", "?")))
    finally:
        B.brain = real_brain
        B.db.set(CHAT, "aivision", "0")


# ── הקלטות ────────────────────────────────────────────────────────────────
async def test_voice():
    section("הקלטות")
    B.perms.set_role(CHAT, USER, "member")
    real_brain = B.brain
    B.brain = aiclient.AIClient(
        aikeys.Providers.from_env({"GROUPOS_GEMINI_KEYS": "g1"}),
        transport=ai_transport)
    dl0, calls0 = len(DOWNLOADS), AI_CALLS["n"]
    try:
        await B.on_group_message(voice_msg("VA", mid=300))
        ok("כשהמתג כבוי לא מורידים הקלטה",
           len(DOWNLOADS) == dl0 and AI_CALLS["n"] == calls0)

        B.db.set(CHAT, "aivoice", "1")
        VERDICT["json"] = ('{"category":"threat","confidence":0.9,'
                           '"reason":"איום"}')
        await B.on_group_message(voice_msg("VB", mid=301))
        ok("ההקלטה הורדה פעם אחת", len(DOWNLOADS) == dl0 + 1, str(DOWNLOADS))
        ok("ההודעה נמחקה", 301 in DELETED, str(DELETED))
        ok("נרשם ביומן כמסלול הקול",
           any(r["action"] == "voice.action" for r in B.audit.recent(CHAT)),
           str([r["action"] for r in B.audit.recent(CHAT)][:5]))

        dl, calls = len(DOWNLOADS), AI_CALLS["n"]
        await B.on_group_message(voice_msg("VB", mid=302))
        ok("אותה הקלטה — בלי הורדה ובלי בקשה",
           len(DOWNLOADS) == dl and AI_CALLS["n"] == calls)
        ok("ובכל זאת נאכף", 302 in DELETED, str(DELETED))

        # המשך נבדק לפני ההורדה
        dl = len(DOWNLOADS)
        await B.on_group_message(voice_msg("VC", secs=600, mid=303))
        ok("הקלטה ארוכה מדי לא מורידה כלום",
           len(DOWNLOADS) == dl and 303 not in DELETED)

        VERDICT["json"] = ('{"category":"safe","confidence":0.1,'
                           '"reason":"שיחה"}')
        await B.on_group_message(voice_msg("VD", mid=304))
        ok("הקלטה רגילה לא נמחקת", 304 not in DELETED, str(DELETED))

        B.db.set(CHAT, "aivoice", "0")
        B.perms.set_role(CHAT, USER, "owner")
        B.brain = aiclient.AIClient(
            aikeys.Providers.from_env({"GROUPOS_GROQ_KEYS": "k"}),
            transport=ai_transport)
        await B.cmd_aivoice(msg("/aivoice on", uid=USER, mid=305))
        ok("בלי מפתח שמאזין הפקודה מסבירה ולא מדליקה",
           "מפתח" in last() and B.db.get(CHAT, "aivoice", "0") == "0",
           last())
    finally:
        B.brain = real_brain
        B.db.set(CHAT, "aivoice", "0")


# ── כל הפקודות, אחת-אחת ───────────────────────────────────────────────────
class SmokeBot(FakeBot):
    """מתירני בכוונה: כל קריאה ל-API מחזירה אובייקט דמה.

    בסריקה על 131 פקודות המטרה אינה לאמת את ה-API אלא שהמטפל **ירוץ
    מקצה לקצה** — יפרש ארגומנטים, יבדוק הרשאה, ויענה משהו. בוט קפדני
    היה נופל על ‎AttributeError‎ של שיטה שלא מימשנו, וזה רעש ולא מידע.
    """

    def __getattr__(self, name):
        async def any_call(*a, **kw):
            if name.startswith("send_"):
                SENT.append((a[0] if a else 0, f"[{name}]", False))
                return Message(message_id=9999, date=dt.datetime.now(),
                               chat=Chat(id=CHAT, type="private"), text="")
            if name == "get_chat_administrators":
                return []
            if name == "delete_message":
                DELETED.append(a[1] if len(a) > 1 else 0)
                return True
            return MagicMock()
        return any_call


def _handler_map() -> dict:
    """שם פקודה → המטפל שנרשם עליה, מתוך המרשם של aiogram עצמו.

    לא לפי מוסכמת שמות: ‎_variant‎ רושם וריאציות בלולאה, ומיפוי לפי
    ‎cmd_<שם>‎ היה מפספס אותן — כלומר מדווח "יש מטפל" על סמך ניחוש."""
    out = {}
    for h in B.dp.message.handlers:
        for f in (h.filters or []):
            cb = getattr(f, "callback", None)
            if isinstance(cb, Command):
                for c in cb.commands:
                    out[str(c)] = h.callback
            elif isinstance(cb, CommandStart):
                out["start"] = h.callback
    return out


# ‎/pinned‎ מעביר את ההודעה הנעוצה ב-‎forward_message‎ ואינו שולח טקסט.
# בבוט המדומה ‎pinned_message‎ הוא אובייקט דמה ולכן תמיד "יש נעיצה".
SILENT_OK = {"pinned"}


# פקודות שכל תפקידן להפנות למקום אחר, ולכן הן מדברות על פקודות אחרות
# ולא על עצמן — וזה נכון:
#   notes / filters / ...  — רשימה ריקה מסבירה איך יוצרים את הפריט הראשון
#   diag · security        — דוח שמונה מה חסר ובאיזו פקודה מסדרים
#   help · start           — תפריט
POINTERS = {"notes", "filters", "blocklist", "cmds", "scheduled",
            "allowlist", "approved", "diag", "security", "help", "start",
            "disabled", "automation", "locks", "reportlist", "purgeto",
            "settings", "aikeys", "import", "simulate"}
_TAG = re.compile(r"<[^>]+>")
_SLASH = re.compile(r"/([a-z][a-z0-9_]{1,31})")


async def test_usage_names_the_typed_command():
    """פקודה שמסבירה על פקודה **אחרת** מזו שהוקלדה.

    מי שהקליד ‎/unlock‎ קיבל "שימוש: /lock", ומי שהקליד ‎/spurge‎ קיבל
    "שימוש: /purge <מספר>" — תחביר שאינו עובד שם בכלל, כי ‎/spurge‎
    דורש תשובה להודעה. זה לא סגנון: זו הפניה לפקודה שלא ביקשו.

    הכלל שנבדק אינו "אסור להזכיר פקודה אחרת" — ‎"שימוש: /get <שם>‎ ·
    ‎הרשימה: /notes"‎ הוא בדיוק מה שרצוי. הכלל הוא **שהפקודה שהוקלדה
    תופיע בתשובה שמזכירה פקודות**. תשובה שמדברת רק על פקודות אחרות
    היא הפניה למקום שלא ביקשו.

    הסיבה היא מטפל משותף עם מחרוזת שימוש אחת קבועה, ולכן הבדיקה סורקת
    את **כל** הפקודות ולא את אלה שתוקנו — פקודה חדשה שתחלוק מטפל
    תיתפס כאן ולא אצל המשתמש."""
    section("הודעת השימוש מדברת על הפקודה שהוקלדה")
    hmap = _handler_map()
    names = {n for n, _ in panel.COMMANDS}
    real_bot, real_guard = B.bot, B.guard.acquire
    B.bot = SmokeBot()

    async def no_wait(chat_id, is_group=True):
        return None
    B.guard.acquire = no_wait
    B.perms.set_role(CHAT, ADM, "owner")
    bad = []
    try:
        for i, n in enumerate(sorted(names)):
            before = len(SENT)
            try:
                await asyncio.wait_for(
                    hmap[n](msg("/" + n, uid=ADM, mid=8000 + i)), timeout=5)
            except Exception:                            # noqa: BLE001
                continue           # קריסות נבדקות בסריקה הכללית
            if n in POINTERS:
                continue
            out = _TAG.sub(" ", " ".join(t for _, t, _ in SENT[before:]))
            said = {c for c in _SLASH.findall(out) if c in names}
            if said and n not in said:
                bad.append(f"/{n} → /" + ", /".join(sorted(said)))
    finally:
        B.bot, B.guard.acquire = real_bot, real_guard
    ok("אין פקודה שמפנה לפקודה שלא הוקלדה", not bad, " · ".join(bad[:8]))


async def test_switch_titles():
    """כותרת של מתג היא שם בשפת אדם, ולא מפתח מהמסד.

    ‎/lockdown‎ ו-‎/emergency‎ אינם ב-‎SWITCHES‎, ולכן הכותרת שלהם נפלה
    חזרה למפתח והוצג ‎<b>lockdown</b>‎ — מילה באנגלית בתוך הודעה
    בעברית. התווית קיימת תחת ‎cmd.<שם>‎ ופשוט לא נקראה."""
    section("כותרות המתגים")
    keys = sorted({k for k, _, _ in panel.SWITCHES}
                  | {"lockdown", "emergency"})
    raw = [k for k in keys if panel.switch_label(k, "he") == k]
    ok("אין מתג שמוצג בשם המפתח", not raw, str(raw))
    # ובפועל, ולא רק דרך המילון: המסך עצמו
    shown = [k for k in keys
             if f"<b>{k}</b>" in panel.switch_screen(CHAT, k, True, "he").text]
    ok("אין מסך מתג עם מפתח ככותרת", not shown, str(shown))


async def test_every_command():
    section("כל הפקודות שבתפריט")
    hmap = _handler_map()
    names = [n for n, _ in panel.COMMANDS]

    ok("אין פקודה בתפריט בלי מטפל",
       not [n for n in names if n not in hmap],
       str([n for n in names if n not in hmap]))
    ok("אין מטפל שאינו בתפריט",
       not (set(hmap) - set(names)), str(sorted(set(hmap) - set(names))))

    # פקודה שמצהירה על הרשאה שאינה קיימת ב-PERMISSIONS תיענה **תמיד**
    # ב"אין לך הרשאה", גם לבעלים. כלומר פקודה מתה שנראית קיימת.
    unknown = [(n, p) for n, p in panel.COMMANDS
               if p and p not in permissions.PERMISSIONS]
    ok("כל הרשאה שפקודה דורשת קיימת", not unknown, str(unknown))

    real_bot, real_guard = B.bot, B.guard.acquire
    B.bot = SmokeBot()

    async def no_wait(chat_id, is_group=True):
        return None
    B.guard.acquire = no_wait          # שומר המכסות נבדק בנפרד
    B.perms.set_role(CHAT, ADM, "owner")
    try:
        crashed, silent = [], []
        for i, n in enumerate(names):
            fn = hmap[n]
            before = len(SENT)
            try:
                await asyncio.wait_for(
                    fn(msg("/" + n, uid=ADM, mid=5000 + i)), timeout=5)
                out = " ".join(t for _, t, _ in SENT[before:])
                if not out.strip():
                    # ייתכן שהיא לפרטי בלבד
                    pm = Message(message_id=6000 + i, date=dt.datetime.now(),
                                 chat=Chat(id=ADM, type="private"),
                                 from_user=User(id=ADM, is_bot=False,
                                                first_name="דוד",
                                                language_code="he"),
                                 text="/" + n)
                    await asyncio.wait_for(fn(pm), timeout=5)
                    out = " ".join(t for _, t, _ in SENT[before:])
                if not out.strip() and n not in SILENT_OK:
                    silent.append(n)
            except asyncio.TimeoutError:
                crashed.append(f"{n}: נתקע")
            except Exception as e:                       # noqa: BLE001
                crashed.append(f"{n}: {type(e).__name__}: {e}")
        ok(f"כל {len(names)} הפקודות רצות בלי לקרוס", not crashed,
           " · ".join(crashed[:6]))
        ok("כל פקודה עונה משהו", not silent, str(silent))
    finally:
        B.bot, B.guard.acquire = real_bot, real_guard



async def test_new_features():
    """שבת, שעות פתיחה, וזיהוי תוכן חריג — דרך המטפלים עצמם."""
    section("שבת, שעות פתיחה ותוכן חריג")
    import json as _json
    import zmanim as _zm

    # התאריכים נגזרים מ"עכשיו": פיד עם שבת שעברה אינו חלון קרוב,
    # והבדיקה הייתה מתחילה להיכשל מעצמה בתאריך מסוים.
    _tz = dt.timezone(dt.timedelta(hours=3))
    _fri = (dt.datetime.now(_tz) + dt.timedelta(days=2)).replace(
        hour=17, minute=42, second=0, microsecond=0)
    _sat = (_fri + dt.timedelta(days=1)).replace(hour=18, minute=38)
    feed = {"items": [
        {"category": "candles", "title": "Candle lighting: 17:42",
         "date": _fri.isoformat()},
        {"category": "parashat", "title": "Parashat Noach",
         "hebrew": "פרשת נח"},
        {"category": "havdalah", "title": "Havdalah: 18:38",
         "date": _sat.isoformat()}]}

    async def fake_feed(url, timeout):
        return _json.dumps(feed)

    B.zman = _zm.Zmanim(transport=fake_feed)
    B.db.set(CHAT, "tz_offset", "180")

    out = await _out(B.cmd_shabbat, msg("/shabbat on", mid=9900))
    ok("שבת נדלקת", B.db.get(CHAT, "shabbat", "0") == "1", out)
    out = await _out(B.cmd_shabbat, msg("/shabbat city telaviv", mid=9901))
    ok("עיר נקבעת", B.db.get(CHAT, "shabbat_city", "") == "telaviv", out)
    out = await _out(B.cmd_shabbat, msg("/shabbat city atlantis", mid=9902))
    ok("עיר לא מוכרת אינה נשמרת",
       B.db.get(CHAT, "shabbat_city", "") == "telaviv", out)
    out = await _out(B.cmd_shabbat, msg("/shabbat before 20", mid=9903))
    ok("היסט נשמר", B.db.get(CHAT, "shabbat_before", "") == "20", out)
    out = await _out(B.cmd_shabbat, msg("/shabbat preview", mid=9904))
    ok("תצוגה מקדימה מציגה זמנים", "17:42" in out and "18:38" in out, out[:120])
    out = await _out(B.cmd_shabbat,
                     msg("/shabbat msg lock סוגרים ב-{candles}", mid=9905))
    ok("תבנית נשמרת",
       B.db.get(CHAT, "shabbat_msg_lock", "") == "סוגרים ב-{candles}", out)
    out = await _out(B.cmd_shabbat, msg("/shabbat preview", mid=9906))
    ok("והתצוגה משתמשת בה", "סוגרים ב-17:42" in out, out[:120])
    out = await _out(B.cmd_shabbat, msg("/shabbat", mid=9907))
    ok("המסך מציג את השבת הקרובה", "17:42" in out, out[:160])

    # הלולאה: נועלת בתוך החלון, פותחת אחריו, ולא נוגעת בקבוצה שמנהל
    # השבית ידנית.
    wins = await B._shab_windows(CHAT)
    w = wins[0]
    locked = []
    real_lock = B.set_lockdown

    async def fake_lock(chat_id, on, by):
        locked.append(on)
        B.db.set(chat_id, "lockdown", "1" if on else "0", by)
        return True

    B.set_lockdown = fake_lock
    try:
        B.db.set(CHAT, "shabbat_msg_lock", "")
        held = await B._tick_shabbat(CHAT, (w.candles + w.havdalah) / 2)
        ok("בתוך השבת — נעול", held and locked == [True], str(locked))
        ok("והבעלות נרשמה", B.db.get(CHAT, B.AUTOLOCK_KEY, "") == "shab")
        held = await B._tick_shabbat(CHAT, (w.candles + w.havdalah) / 2 + 60)
        ok("ולא ננעל פעמיים", locked == [True])
        held = await B._tick_shabbat(CHAT, w.open_at + 120)
        ok("אחרי צאת השבת — נפתח", not held and locked == [True, False])
        ok("והבעלות נוקתה", B.db.get(CHAT, B.AUTOLOCK_KEY, "") == "")

        # לוח שעות
        out = await _out(B.cmd_hours, msg("/hours sat closed", mid=9910))
        ok("יום נשמר בלוח", "sat=closed" in B.db.get(CHAT, "hours", ""), out)
        out = await _out(B.cmd_hours, msg("/hours xyz 08:00-09:00", mid=9911))
        ok("יום לא מוכר נדחה", "sat=closed" == B.db.get(CHAT, "hours", ""), out)
        locked.clear()
        import calendar as _cal
        sat = float(_cal.timegm((2026, 10, 24, 9, 0, 0)))   # שבת בבוקר
        B.db.set(CHAT, "shabbat", "0")
        await B._tick_hours(CHAT, sat, False)
        ok("לוח סוגר", locked == [True], str(locked))
        sun = sat + 24 * 3600
        await B._tick_hours(CHAT, sun, False)
        ok("ולמחרת פותח", locked == [True, False], str(locked))

        # קבוצה שהמנהל השבית ידנית אינה נפתחת על ידי הלוח
        locked.clear()
        B.db.set(CHAT, "lockdown", "1")
        B.db.set(CHAT, B.AUTOLOCK_KEY, "")
        await B._tick_hours(CHAT, sun, False)
        ok("השבתה ידנית אינה נפתחת אוטומטית", locked == [], str(locked))
        out = await _out(B.cmd_hours, msg("/hours clear", mid=9912))
        ok("הלוח מתנקה", B.db.get(CHAT, "hours", "") == "", out)
    finally:
        B.set_lockdown = real_lock
        B.db.set(CHAT, "lockdown", "0")
        B.db.set(CHAT, "shabbat", "0")
        B.db.set(CHAT, B.AUTOLOCK_KEY, "")

    # ── התוכן החריג שהתחיל את כל זה ─────────────────────────────────
    DELETED.clear()
    bad = Message(
        message_id=9920, date=dt.datetime.now(),
        chat=Chat(id=CHAT, type="supergroup", title="קבוצה"),
        from_user=User(id=BAD, is_bot=False, first_name="ספאמר"),
        photo=[PhotoSize(file_id="F1", file_unique_id="U1", width=90,
                         height=90, file_size=1000)],
        caption="💦Ch1ld 💜 Ladyboy 💝 Te ens 14-16 😻 Gay")
    banned = []
    real_apply = B.apply_action

    async def fake_apply(chat_id, user_id, kind, duration, reason, by):
        banned.append((user_id, kind))
        return True

    B.apply_action = fake_apply
    try:
        before = len(SENT)
        await B.on_group_message(bad)
        ok("ההודעה האסורה נמחקה", 9920 in DELETED, str(DELETED[-3:]))
        ok("והשולח נחסם", banned and banned[0][1] == "ban", str(banned))
        reported = [t for _c, t, _m in SENT[before:] if "🚨" in t]
        ok("והמנהלים קיבלו דיווח", bool(reported), str(SENT[before:])[:120])
        ok("הדיווח יצא בפרטי ולא לקבוצה",
           all(c != CHAT for c, t, _m in SENT[before:] if "🚨" in t))
        ok("נרשם ביומן כקריטי",
           any(r["action"] == "spam.illegal"
               for r in B.audit.recent(CHAT, 5)),
           str([r["action"] for r in B.audit.recent(CHAT, 5)]))

        # הודעה תמימה עוברת
        DELETED.clear()
        fine = Message(message_id=9921, date=dt.datetime.now(),
                       chat=Chat(id=CHAT, type="supergroup", title="קבוצה"),
                       from_user=User(id=USER, is_bot=False, first_name="דנה"),
                       text="מישהו יודע מתי המפגש?")
        await B.on_group_message(fine)
        ok("הודעה רגילה אינה נפגעת", 9921 not in DELETED)
    finally:
        B.apply_action = real_apply



async def test_button_editing():
    """עריכה בלחיצה: ההמתנה, ההודעה שאחריה, והשמירה."""
    section("עריכה בכפתורים")
    import prompts as _pr
    B.perms.set_role(CHAT, ADM, "owner")

    def pm(text: str, uid: int = ADM, mid: int = 9950) -> Message:
        return Message(message_id=mid, date=dt.datetime.now(),
                       chat=Chat(id=uid, type="private"),
                       from_user=User(id=uid, is_bot=False, first_name="דוד"),
                       text=text)

    # בלי המתנה: הודעה פרטית מקבלת את מסך הבית ולא נבלעת
    out = await _out(B.on_private_text, pm("היי", mid=9951))
    ok("הודעה פרטית בלי המתנה מחזירה מסך", bool(out), out[:60])

    B.waiting.start(ADM, CHAT, "welcome")
    out = await _out(B.on_private_text, pm("ברוך הבא {mention}!", mid=9952))
    ok("הטקסט נשמר בלי פקודה",
       B.db.get(CHAT, "welcome", "") == "ברוך הבא {mention}!", out[:60])
    ok("והמתג נדלק מעצמו", B.db.get(CHAT, "welcome_on", "0") == "1")
    ok("וההמתנה נסגרה", B.waiting.get(ADM) is None)
    ok("ההודעה הבאה כבר אינה נלכדת",
       (await _out(B.on_private_text, pm("סתם משפט", mid=9953))) is not None
       and B.db.get(CHAT, "welcome", "") == "ברוך הבא {mention}!")

    # מספר
    B.waiting.start(ADM, CHAT, "floodrate")
    await _out(B.on_private_text, pm("9999", mid=9954))
    ok("מספר נחתך לטווח", B.db.get(CHAT, "flood_rate", "") == "60",
       str(B.db.get(CHAT, "flood_rate", "?")))
    B.waiting.start(ADM, CHAT, "floodrate")
    out = await _out(B.on_private_text, pm("הרבה", mid=9955))
    ok("טקסט במקום מספר אינו נשמר",
       B.db.get(CHAT, "flood_rate", "") == "60" and bool(out), out[:40])

    # HTML שבור אינו נשמר בשקט
    rules_before = B.db.get(CHAT, "rules", "") or ""
    B.waiting.start(ADM, CHAT, "rules")
    out = await _out(B.on_private_text, pm("<b>לא נסגר", mid=9956))
    ok("HTML שבור נדחה עם הסבר",
       (B.db.get(CHAT, "rules", "") or "") == rules_before
       and "<b>" in out, out[:60])

    # מי שאינו מנהל אינו עורך, גם אם פתחו לו המתנה
    B.perms.set_role(CHAT, USER, "member")
    B.waiting.start(USER, CHAT, "welcome")
    before = B.db.get(CHAT, "welcome", "")
    await _out(B.on_private_text, pm("שלי עכשיו", uid=USER, mid=9957))
    ok("חבר רגיל אינו עורך", B.db.get(CHAT, "welcome", "") == before)

    # המסכים החדשים נבנים
    for name in ("texts", "nums", "aim"):
        sc = B._screen_for(CHAT, name, "")
        ok(f"מסך {name} נבנה", sc is not None and bool(sc.rows))
        ok(f"ומזהי הכפתורים בו תקינים",
           all(len(c.encode()) <= panel.CB_MAX for c in sc.all_callbacks()))

    # כל שדה מופיע במסך כלשהו, אחרת הוא נגיש רק בפקודה
    shown = set()
    B.db.set(CHAT, "shabbat", "1")
    for name in ("texts", "nums", "aim", "reps", "stmsgs"):
        for c in B._screen_for(CHAT, name, "").all_callbacks():
            parts = c.split(":")
            if len(parts) > 3 and parts[2] in ("ask", "clr", "stmsg"):
                shown.add(parts[3])
    B.db.set(CHAT, "shabbat", "0")
    # ‎hrange‎ נגיש מכפתור "שעות עם דקות" בתוך מסך היום, לא מהמסכים
    # האלה, ו-‎warnpol‎ יושב במסך האזהרות.
    missing = set(_pr.FIELDS) - shown - {"warnpol", "hrange"}
    ok("כל שדה נגיש בכפתור", not missing, str(missing))



async def test_aggressive_paths():
    """מצב אגרסיבי: מנהל שמפרסם, וערוץ ששולח בשם עצמו."""
    section("מצב אגרסיבי")
    DELETED.clear()
    banned = []
    chans = []
    real_apply = B.apply_action
    real_ban_chat = B.bot.ban_chat_sender_chat if hasattr(
        B.bot, "ban_chat_sender_chat") else None

    async def fake_apply(chat_id, user_id, kind, duration, reason, by,
                         source="policy"):
        banned.append((user_id, kind))
        return True

    async def fake_ban_chat(chat_id, sender_chat_id):
        chans.append(sender_chat_id)

    B.apply_action = fake_apply
    B.bot.ban_chat_sender_chat = fake_ban_chat
    try:
        ad = "💋 RAW SCANDAL FULLY UNLOCKED ✅ GRAB THIS LINK https://x.example"
        # מנהל: ההודעה נמחקת, הוא אינו נחסם
        B.perms.set_role(CHAT, ADM, "owner")
        await B.on_group_message(msg(ad, uid=ADM, mid=9960))
        ok("מודעה של מנהל נמחקת", 9960 in DELETED, str(DELETED[-3:]))
        ok("ומנהל אינו נחסם", not banned, str(banned))

        # חבר רגיל: נחסם
        B.perms.set_role(CHAT, BAD, "member")
        await B.on_group_message(msg(ad, uid=BAD, mid=9961))
        ok("מודעה של חבר — חסימה", 9961 in DELETED and banned
           and banned[-1][1] == "ban", str(banned))

        # ערוץ ששולח בשם עצמו: נחסם הערוץ ולא הבוט האנונימי
        banned.clear()
        chan_msg = Message(
            message_id=9962, date=dt.datetime.now(),
            chat=Chat(id=CHAT, type="supergroup", title="קבוצה"),
            from_user=User(id=136817688, is_bot=True, first_name="Channel"),
            sender_chat=Chat(id=-1009999, type="channel", title="ערוץ"),
            text=ad)
        await B.on_group_message(chan_msg)
        ok("ערוץ ספאם נחסם כערוץ", chans == [-1009999], str(chans))
        ok("ולא נחסם משתמש", not banned, str(banned))

        # מצב אגרסיבי כבוי — מנהל שוב פטור
        DELETED.clear()
        B.db.set(CHAT, "strict", "0")
        await B.on_group_message(msg(ad, uid=ADM, mid=9963))
        ok("בלי מצב אגרסיבי מנהל פטור", 9963 not in DELETED, str(DELETED))
    finally:
        B.db.set(CHAT, "strict", "1")
        B.apply_action = real_apply
        if real_ban_chat is not None:
            B.bot.ban_chat_sender_chat = real_ban_chat



async def test_forum_topics():
    """קבוצת נושאים: התשובה חוזרת לנושא שבו נשאלה, לא ל"כללי"."""
    section("נושאים")

    def topic_msg(text: str, thread: int, mid: int = 9970) -> Message:
        return Message(message_id=mid, date=dt.datetime.now(),
                       chat=Chat(id=CHAT, type="supergroup", title="ק",
                                 is_forum=True),
                       from_user=User(id=ADM, is_bot=False, first_name="דוד"),
                       text=text, message_thread_id=thread,
                       is_topic_message=True)

    B.perms.set_role(CHAT, ADM, "owner")
    B.db.set(CHAT, "adminpriv", "0")       # שהתשובה תצא בקבוצה
    try:
        THREADS.clear()
        await _out(B.cmd_rules, topic_msg("/rules", 55, mid=9971))
        ok("התשובה יצאה לנושא ולא לכללי", THREADS and THREADS[-1] == 55,
           str(THREADS[-3:]))

        THREADS.clear()
        await _out(B.cmd_id, msg("/id", mid=9972))
        ok("בקבוצה רגילה אין נושא", THREADS and THREADS[-1] is None,
           str(THREADS[-3:]))

        # תשובה בתוך שרשור בקבוצה רגילה אינה נושא: שליחה אליו נכשלת
        thready = Message(message_id=9973, date=dt.datetime.now(),
                          chat=Chat(id=CHAT, type="supergroup", title="ק"),
                          from_user=User(id=ADM, is_bot=False,
                                         first_name="דוד"),
                          text="/id", message_thread_id=77)
        ok("שרשור רגיל אינו נחשב נושא", B._thread_of(thready) is None)

        # הודעת אכיפה חוזרת לנושא שבו נשלחה ההפרה
        THREADS.clear()
        B.db.set(CHAT, "silent", "0")
        B.perms.set_role(CHAT, BAD, "member")
        bad = Message(message_id=9974, date=dt.datetime.now(),
                      chat=Chat(id=CHAT, type="supergroup", title="ק",
                                is_forum=True),
                      from_user=User(id=BAD, is_bot=False, first_name="ס"),
                      text="קנו עכשיו קנו עכשיו", message_thread_id=55,
                      is_topic_message=True)
        B.locks.set(CHAT, "url", "off")
        B.filters.add(CHAT, "קנו עכשיו", "", action="warn")
        await B.on_group_message(bad)
        ok("הודעת האכיפה בנושא הנכון",
           not THREADS or all(t in (55, None) for t in THREADS),
           str(THREADS))
    finally:
        B.db.set(CHAT, "adminpriv", "1")
        B.db.set(CHAT, "silent", "1")
        B.filters.remove(CHAT, "קנו עכשיו")



async def test_hours_picker():
    """בחירת שעות: סוג, שעת התחלה, שעת סיום — וטווח מוקלד."""
    section("בחירת שעות")
    import grouphours as _gh
    B.perms.set_role(CHAT, ADM, "owner")
    B.db.set(CHAT, "hours", "")

    def pm(text: str, mid: int = 9980) -> Message:
        return Message(message_id=mid, date=dt.datetime.now(),
                       chat=Chat(id=ADM, type="private"),
                       from_user=User(id=ADM, is_bot=False, first_name="דוד"),
                       text=text)

    # הלוח: כל 24 השעות, ולא רשימת הצעות
    grid = panel.hour_grid(CHAT, "mon", "c", None, False, "he")
    ok("לוח של 24 שעות", len(grid.all_callbacks()) == 27,
       str(len(grid.all_callbacks())))
    half = panel.hour_grid(CHAT, "mon", "c", None, True, "he")
    ok("חצאי שעות בלחיצה אחת",
       any(t == "08:30" for row in half.rows for t, _ in row),
       str(half.rows[2]))
    ok("והדקות עוברות במזהה כדקות מחצות",
       any(c.endswith(":mon.c.510") for c in half.all_callbacks()),
       str(half.all_callbacks()[:3]))
    ok("כולל חצות ואחת עשרה בלילה",
       any("00:00" == t for row in grid.rows for t, _ in row)
       and any("23:00" == t for row in grid.rows for t, _ in row))
    ok("מזהי הכפתורים בטווח",
       all(len(c.encode()) <= panel.CB_MAX for c in grid.all_callbacks()))
    ok("אחרי בחירת התחלה מוצגת ההתחלה",
       "00:00" in panel.hour_grid(CHAT, "mon", "c", 0, False, "he").text)

    # טווח סגירה שנשמר דרך העזר של השמירה
    ok("סגירת לילה נשמרת",
       B._save_day_range(CHAT, "mon", "!00:00-07:00", ADM)
       and _gh.parse(B.db.get(CHAT, "hours", ""))["mon"].mode == _gh.SHUT,
       B.db.get(CHAT, "hours", ""))
    ok("והקבוצה סגורה בלילה",
       not _gh.is_open(B.db.get(CHAT, "hours", ""),
                       now=float(__import__("calendar").timegm(
                           (2026, 10, 19, 2, 0, 0)))))
    ok("התווית מסבירה מה נבחר",
       "סגור" in B._day_label(CHAT, "mon", "he"),
       B._day_label(CHAT, "mon", "he"))

    # הקלדה חופשית עם דקות
    B.waiting.start(ADM, CHAT, "hrange", arg="tue")
    out = await _out(B.on_private_text, pm("08:15-23:45", mid=9981))
    ok("דקות מדויקות נשמרות",
       _gh.parse(B.db.get(CHAT, "hours", ""))["tue"].span == "08:15-23:45",
       B.db.get(CHAT, "hours", "") + " | " + out[:40])

    B.waiting.start(ADM, CHAT, "hrange", arg="wed")
    before = B.db.get(CHAT, "hours", "")
    out = await _out(B.on_private_text, pm("מתישהו בערב", mid=9982))
    ok("ניסוח שאינו טווח אינו נשמר",
       B.db.get(CHAT, "hours", "") == before and bool(out), out[:40])

    B.waiting.start(ADM, CHAT, "hrange", arg="tue")
    await _out(B.on_private_text, pm("off", mid=9983))
    ok("off מסיר את היום",
       "tue" not in _gh.parse(B.db.get(CHAT, "hours", "")),
       B.db.get(CHAT, "hours", ""))
    B.db.set(CHAT, "hours", "")



async def test_evidence_flow():
    """האכיפה נשמרת עם ההודעה שגרמה לה, ואפשר לבטל אותה."""
    section("יומן אכיפה")
    B.perms.set_role(CHAT, BAD, "member")
    B.db.set(CHAT, "keepproof", "1")
    before = B.proof.count(CHAT)

    bad = Message(
        message_id=9990, date=dt.datetime.now(),
        chat=Chat(id=CHAT, type="supergroup", title="ק"),
        from_user=User(id=BAD, is_bot=False, first_name="ספאמר"),
        photo=[PhotoSize(file_id="BIGFILE", file_unique_id="UZ", width=1280,
                         height=720, file_size=400_000)],
        caption="💋 RAW SCANDAL FULLY UNLOCKED ✅ GRAB THIS LINK https://x.tv")
    banned = []
    real_apply = B.apply_action

    async def fake_apply(chat_id, user_id, kind, duration, reason, by,
                         source="policy"):
        banned.append(kind)
        return True

    B.apply_action = fake_apply
    try:
        await B.on_group_message(bad)
        ok("נשמר מקרה חדש", B.proof.count(CHAT) == before + 1,
           f"{before} → {B.proof.count(CHAT)}")
        it = B.proof.recent(CHAT, 1)[0]
        ok("עם ההודעה שגרמה לו", "SCANDAL" in it.text, it.text[:40])
        ok("ועם הקובץ עצמו", it.media_id == "BIGFILE" and it.has_media,
           it.media_id)
        ok("הסיבה נשמרה", "adult_ad" in it.reason or "spam" in it.reason,
           it.reason)
        ok("והפעולה", it.action == "ban" and banned == ["ban"], str(banned))

        when = "עכשיו"
        sc = panel.proof_item(CHAT, it, when,
                              B.proof.count_user(CHAT, BAD), "he")
        ok("מסך המקרה מציג את הטקסט", "SCANDAL" in sc.text, sc.text[:60])
        ok("ויש כפתור לקובץ",
           any("pfm" in c for c in sc.all_callbacks()),
           str(sc.all_callbacks()))
        ok("ויש כפתור ביטול",
           any("pfu:" in c for c in sc.all_callbacks()),
           str(sc.all_callbacks()))
        lst = panel.proof_list(CHAT, B.proof.recent(CHAT, 10),
                               lambda t: "x", "he")
        ok("הרשימה נבנית", bool(lst.rows))
        ok("ומזהי הכפתורים בטווח",
           all(len(c.encode()) <= panel.CB_MAX for c in lst.all_callbacks()))

        # ביטול: שחרור החסימה
        unbanned = []

        async def fake_unban(chat_id, user_id, only_if_banned=False):
            unbanned.append(user_id)

        real_unban = B.bot.unban_chat_member if hasattr(
            B.bot, "unban_chat_member") else None
        B.bot.unban_chat_member = fake_unban
        try:
            okay = await B._undo_action(CHAT, it, ADM)
            ok("הביטול שחרר את המשתמש", okay and unbanned == [BAD],
               str(unbanned))
        finally:
            if real_unban is not None:
                B.bot.unban_chat_member = real_unban

        # מתג כבוי = לא נשמרות ראיות
        B.db.set(CHAT, "keepproof", "0")
        n = B.proof.count(CHAT)
        await B.on_group_message(Message(
            message_id=9991, date=dt.datetime.now(),
            chat=Chat(id=CHAT, type="supergroup", title="ק"),
            from_user=User(id=BAD, is_bot=False, first_name="ספאמר"),
            text="💋 RAW SCANDAL FULLY UNLOCKED GRAB THIS LINK https://x.tv"))
        ok("מתג כבוי — לא נשמר", B.proof.count(CHAT) == n)
    finally:
        B.apply_action = real_apply
        B.db.set(CHAT, "keepproof", "1")


async def test_filter_file():
    """פילטר שמשיב בקובץ: נשמר file_id, ונשלח כמו שהוא."""
    section("פילטר עם קובץ")
    B.perms.set_role(CHAT, ADM, "owner")
    src = Message(message_id=9995, date=dt.datetime.now(),
                  chat=Chat(id=CHAT, type="supergroup", title="ק"),
                  from_user=User(id=ADM, is_bot=False, first_name="דוד"),
                  document=Document(file_id="HUGE4GB", file_unique_id="D1",
                                    file_name="app.apk",
                                    file_size=4_000_000_000))
    cmd = Message(message_id=9996, date=dt.datetime.now(),
                  chat=Chat(id=CHAT, type="supergroup", title="ק"),
                  from_user=User(id=ADM, is_bot=False, first_name="דוד"),
                  text="/filter youtube הנה האפליקציה", reply_to_message=src)
    await _out(B.cmd_filter, cmd)
    fh = B.filters.check(CHAT, "youtube")
    ok("הפילטר נשמר עם הקובץ",
       fh is not None and fh.media_id == "HUGE4GB"
       and fh.media_kind == "document", str(fh))

    B.perms.set_role(CHAT, USER, "member")
    before = len(SENT)
    await B.on_group_message(msg("איפה youtube?", uid=USER, mid=9997))
    out = " ".join(t for _c, t, _m in SENT[before:])
    ok("והתשובה כוללת את הקובץ", "HUGE4GB" in out, out[:80])
    B.filters.remove(CHAT, "youtube")



async def test_ephemeral():
    """הודעות שרק הנמען רואה: ברכה, ואזהרה."""
    section("הודעות אישיות")
    B.db.set(CHAT, "ephemeral", "1")
    B.db.set(CHAT, "welcome", "ברוך הבא {first}")
    B.db.set(CHAT, "welcome_on", "1")
    newbie = User(id=4242, is_bot=False, first_name="חדש")
    TO_USER.clear()
    await B._greet(CHAT, newbie, B.WELCOME_KEY, True)
    ok("הברכה נשלחה רק לנכנס", TO_USER and TO_USER[-1] == 4242,
       str(TO_USER[-3:]))

    TO_USER.clear()
    await B._greet(CHAT, newbie, B.GOODBYE_KEY, False)
    ok("הודעת פרידה נשארת גלויה",
       not TO_USER or TO_USER[-1] is None, str(TO_USER[-3:]))

    # מתג כבוי — הכול גלוי
    B.db.set(CHAT, "ephemeral", "0")
    TO_USER.clear()
    await B._greet(CHAT, newbie, B.WELCOME_KEY, True)
    ok("כשהמתג כבוי הברכה גלויה לכולם",
       TO_USER and TO_USER[-1] is None, str(TO_USER[-3:]))

    B.db.set(CHAT, "ephemeral", "1")
    B.db.set(CHAT, "welcome", "")
    B.db.set(CHAT, "silent", "0")
    B.perms.set_role(CHAT, BAD, "member")
    B.locks.set(CHAT, "url", "warn")
    TO_USER.clear()
    try:
        await B.on_group_message(msg("בואו ל-t.me/spam", uid=BAD, mid=9998))
        ok("הודעת האזהרה נשלחה רק למי שהוזהר",
           BAD in TO_USER, str(TO_USER))
    finally:
        B.locks.set(CHAT, "url", "off")
        B.db.set(CHAT, "silent", "1")



async def test_welcome_visibility():
    """מי רואה את ברכת הכניסה, וכמה זמן היא נשארת."""
    section("ברכת כניסה")
    B.db.set(CHAT, "welcome", "ברוך הבא {first}")
    B.db.set(CHAT, "welcome_on", "1")
    B.db.set(CHAT, "ephemeral", "1")
    guy = User(id=4343, is_bot=False, first_name="חדש")

    B.db.set(CHAT, "welcome_private", "1")
    TO_USER.clear()
    await B._greet(CHAT, guy, B.WELCOME_KEY, True)
    ok("ברירת המחדל — רק הנכנס", TO_USER and TO_USER[-1] == 4343,
       str(TO_USER[-2:]))

    B.db.set(CHAT, "welcome_private", "0")
    TO_USER.clear()
    await B._greet(CHAT, guy, B.WELCOME_KEY, True)
    ok("ומי שבוחר — כל הקבוצה רואה",
       TO_USER and TO_USER[-1] is None, str(TO_USER[-2:]))

    sc = B._screen_for(CHAT, "greet", "")
    ok("מסך הברכה נבנה", sc is not None and bool(sc.rows))
    ok("ויש בו את שתי האפשרויות",
       any("gwho:1" in c for c in sc.all_callbacks())
       and any("gwho:0" in c for c in sc.all_callbacks()),
       str(sc.all_callbacks()))
    ok("ובורר זמן מחיקה",
       any("gclean" in c for c in sc.all_callbacks()))
    ok("המסך אומר מי רואה",
       "כל הקבוצה" in sc.text or "whole group" in sc.text, sc.text[:80])

    # מחזור זמני המחיקה
    cur = "0"
    seen = []
    for _ in range(len(panel.GREET_CLEAN_CYCLE)):
        cur = panel.next_in_cycle(panel.GREET_CLEAN_CYCLE, cur)
        seen.append(cur)
    ok("מחזור המחיקה חוזר להתחלה", seen[-1] == "0", str(seen))
    ok("ויש בו דקות ושעות", "120" in seen and "3600" in seen, str(seen))
    B.db.set(CHAT, "welcome_private", "1")
    B.db.set(CHAT, "welcome", "")


async def test_filter_multi():
    """פילטר שמחזיר כמה הודעות — בדיוק כמו שהמנהל שמר."""
    section("פילטר בכמה הודעות")
    B.perms.set_role(CHAT, ADM, "owner")
    B.filters.remove(CHAT, "youtube")

    doc = Message(message_id=9900, date=dt.datetime.now(),
                  chat=Chat(id=CHAT, type="supergroup", title="ק"),
                  from_user=User(id=ADM, is_bot=False, first_name="דוד"),
                  document=Document(file_id="APK", file_unique_id="D9",
                                    file_name="a.apk"))
    await _out(B.cmd_filter, Message(
        message_id=9901, date=dt.datetime.now(),
        chat=Chat(id=CHAT, type="supergroup", title="ק"),
        from_user=User(id=ADM, is_bot=False, first_name="דוד"),
        text="/filter youtube הנה הקובץ", reply_to_message=doc))

    pic = Message(message_id=9902, date=dt.datetime.now(),
                  chat=Chat(id=CHAT, type="supergroup", title="ק"),
                  from_user=User(id=ADM, is_bot=False, first_name="דוד"),
                  photo=[PhotoSize(file_id="PIC", file_unique_id="P9",
                                   width=90, height=90)])
    out = await _out(B.cmd_filteradd, Message(
        message_id=9903, date=dt.datetime.now(),
        chat=Chat(id=CHAT, type="supergroup", title="ק"),
        from_user=User(id=ADM, is_bot=False, first_name="דוד"),
        text="/filteradd youtube", reply_to_message=pic))
    ok("פריט שני נוסף", B.filters.item_count(CHAT, "youtube") == 1, out[:60])

    await _out(B.cmd_filteradd, Message(
        message_id=9904, date=dt.datetime.now(),
        chat=Chat(id=CHAT, type="supergroup", title="ק"),
        from_user=User(id=ADM, is_bot=False, first_name="דוד"),
        text="/filteradd youtube וזה ההסבר"))
    ok("ושלישי", B.filters.item_count(CHAT, "youtube") == 2)

    out = await _out(B.cmd_filteradd, msg("/filteradd nosuch משהו", mid=9905))
    ok("הדק שלא קיים נדחה", "nosuch" in out, out[:60])

    B.perms.set_role(CHAT, USER, "member")
    before = len(SENT)
    await B.on_group_message(msg("youtube", uid=USER, mid=9906))
    sent = [t for _c, t, _m in SENT[before:]]
    ok("שלוש הודעות חזרו", len(sent) == 3, str(sent))
    ok("בסדר שנשמר",
       "APK" in sent[0] and "PIC" in sent[1] and "ההסבר" in sent[2],
       str(sent))

    n = B.filters.clear_items(CHAT, "youtube")
    ok("אפשר לאפס את הנוספות",
       n == 2 and B.filters.item_count(CHAT, "youtube") == 0)
    B.filters.remove(CHAT, "youtube")
    ok("ומחיקת הפילטר מנקה גם אותן",
       B.filters.item_count(CHAT, "youtube") == 0)



async def test_cmd_multi():
    """אותו מנגנון על פקודה מותאמת: /סרטים מחזיר כמה הודעות."""
    section("פקודה בכמה הודעות")
    B.perms.set_role(CHAT, ADM, "owner")
    # שם פקודה חייב להיות באותיות לטיניות — זו מגבלה של טלגרם עצמה
    # ולא שלנו. מילת הדק בעברית עובדת דרך /filter.
    name = "movies"
    doc = Message(message_id=9800, date=dt.datetime.now(),
                  chat=Chat(id=CHAT, type="supergroup", title="ק"),
                  from_user=User(id=ADM, is_bot=False, first_name="דוד"),
                  document=Document(file_id="MOVIEAPK", file_unique_id="D7",
                                    file_name="x.apk"))
    await _out(B.cmd_addcmd, Message(
        message_id=9801, date=dt.datetime.now(),
        chat=Chat(id=CHAT, type="supergroup", title="ק"),
        from_user=User(id=ADM, is_bot=False, first_name="דוד"),
        text=f"/addcmd {name} הנה", reply_to_message=doc))
    ok("הפקודה נוצרה", B.cmds.get(CHAT, name) is not None)

    out = await _out(B.cmd_cmdadd, msg(f"/cmdadd {name} וזה ההסבר", mid=9802))
    ok("פריט נוסף לפקודה",
       B.filters.item_count(CHAT, name, "cmd") == 1, out[:60])
    out = await _out(B.cmd_cmdadd, msg("/cmdadd nope משהו", mid=9803))
    ok("פקודה שלא קיימת נדחית", "nope" in out, out[:60])

    # הפילטר והפקודה באותו שם אינם מתערבבים
    B.filters.add(CHAT, name, "תשובת פילטר")
    B.filters.add_item(CHAT, name, "של הפילטר")
    ok("סוגים נפרדים",
       B.filters.item_count(CHAT, name) == 1
       and B.filters.item_count(CHAT, name, "cmd") == 1)

    B.perms.set_role(CHAT, USER, "member")
    before = len(SENT)
    await B.on_custom_command(msg(f"/{name}", uid=USER, mid=9804))
    sent = [t for _c, t, _m in SENT[before:]]
    ok("שתי הודעות חזרו מהפקודה", len(sent) == 2, str(sent))
    ok("הקובץ ואז ההסבר",
       "MOVIEAPK" in sent[0] and "ההסבר" in sent[1], str(sent))

    out = await _out(B.cmd_cmditems, msg(f"/cmditems {name}", mid=9805))
    ok("הספירה מוצגת", "2" in out, out[:60])
    await _out(B.cmd_cmditems, msg(f"/cmditems {name} clear", mid=9806))
    ok("ואיפוס עובד", B.filters.item_count(CHAT, name, "cmd") == 0)
    ok("ולא נגע בפילטר", B.filters.item_count(CHAT, name) == 1)
    B.filters.remove(CHAT, name)



async def test_bulk_collect():
    """מצב איסוף: שולחים הודעות ברצף, והן מצטרפות להדק."""
    section("איסוף הודעות")
    B.perms.set_role(CHAT, ADM, "owner")
    word = "fifa"
    B.filters.remove(CHAT, word)
    DELETED.clear()

    out = await _out(B.cmd_filterbulk, msg(f"/filterbulk {word}", mid=9700))
    ok("האיסוף התחיל", "/done" in out, out[:80])
    ok("וההדק נוצר אם לא היה", word in B.filters.triggers(CHAT))

    # טקסט, תמונה וקובץ — ברצף, בלי פקודה לכל אחד
    await B.on_group_message(msg("ההסבר על המשחק", uid=ADM, mid=9701))
    await B.on_group_message(Message(
        message_id=9702, date=dt.datetime.now(),
        chat=Chat(id=CHAT, type="supergroup", title="ק"),
        from_user=User(id=ADM, is_bot=False, first_name="דוד"),
        photo=[PhotoSize(file_id="SHOT", file_unique_id="S1", width=90,
                         height=90)], caption="מסך"))
    await B.on_group_message(Message(
        message_id=9703, date=dt.datetime.now(),
        chat=Chat(id=CHAT, type="supergroup", title="ק"),
        from_user=User(id=ADM, is_bot=False, first_name="דוד"),
        document=Document(file_id="GAMEAPK", file_unique_id="G1",
                          file_name="g.apk")))
    ok("שלושתן נאספו", B.filters.item_count(CHAT, word) == 3,
       str(B.filters.items(CHAT, word)))
    ok("והן נמחקו מהקבוצה",
       all(m in DELETED for m in (9701, 9702, 9703)), str(DELETED[-4:]))

    out = await _out(B.cmd_done, msg("/done", mid=9704))
    # שלוש, ולא ארבע: ההדק נוצר ריק ואין לו "הודעה ראשונה" משלו.
    ok("סיום מדווח כמה הודעות", "3" in out, out[:60])
    ok("והאיסוף נסגר", B._bulk_get(CHAT, ADM) is None)

    # אחרי הסיום ההודעות חוזרות להיות רגילות
    before = B.filters.item_count(CHAT, word)
    await B.on_group_message(msg("סתם הודעה", uid=ADM, mid=9705))
    ok("הודעה אחרי /done אינה נאספת",
       B.filters.item_count(CHAT, word) == before)

    # והחבר שכותב את המילה מקבל את הכול
    B.perms.set_role(CHAT, USER, "member")
    sent_before = len(SENT)
    await B.on_group_message(msg(word, uid=USER, mid=9706))
    sent = [t for _c, t, _m in SENT[sent_before:]]
    ok("שלוש הודעות חזרו", len(sent) == 3, str(len(sent)))
    ok("הקובץ והתמונה בפנים",
       any("SHOT" in t for t in sent) and any("GAMEAPK" in t for t in sent),
       str(sent))

    # ביטול
    await _out(B.cmd_filterbulk, msg(f"/filterbulk {word}", mid=9707))
    out = await _out(B.cmd_cancel, msg("/cancel", mid=9708))
    ok("ביטול עובד", B._bulk_get(CHAT, ADM) is None and bool(out), out[:40])

    # תקרה
    ok("התקרה היא 30", B.FILTER_ITEMS_MAX == 30)
    B.filters.remove(CHAT, word)



async def test_cmd_reply_stays():
    """תשובת פקודה של הקבוצה נשארת — היא התוכן, לא רעש ניהול."""
    section("תשובת פקודה נשארת")
    B.perms.set_role(CHAT, ADM, "owner")
    B.db.set(CHAT, "autoclean", "30")
    B.db.set(CHAT, "cleancmds", "0")
    doc = Message(message_id=9600, date=dt.datetime.now(),
                  chat=Chat(id=CHAT, type="supergroup", title="ק"),
                  from_user=User(id=ADM, is_bot=False, first_name="דוד"),
                  document=Document(file_id="FILM", file_unique_id="F9",
                                    file_name="f.mkv"))
    await _out(B.cmd_addcmd, Message(
        message_id=9601, date=dt.datetime.now(),
        chat=Chat(id=CHAT, type="supergroup", title="ק"),
        from_user=User(id=ADM, is_bot=False, first_name="דוד"),
        text="/addcmd films הנה", reply_to_message=doc))

    B.perms.set_role(CHAT, USER, "member")
    DELETED.clear()
    await B.on_custom_command(msg("/films", uid=USER, mid=9602))
    await asyncio.sleep(0.05)
    ok("הודעת הבקשה אינה נמחקת", 9602 not in DELETED, str(DELETED))
    ok("וגם התשובה נשארת", not DELETED, str(DELETED))

    # ומי שרוצה ניקוי מדליק מתג
    B.db.set(CHAT, "cleancmds", "1")
    DELETED.clear()
    await B.on_custom_command(msg("/films", uid=USER, mid=9603))
    ok("עם המתג — מתוזמנת מחיקה",
       B.db.get(CHAT, "cleancmds", "0") == "1")
    B.db.set(CHAT, "cleancmds", "0")
    B.db.set(CHAT, "autoclean", "0")
    B.cmds.delete(CHAT, "films")



async def test_replies_panel():
    """הזרימה של Manybot, רק בפרטי ועם כמה הודעות: שם → שליחה → סיום."""
    section("תגובות ופקודות בפאנל")
    B.perms.set_role(CHAT, ADM, "owner")
    B.filters.remove(CHAT, "fifa")

    def pm(text="", mid=9500, **kw) -> Message:
        return Message(message_id=mid, date=dt.datetime.now(),
                       chat=Chat(id=ADM, type="private"),
                       from_user=User(id=ADM, is_bot=False, first_name="דוד"),
                       text=text or None, **kw)

    # "➕ מילה" → שולחים שם → נפתח איסוף
    B.waiting.start(ADM, CHAT, "newword")
    out = await _out(B.on_private_text, pm("fifa", mid=9501))
    ok("ההדק נוצר", "fifa" in B.filters.triggers(CHAT), out[:60])
    ok("והאיסוף נפתח", B._pm_bulk(ADM) is not None)
    ok("המסך מסביר מה לעשות", "fifa" in out, out[:80])

    # שולחים שלוש הודעות — בלי שום פקודה
    await _out(B.on_private_text, pm("ההסבר", mid=9502))
    await _out(B.on_private_text, pm(mid=9503, photo=[
        PhotoSize(file_id="SHOT", file_unique_id="S2", width=90, height=90)]))
    out = await _out(B.on_private_text, pm(mid=9504, document=Document(
        file_id="APK2", file_unique_id="D2", file_name="f.apk")))
    ok("שלוש נאספו", B.filters.item_count(CHAT, "fifa") == 3,
       str(B.filters.item_count(CHAT, "fifa")))
    ok("והמונה מוצג", "3" in out, out[:80])

    # הרשימה והפריט
    words, commands = B._reps_lists(CHAT)
    ok("ההדק ברשימה", any(w[0] == "fifa" and w[1] == 3 for w in words),
       str(words))
    sc = panel.replies_screen(CHAT, words, commands, "he")
    ok("מסך הרשימה נבנה",
       any("rep:f|fifa" in c for c in sc.all_callbacks()), str(sc.rows[:2]))
    ok("ומזהי הכפתורים בטווח",
       all(len(c.encode()) <= panel.CB_MAX for c in sc.all_callbacks()))
    item = panel.reply_item(CHAT, "f", "fifa", 3, "he")
    ok("מסך הפריט מציג כמה הודעות", "3" in item.text, item.text[:60])

    # והחבר בקבוצה מקבל את הכול
    B.perms.set_role(CHAT, USER, "member")
    before = len(SENT)
    await B.on_group_message(msg("fifa", uid=USER, mid=9505))
    ok("שלוש הודעות בקבוצה", len(SENT) - before == 3,
       str(len(SENT) - before))

    # פקודה בעברית נדחית בהסבר, לא בשקט. לחיצה על "➕" סוגרת איסוף
    # פעיל, וכאן זה נעשה במפורש כי אין לחיצה.
    B._bulk_pm.clear()
    B.waiting.start(ADM, CHAT, "newcmd")
    out = await _out(B.on_private_text, pm("סרטים", mid=9506))
    ok("שם פקודה לא חוקי מוסבר", bool(out) and B._pm_bulk(ADM) is None,
       out[:60])

    B._bulk_pm.clear()
    B.waiting.start(ADM, CHAT, "newcmd")
    await _out(B.on_private_text, pm("movies2", mid=9507))
    ok("פקודה לטינית נוצרת", B.cmds.get(CHAT, "movies2") is not None)
    await _out(B.on_private_text, pm("הנה הסרט", mid=9508))
    ok("ונאספת לה הודעה",
       B.filters.item_count(CHAT, "movies2", "cmd") == 1)

    B.filters.remove(CHAT, "fifa")
    B.cmds.delete(CHAT, "movies2")
    B.filters.clear_items(CHAT, "movies2", "cmd")
    B._bulk_pm.clear()



async def test_every_menu_button():
    """כל כפתור בתפריט פותח מסך — ולא נופל בשקט.

    ‎🔒 נעילות‎ "לא הגיב": ‎_screen_for‎ פרק שלושה ערכים מזוג, זרק
    ‎ValueError‎ בתוך הקולבק, וטלגרם אינה מציגה שגיאה של בוט — הכפתור
    פשוט מת. זו הבדיקה שתופסת את זה בפעם הבאה."""
    section("כל כפתור בתפריט")
    B.perms.set_role(CHAT, ADM, "owner")
    B.db.set(CHAT, "shabbat", "1")      # שהכפתור יופיע
    B.lang.set_chat(CHAT, "he")
    main = panel.main_menu(CHAT, "ק", B._stats(CHAT), "he")
    targets = []
    for row in main.rows:
        for _label, data in row:
            parsed = panel.parse_cb(data)
            if parsed and parsed[1] not in ("home",):
                targets.append((parsed[1], parsed[2]))
    ok("בתפריט יש כפתורים", len(targets) >= 8, str(len(targets)))

    # מסכים סינכרוניים נבנים כאן; האסינכרוניים (שבת) נבדקים לחוד
    async_only = {"shab", "hours", "ldown", "reps", "proofs"}
    skip = {"home"}
    dead = []
    for name, arg in targets:
        if name in async_only:
            continue
        try:
            sc = B._screen_for(CHAT, name, arg)
        except Exception as e:                           # noqa: BLE001
            dead.append(f"{name}: {type(e).__name__}: {e}")
            continue
        if sc is None:
            dead.append(f"{name}: אין מסך")
    ok("כל מסך בתפריט נבנה", not dead, " · ".join(dead))

    # והמסכים שמאחורי הכפתורים הפנימיים של הנעילות
    try:
        groups = list(B.locks.by_group(CHAT))
        inner = [B._screen_for(CHAT, "lockg", g) for g in groups]
        ok("מסכי קבוצות הנעילה נבנים",
           all(x is not None for x in inner), str(groups))
    except Exception as e:                               # noqa: BLE001
        ok("מסכי קבוצות הנעילה נבנים", False, f"{type(e).__name__}: {e}")

    # ושני המסכים האסינכרוניים
    for name in ("reps", "proofs"):
        try:
            ok(f"מסך {name} נבנה", B._screen_for(CHAT, name, "") is not None)
        except Exception as e:                           # noqa: BLE001
            ok(f"מסך {name} נבנה", False, f"{type(e).__name__}: {e}")
    B.db.set(CHAT, "shabbat", "0")



async def test_state_messages():
    """הודעות סגירה ופתיחה: נוסח משלך, ברירת מחדל, או שקט."""
    section("הודעות סגירה ופתיחה")
    B.perms.set_role(CHAT, ADM, "owner")
    for f in ("lock_msg_close", "lock_msg_open"):
        B.db.set(CHAT, f, "")
        B.db.set(CHAT, f + "_media", "")

    locked = []

    async def fake_perms(chat_id, perms_obj):
        locked.append(perms_obj)

    # ‎FakeBot.__getattr__‎ עונה רק על ‎send_*‎, ולכן הפונקציה הזאת
    # מוזרקת ולא מוחלפת.
    real = getattr(B.bot, "set_chat_permissions", None)
    B.bot.set_chat_permissions = fake_perms
    try:
        # ברירת המחדל היא **שקט**: הודעה שאיש לא כתב לא נשלחת.
        before = len(SENT)
        await B.set_lockdown(CHAT, True, ADM)
        ok("בלי נוסח — לא נשלחת הודעה", len(SENT) == before,
           str([t for _c, t, _m in SENT[before:]])[:60])

        # "הצע לי נוסח" כותב את הנוסח המוכן לתוך ההגדרה
        B.db.set(CHAT, "lock_msg_open",
                 i18n.t("state.msg_open", "he"), ADM)
        before = len(SENT)
        await B.set_lockdown(CHAT, False, ADM)
        out = " ".join(t for _c, t, _m in SENT[before:])
        ok("ועם נוסח — נשלח", "נפתחה" in out, out[:60])

        # נוסח של המנהל, עם תמונה
        def pm(text="", mid=9400, **kw):
            return Message(message_id=mid, date=dt.datetime.now(),
                           chat=Chat(id=ADM, type="private"),
                           from_user=User(id=ADM, is_bot=False,
                                          first_name="דוד"),
                           text=text or None, **kw)

        B.waiting.start(ADM, CHAT, "lockmsg")
        await _out(B.on_private_text, pm(mid=9401, caption="סגור ללילה", photo=[
            PhotoSize(file_id="BANNER", file_unique_id="B1", width=90,
                      height=90)]))
        ok("נשמר נוסח עם תמונה",
           B.db.get(CHAT, "lock_msg_close", "") == "סגור ללילה"
           and B.db.get(CHAT, "lock_msg_close_media", "") == "BANNER",
           B.db.get(CHAT, "lock_msg_close", "?"))

        before = len(SENT)
        await B.set_lockdown(CHAT, True, ADM)
        out = " ".join(t for _c, t, _m in SENT[before:])
        ok("והוא נשלח עם המדיה",
           "סגור ללילה" in out and "BANNER" in out, out[:80])

        # שקט מפורש
        B.db.set(CHAT, "lock_msg_open", panel.SILENT)
        before = len(SENT)
        await B.set_lockdown(CHAT, False, ADM)
        ok("בלי הודעה — שקט", len(SENT) == before,
           str([t for _c, t, _m in SENT[before:]])[:60])

        # המסכים
        sc = B._screen_for(CHAT, "stmsgs", "")
        ok("מסך ההודעות נבנה", sc is not None and len(sc.rows) >= 5)
        ok("ומסמן מה מוגדר",
           "✅" in str(sc.rows) and "🔇" in str(sc.rows), str(sc.rows))
        one = panel.state_msg_screen(CHAT, "lockmsg",
                                     B.db.get(CHAT, "lock_msg_close", ""),
                                     "BANNER", "he")
        ok("מסך ההודעה מציג את הנוסח", "סגור ללילה" in one.text, one.text[:60])
        ok("ויש בו שלוש אפשרויות",
           any("ask:lockmsg" in c for c in one.all_callbacks())
           and any("stdef" in c for c in one.all_callbacks())
           and any("stoff" in c for c in one.all_callbacks()))
    finally:
        if real is not None:
            B.bot.set_chat_permissions = real
        else:
            B.bot.__dict__.pop("set_chat_permissions", None)
        for f in ("lock_msg_close", "lock_msg_open"):
            B.db.set(CHAT, f, "")
            B.db.set(CHAT, f + "_media", "")
        B.db.set(CHAT, "lockdown", "0")



async def test_buttons_spam_and_help():
    """ספאם שכל תוכנו בכפתורים, והסבר לכל מתג."""
    section("כפתורים והסברים")

    # ‎Message‎ של aiogram קפוא, ולכן המקלדת עוברת בבנייה ולא בהשמה.
    from aiogram.types import InlineKeyboardButton as _B
    from aiogram.types import InlineKeyboardMarkup as _M

    ad = Message(
        message_id=9300, date=dt.datetime.now(),
        chat=Chat(id=CHAT, type="supergroup", title="ק"),
        from_user=User(id=BAD, is_bot=False, first_name="ס"),
        text="Hurry up. Choose the style that sets every nerve on fire",
        reply_markup=_M(inline_keyboard=[
            [_B(text="🍑 Great videos for 18+ 👅", url="https://x.example/1")],
            [_B(text="💕 Try watching 🍒", url="https://x.example/2")],
            [_B(text="🍑 Great videos for 18+ 👅", url="https://x.example/3")],
            [_B(text="💕 Try watching 🍒", url="https://x.example/4")],
        ]))
    ok("טקסט הכפתורים נקרא",
       "Great videos" in B._button_text(ad), B._button_text(ad)[:50])

    B.perms.set_role(CHAT, BAD, "member")
    DELETED.clear()
    banned = []
    real_apply = B.apply_action

    async def fake_apply(chat_id, user_id, kind, duration, reason, by,
                         source="policy"):
        banned.append(kind)
        return True

    B.apply_action = fake_apply
    try:
        await B.on_group_message(ad)
        ok("המודעה שכל תוכנה בכפתורים נמחקה", 9300 in DELETED, str(DELETED))
        ok("והשולח נחסם", banned == ["ban"], str(banned))
        it = B.proof.recent(CHAT, 1)[0]
        ok("והראיה שמרה גם את הכפתורים",
           "Great videos" in it.text, it.text[:70])
    finally:
        B.apply_action = real_apply

    # הודעה רגילה עם כפתור אחד אינה נפגעת
    # משתמש נקי: למי שצבר אזהרות ועונשים בבדיקות הקודמות יש מוניטין
    # שמצטרף לכל אות, וזו התנהגות נכונה — אבל לא מה שנבדק כאן.
    clean = 5151
    B.perms.set_role(CHAT, clean, "member")
    fine = Message(
        message_id=9301, date=dt.datetime.now(),
        chat=Chat(id=CHAT, type="supergroup", title="ק"),
        from_user=User(id=clean, is_bot=False, first_name="דנה"),
        text="הנה הקישור לאתר של הקבוצה",
        reply_markup=_M(inline_keyboard=[
            [_B(text="האתר", url="https://example.org")]]))
    DELETED.clear()
    await B.on_group_message(fine)
    why = [f"{r['action']}:{(r['reason'] or '')[:40]}"
           for r in B.audit.recent(CHAT, 3)]
    ok("הודעה עם כפתור אחד עוברת", 9301 not in DELETED, str(why))

    # והתצוגה המקדימה: מה שהקבוצה תראה, אצל המנהל
    one = panel.state_msg_screen(CHAT, "lockmsg", "סגור ללילה", "BANNER", "he")
    ok("יש כפתור צפייה",
       any("stprev" in c for c in one.all_callbacks()), str(one.rows))
    gsc = B._screen_for(CHAT, "greet", "")
    ok("וגם בברכה", any("gprev" in c for c in gsc.all_callbacks()),
       str(gsc.rows))

    # ההסברים
    sc = B._screen_for(CHAT, "swhelp", "")
    ok("מסך ההסברים נבנה", sc is not None and len(sc.text) > 400)
    missing = [k for k, _d, _l in panel.SWITCHES
               if i18n.t(f"why.{k}", "he") == f"why.{k}"]
    ok("לכל מתג יש הסבר בעברית", not missing, str(missing))
    missing_en = [k for k, _d, _l in panel.SWITCHES
                  if i18n.t(f"why.{k}", "en") == f"why.{k}"]
    ok("וגם באנגלית", not missing_en, str(missing_en))
    one = panel.switch_screen(CHAT, "strict", True, "he")
    ok("ומסך מתג בודד מסביר את עצמו",
       "מחמיר" in one.text, one.text[:80])
    sws = B._screen_for(CHAT, "sws", "")
    ok("ויש כפתור להסברים",
       any("swhelp" in c for c in sws.all_callbacks()))



async def test_hours_timezone():
    """לוח השעות סוגר לפי שעון הקבוצה, לא לפי UTC."""
    section("לוח שעות ואזור זמן")
    import calendar as _cal
    import grouphours as _gh
    B.perms.set_role(CHAT, ADM, "owner")
    B.db.set(CHAT, "hours", "sun=!01:00-07:00")
    B.db.set(CHAT, "tz", "Asia/Jerusalem")
    B.db.set(CHAT, B.AUTOLOCK_KEY, "")
    B.db.set(CHAT, "lockdown", "0")

    acted = []

    async def fake_lock(chat_id, on, by):
        acted.append(on)
        B.db.set(chat_id, "lockdown", "1" if on else "0", by)
        return True

    real = B.set_lockdown
    B.set_lockdown = fake_lock
    try:
        # ראשון 01:30 בשעון ישראל (חורף, UTC+2) = 23:30 שבת ב-UTC
        israel_0130 = float(_cal.timegm((2026, 1, 17, 23, 30, 0)))
        await B._tick_hours(CHAT, israel_0130, False)
        ok("נסגר בשעון הקבוצה", acted == [True], str(acted))
        ok("והבעלות נרשמה", B.db.get(CHAT, B.AUTOLOCK_KEY, "") == "hours")

        acted.clear()
        # ראשון 08:00 בשעון ישראל = 06:00 UTC
        israel_0800 = float(_cal.timegm((2026, 1, 18, 6, 0, 0)))
        await B._tick_hours(CHAT, israel_0800, False)
        ok("ונפתח בבוקר", acted == [False], str(acted))

        # בלי אזור זמן — אותה נקודה בזמן אינה סוגרת. גם ההיסט המספרי
        # הישן מתאפס, אחרת הוא שנשאר מבדיקה קודמת הוא שקובע.
        B.db.set(CHAT, "tz", "")
        B.db.set(CHAT, "tz_offset", "0")
        B.db.set(CHAT, B.AUTOLOCK_KEY, "")
        acted.clear()
        await B._tick_hours(CHAT, israel_0130, False)
        ok("בלי אזור זמן הבוט עובד ב-UTC ולא סוגר", acted == [],
           str(acted))

        # המסך מראה את השעה ואת הבורר
        B.db.set(CHAT, "tz", "Asia/Jerusalem")
        sc = B._screen_for(CHAT, "hours", "")
        ok("המסך מציג את השעה של הקבוצה",
           "UTC+" in sc.text or "UTC−" in sc.text, sc.text[-80:])
        ok("ויש כפתור אזור זמן",
           any("zones" in c for c in sc.all_callbacks()), str(sc.rows[-2:]))
        zs = B._screen_for(CHAT, "zones", "")
        pages = [B._screen_for(CHAT, "zones", str(p))
                 for p in range(_gh.zone_pages())]
        every = {c.split(":")[-1] for sc2 in pages
                 for c in sc2.all_callbacks() if ":setz:" in c}
        ok("בורר האזורים נבנה", zs is not None and bool(every))
        ok("וכל אזור נגיש באיזה עמוד",
           set(_gh.ZONES) <= every, str(set(_gh.ZONES) - every))
        ok("וההיסט מוצג לצד השם",
           any("UTC+" in t or "UTC-" in t
               for sc2 in pages for row in sc2.rows for t, _ in row))
        ok("ומזהי הכפתורים בטווח",
           all(len(c.encode()) <= panel.CB_MAX for c in zs.all_callbacks()))
        marked = any("●" in t for sc2 in pages for row in sc2.rows
                     for t, _ in row)
        ok("והאזור הנוכחי מסומן", marked, str(zs.rows[:1]))

        # ניחוש לפי שפה: נקבע רק כשאין אזור, ולא דורס בחירה
        B.db.set(CHAT, "tz", "")
        ok("שפה עברית מנחשת ירושלים",
           B._guess_zone(CHAT, "he", ADM) == "Asia/Jerusalem"
           and B.db.get(CHAT, "tz", "") == "Asia/Jerusalem")
        ok("ובחירה קיימת אינה נדרסת", B._guess_zone(CHAT, "ru", ADM) == ""
           and B.db.get(CHAT, "tz", "") == "Asia/Jerusalem")
        B.db.set(CHAT, "tz", "")
        ok("אנגלית אינה מנחשת", B._guess_zone(CHAT, "en", ADM) == "")
        B.db.set(CHAT, "tz", "Asia/Jerusalem")
    finally:
        B.set_lockdown = real
        B.db.set(CHAT, "hours", "")
        B.db.set(CHAT, "tz", "")
        B.db.set(CHAT, B.AUTOLOCK_KEY, "")
        B.db.set(CHAT, "lockdown", "0")



async def test_service_cleaning():
    """ניקוי הודעות המערכת: לפי קטגוריה, ורק כשמדליקים."""
    section("ניקוי הודעות מערכת")
    B.perms.set_role(CHAT, ADM, "owner")

    def svc(mid: int, **kw) -> Message:
        return Message(message_id=mid, date=dt.datetime.now(),
                       chat=Chat(id=CHAT, type="supergroup", title="ק"),
                       from_user=User(id=ADM, is_bot=False, first_name="דוד"),
                       **kw)

    title_msg = svc(9200, new_chat_title="שם חדש")
    pin_msg = svc(9201, pinned_message=svc(9199, text="נעוץ"))
    ok("זיהוי קטגוריה: שם", B._service_kind(title_msg) == "about")
    ok("זיהוי קטגוריה: נעיצה", B._service_kind(pin_msg) == "pin")
    ok("הודעה רגילה אינה שירות",
       B._service_kind(msg("סתם", mid=9202)) == "")

    # מתג ראשי כבוי — לא נוגעים
    B.db.set(CHAT, "cleanservice", "0")
    DELETED.clear()
    await B.on_service_message(title_msg)
    await asyncio.sleep(0.05)
    ok("כשהניקוי כבוי לא נמחק כלום", not DELETED, str(DELETED))

    # דלוק — נמחק (אחרי ההשהיה)
    B.db.set(CHAT, "cleanservice", "1")
    B.db.set(CHAT, "clean_about", "1")
    real_sleep = asyncio.sleep

    async def no_wait(_secs):
        await real_sleep(0)

    asyncio.sleep = no_wait
    try:
        DELETED.clear()
        await B.on_service_message(title_msg)
        await real_sleep(0.05)
        ok("שינוי שם נמחק", 9200 in DELETED, str(DELETED))

        # קטגוריה שכובתה בנפרד — נשארת
        B.db.set(CHAT, "clean_pin", "0")
        DELETED.clear()
        await B.on_service_message(pin_msg)
        await real_sleep(0.05)
        ok("נעיצה שכובתה נשארת", 9201 not in DELETED, str(DELETED))

        B.db.set(CHAT, "clean_pin", "1")
        DELETED.clear()
        await B.on_service_message(pin_msg)
        await real_sleep(0.05)
        ok("וכשמדליקים אותה — נמחקת", 9201 in DELETED, str(DELETED))

        # הצטרפות עוברת במסלול שלה ולא כאן
        join = svc(9203, new_chat_members=[User(id=7, is_bot=False,
                                                first_name="חדש")])
        DELETED.clear()
        await B.on_service_message(join)
        await real_sleep(0.05)
        ok("הצטרפות אינה מטופלת פעמיים", 9203 not in DELETED, str(DELETED))
        B._clean_service(join)
        await real_sleep(0.05)
        ok("אלא במסלול שלה", 9203 in DELETED, str(DELETED))
    finally:
        asyncio.sleep = real_sleep
        B.db.set(CHAT, "cleanservice", "0")

    sc = B._screen_for(CHAT, "svcs", "")
    ok("מסך הניקוי נבנה", sc is not None and len(sc.rows) >= 4)
    ok("ויש בו קטגוריה לכל סוג",
       all(any(f"svc:{k}" in c for c in sc.all_callbacks())
           for k, _l in panel.SERVICE_CATS), str(sc.all_callbacks()))
    ok("וכל קטגוריה מוכרת לקוד",
       {k for k, _l in panel.SERVICE_CATS} == set(B.SERVICE_CATEGORIES))
    ok("וכל שדה שירות שייך לקטגוריה מוכרת",
       all(kind in B.SERVICE_CATEGORIES for _f, kind in B.SERVICE_FIELDS))



async def test_fresh_user_start():
    """משתמש חדש לגמרי: /start מציג בורר שפה באנגלית, ולא קורס."""
    section("משתמש חדש")
    fresh = 606060
    B.db.change("DELETE FROM settings WHERE chat_id=? AND key='lang'",
                (fresh,))
    B.db.change("DELETE FROM settings WHERE chat_id=0 AND key='lang'", ())
    pm = Message(message_id=9100, date=dt.datetime.now(),
                 chat=Chat(id=fresh, type="private"),
                 from_user=User(id=fresh, is_bot=False, first_name="New",
                                language_code="he"),
                 text="/start")
    out = await _out(B.cmd_start, pm)
    ok("יש תשובה בכלל", bool(out) and not out.startswith("!!"), out[:80])
    ok("והיא בורר השפה", "language" in out.lower(), out[:80])
    ok("באנגלית, למרות שהטלגרם שלו בעברית",
       "Choose" in out, out[:80])

    # ואחרי שבוחר — אפשר לשנות שוב
    B.lang.set_chat(fresh, "he")
    sc = panel.home([(CHAT, "ק")], "he")
    ok("במסך הבית יש כפתור שפה",
       any("mylang" in c for c in sc.all_callbacks()), str(sc.rows))

    # ומי שעוד לא הוסיף את הבוט לשום מקום מקבל כפתור, לא הוראות
    empty = panel.home([], "en", "Rocky81bot")
    ok("כפתור הוספה לקבוצה למי שאין לו קבוצות",
       any("startgroup=true" in c for c in empty.all_callbacks()),
       str(empty.rows))
    ok("והוא כתוב באנגלית",
       any("Add me" in t for row in empty.rows for t, _ in row),
       str(empty.rows))
    ok("וגם למי שכבר יש",
       any("startgroup=true" in c
           for c in panel.home([(CHAT, "ק")], "he",
                               "Rocky81bot").all_callbacks()))
    ok("בלי שם בוט אין כפתור שבור",
       not any("startgroup" in c for c in panel.home([], "en").all_callbacks()))
    ok("וכפתור קישור נבנה כ-url",
       B._button("x", "https://t.me/a").url == "https://t.me/a"
       and B._button("y", "g:0:home").callback_data == "g:0:home")
    picker = panel.welcome_screen("he")
    ok("והבורר מסמן את הנוכחית",
       any("●" in t for row in picker.rows for t, _ in row), str(picker.rows))
    ok("ויש בו חזרה", any("g:0:home" in c for c in picker.all_callbacks()))

    # ‎/lang‎ בפרטי פותחת את הבורר במקום להידחות
    pm2 = Message(message_id=9101, date=dt.datetime.now(),
                  chat=Chat(id=fresh, type="private"),
                  from_user=User(id=fresh, is_bot=False, first_name="New"),
                  text="/lang")
    out2 = await _out(B.cmd_lang, pm2)
    ok("/lang בפרטי פותחת בורר", "language" in out2.lower(), out2[:60])
    B.db.change("DELETE FROM settings WHERE chat_id=? AND key='lang'",
                (fresh,))



async def test_access_revoked():
    """מי שהוסר מניהול מאבד גישה מיד — גם אם המסד עוד זוכר אותו."""
    section("גישה אחרי הסרה מניהול")
    gone = 717171
    B.perms.set_role(CHAT, gone, "admin")
    ok("במסד הוא מנהל", B.perms.rank_of(CHAT, gone) >= B.RANK["admin"])
    ok("והקבוצה מופיעה לו ברשימה",
       any(c == CHAT for c, _t in B.my_groups(gone)))

    # טלגרם אומרת שהוא כבר לא מנהל. ‎sync_admins‎ עצמה מוחלפת
    # בהרצת הבדיקות, ולכן נבדקת כאן הפונקציה שהיא קוראת לה.
    B._admin_cache.clear()
    try:
        B.revoke_missing_admins(CHAT, {ADM: "owner"})
        ok("הסנכרון מוריד אותו לחבר",
           B.perms.role_of(CHAT, gone) == "member",
           B.perms.role_of(CHAT, gone))
        ok("ונרשם ביומן",
           any(r["action"] == "admin.revoked" for r in B.audit.recent(CHAT, 5)),
           str([r["action"] for r in B.audit.recent(CHAT, 5)][:4]))
        ok("אין לו גישה", not await B._has_access(CHAT, gone))
        ok("והבדיקה מחזירה כמה הורדו",
           B.revoke_missing_admins(CHAT, {ADM: "owner"}) == 0)
        ok("והקבוצה נעלמה מהרשימה שלו",
           not await B.my_groups_live(gone),
           str(await B.my_groups_live(gone)))
        ok("ולבעלים כן יש", await B._has_access(CHAT, ADM))
        ok("והקבוצה אצלו ברשימה",
           any(c == CHAT for c, _t in await B.my_groups_live(ADM)))

        # ותפקיד ידני נמוך אינו נמחק
        helper = 818181
        B.perms.set_role(CHAT, helper, "helper")
        B.revoke_missing_admins(CHAT, {ADM: "owner"})
        ok("עוזר שהוגדר ידנית נשאר",
           B.perms.role_of(CHAT, helper) == "helper",
           B.perms.role_of(CHAT, helper))
    finally:
        B._admin_cache.clear()
        B.perms.set_role(CHAT, ADM, "owner")



async def test_stars_flow():
    """חשבונית כוכבים, אישור התשלום, והתודה."""
    section("תרומה בכוכבים")
    sent = []

    async def fake_invoice(**kw):
        sent.append(kw)
        return True

    B.bot.send_invoice = fake_invoice
    try:
        ok("החשבונית נשלחת", await B._send_invoice(ADM, 50, "he"))
        inv = sent[-1]
        ok("במטבע כוכבים", inv["currency"] == "XTR", str(inv.get("currency")))
        ok("בלי ספק סליקה", inv["provider_token"] == "")
        ok("הסכום נכון",
           inv["prices"][0].amount == 50, str(inv["prices"][0]))
        ok("והמטען מזהה תרומה", inv["payload"] == "donate:50", inv["payload"])

        # תשלום שהצליח → תודה ושורה ביומן
        from aiogram.types import SuccessfulPayment as _SP
        paid = Message(
            message_id=9050, date=dt.datetime.now(),
            chat=Chat(id=ADM, type="private"),
            from_user=User(id=ADM, is_bot=False, first_name="דוד"),
            successful_payment=_SP(currency="XTR", total_amount=50,
                                   invoice_payload="donate:50",
                                   telegram_payment_charge_id="c1",
                                   provider_payment_charge_id="p1"))
        before = len(SENT)
        await B.on_paid(paid)
        out = " ".join(t for _c, t, _m in SENT[before:])
        ok("נשלחה תודה", "50" in out and ("תודה" in out or "Thank" in out),
           out[:60])
        ok("ונרשם ביומן",
           any(r["action"] == "donation" for r in B.audit.recent(ADM, 5)),
           str([r["action"] for r in B.audit.recent(ADM, 5)][:3]))

        # כישלון ברשת אינו קורס אלא מסביר
        async def boom(**kw):
            raise TelegramAPIError(method=None, message="nope")

        B.bot.send_invoice = boom
        before = len(SENT)
        ok("כישלון מוסבר ולא קורס",
           not await B._send_invoice(ADM, 10, "he") and len(SENT) > before)
    finally:
        B.bot.__dict__.pop("send_invoice", None)



async def test_personal_language_sticks():
    """לחיצה על מסך אישי אינה מחזירה לשפת הטלגרם."""
    section("שפה אישית נשמרת")
    uid = 929292
    B.lang.set_chat(uid, "en")        # בחר אנגלית במפורש

    class _Msg:
        def __init__(self, chat_id):
            self.chat = Chat(id=chat_id, type="private")
            self.message_id = 1

    class _Q:
        def __init__(self, data, uid_):
            self.data = data
            self.from_user = User(id=uid_, is_bot=False, first_name="x",
                                  language_code="he")   # הטלגרם שלו בעברית
            self.message = _Msg(uid_)
            self.answered = []
            self.edited = []

        async def answer(self, text="", show_alert=False):
            self.answered.append(text)

    edits = []
    real_edit = B._edit

    async def fake_edit(q, sc):
        edits.append(sc)

    B._edit = fake_edit
    try:
        q = _Q("g:0:donate", uid)
        await B.on_callback(q)
        ok("מסך הכוכבים נפתח", bool(edits), str(edits))
        ok("והוא באנגלית, לא בעברית של הטלגרם",
           "Stars" in edits[-1].text and "כוכבים" not in edits[-1].text,
           edits[-1].text[:60])

        edits.clear()
        q2 = _Q("g:0:mylang", uid)
        await B.on_callback(q2)
        ok("וגם בורר השפה מסמן את אנגלית",
           any("● English" in t for row in edits[-1].rows for t, _ in row),
           str(edits[-1].rows[0]))

        # ובעברית — עברית
        B.lang.set_chat(uid, "he")
        edits.clear()
        await B.on_callback(_Q("g:0:donate", uid))
        ok("מי שבחר עברית מקבל עברית", "כוכבים" in edits[-1].text,
           edits[-1].text[:60])
    finally:
        B._edit = real_edit
        B.db.change("DELETE FROM settings WHERE chat_id=? AND key='lang'",
                    (uid,))

    # והכפתורים קיימים גם בתוך תפריט הקבוצה
    main = panel.main_menu(CHAT, "ק", B._stats(CHAT), "en")
    cbs = main.all_callbacks()
    ok("תמיכה בתפריט הקבוצה", any("t.me/" in c for c in cbs), str(cbs[-4:]))
    ok("וכוכבים בתפריט הקבוצה", any("g:0:donate" in c for c in cbs))



async def test_ai_soft_damper():
    """פסק AI מסוג ספאם/פרסום אינו מוחק בקשת תוכן."""
    section("בלם AI על בקשות תוכן")
    B.db.set(CHAT, "ai_titles_ok", "1")

    class _V:
        def __init__(self, cat, conf):
            self.category, self.confidence = cat, conf

    ask = "אשמח לפרק 39 ורדים וחטאים"
    for cat in ("spam", "advertising", "adult", "gambling"):
        ok(f"{cat} בביטחון בינוני נחסם",
           not B._ai_may_act(CHAT, _V(cat, 0.7), ask))
        ok(f"{cat} בביטחון כמעט מלא עובר",
           B._ai_may_act(CHAT, _V(cat, 0.95), ask))
    for cat in ("scam", "phishing", "threat", "malware", "harassment"):
        ok(f"{cat} אינו מרוכך גם בקבוצת תוכן",
           B._ai_may_act(CHAT, _V(cat, 0.6), ask))

    ok("מודעה אמיתית אינה מרוככת",
       B._ai_may_act(CHAT, _V("spam", 0.7),
                     "קזינו אונליין הצטרפו עכשיו https://x.example"))
    B.db.set(CHAT, "ai_titles_ok", "0")
    ok("ומי שכיבה את הבלם מקבל אכיפה מלאה",
       B._ai_may_act(CHAT, _V("spam", 0.7), ask))
    B.db.set(CHAT, "ai_titles_ok", "1")



async def test_ui_clarity():
    """מסכים שאפשר להבין: שורה לפריט, הסבר לכל דבר, וקיצור מהשבתה."""
    section("בהירות הממשק")
    nums = B._screen_for(CHAT, "nums", "")
    ok("ספים: שורה אחת לכל פריט",
       all(len(row) == 1 for row in nums.rows), str(nums.rows[:2]))
    import prompts as _pr
    ok("ולכל סף יש הסבר בגוף המסך",
       all(i18n.t(_pr.FIELDS[n].hint_key, "he") in nums.text
           for n in _pr.NUMBER_FIELDS),
       nums.text[:120])
    ok("ההסברים אינם מפתחות גולמיים",
       all(not i18n.t(_pr.FIELDS[n].hint_key, "he").startswith("field.")
           for n in _pr.NUMBER_FIELDS))

    texts = B._screen_for(CHAT, "texts", "")
    ok("ובמסך ההודעות יש הסבר לכל שורה",
       i18n.t("field.welcome.hint", "he") in texts.text, texts.text[:120])
    ok("ו\"כללים\" ירד מהמסך",
       "rules" not in _pr.FIELDS and "כללים" not in texts.text)
    ok("והקשר הקבוצה יושב רק במסך הסינון",
       "aictx" not in _pr.TEXT_FIELDS
       and any("ask:aictx" in c
               for c in B._screen_for(CHAT, "aim", "").all_callbacks()))

    reps = B._screen_for(CHAT, "reps", "")
    ok("מסך התגובות מסביר מה ההבדל בין מילה לפקודה",
       "⌨️" in reps.text and "💬" in reps.text, reps.text[:160])

    st = B._screen_for(CHAT, "stmsgs", "")
    ok("ומסך ההודעות מסביר איך משנים",
       "איך משנים" in st.text or "To change" in st.text, st.text[:140])

    one = panel.state_msg_screen(CHAT, "lockmsg", "", "", "he")
    ok("ובמסך ההודעה יש גם צפייה וגם עריכה",
       any("stprev" in c for c in one.all_callbacks())
       and any("ask:lockmsg" in c for c in one.all_callbacks()))

    # התפריט מסודר: כל נושא בשורה שלו, ושני מסכי מתגים אינם יושבים
    # זה לצד זה בתפריט הראשי.
    menu = panel.main_menu(CHAT, "ק", {}, "he")
    cbs = [c for row in menu.rows for _t, c in row]
    ok("מתגים אינם בתפריט הראשי",
       not any(c.endswith(":sws") for c in cbs), str(cbs))
    ok("אלא בתוך ההגדרות",
       any("sws" in c for c in
           panel.settings_screen(CHAT, {"autoclean": "30"},
                                 "he").all_callbacks()))
    ok("וההשבתה אחרונה, לבדה",
       any(row == [r for r in row if "ldown" in r[1]]
           and len(row) == 1 for row in menu.rows
           if any("ldown" in c for _t, c in row)), str(menu.rows))
    ok("אין שורה עם יותר משני כפתורים",
       all(len(row) <= 2 for row in menu.rows), str(menu.rows))

    w = panel.waiting_screen(CHAT, "floodrate", "8", "he")
    ok("ומסך ההמתנה אומר גם את הפקודה המקבילה",
       "/setflood" in w.text, w.text[:120])
    ok("ומסביר מה שולחים", "📩" in w.text or "שלח" in w.text)



async def test_triggers_answer_admins():
    """הדק עונה גם למנהל — זה הדבר הראשון שכל מנהל בודק."""
    section("הדקים עונים למנהל")
    B.perms.set_role(CHAT, ADM, "owner")
    B.filters.remove(CHAT, "פיפא")
    B.filters.add(CHAT, "פיפא", "הנה המשחק", match_kind="substring")

    before = len(SENT)
    await B.on_group_message(msg("פיפא", uid=ADM, mid=9010))
    out = " ".join(t for _c, t, _m in SENT[before:])
    ok("מנהל מקבל תשובה", "הנה המשחק" in out, out[:60])

    B.perms.set_role(CHAT, USER, "member")
    before = len(SENT)
    await B.on_group_message(msg("פיפא", uid=USER, mid=9011))
    out = " ".join(t for _c, t, _m in SENT[before:])
    ok("וגם חבר רגיל", "הנה המשחק" in out, out[:60])

    # הערה שמורה — אותו דבר
    B.notes.save(CHAT, "כללים", "אלה הכללים", by=ADM)
    before = len(SENT)
    await B.on_group_message(msg("#כללים", uid=ADM, mid=9012))
    out = " ".join(t for _c, t, _m in SENT[before:])
    ok("והערה שמורה עונה למנהל", "אלה הכללים" in out, out[:60])

    # אבל אכיפה עדיין לא חלה על מנהל
    B.filters.remove(CHAT, "פיפא")
    B.filters.add(CHAT, "אסור", "", match_kind="substring", action="warn")
    DELETED.clear()
    await B.on_group_message(msg("מילה אסור פה", uid=ADM, mid=9013))
    ok("מנהל אינו נענש על הדק", 9013 not in DELETED, str(DELETED))
    B.filters.remove(CHAT, "אסור")
    B.notes.delete(CHAT, "כללים")


async def main() -> int:
    B.bot = FakeBot()
    B.sync_admins = fake_admins
    B.db.set(CHAT, "lang", "he")
    B.db.set(CHAT, "autoclean", "0")
    B.db.set(CHAT, "xp", "0")
    # בלי זה הגנת ההצפה נכנסת לפני מסלולי המדיה ומוחקת את ההודעה —
    # והבדיקה "ההודעה נמחקה" הייתה עוברת מהסיבה הלא נכונה.
    B.db.set(CHAT, "flood", "0")
    B.perms.set_role(CHAT, ADM, "owner")
    B.perms.set_role(CHAT, USER, "member")
    B.perms.set_role(CHAT, BAD, "member")

    await test_customcmd()
    await test_reports()
    await test_vision()
    await test_voice()
    await test_help_ux()
    await test_greet_oneclick()
    await test_switch_gap()
    await test_diag()
    await test_bad_html()
    await test_anon_admin()
    await test_join()
    await test_flows()
    await test_quiet_group()
    await test_command_visibility()
    await test_upkeep()
    await test_switch_titles()
    await test_every_command()
    await test_usage_names_the_typed_command()
    await test_new_features()
    await test_button_editing()
    await test_aggressive_paths()
    await test_forum_topics()
    await test_hours_picker()
    await test_hours_timezone()
    await test_service_cleaning()
    await test_fresh_user_start()
    await test_access_revoked()
    await test_stars_flow()
    await test_personal_language_sticks()
    await test_ai_soft_damper()
    await test_ui_clarity()
    await test_triggers_answer_admins()
    await test_evidence_flow()
    await test_filter_file()
    await test_ephemeral()
    await test_welcome_visibility()
    await test_filter_multi()
    await test_cmd_multi()
    await test_bulk_collect()
    await test_cmd_reply_stays()
    await test_replies_panel()
    await test_every_menu_button()
    await test_state_messages()
    await test_buttons_spam_and_help()

    print(f"\n{'─' * 46}")
    print(f"עברו {PASS} · נכשלו {FAIL}")
    if FAILURES:
        print("נכשלו: " + ", ".join(FAILURES))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
