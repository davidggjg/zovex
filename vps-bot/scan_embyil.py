#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מוצא את כל הערוצים שקיימים אצל הספק tv.embyil.tv.

רץ *על השרת* ולא מבחוץ, כי לשרת יש גישה ישירה לספק (הוא כבר מרלה אותו),
בלי פרוקסי באמצע ובלי הפורטים החסומים 7070/86.

שני שלבים, בסדר הזה:

  שלב 1 — חיפוש אינדקס. שרתי IPTV כמעט תמיד חושפים רשימה מלאה במקום כלשהו
  (m3u, player_api, דף תוכן). אם יש כזאת — מקבלים את הכל בבקשה אחת, *כולל
  שמות הערוצים*, וזה עדיף בהרבה על ניחוש מספרים.

  שלב 2 — סריקת מספרים, רק אם שלב 1 לא הניב. בלי תקרה: סורקת בבלוקים
  ונעצרת לבד אחרי שכמה בלוקים רצופים לא הניבו כלום.

שני פורמטי כתובת שכבר בשימוש אצלך היום נסרקים שניהם:
    A   https://tv.embyil.tv:7070/p/embyil/s/{מספר}/playlist.m3u8
    B   https://tv.embyil.tv:86/live/{מספר}/chunks.m3u8

    python3 scan_embyil.py                    # אינדקס, ואז סריקה בלי הגבלה
    python3 scan_embyil.py --no-index         # לדלג על שלב 1
    python3 scan_embyil.py --to 5000          # תקרה מפורשת במקום עצירה אוטומטית
    python3 scan_embyil.py --conns 40         # מהיר יותר (ברירת מחדל 20)
