"""שבת וחג — נעילת הקבוצה בכניסה, שחרור ביציאה, והודעת זמנים.

עובד לפי בדיקה תקופתית (כל 5 דק') במקום תזמון מדויק — חסין להפעלה-מחדש
ולשעון-קיץ. אם עכשיו בתוך חלון השבת/חג והקבוצה פתוחה → נועל ומכריז; אם
מחוץ לחלון והקבוצה נעולה → פותח ומכריז. hebcal מטפל גם בחגים.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from loguru import logger
from pyrogram.types import ChatPermissions

from .config import MANAGED_GROUP_ID, TIMEZONE

_locked = False          # מצב אחרון שידוע לנו, כדי להכריז רק במעבר

_OPEN = ChatPermissions(
    can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True,
    can_add_web_page_previews=True, can_send_polls=True)
_CLOSED = ChatPermissions(can_send_messages=False)


async def _shabbat_window():
    """(start, end, is_holiday) לחלון השבת/חג הרלוונטי, או (None, None, False)."""
    try:
        from hebcal_api import ShabbatRequest, fetch_shabbat_async
        city = TIMEZONE.split("/")[-1].replace("_", " ")
        resp = await fetch_shabbat_async(ShabbatRequest(city=city, tzid=TIMEZONE, c="on", s="on"))
        tz = ZoneInfo(TIMEZONE)
        start = end = None
        is_holiday = False
        for item in getattr(resp, "items", resp) or []:
            cat = getattr(item, "category", None) or (item.get("category") if isinstance(item, dict) else None)
            date = getattr(item, "date", None) or (item.get("date") if isinstance(item, dict) else None)
            if not date:
                continue
            dt = datetime.fromisoformat(str(date))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            if cat == "candles":
                start = dt
            elif cat == "havdalah":
                end = dt
            elif cat == "holiday":
                is_holiday = True
        return start, end, is_holiday
    except Exception as e:
        logger.error(f"שבת: חישוב זמנים נכשל: {e}")
        return None, None, False


async def check_and_apply(client):
    """נקרא מחזורית. נועל/פותח את הקבוצה לפי חלון השבת, ומכריז במעבר."""
    global _locked
    if not MANAGED_GROUP_ID:
        return
    start, end, is_holiday = await _shabbat_window()
    if not start or not end:
        return
    now = datetime.now(ZoneInfo(TIMEZONE))
    in_window = start <= now <= end
    fmt = "%H:%M"
    label = "החג" if is_holiday else "השבת"

    if in_window and not _locked:
        try:
            await client.set_chat_permissions(MANAGED_GROUP_ID, _CLOSED)
            await client.send_message(
                MANAGED_GROUP_ID,
                f"🕯️ **כניסת {label}**\nהקבוצה ננעלת. שבת שלום! 🌸\n"
                f"יציאה משוערת: {end.strftime(fmt)}")
            _locked = True
            logger.info("שבת: הקבוצה ננעלה")
        except Exception as e:
            logger.error(f"שבת: נעילה נכשלה: {e}")

    elif not in_window and _locked:
        try:
            await client.set_chat_permissions(MANAGED_GROUP_ID, _OPEN)
            await client.send_message(
                MANAGED_GROUP_ID,
                f"✨ **צאת {label}**\nהקבוצה נפתחה מחדש. שבוע טוב! 🙏")
            _locked = False
            logger.info("שבת: הקבוצה נפתחה")
        except Exception as e:
            logger.error(f"שבת: שחרור נכשל: {e}")


async def upcoming_text() -> str:
    """טקסט לפקודת /שבת — מתי כניסת/צאת השבת הקרובה."""
    start, end, is_holiday = await _shabbat_window()
    if not start or not end:
        return "לא הצלחתי לחשב את זמני השבת כרגע 🙁"
    label = "החג" if is_holiday else "השבת"
    return (f"🕯️ **זמני {label}**\n"
            f"כניסה: {start.strftime('%d/%m %H:%M')}\n"
            f"יציאה: {end.strftime('%d/%m %H:%M')}")
