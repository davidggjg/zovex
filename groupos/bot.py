#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bot — מתאם טלגרם. השכבה הדקה היחידה שיודעת ש-aiogram קיים.

## הכלל שמחזיק את כל הארכיטקטורה

מודול אחד בלבד מייבא ‎aiogram‎ — זה. ‎db‎, ‎permissions‎, ‎audit‎, ‎locks‎,
‎moderation‎, ‎panel‎ ו-‎ratelimit‎ אינם יודעים שקיים טלגרם, ולכן 134 בדיקות
רצות בלי טוקן ובלי רשת.

## הקבוצה נשארת נקייה

שתי החלטות:

  **ניהול בפרטי.** כל ההגדרות דרך ‎/start‎ בצ'אט הפרטי — רשימת הקבוצות,
  ואז כפתורים. אין צורך לשלוח פקודות בקבוצה כדי לנעול אותה.

  **ניקוי אוטומטי.** פקודה שכן נשלחת בקבוצה, והתשובה עליה, נמחקות אחרי
  זמן שנקבע בהגדרות. כך הקבוצה לא מתמלאת בהודעות ניהול.

## זיהוי מנהלים

טלגרם היא מקור האמת. מי שמנהל בקבוצה מקבל ‎admin‎ אצלנו, והבעלים מקבל
‎owner‎ — בסנכרון עצל ששומר תשובה לחמש דקות, כי ‎getChatAdministrators‎
נספרת במכסת הבקשות.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import sys
import time
from functools import wraps
from typing import Callable, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.types import (BufferedInputFile, BotCommand, CallbackQuery,
                           ChatMemberUpdated,
                           ChatPermissions, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import i18n                                     # noqa: E402
import panel                                    # noqa: E402
import aikeys                                   # noqa: E402
import backup                                   # noqa: E402
import policy                                   # noqa: E402
import captcha as cap                           # noqa: E402
import emergency as emerg                       # noqa: E402
import templates as tpl                         # noqa: E402
from allowlist import Allowlist                 # noqa: E402
from antiflood import AntiFlood                 # noqa: E402
from audit import Audit                         # noqa: E402
from blocklist import Blocklist                 # noqa: E402
from content import (Filters, Notes, GOODBYE_KEY, RULES_KEY,  # noqa: E402
                     WELCOME_KEY, parse_buttons)
from db import Db                               # noqa: E402
from locks import ACTIONS, LOCK_TYPES, Locks    # noqa: E402
from moderation import Moderation, parse_policy  # noqa: E402
from permissions import Permissions, RANK       # noqa: E402
from ratelimit import RateGuard                 # noqa: E402

log = logging.getLogger("groupos")

# 78 = EX_CONFIG. ה-unit מורה לא להפעיל מחדש עליו: טוקן שגוי לא יתקן
# את עצמו בניסיון ה-12, הוא רק שורף מעבד.
EX_CONFIG = 78

TOKEN = os.environ.get("GROUPOS_TOKEN", "").strip()
API_BASE = os.environ.get("GROUPOS_API_BASE", "").strip()

db = Db()
perms = Permissions(db)
audit = Audit(db)
locks = Locks(db)
mod = Moderation(db, audit)
notes = Notes(db)
filters = Filters(db)
blocks = Blocklist(db)
flood = AntiFlood()
pending = cap.Pending()
allow = Allowlist(db)
# המפתחות נטענים ממשתני סביבה בלבד ולעולם לא מהמסד: מסד עובר בגיבוי,
# ו-.env עם הרשאות 600 לא.
ai = aikeys.Providers.from_env()
lang = i18n.Lang(db)
guard = RateGuard()
dp = Dispatcher()
bot: Optional[Bot] = None

GROUP_TYPES = (ChatType.GROUP, ChatType.SUPERGROUP)
_admin_cache: dict[int, tuple[float, dict[int, str]]] = {}
# ברירות המחדל של הגנת ההצפה, לדריסה פר-קבוצה דרך settings
AF_RATE, AF_WINDOW, AF_REPEAT, AF_MENTIONS = 8, 10, 4, 8
# תקרת מחיקה בפעולה אחת. כל מחיקה היא קריאת API, ומחיקה של 5000
# הודעות תתקע את הבוט לכל הקבוצות האחרות לדקות.
PURGE_MAX = 200
ADMIN_TTL = 300


# ── שליחה ומחיקה ───────────────────────────────────────────────────────────
async def send(chat_id: int, text: str, *, is_group: bool = True,
               markup=None, clean_after: Optional[int] = None) -> Optional[Message]:
    """היציאה היחידה. עוברת דרך שומר המכסות תמיד."""
    await guard.acquire(chat_id, is_group)
    try:
        m = await bot.send_message(chat_id, text, reply_markup=markup)
    except TelegramRetryAfter as e:
        guard.note_flood_wait(chat_id, float(e.retry_after))
        log.warning("FloodWait %ss בצ'אט %s", e.retry_after, chat_id)
        return None
    except TelegramAPIError as e:
        log.warning("שליחה נכשלה בצ'אט %s: %s", chat_id, e)
        return None
    if clean_after:
        _schedule_delete(chat_id, m.message_id, clean_after)
    return m


def _schedule_delete(chat_id: int, message_id: int, after: int) -> None:
    """מחיקה מושהית. משימת רקע ולא המתנה, כדי לא לתקוע את הטיפול בהודעה."""
    async def run():
        await asyncio.sleep(after)
        with contextlib.suppress(TelegramAPIError):
            await bot.delete_message(chat_id, message_id)
    task = asyncio.create_task(run())
    _bg.add(task)
    task.add_done_callback(_bg.discard)


_bg: set = set()


def clean_delay(chat_id: int) -> int:
    try:
        return int(db.get(chat_id, "autoclean", "30"))
    except (TypeError, ValueError):
        return 30


def lang_of(msg: Message) -> str:
    """השפה שנקבעה לצ'אט הזה, אחרת שפת הטלגרם של מי ששלח, אחרת אנגלית.

    בצ'אט פרטי ‎chat_id‎ שווה ל-‎user_id‎, ולכן אותה שורה במסד מחזיקה
    גם את שפת הקבוצה וגם את השפה שמשתמש בחר לעצמו."""
    u = msg.from_user
    return lang.resolve(msg.chat.id, u.language_code if u else None)


def T(msg: Message, key: str, **kw) -> str:
    return i18n.t(key, lang_of(msg), **kw)


async def reply(msg: Message, text: str, markup=None) -> Optional[Message]:
    """תשובה בקבוצה שמנקה אחריה — גם את הפקודה עצמה."""
    is_group = msg.chat.type in GROUP_TYPES
    delay = clean_delay(msg.chat.id) if is_group else 0
    if delay:
        _schedule_delete(msg.chat.id, msg.message_id, delay)
    return await send(msg.chat.id, text, is_group=is_group, markup=markup,
                      clean_after=delay or None)


def kb(screen: panel.Screen) -> Optional[InlineKeyboardMarkup]:
    if not screen.rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=c) for t, c in row]
        for row in screen.rows])


# ── סנכרון מנהלים ──────────────────────────────────────────────────────────
async def sync_admins(chat_id: int, force: bool = False) -> dict[int, str]:
    hit = _admin_cache.get(chat_id)
    if hit and not force and time.time() - hit[0] < ADMIN_TTL:
        return hit[1]
    out: dict[int, str] = {}
    try:
        for m in await bot.get_chat_administrators(chat_id):
            # הבוט עצמו ובוטים אחרים אינם מנהלים אנושיים. בלי הסינון
            # הזה "זוהו 2 מנהלים" בקבוצה שיש בה מנהל אחד — כי הבוט
            # ספר את עצמו, וזה נראה כאילו אותו אדם נקלט פעמיים.
            if m.user.is_bot:
                continue
            role = "owner" if m.status == ChatMemberStatus.CREATOR else "admin"
            out[m.user.id] = role
    except TelegramAPIError as e:
        log.warning("שליפת מנהלים נכשלה ב-%s: %s", chat_id, e)
        return hit[1] if hit else {}
    for uid, role in out.items():
        # לא דורסים תפקיד שהוענק אצלנו ידנית והוא גבוה מזה שטלגרם מדווחת
        cur = perms.role_of(chat_id, uid)
        if RANK.get(cur, 0) < RANK[role]:
            perms.set_role(chat_id, uid, role)
    _admin_cache[chat_id] = (time.time(), out)
    return out


# ההרשאות שהבוט צריך בקבוצה כדי לאכוף משהו. בלעדיהן הוא יזהה הפרה
# ולא יוכל לעשות איתה כלום — ועדיף לומר את זה מראש מאשר להיכשל בשקט.
NEEDED_RIGHTS = (
    ("can_delete_messages", "right.delete"),
    ("can_restrict_members", "right.restrict"),
)
_me_id: Optional[int] = None


async def bot_rights(chat_id: int) -> tuple[bool, list[str]]:
    """‎(האם מנהל, מפתחות ההרשאות החסרות)‎."""
    if _me_id is None:
        return False, [k for _, k in NEEDED_RIGHTS]
    try:
        m = await bot.get_chat_member(chat_id, _me_id)
    except TelegramAPIError as e:
        log.warning("בדיקת ההרשאות שלי ב-%s נכשלה: %s", chat_id, e)
        return False, [k for _, k in NEEDED_RIGHTS]
    if m.status != ChatMemberStatus.ADMINISTRATOR:
        return False, [k for _, k in NEEDED_RIGHTS]
    return True, [k for attr, k in NEEDED_RIGHTS if not getattr(m, attr, False)]


async def group_status(chat_id: int, lg: str) -> str:
    """מה חסר כדי שהבוט יעבוד כאן. תשובה אחת שאומרת את כל האמת."""
    admins = await sync_admins(chat_id, force=True)
    is_admin, missing = await bot_rights(chat_id)
    if not is_admin:
        return i18n.t("status.not_admin", lg, n=len(admins))
    if missing:
        return i18n.t("status.missing", lg,
                      list="\n".join("• " + i18n.t(k, lg) for k in missing))
    return i18n.t("status.ready", lg, n=len(admins))


def my_groups(user_id: int) -> list[tuple[int, str]]:
    return [(r["chat_id"], r["title"] or str(r["chat_id"])) for r in db.q(
        """SELECT c.chat_id, c.title FROM chats c
           JOIN members m ON m.chat_id = c.chat_id
           WHERE m.user_id=? AND m.role IN ('owner','super_admin','admin')
             AND c.active=1 ORDER BY c.title""", (user_id,))]


# ── רישום ──────────────────────────────────────────────────────────────────
def register_chat(chat) -> None:
    """הקבוצה נכנסת למסד. נקרא גם מהודעה וגם מרגע ההוספה לקבוצה."""
    db.run("""INSERT INTO chats (chat_id,title,username,type,added_at)
              VALUES (?,?,?,?,?)
              ON CONFLICT (chat_id) DO UPDATE SET
                title=excluded.title, username=excluded.username, active=1""",
           (chat.id, chat.title or "", chat.username, chat.type, time.time()))


def touch(msg: Message) -> None:
    now = time.time()
    u = msg.from_user
    if u is None:
        return
    db.run("""INSERT INTO users (user_id,username,first_name,language,is_bot,
                                 first_seen,last_seen)
              VALUES (?,?,?,?,?,?,?)
              ON CONFLICT (user_id) DO UPDATE SET
                username=excluded.username, first_name=excluded.first_name,
                last_seen=excluded.last_seen""",
           (u.id, u.username, u.first_name or "", u.language_code,
            1 if u.is_bot else 0, now, now))
    if msg.chat.type in GROUP_TYPES:
        register_chat(msg.chat)
        db.run("""INSERT INTO members (chat_id,user_id,msg_count,last_msg)
                  VALUES (?,?,1,?)
                  ON CONFLICT (chat_id,user_id) DO UPDATE SET
                    msg_count=members.msg_count+1, last_msg=excluded.last_msg""",
               (msg.chat.id, u.id, now))


def needs(permission: str):
    def deco(fn: Callable):
        @wraps(fn)
        async def inner(msg: Message, *a, **kw):
            if msg.from_user is None:
                return
            if msg.chat.type == ChatType.PRIVATE:
                await reply(msg, T(msg, "err.group_only"))
                return
            await sync_admins(msg.chat.id)
            d = perms.check(msg.chat.id, msg.from_user.id, permission,
                            _target_of(msg))
            if not d:
                await reply(msg, T(msg, "err.no_permission", reason=d.reason))
                audit.log(msg.chat.id, "permission.denied",
                          actor_id=msg.from_user.id, reason=d.reason,
                          after=permission, severity="low")
                return
            return await fn(msg, *a, **kw)
        return inner
    return deco


