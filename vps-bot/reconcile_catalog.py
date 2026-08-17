"""מיישב את הקטלוג מול הערוץ — "סריקה של הכל".

מה זה עושה
----------
1. סורק את *כל* ערוץ התוכן פעם אחת, ובונה שני אינדקסים:
     · לפי מזהה־הודעה  (msg_id → קובץ/שם/גודל)
     · לפי שם מנורמל   (שם נקי → [msg_id...])   ← לזיהוי "איפה זה בערוץ"
2. עובר על כל פריט בקטלוג, שולף מתוכו כל קישור /stream/<chat>/<msg>,
   ובודק אם ההודעה עדיין קיימת ומכילה מדיה.
3. קישור *שבור* (ההודעה נמחקה/הוחלפה, ולכן באתר זה "טוען לנצח ולא מנגן")
   → מנסה למצוא את אותו קובץ בערוץ לפי השם, ומצביע מחדש למזהה הנכון.
4. ברירת מחדל: הרצה יבשה (רק דו"ח, לא משנה כלום). עם --apply מתקן בפועל
   (עם גיבוי אוטומטי של content.json קודם).

למה צריך חשבון משתמש: בוטים לא יכולים לקרוא היסטוריית ערוץ
(BOT_METHOD_INVALID), ולכן משתמשים ב-session string מתוך stream_bots.txt —
בדיוק כמו scan_channel.py.

שימוש
-----
    python3 reconcile_catalog.py                 # דו"ח: כמה שבורים, כמה ניתן לתקן
    python3 reconcile_catalog.py --schema         # מדפיס את מבנה הפריטים בקטלוג
    python3 reconcile_catalog.py --apply          # מתקן בפועל (מגבה קודם)
    python3 reconcile_catalog.py --query "ספיידרמן"  # מצמצם לפריט מסוים
"""
import argparse
import asyncio
import json
import os
import pathlib
import re
import sys
import time
from collections import defaultdict

sys.path.insert(0, "/opt/zovex-bot")
DATA = pathlib.Path("/opt/zovex-bot/data")
CONTENT = DATA / "content.json"

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true", help="לתקן בפועל (אחרת רק דו\"ח)")
ap.add_argument("--query", default="", help="לצמצם לפריטים שהשם/כיתוב מכיל את הטקסט")
ap.add_argument("--schema", action="store_true", help="להדפיס את מבנה הפריטים ולצאת")
ap.add_argument("--limit", type=int, default=0, help="לעצור אחרי N הודעות בערוץ (0=הכל)")
args = ap.parse_args()

# טעינת .env ידנית (כמו ב-scan_channel.py) — systemd טוען אותו, טרמינל לא.
ENV_FILE = pathlib.Path("/opt/zovex-bot/.env")
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

from pyrogram import Client                                    # noqa: E402
from main import (API_ID, API_HASH, STREAM_CHANNEL_ID,          # noqa: E402
                  STREAM_BOTS_FILE, clean_name)

_STREAM_RE = re.compile(r"/stream/(-?\d+)/(\d+)")


def _norm(s: str) -> str:
    """שם מנורמל להשוואה: מנקה, מוריד פיסוק, משאיר אותיות/ספרות (כולל עברית)."""
    s = clean_name(str(s or ""))
    s = s.lower()
    s = re.sub(r"[^\w֐-׿]+", " ", s)   # רק אלפאנומרי + עברית
    return re.sub(r"\s+", " ", s).strip()


def load_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def pick_user_session():
    if not STREAM_BOTS_FILE.exists():
        return None
    for line in STREAM_BOTS_FILE.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        # session string של חשבון = ארוך, בלי תבנית של טוקן בוט (digits:hash)
        if len(t) >= 80 and not re.match(r"^\d{5,}:[A-Za-z0-9_-]{20,}$", t):
            return t
    return None


