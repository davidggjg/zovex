"""
בדיקת ריבוי-בוטים: האם כמה בוטים *שונים* יכולים למשוך את אותו קובץ במקביל?

איך זה עובד: הבוטים עולים ומחכים שתפרסם קובץ *חדש* בערוץ בזמן שהם רצים —
כך כל בוט מקבל את ההודעה ו"מזהה" את הערוץ (בוט טרי לא מכיר ערוץ עד שהוא
מקבל ממנו הודעה חיה). אחרי שכולם קיבלו, מודדים בוט-אחד מול כל-הבוטים-במקביל.

קורא:
  - API_ID / API_HASH מתוך /opt/zovex-bot/.env
  - טוקנים מתוך /opt/zovex-bot/verify_bots.txt (טוקן בכל שורה)

הרצה:
  cd /opt/zovex-bot && ./venv/bin/python verify_multibot.py [mb]
ואז לפרסם סרטון לערוץ כשמתבקש.
"""
import asyncio
import sys
import time
from pathlib import Path
from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler

CHUNK = 1024 * 1024


def _read_env(path: str) -> dict:
    env = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


async def pull_band(client, msg, off_chunks, lim_chunks):
    total = 0
    async for ch in client.stream_media(msg, offset=off_chunks, limit=lim_chunks):
        total += len(ch)
    return total


async def main():
    mb = int(sys.argv[1]) if len(sys.argv) > 1 else 24

    env = _read_env("/opt/zovex-bot/.env")
    api_id = int(env["API_ID"])
    api_hash = env["API_HASH"]
    tokens = [t.strip() for t in Path("/opt/zovex-bot/verify_bots.txt").read_text().splitlines() if t.strip()]
    print(f"נטענו {len(tokens)} טוקנים של בוטים")

    clients = []
    got_msg = {}      # index -> Message
    events = []

    for i, tok in enumerate(tokens):
        c = Client(f"verify_{i}", api_id=api_id, api_hash=api_hash, bot_token=tok,
                   in_memory=True)   # no_updates=False (ברירת מחדל) — צריך לקבל עדכונים
        ev = asyncio.Event()

        async def handler(client, message, i=i, ev=ev):
            media = message.video or message.document or message.audio or message.video_note
            if media and not ev.is_set():
                got_msg[i] = message
                ev.set()

        c.add_handler(MessageHandler(handler, filters.channel))
        try:
            await c.start()
            clients.append(c)
            events.append(ev)
            print(f"✅ בוט {i} מחובר ומאזין")
        except Exception as e:
            print(f"❌ בוט {i} לא עלה: {e}")

    if not clients:
        print("אין בוטים פעילים — עצירה")
        return

    print("\n📤 עכשיו — פרסם/העלה סרטון *חדש* לערוץ (בזמן שהסקריפט רץ)...")
    print("   ממתין עד 180 שניות שכל הבוטים יקבלו אותו...")
    try:
        await asyncio.wait_for(asyncio.gather(*[ev.wait() for ev in events]), timeout=180)
    except asyncio.TimeoutError:
        got = len(got_msg)
        print(f"⏱️ קיבלו את ההודעה: {got}/{len(clients)} בוטים.")
        if got == 0:
            print("❌ אף בוט לא קיבל — כנראה שהבוטים אינם אדמינים בערוץ. הוסף אותם כאדמינים ונסה שוב.")
            for c in clients:
                await c.stop()
            return

    # רק בוטים שקיבלו את ההודעה משתתפים
    active = [(i, c) for i, c in enumerate(clients) if i in got_msg]
    media = None
    for i, _ in active:
        m = got_msg[i]
        media = m.video or m.document or m.audio or m.video_note
        break
    print(f"\n📄 קובץ: {getattr(media, 'file_name', '?')} | גודל: {media.file_size/1048576:.1f}MB")
    print(f"👥 בוטים שמזהים את הקובץ: {len(active)}")

    # ── בדיקה 1: בוט אחד ──
    idx0, c0 = active[0]
    t0 = time.time()
    b = await pull_band(c0, got_msg[idx0], 0, mb)
    dt = time.time() - t0
    print(f"\n▶️ בוט אחד: {b/1048576:.1f}MB ב-{dt:.1f}s = {b/dt/1048576:.2f} MB/s")

    # ── בדיקה 2: כל הבוטים במקביל ──
    n = len(active)
    per = (mb + n - 1) // n
    t0 = time.time()
    tasks = []
    for k in range(n):
        off = k * per
        if off >= mb:
            break
        lim = min(per, mb - off)
        idx, c = active[k]
        tasks.append(pull_band(c, got_msg[idx], off, lim))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    dt = time.time() - t0
    total = sum(r for r in results if isinstance(r, int))
    errs = [repr(r) for r in results if not isinstance(r, int)]
    print(f"🚀 {len(tasks)} בוטים במקביל: {total/1048576:.1f}MB ב-{dt:.1f}s = {total/dt/1048576:.2f} MB/s")
    if errs:
        print(f"   שגיאות: {errs}")

    for c in clients:
        try:
            await c.stop()
        except Exception:
            pass

    print("\n=== אם המקביל גבוה משמעותית מהיחיד → ריבוי בוטים עובד! ===")


if __name__ == "__main__":
    asyncio.run(main())
