#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""live_watch.py — עוקב אחרי ערוצי השידור החי לאורך זמן, ואומר מה קרה.

## למה

44 ערוצים על שרת אחד אצל הספק מחזירים HTTP 200 עם playlist תקין וללא
אף סגמנט — 72 בתים, ‎TARGETDURATION:0‎. נמדד על כל 44, בשלוש בקשות לכל
אחד, ובשלושה User-Agent כולל VLC. ארבעת המארחים האחרים מחזירים סגמנטים
תקינים באותו רגע, 49 ערוצים, בלי אף ריק.

הועלתה השערה שהפאנל מתעורר לפי ביקוש. היא נבדקה — 15 בקשות על פני
3.5 דקות לחמישה ערוצים — וכולן חזרו ריקות. כלומר הוא אינו נדלק מבקשה
בודדת בטווח של דקות. מה שהבדיקה הזאת **אינה** יכולה לשלול הוא ביקוש
מצטבר, או שעות אחרות ביום; שלוש דקות מלקוח אחד אינן ראיה לזה.

וזו בדיוק השאלה שהכלי הזה עונה עליה: הוא דוגם את כל הערוצים כל כמה
דקות, רושם שורה לכל דגימה, ומאפשר לראות אם ומתי שרת חזר לעצמו — במקום
לבדוק ידנית ולזכור.

## מה הוא עושה

* **קורא בלבד.** בקשת GET לכל playlist דרך הריליי המקומי. אינו נוגע
  בקטלוג, בנתונים, ב-main.py או בכל קובץ של המערכת.
* רושם ל-‎data/live_watch.log‎ שורה אחת לכל דגימה: זמן, כמה עובדים,
  כמה ריקים, כמה שגיאה — ואת שמות הערוצים שהשתנו מהדגימה הקודמת.
* **ממסך את שם המארח של הספק** בכל פלט, כדי שאפשר יהיה להעתיק בבטחה.

    python3 live_watch.py --once              דגימה אחת, מדפיס טבלה
    python3 live_watch.py --once --names      וגם שמות הריקים
    python3 live_watch.py --loop 300          כל 5 דקות, עד Ctrl+C
    python3 live_watch.py --report            סיכום הלוג עד כה

להשארה רצה ברקע גם אחרי יציאה מה-SSH:
    nohup python3 live_watch.py --loop 300 >/dev/null 2>&1 &
ולעצירה:
    pkill -f 'live_watch.py --loop'
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter
from urllib.parse import urlparse

DATA = os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data")
CONTENT = os.path.join(DATA, "content.json")
LOG = os.path.join(DATA, "live_watch.log")
PORT = int(os.environ.get("PORT", 8000))
UA = "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"


def mask(s: str) -> str:
    """מסתיר את שם המארח של הספק ואת האסימון שבנתיב."""
    s = re.sub(r"(/hls-relay/)(_fix/)?[^/\s]+", r"\1\2<ספק>", s)
    s = re.sub(r"\b[A-Z0-9]{8,}\b", "<אסימון>", s)
    return re.sub(r"\b(?:[a-z0-9-]+\.){2,}[a-z]{2,}\b", "<ספק>", s)


def host_tag(url: str) -> str:
    """מזהה קצר ליציב למארח, בלי לחשוף את שמו."""
    m = re.match(r"^/hls-relay/(?:_fix/)?([^/]+)/", urlparse(url).path)
    if not m:
        return "?"
    h = m.group(1)
    base, _, port = h.partition(":")
    return "מארח-" + hashlib.sha256(base.encode()).hexdigest()[:6] + \
           (f":{port}" if port else "")


def channels():
    if not os.path.exists(CONTENT):
        sys.exit(f"לא נמצא {CONTENT} — הרץ מהשרת.")
    out = []
    for i in json.load(open(CONTENT, encoding="utf-8")):
        if not i.get("is_live"):
            continue
        u = (i.get("video_url") or "").strip()
        p = urlparse(u).path
        if not p.startswith("/hls-relay/"):
            continue
        # דרך הריליי המקומי: הוא מכיר את הסכימה והפורט של כל מארח.
        # פנייה ישירה לספק ב-http קשיח נכשלה על המארחים שכן עובדים,
        # וזו הייתה טעות באבחון קודם — לא עדות על הערוץ.
        local = f"http://127.0.0.1:{PORT}{p}"
        out.append((i.get("custom_slug") or str(i.get("id")), local, host_tag(u)))
    return out