def _target_of(msg: Message) -> Optional[int]:
    """היעד: תשובה להודעה, ‎@שם‎ או מזהה מספרי בארגומנטים.

    Rose מאפשרת את שלושתם, ובצדק: להשיב להודעה של מי שכבר עזב אי אפשר,
    ומזהה מספרי הוא לעיתים הדרך היחידה לטפל בחשבון שנמחק."""
    if msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user.id
    # ‎text_mention‎ נושא את המזהה גם כשאין למשתמש username
    for e in (msg.entities or []):
        if e.type == "text_mention" and e.user:
            return e.user.id
    for tok in (msg.text or "").split()[1:]:
        if tok.isdigit() or (tok.startswith("-") and tok[1:].isdigit()):
            return int(tok)
        if tok.startswith("@") and len(tok) > 1:
            r = db.one("SELECT user_id FROM users WHERE lower(username)=?",
                       (tok[1:].lower(),))
            if r:
                return r["user_id"]
    return None


def _named(msg: Message, uid: int) -> str:
    r = db.one("SELECT first_name,username FROM users WHERE user_id=?", (uid,))
    if r and r["username"]:
        return "@" + r["username"]
    return tpl.esc((r["first_name"] if r else "") or uid)


def _describe(msg: Message) -> dict:
    """ההודעה כמילון, לשכבת הנעילות — שאינה מכירה טלגרם."""
    kind = None
    for attr, name in (("photo", "photo"), ("video", "video"),
                       ("animation", "gif"), ("sticker", "sticker"),
                       ("audio", "audio"), ("voice", "voice"),
                       ("video_note", "video_note"), ("document", "document"),
                       ("poll", "poll"), ("game", "game"),
                       ("contact", "contact"), ("location", "location")):
        if getattr(msg, attr, None):
            kind = name
            break
    st = msg.sticker
    return {
        "text": msg.text or "",
        "caption": msg.caption or "",
        "media_kind": kind,
        "is_forward": bool(msg.forward_origin),
        "via_bot": bool(msg.via_bot),
        "has_buttons": bool(msg.reply_markup),
        "is_premium_sticker": bool(st and getattr(st, "premium_animation", None)),
        "media_group_id": msg.media_group_id,
        "sender_chat": msg.sender_chat.id if msg.sender_chat else None,
    }


# ── אכיפה ──────────────────────────────────────────────────────────────────
MUTED = ChatPermissions(can_send_messages=False, can_send_audios=False,
                        can_send_documents=False, can_send_photos=False,
                        can_send_videos=False, can_send_video_notes=False,
                        can_send_voice_notes=False, can_send_polls=False,
                        can_send_other_messages=False)
UNMUTED = ChatPermissions(can_send_messages=True, can_send_audios=True,
                          can_send_documents=True, can_send_photos=True,
                          can_send_videos=True, can_send_video_notes=True,
                          can_send_voice_notes=True, can_send_polls=True,
                          can_send_other_messages=True,
                          can_add_web_page_previews=True)

# ביטול השבתה הוא **לא** ‎UNMUTED‎. ‎UNMUTED‎ נועד להחזרת משתמש יחיד, ואין
# בו ‎can_invite_users‎, ‎can_pin_messages‎ ו-‎can_change_info‎ — שלוש
# הרשאות שקיימות בקבוצה רגילה. שימוש בו כדי "לפתוח" קבוצה השאיר אותה
# משותקת למחצה: כולם יכלו לכתוב, אף אחד לא יכול היה להזמין או לנעוץ.
# זה מה שנראה כמו "השבית את הקבוצה בלי אפשרות להחזיר".
OPEN_CHAT = ChatPermissions(can_send_messages=True, can_send_audios=True,
                            can_send_documents=True, can_send_photos=True,
                            can_send_videos=True, can_send_video_notes=True,
                            can_send_voice_notes=True, can_send_polls=True,
                            can_send_other_messages=True,
                            can_add_web_page_previews=True,
                            can_invite_users=True, can_pin_messages=True,
                            can_change_info=False)


async def apply_action(chat_id: int, user_id: int, kind: str,
                       duration: Optional[int], reason: str,
                       by: Optional[int], source: str = "policy") -> bool:
    """מבצע מול טלגרם ורושם. מחזיר האם הצליח."""
    try:
        if kind == "mute":
            until = int(time.time() + duration) if duration else None
            await bot.restrict_chat_member(chat_id, user_id, MUTED,
                                           until_date=until)
        elif kind == "ban":
            until = int(time.time() + duration) if duration else None
            await bot.ban_chat_member(chat_id, user_id, until_date=until)
        elif kind == "kick":
            await bot.ban_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
        else:
            return False
    except TelegramAPIError as e:
        log.warning("%s נכשל על %s ב-%s: %s", kind, user_id, chat_id, e)
        audit.log(chat_id, f"{kind}.failed", target_id=user_id, reason=str(e),
                  actor_id=by, severity="medium", source=source)
        return False
    if kind != "kick":
        mod.record(chat_id, user_id, kind, by, reason, duration, source)
    else:
        audit.log(chat_id, "user.kick", actor_id=by, target_id=user_id,
                  reason=reason, source=source, severity="medium")
    return True


# הודעות שירות (הצטרפות, עזיבה) הן הודעות בלי טקסט, ולכן ‎~F.text‎
# תופס גם אותן — והמטפל הזה רשום ראשון. בלי ההחרגה המפורשת, ברכת
# הכניסה לעולם לא הייתה נורית: ההודעה נבלעה כאן.
@dp.message(F.chat.type.in_(GROUP_TYPES), ~F.text.startswith("/"),
            ~F.new_chat_members, ~F.left_chat_member)
async def on_group_message(msg: Message):
    """הנתיב החם. כל הודעה בכל קבוצה עוברת כאן, ולכן הסדר הוא לפי מחיר.

    קודם בדיקות בזיכרון (נעילות, הצפה), אחר כך שאילתות (חסימות,
    פילטרים). הודעה של מנהל יוצאת מוקדם ככל האפשר."""
    touch(msg)
    if msg.from_user is None:
        return
    await sync_admins(msg.chat.id)
    # מנהלים ומנחים פטורים מהכול — כלל שכל בוט ניהול מקיים
    if perms.rank_of(msg.chat.id, msg.from_user.id) >= RANK["moderator"]:
        return

    text = (msg.text or msg.caption or "")
    lg = lang_of(msg)

    # החרגת משתמש קודמת לכל בדיקה. מי שהוחרג במפורש לא נבדק, אחרת
    # ההחרגה אינה החרגה אלא הצעה.
    if allow.has_user(msg.chat.id, msg.from_user.id):
        return

    # 1. נעילות
    hit = locks.check(msg.chat.id, _describe(msg))
    # דומיין מותר מבטל נעילת קישורים — וזה מה שהופך נעילת קישורים
    # לשמישה. ההחרגה חלה רק כש**כל** הדומיינים בהודעה מותרים.
    if hit and hit.lock in ("url", "invite") and text:
        if allow.domains_ok(msg.chat.id, _bl_domains(text)):
            hit = None
    if hit:
        await _enforce(msg, hit.action, hit.duration,
                       i18n.t(hit.key, lg), "lock.triggered")
        return

    # 2. רשימת חסומים. ‎evaded‎ מסמן ניסיון לעקוף ולא הודעה מקרית —
    # ההבדל חשוב ביומן, כי הוא מבחין בין טעות לבין כוונה.
    m = blocks.check(msg.chat.id, text) if text else None
    if m:
        await _enforce(msg, m.action, None, m.pattern,
                       "blocklist.evaded" if m.evaded else "blocklist.hit",
                       severity="medium" if m.evaded else "low")
        return

    # 3. הצפה
    fl = _flood_check(msg, text)
    if fl:
        act = db.get(msg.chat.id, "flood_action", "mute")
        dur = _int(db.get(msg.chat.id, "flood_time", "3600"), 3600)
        await _enforce(msg, act, dur, fl.kind, "flood." + fl.kind,
                       severity="medium", notice=f"flood.{fl.kind}")
        return

    # 4. קיצור ‎#שם‎ להערה. לפני הפילטרים, כי הוא מפורש יותר.
    if text.startswith("#") and len(text) > 1:
        n = notes.get(msg.chat.id, text[1:].split()[0])
        if n is not None and n.visibility == "public":
            await send_content(msg.chat.id,
                               tpl.render_pick(n.content, _ctx(msg)),
                               n.media_id, n.media_kind, n.buttons)
            return

    # 5. פילטרים — אחרונים, כי הם היחידים שיכולים גם *להשיב*
    fh = filters.check(msg.chat.id, text) if text else None
    if fh:
        await _run_filter(msg, fh)


def _bl_domains(text: str) -> set[str]:
    import blocklist as _b
    return _b.domains(text)


