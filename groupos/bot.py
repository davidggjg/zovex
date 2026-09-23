#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bot — מתאם טלגרם. השכבה הדקה היחידה שיודעת ש-aiogram קיים.

## הכלל שמחזיק את כל הארכיטקטורה

מודול אחד בלבד מייבא ‎aiogram‎ — זה. ‎db‎, ‎permissions‎, ‎audit‎ ו-‎ratelimit‎
אינם יודעים שקיים טלגרם, ולכן הם נבדקים בלי טלגרם — 57 בדיקות רצות בלי
טוקן ובלי רשת.

זה גם מה שמשאיר פתוחה את הדלת ל-Go: אם המערכת תגדל מעבר למה שפייתון
נותן, מה שצריך להיכתב מחדש הוא הקובץ הזה, לא המנוע.

## כל פקודה עוברת את אותו מסלול

    עדכון → זיהוי שחקן → בדיקת הרשאה → פעולה → יומן → תשובה דרך RateGuard

אף פקודה לא בודקת הרשאות בעצמה. היא מצהירה מה היא דורשת ב-‎@needs‎,
והמסלול בודק. פקודה שנכתבת בלי ההצהרה הזאת פשוט לא תרוץ.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import time
from functools import wraps
from typing import Callable, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import TelegramRetryAfter, TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit import Audit          # noqa: E402
from db import Db                # noqa: E402
from permissions import Permissions, RANK  # noqa: E402
from ratelimit import RateGuard  # noqa: E402

log = logging.getLogger("groupos")

# קוד יציאה 78 = EX_CONFIG. ה-systemd unit מורה לא להפעיל מחדש עליו,
# כי טוקן שגוי לא יתקן את עצמו בניסיון ה-12 — הוא רק שורף מעבד.
EX_CONFIG = 78

TOKEN = os.environ.get("GROUPOS_TOKEN", "").strip()
# שרת Bot API מקומי — מחזיר נתיב מקומי לקבצים במקום להוריד אותם,
# ומעלה את תקרת ההעלאה ל-2000MB. ריק = השרת של טלגרם.
API_BASE = os.environ.get("GROUPOS_API_BASE", "").strip()

db = Db()
perms = Permissions(db)
audit = Audit(db)
guard = RateGuard()
dp = Dispatcher()


# ── שליחה ──────────────────────────────────────────────────────────────────
async def reply(msg: Message, text: str, **kw) -> Optional[Message]:
    """התשובה היחידה שמותר לשלוח — עוברת דרך שומר המכסות.

    טלגרם מרשה הודעה אחת בשנייה לצ'אט ו-20 בדקה בקבוצה. שליחה ישירה
    דרך ‎msg.answer‎ עוקפת את השומר וגוררת FloodWait, ולכן אין קריאה
    כזאת בשום מקום אחר בקוד.
    """
    is_group = msg.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
    await guard.acquire(msg.chat.id, is_group)
    try:
        return await msg.answer(text, **kw)
    except TelegramRetryAfter as e:
        guard.note_flood_wait(msg.chat.id, float(e.retry_after))
        log.warning("FloodWait %ss בצ'אט %s", e.retry_after, msg.chat.id)
    except TelegramAPIError as e:
        log.warning("שליחה נכשלה בצ'אט %s: %s", msg.chat.id, e)
    return None


# ── זיהוי ורישום ───────────────────────────────────────────────────────────
def touch(msg: Message) -> None:
    """מעדכן מי ראינו ואיפה. הבסיס ל-flood, ל-reputation ולסטטיסטיקות."""
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
    if msg.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        db.run("""INSERT INTO chats (chat_id,title,username,type,added_at)
                  VALUES (?,?,?,?,?)
                  ON CONFLICT (chat_id) DO UPDATE SET
                    title=excluded.title, username=excluded.username""",
               (msg.chat.id, msg.chat.title or "", msg.chat.username,
                msg.chat.type, now))
        db.run("""INSERT INTO members (chat_id,user_id,msg_count,last_msg)
                  VALUES (?,?,1,?)
                  ON CONFLICT (chat_id,user_id) DO UPDATE SET
                    msg_count=members.msg_count+1, last_msg=excluded.last_msg""",
               (msg.chat.id, u.id, now))


def needs(permission: str):
    """מצהיר איזו הרשאה הפקודה דורשת. הבדיקה נעשית כאן, פעם אחת."""
    def deco(fn: Callable):
        @wraps(fn)
        async def inner(msg: Message, *a, **kw):
            if msg.from_user is None:
                return
            if msg.chat.type == ChatType.PRIVATE:
                await reply(msg, "הפקודה הזאת עובדת בתוך קבוצה.")
                return
            d = perms.check(msg.chat.id, msg.from_user.id, permission,
                            _target_of(msg))
            if not d:
                await reply(msg, f"אין לך הרשאה לזה — {d.reason}.")
                audit.log(msg.chat.id, "permission.denied",
                          actor_id=msg.from_user.id, reason=d.reason,
                          after=permission, severity="low", source="command")
                return
            return await fn(msg, *a, **kw)
        return inner
    return deco


