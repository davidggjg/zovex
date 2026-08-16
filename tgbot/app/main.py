"""נקודת הכניסה — מרים את הבוט, מאתחל DB, ומריץ את בדיקת השבת מחזורית."""
import asyncio
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from pyrogram import Client

from . import bot, config, db, shabbat


async def _run():
    miss = config.missing()
    if miss:
        logger.error(f"חסרים משתני סביבה: {', '.join(miss)}")
        sys.exit(1)

    await db.init()
    logger.info("DB אותחל")

    app = Client(
        "zovex_bot",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        bot_token=config.BOT_TOKEN,
        workdir="/app/data",
    )
    bot.register(app)

    await app.start()
    me = await app.get_me()
    logger.info(f"הבוט מחובר: @{me.username} ({me.id})")

    # בדיקת שבת כל 5 דקות (חסין להפעלה-מחדש, מטפל בכניסה וביציאה)
    sched = AsyncIOScheduler(timezone=config.TIMEZONE)
    sched.add_job(shabbat.check_and_apply, "interval", minutes=5, args=[app],
                  id="shabbat", next_run_time=None)
    sched.start()
    # בדיקה ראשונה מיד (לא ממתינים 5 דקות אחרי הפעלה)
    asyncio.create_task(shabbat.check_and_apply(app))

    logger.info("ZOVEX bot רץ.")
    await asyncio.Event().wait()      # רץ עד הפסקה


def run():
    try:
        import uvloop
        uvloop.install()
    except Exception:
        pass
    asyncio.run(_run())


if __name__ == "__main__":
    run()