def _int(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _flood_check(msg: Message, text: str):
    if db.get(msg.chat.id, "flood", "1") != "1":
        return None
    ents = (msg.entities or []) + (msg.caption_entities or [])
    mentions = sum(1 for e in ents if e.type in ("mention", "text_mention"))
    return flood.note(
        msg.chat.id, msg.from_user.id, text, mentions,
        rate=_int(db.get(msg.chat.id, "flood_rate", ""), AF_RATE),
        window=float(_int(db.get(msg.chat.id, "flood_window", ""), AF_WINDOW)),
        repeat=_int(db.get(msg.chat.id, "flood_repeat", ""), AF_REPEAT),
        mention_max=_int(db.get(msg.chat.id, "flood_mentions", ""), AF_MENTIONS))


async def _enforce(msg: Message, action: str, duration: Optional[int],
                   label: str, log_action: str, *, severity: str = "low",
                   notice: Optional[str] = None) -> None:
    """מחיקה, רישום, ענישה והודעה — במקום אחד.

    לפני זה כל מנגנון אכיפה חזר על ארבעת השלבים בעצמו, וזה בדיוק איך
    שמנגנון שלישי נולד בלי רישום ביומן."""
    if action == "off":
        return
    with contextlib.suppress(TelegramAPIError):
        await bot.delete_message(msg.chat.id, msg.message_id)
    audit.log(msg.chat.id, log_action, target_id=msg.from_user.id,
              actor_kind="bot", reason=label, after=action,
              source="policy", severity=severity)
    if action == "delete":
        return
    if action == "warn":
        out = mod.warn(msg.chat.id, msg.from_user.id, None, label, "policy")
        if out.threshold_hit:
            await apply_action(msg.chat.id, msg.from_user.id, out.kind,
                               out.duration, out.reason, None)
        if db.get(msg.chat.id, "silent", "1") != "1":
            await send(msg.chat.id,
                       T(msg, notice or "lock.violation", name=_name(msg),
                         label=label, n=out.warns),
                       clean_after=clean_delay(msg.chat.id) or None)
        return
    if action in ("mute", "ban", "kick", "tmute", "tban"):
        kind = {"tmute": "mute", "tban": "ban"}.get(action, action)
        await apply_action(msg.chat.id, msg.from_user.id, kind, duration,
                           label, None)
        if notice and db.get(msg.chat.id, "silent", "1") != "1":
            await send(msg.chat.id, T(msg, notice, name=_name(msg)),
                       clean_after=clean_delay(msg.chat.id) or None)


async def _run_filter(msg: Message, fh) -> None:
    if fh.action in ("delete", "delete_reply"):
        with contextlib.suppress(TelegramAPIError):
            await bot.delete_message(msg.chat.id, msg.message_id)
    if fh.action in ("reply", "delete_reply") and fh.content:
        await send_content(msg.chat.id,
                           tpl.render_pick(fh.content, _ctx(msg)),
                           None, None, "")
        return
    if fh.action in ("warn", "mute", "kick", "ban"):
        await _enforce(msg, fh.action, None, fh.trigger, "filter.triggered")


def _name(msg: Message) -> str:
    u = msg.from_user
    return f"@{u.username}" if u and u.username else (u.first_name if u else "משתמש")


# ── הצטרפות ושינויי מנהלים ─────────────────────────────────────────────────
@dp.my_chat_member()
async def on_my_status(ev: ChatMemberUpdated):
    """הרגע שבו הבוט נוסף לקבוצה או קודם למנהל.

    בלי זה הקבוצה נרשמת רק כשמישהו שולח בה הודעה — וכל עוד הבוט אינו
    מנהל, טלגרם לא מוסרת לו הודעות רגילות כלל. כך נוצר מצב שבו הבוט
    בקבוצה, המשתמש מנהל בה, והפאנל הפרטי מציג "לא ראיתי אותך מנהל
    באף קבוצה". זה בדיוק מה שקרה."""
    if ev.chat.type not in GROUP_TYPES:
        return
    new = ev.new_chat_member.status
    if new in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
        db.run("UPDATE chats SET active=0 WHERE chat_id=?", (ev.chat.id,))
        log.info("הוסרתי מ-%s", ev.chat.id)
        return
    register_chat(ev.chat)
    admins = await sync_admins(ev.chat.id, force=True)
    audit.log(ev.chat.id, "bot.status", actor_kind="bot", source="system",
              before=ev.old_chat_member.status, after=new, severity="info")
    log.info("מצבי ב-%s: %s · %d מנהלים", ev.chat.id, new, len(admins))
    if new == ChatMemberStatus.ADMINISTRATOR:
        lg = lang.for_chat(ev.chat.id)
        await send(ev.chat.id, await group_status(ev.chat.id, lg),
                   clean_after=clean_delay(ev.chat.id) or None)


ADMIN_STATUSES = (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
JOINED = (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR,
          ChatMemberStatus.CREATOR, ChatMemberStatus.RESTRICTED)


async def _greet(chat_id: int, user, key: str, joined: bool) -> None:
    """ברכת כניסה או פרידה. ריק = כבוי, וזו ברירת המחדל.

    בוט שמכריז על כל נכנס בקבוצה של אלף איש הוא רעש, ולכן הוא לא
    מדבר עד שמנהל ביקש."""
    raw = db.get(chat_id, key, "") or ""
    if not raw.strip():
        return
    lg = lang.for_chat(chat_id)
    row = db.one("SELECT title FROM chats WHERE chat_id=?", (chat_id,))
    n = db.one("SELECT COUNT(*) c FROM members WHERE chat_id=?", (chat_id,))
    ctx = tpl.context(user_id=user.id, first=user.first_name or "",
                      last=user.last_name or "", username=user.username or "",
                      chat_title=(row["title"] if row else "") or "",
                      chat_id=chat_id, count=(n["c"] if n else 0),
                      language=lg, rules=db.get(chat_id, RULES_KEY, "") or "")
    secs = _int(db.get(chat_id, "greet_clean", "0"), 0)
    await send_content(chat_id, tpl.render_pick(raw, ctx), None, None,
                       db.get(chat_id, key + "_buttons", "") or "",
                       clean_after=secs or None)


@dp.message(F.new_chat_members)
async def on_join(msg: Message):
    """כניסה לקבוצה. גם מונה פשיטה — הצטרפות המונית מתחילה כאן."""
    register_chat(msg.chat)
    for u in msg.new_chat_members or []:
        if u.is_bot:
            continue
        db.run("""INSERT INTO members (chat_id,user_id,joined_at,last_msg)
                  VALUES (?,?,?,0)
                  ON CONFLICT (chat_id,user_id) DO UPDATE SET
                    joined_at=COALESCE(members.joined_at,excluded.joined_at)""",
               (msg.chat.id, u.id, time.time()))
        raid = flood.join(msg.chat.id)
        if raid and db.get(msg.chat.id, "antiraid", "1") == "1":
            await _on_raid(msg.chat.id, raid)
        if db.get(msg.chat.id, "captcha", "0") == "1":
            # האימות קודם לברכה: אין טעם לברך מי שעוד לא הוכח כאדם
            if await _start_captcha(msg.chat.id, u):
                continue
        await _greet(msg.chat.id, u, WELCOME_KEY, True)
    _clean_service(msg)


@dp.message(F.left_chat_member)
async def on_leave(msg: Message):
    u = msg.left_chat_member
    if u and not u.is_bot:
        await _greet(msg.chat.id, u, GOODBYE_KEY, False)
    _clean_service(msg)


def _clean_service(msg: Message) -> None:
    """הודעות "הצטרף" ו"עזב". כבוי כברירת מחדל — יש קבוצות שרוצות לראות
    מי נכנס, ומחיקה שקטה של זה הייתה מפתיעה."""
    if db.get(msg.chat.id, "cleanservice", "0") == "1":
        _schedule_delete(msg.chat.id, msg.message_id, 3)


async def _start_captcha(chat_id: int, user) -> bool:
    """משתיק את הנכנס ושולח אתגר. מחזיר האם האתגר נשלח.

    ההשתקה **קודמת** להודעה. אם השליחה תיכשל ברשת, עדיף משתמש מושתק
    שמנהל ישחרר מאשר ספאמר שנכנס בלי שנבדק."""
    try:
        await bot.restrict_chat_member(chat_id, user.id, MUTED)
    except TelegramAPIError as e:
        log.warning("השתקת נכנס ב-%s נכשלה: %s", chat_id, e)
        return False
    ch = cap.build(chat_id, user.id,
                   db.get(chat_id, "captcha_kind", "button"),
                   timeout=_int(db.get(chat_id, "captcha_time", ""), 120),
                   tries=_int(db.get(chat_id, "captcha_tries", ""), 3))
    lg = lang.for_chat(chat_id)
    sc = panel.captcha_screen(ch, lg)
    text = sc.text.replace("{mention}",
                           tpl.mention(user.id, user.first_name or "?"))
    m = await send(chat_id, text, markup=kb(sc))
    ch.message_id = m.message_id if m else None
    pending.add(ch)
    audit.log(chat_id, "captcha.sent", target_id=user.id, actor_kind="bot",
              source="policy", after=ch.kind, severity="info")
    return True


async def _captcha_done(ch, passed: bool) -> None:
    """סוגר אתגר: משחרר או מעניש, ומנקה את ההודעה."""
    lg = lang.for_chat(ch.chat_id)
    if ch.message_id:
        with contextlib.suppress(TelegramAPIError):
            await bot.delete_message(ch.chat_id, ch.message_id)
    if passed:
        with contextlib.suppress(TelegramAPIError):
            await bot.restrict_chat_member(ch.chat_id, ch.user_id, UNMUTED)
        audit.log(ch.chat_id, "captcha.passed", target_id=ch.user_id,
                  actor_kind="bot", source="policy", severity="info")
        row = db.one("SELECT first_name,username FROM users WHERE user_id=?",
                     (ch.user_id,))
        u = type("U", (), {"id": ch.user_id,
                           "first_name": (row["first_name"] if row else ""),
                           "last_name": "",
                           "username": (row["username"] if row else "")})
        await _greet(ch.chat_id, u, WELCOME_KEY, True)
        return
    action = db.get(ch.chat_id, "captcha_fail", "kick")
    audit.log(ch.chat_id, "captcha.failed", target_id=ch.user_id,
              actor_kind="bot", source="policy", after=action, severity="medium")
    if action in ("kick", "ban", "mute"):
        await apply_action(ch.chat_id, ch.user_id, action, None,
                           "captcha", None, "policy")


@dp.callback_query(F.data.startswith("c:"))
async def on_captcha(q: CallbackQuery):
    """‎c:<user_id>:<תשובה>‎. רק בעל האתגר יכול לענות עליו."""
    parts = (q.data or "").split(":", 2)
    if len(parts) < 3:
        return
    try:
        owner = int(parts[1])
    except ValueError:
        return
    lg = lang.for_chat(q.message.chat.id)
    if q.from_user.id != owner:
        await q.answer(i18n.t("captcha.not_yours", lg), show_alert=True)
        return
    ch = pending.get(q.message.chat.id, owner)
    res = pending.answer(q.message.chat.id, owner, parts[2])
    if res == "gone":
        await q.answer()
        return
    if res == "ok":
        await q.answer(i18n.t("captcha.ok", lg))
        await _captcha_done(ch, True)
        return
    if res == "retry":
        await q.answer(i18n.t("captcha.retry", lg, n=ch.tries), show_alert=True)
        return
    await q.answer(i18n.t("captcha.fail", lg), show_alert=True)
    await _captcha_done(ch, False)


async def _on_raid(chat_id: int, raid) -> None:
    """הצטרפות המונית. משביתים ומודיעים — פעם אחת, לא בכל הצטרפות."""
    if db.get(chat_id, "lockdown", "0") == "1":
        return
    lg = lang.for_chat(chat_id)
    okay = await set_lockdown(chat_id, True, None)
    audit.log(chat_id, "raid.detected", actor_kind="bot", source="policy",
              after=f"{raid.count}/{raid.limit}", severity="critical")
    if okay:
        await send(chat_id, i18n.t("raid.detected", lg, n=raid.count))
    for uid in list((await sync_admins(chat_id)))[:10]:
        await send(uid, i18n.t("raid.alert", lg, n=raid.count,
                               chat=_title(chat_id)), is_group=False)


@dp.chat_member()
async def on_member_change(ev: ChatMemberUpdated):
    """קידום או הורדה של משתמש. מרענן את המטמון מיד במקום לחכות לפקיעה.

    רק שינוי שנוגע לניהול מפעיל שליפה מחדש. בקבוצה פעילה כל הצטרפות
    ועזיבה מגיעות לכאן, ו-getChatAdministrators על כל אחת מהן היא בזבוז
    מכסה על מידע שלא השתנה."""
    if ev.chat.type not in GROUP_TYPES:
        return
    touched = {ev.old_chat_member.status, ev.new_chat_member.status}
    if not touched & set(ADMIN_STATUSES):
        return
    _admin_cache.pop(ev.chat.id, None)
    await sync_admins(ev.chat.id, force=True)


# ── פקודות בקבוצה ──────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(msg: Message):
    touch(msg)
    if msg.chat.type == ChatType.PRIVATE:
        # מי שטרם בחר שפה רואה קודם את הבורר. הבוט לא מיועד לישראל
        # בלבד, ולהניח שהפונה קורא עברית זה לאבד אותו במסך הראשון.
        if lang.chosen(msg.chat.id) is None:
            sc = panel.welcome_screen()
        else:
            sc = panel.home(my_groups(msg.from_user.id), lang_of(msg))
        await send(msg.chat.id, sc.text, is_group=False, markup=kb(sc))
    else:
        await reply(msg, await group_status(msg.chat.id, lang_of(msg)))


@dp.message(Command("help"))
async def cmd_help(msg: Message):
    """כל הפקודות, בשפה של הצ'אט. בפרטי לא נמחק — שם זה אמור להישאר."""
    touch(msg)
    pages = panel.help_pages(lang_of(msg))
    private = msg.chat.type == ChatType.PRIVATE
    if not private:
        # בקבוצה עמוד אחד בלבד; השאר בפרטי. שלוש הודעות עזרה בקבוצה
        # הן בדיוק הרעש שהבוט הזה נועד למנוע.
        await reply(msg, pages[0])
        return
    for page in pages:
        await send(msg.chat.id, page, is_group=False)


# ── תוכן: הערות, פילטרים, חוקים, ברכות ─────────────────────────────────────
def _ctx(msg: Message, **extra) -> dict:
    u = msg.from_user
    return tpl.context(
        user_id=u.id if u else 0, first=u.first_name if u else "",
        last=(u.last_name or "") if u else "", username=(u.username or "") if u else "",
        chat_title=msg.chat.title or "", chat_id=msg.chat.id,
        language=lang_of(msg), rules=db.get(msg.chat.id, RULES_KEY, "") or "",
        **extra)


def _content_of(msg: Message, args: str) -> tuple[str, Optional[str], Optional[str]]:
    """‎(טקסט, media_id, media_kind)‎ — מהארגומנטים או מההודעה שהשבת עליה."""
    src = msg.reply_to_message
    if src is None:
        return args, None, None
    text = args or (src.text or src.caption or "")
    for attr, kind in (("photo", "photo"), ("video", "video"),
                       ("animation", "animation"), ("sticker", "sticker"),
                       ("document", "document"), ("audio", "audio"),
                       ("voice", "voice")):
        got = getattr(src, attr, None)
        if got:
            fid = got[-1].file_id if attr == "photo" else got.file_id
            return text, fid, kind
    return text, None, None


async def send_content(chat_id: int, text: str, media_id: Optional[str],
                       media_kind: Optional[str], buttons: str,
                       *, clean_after: Optional[int] = None):
    """שולח הערה/ברכה/תגובת פילטר — טקסט, מדיה וכפתורים כאחד."""
    rows = parse_buttons(buttons)
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, url=u) for t, u in row] for row in rows
    ]) if rows else None
    await guard.acquire(chat_id, True)
    try:
        if media_id and media_kind:
            fn = {"photo": bot.send_photo, "video": bot.send_video,
                  "animation": bot.send_animation, "sticker": bot.send_sticker,
                  "document": bot.send_document, "audio": bot.send_audio,
                  "voice": bot.send_voice}[media_kind]
            kw = {"reply_markup": markup}
            if media_kind != "sticker":
                kw["caption"] = text[:1024] or None
            m = await fn(chat_id, media_id, **kw)
        else:
            m = await bot.send_message(chat_id, text, reply_markup=markup)
    except TelegramAPIError as e:
        log.warning("שליחת תוכן ל-%s נכשלה: %s", chat_id, e)
        return None
    if clean_after:
        _schedule_delete(chat_id, m.message_id, clean_after)
    return m


