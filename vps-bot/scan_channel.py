"""סורק את ערוץ התוכן ומוצא קבצים שקיימים בטלגרם אבל חסרים בקטלוג.

למה זה קיים: תוכן נעלם מהאתר, והקבצים עצמם עדיין יושבים בערוץ. הכלי הזה
משווה בין מה שיש בערוץ למה שרשום ב-content.json לפי מזהה ההודעה, ומדווח מה
חסר — ובאישור מפורש גם מוסיף אותו בחזרה.

חשוב: בוטים לא יכולים לקרוא היסטוריה של ערוץ (BOT_METHOD_INVALID), ולכן
הכלי משתמש ב-session string של חשבון משתמש מתוך stream_bots.txt.

    python3 scan_channel.py --query "דרגון בול"     # מה חסר (בלי לשנות כלום)
    python3 scan_channel.py                          # כל מה שחסר בערוץ
    python3 scan_channel.py --query "דרגון בול" --add  # מוסיף בפועל
"""
import argparse, asyncio, json, os, pathlib, re, sys, uuid
from datetime import datetime

sys.path.insert(0, "/opt/zovex-bot")
DATA = pathlib.Path("/opt/zovex-bot/data")
CONTENT = DATA / "content.json"
BASE_TOKEN = "%BASE%"

ap = argparse.ArgumentParser()
ap.add_argument("--query", default="", help="סינון לפי טקסט בשם/כיתוב")
ap.add_argument("--add", action="store_true", help="להוסיף בפועל לקטלוג")
ap.add_argument("--category", default="אנימה", help="קטגוריה לפריטים חדשים")
ap.add_argument("--limit", type=int, default=0, help="לעצור אחרי N הודעות (0=הכל)")
args = ap.parse_args()

# main.py דורש משתני סביבה שמוגדרים ב-.env, ואותו קובץ נטען רק ע"י systemd.
# בהרצה ידנית מהטרמינל הם חסרים ו-main נופל בייבוא, ולכן טוענים אותם כאן.
ENV_FILE = pathlib.Path("/opt/zovex-bot/.env")
_loaded = 0
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip().lstrip("﻿")
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if k:
            os.environ[k] = v
            _loaded += 1
    print(f"נטענו {_loaded} משתנים מ-{ENV_FILE}")
else:
    print(f"⚠️  {ENV_FILE} לא נמצא")
for _k in ("API_ID", "API_HASH", "BOT_TOKEN"):
    if not os.environ.get(_k):
        print(f"⚠️  {_k} עדיין חסר אחרי הטעינה")

from pyrogram import Client
from main import (API_ID, API_HASH, STREAM_CHANNEL_ID, STREAM_BOTS_FILE,
                  parse_episode_info, clean_name, _slug_base)

# הנתיב מגיע מ-main ולא מניחוש: הקובץ יושב ב-/opt/zovex-bot/ ולא בתוך data/,
# וניחוש שגוי כאן נראה בדיוק כמו "אין חשבון משתמש בבריכה".
BOTS_FILE = STREAM_BOTS_FILE


def load_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def known_message_ids(content):
    """מזהי ההודעות שכבר רשומים בקטלוג."""
    ids = set()
    for e in content:
        for k in ("video_url", "video_id"):
            v = e.get(k)
            if isinstance(v, str):
                m = re.search(r"/stream/(-?\d+)/(\d+)", v)
                if m:
                    ids.add(int(m.group(2)))
    return ids


def pick_user_session():
    """בוטים לא יכולים לקרוא היסטוריה — צריך session string של חשבון."""
    if not BOTS_FILE.exists():
        return None
    bots = users = 0
    found = None
    for line in BOTS_FILE.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if not t:
            continue
        if re.match(r"^\d{5,}:[A-Za-z0-9_-]{20,}$", t):
            bots += 1
        elif len(t) >= 80:
            users += 1
            found = found or t
    print(f"ב-{BOTS_FILE.name}: {bots} בוטים, {users} חשבונות משתמש")
    return found


