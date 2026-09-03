#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מוצא בקטלוג קבצים שהדפדפן לא ישמיע.

הרקע: ונסדיי פרק 1 נמצא עם פס קול `ec-3` (Dolby Digital Plus, 5.1). שום דפדפן
אינו מפענח ec-3 או ac-3 ב-HTML5 — הוא זורק את הרצועה **בשקט** ומנגן וידאו
ללא סאונד, בלי שגיאה. VLC מנגן, כי יש לו מפענח Dolby. לכן "עובד ב-VLC, אין קול
באתר".

מה הסקריפט עושה: קורא את טבלת ה-stsd מתוך ה-moov של כל קובץ ומדווח את שם קודק
האודיו. **קריאה בלבד** — לא נוגע בכלום.

למה זה לא סורק את כל הקטלוג כברירת מחדל: כל פריט דורש משיכה של 2-6MB מטלגרם.
8,557 פריטי VOD = ~34GB, וכל משיכת רקע מטלגרם גוזלת ישירות מהצופים (זו
המלכודת שתועדה ב-STREAMING_DIAGNOSIS.md, סעיף ב). לכן חייבים מסנן. הפריטים
החשודים הם העלאות חדשות של WEB-DL באיכות גבוהה — הרִיפים האלה מגיעים עם Dolby.

    python3 audio_scan.py --since 2026-09-01          # כל מה שהועלה מה-1/9
    python3 audio_scan.py --series ונסדיי              # סדרה אחת
    python3 audio_scan.py --since 2026-08-25 --limit 80
    python3 audio_scan.py --all                        # הכל. שעות. לא בשעות שיא.