def walk_stream_refs(node, path="$"):
    """עובר רקורסיבית על פריט ומחזיר [(path, key/index, chat_id, msg_id, raw)]."""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str):
                m = _STREAM_RE.search(v)
                if m:
                    out.append((path, k, int(m.group(1)), int(m.group(2)), v))
            else:
                out.extend(walk_stream_refs(v, f"{path}.{k}"))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            if isinstance(v, str):
                m = _STREAM_RE.search(v)
                if m:
                    out.append((path, i, int(m.group(1)), int(m.group(2)), v))
            else:
                out.extend(walk_stream_refs(v, f"{path}[{i}]"))
    return out


def item_title(item: dict) -> str:
    """שם התצוגה של פריט — מנסה כמה מפתחות נפוצים."""
    for k in ("title", "name", "he", "heb", "hebrew", "original_title",
              "series", "series_name", "display", "label"):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def repoint(raw: str, new_chat: int, new_msg: int) -> str:
    """מחליף רק את החלק /stream/<chat>/<msg> בתוך המחרוזת, שומר בסיס/חתימה."""
    return _STREAM_RE.sub(f"/stream/{new_chat}/{new_msg}", raw, count=1)


async def main():
    content = load_json(CONTENT, [])
    if not isinstance(content, list):
        print("❌ content.json אינו רשימה — מבנה לא צפוי.")
        return 1
    print(f"בקטלוג: {len(content)} פריטים")

    if args.schema:
        keys = defaultdict(int)
        for it in content:
            if isinstance(it, dict):
                for k in it.keys():
                    keys[k] += 1
        print("מפתחות שמופיעים בפריטים (מפתח: בכמה פריטים):")
        for k, n in sorted(keys.items(), key=lambda x: -x[1]):
            print(f"  {k:<20} {n}")
        if content:
            print("\nדוגמת פריט ראשון:")
            print(json.dumps(content[0], ensure_ascii=False, indent=2)[:1400])
        return 0

    sess = pick_user_session()
    if not sess:
        print("❌ אין session string של חשבון ב-stream_bots.txt — אי אפשר לסרוק ערוץ.")
        return 1

    app = Client("reconcile_tmp", api_id=API_ID, api_hash=API_HASH,
                 session_string=sess, in_memory=True, no_updates=True)
    await app.start()
    try:
        try:
            peer = await app.get_chat(STREAM_CHANNEL_ID)
        except Exception:
            print("מזהה את הערוץ דרך רשימת הצ'אטים...")
            async for _ in app.get_dialogs():
                pass
            peer = await app.get_chat(STREAM_CHANNEL_ID)
        print(f"ערוץ: {getattr(peer, 'title', STREAM_CHANNEL_ID)}")

        by_id = {}
        by_norm = defaultdict(list)
        seen = 0
        async for m in app.get_chat_history(STREAM_CHANNEL_ID):
            seen += 1
            if args.limit and seen > args.limit:
                break
            if seen % 3000 == 0:
                print(f"  נסרקו {seen} הודעות...")
            media = m.video or m.document or m.audio or m.video_note
            if not media:
                continue
            name = str(getattr(media, "file_name", "") or "")
            caption = str(m.caption or "")
            by_id[m.id] = {"name": name, "caption": caption,
                           "size": getattr(media, "file_size", 0)}
            nm = _norm(name or caption)
            if nm:
                by_norm[nm].append(m.id)
        print(f"נסרקו {seen} הודעות · {len(by_id)} מהן מדיה · "
              f"{len(by_norm)} שמות ייחודיים\n")
    finally:
        await app.stop()

    q = args.query.strip().lower()
    total_refs = ok = broken = fixed = unmatched = ambiguous = 0
    fixes = []          # (item_idx, key, old, new_msg, title)
    unresolved = []     # (title, old_msg)

    for idx, item in enumerate(content):
        if not isinstance(item, dict):
            continue
        title = item_title(item)
        if q and q not in json.dumps(item, ensure_ascii=False).lower():
            continue
        for path, key, chat_id, msg_id, raw in walk_stream_refs(item):
            total_refs += 1
            if msg_id in by_id:
                ok += 1
                continue
            broken += 1
            # מנסים למצוא את אותו קובץ לפי השם
            cand = by_norm.get(_norm(title))
            # אם אין התאמה לפי כותרת הפריט, ננסה גם לפי כל טקסט בפריט
            if not cand:
                for k2 in ("file_name", "filename", "original_name"):
                    v = item.get(k2)
                    if isinstance(v, str):
                        cand = by_norm.get(_norm(v))
                        if cand:
                            break
            if not cand:
                unmatched += 1
                unresolved.append((title or f"פריט #{idx}", msg_id))
                continue
            if len(set(cand)) > 1:
                ambiguous += 1
                unresolved.append((f"{title} (⚠️ {len(set(cand))} התאמות)", msg_id))
                continue
            new_msg = cand[0]
            fixes.append((idx, key, path, msg_id, new_msg, title, chat_id, raw))
            fixed += 1

    print("── דו\"ח ─────────────────────────────────────────")
    print(f"סה\"כ קישורי /stream בקטלוג : {total_refs}")
    print(f"תקינים (קיימים בערוץ)      : {ok}")
    print(f"שבורים                     : {broken}")
    print(f"  → ניתנים לתיקון אוטומטי  : {fixed}")
    print(f"  → בלי התאמה לפי שם       : {unmatched}")
    print(f"  → התאמה מעורפלת (כמה)    : {ambiguous}")
    print("────────────────────────────────────────────────\n")

    if fixes:
        print("דוגמאות לתיקונים שיבוצעו:")
        for _idx, _key, _path, oldm, newm, title, _chat, _raw in fixes[:25]:
            print(f"  {(title or '?')[:45]:<45}  msg {oldm} → {newm}")
        if len(fixes) > 25:
            print(f"  ... ועוד {len(fixes) - 25}")
        print()

    if unresolved:
        print("שבורים שלא נמצאה להם התאמה (צריך בדיקה ידנית):")
        for title, oldm in unresolved[:25]:
            print(f"  {(title or '?')[:50]:<50}  msg {oldm}")
        if len(unresolved) > 25:
            print(f"  ... ועוד {len(unresolved) - 25}")
        print()

    if not args.apply:
        print("הרצה יבשה — לא שונה כלום. לתיקון בפועל הוסף --apply")
        return 0

    if not fixes:
        print("אין מה לתקן.")
        return 0

    # גיבוי לפני שינוי
    backup = CONTENT.with_suffix(f".json.bak.{int(time.time())}")
    backup.write_text(CONTENT.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"גיבוי נשמר: {backup.name}")

    for idx, key, _path, _oldm, newm, _title, chat_id, raw in fixes:
        item = content[idx]
        # מאתרים מחדש את המחרוזת ומחליפים רק את החלק /stream/
        new_chat = STREAM_CHANNEL_ID if chat_id != STREAM_CHANNEL_ID else chat_id
        newval = repoint(raw, new_chat, newm)
        # key הוא מפתח־מילון או אינדקס־רשימה — מתקנים במקום הנכון
        node = item
        # רוב הפריטים שטוחים: המפתח ישירות על הפריט
        if isinstance(node, dict) and key in node and isinstance(node[key], str):
            node[key] = newval
        else:
            # מבנה מקונן — מאתרים לפי הערך הישן ומחליפים
            _replace_deep(item, raw, newval)

    CONTENT.write_text(json.dumps(content, ensure_ascii=False, indent=0),
                       encoding="utf-8")
    print(f"✅ תוקנו {len(fixes)} קישורים ב-content.json")
    print("   (הפעל מחדש לא נדרש — האתר קורא את הקובץ, אבל אם יש מטמון: "
          "systemctl restart zovex-bot)")
    return 0


def _replace_deep(node, old, new):
    if isinstance(node, dict):
        for k, v in node.items():
            if v == old:
                node[k] = new
            elif isinstance(v, (dict, list)):
                _replace_deep(v, old, new)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            if v == old:
                node[i] = new
            elif isinstance(v, (dict, list)):
                _replace_deep(v, old, new)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