@dp.message(Command("save"))
@needs("notes.write")
async def cmd_save(msg: Message):
    touch(msg)
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await reply(msg, T(msg, "note.usage"))
        return
    name = parts[1]
    text, mid, kind = _content_of(msg, parts[2] if len(parts) > 2 else "")
    if not notes.save(msg.chat.id, name, text, media_id=mid, media_kind=kind,
                      by=msg.from_user.id):
        await reply(msg, T(msg, "note.usage"))
        return
    audit.log(msg.chat.id, "note.save", actor_id=msg.from_user.id,
              after=name, severity="info")
    await reply(msg, T(msg, "note.saved", name=name))


@dp.message(Command("get"))
@needs("notes.read")
async def cmd_get(msg: Message):
    touch(msg)
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await reply(msg, T(msg, "note.usage"))
        return
    await _send_note(msg, parts[1])


async def _send_note(msg: Message, name: str) -> bool:
    n = notes.get(msg.chat.id, name)
    if n is None:
        await reply(msg, T(msg, "note.missing", name=name))
        return False
    if n.visibility == "admin" and not perms.check(
            msg.chat.id, msg.from_user.id, "settings.read"):
        return False
    await send_content(msg.chat.id, tpl.render_pick(n.content, _ctx(msg)),
                       n.media_id, n.media_kind, n.buttons)
    return True


@dp.message(Command("notes"))
@needs("notes.read")
async def cmd_notes(msg: Message):
    touch(msg)
    admin = bool(perms.check(msg.chat.id, msg.from_user.id, "settings.read"))
    names = notes.names(msg.chat.id, include_admin=admin)
    if not names:
        await reply(msg, T(msg, "note.none"))
        return
    await reply(msg, T(msg, "note.list",
                       list="\n".join(f"• <code>#{n}</code>" for n in names)))


@dp.message(Command("clear"))
@needs("notes.write")
async def cmd_clear_note(msg: Message):
    touch(msg)
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await reply(msg, T(msg, "note.usage"))
        return
    n = notes.delete(msg.chat.id, parts[1])
    await reply(msg, T(msg, "note.deleted") if n
                else T(msg, "note.missing", name=parts[1]))


@dp.message(Command("filter"))
@needs("filters.write")
async def cmd_filter(msg: Message):
    touch(msg)
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await reply(msg, T(msg, "filter.usage"))
        return
    trigger = parts[1]
    content, _, _ = _content_of(msg, parts[2] if len(parts) > 2 else "")
    if not content.strip() or not filters.add(msg.chat.id, trigger, content):
        await reply(msg, T(msg, "filter.usage"))
        return
    audit.log(msg.chat.id, "filter.add", actor_id=msg.from_user.id,
              after=trigger, severity="info")
    await reply(msg, T(msg, "filter.saved", trigger=trigger))


@dp.message(Command("stop"))
@needs("filters.write")
async def cmd_stop(msg: Message):
    touch(msg)
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await reply(msg, T(msg, "filter.usage"))
        return
    n = filters.remove(msg.chat.id, parts[1])
    await reply(msg, T(msg, "filter.removed") if n else T(msg, "filter.none"))


@dp.message(Command("filters"))
@needs("settings.read")
async def cmd_filters(msg: Message):
    touch(msg)
    trg = filters.triggers(msg.chat.id)
    await reply(msg, T(msg, "filter.list",
                       list="\n".join(f"• <code>{t}</code>" for t in trg))
                if trg else T(msg, "filter.none"))


@dp.message(Command("addblock"))
@needs("blocklist.write")
async def cmd_addblock(msg: Message):
    touch(msg)
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await reply(msg, T(msg, "block.usage"))
        return
    # "/addblock regex: ^..." — קידומת בוחרת סוג התאמה
    raw, kind = parts[1], "word"
    for pre in ("regex:", "domain:", "substring:"):
        if raw.lower().startswith(pre):
            kind, raw = pre[:-1], raw[len(pre):].strip()
            break
    if not blocks.add(msg.chat.id, raw, kind):
        await reply(msg, T(msg, "block.bad_regex" if kind == "regex"
                           else "block.usage"))
        return
    audit.log(msg.chat.id, "blocklist.add", actor_id=msg.from_user.id,
              after=f"{kind}:{raw}", severity="medium")
    await reply(msg, T(msg, "block.added", pattern=raw))


@dp.message(Command("rmblock"))
@needs("blocklist.write")
async def cmd_rmblock(msg: Message):
    touch(msg)
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await reply(msg, T(msg, "block.usage"))
        return
    n = blocks.remove(msg.chat.id, parts[1])
    await reply(msg, T(msg, "block.removed") if n else T(msg, "block.none"))


@dp.message(Command("blocklist"))
@needs("settings.read")
async def cmd_blocklist(msg: Message):
    touch(msg)
    rows = blocks.all(msg.chat.id)
    if not rows:
        await reply(msg, T(msg, "block.none"))
        return
    await reply(msg, T(msg, "block.list", list="\n".join(
        f"• <code>{r['pattern']}</code> ({r['kind']})" for r in rows)))


@dp.message(Command("rules"))
async def cmd_rules(msg: Message):
    touch(msg)
    txt = db.get(msg.chat.id, RULES_KEY, "") or ""
    await reply(msg, tpl.render(txt, _ctx(msg)) if txt.strip()
                else T(msg, "rules.none"))


@dp.message(Command("setrules"))
@needs("rules.write")
async def cmd_setrules(msg: Message):
    touch(msg)
    parts = (msg.text or "").split(maxsplit=1)
    body, _, _ = _content_of(msg, parts[1] if len(parts) > 1 else "")
    if not body.strip():
        await reply(msg, T(msg, "rules.usage"))
        return
    db.set(msg.chat.id, RULES_KEY, body, msg.from_user.id)
    audit.log(msg.chat.id, "rules.write", actor_id=msg.from_user.id,
              severity="medium")
    await reply(msg, T(msg, "rules.set"))


async def _greet_cmd(msg: Message, key: str, cmd: str):
    parts = (msg.text or "").split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ""
    if arg.lower() in ("off", "0", "no"):
        db.set(msg.chat.id, key, "", msg.from_user.id)
        await reply(msg, T(msg, "greet.off"))
        return
    if not arg and not msg.reply_to_message:
        cur = db.get(msg.chat.id, key, "") or ""
        await reply(msg, (tpl.render(cur, _ctx(msg)) if cur else "")
                    + ("\n\n" if cur else "")
                    + T(msg, "greet.usage", cmd=cmd,
                        vars=", ".join("{" + v + "}" for v in tpl.VARIABLES)))
        return
    body, _, _ = _content_of(msg, arg)
    db.set(msg.chat.id, key, body, msg.from_user.id)
    await reply(msg, T(msg, "greet.set"))


@dp.message(Command("welcome"))
@needs("welcome.write")
async def cmd_welcome(msg: Message):
    touch(msg); await _greet_cmd(msg, WELCOME_KEY, "/welcome")


@dp.message(Command("goodbye"))
@needs("welcome.write")
async def cmd_goodbye(msg: Message):
    touch(msg); await _greet_cmd(msg, GOODBYE_KEY, "/goodbye")


@dp.message(Command("report"))
async def cmd_report(msg: Message):
    """דיווח מחבר הקבוצה. לא דורש הרשאה — זו כל הנקודה."""
    touch(msg)
    if msg.chat.type not in GROUP_TYPES:
        await reply(msg, T(msg, "err.group_only"))
        return
    if db.get(msg.chat.id, "reports", "1") != "1":
        await reply(msg, T(msg, "report.off"))
        return
    src = msg.reply_to_message
    if src is None or src.from_user is None:
        await reply(msg, T(msg, "report.need_reply"))
        return
    reason = " ".join((msg.text or "").split()[1:])
    audit.log(msg.chat.id, "user.report", actor_id=msg.from_user.id,
              target_id=src.from_user.id, reason=reason, severity="medium")
    admins = await sync_admins(msg.chat.id)
    alert = T(msg, "report.alert",
              reporter=tpl.mention(msg.from_user.id, _name(msg)),
              target=tpl.mention(src.from_user.id,
                                 src.from_user.first_name or "?"),
              reason=tpl.esc(reason))
    for uid in list(admins)[:10]:
        await send(uid, alert, is_group=False)
    await reply(msg, T(msg, "report.sent"))


@dp.message(Command("info"))
@needs("settings.read")
async def cmd_info(msg: Message):
    touch(msg)
    t = _target_of(msg) or msg.from_user.id
    r = db.one("""SELECT m.role, m.msg_count, m.joined_at, u.first_name,
                         u.username
                  FROM members m LEFT JOIN users u ON u.user_id=m.user_id
                  WHERE m.chat_id=? AND m.user_id=?""", (msg.chat.id, t))
    joined = (time.strftime("%d/%m/%Y", time.localtime(r["joined_at"]))
              if r and r["joined_at"] else "—")
    await reply(msg, T(msg, "info.card",
                       name=tpl.esc((r["first_name"] if r else "") or t),
                       id=t, role=(r["role"] if r else "member"),
                       msgs=(r["msg_count"] if r else 0),
                       warns=mod.warn_count(msg.chat.id, t), joined=joined))


# ── אותות: מה שכל מזהה אומר על הודעה, בלי להחליט בעצמו ────────────────
def collect_signals(msg: Message, text: str) -> list[policy.Signal]:
    """כל המזהים מדווחים. אף אחד מהם לא מחליט — זה תפקיד ה-Policy.

    המשקלים כאן הם ברירת מחדל שמרנית: נעילה שהמנהל הגדיר במפורש
    שוקלת יותר מחשד התנהגותי, כי היא **כלל** ולא ניחוש."""
    out: list[policy.Signal] = []
    hit = locks.check(msg.chat.id, _describe(msg))
    if hit:
        out.append(policy.Signal("lock", hit.lock, 0.8))
    m = blocks.check(msg.chat.id, text) if text else None
    if m:
        # ניסיון עקיפה שוקל יותר מהפרה ישירה: מי שפיזר אותיות ידע
        out.append(policy.Signal("blocklist", m.kind,
                                 0.95 if m.evaded else 0.75,
                                 "עקיפה" if m.evaded else m.pattern[:24]))
    fh = filters.check(msg.chat.id, text) if text else None
    if fh and fh.action not in ("reply", "delete_reply"):
        out.append(policy.Signal("filter", fh.trigger[:24], 0.5))
    u = msg.from_user
    if u:
        w = mod.warn_count(msg.chat.id, u.id)
        if w:
            out.append(policy.Signal("reputation", "warnings",
                                     min(0.15 * w, 0.6), str(w)))
        r = db.one("SELECT joined_at FROM members WHERE chat_id=? AND user_id=?",
                   (msg.chat.id, u.id))
        if r and r["joined_at"] and time.time() - r["joined_at"] < 300:
            out.append(policy.Signal("account", "just_joined", 0.35))
    return out


@dp.message(Command("policy"))
@needs("settings.write")
async def cmd_policy(msg: Message):
    touch(msg)
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await reply(msg, T(msg, "policy.current",
                           rules=policy.format_rules(
                               policy.rules_for(db, msg.chat.id))))
        return
    arg = parts[1].strip()
    if arg.lower() in ("reset", "default"):
        db.unset(msg.chat.id, "policy_rules")
        await reply(msg, T(msg, "policy.reset"))
        return
    rules = policy.parse_rules(arg)
    if not rules:
        await reply(msg, T(msg, "policy.bad"))
        return
    db.set(msg.chat.id, "policy_rules", policy.format_rules(rules),
           msg.from_user.id)
    audit.log(msg.chat.id, "policy.write", actor_id=msg.from_user.id,
              after=policy.format_rules(rules), severity="high")
    await reply(msg, T(msg, "policy.set", rules=policy.format_rules(rules)))


@dp.message(Command("simulate"))
@needs("settings.read")
async def cmd_simulate(msg: Message):
    """מה היה קורה להודעה הזאת. בלי לעשות לה כלום.

    מדיניות אבטחה שמופעלת בלי לראות מה היא עושה היא הדרך המהירה
    ביותר לחסום חצי קבוצה בטעות."""
    touch(msg)
    src = msg.reply_to_message
    if src is None:
        await reply(msg, T(msg, "sim.usage"))
        return
    text = src.text or src.caption or ""
    sigs = collect_signals(src, text)
    res = policy.simulate(sigs, policy.rules_for(db, msg.chat.id))
    if not sigs:
        await reply(msg, T(msg, "sim.none"))
        return
    lines = "\n".join(T(msg, "sim.signal", source=s["source"], kind=s["kind"],
                        weight=int(s["weight"] * 100),
                        detail=f" · {tpl.esc(s['detail'])}" if s["detail"] else "")
                      for s in res["signals"])
    dur = f" ({res['duration']}s)" if res["duration"] else ""
    await reply(msg, T(msg, "sim.result", risk=int(res["risk"] * 100),
                       action=res["action"], dur=dur, signals=lines))