def entries(text: str) -> int:
    """שורות שאינן הערה — סגמנטים או גרסאות. בדיוק כמו בריליי.

    ספירת ‎#EXTINF‎ בלבד הייתה טעות בגרסה קודמת: playlist של גרסאות
    (master) נראה 'ריק' למרות שהוא תקין לגמרי.
    """
    return sum(1 for l in text.splitlines()
               if l.strip() and not l.strip().startswith("#"))


def probe(url: str):
    try:
        r = urllib.request.Request(url, headers={"User-Agent": UA})
        b = urllib.request.urlopen(r, timeout=25).read().decode("utf-8", "replace")
        n = entries(b)
        return ("ok" if n else "empty"), n, len(b)
    except urllib.error.HTTPError as e:
        return "err", -1, f"HTTP {e.code}"
    except Exception as e:
        return "err", -1, type(e).__name__


def sample(show_names=False):
    rows = channels()
    res = {}
    for slug, url, tag in rows:
        state, n, extra = probe(url)
        res[slug] = (state, tag, n, extra)
    c = Counter(v[0] for v in res.values())
    by_host = {}
    for slug, (state, tag, _, _) in res.items():
        by_host.setdefault(tag, Counter())[state] += 1

    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{stamp} · {len(rows)} ערוצים · עובדים {c['ok']} · "
          f"ריקים {c['empty']} · שגיאה {c['err']}")
    print(f"\n  {'מארח':<16}{'עובדים':>8}{'ריקים':>8}{'שגיאה':>8}")
    for tag in sorted(by_host, key=lambda t: -by_host[t]["empty"]):
        h = by_host[tag]
        print(f"  {tag:<16}{h['ok']:>8}{h['empty']:>8}{h['err']:>8}")
    if show_names:
        for state, label in (("empty", "ריקים"), ("err", "שגיאה")):
            names = [s for s, v in sorted(res.items()) if v[0] == state]
            if names:
                print(f"\n  ── {label} ({len(names)}) ──")
                print("     " + ", ".join(names))
    return stamp, res, c


def log_line(stamp, res, c, prev):
    changed = []
    if prev:
        for slug, (state, *_rest) in res.items():
            was = prev.get(slug)
            if was and was != state:
                changed.append(f"{slug}:{was}→{state}")
    rec = {"t": stamp, "ok": c["ok"], "empty": c["empty"], "err": c["err"],
           "changed": changed}
    try:
        os.makedirs(DATA, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"  ⚠ לא נרשם ללוג: {e}")
    if changed:
        print(f"\n  ★ השתנו מהדגימה הקודמת: {', '.join(changed)}")
    return {s: v[0] for s, v in res.items()}


def report():
    if not os.path.exists(LOG):
        sys.exit(f"אין לוג ב-{LOG}. הרץ קודם --once או --loop.")
    recs = []
    for ln in open(LOG, encoding="utf-8"):
        try:
            recs.append(json.loads(ln))
        except Exception:
            continue
    if not recs:
        sys.exit("הלוג ריק.")
    print(f"  {len(recs)} דגימות · מ-{recs[0]['t']} עד {recs[-1]['t']}\n")
    print(f"  {'זמן':<21}{'עובדים':>8}{'ריקים':>8}{'שגיאה':>8}")
    for r in recs[-25:]:
        print(f"  {r['t']:<21}{r['ok']:>8}{r['empty']:>8}{r['err']:>8}")
    best = max(recs, key=lambda r: r["ok"])
    worst = min(recs, key=lambda r: r["ok"])
    print(f"\n  הטוב ביותר: {best['ok']} עובדים ב-{best['t']}")
    print(f"  הגרוע ביותר: {worst['ok']} עובדים ב-{worst['t']}")
    if best["ok"] > worst["ok"]:
        print("\n  ⇒ המצב **כן** משתנה לאורך הזמן. כלומר זה תלוי בספק")
        print("     ובשעה, ולא בתקלה קבועה — וכדאי לדגום עוד.")
    else:
        print("\n  ⇒ המצב לא זז לאורך כל הדגימות. לא נראה תלוי-שעה.")
    ch = [(r["t"], c) for r in recs for c in r.get("changed", [])]
    if ch:
        print(f"\n  ── שינויים שנרשמו ({len(ch)}) ──")
        for t, c in ch[-30:]:
            print(f"     {t}  {c}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", type=int, metavar="שניות")
    ap.add_argument("--names", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()

    if a.report:
        report()
        return
    if a.loop:
        prev = None
        print(f"דוגם כל {a.loop} שניות. הלוג: {LOG}\n")
        while True:
            stamp, res, c = sample(a.names)
            prev = log_line(stamp, res, c, prev)
            print()
            time.sleep(a.loop)
    elif a.once:
        stamp, res, c = sample(a.names)
        log_line(stamp, res, c, None)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
