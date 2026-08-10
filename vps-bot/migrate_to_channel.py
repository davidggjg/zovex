"""
מיגרציה: מעביר את כל הקבצים מהצ'אטים הפרטיים של הבוט הישן אל הערוץ המשותף,
ומייצר movies.json מעודכן עם קישורים חדשים (‎/stream/<channel>/<msg>).

- משתמש בבוט הישן (BOT_TOKEN מ-.env) שיש לו גישה לקבצים המקוריים.
- copy_message מעביר את הקובץ עצמו (בלי הורדה מחדש) — מהיר.
- checkpoint לחידוש: אם נעצר באמצע, מריצים שוב והוא ממשיך מאיפה שהפסיק.
- מטפל ב-FloodWait (המתנה) ומגביל קצב כדי לא להיחסם.

הרצה (מומלץ קודם בקטן):
  cd /opt/zovex-bot && ./venv/bin/python migrate_to_channel.py --limit 10
ואז את הכל:
  cd /opt/zovex-bot && ./venv/bin/python migrate_to_channel.py

פלט:
  /opt/zovex-bot/movies_migrated.json   — movies.json מעודכן
  /opt/zovex-bot/migration_progress.json — checkpoint (chat:msg -> new_id)
"""
import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from pyrogram import Client
from pyrogram.errors import FloodWait

DATA_DIR = Path("/opt/zovex-bot")
PROGRESS_FILE = DATA_DIR / "migration_progress.json"
OUT_FILE = DATA_DIR / "movies_migrated.json"
MOVIES_URL = "https://raw.githubusercontent.com/davidggjg/zovex/main/public/movies.json"

# מזהה הבוט הישן ב-URL (רק קישורים כאלה מוגרים)
OLD_HOST_RE = re.compile(r"https?://[^/]*hf\.space/stream/(-?\d+)/(\d+)")

# בסיס לקישורים החדשים — הכתובת של השרת. יוחלף לדומיין בעתיד (sed פשוט).
NEW_BASE = "http://213.139.78.39"

# קצב: השהיה בין העברות כדי לא להיחסם (שניות)
DELAY_BETWEEN = 0.7


def _read_env(path):
    env = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def load_progress():
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_progress(p):
    PROGRESS_FILE.write_text(json.dumps(p, ensure_ascii=False))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="הגבל למספר קבצים (0=הכל)")
    args = ap.parse_args()

    env = _read_env(DATA_DIR / ".env")
    api_id = int(env["API_ID"])
    api_hash = env["API_HASH"]
    bot_token = env["BOT_TOKEN"]
    channel = int(env["STREAM_CHANNEL_ID"])
    print(f"ערוץ יעד: {channel}")

    # מקור התוכן: movies.json המקורי (קישורי hf.space)
    import urllib.request
    print("מוריד את movies.json המקורי...")
    data = json.loads(urllib.request.urlopen(MOVIES_URL, timeout=60).read().decode())
    print(f"נטענו {len(data)} רשומות")

    progress = load_progress()
    print(f"checkpoint קיים: {len(progress)} כבר הועברו")

    old_bot = Client("migrate_old_bot", api_id=api_id, api_hash=api_hash,
                     bot_token=bot_token, in_memory=True, no_updates=True)
    await old_bot.start()
    print("✅ הבוט הישן מחובר")

    migrated = 0
    failed = 0
    skipped = 0
    processed = 0

    for entry in data:
        url = entry.get("video_url") or entry.get("video_id") or ""
        m = OLD_HOST_RE.search(url)
        if not m:
            continue   # לא קישור טלגרם ישן — משאירים כמו שהוא
        old_chat, old_msg = int(m.group(1)), int(m.group(2))
        key = f"{old_chat}:{old_msg}"

        if key in progress:
            new_id = progress[key]
            skipped += 1
        else:
            # מגבלת --limit חלה רק על העברות *חדשות*
            if args.limit and migrated >= args.limit:
                continue
            try:
                res = await old_bot.copy_message(
                    chat_id=channel, from_chat_id=old_chat, message_id=old_msg)
                new_id = res.id
                progress[key] = new_id
                migrated += 1
                if migrated % 20 == 0:
                    save_progress(progress)
                    print(f"  ...הועברו {migrated} (אחרון: {key} -> {new_id})")
                await asyncio.sleep(DELAY_BETWEEN)
            except FloodWait as e:
                print(f"⏳ FloodWait {e.value}s — ממתין...")
                save_progress(progress)
                await asyncio.sleep(e.value + 1)
                try:
                    res = await old_bot.copy_message(
                        chat_id=channel, from_chat_id=old_chat, message_id=old_msg)
                    new_id = res.id
                    progress[key] = new_id
                    migrated += 1
                except Exception as e2:
                    print(f"❌ {key} נכשל אחרי FloodWait: {e2}")
                    failed += 1
                    continue
            except Exception as e:
                print(f"❌ {key} נכשל: {e}")
                failed += 1
                continue

        # עדכון הקישור ברשומה
        new_url = f"{NEW_BASE}/stream/{channel}/{new_id}"
        entry["video_url"] = new_url
        entry["video_id"] = new_url
        processed += 1

    save_progress(progress)
    OUT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    await old_bot.stop()

    print("\n=== סיכום מיגרציה ===")
    print(f"הועברו עכשיו: {migrated}")
    print(f"כבר היו (checkpoint): {skipped}")
    print(f"נכשלו: {failed}")
    print(f"רשומות שעודכנו: {processed}")
    print(f"📄 נשמר: {OUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