@dp.message(Command("aikeys"))
@needs("settings.read")
async def cmd_aikeys(msg: Message):
    """מצב הבריכה. בלי לחשוף מפתח — רק ארבעה תווים מכל קצה."""
    touch(msg)
    pools = ai.stats()
    if not pools:
        await reply(msg, T(msg, "ai.none"))
        return
    lg = lang_of(msg)
    parts = []
    for p in pools:
        lines = [T(msg, "ai.pool", provider=p["provider"], keys=p["keys"],
                   available=p["available"], cooling=p["cooling"],
                   dead=p["dead"], used=p["used_today"])]
        for k in p["detail"]:
            state = (i18n.t("ai.state_dead", lg) if k["dead"]
                     else i18n.t("ai.state_cool", lg, n=k["cooling_for"])
                     if k["cooling_for"] else i18n.t("ai.state_ok", lg))
            lines.append(T(msg, "ai.key", key=k["key"], used=k["used"],
                           state=state))
        parts.append("\n".join(lines))
    await reply(msg, "\n\n".join(parts)
                + T(msg, "ai.budget", n=ai.budget()))


@dp.message(Command("emergency"))
@needs("emergency.toggle")
async def cmd_emergency(msg: Message):
    touch(msg)
    arg = ((msg.text or "").split() + [""])[1].lower()
    want = not emerg.is_on(db, msg.chat.id) if arg not in ("on", "off") \
        else (arg == "on")
    if want:
        if not emerg.enable(db, msg.chat.id, msg.from_user.id):
            await reply(msg, T(msg, "emergency.already"))
            return
        audit.log(msg.chat.id, "emergency.on", actor_id=msg.from_user.id,
                  severity="critical")
        await reply(msg, T(msg, "emergency.on"))
        return
    if not emerg.disable(db, msg.chat.id, msg.from_user.id):
        await reply(msg, T(msg, "emergency.not_on"))
        return
    audit.log(msg.chat.id, "emergency.off", actor_id=msg.from_user.id,
              severity="high")
    await reply(msg, T(msg, "emergency.off"))


@dp.message(Command("captcha"))
@needs("settings.write")
async def cmd_captcha(msg: Message):
    """‎/captcha on|off|button|math|emoji‎."""
    touch(msg)
    arg = ((msg.text or "").split() + [""])[1].lower()
    if arg in ("on", "off"):
        db.set(msg.chat.id, "captcha", "1" if arg == "on" else "0",
               msg.from_user.id)
    elif arg in cap.KINDS:
        db.set(msg.chat.id, "captcha_kind", arg, msg.from_user.id)
        db.set(msg.chat.id, "captcha", "1", msg.from_user.id)
    elif arg:
        await reply(msg, T(msg, "captcha.settings",
                           kind=db.get(msg.chat.id, "captcha_kind", "button"),
                           secs=db.get(msg.chat.id, "captcha_time", "120"),
                           tries=db.get(msg.chat.id, "captcha_tries", "3"),
                           action=db.get(msg.chat.id, "captcha_fail", "kick")))
        return
    await reply(msg, T(msg, "captcha.settings",
                       kind=db.get(msg.chat.id, "captcha_kind", "button"),
                       secs=db.get(msg.chat.id, "captcha_time", "120"),
                       tries=db.get(msg.chat.id, "captcha_tries", "3"),
                       action=db.get(msg.chat.id, "captcha_fail", "kick")))


@dp.message(Command("security"))
@needs("settings.read")
async def cmd_security(msg: Message):
    touch(msg)
    sc = panel.security_screen(msg.chat.id, emerg.status(db, msg.chat.id),
                               _sec_numbers(msg.chat.id), lang_of(msg))
    await reply(msg, sc.text)


@dp.message(Command("delall"))
@needs("chat.purge")
async def cmd_delall(msg: Message):
    """מוחק את ההודעות האחרונות של מי שהשבת עליו.

    טלגרם אינה נותנת "מחק הכול ממשתמש". מה שאפשר הוא לעבור על טווח
    מזהים אחורה ולמחוק את שלו — ולכן הטווח חסום, אחרת זו לולאה של
    אלפי קריאות API על קבוצה אחת."""
    touch(msg)
    t = _target_of(msg)
    if t is None:
        await reply(msg, T(msg, "err.need_reply"))
        return
    start = msg.reply_to_message.message_id
    n = 0
    for mid in range(start, max(start - PURGE_MAX, 0), -1):
        try:
            await bot.delete_message(msg.chat.id, mid)
            n += 1
        except TelegramAPIError:
            continue
    audit.log(msg.chat.id, "chat.purge_user", actor_id=msg.from_user.id,
              target_id=t, after=n, severity="high")
    await send(msg.chat.id, T(msg, "purge.by_user", n=n,
                              name=tpl.esc(_name(msg))), clean_after=10)



# ── וריאנטים שקטים ומוחקים ────────────────────────────────────────────────
# Rose נותנת לכל פעולה שלוש צורות, וזה לא קישוט: בקבוצה גדולה הודעת
# "X נחסם" היא רעש, ולפעמים ההודעה שבגללה חסמו צריכה להיעלם איתו.
async def _mod_variant(msg: Message, kind: str, *, silent: bool = False,
                       purge: bool = False):
    if purge and msg.reply_to_message:
        with contextlib.suppress(TelegramAPIError):
            await bot.delete_message(msg.chat.id,
                                     msg.reply_to_message.message_id)
    target = _target_of(msg)
    if target is None:
        await reply(msg, T(msg, "target.usage"))
        return
    args = [a for a in (msg.text or "").split()[1:]
            if not a.startswith("@") and not a.lstrip("-").isdigit()]
    dur = _parse_duration(args[0]) if args else None
    reason = " ".join(args[1:] if dur else args) or ""
    okay = await apply_action(msg.chat.id, target, kind, dur, reason,
                              msg.from_user.id, "command")
    _schedule_delete(msg.chat.id, msg.message_id, 1)
    if silent:
        return
    if not okay:
        await reply(msg, T(msg, "err.failed"))
        return
    lbl = T(msg, {"mute": "act.muted", "ban": "act.banned",
                  "kick": "act.kicked"}[kind])
    await reply(msg, f"{_named(msg, target)} — {lbl}."
                + (T(msg, "act.reason", reason=tpl.esc(reason)) if reason else ""))


def _variant(name: str, kind: str, perm: str, **kw):
    @dp.message(Command(name))
    @needs(perm)
    async def handler(msg: Message, _k=kind, _kw=kw):
        touch(msg)
        await _mod_variant(msg, _k, **_kw)
    handler.__name__ = f"cmd_{name}"
    return handler


# שש וריאציות שנבדלות בשני דגלים. כתיבתן ידנית הייתה 120 שורות שבהן
# ההבדל היחיד הוא מילה אחת — וזה בדיוק המקום שבו אחת מהן נשכחת.
MOD_VARIANTS = (
    ("sban", "ban", "user.ban", {"silent": True}),
    ("dban", "ban", "user.ban", {"purge": True}),
    ("smute", "mute", "user.mute", {"silent": True}),
    ("dmute", "mute", "user.mute", {"purge": True}),
    ("skick", "kick", "user.kick", {"silent": True}),
    ("dkick", "kick", "user.kick", {"purge": True}),
)
for _n, _k, _p, _o in MOD_VARIANTS:
    _variant(_n, _k, _p, **_o)


# ── אזהרות ────────────────────────────────────────────────────────────────
@dp.message(Command("resetwarns"))
@needs("user.unwarn")
async def cmd_resetwarns(msg: Message):
    touch(msg)
    t = _target_of(msg)
    if t is None:
        await reply(msg, T(msg, "target.usage"))
        return
    n = mod.reset_warns(msg.chat.id, t, msg.from_user.id)
    await reply(msg, T(msg, "warns.reset", name=_named(msg, t), n=n))


@dp.message(Command("warnings"))
@needs("user.warn")
async def cmd_warnings(msg: Message):
    touch(msg)
    t = _target_of(msg) or msg.from_user.id
    rows = db.q("""SELECT reason, ts, by_id FROM warnings
                   WHERE chat_id=? AND user_id=? AND revoked_at IS NULL
                   ORDER BY ts DESC LIMIT 10""", (msg.chat.id, t))
    if not rows:
        await reply(msg, T(msg, "warns.history_none", name=_named(msg, t)))
        return
    lines = "\n".join(
        f"• <code>{time.strftime('%d/%m %H:%M', time.localtime(r['ts']))}</code> "
        f"{tpl.esc(r['reason'] or '—')}" for r in rows)
    await reply(msg, T(msg, "warns.history", name=_named(msg, t), list=lines))


@dp.message(Command("warnlimit"))
@needs("settings.write")
async def cmd_warnlimit(msg: Message):
    touch(msg)
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await reply(msg, T(msg, "warns.limit_usage"))
        return
    raw = "" if parts[1].strip().lower() in ("off", "none") else parts[1].strip()
    if raw and not parse_policy(raw):
        await reply(msg, T(msg, "warns.limit_usage"))
        return
    db.set(msg.chat.id, "warn_policy", raw, msg.from_user.id)
    await reply(msg, T(msg, "warns.limit_set"))


# ── מנהלים ────────────────────────────────────────────────────────────────
@dp.message(Command("promote"))
@needs("roles.assign")
async def cmd_promote(msg: Message):
    touch(msg)
    t = _target_of(msg)
    if t is None:
        await reply(msg, T(msg, "target.usage"))
        return
    try:
        await bot.promote_chat_member(
            msg.chat.id, t, can_delete_messages=True,
            can_restrict_members=True, can_pin_messages=True,
            can_invite_users=True, can_manage_video_chats=True)
    except TelegramAPIError:
        await reply(msg, T(msg, "err.failed"))
        return
    perms.set_role(msg.chat.id, t, "admin")
    _admin_cache.pop(msg.chat.id, None)
    audit.log(msg.chat.id, "admin.promote", actor_id=msg.from_user.id,
              target_id=t, severity="high")
    await reply(msg, T(msg, "admin.promoted", name=_named(msg, t)))


@dp.message(Command("demote"))
@needs("roles.assign")
async def cmd_demote(msg: Message):
    touch(msg)
    t = _target_of(msg)
    if t is None:
        await reply(msg, T(msg, "target.usage"))
        return
    try:
        await bot.promote_chat_member(
            msg.chat.id, t, can_delete_messages=False,
            can_restrict_members=False, can_pin_messages=False,
            can_invite_users=False, can_manage_video_chats=False,
            can_promote_members=False, can_change_info=False)
    except TelegramAPIError:
        await reply(msg, T(msg, "err.failed"))
        return
    perms.set_role(msg.chat.id, t, "member")
    _admin_cache.pop(msg.chat.id, None)
    audit.log(msg.chat.id, "admin.demote", actor_id=msg.from_user.id,
              target_id=t, severity="high")
    await reply(msg, T(msg, "admin.demoted", name=_named(msg, t)))


@dp.message(Command("adminlist"))
async def cmd_adminlist(msg: Message):
    touch(msg)
    if msg.chat.type not in GROUP_TYPES:
        await reply(msg, T(msg, "err.group_only"))
        return
    admins = await sync_admins(msg.chat.id, force=True)
    lines = "\n".join(f"• {_named(msg, u)}"
                      + (" 👑" if r == "owner" else "")
                      for u, r in admins.items())
    await reply(msg, T(msg, "admin.list", list=lines or "—"))


@dp.message(Command("roles"))
@needs("settings.read")
async def cmd_roles(msg: Message):
    touch(msg)
    rows = db.q("""SELECT user_id, role FROM members
                   WHERE chat_id=? AND role!='member' ORDER BY role""",
                (msg.chat.id,))
    lines = "\n".join(f"• {_named(msg, r['user_id'])} — {r['role']}"
                      for r in rows)
    await reply(msg, T(msg, "roles.list", list=lines or "—"))


# ── הקבוצה עצמה ───────────────────────────────────────────────────────────
@dp.message(Command("link"))
@needs("settings.read")
async def cmd_link(msg: Message):
    touch(msg)
    try:
        link = await bot.export_chat_invite_link(msg.chat.id)
    except TelegramAPIError:
        await reply(msg, T(msg, "err.failed"))
        return
    await reply(msg, T(msg, "chat.link", link=link))


