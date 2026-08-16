"""מודרציה בסגנון Rose — פקודות ניהול קבוצה.

חסימה/השתקה (עם זמן), אזהרות עם ענישה אוטומטית, ניקוי, נעיצה, קידום,
חוקים, ברוכים הבאים, הערות (#שם), ופילטרים אוטומטיים.

כל פקודת ניהול דורשת שהשולח יהיה אדמין בקבוצה, ושלבוט יהיו ההרשאות.
"""
import re
from datetime import datetime, timedelta

from loguru import logger
from pyrogram import Client, filters
from pyrogram.enums import ChatMembersFilter, ChatMemberStatus, ChatType
from pyrogram.types import ChatPermissions, Message

from . import db

# ── עוזרים ────────────────────────────────────────────────────────────────────
_ADMIN = {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}
_MUTED = ChatPermissions(can_send_messages=False)
_UNMUTED = ChatPermissions(
    can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True,
    can_add_web_page_previews=True, can_send_polls=True)
_DUR = re.compile(r"^(\d+)\s*([smhdw])$", re.I)
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


async def _is_admin(client, chat_id, user_id) -> bool:
    try:
        m = await client.get_chat_member(chat_id, user_id)
        return m.status in _ADMIN
    except Exception:
        return False


def _parse_duration(text):
    """'1h'/'30m'/'2d' → שניות, או None (לצמיתות)."""
    m = _DUR.match((text or "").strip())
    return int(m.group(1)) * _UNITS[m.group(2).lower()] if m else None


async def _target(client, m: Message):
    """(user_id, name, rest_text) מהודעה: reply, @username, או id. rest = הסיבה."""
    args = (m.text or m.caption or "").split()[1:]
    if m.reply_to_message and m.reply_to_message.from_user:
        u = m.reply_to_message.from_user
        return u.id, u.first_name, " ".join(args)
    if args:
        ref = args[0]
        try:
            if ref.startswith("@") or not ref.lstrip("-").isdigit():
                u = await client.get_users(ref)
            else:
                u = await client.get_users(int(ref))
            return u.id, u.first_name, " ".join(args[1:])
        except Exception:
            return None, None, " ".join(args)
    return None, None, ""


def _mention(uid, name):
    return f"[{name or uid}](tg://user?id={uid})"