async def main():
    content = load_json(CONTENT, [])
    known = known_message_ids(content)
    print(f"בקטלוג: {len(content)} פריטים, {len(known)} מהם מקושרים להודעה בערוץ")

    sess = pick_user_session()
    if not sess:
        print("❌ אין session string של חשבון משתמש ב-stream_bots.txt.")
        print("   בוטים לא יכולים לקרוא היסטוריית ערוץ, אז אי אפשר לסרוק בלי אחד.")
        return 1

    q = args.query.strip().lower()
    app = Client("scan_channel_tmp", api_id=API_ID, api_hash=API_HASH,
                 session_string=sess, in_memory=True, no_updates=True)
    await app.start()

    # סשן טרי לא מכיר את הערוץ: טלגרם דורש access_hash לכל peer, והוא נלמד רק
    # מרשימת הצ'אטים. בלי זה כל פנייה נכשלת ב-"Peer id invalid" גם כשהחשבון
    # חבר בערוץ. מעבר על הדיאלוגים ממלא את המטמון.
    peer = None
    try:
        peer = await app.get_chat(STREAM_CHANNEL_ID)
    except Exception:
        print("מזהה את הערוץ דרך רשימת הצ'אטים...")
        async for _d in app.get_dialogs():
            pass
        try:
            peer = await app.get_chat(STREAM_CHANNEL_ID)
        except Exception as e:
            print(f"❌ החשבון לא מצליח לגשת לערוץ {STREAM_CHANNEL_ID}: {e}")
            print("   ודא שהחשבון הזה חבר בערוץ התוכן.")
            await app.stop()
            return 1
    print(f"ערוץ: {getattr(peer, 'title', STREAM_CHANNEL_ID)}")

    found, seen = [], 0
    try:
        async for m in app.get_chat_history(STREAM_CHANNEL_ID):
            seen += 1
            if args.limit and seen > args.limit:
                break
            if seen % 2000 == 0:
                print(f"  נסרקו {seen} הודעות, נמצאו {len(found)} חסרים...")
            media = m.video or m.document or m.audio
            if not media:
                continue
            name = getattr(media, "file_name", "") or ""
            text = f"{name} {m.caption or ''}".strip()
            if q and q not in text.lower():
                continue
            if m.id in known:
                continue
            found.append({"msg_id": m.id, "name": name, "caption": (m.caption or "")[:120],
                          "size": getattr(media, "file_size", 0)})
    finally:
        await app.stop()

    print(f"\nנסרקו {seen} הודעות. חסרים בקטלוג: {len(found)}\n")
    if not found:
        print("אין מה להוסיף.")
        return 0

    for f in found[:40]:
        print(f"  msg {f['msg_id']:>7}  {(f['name'] or f['caption'])[:70]}")
    if len(found) > 40:
        print(f"  ... ועוד {len(found) - 40}")

    if not args.add:
        print("\nהרצה יבשה — לא שונה כלום. להוספה בפועל הוסף --add")
        return 0

    added = 0
    for f in found:
        label = f["name"] or f["caption"]
        ep = parse_episode_info(label)
        url = f"{BASE_TOKEN}/stream/{STREAM_CHANNEL_ID}/{f['msg_id']}"
        base = {
            "video_url": url, "video_id": None, "thumbnail_url": "",
            "category": args.category, "is_live": False, "type": None,
            "episode_title": None, "year": None, "description": "",
            "id": str(uuid.uuid4()),
            "created_date": datetime.utcnow().isoformat() + "Z",
        }
        if ep:
            base.update(title=ep["series"], series_name=ep["series"],
                        season_number=ep["season"], episode_number=ep["episode"],
                        custom_slug=_slug_base(ep["series"]) or None)
        else:
            t = clean_name(label) or label
            base.update(title=t, series_name=None, season_number=None,
                        episode_number=None, custom_slug=_slug_base(t) or None)
        content.append(base)
        added += 1

    CONTENT.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ נוספו {added} פריטים. סה\"כ בקטלוג: {len(content)}")
    print("   הפעל מחדש:  sudo systemctl restart zovex-bot")
    return 0


sys.exit(asyncio.run(main()))
