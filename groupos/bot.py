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
from aiogram.types import (BotCommand, CallbackQuery, ChatPermissions,
                           InlineKeyboardButton, InlineKeyboardMarkup, Message)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import i18n                                     # noqa: E402
import panel                                    # noqa: E402
from audit import Audit                         # noqa: E402
from db import Db                               # noqa: E402
from locks import LOCK_TYPES, Locks             # noqa: E402
from moderation import Moderation               # noqa: E402
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
lang = i18n.Lang(db)
guard = RateGuard()
dp = Dispatcher()
bot: Optional[Bot] = None

GROUP_TYPES = (ChatType.GROUP, ChatType.SUPERGROUP)
_admin_cache: dict[int, tuple[float, dict[int, str]]] = {}
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
    """שפת הקבוצה אם נקבעה, אחרת שפת הטלגרם של מי ששלח.

    בפרטי אין קבוצה, ולכן שפת המשתמש היא היחידה שקיימת."""
    u = msg.from_user
    code = u.language_code if u else None
    if msg.chat.type == ChatType.PRIVATE:
        return i18n.normalize(code)
    return lang.for_user(msg.chat.id, u.id if u else 0, code)


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


def my_groups(user_id: int) -> list[tuple[int, str]]:
    return [(r["chat_id"], r["title"] or str(r["chat_id"])) for r in db.q(
        """SELECT c.chat_id, c.title FROM chats c
           JOIN members m ON m.chat_id = c.chat_id
           WHERE m.user_id=? AND m.role IN ('owner','super_admin','admin')
             AND c.active=1 ORDER BY c.title""", (user_id,))]


# ── רישום ──────────────────────────────────────────────────────────────────
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
        db.run("""INSERT INTO chats (chat_id,title,username,type,added_at)
                  VALUES (?,?,?,?,?)
                  ON CONFLICT (chat_id) DO UPDATE SET
                    title=excluded.title, username=excluded.username, active=1""",
               (msg.chat.id, msg.chat.title or "", msg.chat.username,
                msg.chat.type, now))
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
    if msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user.id
    return None


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


@dp.message(F.chat.type.in_(GROUP_TYPES), ~F.text.startswith("/"))
async def on_group_message(msg: Message):
    touch(msg)
    if msg.from_user is None:
        return
    # מנהלים אינם נבדקים מול נעילות — זה כלל שכל בוט ניהול מקיים
    await sync_admins(msg.chat.id)
    if perms.rank_of(msg.chat.id, msg.from_user.id) >= RANK["moderator"]:
        return
    hit = locks.check(msg.chat.id, _describe(msg))
    if not hit:
        return
    with contextlib.suppress(TelegramAPIError):
        await bot.delete_message(msg.chat.id, msg.message_id)
    audit.log(msg.chat.id, "lock.triggered", target_id=msg.from_user.id,
              actor_kind="bot", reason=hit.label, after=hit.action,
              source="policy", severity="low")

    if hit.action == "warn":
        out = mod.warn(msg.chat.id, msg.from_user.id, None, hit.label, "policy")
        if out.threshold_hit:
            await apply_action(msg.chat.id, msg.from_user.id, out.kind,
                               out.duration, out.reason, None)
        if db.get(msg.chat.id, "silent", "1") != "1":
            await send(msg.chat.id,
                       T(msg, "lock.violation", name=_name(msg),
                         label=hit.label, n=out.warns),
                       clean_after=clean_delay(msg.chat.id) or None)
    elif hit.action in ("mute", "ban", "kick"):
        await apply_action(msg.chat.id, msg.from_user.id, hit.action,
                           hit.duration, hit.label, None)


def _name(msg: Message) -> str:
    u = msg.from_user
    return f"@{u.username}" if u and u.username else (u.first_name if u else "משתמש")


# ── פקודות בקבוצה ──────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(msg: Message):
    touch(msg)
    if msg.chat.type == ChatType.PRIVATE:
        sc = panel.home(my_groups(msg.from_user.id), lang_of(msg))
        await send(msg.chat.id, sc.text, is_group=False, markup=kb(sc))
    else:
        await sync_admins(msg.chat.id, force=True)
        await reply(msg, T(msg, "start.group"))


@dp.message(Command("help"))
async def cmd_help(msg: Message):
    """כל הפקודות, בשפה של הצ'אט. בפרטי לא נמחק — שם זה אמור להישאר."""
    touch(msg)
    sc = panel.help_screen(lang_of(msg))
    if msg.chat.type == ChatType.PRIVATE:
        await send(msg.chat.id, sc.text, is_group=False)
    else:
        await reply(msg, sc.text)


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
    if not msg.reply_to_message:
        await reply(msg, T(msg, "purge.need_reply"))
        return
    start = msg.reply_to_message.message_id
    n = 0
    for mid in range(start, msg.message_id + 1):
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
    return None


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


async def main() -> int:
    global bot
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
    log.info("GroupOS עלה כ-@%s · סכימה v%s", me.username, db.version)
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
