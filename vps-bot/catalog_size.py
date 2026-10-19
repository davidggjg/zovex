#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# כמה ג'יגה יש בסך הכל בכל מה שמופיע בקטלוג.
#
# תשובה אחת: סך הנפח של כל הסרטים והסדרות שהאתר והאפליקציה מגישים.
#
# ## מה נספר
#
# כל פריט ב-/content/lite שמוגש דרך ‎/stream/‎ — כלומר קובץ שיושב בטלגרם.
# שידורים חיים אינם קבצים אלא כתובות חיצוניות, ולכן אין להם נפח והם
# מוחרגים מעצמם.
#
# ## למה זה לוקח זמן
#
# הגודל של פריט שמור אצלנו רק אם מישהו פתח אותו אי פעם (stream_meta.json).
# לשאר צריך לשאול את טלגרם, פריט-פריט. זו שאילתת מטא-דאטה בלבד ולא הורדה,
# ולכן היא זולה — אבל יש הרבה כאלה. העבודה רצה בכמה חוטים במקביל כדי
# לקצר את זה משעות לדקות.
#
# ## על העומס
#
# ‎SIZE_WORKERS‎ שולט בעומס. ברירת המחדל 4 נבחרה כדי שהבדיקה לא תתחרה
# בצופים על אותם בוטים — זו טעות שכבר עלתה לנו פעם עם מחמם שרץ בשעת
# צפייה. בשעה ריקה אפשר להעלות.
#
#   python3 catalog_size.py                  # התשובה
#   SIZE_WORKERS=8 python3 catalog_size.py   # מהר יותר, עומס גדול יותר
# ─────────────────────────────────────────────────────────────────────────────
import json
import os
import re
import sys
import threading
import time
import urllib.request
from queue import Queue

BASE = os.environ.get("SIZE_BASE", "http://127.0.0.1:8000")
META = os.environ.get("SIZE_META", "/opt/zovex-bot/data/stream_meta.json")
WORKERS = int(os.environ.get("SIZE_WORKERS", "4"))

STREAM_RE = re.compile(r"/stream/(-?\d+)/(\d+)(\?[^\"'\s<>\\]*)?")
GB = 1024 ** 3


def main():
    print("קורא את הקטלוג...")
    try:
        raw = urllib.request.urlopen(BASE + "/content/lite", timeout=300).read()
    except Exception as e:
        sys.exit(f"לא הצלחתי לקרוא את הקטלוג מ-{BASE}: {e}")
    body = raw.decode("utf-8", "replace")

    seen, items = set(), []
    for chat, msg, qs in STREAM_RE.findall(body):
        if (chat, msg) in seen:
            continue
        seen.add((chat, msg))
        items.append((chat, msg, qs or ""))

    try:
        meta = json.load(open(META, encoding="utf-8"))
    except Exception:
        meta = {}

    sizes, todo = {}, []
    for chat, msg, qs in items:
        m = meta.get(f"{chat}:{msg}")
        if m and m.get("size"):
            sizes[(chat, msg)] = int(m["size"])
        else:
            todo.append((chat, msg, qs))

    print(f"{len(items):,} קבצים בקטלוג · "
          f"{len(sizes):,} גדלים כבר ידועים · "
          f"{len(todo):,} לשאול\n")

    if todo:
        q = Queue()
        for x in todo:
            q.put(x)
        lock = threading.Lock()
        done = [0]
        failed = [0]
        t0 = time.time()

        def worker():
            while True:
                try:
                    chat, msg, qs = q.get_nowait()
                except Exception:
                    return
                try:
                    req = urllib.request.Request(f"{BASE}/stream/{chat}/{msg}{qs}")
                    req.add_header("Range", "bytes=0-0")
                    with urllib.request.urlopen(req, timeout=90) as r:
                        cr = r.headers.get("Content-Range", "")
                    sz = int(cr.rsplit("/", 1)[1]) if "/" in cr else 0
                except Exception:
                    sz = 0
                with lock:
                    done[0] += 1
                    if sz:
                        sizes[(chat, msg)] = sz
                    else:
                        failed[0] += 1
                    d = done[0]
                if d % 50 == 0:
                    el = time.time() - t0
                    rate = d / el
                    left = (len(todo) - d) / rate / 60 if rate else 0
                    with lock:
                        cur = sum(sizes.values())
                    print(f"   {d:,}/{len(todo):,} · "
                          f"עד כה {cur / GB:,.0f} GB · "
                          f"נותרו כ-{left:.0f} דקות")
                q.task_done()

        ts = [threading.Thread(target=worker, daemon=True) for _ in range(WORKERS)]
        for t in ts:
            t.start()
        try:
            for t in ts:
                t.join()
        except KeyboardInterrupt:
            print("\nנעצר ידנית — התוצאה למטה חלקית.\n")

    total = sum(sizes.values())
    n = len(sizes)
    miss = len(items) - n

    print()
    print("═" * 50)
    print(f"   סך הכל:  {total / GB:,.1f} GB")
    print("═" * 50)
    print(f"   {n:,} קבצים נמדדו")
    if miss:
        print(f"   {miss:,} לא נמדדו (נמחקו מהערוץ, או שגיאה)")
        print(f"   הערכה כולל אלה: ~{(total / n * len(items)) / GB:,.0f} GB")
    print(f"   ממוצע לקובץ: {total / n / GB:,.2f} GB" if n else "")


if __name__ == "__main__":
    main()
