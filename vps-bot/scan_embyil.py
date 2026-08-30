#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
סורק את הספק tv.embyil.tv ומוצא את כל הערוצים שקיימים בו.

רץ *על השרת* ולא מכאן, כי לשרת יש גישה ישירה לספק (הוא כבר מרלה אותו),
בלי פרוקסי באמצע ובלי הפורטים החסומים.

שני פורמטים של כתובת קיימים אצלך היום, ושניהם נסרקים:
    A   https://tv.embyil.tv:7070/p/embyil/s/{מספר}/playlist.m3u8
    B   https://tv.embyil.tv:86/live/{מספר}/chunks.m3u8

מה שנמצא מושווה למה שכבר יש ב-content.json, כך שהפלט הוא *רק החדשים*.
הסריקה מושכת manifest בלבד (כמה מאות בייטים לכל בדיקה) ומגבילה את עצמה
ל-12 בקשות במקביל — לא להפיל לספק את השרת.

    python3 scan_embyil.py                 # 1..1500 בשני הפורמטים
    python3 scan_embyil.py --from 1 --to 3000
    python3 scan_embyil.py --pattern a     # רק פורמט אחד
    python3 scan_embyil.py --conns 6       # עדין יותר

הפלט: data/embyil_scan.json + סיכום למסך.
"""
import argparse, asyncio, json, pathlib, sys, time

try:
    import httpx
except ImportError:
    sys.exit("חסר httpx (הוא כבר מותקן לבוט — הרץ עם אותו פייתון)")

DATA = pathlib.Path("/opt/zovex-bot/data")
CONTENT = DATA / "content.json"
OUT = DATA / "embyil_scan.json"

# אותו User-Agent שהרלֵיי משתמש בו: הספק חוסם בקשות בלי UA של דפדפן.
HDR = {"User-Agent": ("Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")}

PATTERNS = {
    "a": "https://tv.embyil.tv:7070/p/embyil/s/{n}/playlist.m3u8",
    "b": "https://tv.embyil.tv:86/live/{n}/chunks.m3u8",
}


def existing_ids():
    """המספרים שכבר בשימוש באתר, לפי הכתובות ב-content.json."""
    have = {"a": set(), "b": set()}
    try:
        data = json.loads(CONTENT.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("movies", [])
    except Exception as e:
        print(f"⚠️  לא ניתן לקרוא את {CONTENT}: {e} — ידווחו כל הערוצים, גם קיימים")
        return have
    import re
    ra = re.compile(r"/p/embyil/s/(\d+)/")
    rb = re.compile(r"tv\.embyil\.tv[^/]*/live/(\d+)/")
    for m in items:
        u = m.get("video_url") or ""
        for rx, k in ((ra, "a"), (rb, "b")):
            g = rx.search(u)
            if g:
                have[k].add(int(g.group(1)))
    return have


async def probe(client, sem, pat, n, found, seen_bodies):
    url = PATTERNS[pat].format(n=n)
    async with sem:
        for attempt in range(2):
            try:
                r = await client.get(url, headers=HDR, timeout=12)
            except Exception:
                await asyncio.sleep(0.4)
                continue
            if r.status_code != 200:
                return
            body = r.text
            if not body.lstrip().startswith("#EXTM3U"):
                return
            # חלק מהשרתים מחזירים לכל מספר את אותו "ערוץ ריק". חתימה על גוף
            # התשובה מזהה כפילויות כאלה במקום לדווח מאות ערוצים מדומים.
            sig = hash(body[:400])
            found.append({"pattern": pat, "id": n, "url": url,
                          "bytes": len(body), "sig": sig})
            seen_bodies[sig] = seen_bodies.get(sig, 0) + 1
            return


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="lo", type=int, default=1)
    ap.add_argument("--to", dest="hi", type=int, default=1500)
    ap.add_argument("--pattern", default="ab", help="a / b / ab")
    ap.add_argument("--conns", type=int, default=12)
    a = ap.parse_args()

    pats = [p for p in "ab" if p in a.pattern]
    have = existing_ids()
    print(f"כבר בשימוש באתר:  פורמט A: {len(have['a'])}   פורמט B: {len(have['b'])}")
    total = len(pats) * (a.hi - a.lo + 1)
    print(f"סורקת {a.lo}–{a.hi} בפורמטים {','.join(pats).upper()} "
          f"({total} בדיקות, {a.conns} במקביל)…\n")

    found, seen = [], {}
    sem = asyncio.Semaphore(a.conns)
    t0 = time.time()
    try:
        client = httpx.AsyncClient(follow_redirects=True, http2=True)
    except ImportError:
        client = httpx.AsyncClient(follow_redirects=True)
    async with client:
        tasks = [probe(client, sem, p, n, found, seen)
                 for p in pats for n in range(a.lo, a.hi + 1)]
        done = 0
        for chunk in [tasks[i:i + 400] for i in range(0, len(tasks), 400)]:
            await asyncio.gather(*chunk)
            done += len(chunk)
            print(f"  {done}/{total}  נמצאו עד כה: {len(found)}", flush=True)

    # ערוץ שגוף התשובה שלו חוזר על עצמו הרבה = תשובת ברירת מחדל, לא ערוץ אמיתי
    noise = {s for s, c in seen.items() if c > 8}
    real = [f for f in found if f["sig"] not in noise]
    new = [f for f in real if f["id"] not in have[f["pattern"]]]

    for f in real:
        f.pop("sig", None)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"all": real, "new": new}, ensure_ascii=False, indent=1),
                   encoding="utf-8")

    print(f"\n{'='*54}")
    print(f"זמן: {time.time()-t0:.0f} שניות")
    print(f"נמצאו ערוצים תקינים: {len(real)}")
    if noise:
        print(f"(סוננו {len(found)-len(real)} תשובות ברירת-מחדל זהות)")
    print(f"מתוכם חדשים שאין לך: {len(new)}")
    print(f"נשמר: {OUT}")
    if new:
        print("\nהחדשים:")
        for f in new[:80]:
            print(f"  [{f['pattern'].upper()}] {f['id']:>5}   {f['url']}")
        if len(new) > 80:
            print(f"  … ועוד {len(new)-80}")

asyncio.run(main())
