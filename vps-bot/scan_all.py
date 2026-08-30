#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
סורק את *כל* הספקים שהאתר מושך מהם, ומוצא כל ערוץ שקיים אצלם.

למה נכתב מחדש: הסורק הקודם עצר לבד אחרי 1500 מזהים ריקים ברצף, והנחתי
שזה סימן לסוף הרשימה. זו הייתה טעות — מרחב המזהים אצל הספקים האלה מפוזר
עם פערים ענקיים. אצל siauliairsavlt יש ערוצים ב-2341, ב-7203 וב-12278;
פער כזה מפיל את העצירה האוטומטית בכל פעם ומשאיר את רוב הקטלוג בחוץ.
כאן אין עצירה אוטומטית בכלל — סורקים את כל הטווח עד הסוף.

ארבעת המקורות (הטווחים ניתנים לשינוי):
    cellcom   tv.embyil.tv:7070/p/embyil/s/{n}   — לוח הערוצים של סלקום tv
    embyil    tv.embyil.tv:86/live/{n}
    pw        siauliairsavlt.pw/iptv/…/{n}       — הספורט יושב כאן
    mcquack   stream.mcquack.net/{n}

    python3 scan_all.py                      # הכל, טווחי ברירת מחדל
    python3 scan_all.py --only pw --to 20000
    python3 scan_all.py --only cellcom --to 6000 --conns 40
"""
import argparse, asyncio, json, pathlib, re, sys, time

try:
    import httpx
except ImportError:
    sys.exit("חסר httpx (מותקן לבוט — הרץ עם אותו פייתון)")

DATA = pathlib.Path("/opt/zovex-bot/data")
CONTENT = DATA / "content.json"
OUT = DATA / "scan_all.json"

HDR = {"User-Agent": ("Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")}

PROVIDERS = {
    "cellcom": dict(
        url="https://tv.embyil.tv:7070/p/embyil/s/{n}/playlist.m3u8",
        rx=r"/p/embyil/s/(\d+)/", hi=6000, tag="C"),
    "embyil": dict(
        url="https://tv.embyil.tv:86/live/{n}/chunks.m3u8",
        rx=r"tv\.embyil\.tv[^/]*/live/(\d+)/", hi=6000, tag="E"),
    "pw": dict(
        url="https://sewv654wfcsdwfi87fwvgbngh.siauliairsavlt.pw"
            "/iptv/F5GDYXTUM2QBV3/{n}/index.m3u8",
        rx=r"siauliairsavlt\.pw/iptv/[^/]+/(\d+)/", hi=20000, tag="P"),
    "mcquack": dict(
        url="https://stream.mcquack.net/{n}/index.m3u8",
        rx=r"stream\.mcquack\.net/(\d+)/", hi=3000, tag="M"),
}


def existing(rx):
    try:
        data = json.loads(CONTENT.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("movies", [])
    except Exception as e:
        print(f"⚠️  לא ניתן לקרוא את {CONTENT}: {e}")
        return set()
    r = re.compile(rx)
    out = set()
    for m in items:
        g = r.search(m.get("video_url") or "")
        if g:
            out.add(int(g.group(1)))
    return out


async def probe(client, sem, tmpl, n, found, sigs):
    url = tmpl.format(n=n)
    async with sem:
        for _ in range(2):
            try:
                r = await client.get(url, headers=HDR, timeout=9)
            except Exception:
                await asyncio.sleep(0.25)
                continue
            if r.status_code != 200:
                return
            body = r.text
            if not body.lstrip().startswith("#EXTM3U"):
                return
            sig = hash(body[:400])
            found.append({"id": n, "url": url, "sig": sig})
            sigs[sig] = sigs.get(sig, 0) + 1
            return


async def scan(client, key, lo, hi, conns):
    p = PROVIDERS[key]
    have = existing(p["rx"])
    print(f"\n{'='*58}\n{key}   טווח {lo}–{hi}   כבר באתר: {len(have)}")
    found, sigs = [], {}
    sem = asyncio.Semaphore(conns)
    t0 = time.time()
    STEP = 1000
    for a in range(lo, hi + 1, STEP):
        b = min(a + STEP - 1, hi)
        before = len(found)
        await asyncio.gather(*[probe(client, sem, p["url"], n, found, sigs)
                               for n in range(a, b + 1)])
        print(f"  {a}–{b}:  +{len(found)-before}   (סה\"כ {len(found)})", flush=True)

    noise = {s for s, c in sigs.items() if c > 8}
    real = [f for f in found if f["sig"] not in noise]
    new = [f for f in real if f["id"] not in have]
    for f in real:
        f.pop("sig", None)
    print(f"  זמן {time.time()-t0:.0f}ש · תקינים {len(real)} · "
          f"מסוננים {len(found)-len(real)} · חדשים {len(new)}")
    return {"provider": key, "tag": p["tag"], "all": real, "new": new}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="cellcom / embyil / pw / mcquack")
    ap.add_argument("--from", dest="lo", type=int, default=1)
    ap.add_argument("--to", dest="hi", type=int, default=0, help="0 = ברירת המחדל של הספק")
    ap.add_argument("--conns", type=int, default=30)
    a = ap.parse_args()

    keys = [a.only] if a.only else list(PROVIDERS)
    for k in keys:
        if k not in PROVIDERS:
            sys.exit(f"ספק לא מוכר: {k}. אפשר: {', '.join(PROVIDERS)}")

    try:
        client = httpx.AsyncClient(follow_redirects=True, http2=True)
    except ImportError:
        client = httpx.AsyncClient(follow_redirects=True)

    res = []
    async with client:
        for k in keys:
            hi = a.hi or PROVIDERS[k]["hi"]
            res.append(await scan(client, k, a.lo, hi, a.conns))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n{'='*58}\nסיכום")
    tot_new = 0
    for r in res:
        tot_new += len(r["new"])
        print(f"  {r['provider']:9} תקינים {len(r['all']):4}   חדשים {len(r['new']):4}")
    print(f"\nסה\"כ חדשים: {tot_new}")
    print(f"נשמר: {OUT}")
    for r in res:
        if not r["new"]:
            continue
        ids = [str(f["id"]) for f in r["new"]]
        print(f"\n{r['provider']} — {len(ids)} חדשים:")
        for i in range(0, len(ids), 18):
            print("  " + " ".join(f"{x:>6}" for x in ids[i:i + 18]))

asyncio.run(main())
