#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בודק את חותמות הזמן שמסלול תיקון-הקול (/vh) מגיש בפועל.

מפענח את חבילות ה-MPEG-TS ומדפיס את ה-PTS הראשון של כל רצועה בכל מקטע.
כך רואים מיד אם חזרה החותמת השלילית העטופה, בלי לנחש ובלי VLC.

איך זה אמור להיראות אחרי fix_vh_negative_ts.py — הקול והתמונה קרובים,
וכל מקטע ממשיך את קודמו:

    s0   H.264    0.083    AAC    0.062
    s1   H.264   13.890    AAC   13.870
    s2   H.264   29.821    AAC   29.801

ואיך זה נראה כשהתקלה קיימת — הקול בשמיים:

    s0   H.264    0.000    AAC 95443.696      ← 2**33/90000, מינוס שנעטף

    python3 check_vh_ts.py                   # ונסדיי, 3 מקטעים ראשונים
    python3 check_vh_ts.py --title "שם"      # פריט אחר
    python3 check_vh_ts.py --segs 5
"""
import argparse, collections, json, subprocess, sys, urllib.request

LOCAL = "http://127.0.0.1:8000"

# סוגי זרמים שמעניינים אותנו כאן. השאר יודפס כמספר.
STYPE = {0x0f: "AAC", 0x11: "AAC-LATM", 0x1b: "H.264", 0x24: "HEVC",
         0x81: "AC-3", 0x87: "E-AC-3", 0x03: "MP2", 0x04: "MP2"}

WRAP = 2 ** 33 / 90000.0        # 95443.717 — התקרה של שדה PTS בן 33 סיביות


def first_pts(data):
    """{שם רצועה: PTS ראשון} מתוך זרם MPEG-TS גולמי."""
    pmt, streams, out = None, {}, {}
    for i in range(0, len(data) - 187, 188):
        p = data[i:i + 188]
        if p[0] != 0x47:
            continue
        pid = ((p[1] & 0x1f) << 8) | p[2]
        start = p[1] & 0x40
        af = (p[3] >> 4) & 3
        off = 4
        if af in (2, 3):
            off += 1 + p[4]
        if off >= 188:
            continue
        if pid == 0 and start:                       # PAT
            q = off + 1 + p[off]
            pmt = ((p[q + 10] & 0x1f) << 8) | p[q + 11]
        elif pmt is not None and pid == pmt and start:   # PMT
            q = off + 1 + p[off]
            slen = ((p[q + 1] & 0x0f) << 8) | p[q + 2]
            pil = ((p[q + 10] & 0x0f) << 8) | p[q + 11]
            e, end = q + 12 + pil, q + 3 + slen - 4
            while e + 4 <= end and e + 4 < 188:
                epid = ((p[e + 1] & 0x1f) << 8) | p[e + 2]
                streams[epid] = STYPE.get(p[e], hex(p[e]))
                e += 5 + (((p[e + 3] & 0x0f) << 8) | p[e + 4])
        elif start and pid in streams and off + 13 < 188 \
                and p[off:off + 3] == b"\x00\x00\x01":
            name = streams[pid]
            if name in out:
                continue
            if p[off + 7] & 0x80:                    # יש PTS
                b = p[off + 9:off + 14]
                v = (((b[0] >> 1) & 7) << 30) | (b[1] << 22) | \
                    ((b[2] >> 1) << 15) | (b[3] << 7) | (b[4] >> 1)
                out[name] = v / 90000.0
    return out


def fetch(url, timeout=180):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="ונסדיי")
    ap.add_argument("--segs", type=int, default=3)
    a = ap.parse_args()

    raw = subprocess.run(["curl", "-sS", "--noproxy", "127.0.0.1",
                          "--max-time", "120", f"{LOCAL}/movies.json"],
                         capture_output=True).stdout
    try:
        cat = json.loads(raw)
    except Exception as e:
        sys.exit(f"❌ לא הצלחתי לקרוא את הקטלוג: {e}")

    hit = None
    for m in cat:
        u = str(m.get("video_url", ""))
        if a.title in str(m.get("title", "")) and "/stream/" in u:
            hit = m
            break
    if not hit:
        sys.exit(f"❌ לא נמצא פריט עם '{a.title}' וקישור /stream")

    # אותה המרה בדיוק שהאתר והאפליקציה עושים.
    u = hit["video_url"]
    head, tail = u.split("/stream/", 1)
    path, _, q = tail.partition("?")
    chat, msg = path.split("/")[:2]
    base = head.replace("https://zovex.duckdns.org", LOCAL)
    pl_url = f"{base}/vh/{chat}/{msg}/index.m3u8" + (f"?{q}" if q else "")

    print(f"{hit.get('title')} · עונה {hit.get('season_number')} "
          f"פרק {hit.get('episode_number')} · {chat}/{msg}\n")

    pl = fetch(pl_url).decode("utf-8", "replace")
    if not pl.startswith("#EXTM3U"):
        sys.exit(f"❌ הפלייליסט לא תקין:\n{pl[:200]}")
    durs = [l.split(":", 1)[1].rstrip(",") for l in pl.splitlines()
            if l.startswith("#EXTINF:")]
    print(f"{len(durs)} מקטעים ברשימה. בודקים {min(a.segs, len(durs))}:\n")

    bad = False
    for i in range(min(a.segs, len(durs))):
        seg = fetch(f"{base}/vh/{chat}/{msg}/s{i}.ts" + (f"?{q}" if q else ""))
        pts = first_pts(seg)
        cells = "  ".join(f"{n:<7}{v:>10.3f}" for n, v in pts.items())
        flag = ""
        if any(v > WRAP - 60 for v in pts.values()):
            flag = "   ← חותמת שלילית שנעטפה"
            bad = True
        print(f"  s{i}  {len(seg) / 1e6:>5.1f}MB  {cells}{flag}")

    print()
    if bad:
        print("❌ התקלה קיימת. הרץ:  python3 fix_vh_negative_ts.py")
        sys.exit(1)
    print("✓ החותמות תקינות בכל המקטעים שנבדקו.")


if __name__ == "__main__":
    main()
