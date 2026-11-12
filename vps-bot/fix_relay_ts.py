#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_relay_ts — שידור חי שהמקור שלו זרם TS גולמי (בלי .m3u8).

## התקלה
ספקי IPTV (פאנל Xtream) נותנים קישור כמו ‎/user/pass/12345‎ שמחזיר זרם
MPEG-TS אינסופי. VLC מנגן אותו; דפדפן, Shaka, אייפון והאפליקציה — לא.
הרלֵיי הרגיל מעביר אותו כמו שהוא, וזה לא עוזר. גרוע מזה: מסלול המקטעים
של הרלֵיי צובר את התשובה בזיכרון, כך שזרם אינסופי דרכו מנפח זיכרון.

## הפתרון
מצב TS במסלול ההמרה הקיים (‎/hls-relay/_fix/‎). נתיב שמסתיים ב-‎/__ts.m3u8‎:
  · ffmpeg מושך את ה-TS **ישירות מהספק** (לא דרך הרלֵיי — אין צבירה בזיכרון),
    עם אותו User-Agent שהרלֵיי שולח, ובלי האסימון הפנימי שלנו.
  · אורז ל-HLS עם ‎-c copy‎ (כשהקודק H.264 — כמעט אפס מעבד), מגיש index.m3u8.
  · בדיקת החיות קוראת כמה מאות בייטים ומוודאת סנכרון TS (0x47) — במקום
    לחכות לסוף של זרם שאין לו סוף.
ערוצים קיימים לא מושפעים: בלי הסיומת ‎/__ts.m3u8‎ שום דבר לא משתנה.

    MAIN_PY=... python3 fix_relay_ts.py --check | (ריק) | --revert
