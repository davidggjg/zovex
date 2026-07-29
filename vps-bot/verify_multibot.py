"""
בדיקת ריבוי-בוטים: האם טלגרם מאפשר לכמה בוטים *שונים* למשוך את אותו קובץ
במקביל (בניגוד לבוט אחד, שטלגרם חוסם לו משיכה מקבילה)?

קורא:
  - API_ID / API_HASH מתוך /opt/zovex-bot/.env
  - טוקנים של הבוטים מתוך /opt/zovex-bot/verify_bots.txt (טוקן בכל שורה)

הרצה:
  ./venv/bin/python verify_multibot.py <channel_id> <message_id> [mb]
דוגמה:
  ./venv/bin/python verify_multibot.py -1002334455667 5 24
"""
import asyncio
import sys
import time
from pathlib import Path
from pyrogram import Client

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
    """מושך רצועה (lim_chunks חתיכות של 1MB מ-off_chunks) ומחזיר כמה בייטים נמשכו."""
    total = 0
    async for ch in client.stream_media(msg, offset=off_chunks, limit=lim_chunks):
        total += len(ch)
    return total


async def main():
    if len(sys.argv) < 3:
        print("שימוש: verify_multibot.py <channel_id> <message_id> [mb]")
        return
    channel = int(sys.argv[1])
    msg_id = int(sys.argv[2])
    mb = int(sys.argv[3]) if len(sys.argv) > 3 else 24

    env = _read_env("/opt/zovex-bot/.env")
    api_id = int(env["API_ID"])
    api_hash = env["API_HASH"]
    tokens = [t.strip() for t in Path("/opt/zovex-bot/verify_bots.txt").read_text().splitlines() if t.strip()]
    print(f"נטענו {len(tokens)} טוקנים של בוטים")

    clients = []
    for i, tok in enumerate(tokens):
        c = Client(f"verify_{i}", api_id=api_id, api_hash=api_hash, bot_token=tok,
                   in_memory=True, no_updates=True)
        try:
            await c.start()
            # פתרון ה-peer של הערוץ (דורש שהבוט אדמין בערוץ)
            try:
                await c.get_chat(channel)
            except Exception as e:
                print(f"⚠️ בוט {i}: get_chat נכשל ({e}) — יתכן שאינו אדמין בערוץ")
            clients.append(c)
            print(f"✅ בוט {i} מחובר")
        except Exception as e:
            print(f"❌ בוט {i} לא עלה: {e}")

    if not clients:
        print("אין בוטים פעילים — עצירה")
        return

    # פתרון ההודעה + גודל הקובץ
    try:
        msg0 = await clients[0].get_messages(channel, msg_id)
        media = msg0.video or msg0.document or msg0.audio or msg0.video_note
        if not media:
            print("❌ ההודעה לא מכילה מדיה")
            return
        print(f"📄 קובץ: {getattr(media, 'file_name', '?')} | גודל: {media.file_size/1048576:.1f}MB")
    except Exception as e:
        print(f"❌ get_messages נכשל: {e}")
        return

    # ── בדיקה 1: בוט אחד ──
    t0 = time.time()
    b = await pull_band(clients[0], msg0, 0, mb)
    dt = time.time() - t0
    print(f"\n▶️ בוט אחד: {b/1048576:.1f}MB ב-{dt:.1f}s = {b/dt/1048576:.2f} MB/s")

    # ── בדיקה 2: כל הבוטים במקביל ──
    n = len(clients)
    per = (mb + n - 1) // n
    # לכל בוט ה-msg שלו (כל אחד פותר בעצמו)
    msgs = []
    for c in clients:
        try:
            msgs.append(await c.get_messages(channel, msg_id))
        except Exception as e:
            print(f"⚠️ בוט לא הצליח לפתור הודעה: {e}")
            msgs.append(msg0)
    t0 = time.time()
    tasks = []
    for i in range(n):
        off = i * per
        if off >= mb:
            break
        lim = min(per, mb - off)
        tasks.append(pull_band(clients[i], msgs[i], off, lim))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    dt = time.time() - t0
    got = sum(r for r in results if isinstance(r, int))
    errs = [repr(r) for r in results if not isinstance(r, int)]
    print(f"🚀 {len(tasks)} בוטים במקביל: {got/1048576:.1f}MB ב-{dt:.1f}s = {got/dt/1048576:.2f} MB/s")
    if errs:
        print(f"   שגיאות: {errs}")

    for c in clients:
        try:
            await c.stop()
        except Exception:
            pass

    print("\n=== סיכום: אם המקביל גבוה משמעותית מהיחיד → ריבוי בוטים עובד! ===")


if __name__ == "__main__":
    asyncio.run(main())
