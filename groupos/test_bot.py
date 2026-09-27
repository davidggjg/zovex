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
from aiogram.filters import Command, CommandStart          # noqa: E402
from aiogram.types import (Chat, Message, PhotoSize, User,  # noqa: E402
                           Voice)
import panel                                               # noqa: E402
import permissions                                         # noqa: E402

CHAT, ADM, USER, BAD = -1001234567890, 90, 11, 13

PASS = FAIL = 0
FAILURES: list[str] = []
SENT: list[tuple[int, str, bool]] = []
DELETED: list[int] = []
DOWNLOADS: list[str] = []
EDITED: list[str] = []
ANSWERED: list[str] = []
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
        return Message(message_id=9000 + len(SENT), date=dt.datetime.now(),
                       chat=Chat(id=chat_id, type="private"), text=text)

    async def send_photo(self, chat_id, media, caption=None,
                         reply_markup=None, **kw):
        SENT.append((chat_id, f"[photo {media}] {caption or ''}",
                     reply_markup is not None))
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
    await B.cmd_report(msg("/report ספאם", uid=USER, reply_to=victim))
    to_admin = [s for s in SENT if s[0] == ADM]
    ok("ההתראה נשלחה למנהל בפרטי", len(to_admin) == 1, str(len(to_admin)))
    ok("להתראה יש כפתורים", to_admin[-1][2])
    ok("המדווח קיבל אישור", "נשלח" in last(), last())

    open_ = B.rpt.list(CHAT)
    ok("נפתח דיווח אחד", len(open_) == 1, str(open_))
    rid = open_[0].id

    await B.cmd_report(msg("/report גם קישור", uid=ADM, reply_to=victim))
    ok("דיווח שני מצטרף ולא מתריע שוב",
       len([s for s in SENT if s[0] == ADM and s[2]]) == 1
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

        # ‎decide‎ מחזיר החלטה תמיד; ‎action="none"‎ אינו מחיקה
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
    await test_upkeep()
    await test_every_command()

    print(f"\n{'─' * 46}")
    print(f"עברו {PASS} · נכשלו {FAIL}")
    if FAILURES:
        print("נכשלו: " + ", ".join(FAILURES))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
