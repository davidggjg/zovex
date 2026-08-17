"""מכניס את "רשימת ההמתנה" (new_uploads.json) לאתר — ומעדכן קיימים לחדשים.

מה זה עושה
----------
לכל פריט שממתין בפאנל (new_uploads.json):
  · אם הכותרת כבר קיימת באתר → *מעדכן את הקישור לקובץ החדש* (הכי חדש מנצח),
    בלי ליצור כפילות. זה ה"דברים שיש באתר → תעדכני לחדשים".
  · אחרת → מוסיף אותו כפריט חדש, בקטגוריה מזוהה (מארוול אם מתאים, אחרת
    הקטגוריה שהגיעה מההעלאה, אחרת לפי סוג: סרט→"סרטים", סדרה→"סדרות").
פרקי סדרה: מזוהים לפי (סדרה, עונה, פרק); פרק שכבר קיים מתעדכן לחדש, פרק
חדש מתווסף.

ברירת מחדל: הרצה יבשה. עם --apply מבצע (גיבוי אוטומטי, ומרוקן מהממתינים רק
את מה שטופל).

    python3 publish_waitlist.py            # דו"ח: כמה חדשים, כמה עדכונים
    python3 publish_waitlist.py --apply    # מבצע
"""
import argparse
import os
import pathlib
import re
import sys

sys.path.insert(0, "/opt/zovex-bot")

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

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

from main import (load_content, save_content, load_new_uploads,   # noqa: E402
                  save_new_uploads)
from marvel import MARVEL_CATEGORY, looks_marvel, norm             # noqa: E402

LINK_KEYS = ("video_url", "video_id", "channel_msg_id", "thumbnail_url",
             "file_unique_id", "chat_id", "dest_channel")


def is_live(e):
    return bool(e.get("is_live")) or e.get("category") == "שידורים חיים"


def is_episode(e):
    return (e.get("episode_number") is not None
            or e.get("season_number") is not None
            or bool(e.get("series_name")))


def ep_key(e):
    return (norm(e.get("series_name")), e.get("season_number"), e.get("episode_number"))


def movie_key(e):
    return norm(e.get("en_title")) or norm(e.get("title"))


def pick_category(e):
    if looks_marvel(e.get("en_title"), e.get("title"), e.get("series_name")):
        return MARVEL_CATEGORY
    if (e.get("category") or "").strip():
        return e["category"]
    return "סדרות" if is_episode(e) else "סרטים"


def newer(a, b):
    """האם a חדש יותר מ-b לפי channel_msg_id (מזהה עולה = העלאה מאוחרת)."""
    try:
        return int(a.get("channel_msg_id") or 0) > int(b.get("channel_msg_id") or 0)
    except Exception:
        return True


def copy_link(dst, src):
    """מעדכן את הקישור/הקובץ בפריט קיים לזה של ההעלאה החדשה."""
    for k in LINK_KEYS:
        if k in src:
            dst[k] = src[k]


def main():
    content = load_content()
    pending = load_new_uploads()
    print(f"באתר: {len(content)} פריטים · בהמתנה: {len(pending)}\n")
    if not pending:
        print("רשימת ההמתנה ריקה — אין מה להכניס.")
        return

    # אינדקסים על התוכן הקיים
    movies_idx = {}
    eps_idx = {}
    for e in content:
        if is_live(e):
            continue
        if is_episode(e):
            eps_idx.setdefault(ep_key(e), e)
        else:
            k = movie_key(e)
            if k:
                movies_idx.setdefault(k, e)

    add_new, upd_existing, skipped = [], [], []
    processed_ids = []

    for it in pending:
        cmid = it.get("channel_msg_id")
        if is_episode(it):
            key = ep_key(it)
            cur = eps_idx.get(key)
            if cur is not None:
                if newer(it, cur):
                    upd_existing.append((cur, it))
                else:
                    skipped.append(it)
                processed_ids.append(cmid)
            else:
                add_new.append(it)
                eps_idx[key] = it        # כדי שכפילויות בתוך ההמתנה עצמה לא יתווספו פעמיים
                processed_ids.append(cmid)
        else:
            key = movie_key(it)
            cur = movies_idx.get(key) if key else None
            if cur is not None:
                if newer(it, cur):
                    upd_existing.append((cur, it))
                else:
                    skipped.append(it)
                processed_ids.append(cmid)
            else:
                add_new.append(it)
                if key:
                    movies_idx[key] = it
                processed_ids.append(cmid)

    # פירוק לפי קטגוריה לתצוגה
    from collections import Counter
    cat_new = Counter(pick_category(e) for e in add_new)

    print("── דו\"ח ─────────────────────────────────────────")
    print(f"פריטים חדשים שיתווספו : {len(add_new)}")
    for cat, n in cat_new.most_common():
        print(f"      {n:>4}  {cat}")
    print(f"קיימים שיעודכנו לחדש  : {len(upd_existing)}")
    print(f"דולגו (הקיים כבר חדש) : {len(skipped)}")
    print("────────────────────────────────────────────────\n")

    if add_new:
        print("דוגמאות לחדשים:")
        for e in add_new[:20]:
            print(f"  + [{pick_category(e)}] {(e.get('series_name') or e.get('title') or '?')[:50]}")
        if len(add_new) > 20:
            print(f"  ... ועוד {len(add_new) - 20}")
        print()
    if upd_existing:
        print("דוגמאות לעדכונים (קישור → קובץ חדש):")
        for cur, it in upd_existing[:20]:
            print(f"  ~ {(cur.get('title') or cur.get('series_name') or '?')[:45]:<45} "
                  f"msg {cur.get('channel_msg_id')} → {it.get('channel_msg_id')}")
        if len(upd_existing) > 20:
            print(f"  ... ועוד {len(upd_existing) - 20}")
        print()

    if not args.apply:
        print("הרצה יבשה — לא שונה כלום. לביצוע: --apply")
        return

    # יישום: מעדכנים קיימים, מוסיפים חדשים, מנקים מהממתינים את מה שטופל
    for cur, it in upd_existing:
        copy_link(cur, it)
    for it in add_new:
        x = dict(it)
        x["category"] = pick_category(it)
        content.append(x)
    save_content(content)

    done = set(processed_ids)
    remaining = [p for p in pending if p.get("channel_msg_id") not in done]
    save_new_uploads(remaining)

    print(f"✅ נוספו {len(add_new)}, עודכנו {len(upd_existing)}. "
          f"נשארו בהמתנה: {len(remaining)}. גיבוי ב-content_backups/")


if __name__ == "__main__":
    main()
