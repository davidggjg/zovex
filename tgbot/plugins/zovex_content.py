"""פלאגין ZOVEX — חיפוש תוכן ושליחת קבצים בטלגרם.

איך זה עובד
-----------
· טוען את הקטלוג של האתר מ-/content/lite (מטמון, רענון כל כמה דקות).
· משתמש שולח שם של סרט/סדרה בפרטי לבוט (או /search בקבוצה) → הבוט מחפש.
· התאמה לסרט → שולח את הקובץ מיד עם copy_message.
· התאמה לסדרה → מציג כפתורים לעונות/פרקים, ובבחירה שולח את הפרק.

למה זה לא מעמיס על השרת
----------------------
copy_message אומר לטלגרם "העתק את ההודעה הזו למשתמש" — טלגרם שולח את הבייטים
מהשרתים שלו. הקובץ לא עובר דרך ה-VPS. כל מה שעובר זה קריאת API זעירה + משיכת
הקטלוג (~800KB) כל כמה דקות.

דורש
----
· משתני סביבה: ZOVEX_CONTENT_URL (ברירת מחדל https://zovex.duckdns.org/content/lite)
· הבוט חייב להיות חבר בערוץ האחסון שממנו מעתיקים (מזהה הערוץ מגיע מכל פריט).

הפלאגין נטען אוטומטית ע"י autodiscover של LEX (מספיק שהקובץ ב-src/plugins/).
"""
import asyncio
import os
import re
import time
from typing import Optional

import httpx
from loguru import logger
from pyrogram import filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.core.bot import bot
from src.core.plugin import Plugin, register
from src.utils.decorators import safe_handler

# ── הגדרות ────────────────────────────────────────────────────────────────────
CONTENT_URL = os.environ.get("ZOVEX_CONTENT_URL", "https://zovex.duckdns.org/content/lite")
CATALOG_TTL = int(os.environ.get("ZOVEX_CATALOG_TTL", "300"))     # רענון כל 5 דקות
MAX_RESULTS = 8                                                    # תוצאות חיפוש בכפתורים
STREAM_RE = re.compile(r"/stream/(-?\d+)/(\d+)")                   # chat_id + message_id מהקישור

# ── מטמון הקטלוג ──────────────────────────────────────────────────────────────
_catalog: list = []
_catalog_at: float = 0.0
_catalog_lock = asyncio.Lock()

# מטמון בחירות קצר-מועד: token → פריט. callback_data מוגבל ל-64 בתים ואי אפשר
# לדחוס לתוכו כותרת עברית, אז שומרים את הפריט ומעבירים רק אסימון קצר.
_picks: dict = {}
_PICK_TTL = 3600


def _norm(s) -> str:
    """נרמול חיפוש — זהה לאתר ולאפליקציה: ניקוד, גרשיים, רווחים."""
    s = "" if s is None else str(s)
    s = s.lower()
    s = re.sub(r"[֑-ׇ]", "", s)                          # ניקוד עברי
    s = re.sub(r"[\"'`׳״‘’“”]", "", s)  # גרשיים
    return re.sub(r"\s+", " ", s).strip()


async def _get_catalog() -> list:
    """הקטלוג, עם רענון לפי TTL. חסין למספר קוראים במקביל."""
    global _catalog, _catalog_at
    now = time.time()
    if _catalog and now - _catalog_at < CATALOG_TTL:
        return _catalog
    async with _catalog_lock:
        if _catalog and time.time() - _catalog_at < CATALOG_TTL:
            return _catalog
        try:
            async with httpx.AsyncClient(timeout=30) as cx:
                r = await cx.get(CONTENT_URL)
                r.raise_for_status()
                data = r.json()
            if isinstance(data, list) and data:
                for e in data:                                    # מפתח חיפוש מנורמל פעם אחת
                    e["_hay"] = _norm(" ".join(
                        str(e.get(k) or "") for k in
                        ("title", "name", "series_name", "en_title", "original_title")))
                _catalog = data
                _catalog_at = time.time()
                logger.info(f"ZOVEX: קטלוג נטען — {len(_catalog)} פריטים")
        except Exception as e:
            logger.error(f"ZOVEX: טעינת קטלוג נכשלה: {e}")
    return _catalog


def _ref(item) -> Optional[tuple]:
    """(chat_id, message_id) מתוך הקישור של הפריט, או None אם אין קובץ בטלגרם."""
    for k in ("video_url", "video_id"):
        m = STREAM_RE.search(str(item.get(k) or ""))
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def _store_pick(item) -> str:
    token = f"{int(time.time()*1000)%1000000:06d}"
    _picks[token] = (item, time.time())
    # ניקוי אסימונים ישנים כדי שהמילון לא יגדל בלי סוף
    cutoff = time.time() - _PICK_TTL
    for k in [k for k, (_, ts) in _picks.items() if ts < cutoff]:
        _picks.pop(k, None)
    return token


def _title_of(item) -> str:
    return item.get("series_name") or item.get("title") or item.get("name") or "ללא שם"


async def _send_file(client, user_id: int, item, status: Message = None):
    """שולח את הקובץ למשתמש עם copy_message. טלגרם מגיש את הבייטים, לא ה-VPS."""
    ref = _ref(item)
    if not ref:
        txt = "😕 לתוכן הזה אין קובץ שמור בטלגרם (הוא מוגש כשידור/קישור חיצוני)."
        return await (status.edit(txt) if status else client.send_message(user_id, txt))
    from_chat, msg_id = ref
    try:
        await client.copy_message(chat_id=user_id, from_chat_id=from_chat, message_id=msg_id)
        if status:
            await status.delete()
    except Exception as e:
        logger.error(f"ZOVEX: copy_message נכשל ({from_chat}/{msg_id}): {e}")
        txt = ("😕 לא הצלחתי לשלוח את הקובץ.\n"
               "ייתכן שהבוט אינו חבר בערוץ האחסון, או שההודעה נמחקה.")
        await (status.edit(txt) if status else client.send_message(user_id, txt))