@dp.message(Command("settitle"))
@needs("settings.write")
async def cmd_settitle(msg: Message):
    touch(msg)
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await reply(msg, T(msg, "set.usage", cmd="/settitle",
                           cur=tpl.esc(msg.chat.title or "")))
        return
    try:
        await bot.set_chat_title(msg.chat.id, parts[1][:128])
    except TelegramAPIError:
        await reply(msg, T(msg, "err.failed"))
        return
    audit.log(msg.chat.id, "chat.title", actor_id=msg.from_user.id,
              before=msg.chat.title, after=parts[1][:128], severity="medium")
    await reply(msg, T(msg, "chat.title_set"))


@dp.message(Command("setdesc"))
@needs("settings.write")
async def cmd_setdesc(msg: Message):
    touch(msg)
    parts = (msg.text or "").split(maxsplit=1)
    try:
        await bot.set_chat_description(msg.chat.id,
                                       parts[1][:255] if len(parts) > 1 else "")
    except TelegramAPIError:
        await reply(msg, T(msg, "err.failed"))
        return
    await reply(msg, T(msg, "chat.desc_set"))


@dp.message(Command("pinned"))
async def cmd_pinned(msg: Message):
    touch(msg)
    try:
        chat = await bot.get_chat(msg.chat.id)
    except TelegramAPIError:
        await reply(msg, T(msg, "err.failed"))
        return
    pin = getattr(chat, "pinned_message", None)
    if pin is None:
        await reply(msg, T(msg, "chat.no_pinned"))
        return
    with contextlib.suppress(TelegramAPIError):
        await bot.forward_message(msg.chat.id, msg.chat.id, pin.message_id)


# ── מתגי הגדרות ───────────────────────────────────────────────────────────
async def _toggle(msg: Message, key: str, cmd: str, default: str = "1"):
    arg = ((msg.text or "").split() + [""])[1].lower()
    cur = db.get(msg.chat.id, key, default) == "1"
    if arg not in ("on", "off"):
        await reply(msg, T(msg, "set.on_off", cmd=cmd,
                           cur=T(msg, "on" if cur else "off")))
        return
    db.set(msg.chat.id, key, "1" if arg == "on" else "0", msg.from_user.id)
    audit.log(msg.chat.id, "settings.write", actor_id=msg.from_user.id,
              before=f"{key}={int(cur)}", after=f"{key}={int(arg == 'on')}",
              severity="medium")
    await reply(msg, T(msg, "set.done", key=key, value=arg))


async def _number(msg: Message, key: str, cmd: str, default: str,
                  lo: int, hi: int):
    parts = (msg.text or "").split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        await reply(msg, T(msg, "set.usage", cmd=cmd,
                           cur=db.get(msg.chat.id, key, default)))
        return
    val = max(lo, min(hi, int(parts[1])))
    db.set(msg.chat.id, key, str(val), msg.from_user.id)
    await reply(msg, T(msg, "set.done", key=key, value=val))


@dp.message(Command("antiraid"))
@needs("settings.write")
async def cmd_antiraid(msg: Message):
    touch(msg); await _toggle(msg, "antiraid", "/antiraid")


@dp.message(Command("reports"))
@needs("settings.write")
async def cmd_reports(msg: Message):
    touch(msg); await _toggle(msg, "reports", "/reports")


@dp.message(Command("silent"))
@needs("settings.write")
async def cmd_silent(msg: Message):
    touch(msg); await _toggle(msg, "silent", "/silent")


@dp.message(Command("cleanservice"))
@needs("settings.write")
async def cmd_cleanservice(msg: Message):
    touch(msg); await _toggle(msg, "cleanservice", "/cleanservice", "0")


@dp.message(Command("setflood"))
@needs("settings.write")
async def cmd_setflood(msg: Message):
    """‎/setflood 0‎ מכבה. אין פקודה נפרדת לכיבוי, כי סף אפס **הוא** כיבוי."""
    touch(msg)
    parts = (msg.text or "").split()
    if len(parts) > 1 and parts[1].lower() == "off":
        db.set(msg.chat.id, "flood", "0", msg.from_user.id)
        await reply(msg, T(msg, "flood.off"))
        return
    if len(parts) > 1 and parts[1].isdigit():
        db.set(msg.chat.id, "flood", "1", msg.from_user.id)
    await _number(msg, "flood_rate", "/setflood", str(AF_RATE), 0, 100)


@dp.message(Command("floodaction"))
@needs("settings.write")
async def cmd_floodaction(msg: Message):
    touch(msg)
    parts = (msg.text or "").split()
    valid = ("delete", "warn", "mute", "kick", "ban")
    if len(parts) < 2 or parts[1].lower() not in valid:
        await reply(msg, T(msg, "set.usage", cmd="/floodaction " + "|".join(valid),
                           cur=db.get(msg.chat.id, "flood_action", "mute")))
        return
    db.set(msg.chat.id, "flood_action", parts[1].lower(), msg.from_user.id)
    await reply(msg, T(msg, "set.done", key="flood_action", value=parts[1].lower()))


@dp.message(Command("setclean"))
@needs("settings.write")
async def cmd_setclean(msg: Message):
    touch(msg); await _number(msg, "autoclean", "/setclean", "30", 0, 3600)


# ── החרגות ────────────────────────────────────────────────────────────────
def _allow_arg(msg: Message) -> tuple[Optional[str], str]:
    t = _target_of(msg)
    if t is not None:
        return "user", str(t)
    for tok in (msg.text or "").split()[1:]:
        if "." in tok:
            return "domain", tok
    return None, ""


@dp.message(Command("allow"))
@needs("settings.write")
async def cmd_allow(msg: Message):
    touch(msg)
    scope, value = _allow_arg(msg)
    if scope is None or not allow.add(msg.chat.id, scope, value):
        await reply(msg, T(msg, "allow.usage"))
        return
    audit.log(msg.chat.id, "allowlist.add", actor_id=msg.from_user.id,
              after=f"{scope}:{value}", severity="medium")
    await reply(msg, T(msg, "allow.added", value=tpl.esc(value)))


@dp.message(Command("unallow"))
@needs("settings.write")
async def cmd_unallow(msg: Message):
    touch(msg)
    scope, value = _allow_arg(msg)
    n = allow.remove(msg.chat.id, scope, value) if scope else 0
    await reply(msg, T(msg, "allow.removed") if n else T(msg, "allow.none"))


@dp.message(Command("allowlist"))
@needs("settings.read")
async def cmd_allowlist(msg: Message):
    touch(msg)
    rows = allow.all(msg.chat.id)
    if not rows:
        await reply(msg, T(msg, "allow.none"))
        return
    await reply(msg, T(msg, "allow.list", list="\n".join(
        f"• {sc}: <code>{tpl.esc(v)}</code>" for sc, v in rows)))


# ── מידע ──────────────────────────────────────────────────────────────────
@dp.message(Command("stats"))
@needs("settings.read")
async def cmd_stats(msg: Message):
    touch(msg)
    c = msg.chat.id
    day, week = time.time() - 86400, time.time() - 7 * 86400

    def n(sql, args):
        return (db.one(sql, args) or {"c": 0})["c"]
    await reply(msg, T(msg, "stats.card", chat=tpl.esc(msg.chat.title or ""),
        members=n("SELECT COUNT(*) c FROM members WHERE chat_id=?", (c,)),
        msgs=n("SELECT COALESCE(SUM(msg_count),0) c FROM members WHERE chat_id=?", (c,)),
        active=n("SELECT COUNT(*) c FROM members WHERE chat_id=? AND last_msg>?", (c, day)),
        today=n("SELECT COUNT(*) c FROM audit_log WHERE chat_id=? AND ts>?", (c, day)),
        week=n("SELECT COUNT(*) c FROM audit_log WHERE chat_id=? AND ts>?", (c, week)),
        warns=n("""SELECT COUNT(*) c FROM warnings WHERE chat_id=?
                   AND revoked_at IS NULL""", (c,)),
        locks=len(locks.get_all(c))))


@dp.message(Command("actions"))
@needs("audit.read")
async def cmd_actions(msg: Message):
    touch(msg)
    t = _target_of(msg)
    if t is None:
        await reply(msg, T(msg, "target.usage"))
        return
    rows = audit.for_user(msg.chat.id, t)[:10]
    if not rows:
        await reply(msg, T(msg, "actions.none", name=_named(msg, t)))
        return
    await reply(msg, T(msg, "actions.title", name=_named(msg, t), list="\n".join(
        f"<code>{time.strftime('%d/%m %H:%M', time.localtime(r['ts']))}</code> "
        f"{r['action']}" for r in rows)))


@dp.message(Command("locktypes"))
async def cmd_locktypes(msg: Message):
    touch(msg)
    lg = lang_of(msg)
    by: dict[str, list[str]] = {}
    for key, grp in LOCK_TYPES.items():
        by.setdefault(grp, []).append(f"<code>{key}</code>")
    await reply(msg, T(msg, "locktypes.list", list="\n".join(
        f"<b>{i18n.t('group.' + g, lg)}</b>\n" + ", ".join(v)
        for g, v in by.items())))


@dp.message(Command("vars"))
async def cmd_vars(msg: Message):
    touch(msg)
    await reply(msg, T(msg, "vars.help",
                       list=" ".join("<code>{" + v + "}</code>"
                                     for v in tpl.VARIABLES)))


# ── ייצוא וייבוא ──────────────────────────────────────────────────────────
IMPORT_MAX = 256 * 1024


@dp.message(Command("export"))
@needs("chat.export")
async def cmd_export(msg: Message):
    touch(msg)
    data = backup.export(db, msg.chat.id)
    raw = backup.dumps(db, msg.chat.id).encode()
    audit.log(msg.chat.id, "chat.export", actor_id=msg.from_user.id,
              severity="high")
    counts = T(msg, "export.counts", **backup.counts(data))
    with contextlib.suppress(TelegramAPIError):
        await bot.send_document(
            msg.from_user.id,
            BufferedInputFile(raw, filename=f"groupos-{msg.chat.id}.json"),
            caption=T(msg, "export.done", n=counts))
    await reply(msg, T(msg, "export.done", n=counts))


@dp.message(Command("import"))
@needs("chat.import")
async def cmd_import(msg: Message):
    touch(msg)
    doc = msg.reply_to_message.document if msg.reply_to_message else None
    if doc is None:
        await reply(msg, T(msg, "import.usage"))
        return
    if (doc.file_size or 0) > IMPORT_MAX:
        await reply(msg, T(msg, "import.too_big"))
        return
    try:
        buf = await bot.download(doc)
        data = backup.parse(buf.read().decode("utf-8", "replace"))
    except backup.ImportError_ as e:
        await reply(msg, T(msg, "import." + str(e)))
        return
    except (TelegramAPIError, UnicodeError, AttributeError):
        await reply(msg, T(msg, "err.failed"))
        return
    replace = "replace" in (msg.text or "").lower()
    got = backup.apply(db, msg.chat.id, data, msg.from_user.id, replace=replace)
    audit.log(msg.chat.id, "chat.import", actor_id=msg.from_user.id,
              after=str(got), severity="critical")
    await reply(msg, T(msg, "import.done", n=T(msg, "export.counts", **got)))


async def set_lockdown(chat_id: int, on: bool, by: Optional[int]) -> bool:
    """משתיק את כל הקבוצה בבת אחת, או מחזיר אותה.

    זה ‎setChatPermissions‎ — הרשאות ברירת המחדל של הצ'אט — ולא השתקה
    של כל משתמש בנפרד. לכן זה פועל מיד גם על מי שעוד לא הצטרף, ולכן
    ביטול הוא פעולה אחת ולא מאה."""
    try:
        await bot.set_chat_permissions(chat_id, MUTED if on else OPEN_CHAT)
    except TelegramAPIError as e:
        log.warning("השבתת קבוצה %s נכשלה: %s", chat_id, e)
        return False
    db.set(chat_id, "lockdown", "1" if on else "0", by)
    audit.log(chat_id, "chat.lockdown", actor_id=by, after="on" if on else "off",
              severity="high")
    return True


@dp.message(Command("lockdown"))
@needs("chat.lockdown")
async def cmd_lockdown(msg: Message):
    touch(msg)
    arg = ((msg.text or "").split() + [""])[1].lower()
    cur = db.get(msg.chat.id, "lockdown", "0") == "1"
    on = not cur if arg not in ("on", "off") else (arg == "on")
    okay = await set_lockdown(msg.chat.id, on, msg.from_user.id)
    await reply(msg, T(msg, "lockdown.on" if on else "lockdown.off")
                if okay else T(msg, "err.failed"))


