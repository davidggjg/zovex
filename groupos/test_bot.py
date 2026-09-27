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
from aiogram.enums import ChatMemberStatus                # noqa: E402
from aiogram.filters import Command, CommandStart          # noqa: E402
from aiogram.types import (Chat, ChatMemberLeft,           # noqa: E402
                           ChatMemberMember, ChatMemberUpdated,
                           Message, PhotoSize, User, Voice)
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
                         clean_after=None):
        if not is_group:
            return None                    # טלגרם דוחה — אין שיחה פרטית
        return await real_send(chat_id, text, is_group=is_group,
                               markup=markup, clean_after=clean_after)

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
    await test_anon_admin()
    await test_join()
    await test_flows()
    await test_quiet_group()
    await test_command_visibility()
    await test_upkeep()
    await test_every_command()

    print(f"\n{'─' * 46}")
    print(f"עברו {PASS} · נכשלו {FAIL}")
    if FAILURES:
        print("נכשלו: " + ", ".join(FAILURES))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