def _target_of(msg: Message) -> Optional[int]:
    if msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user.id
    return None


# ── פקודות ─────────────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(msg: Message):
    touch(msg)
    if msg.chat.type == ChatType.PRIVATE:
        await reply(msg, "GroupOS פעיל.\n\nהוסף אותי לקבוצה ותן לי הרשאות ניהול.")
    else:
        await reply(msg, "GroupOS מחובר לקבוצה הזאת.")


@dp.message(Command("id"))
async def cmd_id(msg: Message):
    touch(msg)
    t = _target_of(msg) or (msg.from_user.id if msg.from_user else 0)
    await reply(msg, f"מזהה המשתמש: <code>{t}</code>\n"
                     f"מזהה הצ'אט: <code>{msg.chat.id}</code>")


@dp.message(Command("role"))
@needs("roles.assign")
async def cmd_role(msg: Message):
    """/role <תפקיד> בתגובה להודעה."""
    touch(msg)
    target = _target_of(msg)
    if target is None:
        await reply(msg, "צריך להשיב להודעה של מי שרוצים לשנות לו תפקיד.")
        return
    parts = (msg.text or "").split()
    if len(parts) < 2 or parts[1] not in RANK:
        await reply(msg, "תפקידים: " + ", ".join(
            f"<code>{r}</code>" for r in RANK))
        return
    new = parts[1]
    old = perms.role_of(msg.chat.id, target)
    perms.set_role(msg.chat.id, target, new)
    audit.log(msg.chat.id, "role.change", actor_id=msg.from_user.id,
              target_id=target, before=old, after=new, severity="medium")
    await reply(msg, f"התפקיד שונה מ-<code>{old}</code> ל-<code>{new}</code>.")


@dp.message(Command("perms"))
@needs("settings.read")
async def cmd_perms(msg: Message):
    touch(msg)
    target = _target_of(msg) or msg.from_user.id
    role = perms.role_of(msg.chat.id, target)
    allowed = [p for p, ok in perms.list_for(msg.chat.id, role).items() if ok]
    await reply(msg, f"תפקיד: <code>{role}</code>\n"
                     f"הרשאות ({len(allowed)}):\n" +
                     "\n".join(f"• <code>{p}</code>" for p in sorted(allowed)))


@dp.message(Command("audit"))
@needs("audit.read")
async def cmd_audit(msg: Message):
    touch(msg)
    rows = audit.recent(msg.chat.id, limit=10)
    if not rows:
        await reply(msg, "היומן ריק.")
        return
    lines = []
    for r in rows:
        when = time.strftime("%d/%m %H:%M", time.localtime(r["ts"]))
        who = r["actor_id"] or r["actor_kind"]
        lines.append(f"<code>{when}</code> {r['action']} · {who}"
                     + (f" ← {r['target_id']}" if r["target_id"] else ""))
    await reply(msg, "עשר הפעולות האחרונות:\n" + "\n".join(lines))


@dp.message(Command("health"))
async def cmd_health(msg: Message):
    touch(msg)
    s = guard.stats()
    await reply(msg,
                f"גרסת סכימה: <code>{db.version}</code>\n"
                f"שליחות: <code>{s['calls']}</code>\n"
                f"המתנה ממוצעת: <code>{s['avg_wait_ms']}ms</code>\n"
                f"צ'אטים במעקב: <code>{s['chats_tracked']}</code>")


@dp.message(F.text | F.caption)
async def on_message(msg: Message):
    """כל הודעה אחרת. כאן ייכנסו שכבות הזיהוי בשלב 2."""
    touch(msg)


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not TOKEN:
        log.error("חסר GROUPOS_TOKEN. ערוך את /opt/groupos/.env")
        return EX_CONFIG
    if not re.match(r"^\d{6,}:[A-Za-z0-9_-]{30,}$", TOKEN):
        # הודעה שאומרת *מה* לא בסדר. "Token is invalid" של aiogram
        # לא מגלה שמה שיושב שם הוא טקסט מציין-מקום עם רווחים.
        shown = TOKEN[:12] + "…" if len(TOKEN) > 12 else TOKEN
        log.error("הטוקן ב-GROUPOS_TOKEN אינו בצורה של טוקן טלגרם.")
        log.error("  מה שנמצא: %r (%d תווים)", shown, len(TOKEN))
        log.error("  הצורה הנכונה: 123456789:AA...")
        log.error("  לתיקון:  bash /opt/groupos/install.sh --token <הטוקן>")
        return EX_CONFIG
    kw = {}
    if API_BASE:
        from aiogram.client.telegram import TelegramAPIServer
        from aiogram.client.session.aiohttp import AiohttpSession
        kw["session"] = AiohttpSession(
            api=TelegramAPIServer.from_base(API_BASE))
        log.info("משתמש בשרת Bot API מקומי: %s", API_BASE)
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML), **kw)
    me = await bot.get_me()
    log.info("GroupOS עלה כ-@%s · סכימה v%s", me.username, db.version)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