התוצאה נשמרת ל-audio_scan.json ומצטברת, כך שריצה חוזרת לא מודדת שוב מה שנמדד.
"""
import argparse, json, os, pathlib, struct, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "audio_scan.json"

# הקטלוג נקרא מהשרת המקומי כדי לא לעבור דרך האינטרנט.
CATALOG_URLS = [
    "http://127.0.0.1:8000/movies.json",
    "https://zovex.duckdns.org/movies.json",
]

# קודקים שדפדפן ישמיע. כל השאר = אין קול.
BROWSER_OK = {"mp4a", ".mp3", "Opus", "opus", "fLaC", "vorb"}
# אלה מה שראינו בשטח כשאין קול:
KNOWN_BAD = {"ec-3", "ac-3", "ac-4", "dtsc", "dtse", "dtsh", "dtsl",
             "mlpa", "sowt", "twos", "lpcm", "alac"}


# ── קריאת קופסאות MP4 ───────────────────────────────────────────────────────
CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts"}


def _boxes(buf, start=0, end=None):
    end = len(buf) if end is None else end
    o, out = start, []
    while o + 8 <= end:
        sz = struct.unpack_from(">I", buf, o)[0]
        typ = buf[o + 4:o + 8]
        hdr = 8
        if sz == 1:
            if o + 16 > end:
                break
            sz = struct.unpack_from(">Q", buf, o + 8)[0]
            hdr = 16
        elif sz == 0:
            sz = end - o
        if sz < hdr:
            break
        out.append((typ, o, hdr, sz))
        o += sz
    return out


def _streams(buf, s, e):
    """שמות הקודקים בכל ה-trak-ים שבטווח."""
    found = []
    for typ, o, hdr, sz in _boxes(buf, s, e):
        if typ in CONTAINERS:
            found += _streams(buf, o + hdr, min(o + sz, e))
        elif typ == b"stsd":
            if o + hdr + 8 > e:
                continue
            cnt = struct.unpack_from(">I", buf, o + hdr + 4)[0]
            p = o + hdr + 8
            for _ in range(min(cnt, 8)):
                if p + 8 > e:
                    break
                esz = struct.unpack_from(">I", buf, p)[0]
                if esz < 8:
                    break
                fmt = buf[p + 4:p + 8].decode("latin1", "replace")
                # SampleEntry: 6 reserved + 2 index = 8, ואז גוף הרצועה
                b = p + 8 + 8
                if fmt.startswith(("mp4a", "ec-3", "ac-3", "ac-4", "dts",
                                   "mlpa", "Opus", "alac", "sowt", "twos",
                                   "lpcm", ".mp3", "fLaC")):
                    ch = struct.unpack_from(">H", buf, b + 8)[0] if b + 10 <= e else 0
                    sr = (struct.unpack_from(">I", buf, b + 16)[0] >> 16) \
                        if b + 20 <= e else 0
                    found.append(("audio", fmt, ch, sr))
                elif fmt.startswith(("avc", "hev", "hvc", "mp4v", "vp0", "av0",
                                     "dvh", "dva")):
                    w = struct.unpack_from(">H", buf, b + 16)[0] if b + 18 <= e else 0
                    h = struct.unpack_from(">H", buf, b + 18)[0] if b + 20 <= e else 0
                    found.append(("video", fmt, w, h))
                p += esz
    return found


# ── משיכה ───────────────────────────────────────────────────────────────────
def _curl(url, rng=None, timeout=90, head=False):
    cmd = ["curl", "-sS", "--max-time", str(timeout)]
    if head:
        cmd += ["-D", "-", "-o", "/dev/null", "-H", "Range: bytes=0-1"]
    else:
        cmd += ["-H", f"Range: bytes={rng[0]}-{rng[1]}"]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True)
    return r.stdout


def _filesize(url):
    """הגודל האמיתי. HEAD על /stream מחזיר 31 בייט, לכן קוראים Content-Range."""
    txt = _curl(url, head=True, timeout=40).decode("latin1", "replace")
    for line in txt.splitlines():
        if line.lower().startswith("content-range"):
            try:
                return int(line.split("/")[-1].strip())
            except ValueError:
                pass
    return None


def _find_moov(buf):
    """קופסאות moov בטווח. אם החלון לא נפל על גבול קופסה — מאתרים בסריקה."""
    top = [b for b in _boxes(buf) if b[0] == b"moov"]
    if top:
        return top
    cand, i = [], -1
    while True:
        i = buf.find(b"moov", i + 1)
        if i < 0:
            break
        if i >= 4:
            sz = struct.unpack_from(">I", buf, i - 4)[0]
            if 100 < sz < 80_000_000:
                cand.append((b"moov", i - 4, 8, sz))
    return cand


def probe(url, head_bytes=2_500_000):
    """(איפה נמצא ה-moov, רשימת רצועות) או (סיבת כשל, None).

    ה-moov של סרט ארוך יכול להיות כמה MB, ואם הוא לא בסוף המוחלט של הקובץ
    (יש קבצים עם קופסאות אחריו) חלון קטן מפספס אותו. לכן החלון מתרחב, ולא
    נמשך יותר ממה שצריך: הרוב נסגר בקריאה הראשונה.
    """
    n = _filesize(url)
    if not n:
        n = _filesize(url)          # ניסיון שני — כשל רשת בודד אינו ממצא
    if not n:
        return "אין-גודל", None

    buf = _curl(url, (0, head_bytes - 1))
    if len(buf) < 64:
        buf = _curl(url, (0, head_bytes - 1))
    if len(buf) < 64:
        return "אין-נתונים", None

    if _find_moov(buf):
        where, top = "התחלה", _find_moov(buf)
    else:
        # moov בסוף — כך נראה כמעט כל מה שמועלה לטלגרם
        where, top = None, []
        for tail in (6_000_000, 20_000_000, 48_000_000):
            if tail >= n:
                tail = n
            buf = _curl(url, (max(0, n - tail), n - 1), timeout=180)
            top = _find_moov(buf)
            # ה-stsd יושב בתחילת ה-moov, לפני הטבלאות הגדולות. אם מצאנו כותרת
            # אבל הרצועות עדיין לא נקראות — החלון קצר, מרחיבים.
            if top and any(_streams(buf, o + h, min(o + s, len(buf)))
                           for _, o, h, s in top):
                where = "סוף" if tail == 6_000_000 else f"סוף/{tail // 1_000_000}MB"
                break
            if tail >= n:
                break
        if where is None:
            return "moov לא נקרא", None

    streams = []
    for typ, o, hdr, sz in top:
        streams += _streams(buf, o + hdr, min(o + sz, len(buf)))
    if not streams:
        return f"moov לא נקרא ({where})", None
    return where, streams


# ── ראשי ───────────────────────────────────────────────────────────────────
def load_catalog():
    for u in CATALOG_URLS:
        raw = subprocess.run(["curl", "-sS", "--max-time", "120", u],
                             capture_output=True).stdout
        if len(raw) > 10000:
            try:
                d = json.loads(raw)
                print(f"קטלוג: {len(d)} פריטים  ({u})")
                return d
            except json.JSONDecodeError:
                pass
    print("❌ לא הצלחתי לקרוא את הקטלוג")
    sys.exit(1)


def local(url, remote=False):
    """מפנה את המשיכה לשרת המקומי — אחרת המדידה עוברת דרך האינטרנט."""
    if remote:
        return url
    return url.replace("https://zovex.duckdns.org/", "http://127.0.0.1:8000/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", help="שם סדרה מדויק או חלקי")
    ap.add_argument("--since", help="added_at מהתאריך הזה (YYYY-MM-DD)")
    ap.add_argument("--all", action="store_true", help="כל הקטלוג. שעות.")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=1.5,
                    help="המתנה בין פריטים. אל תוריד מתחת ל-1 בשעות פעילות.")
    ap.add_argument("--recheck", action="store_true", help="למדוד גם מה שנמדד")
    ap.add_argument("--remote", action="store_true",
                    help="למדוד דרך הדומיין ולא דרך 127.0.0.1 (רק לבדיקה מבחוץ)")
    a = ap.parse_args()

    if not (a.series or a.since or a.all):
        print(__doc__)
        print("❌ חייב מסנן: --series / --since / --all")
        sys.exit(1)

    cat = load_catalog()
    vod = [m for m in cat
           if str(m.get("video_url", "")).startswith(
               "https://zovex.duckdns.org/stream/")]

    sel = vod
    if a.series:
        sel = [m for m in sel if a.series in str(m.get("series_name", "")) or
               a.series in str(m.get("title", ""))]
    if a.since:
        sel = [m for m in sel if str(m.get("added_at", "")) >= a.since]
    sel.sort(key=lambda m: str(m.get("added_at", "")), reverse=True)
    if a.limit:
        sel = sel[:a.limit]

    done = {}
    if OUT.exists():
        try:
            done = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            done = {}
    if not a.recheck:
        sel = [m for m in sel if m["id"] not in done]

    mb = len(sel) * 4
    print(f"נבחרו {len(sel)} פריטים (מתוך {len(vod)} VOD). "
          f"משיכה מוערכת ~{mb}MB מטלגרם, ~{len(sel) * (a.sleep + 4) / 60:.0f} דקות.")
    if mb > 3000:
        print("⚠️  זו משיכה כבדה. משיכת רקע מטלגרם גוזלת ישירות מהצופים.")
        print("    הרץ את זה בשעות מתות, או צמצם עם --limit.")
    if not sel:
        print("אין מה למדוד.")
    print()

    bad = []
    for i, m in enumerate(sel, 1):
        name = (m.get("series_name") or m.get("title") or "")[:26]
        ep = ""
        if m.get("series_name"):
            ep = f"s{m.get('season_number')}e{m.get('episode_number')}"
        try:
            where, st = probe(local(m["video_url"], a.remote))
        except Exception as e:
            where, st = f"שגיאה: {e}", None

        rec = {"id": m["id"], "name": name, "ep": ep, "moov": where,
               "at": m.get("added_at", ""),
               "chat": m.get("channel_id"), "msg": m.get("channel_msg_id")}
        if st:
            auds = [s for s in st if s[0] == "audio"]
            vids = [s for s in st if s[0] == "video"]
            rec["audio"] = [{"codec": c, "ch": x, "sr": y} for _, c, x, y in auds]
            rec["video"] = [{"codec": c, "w": x, "h": y} for _, c, x, y in vids]
            playable = [c for _, c, _, _ in auds if c in BROWSER_OK]
            rec["ok"] = bool(playable)
            rec["silent"] = not playable and bool(auds)
            rec["novideo"] = not any(
                c.startswith(("avc", "hev", "hvc")) for _, c, _, _ in vids)
        else:
            rec["ok"] = None

        done[m["id"]] = rec
        tag = "✓" if rec.get("ok") else ("🔇" if rec.get("silent") else "?")
        codecs = ",".join(f"{d['codec']}/{d['ch']}ch" for d in rec.get("audio", [])) \
            or where
        vv = ",".join(f"{d['codec']} {d['w']}x{d['h']}" for d in rec.get("video", []))
        print(f"{i:4}/{len(sel)} {tag} {name} {ep}  אודיו: {codecs}   "
              f"וידאו: {vv}   moov: {where}", flush=True)
        if rec.get("silent") or rec.get("novideo"):
            bad.append(rec)

        json.dump(done, open(OUT, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        time.sleep(a.sleep)

    # ── סיכום על כל מה שנמדד אי פעם, לא רק על הריצה הזאת ─────────────────
    allbad = [r for r in done.values() if r.get("silent") or r.get("novideo")]
    tail = [r for r in done.values() if str(r.get("moov", "")).startswith("סוף")]
    print()
    print(f"נמדדו בסך הכל: {len(done)}")
    print(f"🔇 בלי קול בדפדפן: {len(allbad)}")
    print(f"   moov בסוף הקובץ (טעינה איטית וקפיצות תקועות): {len(tail)}")
    if allbad:
        print()
        by = {}
        for r in allbad:
            by.setdefault(r["name"], []).append(r)
        for nm, rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
            cs = sorted({d["codec"] for r in rs for d in r.get("audio", [])})
            print(f"   {len(rs):3}×  {nm}   ({','.join(cs)})")
        print()
        print(f"הרשימה המלאה: {OUT}")
        print("התיקון:  python3 fix_audio_track.py --from-scan")


if __name__ == "__main__":
    main()
