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
import datetime as dt
import os
import sys
import tempfile

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
from aiogram.types import Chat, Message, PhotoSize, User  # noqa: E402

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

    B.db.set(CHAT, "reports", "0")
    await B.cmd_report(msg("/report x", uid=USER, reply_to=spam_msg(502)))
    ok("כשהדיווחים כבויים לא נפתח דיווח",
       B.rpt.open_count(CHAT) == 0 and "כבויים" in last(), last())
    B.db.set(CHAT, "reports", "1")


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


async def main() -> int:
    B.bot = FakeBot()
    B.sync_admins = fake_admins
    B.db.set(CHAT, "lang", "he")
    B.db.set(CHAT, "autoclean", "0")
    B.db.set(CHAT, "xp", "0")
    B.perms.set_role(CHAT, ADM, "owner")
    B.perms.set_role(CHAT, USER, "member")
    B.perms.set_role(CHAT, BAD, "member")

    await test_customcmd()
    await test_reports()
    await test_vision()

    print(f"\n{'─' * 46}")
    print(f"עברו {PASS} · נכשלו {FAIL}")
    if FAILURES:
        print("נכשלו: " + ", ".join(FAILURES))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
