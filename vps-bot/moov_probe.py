#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# כמה באמת שוקלת טבלת האינדקס (moov) בקטלוג.
#
# ## למה זה חשוב
#
# כדי להתחיל לנגן, כל נגן חייב את ה-moov. ב-MP4 שלא עבר faststart הוא יושב
# בסוף הקובץ, ולכן השרת מטמן 12MB עיוורים מהסוף בתקווה שהוא בפנים. אם
# ה-moov בפועל שוקל מגה אחד, אנחנו משלמים פי 12 על כל פריט: בזמן ההתנעה
# שהצופה מרגיש, בעומס על הבוטים, ובמקום בדיסק.
#
# ## איך מוצאים אותו בלי למשוך 12MB
#
# MP4 הוא שרשרת קופסאות, וכל קופסה פותחת ב-8 בתים: גודל וסוג. לכן אפשר
# לקרוא 16 בתים בתחילת קופסה, לקפוץ לפי הגודל לקופסה הבאה, ולחזור — עד
# שמגיעים ל-moov. בקובץ טיפוסי זה ftyp → mdat → moov, כלומר **שלוש קריאות
# של 16 בתים** במקום 12 מגה-בייט.
#
# ## מה הסקריפט עושה
#
# דוגם פריטים מהקטלוג, מוצא לכל אחד את ה-moov המדויק, ומדפיס את ההתפלגות.
# המספר שמעניין הוא החציון ואחוזון 90: הם קובעים אם שווה להחליף את הזנב
# הקבוע בזנב מדויק, וב-STREAM_EDGE_TAIL איזה ערך לשים אם לא.
#
# קורא בלבד. לא נוגע בקוד, בשירות או במטמון.
#
#   python3 moov_probe.py              # 40 פריטים
#   PROBE_N=100 python3 moov_probe.py  # יותר, מדויק יותר
# ─────────────────────────────────────────────────────────────────────────────
import os
import re
import struct
import sys
import time
import urllib.request

BASE = os.environ.get("PROBE_BASE", "http://127.0.0.1:8000")
N = int(os.environ.get("PROBE_N", "40"))
PAUSE = float(os.environ.get("PROBE_PAUSE", "1"))
# תקרת קפיצות. קובץ תקין מגיע ל-moov תוך כמה קופסאות; תקרה מונעת לולאה
# על קובץ פגום שמדווח גודל 0.
MAX_HOPS = 12

STREAM_RE = re.compile(r"/stream/(-?\d+)/(\d+)(\?[^\"'\s<>\\]*)?")


def rng(path, a, b, timeout=90):
    """טווח בתים מהשרת. מחזיר (נתונים, גודל_הקובץ)."""
    req = urllib.request.Request(BASE + path)
    req.add_header("Range", f"bytes={a}-{b}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        cr = r.headers.get("Content-Range", "")
    total = int(cr.rsplit("/", 1)[1]) if "/" in cr else 0
    return data, total


def find_moov(path):
    """(היסט, אורך, בסוף?, כמה קפיצות) — או None אם לא נמצא."""
    off, total, hops = 0, None, 0
    while hops < MAX_HOPS:
        hops += 1
        head, n = rng(path, off, off + 15)
        if total is None:
            total = n
        if len(head) < 8:
            return None
        size = struct.unpack_from(">I", head, 0)[0]
        typ = head[4:8]
        hdr = 8
        if size == 1:                       # גודל 64 ביט
            if len(head) < 16:
                return None
            size = struct.unpack_from(">Q", head, 8)[0]
            hdr = 16
        elif size == 0:                     # "עד סוף הקובץ"
            size = total - off
        if typ == b"moov":
            return off, size, (off + size == total), hops
        if size < hdr:                      # גודל לא תקין — עוצרים
            return None
        off += size
        if total and off >= total:
            return None
    return None


def catalog():
    try:
        body = urllib.request.urlopen(
            BASE + "/content/lite", timeout=180).read().decode("utf-8", "replace")
    except Exception as e:
        sys.exit(f"לא הצלחתי לקרוא את הקטלוג: {e}")
    seen, out = set(), []
    for chat, msg, qs in STREAM_RE.findall(body):
        if (chat, msg) in seen:
            continue
        seen.add((chat, msg))
        out.append((chat, msg, qs or ""))
    return out


def mb(x):
    return x / 1024 / 1024


def main():
    items = catalog()
    # דגימה פרושה על כל הקטלוג ולא רק על ההתחלה: הפריטים הראשונים הם
    # התוספות האחרונות, ואין סיבה להניח שהן מייצגות.
    step = max(1, len(items) // N)
    sample = items[::step][:N]
    print(f"קטלוג: {len(items)} פריטים · דוגם {len(sample)} (כל {step})\n")

    sizes, at_end, failed, hops_total = [], 0, 0, 0
    t0 = time.time()
    for i, (chat, msg, qs) in enumerate(sample, 1):
        path = f"/stream/{chat}/{msg}{qs}"
        try:
            r = find_moov(path)
        except Exception as e:
            r = None
            print(f"[{i}/{len(sample)}] {chat}/{msg}  שגיאה: {type(e).__name__}")
        if r is None:
            failed += 1
            print(f"[{i}/{len(sample)}] {chat}/{msg}  לא נמצא moov "
                  f"(לא MP4, או מבנה חריג)")
        else:
            off, size, end, hops = r
            sizes.append(size)
            hops_total += hops
            at_end += 1 if end else 0
            print(f"[{i}/{len(sample)}] {chat}/{msg}  moov {mb(size):6.2f}MB "
                  f"· {'בסוף' if end else 'בהתחלה'} · {hops} קפיצות")
        time.sleep(PAUSE)

    print(f"\n{'─' * 58}")
    if not sizes:
        sys.exit("לא נמצא אף moov — שלח לי את הפלט.")
    sizes.sort()
    def pct(p):
        return sizes[min(len(sizes) - 1, int(len(sizes) * p))]
    cur = int(os.environ.get("STREAM_EDGE_TAIL", str(12 * 1024 * 1024)))
    print(f"נמדדו {len(sizes)} · נכשלו {failed} · {time.time() - t0:.0f} שניות")
    print(f"moov בסוף הקובץ: {at_end}/{len(sizes)}   "
          f"קפיצות בממוצע: {hops_total / len(sizes):.1f}")
    print(f"\nגודל moov:")
    print(f"   חציון      {mb(pct(0.50)):6.2f}MB")
    print(f"   אחוזון 90  {mb(pct(0.90)):6.2f}MB")
    print(f"   מקסימום    {mb(sizes[-1]):6.2f}MB")
    print(f"\nהזנב הקבוע היום: {mb(cur):.0f}MB")
    print(f"בזבוז בחציון:    פי {cur / max(1, pct(0.50)):.1f}")
    covered = sum(1 for s in sizes if s <= cur)
    print(f"מכוסים היום:     {covered}/{len(sizes)}")


if __name__ == "__main__":
    main()