def _episodes(catalog, series_name) -> list:
    eps = [e for e in catalog if e.get("series_name") == series_name and _ref(e)]
    eps.sort(key=lambda e: ((e.get("season_number") or 0), (e.get("episode_number") or 0)))
    return eps


async def _search(query: str) -> tuple:
    """מחזיר (movies, series_names). מפריד סרטים בודדים מסדרות."""
    toks = _norm(query).split()
    if not toks:
        return [], []
    catalog = await _get_catalog()
    movies, series = [], {}
    for e in catalog:
        if e.get("is_live"):
            continue
        hay = e.get("_hay") or ""
        if not all(t in hay for t in toks):
            continue
        sn = e.get("series_name")
        if sn:
            series.setdefault(sn, e)
        elif _ref(e):
            movies.append(e)
    return movies, list(series.values())


# ── פלאגין ────────────────────────────────────────────────────────────────────
class ZovexContentPlugin(Plugin):
    name = "zovex_content"
    priority = 60

    async def setup(self, client, ctx) -> None:
        asyncio.create_task(_get_catalog())      # חימום מוקדם, לא חוסם הפעלה


WELCOME = (
    "🎬 **ZOVEX**\n\n"
    "כתוב לי שם של סרט או סדרה — ואשלח לך את הקובץ ישירות לכאן.\n\n"
    "לדוגמה: `דרגון בול סופר`\n\n"
    "אפשר גם בקבוצה עם `/search <שם>`."
)


@bot.on_message(filters.command("start") & filters.private, group=1)
@safe_handler
async def zx_start(client, message: Message):
    await message.reply(WELCOME)


async def _handle_query(client, message: Message, query: str):
    query = (query or "").strip()
    if len(query) < 2:
        return await message.reply("כתוב שם ארוך יותר לחיפוש 🙂")
    status = await message.reply("🔎 מחפש…")
    movies, series = await _search(query)

    # תוצאה יחידה וברורה — שולחים מיד
    if len(movies) == 1 and not series:
        return await _send_file(client, message.chat.id, movies[0], status)

    results = []
    for m in movies[:MAX_RESULTS]:
        yr = f" ({m.get('year')})" if m.get("year") else ""
        results.append(("🎬 " + _title_of(m) + yr, "zx:m:" + _store_pick(m)))
    for s in series[:MAX_RESULTS]:
        results.append(("📺 " + _title_of(s), "zx:s:" + _store_pick(s)))

    if not results:
        return await status.edit(f"לא מצאתי כלום עבור **{query}** 😕\nנסה שם אחר או פחות מילים.")

    kb = InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d)] for t, d in results])
    await status.edit(f"מצאתי {len(results)} תוצאות עבור **{query}**:", reply_markup=kb)


@bot.on_message(filters.command("search"), group=1)
@safe_handler
async def zx_search_cmd(client, message: Message):
    query = " ".join(message.command[1:]) if len(message.command) > 1 else ""
    if not query:
        return await message.reply("שימוש: `/search שם הסרט`")
    await _handle_query(client, message, query)


# בפרטי — כל טקסט חופשי (שאינו פקודה) נחשב לחיפוש
@bot.on_message(filters.private & filters.text & ~filters.command([
    "start", "search", "help", "shabbat"]), group=5)
@safe_handler
async def zx_private_text(client, message: Message):
    await _handle_query(client, message, message.text)


@bot.on_callback_query(filters.regex(r"^zx:m:(\d+)$"), group=1)
@safe_handler
async def zx_pick_movie(client, callback: CallbackQuery):
    token = callback.matches[0].group(1)
    entry = _picks.get(token)
    if not entry:
        return await callback.answer("הבחירה פגה, חפש שוב 🙂", show_alert=True)
    await callback.answer("שולח…")
    await _send_file(client, callback.from_user.id, entry[0])


@bot.on_callback_query(filters.regex(r"^zx:s:(\d+)$"), group=1)
@safe_handler
async def zx_pick_series(client, callback: CallbackQuery):
    token = callback.matches[0].group(1)
    entry = _picks.get(token)
    if not entry:
        return await callback.answer("הבחירה פגה, חפש שוב 🙂", show_alert=True)
    series_name = entry[0].get("series_name")
    catalog = await _get_catalog()
    eps = _episodes(catalog, series_name)
    if not eps:
        return await callback.answer("לא נמצאו פרקים עם קובץ 😕", show_alert=True)
    await callback.answer()
    rows = []
    for e in eps[:40]:                    # עד 40 כפתורים; אם יותר — ראשונים
        s, n = e.get("season_number"), e.get("episode_number")
        label = (f"עונה {s} · פרק {n}" if s else f"פרק {n}") if n else _title_of(e)
        rows.append([InlineKeyboardButton(label, callback_data="zx:m:" + _store_pick(e))])
    more = f"\n\n(מוצגים {min(len(eps),40)} מתוך {len(eps)} פרקים)" if len(eps) > 40 else ""
    await callback.message.edit(
        f"📺 **{series_name}** — בחר פרק:{more}",
        reply_markup=InlineKeyboardMarkup(rows))


register(ZovexContentPlugin())
logger.info("ZOVEX Content Plugin registered.")