def register(app: Client):
    grp = filters.group

    async def guard(client, m: Message):
        """מחזיר True אם מותר להמשיך (אדמין בקבוצה)."""
        if not await _is_admin(client, m.chat.id, m.from_user.id):
            await m.reply("רק אדמינים יכולים להשתמש בפקודה הזו 🙅")
            return False
        return True

    # ── חסימה / הרחקה ─────────────────────────────────────────────────────────
    @app.on_message(filters.command(["ban", "חסום"]) & grp)
    async def ban(client, m: Message):
        if not await guard(client, m):
            return
        uid, name, reason = await _target(client, m)
        if not uid:
            return await m.reply("על מי? הגב להודעה שלו או ציין @שם.")
        try:
            await client.ban_chat_member(m.chat.id, uid)
            await m.reply(f"🔨 {_mention(uid, name)} נחסם." + (f"\nסיבה: {reason}" if reason else ""))
        except Exception as e:
            await m.reply(f"נכשל: {e}")

    @app.on_message(filters.command(["unban", "בטלחסימה"]) & grp)
    async def unban(client, m: Message):
        if not await guard(client, m):
            return
        uid, name, _ = await _target(client, m)
        if not uid:
            return await m.reply("על מי?")
        try:
            await client.unban_chat_member(m.chat.id, uid)
            await m.reply(f"✅ {_mention(uid, name)} שוחרר מחסימה.")
        except Exception as e:
            await m.reply(f"נכשל: {e}")

    @app.on_message(filters.command(["kick", "בעט"]) & grp)
    async def kick(client, m: Message):
        if not await guard(client, m):
            return
        uid, name, _ = await _target(client, m)
        if not uid:
            return await m.reply("על מי?")
        try:
            await client.ban_chat_member(m.chat.id, uid)
            await client.unban_chat_member(m.chat.id, uid)   # ban+unban = kick
            await m.reply(f"👢 {_mention(uid, name)} הורחק.")
        except Exception as e:
            await m.reply(f"נכשל: {e}")

    # ── השתקה (עם זמן) ─────────────────────────────────────────────────────────
    @app.on_message(filters.command(["mute", "השתק"]) & grp)
    async def mute(client, m: Message):
        if not await guard(client, m):
            return
        uid, name, rest = await _target(client, m)
        if not uid:
            return await m.reply("על מי? הגב להודעה שלו או ציין @שם. אפשר זמן: `/השתק 1h`")
        secs = _parse_duration(rest.split()[0]) if rest else None
        until = datetime.now() + timedelta(seconds=secs) if secs else datetime(1970, 1, 1)
        try:
            await client.restrict_chat_member(m.chat.id, uid, _MUTED, until_date=until)
            t = f" ל-{rest.split()[0]}" if secs else ""
            await m.reply(f"🔇 {_mention(uid, name)} הושתק{t}.")
        except Exception as e:
            await m.reply(f"נכשל: {e}")

    @app.on_message(filters.command(["unmute", "בטלהשתקה"]) & grp)
    async def unmute(client, m: Message):
        if not await guard(client, m):
            return
        uid, name, _ = await _target(client, m)
        if not uid:
            return await m.reply("על מי?")
        try:
            await client.restrict_chat_member(m.chat.id, uid, _UNMUTED)
            await m.reply(f"🔊 {_mention(uid, name)} שוחרר מהשתקה.")
        except Exception as e:
            await m.reply(f"נכשל: {e}")

    # ── אזהרות ─────────────────────────────────────────────────────────────────
    @app.on_message(filters.command(["warn", "אזהרה"]) & grp)
    async def warn(client, m: Message):
        if not await guard(client, m):
            return
        uid, name, reason = await _target(client, m)
        if not uid:
            return await m.reply("על מי? הגב להודעה שלו.")
        count = await db.add_warn(m.chat.id, uid, reason or "", m.from_user.id)
        st = await db.get_settings(m.chat.id)
        limit = st["warn_limit"]
        if count >= limit:
            action = st["warn_action"]
            try:
                if action == "ban":
                    await client.ban_chat_member(m.chat.id, uid)
                elif action == "kick":
                    await client.ban_chat_member(m.chat.id, uid)
                    await client.unban_chat_member(m.chat.id, uid)
                else:
                    await client.restrict_chat_member(m.chat.id, uid, _MUTED)
                await db.reset_warns(m.chat.id, uid)
                label = {"ban": "נחסם", "kick": "הורחק"}.get(action, "הושתק")
                await m.reply(f"⚠️ {_mention(uid, name)} הגיע ל-{limit} אזהרות → {label}.")
            except Exception as e:
                await m.reply(f"האזהרה נרשמה אבל הענישה נכשלה: {e}")
        else:
            await m.reply(f"⚠️ אזהרה ל-{_mention(uid, name)} ({count}/{limit})." +
                          (f"\nסיבה: {reason}" if reason else ""))

    @app.on_message(filters.command(["unwarn", "בטלאזהרה", "resetwarn"]) & grp)
    async def unwarn(client, m: Message):
        if not await guard(client, m):
            return
        uid, name, _ = await _target(client, m)
        if not uid:
            return await m.reply("על מי?")
        await db.reset_warns(m.chat.id, uid)
        await m.reply(f"✅ האזהרות של {_mention(uid, name)} אופסו.")

    @app.on_message(filters.command(["warns", "אזהרות"]) & grp)
    async def warns(client, m: Message):
        uid, name, _ = await _target(client, m)
        if not uid:
            uid, name = m.from_user.id, m.from_user.first_name
        c = await db.get_warns(m.chat.id, uid)
        st = await db.get_settings(m.chat.id)
        await m.reply(f"ל-{_mention(uid, name)} יש {c}/{st['warn_limit']} אזהרות.")

    @app.on_message(filters.command(["setwarnlimit"]) & grp)
    async def setwarnlimit(client, m: Message):
        if not await guard(client, m):
            return
        args = m.text.split()
        if len(args) < 2 or not args[1].isdigit():
            return await m.reply("שימוש: `/setwarnlimit 3`")
        await db.set_setting(m.chat.id, "warn_limit", int(args[1]))
        await m.reply(f"מגבלת האזהרות עודכנה ל-{args[1]}.")

    # ── ניקוי ──────────────────────────────────────────────────────────────────
    @app.on_message(filters.command(["purge", "נקה"]) & grp)
    async def purge(client, m: Message):
        if not await guard(client, m):
            return
        if not m.reply_to_message:
            return await m.reply("הגב להודעה שממנה להתחיל לנקות.")
        ids = list(range(m.reply_to_message.id, m.id + 1))
        try:
            await client.delete_messages(m.chat.id, ids)
            note = await client.send_message(m.chat.id, f"🧹 נמחקו {len(ids)} הודעות.")
            import asyncio
            await asyncio.sleep(3)
            await note.delete()
        except Exception as e:
            await m.reply(f"נכשל: {e}")

    @app.on_message(filters.command(["del", "מחק"]) & grp)
    async def delcmd(client, m: Message):
        if not await guard(client, m):
            return
        if m.reply_to_message:
            await client.delete_messages(m.chat.id, [m.reply_to_message.id, m.id])

    # ── נעיצה / קידום ──────────────────────────────────────────────────────────
    @app.on_message(filters.command(["pin", "הצמד"]) & grp)
    async def pin(client, m: Message):
        if not await guard(client, m):
            return
        if m.reply_to_message:
            await m.reply_to_message.pin()
            await m.reply("📌 הוצמד.")

    @app.on_message(filters.command(["unpin", "בטלהצמדה"]) & grp)
    async def unpin(client, m: Message):
        if not await guard(client, m):
            return
        if m.reply_to_message:
            await m.reply_to_message.unpin()
            await m.reply("הצמדה בוטלה.")

    @app.on_message(filters.command(["promote", "קדם"]) & grp)
    async def promote(client, m: Message):
        if not await guard(client, m):
            return
        uid, name, _ = await _target(client, m)
        if not uid:
            return await m.reply("על מי?")
        try:
            from pyrogram.types import ChatPrivileges
            await client.promote_chat_member(m.chat.id, uid, ChatPrivileges(
                can_delete_messages=True, can_restrict_members=True, can_pin_messages=True,
                can_invite_users=True))
            await m.reply(f"⭐ {_mention(uid, name)} קודם לאדמין.")
        except Exception as e:
            await m.reply(f"נכשל: {e}")

    @app.on_message(filters.command(["demote", "הורד"]) & grp)
    async def demote(client, m: Message):
        if not await guard(client, m):
            return
        uid, name, _ = await _target(client, m)
        if not uid:
            return await m.reply("על מי?")
        try:
            from pyrogram.types import ChatPrivileges
            await client.promote_chat_member(m.chat.id, uid, ChatPrivileges(
                can_manage_chat=False, can_delete_messages=False, can_restrict_members=False,
                can_pin_messages=False, can_invite_users=False, can_promote_members=False))
            await m.reply(f"{_mention(uid, name)} הורד מאדמין.")
        except Exception as e:
            await m.reply(f"נכשל: {e}")

    # ── מידע ────────────────────────────────────────────────────────────────────
    @app.on_message(filters.command(["id", "מזהה"]))
    async def idcmd(client, m: Message):
        if m.reply_to_message and m.reply_to_message.from_user:
            u = m.reply_to_message.from_user
            await m.reply(f"מזהה של {u.first_name}: `{u.id}`\nמזהה הצ'אט: `{m.chat.id}`")
        else:
            await m.reply(f"המזהה שלך: `{m.from_user.id}`\nמזהה הצ'אט: `{m.chat.id}`")

    @app.on_message(filters.command(["info", "מידע"]) & grp)
    async def info(client, m: Message):
        uid, name, _ = await _target(client, m)
        if not uid:
            uid, name = m.from_user.id, m.from_user.first_name
        c = await db.get_warns(m.chat.id, uid)
        admin = await _is_admin(client, m.chat.id, uid)
        await m.reply(f"👤 {_mention(uid, name)}\nמזהה: `{uid}`\n"
                      f"אדמין: {'כן' if admin else 'לא'}\nאזהרות: {c}")

    # ── חוקים / ברוכים הבאים ──────────────────────────────────────────────────
    @app.on_message(filters.command(["setrules", "הגדרחוקים"]) & grp)
    async def setrules(client, m: Message):
        if not await guard(client, m):
            return
        txt = m.text.split(None, 1)
        if len(txt) < 2:
            return await m.reply("שימוש: `/הגדרחוקים <הטקסט>`")
        await db.set_setting(m.chat.id, "rules", txt[1])
        await m.reply("החוקים עודכנו ✅")

    @app.on_message(filters.command(["rules", "חוקים"]) & grp)
    async def rules(client, m: Message):
        st = await db.get_settings(m.chat.id)
        await m.reply(st["rules"] or "לא הוגדרו חוקים לקבוצה עדיין.")

    @app.on_message(filters.command(["setwelcome", "הגדרברוכים"]) & grp)
    async def setwelcome(client, m: Message):
        if not await guard(client, m):
            return
        txt = m.text.split(None, 1)
        if len(txt) < 2:
            return await m.reply("שימוש: `/הגדרברוכים <טקסט>` (אפשר {name} לשם).")
        await db.set_setting(m.chat.id, "welcome", txt[1])
        await m.reply("הודעת הפתיחה עודכנה ✅")

    @app.on_message(filters.new_chat_members & grp)
    async def greet(client, m: Message):
        st = await db.get_settings(m.chat.id)
        if not st["welcome"]:
            return
        for u in m.new_chat_members:
            if u.is_bot:
                continue
            try:
                await m.reply(st["welcome"].replace("{name}", _mention(u.id, u.first_name)))
            except Exception:
                pass

    # ── הערות (#שם) ────────────────────────────────────────────────────────────
    @app.on_message(filters.command(["save", "שמור"]) & grp)
    async def save_note(client, m: Message):
        if not await guard(client, m):
            return
        args = m.text.split(None, 2)
        if len(args) < 2:
            return await m.reply("שימוש: `/שמור שם <תוכן>` או הגב להודעה עם `/שמור שם`.")
        name = args[1]
        if m.reply_to_message:
            r = m.reply_to_message
            content = r.text or r.caption or ""
            file_id = file_type = None
            if r.document:
                file_id, file_type = r.document.file_id, "document"
            elif r.video:
                file_id, file_type = r.video.file_id, "video"
            elif r.photo:
                file_id, file_type = r.photo.file_id, "photo"
            await db.save_note(m.chat.id, name, content, file_id, file_type)
        else:
            if len(args) < 3:
                return await m.reply("צריך תוכן: `/שמור שם התוכן`.")
            await db.save_note(m.chat.id, name, args[2])
        await m.reply(f"נשמרה הערה `{name}`. שלוף עם `#{name}` או `/get {name}`.")

    @app.on_message(filters.command(["get"]) & grp)
    async def get_note_cmd(client, m: Message):
        args = m.text.split(None, 1)
        if len(args) < 2:
            return await m.reply("שימוש: `/get שם`")
        await _send_note(client, m, args[1])

    @app.on_message(filters.command(["notes", "הערות"]) & grp)
    async def notes_list(client, m: Message):
        names = await db.list_notes(m.chat.id)
        await m.reply("📝 הערות שמורות:\n" + "\n".join(f"· `#{n}`" for n in names)
                      if names else "אין הערות שמורות.")

    @app.on_message(filters.command(["clear", "מחקהערה"]) & grp)
    async def clear_note(client, m: Message):
        if not await guard(client, m):
            return
        args = m.text.split(None, 1)
        if len(args) < 2:
            return await m.reply("שימוש: `/מחקהערה שם`")
        await db.del_note(m.chat.id, args[1])
        await m.reply(f"ההערה `{args[1]}` נמחקה.")

    @app.on_message(filters.regex(r"^#(\w+)") & grp)
    async def hashtag_note(client, m: Message):
        await _send_note(client, m, m.matches[0].group(1))

    async def _send_note(client, m, name):
        note = await db.get_note(m.chat.id, name)
        if not note:
            return
        if note["file_id"]:
            send = {"document": client.send_document, "video": client.send_video,
                    "photo": client.send_photo}.get(note["file_type"])
            if send:
                return await send(m.chat.id, note["file_id"], caption=note["content"] or None)
        if note["content"]:
            await m.reply(note["content"])

    # ── פילטרים (תגובה אוטומטית) ───────────────────────────────────────────────
    @app.on_message(filters.command(["filter", "פילטר"]) & grp)
    async def add_filter_cmd(client, m: Message):
        if not await guard(client, m):
            return
        args = m.text.split(None, 2)
        if len(args) < 2:
            return await m.reply("שימוש: `/פילטר מילה <תגובה>` או הגב להודעה עם `/פילטר מילה`.")
        trigger = args[1]
        if m.reply_to_message and (m.reply_to_message.text or m.reply_to_message.caption):
            reply = m.reply_to_message.text or m.reply_to_message.caption
        elif len(args) >= 3:
            reply = args[2]
        else:
            return await m.reply("צריך תוכן לתגובה, או הגב להודעה.")
        await db.add_filter(m.chat.id, trigger, reply)
        await m.reply(f"נוסף פילטר על `{trigger}` ✅")

    @app.on_message(filters.command(["stop", "עצור"]) & grp)
    async def stop_filter_cmd(client, m: Message):
        if not await guard(client, m):
            return
        args = m.text.split(None, 1)
        if len(args) < 2:
            return await m.reply("שימוש: `/עצור מילה`")
        ok = await db.del_filter(m.chat.id, args[1])
        await m.reply(f"הפילטר `{args[1]}` הוסר." if ok else "אין פילטר כזה.")

    @app.on_message(filters.command(["filters", "פילטרים"]) & grp)
    async def list_filters_cmd(client, m: Message):
        names = await db.list_filters(m.chat.id)
        await m.reply("🧩 פילטרים פעילים:\n" + "\n".join(f"· `{n}`" for n in names)
                      if names else "אין פילטרים פעילים.")

    @app.on_message(filters.text & grp, group=7)
    async def filter_watch(client, m: Message):
        if not m.text or m.text.startswith("/"):
            return
        flt = await db.get_filters(m.chat.id)
        if not flt:
            return
        # מילה בודדת → התאמת גבול-מילה; ביטוי עם רווח → התאמת תת-מחרוזת.
        low = m.text.lower()
        words = set(re.split(r"[\s,.!?;:()\[\]\"'־-]+", low))
        for trigger, reply in flt:
            t = trigger.lower()
            hit = (t in low) if " " in t else (t in words)
            if hit:
                try:
                    await m.reply(reply)
                except Exception:
                    pass
                break

    # ── דיווח לאדמינים ──────────────────────────────────────────────────────────
    @app.on_message(filters.command(["report", "דווח", "דיווח"]) & grp)
    async def report(client, m: Message):
        if not m.reply_to_message:
            return await m.reply("הגב להודעה כדי לדווח עליה לאדמינים.")
        target = m.reply_to_message.from_user
        pings = []
        try:
            async for adm in client.get_chat_members(
                    m.chat.id, filter=ChatMembersFilter.ADMINISTRATORS):
                if adm.user and not adm.user.is_bot:
                    pings.append(f"[⁣](tg://user?id={adm.user.id})")
        except Exception:
            pass
        who = _mention(target.id, target.first_name) if target else "המשתמש"
        await m.reply_to_message.reply(
            f"🚨 **דיווח לאדמינים** על {who}\nמדווח: {_mention(m.from_user.id, m.from_user.first_name)}"
            + "".join(pings[:20]))

    # ── חסימה זמנית ─────────────────────────────────────────────────────────────
    @app.on_message(filters.command(["tban", "חסוםזמני"]) & grp)
    async def tban(client, m: Message):
        if not await guard(client, m):
            return
        uid, name, rest = await _target(client, m)
        if not uid:
            return await m.reply("על מי? הגב + זמן: `/חסוםזמני 1d`")
        secs = _parse_duration(rest.split()[0]) if rest else None
        if not secs:
            return await m.reply("צריך זמן: `1h` `2d` `1w`.")
        try:
            await client.ban_chat_member(
                m.chat.id, uid, until_date=datetime.now() + timedelta(seconds=secs))
            await m.reply(f"🔨 {_mention(uid, name)} נחסם ל-{rest.split()[0]}.")
        except Exception as e:
            await m.reply(f"נכשל: {e}")

    # ── עזרה ────────────────────────────────────────────────────────────────────
    @app.on_message(filters.command(["help", "עזרה", "פקודות"]))
    async def help_cmd(client, m: Message):
        if m.chat.type != ChatType.PRIVATE and not await _is_admin(client, m.chat.id, m.from_user.id):
            return
        await m.reply(
            "🛡️ **פקודות ניהול**\n\n"
            "**מודרציה:** `/חסום` `/בטלחסימה` `/בעט` `/השתק [זמן]` `/בטלהשתקה` `/חסוםזמני זמן`\n"
            "**אזהרות:** `/אזהרה` `/בטלאזהרה` `/אזהרות` `/setwarnlimit`\n"
            "**ניקוי:** `/נקה` (הגב) · `/מחק` (הגב)\n"
            "**ניהול:** `/הצמד` `/בטלהצמדה` `/קדם` `/הורד`\n"
            "**מידע:** `/מזהה` `/מידע` · `/דווח` (הגב — קורא לאדמינים)\n"
            "**הגדרות:** `/חוקים` `/הגדרחוקים` `/הגדרברוכים`\n"
            "**הערות:** `/שמור שם` `#שם` `/הערות` `/מחקהערה`\n"
            "**פילטרים:** `/פילטר מילה תגובה` `/עצור מילה` `/פילטרים`\n"
            "**שבת:** `/שבת`\n\n"
            "זמן: `1h` `30m` `2d` `1w`. רוב הפקודות: הגב להודעה או ציין @שם.")

    logger.info("מודול המודרציה נרשם.")