def _lock_arg(msg: Message) -> tuple[Optional[str], str]:
    """‎(סוג, פעולה)‎ מתוך ‎/lock url ban‎. סוג לא מוכר מחזיר None."""
    parts = (msg.text or "").split()[1:]
    if not parts:
        return None, ""
    key = parts[0].lower().lstrip("#")
    action = parts[1].lower() if len(parts) > 1 else ""
    return (key if key in LOCK_TYPES else None), action


async def _lock_cmd(msg: Message, default_action: str):
    key, action = _lock_arg(msg)
    lg = lang_of(msg)
    if key is None:
        raw = (msg.text or "").split()
        if len(raw) > 1:
            await reply(msg, T(msg, "lock.unknown", name=raw[1]))
            return
        # רשימת הסוגים במקום "שימוש שגוי": מי ששכח את השם צריך אותו כאן
        await reply(msg, T(msg, "lock.usage",
                           types=", ".join(sorted(LOCK_TYPES))))
        return
    if action not in ACTIONS:
        action = default_action
    locks.set(msg.chat.id, key, action)
    audit.log(msg.chat.id, "lock.change", actor_id=msg.from_user.id,
              after=f"{key}={action}", severity="info")
    await reply(msg, T(msg, "lock.done", name=i18n.t(f"lock.{key}", lg),
                       action=panel.action_label(action, lg)))


@dp.message(Command("lock"))
@needs("locks.write")
async def cmd_lock(msg: Message):
    touch(msg); await _lock_cmd(msg, "delete")


@dp.message(Command("unlock"))
@needs("locks.write")
async def cmd_unlock(msg: Message):
    touch(msg); await _lock_cmd(msg, "off")


@dp.message(Command("locks"))
@needs("settings.read")
async def cmd_locks(msg: Message):
    touch(msg)
    lg = lang_of(msg)
    active = locks.get_all(msg.chat.id)
    if not active:
        await reply(msg, T(msg, "locks.state_none"))
        return
    lines = "\n".join(
        f"• {i18n.t(f'lock.{k}', lg)} — {panel.action_label(a, lg)}"
        for k, (a, _) in sorted(active.items()))
    await reply(msg, T(msg, "locks.state", list=lines))


@dp.message(Command("say"))
@needs("chat.say")
async def cmd_say(msg: Message):
    """הודעה בשם הבוט. הפקודה עצמה נמחקת — אחרת רואים מי כתב אותה."""
    touch(msg)
    text = (msg.text or "").split(maxsplit=1)
    if len(text) < 2 or not text[1].strip():
        await reply(msg, T(msg, "say.usage"))
        return
    _schedule_delete(msg.chat.id, msg.message_id, 1)
    audit.log(msg.chat.id, "chat.say", actor_id=msg.from_user.id,
              after=text[1][:200], severity="medium")
    await send(msg.chat.id, text[1])


@dp.message(Command("del"))
@needs("msg.delete")
async def cmd_del(msg: Message):
    touch(msg)
    if not msg.reply_to_message:
        await reply(msg, T(msg, "err.need_reply"))
        return
    with contextlib.suppress(TelegramAPIError):
        await bot.delete_message(msg.chat.id, msg.reply_to_message.message_id)
    audit.log(msg.chat.id, "msg.delete", actor_id=msg.from_user.id,
              target_id=(msg.reply_to_message.from_user.id
                         if msg.reply_to_message.from_user else None),
              severity="low")
    _schedule_delete(msg.chat.id, msg.message_id, 1)


@dp.message(Command("pin"))
@needs("chat.pin")
async def cmd_pin(msg: Message):
    touch(msg)
    if not msg.reply_to_message:
        await reply(msg, T(msg, "err.need_reply"))
        return
    try:
        # שקט: נעיצה שמודיעה לכל חבר בקבוצה היא בדיוק הרעש שהבוט הזה
        # נועד למנוע. מי שרוצה להודיע — יכתוב הודעה.
        await bot.pin_chat_message(msg.chat.id,
                                   msg.reply_to_message.message_id,
                                   disable_notification=True)
    except TelegramAPIError:
        await reply(msg, T(msg, "err.failed"))
        return
    audit.log(msg.chat.id, "chat.pin", actor_id=msg.from_user.id,
              after=msg.reply_to_message.message_id, severity="low")
    await reply(msg, T(msg, "pin.done"))


@dp.message(Command("unpin"))
@needs("chat.pin")
async def cmd_unpin(msg: Message):
    touch(msg)
    mid = msg.reply_to_message.message_id if msg.reply_to_message else None
    with contextlib.suppress(TelegramAPIError):
        await bot.unpin_chat_message(msg.chat.id, message_id=mid)
    await reply(msg, T(msg, "pin.off"))


@dp.message(Command("lang"))
async def cmd_lang(msg: Message):
    """בורר השפה. בקבוצה — למנהלים בלבד, כי זה משנה לכולם."""
    touch(msg)
    if msg.chat.type == ChatType.PRIVATE:
        await reply(msg, T(msg, "err.group_only"))
        return
    await sync_admins(msg.chat.id)
    if not perms.check(msg.chat.id, msg.from_user.id, "settings.write"):
        await reply(msg, T(msg, "err.need_admin"))
        return
    sc = panel.language_screen(msg.chat.id, lang.for_chat(msg.chat.id))
    await reply(msg, sc.text, markup=kb(sc))


@dp.message(Command("id"))
async def cmd_id(msg: Message):
    touch(msg)
    t = _target_of(msg) or (msg.from_user.id if msg.from_user else 0)
    await reply(msg, T(msg, "id.line", user=t, chat=msg.chat.id))


@dp.message(Command("health"))
async def cmd_health(msg: Message):
    touch(msg)
    s = guard.stats()
    await reply(msg, T(msg, "health.line", v=db.version, calls=s["calls"],
                       ms=s["avg_wait_ms"]))


def _parse_duration(txt: str) -> Optional[int]:
    m = re.match(r"^(\d+)([smhd])$", txt.strip(), re.I)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


async def _mod_cmd(msg: Message, kind: str, perm: str):
    target = _target_of(msg)
    if target is None:
        await reply(msg, T(msg, "err.need_reply"))
        return
    args = (msg.text or "").split()[1:]
    dur = _parse_duration(args[0]) if args else None
    reason = " ".join(args[1:] if dur else args) or ""
    okay = await apply_action(msg.chat.id, target, kind, dur, reason,
                              msg.from_user.id, "command")
    if not okay:
        await reply(msg, T(msg, "err.failed"))
        return
    lbl = T(msg, {"mute": "act.muted", "ban": "act.banned",
                  "kick": "act.kicked"}[kind])
    tail = T(msg, "act.reason", reason=reason) if reason else ""
    await reply(msg, f"{lbl}.{tail}")


@dp.message(Command("ban"))
@needs("user.ban")
async def cmd_ban(msg: Message):
    touch(msg); await _mod_cmd(msg, "ban", "user.ban")


@dp.message(Command("mute"))
@needs("user.mute")
async def cmd_mute(msg: Message):
    touch(msg); await _mod_cmd(msg, "mute", "user.mute")


@dp.message(Command("kick"))
@needs("user.kick")
async def cmd_kick(msg: Message):
    touch(msg); await _mod_cmd(msg, "kick", "user.kick")


@dp.message(Command("unban"))
@needs("user.unban")
async def cmd_unban(msg: Message):
    touch(msg)
    t = _target_of(msg)
    if t is None:
        await reply(msg, T(msg, "err.need_reply"))
        return
    with contextlib.suppress(TelegramAPIError):
        await bot.unban_chat_member(msg.chat.id, t, only_if_banned=True)
    mod.lift(msg.chat.id, t, "ban", msg.from_user.id)
    await reply(msg, T(msg, "act.unbanned"))


@dp.message(Command("unmute"))
@needs("user.unmute")
async def cmd_unmute(msg: Message):
    touch(msg)
    t = _target_of(msg)
    if t is None:
        await reply(msg, T(msg, "err.need_reply"))
        return
    with contextlib.suppress(TelegramAPIError):
        await bot.restrict_chat_member(msg.chat.id, t, UNMUTED)
    mod.lift(msg.chat.id, t, "mute", msg.from_user.id)
    await reply(msg, T(msg, "act.unmuted"))


@dp.message(Command("warn"))
@needs("user.warn")
async def cmd_warn(msg: Message):
    touch(msg)
    t = _target_of(msg)
    if t is None:
        await reply(msg, T(msg, "err.need_reply"))
        return
    reason = " ".join((msg.text or "").split()[1:])
    out = mod.warn(msg.chat.id, t, msg.from_user.id, reason, "command")
    if out.threshold_hit:
        await apply_action(msg.chat.id, t, out.kind, out.duration,
                           out.reason, msg.from_user.id, "policy")
        await reply(msg, T(msg, "warn.triggered", n=out.warns,
                           action=out.label))
    else:
        tail = T(msg, "act.reason", reason=reason) if reason else ""
        await reply(msg, T(msg, "warn.added", n=out.warns) + tail)


@dp.message(Command("unwarn"))
@needs("user.unwarn")
async def cmd_unwarn(msg: Message):
    touch(msg)
    t = _target_of(msg)
    if t is None:
        await reply(msg, T(msg, "err.need_reply"))
        return
    n = mod.unwarn(msg.chat.id, t, msg.from_user.id)
    await reply(msg, T(msg, "warn.removed", n=n))


@dp.message(Command("warns"))
@needs("user.warn")
async def cmd_warns(msg: Message):
    touch(msg)
    t = _target_of(msg) or msg.from_user.id
    n = mod.warn_count(msg.chat.id, t)
    await reply(msg, T(msg, "warn.count", n=n))


@dp.message(Command("purge"))
@needs("chat.purge")
async def cmd_purge(msg: Message):
    """מוחק מההודעה שהשבת עליה ועד הפקודה."""
    touch(msg)
    args = (msg.text or "").split()[1:]
    count = _int(args[0], 0) if args else 0
    if count:
        if count > PURGE_MAX:
            await reply(msg, T(msg, "purge.too_many", n=PURGE_MAX))
            return
        first = max(msg.message_id - count, 1)
    elif msg.reply_to_message:
        first = msg.reply_to_message.message_id
        if msg.message_id - first > PURGE_MAX:
            await reply(msg, T(msg, "purge.too_many", n=PURGE_MAX))
            return
    else:
        await reply(msg, T(msg, "purge.usage"))
        return
    n = 0
    for mid in range(first, msg.message_id + 1):
        with contextlib.suppress(TelegramAPIError):
            await bot.delete_message(msg.chat.id, mid)
            n += 1
    audit.log(msg.chat.id, "chat.purge", actor_id=msg.from_user.id,
              after=n, severity="medium")
    await send(msg.chat.id, T(msg, "purge.done", n=n), clean_after=10)


@dp.message(Command("role"))
@needs("roles.assign")
async def cmd_role(msg: Message):
    touch(msg)
    target = _target_of(msg)
    parts = (msg.text or "").split()
    if target is None or len(parts) < 2 or parts[1] not in RANK:
        await reply(msg, T(msg, "role.pick", roles=", ".join(RANK)))
        return
    old = perms.role_of(msg.chat.id, target)
    perms.set_role(msg.chat.id, target, parts[1])
    audit.log(msg.chat.id, "role.change", actor_id=msg.from_user.id,
              target_id=target, before=old, after=parts[1], severity="medium")
    await reply(msg, T(msg, "role.changed", before=old, after=parts[1]))


# ── הפאנל הפרטי ────────────────────────────────────────────────────────────
def _stats(chat_id: int) -> dict:
    day = time.time() - 86400
    return {
        "members": (db.one("SELECT COUNT(*) c FROM members WHERE chat_id=?",
                           (chat_id,)) or {"c": 0})["c"],
        "locks": len(locks.get_all(chat_id)),
        "warns": (db.one("""SELECT COUNT(*) c FROM warnings
                            WHERE chat_id=? AND revoked_at IS NULL""",
                         (chat_id,)) or {"c": 0})["c"],
        "actions_today": (db.one("""SELECT COUNT(*) c FROM audit_log
                                    WHERE chat_id=? AND ts>?""",
                                 (chat_id, day)) or {"c": 0})["c"],
        "lockdown": db.get(chat_id, "lockdown", "0") == "1",
    }


def _title(chat_id: int) -> str:
    r = db.one("SELECT title FROM chats WHERE chat_id=?", (chat_id,))
    return (r["title"] if r else "") or str(chat_id)