"""
import os, re, shutil, sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
MARKER = "[fix_relay_ts]"

HELPERS = r'''# ── [fix_relay_ts] שידור חי שמקורו זרם TS גולמי ────────────────────────────
HLS_TS_SUFFIX = "/__ts.m3u8"


def _hls_src_path(path: str):
    """[fix_relay_ts] ‎(נתיב המקור, האם זרם TS גולמי)‎."""
    if path.endswith(HLS_TS_SUFFIX):
        return path[:-len(HLS_TS_SUFFIX)], True
    return path, False


def _hls_ts_upstream(host: str, upath: str):
    """[fix_relay_ts] הכתובת אצל הספק. רק למארח מורשה — בדיוק כמו הרלֵיי."""
    base, _, port = host.partition(":")
    o = _relay_origin_for(base)
    if o is None:
        return None
    scheme = o["scheme"]
    p = int(port) if port.isdigit() else o["port"]
    dflt = 443 if scheme == "https" else 80
    netloc = base if p == dflt else f"{base}:{p}"
    return f"{scheme}://{netloc}/{upath}"


async def _hls_ts_alive(host: str, upath: str):
    """[fix_relay_ts] קוראים כמה מאות בייטים ובודקים סנכרון TS, ולא את כל
    התשובה — לזרם חי אין סוף, ו-‎.get()‎ רגיל היה מחכה עד פסק הזמן."""
    url = _hls_ts_upstream(host, upath)
    if not url:
        return False, "המארח אינו ברשימה המותרת"
    buf = b""
    try:
        async with _hls_relay_client.stream(
                "GET", url, headers=HLS_RELAY_UPSTREAM_HEADERS,
                timeout=max(HLS_UP_PROBE_TIMEOUT, 8)) as r:
            if r.status_code != 200:
                return False, f"המקור החזיר {r.status_code}"
            async for ch in r.aiter_bytes():
                buf += ch
                if len(buf) >= 188 * 4:
                    break
    except Exception as e:
        return False, f"המקור לא ענה ({type(e).__name__})"
    i = buf.find(b"\x47")
    if i < 0 or len(buf) < i + 189 or buf[i + 188] != 0x47:
        return False, "המקור אינו זרם TS"
    _hls_dead.pop(_hls_fix_key(host, upath + HLS_TS_SUFFIX), None)
    return True, ""


'''


def func_span(src, header):
    s = src.index(header)
    m = re.compile(r"\n(?=(?:@api\.|async def |def |class )\S)").search(src, s + len(header))
    return s, (m.start() if m else len(src))


def sub_in(src, header, old, new, count=1):
    s, e = func_span(src, header)
    body = src[s:e]
    c = body.count(old)
    assert c >= count, f"ב-{header.strip()[:40]}: '{old[:50]}' נמצא {c} (ציפינו {count})"
    if count == 1:
        assert c == 1, f"ב-{header.strip()[:40]}: '{old[:50]}' נמצא {c} פעמים"
    body = body.replace(old, new)
    return src[:s] + body + src[e:]


def apply(src):
    if MARKER in src:
        print("✓ כבר מותקן"); return src
    # 1. עזרים לפני _hls_upstream_alive
    h = "async def _hls_upstream_alive(host: str, path: str):"
    i = src.index(h)
    out = src[:i] + HELPERS + src[i:]
    # 2. בדיקת חיות: מצב TS
    out = sub_in(out, h,
        '    src = f"http://127.0.0.1:{PORT}/hls-relay/{host}/{path}"\n',
        '    _upath, _is_ts = _hls_src_path(path)   # [fix_relay_ts]\n'
        '    if _is_ts:\n'
        '        return await _hls_ts_alive(host, _upath)\n'
        '    src = f"http://127.0.0.1:{PORT}/hls-relay/{host}/{path}"\n')
    # 3. הפעלת ffmpeg: קלט ישיר מהספק במצב TS
    h2 = "async def _hls_fix_start(host: str, path: str, profile: int = 0)"
    out = sub_in(out, h2,
        '        src = f"http://127.0.0.1:{PORT}/hls-relay/{host}/{path}"\n',
        '        src = f"http://127.0.0.1:{PORT}/hls-relay/{host}/{path}"\n'
        '        _in_hdr = ["-headers", f"x-zovex-probe: {HLS_PROBE_TOKEN}\\r\\n"]\n'
        '        _upath, _is_ts = _hls_src_path(path)   # [fix_relay_ts]\n'
        '        if _is_ts:\n'
        '            # ישירות מהספק: מסלול המקטעים של הרלֵיי צובר בזיכרון, וזרם\n'
        '            # אינסופי דרכו מנפח זיכרון. האסימון הפנימי לא נשלח לספק.\n'
        '            src = _hls_ts_upstream(host, _upath)\n'
        '            if not src:\n'
        '                return None\n'
        '            _in_hdr = ["-user_agent", HLS_RELAY_UPSTREAM_HEADERS["User-Agent"]]\n')
    out = sub_in(out, h2,
        '            "-headers", f"x-zovex-probe: {HLS_PROBE_TOKEN}\\r\\n",\n',
        '            *_in_hdr,   # [fix_relay_ts]\n')
    # 4. נפילה למסלול הרגיל — לנתיב המקור, לא לסיומת הסינתטית
    h3 = "async def hls_relay_fixed(host: str, path: str, request: Request):"
    out = sub_in(out, h3,
        'RedirectResponse(f"/hls-relay/{host}/{path}"',
        'RedirectResponse(f"/hls-relay/{host}/{_hls_src_path(path)[0]}"', count=3)
    compile(out, "main.py", "exec")
    return out


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read()
    bak = PATH + ".bak_relay_ts"
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        assert os.path.exists(bak), "אין גיבוי"
        shutil.copy2(bak, PATH); print("✓ שוחזר מהגיבוי"); return 0
    out = apply(src)
    if arg == "--check": print("✓ בדיקה עברה — לא נכתב כלום"); return 0
    if MARKER in src: return 0
    shutil.copy2(PATH, bak)
    open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", bak); return 0


if __name__ == "__main__":
    sys.exit(main())
