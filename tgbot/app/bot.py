"""הבוט — חיפוש ושליחת תוכן, חיבור ערוצים באישור, ופקודות בעלים.

זרימת חיבור ערוץ (ספק מאושר)
----------------------------
1. הספק פותח ערוץ, מוסיף את הבוט כאדמין.
2. הבוט מזהה שנוסף → רושם את הערוץ כ'ממתין' → מודיע לבעלים.
3. בעלים מאשר (כפתור / דשבורד) → מאותו רגע כל פוסט חדש בערוץ נכנס לאינדקס.
4. משתמש מבקש שם → הבוט מחפש במאגר ZOVEX + בערוצים המאושרים → שולח קובץ.

שליחת הקובץ ב-copy_message → טלגרם מגיש את הבייטים, לא ה-VPS.
"""
from loguru import logger
from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from . import catalog, db
from .config import OWNER_IDS

MAX_RESULTS = 8
EPS_PER_PAGE = 8
_pick: dict = {}          # token → series_name (ל-callback_data קצר)
_seq = 0


def _is_owner(uid) -> bool:
    return uid in OWNER_IDS


def _tok(value) -> str:
    global _seq
    _seq = (_seq + 1) % 1000000
    t = f"{_seq:06d}"
    _pick[t] = value
    return t


def _title(item) -> str:
    return item.get("series_name") or item.get("title") or item.get("name") or "ללא שם"


def _cb_file(chat_id, message_id) -> str:
    return f"f:{chat_id}:{message_id}"


# ── שליחת קובץ ────────────────────────────────────────────────────────────────
async def _send(client, user_id, chat_id, message_id, status=None):
    try:
        await client.copy_message(chat_id=user_id, from_chat_id=chat_id, message_id=message_id)
        if status:
            await status.delete()
    except Exception as e:
        logger.error(f"copy_message נכשל ({chat_id}/{message_id}): {e}")
        txt = "😕 לא הצלחתי לשלוח את הקובץ (ייתכן שהבוט אינו חבר בערוץ, או שההודעה נמחקה)."
        await (status.edit(txt) if status else client.send_message(user_id, txt))


