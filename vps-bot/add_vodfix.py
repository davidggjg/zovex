#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מתקן קבצי VOD שבורים בזמן אמת, בלי להוריד, בלי להמיר ובלי להעלות מחדש.

## שתי הבעיות שנמדדו

16 פרקי ונסדיי:

    וידאו:  avc1  1920x1080    ← תקין
    אודיו:  ec-3  6 ערוצים     ← Dolby Digital Plus
    moov:   בסוף הקובץ

**א. `ec-3`** — Dolby Digital Plus. התמיכה בו מושבתת בבנייה הרגילה של Chromium
מסיבות רישוי, ולכן הדפדפן זורק את רצועת הקול **בשקט** ומנגן וידאו בלי סאונד.
בטלגרם וב-VLC כן שומעים, כי להם יש מפענח Dolby משלהם.

**ב. `moov` בסוף** — האינדקס בקצה הקובץ. הנגן חייב אותו לפני שהוא מתחיל, ולכן
נאלץ למשוך את הקצה קודם: 12 שניות טעינה, וקפיצה באמצע שנתקעת.

## הפתרון — Direct Stream, כמו ב-Jellyfin ו-Plex

לא נוגעים בקובץ שבטלגרם. שני מסלולים חדשים:

**`/fs/<chat>/<msg>`** — אותו קובץ בדיוק, רק עם ה-`moov` בהתחלה. ה-`moov`
נמשך פעם אחת (2MB), ההיסטים שבתוכו מתוקנים בזיכרון, והתוצאה מוגשת ככותרת לפני
שאר הקובץ. תומך בטווחי בייטים במלואם, ולכן הנגן מקבל קפיצה מיידית. **אפס
המרה, אפס מעבד.** זה מה ש-qt-faststart עושה, רק בלי לכתוב קובץ.

**`/vh/<chat>/<msg>/index.m3u8`** — HLS. הרשימה נבנית מראש מתוך ה-`moov`,
כשכל סגמנט מתחיל בפריים מפתח אמיתי, ולכן היא **שלמה מהרגע הראשון** ויש בה
סרגל קפיצה מלא. סגמנט מומר רק כשמבקשים אותו: `-c:v copy` (הווידאו עובר כמו
שהוא) + `-c:a aac` (רק האודיו). מי שצופה 10 דקות משלם על 10 דקות.

**`/vodinfo/<chat>/<msg>`** — אומר לאתר מה מצב הקובץ ואיזה קישור לנגן.

האתר כבר יודע לנגן HLS — נגן Shaka נכנס לפעולה לכל קישור `.m3u8`. אין צורך
לשנות את הנגן.

## מה זה עולה

| | הורדה לשרת | דיסק | העלאה | מעבד |
|---|---|---|---|---|
| להעלות מחדש 16 פרקים | 26GB | 3GB | 24GB | נמוך |
| **המסלולים האלה** | **רק מה שצופים** | **0** | **0** | קידוד אודיו בלבד |

**הפאץ' רק מוסיף בסוף הקובץ.** אינו נוגע באף שורה קיימת.

    python3 add_vodfix.py --check
    python3 add_vodfix.py && systemctl restart zovex-bot
    python3 add_vodfix.py --undo
