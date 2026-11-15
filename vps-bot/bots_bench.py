#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bots_bench — מריץ את /stream/bots-bench ומציג טבלה ברורה. קריאה בלבד.
    python3 bots_bench.py            python3 bots_bench.py --mb 8"""
import argparse, json, re, sys, urllib.request
ap = argparse.ArgumentParser(); ap.add_argument("--mb", type=int, default=4)
ap.add_argument("--base", default="http://127.0.0.1:8000"); a = ap.parse_args()
H = {"Referer": "https://zovex.duckdns.org/"}
get = lambda u, t=30: json.load(urllib.request.urlopen(urllib.request.Request(a.base + u, headers=H), timeout=t))
items = get("/content/lite?limit=800")
pick = next((x for x in items if re.search(r"/stream/-?\d+/\d+", x.get("video_url") or "") and not x.get("is_live")), None)
if not pick: sys.exit("לא נמצא סרט לבדיקה")
chat, msg = re.search(r"/stream/(-?\d+)/(\d+)", pick["video_url"]).groups()
print(f"סרט לבדיקה: {pick.get('title')}  ·  {a.mb}MB לכל בוט  ·  בוט אחד בכל פעם (כדקה-שתיים)\n")
r = get(f"/stream/bots-bench?chat={chat}&msg={msg}&mb={a.mb}", t=900)
rows = r["bots"]
ok = sorted([b for b in rows if "mbps" in b], key=lambda b: -b["mbps"])
bad = [b for b in rows if "mbps" not in b]
print(f"{'בוט':<9} {'שם':<24} {'MB/s':>6} {'הכנה':>6}  מצב")
for b in ok:
    st = "✅" if b["mbps"] >= 1.0 else ("🟡 איטי" if b["mbps"] >= 0.4 else "🔴 איטי מאוד")
    if b["choked_for"]: st += f" · חנוק עוד {b['choked_for']}ש"
    print(f"{b['name']:<9} {b['who'][:24]:<24} {b['mbps']:>6.2f} {b.get('setup_s',0):>5.1f}s  {st}")
for b in bad:
    print(f"{b['name']:<9} {b['who'][:24]:<24} {'—':>6} {'':>6}  ❌ {b['err']}")
sp = [b["mbps"] for b in ok]
if sp:
    sp.sort()
    print(f"\n== סיכום ==\n  {len(ok)} תקינים · {len(bad)} נכשלו · "
          f"חציון {sp[len(sp)//2]:.2f} MB/s · הכי מהיר {sp[-1]:.2f} · הכי איטי {sp[0]:.2f}")
    print(f"  מהירים (≥1MB/s): {sum(1 for x in sp if x >= 1)} · איטיים (<0.4): {sum(1 for x in sp if x < 0.4)}")
print("  (בוט אחד צריך ~1MB/s לסרט 1080p; ההזרמה משלבת כמה חתיכות במקביל)")