def register(app: Client, on_ready=None):
    """רושם את כל ההנדלרים על ה-Client."""

    # ── /start בפרטי ──────────────────────────────────────────────────────────
    @app.on_message(filters.command("start") & filters.private)
    async def start_cmd(client, m: Message):
        await db.touch_user(m.from_user.id, m.from_user.first_name)
        await m.reply(
            "🎬 **ZOVEX**\n\n"
            "כתוב לי שם של סרט או סדרה ואשלח לך את הקובץ ישירות לכאן.\n\n"
            "לדוגמה: `דרגון בול סופר`")

    # ── פקודות בעלים ──────────────────────────────────────────────────────────
    @app.on_message(filters.command(["pending", "ממתינים"]) & filters.private)
    async def pending_cmd(client, m: Message):
        if not _is_owner(m.from_user.id):
            return
        chans = await db.list_channels("pending")
        if not chans:
            return await m.reply("אין ערוצים שממתינים לאישור ✅")
        for ch in chans:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ אשר", callback_data=f"appr:{ch['chat_id']}"),
                InlineKeyboardButton("❌ דחה", callback_data=f"rej:{ch['chat_id']}"),
            ]])
            await m.reply(
                f"📡 **{ch['title']}**\nמאת: {ch['owner_name']} (`{ch['owner_id']}`)\n"
                f"מזהה: `{ch['chat_id']}`", reply_markup=kb)

    @app.on_message(filters.command(["shabbat", "שבת"]))
    async def shabbat_cmd(client, m: Message):
        from . import shabbat
        await m.reply(await shabbat.upcoming_text())

    # ── הבוט נוסף/הוסר מערוץ → רישום כ'ממתין' ──────────────────────────────────
    @app.on_chat_member_updated()
    async def member_update(client, upd):
        try:
            me = (await client.get_me()).id
            nm = upd.new_chat_member
            if not nm or nm.user.id != me:
                return
            chat = upd.chat
            if str(chat.type) not in ("ChatType.CHANNEL", "channel", "ChatType.SUPERGROUP", "supergroup"):
                return
            actor = upd.from_user
            await db.add_pending_channel(chat.id, chat.title, getattr(chat, "username", None),
                                         actor.id if actor else 0,
                                         actor.first_name if actor else "לא ידוע")
            for oid in OWNER_IDS:
                try:
                    kb = InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ אשר", callback_data=f"appr:{chat.id}"),
                        InlineKeyboardButton("❌ דחה", callback_data=f"rej:{chat.id}"),
                    ]])
                    await client.send_message(
                        oid,
                        f"📡 **בקשת חיבור ערוץ**\n\n**{chat.title}**\n"
                        f"מאת: {actor.first_name if actor else '?'} (`{actor.id if actor else '?'}`)\n"
                        f"מזהה: `{chat.id}`\n\nלאשר את חיבור הערוץ?", reply_markup=kb)
                except Exception:
                    pass
            logger.info(f"ערוץ ממתין לאישור: {chat.title} ({chat.id})")
        except Exception as e:
            logger.error(f"member_update נכשל: {e}")

    # ── פוסט חדש בערוץ מאושר → אינדקס ─────────────────────────────────────────
    @app.on_message(filters.channel & (filters.document | filters.video))
    async def channel_post(client, m: Message):
        if not await db.is_approved(m.chat.id):
            return
        name = (m.caption or "").strip().split("\n")[0]
        if not name:
            media = m.document or m.video
            name = getattr(media, "file_name", None) or "ללא שם"
        await db.index_content(m.chat.id, m.id, name, catalog.norm(name))
        logger.info(f"אינדקס: {name} ← {m.chat.title}")

    # ── חיפוש בפרטי (טקסט חופשי) ───────────────────────────────────────────────
    @app.on_message(filters.private & filters.text & ~filters.command([
        "start", "pending", "ממתינים", "shabbat", "שבת"]))
    async def search_text(client, m: Message):
        await db.touch_user(m.from_user.id, m.from_user.first_name)
        await _do_search(client, m, m.text)

    async def _do_search(client, m: Message, query: str):
        query = (query or "").strip()
        if len(query) < 2:
            return await m.reply("כתוב שם ארוך יותר 🙂")
        status = await m.reply("🔎 מחפש…")
        movies, series = await catalog.search(query)
        extra = await db.search_content(catalog.norm(query).split(), MAX_RESULTS)
        await db.log_request(m.from_user.id, query, bool(movies or series or extra))

        # תוצאה יחידה — שולחים מיד
        if len(movies) == 1 and not series and not extra:
            r = catalog.ref(movies[0])
            return await _send(client, m.chat.id, r[0], r[1], status)

        rows = []
        for mv in movies[:MAX_RESULTS]:
            r = catalog.ref(mv)
            if r:
                yr = f" ({mv.get('year')})" if mv.get("year") else ""
                rows.append([InlineKeyboardButton("🎬 " + _title(mv) + yr, callback_data=_cb_file(*r))])
        for e in extra:
            rows.append([InlineKeyboardButton("🎬 " + e["name"][:40],
                                              callback_data=_cb_file(e["chat_id"], e["message_id"]))])
        for s in series[:MAX_RESULTS]:
            rows.append([InlineKeyboardButton("📺 " + _title(s),
                                              callback_data="s:" + _tok(s.get("series_name")))])
        if not rows:
            return await status.edit(f"לא מצאתי כלום עבור **{query}** 😕")
        await status.edit(f"מצאתי {len(rows)} תוצאות עבור **{query}**:",
                          reply_markup=InlineKeyboardMarkup(rows))

    # ── כפתורים ────────────────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^f:(-?\d+):(\d+)$"))
    async def cb_file(client, cq: CallbackQuery):
        await cq.answer("שולח…")
        await _send(client, cq.from_user.id, int(cq.matches[0].group(1)), int(cq.matches[0].group(2)))

    @app.on_callback_query(filters.regex(r"^s:(\d+)$"))
    async def cb_series(client, cq: CallbackQuery):
        name = _pick.get(cq.matches[0].group(1))
        if not name:
            return await cq.answer("הבחירה פגה, חפש שוב 🙂", show_alert=True)
        await cq.answer()
        text, kb = await _series_view(name, cq.matches[0].group(1), 0)
        await cq.message.edit(text, reply_markup=kb)

    @app.on_callback_query(filters.regex(r"^sp:(\d+):(\d+)$"))
    async def cb_series_page(client, cq: CallbackQuery):
        name = _pick.get(cq.matches[0].group(1))
        if not name:
            return await cq.answer("הבחירה פגה, חפש שוב 🙂", show_alert=True)
        await cq.answer()
        text, kb = await _series_view(name, cq.matches[0].group(1), int(cq.matches[0].group(2)))
        await cq.message.edit(text, reply_markup=kb)

    @app.on_callback_query(filters.regex(r"^(appr|rej):(-?\d+)$"))
    async def cb_approve(client, cq: CallbackQuery):
        if not _is_owner(cq.from_user.id):
            return await cq.answer("רק בעלים 🙅", show_alert=True)
        action, chat_id = cq.matches[0].group(1), int(cq.matches[0].group(2))
        await db.set_channel_status(chat_id, "approved" if action == "appr" else "rejected")
        await cq.answer("אושר ✅" if action == "appr" else "נדחה ❌")
        await cq.message.edit(cq.message.text.markdown +
                              ("\n\n✅ **אושר**" if action == "appr" else "\n\n❌ **נדחה**"))

    logger.info("הנדלרים של הבוט נרשמו.")


async def _series_view(series_name: str, token: str, page: int):
    eps = await catalog.episodes(series_name)
    if not eps:
        return "לא נמצאו פרקים 😕", None
    pages = (len(eps) + EPS_PER_PAGE - 1) // EPS_PER_PAGE
    page = max(0, min(page, pages - 1))
    rows = []
    for e in eps[page * EPS_PER_PAGE:(page + 1) * EPS_PER_PAGE]:
        s, n = e.get("season_number"), e.get("episode_number")
        label = (f"עונה {s} · פרק {n}" if s else f"פרק {n}") if n else _title(e)
        r = catalog.ref(e)
        if r:
            rows.append([InlineKeyboardButton(label, callback_data=_cb_file(*r))])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ הקודם", callback_data=f"sp:{token}:{page-1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("הבא ▶", callback_data=f"sp:{token}:{page+1}"))
    if nav:
        rows.append(nav)
    return (f"📺 **{series_name}** — עמוד {page+1}/{pages} ({len(eps)} פרקים)",
            InlineKeyboardMarkup(rows))