"""
import argparse, asyncio, json, pathlib, re, sys, time

try:
    import httpx
except ImportError:
    sys.exit("חסר httpx (הוא מותקן לבוט — הרץ עם אותו פייתון)")

DATA = pathlib.Path("/opt/zovex-bot/data")
CONTENT = DATA / "content.json"
OUT = DATA / "embyil_scan.json"

HDR = {"User-Agent": ("Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")}

PATTERNS = {
    "a": "https://tv.embyil.tv:7070/p/embyil/s/{n}/playlist.m3u8",
    "b": "https://tv.embyil.tv:86/live/{n}/chunks.m3u8",
}

# מקומות סבירים שבהם שרת כזה מחזיק רשימה מלאה. עולה כמעט כלום לנסות.
INDEX_URLS = [
    "https://tv.embyil.tv:7070/p/embyil/",
    "https://tv.embyil.tv:7070/p/embyil/s/",
    "https://tv.embyil.tv:7070/p/embyil/playlist.m3u",
    "https://tv.embyil.tv:7070/p/embyil/all.m3u",
    "https://tv.embyil.tv:7070/playlist.m3u",
    "https://tv.embyil.tv:7070/",
    "https://tv.embyil.tv:86/",
    "https://tv.embyil.tv:86/live/",
    "https://tv.embyil.tv:7070/player_api.php?action=get_live_streams",
    "https://tv.embyil.tv:7070/panel_api.php",
]


def existing_ids():
    have = {"a": set(), "b": set()}
    try:
        data = json.loads(CONTENT.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("movies", [])
    except Exception as e:
        print(f"⚠️  לא ניתן לקרוא את {CONTENT}: {e} — הכל ידווח כחדש")
        return have
    ra = re.compile(r"/p/embyil/s/(\d+)/")
    rb = re.compile(r"tv\.embyil\.tv[^/]*/live/(\d+)/")
    for m in items:
        u = m.get("video_url") or ""
        for rx, k in ((ra, "a"), (rb, "b")):
            g = rx.search(u)
            if g:
                have[k].add(int(g.group(1)))
    return have


async def try_index(client):
    """מנסה למצוא רשימה מלאה. מחזיר True אם נמצא משהו ששווה מבט."""
    print("שלב 1 — מחפשת רשימה מלאה אצל הספק…")
    hits = []
    for u in INDEX_URLS:
        try:
            r = await client.get(u, headers=HDR, timeout=15)
        except Exception as e:
            print(f"  ✗ {u[:64]:66} {type(e).__name__}")
            continue
        body = r.text or ""
        note = ""
        if r.status_code == 200 and len(body) > 200:
            ids = set(re.findall(r"/s/(\d+)/", body)) | set(re.findall(r"/live/(\d+)/", body))
            if ids:
                note = f"  ← מכיל {len(ids)} מזהים!"
            elif body.lstrip().startswith("#EXTM3U"):
                note = f"  ← פלייליסט ({body.count('#EXTINF')} ערוצים)!"
            if note:
                hits.append((u, body))
        print(f"  {'✓' if r.status_code == 200 else '✗'} {u[:64]:66} "
              f"{r.status_code} {len(body)}B{note}")
    if hits:
        p = DATA / "embyil_index.txt"
        p.write_text("\n\n".join(f"=== {u} ===\n{b[:200000]}" for u, b in hits),
                     encoding="utf-8")
        print(f"\n🎯 נמצאה רשימה. נשמרה ל-{p} — שלח לי אותה ואוציא ממנה הכל.")
    else:
        print("  לא נמצאה רשימה פתוחה. עוברת לסריקת מספרים.\n")
    return bool(hits)


async def probe(client, sem, pat, n, found, sigs):
    url = PATTERNS[pat].format(n=n)
    async with sem:
        for _ in range(2):
            try:
                r = await client.get(url, headers=HDR, timeout=10)
            except Exception:
                await asyncio.sleep(0.3)
                continue
            if r.status_code != 200:
                return
            body = r.text
            if not body.lstrip().startswith("#EXTM3U"):
                return
            sig = hash(body[:400])
            found.append({"pattern": pat, "id": n, "url": url, "sig": sig})
            sigs[sig] = sigs.get(sig, 0) + 1
            return


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="lo", type=int, default=1)
    ap.add_argument("--to", dest="hi", type=int, default=0,
                    help="0 = בלי תקרה, נעצר לבד")
    ap.add_argument("--pattern", default="ab")
    ap.add_argument("--conns", type=int, default=20)
    ap.add_argument("--block", type=int, default=500)
    ap.add_argument("--quit-after", type=int, default=3,
                    help="כמה בלוקים רצופים ריקים עד עצירה")
    ap.add_argument("--no-index", action="store_true")
    a = ap.parse_args()

    pats = [p for p in "ab" if p in a.pattern]
    try:
        client = httpx.AsyncClient(follow_redirects=True, http2=True)
    except ImportError:
        client = httpx.AsyncClient(follow_redirects=True)

    async with client:
        if not a.no_index:
            await try_index(client)

        have = existing_ids()
        print(f"שלב 2 — סריקת מספרים. כבר באתר: A={len(have['a'])} B={len(have['b'])}")
        print(f"מ-{a.lo}, בלוקים של {a.block}, {a.conns} במקביל, "
              f"{'בלי תקרה' if not a.hi else 'עד ' + str(a.hi)}\n")

        found, sigs = [], {}
        sem = asyncio.Semaphore(a.conns)
        t0, lo, empty = time.time(), a.lo, 0
        while True:
            hi = lo + a.block - 1
            if a.hi and hi > a.hi:
                hi = a.hi
            before = len(found)
            await asyncio.gather(*[probe(client, sem, p, n, found, sigs)
                                   for p in pats for n in range(lo, hi + 1)])
            got = len(found) - before
            print(f"  {lo}–{hi}:  +{got}   (סה\"כ {len(found)})", flush=True)
            empty = empty + 1 if got == 0 else 0
            if a.hi and hi >= a.hi:
                break
            if not a.hi and empty >= a.quit_after:
                print(f"\n{a.quit_after} בלוקים רצופים בלי כלום — עוצרת.")
                break
            lo = hi + 1

    noise = {s for s, c in sigs.items() if c > 8}
    real = [f for f in found if f["sig"] not in noise]
    new = [f for f in real if f["id"] not in have[f["pattern"]]]
    for f in real:
        f.pop("sig", None)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"all": real, "new": new}, ensure_ascii=False, indent=1),
                   encoding="utf-8")

    print(f"\n{'='*54}")
    print(f"זמן: {time.time()-t0:.0f} שניות   נסרקו עד {lo + a.block - 1}")
    print(f"ערוצים תקינים: {len(real)}")
    if noise:
        print(f"(סוננו {len(found)-len(real)} תשובות ברירת-מחדל זהות)")
    print(f"חדשים שאין לך: {len(new)}")
    print(f"נשמר: {OUT}")
    if new:
        print("\nהחדשים (עד 100 ראשונים):")
        for f in new[:100]:
            print(f"  [{f['pattern'].upper()}] {f['id']:>6}   {f['url']}")
        if len(new) > 100:
            print(f"  … ועוד {len(new)-100}. הכל בקובץ.")

asyncio.run(main())