def _screen_for(chat_id: int, name: str, arg: str) -> Optional[panel.Screen]:
    lg = lang.for_chat(chat_id)
    if name == "main":
        return panel.main_menu(chat_id, _title(chat_id), _stats(chat_id), lg)
    if name == "locks":
        by = locks.by_group(chat_id)
        counts = {g: sum(1 for _, _, a in items if a != "off")
                  for g, items in by.items()}
        return panel.locks_groups(chat_id, counts, lg)
    if name == "lockg":
        if arg not in locks.by_group(chat_id):
            return None
        return panel.locks_in_group(chat_id, arg,
                                    locks.by_group(chat_id)[arg], lg)
    if name == "warns":
        top = [(r["user_id"], r["user_id"], r["c"]) for r in db.q(
            """SELECT user_id, COUNT(*) c FROM warnings
               WHERE chat_id=? AND revoked_at IS NULL
               GROUP BY user_id ORDER BY c DESC LIMIT 5""", (chat_id,))]
        return panel.warns_screen(
            chat_id, db.get(chat_id, "warn_policy", ""), top, lg)
    if name == "audit":
        return panel.audit_screen(
            chat_id, audit.recent(chat_id, 10),
            lambda t: time.strftime("%d/%m %H:%M", time.localtime(t)), lg)
    if name == "settings":
        return panel.settings_screen(chat_id, {
            "autoclean": db.get(chat_id, "autoclean", "30"),
            "silent": db.get(chat_id, "silent", "1")}, lg)
    if name == "lang":
        return panel.language_screen(chat_id, lg)
    if name == "sec":
        return panel.security_screen(chat_id, emerg.status(db, chat_id),
                                     _sec_numbers(chat_id), lg)
    return None


def _sec_numbers(chat_id: int) -> dict:
    day = time.time() - 86400
    return {
        "locks": len(locks.get_all(chat_id)),
        "blocks": len(blocks.all(chat_id)),
        "pending": pending.count(chat_id),
        "events": (db.one("""SELECT COUNT(*) c FROM audit_log
                             WHERE chat_id=? AND ts>? AND severity IN
                               ('medium','high','critical')""",
                          (chat_id, day)) or {"c": 0})["c"],
        "captcha": db.get(chat_id, "captcha", "0") == "1",
        "flood": db.get(chat_id, "flood", "1") == "1",
        "antiraid": db.get(chat_id, "antiraid", "1") == "1",
        "reports": db.get(chat_id, "reports", "1") == "1",
    }


@dp.callback_query(F.data.startswith("g:"))
async def on_callback(q: CallbackQuery):
    parsed = panel.parse_cb(q.data or "")
    if parsed is None:
        await q.answer(i18n.t("btn.unknown", i18n.normalize(
            q.from_user.language_code)))
        return
    chat_id, name, arg = parsed
    lg = (lang.for_chat(chat_id) if chat_id
          else i18n.normalize(q.from_user.language_code))

    if name == "pick":
        # בחירת שפה אישית בצ'אט הפרטי. chat_id=0 כי עוד אין קבוצה.
        lang.set_chat(q.message.chat.id, arg)
        lg = i18n.normalize(arg)
        await _edit(q, panel.home(my_groups(q.from_user.id), lg))
        await q.answer(i18n.t("lang.set", lg))
        return

    if name == "home":
        await _edit(q, panel.home(my_groups(q.from_user.id), lg))
        return

    # כל לחיצה נבדקת מחדש. מי שהודח מהניהול לא ימשיך לנהל דרך מסך פתוח.
    if not perms.check(chat_id, q.from_user.id, "settings.read"):
        await q.answer(i18n.t("err.not_your_group", lg), show_alert=True)
        return

    if name == "lock":
        if not perms.check(chat_id, q.from_user.id, "locks.write"):
            await q.answer(i18n.t("err.need_admin", lg), show_alert=True)
            return
        if arg not in LOCK_TYPES:
            await q.answer(i18n.t("btn.unknown", lg))
            return
        cur = locks.get_all(chat_id).get(arg, ("off", None))[0]
        nxt = panel.next_in_cycle(panel.CYCLE, cur)
        locks.set(chat_id, arg, nxt)
        audit.log(chat_id, "lock.change", actor_id=q.from_user.id,
                  before=f"{arg}={cur}", after=f"{arg}={nxt}",
                  source="button", severity="info")
        await _edit(q, _screen_for(chat_id, "lockg", LOCK_TYPES[arg][1]))
        await q.answer(panel.action_label(nxt, lg))
        return

    if name == "lockall":
        if not perms.check(chat_id, q.from_user.id, "locks.write"):
            await q.answer(i18n.t("err.need_admin", lg), show_alert=True)
            return
        n = locks.set_many(chat_id, "delete" if arg == "on" else "off")
        audit.log(chat_id, "locks.bulk", actor_id=q.from_user.id,
                  after=f"{arg}×{n}", source="button", severity="medium")
        await _edit(q, _screen_for(chat_id, "locks", ""))
        await q.answer(i18n.t("locks.bulk", lg, n=n))
        return

    if name == "tgl":
        if not perms.check(chat_id, q.from_user.id, "settings.write"):
            await q.answer(i18n.t("err.need_admin", lg), show_alert=True)
            return
        if arg not in ("captcha", "flood", "antiraid", "reports"):
            await q.answer(i18n.t("btn.unknown", lg))
            return
        cur = db.get(chat_id, arg, "1" if arg != "captcha" else "0") == "1"
        db.set(chat_id, arg, "0" if cur else "1", q.from_user.id)
        audit.log(chat_id, "settings.write", actor_id=q.from_user.id,
                  before=f"{arg}={int(cur)}", after=f"{arg}={int(not cur)}",
                  source="button", severity="medium")
        await _edit(q, _screen_for(chat_id, "sec", ""))
        await q.answer(i18n.t("saved", lg))
        return

    if name == "emerg":
        if not perms.check(chat_id, q.from_user.id, "emergency.toggle"):
            await q.answer(i18n.t("err.need_admin", lg), show_alert=True)
            return
        if emerg.is_on(db, chat_id):
            emerg.disable(db, chat_id, q.from_user.id)
            audit.log(chat_id, "emergency.off", actor_id=q.from_user.id,
                      source="button", severity="high")
            note = "emergency.off"
        else:
            emerg.enable(db, chat_id, q.from_user.id)
            audit.log(chat_id, "emergency.on", actor_id=q.from_user.id,
                      source="button", severity="critical")
            note = "emergency.on"
        await _edit(q, _screen_for(chat_id, "sec", ""))
        await q.answer(i18n.t(note, lg).replace("<b>", "").replace("</b>", "")
                       .split("\n")[0], show_alert=True)
        return

    if name == "ldown":
        if not perms.check(chat_id, q.from_user.id, "chat.lockdown"):
            await q.answer(i18n.t("err.need_admin", lg), show_alert=True)
            return
        on = db.get(chat_id, "lockdown", "0") != "1"
        okay = await set_lockdown(chat_id, on, q.from_user.id)
        await _edit(q, _screen_for(chat_id, "main", ""))
        key = "lockdown.short_on" if on else "lockdown.short_off"
        await q.answer(i18n.t(key if okay else "err.failed", lg),
                       show_alert=True)
        return

    if name == "wpol":
        if not perms.check(chat_id, q.from_user.id, "settings.write"):
            await q.answer(i18n.t("err.need_admin", lg), show_alert=True)
            return
        db.set(chat_id, "warn_policy", panel.WARN_PRESETS.get(arg, ""),
               q.from_user.id)
        await _edit(q, _screen_for(chat_id, "warns", ""))
        await q.answer(i18n.t("policy.updated", lg))
        return

    if name == "setlang":
        if not perms.check(chat_id, q.from_user.id, "settings.write"):
            await q.answer(i18n.t("err.need_admin", lg), show_alert=True)
            return
        lang.set_chat(chat_id, arg)
        audit.log(chat_id, "lang.change", actor_id=q.from_user.id,
                  before=lg, after=i18n.normalize(arg),
                  source="button", severity="info")
        await _edit(q, _screen_for(chat_id, "lang", ""))
        await q.answer(i18n.t("lang.set", arg))
        return

    if name in ("clean", "silent"):
        if not perms.check(chat_id, q.from_user.id, "settings.write"):
            await q.answer(i18n.t("err.need_admin", lg), show_alert=True)
            return
        if name == "clean":
            cur = db.get(chat_id, "autoclean", "30")
            db.set(chat_id, "autoclean",
                   panel.next_in_cycle(panel.CLEAN_CYCLE, cur), q.from_user.id)
        else:
            db.set(chat_id, "silent",
                   "0" if db.get(chat_id, "silent", "1") == "1" else "1",
                   q.from_user.id)
        await _edit(q, _screen_for(chat_id, "settings", ""))
        await q.answer(i18n.t("saved", lg))
        return

    sc = _screen_for(chat_id, name, arg)
    if sc is None:
        await q.answer(i18n.t("screen.unknown", lg))
        return
    await _edit(q, sc)
    await q.answer()


async def _edit(q: CallbackQuery, sc: panel.Screen) -> None:
    with contextlib.suppress(TelegramAPIError):
        await q.message.edit_text(sc.text, reply_markup=kb(sc))


# ── תפריט הפקודות של טלגרם ─────────────────────────────────────────────────
async def publish_commands() -> None:
    """רושם את הפקודות בתפריט ✏️, פעם אחת לכל שפה.

    טלגרם בוחרת לכל משתמש את הרשימה לפי שפת הממשק שלו, ונופלת לברירת
    המחדל כשאין התאמה. לכן ברירת המחדל נרשמת **בלי** ‎language_code‎,
    ואחריה כל שפה שיש לה מילון."""
    for code in [None] + [c for c in i18n.STRINGS if c != i18n.DEFAULT]:
        items = [BotCommand(command=n, description=d[:256])
                 for n, d in panel.command_list(code or i18n.DEFAULT)]
        try:
            await bot.set_my_commands(items, language_code=code)
        except TelegramAPIError as e:
            log.warning("רישום פקודות ל-%s נכשל: %s", code or "ברירת מחדל", e)


# ── רקע ────────────────────────────────────────────────────────────────────
async def expire_loop():
    """משחרר ענישות שפג תוקפן. טלגרם משחררת לבד לפי until_date, אבל
    המסד צריך לדעת — אחרת /warns ומסכי הפאנל מציגים מצב שאינו קיים."""
    while True:
        await asyncio.sleep(60)
        try:
            for s in mod.expired():
                mod.lift(s["chat_id"], s["user_id"], s["kind"], None)
        except Exception as e:
            log.warning("שחרור ענישות נכשל: %s", e)
        try:
            # אתגר שפג אינו "עוד מעט": הנכנס מושתק כל עוד הוא פתוח,
            # ולכן ההכרעה חייבת לקרות גם אם אף אחד לא לחץ דבר.
            for ch in pending.expired():
                audit.log(ch.chat_id, "captcha.timeout", target_id=ch.user_id,
                          actor_kind="bot", source="policy", severity="low")
                await _captcha_done(ch, False)
        except Exception as e:
            log.warning("סגירת אתגרים שפגו נכשלה: %s", e)


async def main() -> int:
    global bot, _me_id
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not TOKEN:
        log.error("חסר GROUPOS_TOKEN. ערוך את /opt/groupos/.env")
        return EX_CONFIG
    if not re.match(r"^\d{6,}:[A-Za-z0-9_-]{30,}$", TOKEN):
        shown = TOKEN[:12] + "…" if len(TOKEN) > 12 else TOKEN
        log.error("הטוקן ב-GROUPOS_TOKEN אינו בצורה של טוקן טלגרם.")
        log.error("  מה שנמצא: %r (%d תווים)", shown, len(TOKEN))
        log.error("  הצורה הנכונה: 123456789:AA...")
        log.error("  לתיקון:  bash /opt/groupos/install.sh --token <הטוקן>")
        return EX_CONFIG

    kw = {}
    if API_BASE:
        from aiogram.client.session.aiohttp import AiohttpSession
        from aiogram.client.telegram import TelegramAPIServer
        kw["session"] = AiohttpSession(api=TelegramAPIServer.from_base(API_BASE))
        log.info("שרת Bot API מקומי: %s", API_BASE)
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML), **kw)
    me = await bot.get_me()
    _me_id = me.id
    log.info("GroupOS עלה כ-@%s · סכימה v%s", me.username, db.version)
    for p in ai.stats():
        log.info("AI %s: %d מפתחות · תקציב %s", p["provider"], p["keys"],
                 p["budget"] or "לא ידוע")
    if not ai.pools:
        log.info("AI: לא הוגדרו מפתחות (GROUPOS_GEMINI_KEYS / GROUPOS_GROQ_KEYS)")
    await publish_commands()
    task = asyncio.create_task(expire_loop())
    _bg.add(task)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        task.cancel()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