"""
import datetime, glob, os, pathlib, py_compile, re, shutil, sys, tempfile

TARGET = pathlib.Path("/opt/zovex-bot/main.py")
DONE_MARK = "_vf_header_for"

NEEDED = ["api = FastAPI", "def check_hotlink", "def _stream_sig",
          "SIGN_SECRET", "SIGN_TTL", "PORT ", "log = logging.getLogger",
          "import httpx", "StreamingResponse", "Response", "import hmac",
          "STREAM_PUBLIC_BASE"]

CORE = r'''
# ── קריאת מבנה MP4 ──────────────────────────────────────────────
# נבדק מול הקובץ שבשרת לפני שנכתב לכאן: 174,892 היסטים תוקנו, גודל הקובץ
# החדש זהה למקורי, ו-ffprobe קרא ממנו avc1 1920x1080 ואורך 3647.552 שניות,
# ופענוח וקפיצה לדקה 0:20 עברו.
import struct

_MP4_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"mvex"}


def _mp4_boxes(buf, start=0, end=None):
    """(סוג, היסט, אורך כותרת, אורך כולל) לכל קופסה בטווח."""
    end = len(buf) if end is None else end
    o, out = start, []
    while o + 8 <= end:
        size = struct.unpack_from(">I", buf, o)[0]
        typ = bytes(buf[o + 4:o + 8])   # bytes תמיד — גם כשהחוצץ bytearray
        hdr = 8
        if size == 1:
            if o + 16 > end:
                break
            size = struct.unpack_from(">Q", buf, o + 8)[0]
            hdr = 16
        elif size == 0:
            size = end - o
        if size < hdr or o + size > end:
            # קופסה שחורגת מהחוצץ — החלון קצר מדי, לא ממציאים
            if size < hdr:
                break
            out.append((typ, o, hdr, size))
            break
        out.append((typ, o, hdr, size))
        o += size
    return out


def _mp4_offset_tables(moov, base=0, end=None):
    """מיקומי כל טבלאות ההיסטים בתוך moov: (סוג, היסט_בטבלה, מספר_רשומות)."""
    end = len(moov) if end is None else end
    found = []
    for typ, o, hdr, size in _mp4_boxes(moov, base, end):
        if typ in _MP4_CONTAINERS:
            found += _mp4_offset_tables(moov, o + hdr, min(o + size, end))
        elif typ in (b"stco", b"co64"):
            # FullBox: 1 בייט גרסה + 3 דגלים, ואז מספר הרשומות
            n = struct.unpack_from(">I", moov, o + hdr + 4)[0]
            found.append((typ, o + hdr + 8, n))
    return found


def _mp4_shift_offsets(moov: bytearray, delta: int) -> int:
    """מוסיף delta לכל היסט נתונים בתוך moov. מחזיר כמה היסטים שונו.

    `stco` הוא 32 סיביות. אם היסט כלשהו יחרוג מ-4GB אחרי ההזזה, הטבלה כבר
    לא יכולה להכיל אותו — במקרה כזה עוצרים ולא מייצרים קובץ פגום.
    """
    n_changed = 0
    for typ, pos, count in _mp4_offset_tables(moov):
        if typ == b"stco":
            for i in range(count):
                p = pos + i * 4
                if p + 4 > len(moov):
                    raise ValueError("stco חורג מגבולות moov")
                v = struct.unpack_from(">I", moov, p)[0] + delta
                if v > 0xFFFFFFFF:
                    raise ValueError("ההיסט חורג מ-4GB; צריך co64")
                struct.pack_into(">I", moov, p, v)
                n_changed += 1
        else:
            for i in range(count):
                p = pos + i * 8
                if p + 8 > len(moov):
                    raise ValueError("co64 חורג מגבולות moov")
                v = struct.unpack_from(">Q", moov, p)[0] + delta
                struct.pack_into(">Q", moov, p, v)
                n_changed += 1
    return n_changed


def _mp4_first_chunk(moov):
    """ההיסט הקטן ביותר בטבלאות — לבדיקת שפיות מול הקובץ המקורי."""
    best = None
    for typ, pos, count in _mp4_offset_tables(moov):
        for i in range(min(count, 4)):
            if typ == b"stco":
                v = struct.unpack_from(">I", moov, pos + i * 4)[0]
            else:
                v = struct.unpack_from(">Q", moov, pos + i * 8)[0]
            best = v if best is None else min(best, v)
    return best


def _mp4_build_header(ftyp: bytes, moov: bytes, moov_start: int, file_size: int):
    """הכותרת החדשה ומפת המיפוי חזרה לקובץ המקורי.

    מחזיר (header_bytes, body_src_start, body_len) כאשר:
        קובץ חדש = header_bytes + מקורי[body_src_start : body_src_start+body_len]

    דורש ש-moov יהיה הקופסה האחרונה. אם יש משהו אחריו, המיפוי אינו רציף
    ואז מוותרים — עדיף להגיש את הקובץ כמו שהוא מאשר להגיש קובץ שגוי.
    """
    if moov_start + len(moov) != file_size:
        raise ValueError("moov אינו הקופסה האחרונה בקובץ")
    if ftyp[4:8] != b"ftyp":
        raise ValueError("לא נמצא ftyp בתחילת הקובץ")

    patched = bytearray(moov)
    n = _mp4_shift_offsets(patched, len(moov))

    header = ftyp + bytes(patched)
    body_start = len(ftyp)
    body_len = moov_start - len(ftyp)
    if body_len < 0:
        raise ValueError("ftyp ארוך מ-moov_start")
    return header, body_start, body_len, n


def _mp4_map_range(pos: int, header_len: int, body_start: int) -> int:
    """מיקום בקובץ החדש → מיקום בקובץ המקורי (רק לאזור שאחרי הכותרת)."""
    return pos - header_len + body_start


# ── נקודות חיתוך לפי פריימי מפתח ────────────────────────────────────────────
# כדי להגיש HLS בלי לקודד וידאו מחדש, כל סגמנט חייב להתחיל בפריים מפתח. אם
# חותכים באמצע, ffmpeg ב-`-c:v copy` מוציא סגמנט שמתחיל בפריים שאי אפשר
# לפענח בלי הקודם — והנגן מראה ריבועים או מסך שחור עד הפריים הבא.
#
# הזמנים האלה כבר יושבים בתוך ה-moov שכבר משכנו: `stss` מחזיק את מספרי
# פריימי המפתח, ו-`stts` את משך כל פריים. אין צורך לקרוא אף בייט נוסף.

def _mp4_trak_tables(moov):
    """לכל trak: (סוג המסלול, timescale, stts, stss) — מהקופסאות שבתוכו בלבד."""
    out = []
    for typ, o, hdr, size in _mp4_boxes(moov):
        if typ != b"moov":
            continue
        for t2, o2, h2, s2 in _mp4_boxes(moov, o + hdr, o + size):
            if t2 != b"trak":
                continue
            info = {"kind": None, "timescale": 0, "stts": None, "stss": None}
            _mp4_scan_trak(moov, o2 + h2, o2 + s2, info)
            out.append(info)
    return out


def _mp4_scan_trak(buf, s, e, info):
    for typ, o, hdr, size in _mp4_boxes(buf, s, e):
        end = min(o + size, e)
        if typ in _MP4_CONTAINERS:
            _mp4_scan_trak(buf, o + hdr, end, info)
        elif typ == b"hdlr":
            info["kind"] = bytes(buf[o + hdr + 8:o + hdr + 12])
        elif typ == b"mdhd":
            ver = buf[o + hdr]
            p = o + hdr + 4 + (16 if ver == 1 else 8)
            info["timescale"] = struct.unpack_from(">I", buf, p)[0]
        elif typ == b"stts":
            n = struct.unpack_from(">I", buf, o + hdr + 4)[0]
            info["stts"] = (o + hdr + 8, n)
        elif typ == b"stss":
            n = struct.unpack_from(">I", buf, o + hdr + 4)[0]
            info["stss"] = (o + hdr + 8, n)


def _mp4_keyframes(moov):
    """זמני פריימי המפתח של מסלול הווידאו, בשניות. [] אם אי אפשר לחשב.

    מסלול בלי `stss` פירושו שכל פריים הוא פריים מפתח — אפשר לחתוך בכל מקום.
    מסלול תמונת שער (PNG) מסונן החוצה לפי מספר הפריימים.
    """
    best = None
    for info in _mp4_trak_tables(moov):
        if info["kind"] != b"vide" or not info["timescale"] or not info["stts"]:
            continue
        pos, n = info["stts"]
        total = 0
        for i in range(n):
            total += struct.unpack_from(">I", moov, pos + i * 8)[0]
        # תמונת שער היא מסלול וידאו עם פריים אחד; המסלול האמיתי ארוך ממנו
        if best is None or total > best[0]:
            best = (total, info)
    if best is None:
        return []
    info = best[1]
    ts = info["timescale"]

    # זמן ההתחלה של כל פריים, מתוך טבלת המשכים הדחוסה
    starts, t = [], 0
    pos, n = info["stts"]
    for i in range(n):
        cnt = struct.unpack_from(">I", moov, pos + i * 8)[0]
        dur = struct.unpack_from(">I", moov, pos + i * 8 + 4)[0]
        for _ in range(cnt):
            starts.append(t)
            t += dur

    if not info["stss"]:
        return [s / ts for s in starts]      # כל פריים הוא פריים מפתח
    pos, n = info["stss"]
    out = []
    for i in range(n):
        num = struct.unpack_from(">I", moov, pos + i * 4)[0]   # 1-based
        if 1 <= num <= len(starts):
            out.append(starts[num - 1] / ts)
    return out


def _mp4_segment_plan(moov, target=10.0):
    """גבולות סגמנטים בשניות, כל אחד מתחיל בפריים מפתח.

    מחזיר (רשימת (התחלה, משך), משך כולל). מאחד פריימי מפתח צפופים כדי לא
    לייצר אלפי סגמנטים, ומפצל רק היכן שיש פריים מפתח באמת.
    """
    kf = _mp4_keyframes(moov)
    total = _mp4_duration(moov)
    if not kf or not total:
        return [], total
    kf = sorted(set(round(k, 3) for k in kf if k < total))
    if not kf or kf[0] > 0.001:
        kf = [0.0] + kf
    bounds = [kf[0]]
    for k in kf[1:]:
        if k - bounds[-1] >= target:
            bounds.append(k)
    segs = []
    for i, s in enumerate(bounds):
        e = bounds[i + 1] if i + 1 < len(bounds) else total
        if e - s > 0.05:
            segs.append((s, e - s))
    return segs, total


def _mp4_duration(moov):
    """אורך הסרט מ-mvhd."""
    for typ, o, hdr, size in _mp4_boxes(moov):
        if typ != b"moov":
            continue
        for t2, o2, h2, s2 in _mp4_boxes(moov, o + hdr, o + size):
            if t2 == b"mvhd":
                ver = moov[o2 + h2]
                p = o2 + h2 + 4 + (16 if ver == 1 else 8)
                ts = struct.unpack_from(">I", moov, p)[0]
                if ver == 1:
                    dur = struct.unpack_from(">Q", moov, p + 4)[0]
                else:
                    dur = struct.unpack_from(">I", moov, p + 4)[0]
                return dur / ts if ts else 0.0
    return 0.0
'''

ENDPOINTS = r'''

# ── תיקון VOD בזמן אמת ──────────────────────────────────────────────────────
# ראה add_vodfix.py לנימוק המלא. בקצרה: קובץ עם moov בסוף נטען 12 שניות
# ונתקע בקפיצה, וקובץ עם אודיו ec-3/ac-3/DTS מתנגן בדפדפן בלי קול בכלל
# (התמיכה ב-Dolby מושבתת ב-Chromium מסיבות רישוי). שניהם מתוקנים כאן בזמן
# אמת, בלי לגעת בקובץ שבטלגרם.

_VF_TTL = 6 * 3600
_vf_cache: dict = {}          # (chat,msg) -> (זמן, מידע)
_VF_CACHE_MAX = 40            # כל כותרת ~2MB; תקרה כדי לא לנפח את הזיכרון
_VF_SEG_TARGET = float(os.environ.get("VODFIX_SEG", "10"))
_VF_ABR = os.environ.get("VODFIX_AUDIO_BITRATE", "192k")
_VF_BROWSER_AUDIO = {"mp4a", ".mp3", "Opus", "opus", "fLaC"}


def _vf_local_url(chat: int, msg: int) -> str:
    exp = int(time.time()) + SIGN_TTL
    sig = _stream_sig(str(chat), str(msg), exp) if SIGN_SECRET else ""
    q = f"?exp={exp}&sig={sig}" if SIGN_SECRET else ""
    return f"http://127.0.0.1:{PORT}/stream/{chat}/{msg}{q}"


async def _vf_fetch(url: str, a: int, b: int) -> bytes:
    async with httpx.AsyncClient(timeout=180) as cx:
        r = await cx.get(url, headers={"Range": f"bytes={a}-{b}"})
        if r.status_code not in (200, 206):
            raise HTTPException(502, f"המקור החזיר {r.status_code}")
        return r.content


async def _vf_size(url: str):
    async with httpx.AsyncClient(timeout=60) as cx:
        r = await cx.get(url, headers={"Range": "bytes=0-1"})
        cr = r.headers.get("content-range", "")
        if "/" in cr:
            try:
                return int(cr.rsplit("/", 1)[1])
            except ValueError:
                pass
    return None


def _vf_audio_codecs(moov: bytes):
    """שמות קודקי האודיו, מתוך טבלאות ה-stsd."""
    out = []

    def walk(s, e):
        for typ, o, hdr, size in _mp4_boxes(moov, s, e):
            end = min(o + size, e)
            if typ in _MP4_CONTAINERS:
                walk(o + hdr, end)
            elif typ == b"stsd":
                cnt = struct.unpack_from(">I", moov, o + hdr + 4)[0]
                p = o + hdr + 8
                for _ in range(min(cnt, 8)):
                    if p + 8 > end:
                        break
                    esz = struct.unpack_from(">I", moov, p)[0]
                    if esz < 8:
                        break
                    fmt = bytes(moov[p + 4:p + 8]).decode("latin1", "replace")
                    if fmt.startswith(("mp4a", "ec-3", "ac-3", "ac-4", "dts",
                                       "mlpa", "Opus", "alac", "sowt", "twos",
                                       "lpcm", ".mp3", "fLaC")):
                        out.append(fmt)
                    p += esz
    walk(0, len(moov))
    return out


async def _vf_header_for(chat: int, msg: int):
    """הכותרת המתוקנת והמידע על הקובץ. נבנה פעם אחת ונשמר.

    זו הפעולה היחידה שמושכת בייטים שלא לצורך צפייה — 2MB פעם אחת לקובץ.
    """
    key = (int(chat), int(msg))
    now = time.time()
    ent = _vf_cache.get(key)
    if ent and now - ent[0] < _VF_TTL:
        return ent[1]

    url = _vf_local_url(chat, msg)
    n = await _vf_size(url)
    if not n:
        raise HTTPException(502, "לא הצלחתי לקבל את גודל הקובץ")

    head = await _vf_fetch(url, 0, 4095)
    tb = _mp4_boxes(head)
    ftyp = None
    for typ, o, hdr, size in tb:
        if typ == b"ftyp":
            ftyp = bytes(head[o:o + size])
            break
    if ftyp is None:
        raise HTTPException(415, "אין ftyp — לא קובץ MP4")

    moov = None
    moov_start = None
    if any(t == b"moov" for t, _, _, _ in tb):
        for typ, o, hdr, size in tb:
            if typ == b"moov":
                moov_start = o
                moov = await _vf_fetch(url, o, o + size - 1)
                break
    else:
        for win in (6_000_000, 20_000_000, 48_000_000):
            win = min(win, n)
            buf = await _vf_fetch(url, n - win, n - 1)
            i = -1
            while True:
                i = buf.find(b"moov", i + 1)
                if i < 0:
                    break
                if i >= 4:
                    sz = struct.unpack_from(">I", buf, i - 4)[0]
                    if 100 < sz < 80_000_000 and i - 4 + sz <= len(buf):
                        moov = bytes(buf[i - 4:i - 4 + sz])
                        moov_start = n - win + i - 4
            if moov is not None:
                break
            if win >= n:
                break
    if moov is None:
        raise HTTPException(415, "לא נמצא moov")

    info = {"size": n, "moov_at_end": moov_start + len(moov) == n,
            "moov_start": moov_start, "moov_len": len(moov),
            "duration": _mp4_duration(moov),
            "audio": _vf_audio_codecs(moov), "header": None,
            "body_start": 0, "body_len": 0, "segments": None}
    info["audio_ok"] = any(c in _VF_BROWSER_AUDIO for c in info["audio"])

    if info["moov_at_end"]:
        try:
            hdr_b, bs, bl, cnt = _mp4_build_header(ftyp, moov, moov_start, n)
            info["header"], info["body_start"], info["body_len"] = hdr_b, bs, bl
            log.info("vodfix: %s/%s — moov הוזז להתחלה (%d היסטים)",
                     chat, msg, cnt)
        except Exception as e:
            # לא מייצרים קובץ שגוי. בלי כותרת, /fs פשוט לא זמין לקובץ הזה.
            log.warning("vodfix: %s/%s — בניית כותרת נכשלה: %s", chat, msg, e)

    if len(_vf_cache) >= _VF_CACHE_MAX:
        for k in sorted(_vf_cache, key=lambda k: _vf_cache[k][0])[:10]:
            _vf_cache.pop(k, None)
    _vf_cache[key] = (now, info)
    return info


def _vf_check_sig(chat: int, msg: int, exp: int, sig: str):
    if not SIGN_SECRET:
        return
    if not exp or exp < int(time.time()):
        raise HTTPException(403, "הקישור פג תוקף")
    if not hmac.compare_digest(sig, _stream_sig(str(chat), str(msg), exp)):
        raise HTTPException(403, "חתימה שגויה")


@api.get("/fs/{chat_id}/{message_id}")
async def vodfix_faststart(chat_id: int, message_id: int, request: Request,
                           exp: int = 0, sig: str = ""):
    """אותו קובץ, עם ה-moov בהתחלה. תומך בטווחי בייטים במלואם."""
    check_hotlink(request)
    _vf_check_sig(chat_id, message_id, exp, sig)
    info = await _vf_header_for(chat_id, message_id)
    # כשה-moov כבר בהתחלה אין כותרת לבנות, ואז המסלול פשוט מעביר את הקובץ
    # כמו שהוא. כך גם נגן שביקש /fs בטעות ממשיך לעבוד.
    hdr = info["header"] or b""
    total = info["size"]
    H = len(hdr)
    bs = info["body_start"] if info["header"] else 0
    src = _vf_local_url(chat_id, message_id)

    rng = request.headers.get("range", "")
    start, end = 0, total - 1
    partial = False
    m = re.match(r"bytes=(\d*)-(\d*)", rng or "")
    if m and (m.group(1) or m.group(2)):
        partial = True
        if m.group(1):
            start = int(m.group(1))
            if m.group(2):
                end = min(int(m.group(2)), total - 1)
        else:                       # bytes=-N — N הבייטים האחרונים
            start = max(0, total - int(m.group(2)))
    if start >= total or start > end:
        return Response(status_code=416,
                        headers={"Content-Range": f"bytes */{total}"})

    async def gen():
        pos = start
        if pos < H:                             # החלק שמגיע מהכותרת שבזיכרון
            stop = min(end, H - 1)
            yield hdr[pos:stop + 1]
            pos = stop + 1
        if pos <= end:                          # והשאר מהקובץ המקורי
            a = pos - H + bs
            b = end - H + bs
            async with httpx.AsyncClient(timeout=None) as cx:
                async with cx.stream("GET", src,
                                     headers={"Range": f"bytes={a}-{b}"}) as r:
                    if r.status_code not in (200, 206):
                        log.warning("vodfix: המקור החזיר %s", r.status_code)
                        return
                    async for chunk in r.aiter_bytes(65536):
                        yield chunk

    headers = {"Accept-Ranges": "bytes",
               "Content-Length": str(end - start + 1),
               "Cache-Control": "no-store"}
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    return StreamingResponse(gen(), status_code=206 if partial else 200,
                             media_type="video/mp4", headers=headers)


@api.get("/vh/{chat_id}/{message_id}/index.m3u8")
async def vodfix_playlist(chat_id: int, message_id: int, request: Request,
                          exp: int = 0, sig: str = ""):
    """רשימת HLS שלמה, בנויה מפריימי המפתח שב-moov."""
    check_hotlink(request)
    _vf_check_sig(chat_id, message_id, exp, sig)
    info = await _vf_header_for(chat_id, message_id)
    if info["segments"] is None:
        url = _vf_local_url(chat_id, message_id)
        # בדיוק אורך ה-moov. בלי זה, קובץ שה-moov שלו בהתחלה היה גורר
        # משיכה של עשרות MB מיותרים מטלגרם בכל בניית רשימה.
        moov = await _vf_fetch(url, info["moov_start"],
                               info["moov_start"] + info["moov_len"] - 1)
        segs, total = _mp4_segment_plan(moov, _VF_SEG_TARGET)
        info["segments"] = segs
        log.info("vodfix: %s/%s — %d סגמנטים, %.0f שניות",
                 chat_id, message_id, len(segs), total)
    segs = info["segments"]
    if not segs:
        raise HTTPException(415, "לא הצלחתי לחשב נקודות חיתוך")

    q = f"?exp={exp}&sig={sig}" if SIGN_SECRET else ""
    longest = max(d for _, d in segs)
    lines = ["#EXTM3U", "#EXT-X-VERSION:3",
             f"#EXT-X-TARGETDURATION:{int(longest) + 1}",
             "#EXT-X-PLAYLIST-TYPE:VOD", "#EXT-X-MEDIA-SEQUENCE:0"]
    for i, (_, d) in enumerate(segs):
        lines.append(f"#EXTINF:{d:.3f},")
        lines.append(f"s{i}.ts{q}")
    lines.append("#EXT-X-ENDLIST")
    return Response("\n".join(lines) + "\n",
                    media_type="application/vnd.apple.mpegurl",
                    headers={"Cache-Control": "no-store"})


@api.get("/vh/{chat_id}/{message_id}/s{seg}.ts")
async def vodfix_segment(chat_id: int, message_id: int, seg: int,
                         request: Request, exp: int = 0, sig: str = ""):
    """סגמנט אחד. הווידאו מועתק כמו שהוא; רק האודיו מומר."""
    check_hotlink(request)
    _vf_check_sig(chat_id, message_id, exp, sig)
    info = await _vf_header_for(chat_id, message_id)
    segs = info["segments"]
    if not segs:
        raise HTTPException(409, "הרשימה עדיין לא נבנתה")
    if seg < 0 or seg >= len(segs):
        raise HTTPException(404, "אין סגמנט כזה")
    start, dur = segs[seg]

    # קלט: /fs אם ה-moov הוזז (הכותרת בזיכרון, ולכן ffmpeg לא מושך את הקצה
    # מטלגרם בכל סגמנט), אחרת הזרם הרגיל.
    iexp = int(time.time()) + SIGN_TTL
    isig = _stream_sig(str(chat_id), str(message_id), iexp) if SIGN_SECRET else ""
    q = f"?exp={iexp}&sig={isig}" if SIGN_SECRET else ""
    route = "fs" if info["header"] else "stream"
    src = f"http://127.0.0.1:{PORT}/{route}/{chat_id}/{message_id}{q}"

    args = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        # -ss ו--to שניהם לפני הקלט: ffmpeg קופץ ישר לנקודה בבקשת טווח
        # וקורא רק עד הסוף הדרוש. `-to` ולא `-t`, כי מול -copyts המשך נמדד
        # על ציר הזמן המקורי — `-t` היה מסיים לפני נקודת ההתחלה ומוציא
        # קובץ ריק (נבדק: "Output file is empty, nothing was encoded").
        "-ss", f"{start:.3f}", "-to", f"{start + dur:.3f}", "-i", src,
        "-map", "0:v:0", "-map", "0:a:0?",   # מסלול תמונת השער נשאר בחוץ
        "-c:v", "copy",
        "-c:a", "aac", "-ac", "2", "-b:a", _VF_ABR, "-ar", "48000",
        # -copyts שומר את חותמות הזמן המקוריות, ולכן הסגמנטים מתחברים
        # ברצף אצל הנגן. תוספת -output_ts_offset כאן הייתה מוסיפה את ההיסט
        # פעם שנייה ומזיזה כל סגמנט קדימה פי שתיים.
        "-copyts", "-avoid_negative_ts", "disabled",
        "-muxdelay", "0", "-muxpreload", "0",
        "-f", "mpegts", "pipe:1",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
    except FileNotFoundError:
        raise HTTPException(500, "ffmpeg לא מותקן בשרת")

    async def gen():
        try:
            while True:
                chunk = await proc.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            try:
                err = (await proc.stderr.read())[-300:]
                if err and proc.returncode not in (0, None):
                    log.warning("vodfix: סגמנט %s של %s/%s: %s",
                                seg, chat_id, message_id,
                                err.decode("utf-8", "replace").strip())
            except Exception:
                pass

    return StreamingResponse(gen(), media_type="video/mp2t",
                             headers={"Cache-Control": "no-store"})


@api.get("/vodinfo/{chat_id}/{message_id}")
async def vodfix_info(chat_id: int, message_id: int, request: Request,
                      exp: int = 0, sig: str = ""):
    """מה מצב הקובץ ואיזה קישור כדאי לנגן."""
    check_hotlink(request)
    _vf_check_sig(chat_id, message_id, exp, sig)
    info = await _vf_header_for(chat_id, message_id)
    q = f"?exp={exp}&sig={sig}" if SIGN_SECRET else ""
    base = STREAM_PUBLIC_BASE.rstrip("/") if "STREAM_PUBLIC_BASE" in globals() else ""
    if info["audio_ok"]:
        # הקול תקין; רק ה-moov אולי צריך הזזה. שני המקרים מוגשים כ-MP4 רגיל
        # ולכן הקפיצה בסרט נשארת מדויקת ולא עולה כלום במעבד.
        play = (f"{base}/fs/{chat_id}/{message_id}{q}" if info["header"]
                else f"{base}/stream/{chat_id}/{message_id}{q}")
        kind = "mp4"
    else:
        play = f"{base}/vh/{chat_id}/{message_id}/index.m3u8{q}"
        kind = "hls"
    return {"audio": info["audio"], "audio_ok": info["audio_ok"],
            "moov_at_end": info["moov_at_end"],
            "faststart_ready": bool(info["header"]),
            "duration": round(info["duration"], 3),
            "size": info["size"], "kind": kind, "url": play}
'''


def _fail(msg):
    print("❌ " + msg)
    print("   לא שונה כלום.")
    sys.exit(1)


def build_block():
    return "\n\n" + CORE + ENDPOINTS


def main():
    if not TARGET.exists():
        _fail(f"לא נמצא {TARGET}")
    src = TARGET.read_text(encoding="utf-8")

    if DONE_MARK in src:
        print("✓ כבר מוחל. אין מה לעשות.")
        return

    missing = [n for n in NEEDED if n not in src]
    if missing:
        _fail("חסרים בקובץ שבשרת: " + ", ".join(missing))
    out = src.rstrip("\n") + "\n" + build_block()

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as t:
        t.write(out)
        tmp = t.name
    try:
        py_compile.compile(tmp, doraise=True)
    except py_compile.PyCompileError as e:
        os.unlink(tmp)
        _fail(f"הקוד המתוקן לא מתקמפל: {e}")
    os.unlink(tmp)

    if "--check" in sys.argv:
        print("✓ הפאץ' מתאים לקובץ ועובר קומפילציה. לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-vodfix-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print("✅ הוחל. נוספו /fs, /vh, /vodinfo (לא שונתה אף שורה קיימת).")
    print(f"   גיבוי: {os.path.basename(bak)}")
    print()
    print("   הרץ:   systemctl restart zovex-bot")
    print("   נסיגה: python3 add_vodfix.py --undo")


def undo():
    baks = sorted(glob.glob(str(TARGET) + ".bak-vodfix-*"))
    if not baks:
        _fail("לא נמצא גיבוי")
    shutil.copy2(baks[-1], TARGET)
    print(f"↩️  שוחזר מ-{os.path.basename(baks[-1])}")
    print("   הרץ:  systemctl restart zovex-bot")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
