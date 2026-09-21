#!/usr/bin/env python3
"""fix_vh_matroska — ‎/vh יעבוד גם על MKV, וכך דילוג והמשך-צפייה יחזרו.

## מה דווח

"מתחיל את הסרט, מעביר קדימה וזה חוזר אחורה, ואז עד שאני מגיע למקום
שעצרתי זה עובד דקה ונעצר."

שלושת התסמינים הם אותו שורש אחד: הקובץ עובר ב-‎/vt, שממיר **תוך כדי
צפייה** מ-0 והלאה. הפלייליסט מכיל רק את מה שהומר עד כה, ולכן אין לאן
לדלג, המשך-צפייה מדקה 40 מצביע למקום שלא קיים, וכשהצופה מדביק את קצה
ההמרה — נגמרו המקטעים.

‎/vh הוא המסלול הנכון: מעתיק את הווידאו, ממיר רק את הקול, ומגיש
פלייליסט **VOD שלם** מהבקשה הראשונה — אורך נכון, דילוג לכל מקום,
המשך-צפייה עובד. הוא סירב ל-MKV רק כי הוא בנה את נקודות החיתוך מה-moov
של MP4.

## מאיפה נקודות החיתוך ב-MKV

מ-Cues, אינדקס נקודות המפתח שבקובץ עצמו. SeekHead בתחילת הקובץ מצביע
עליו. נמדד על הקובץ שדווח: **1,595 נקודות, שתי בקשות Range, 3 שניות.**

## הפיצוי על ה-seek של ffmpeg

‎-ss על MKV **לא** נוחת על הזמן שביקשו. נמדד, ועקבי ב-3 מתוך 3:

    ביקשתי 252.185 → התחיל 243.619
    ביקשתי 256.315 → התחיל 254.421
    ביקשתי 261.737 → התחיל 259.134

בכל המקרים: ה-cue **שלפני** ה-cue הגדול ביותר שקטן מהבקשה. ההסבר הסביר
הוא שה-Cues כאן קיימים רק למסלול הווידאו (אומת: TrackNumber=1 וידאו,
2 אודיו), ולכן ffmpeg נסוג נקודה אחת כדי שיהיה לו גם קול.

זה דטרמיניסטי, ולכן אפשר לפצות: כדי להתחיל ב-cue מסוים, מבקשים זמן מיד
אחרי ה-cue **הבא**. אומת על שני מקטעים רצופים — שניהם התחילו בדיוק
בגבול המתוכנן.

## מה שהפאצ' שומר בכוונה

* ‎_vf_header_for לא נוגעים בו. הוא ממשיך לזרוק 415 על MKV, וזה מה
  ששומר על ‎native_ok ב-‎/vodinfo — השדה שמונע מהאפליקציה לשלוח להמרה
  קבצים שמתנגנים מקומית מצוין.
* מטמון נפרד (‎_mkv_plan_cache) ולא ‎_vf_cache. שמירה במטמון המשותף
  הייתה גורמת ל-‎_vf_header_for להחזיר אותו מהמטמון ולא לזרוק 415 —
  ואז ‎/vodinfo היה מאבד את ‎native_ok.
* המקטע הראשון בלי ‎-ss בכלל: 0.0 הוא ה-cue הראשון ואין לפניו מה
  לפצות עליו.
* כל מקטע פורש **שני מרווחי cue לפחות**, אחרת זמן ה-seek המפוצה היה
  עובר את סוף המקטע ומוציא קובץ ריק.

## אם זה נכשל

‎--revert מחזיר את ‎/vodinfo להחזיר ‎/vt, כלומר בדיוק המצב של היום.

    python3 fix_vh_matroska.py --check
    python3 fix_vh_matroska.py
    python3 fix_vh_matroska.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_vh_matroska"
MARK = "_mkv_segment_plan"

# ── 1. התוכנית מ-Cues ────────────────────────────────────────────────────
A1 = "async def _vf_sniff_container(chat: int, msg: int) -> str:"
N1 = '''_MKV_SEG_TARGET = float(os.environ.get("MKV_SEG", "10"))
_mkv_plan_cache: dict = {}        # (chat,msg) -> (זמן, info)
_MKV_PLAN_TTL = 6 * 3600


def _mkv_seek_table(head, seg):
    """{SeekID: מיקום יחסי לתחילת ה-Segment} מתוך SeekHead."""
    out = {}
    for eid, off, size in _ebml_elems(head, seg, len(head)):
        if eid != 0x114D9B74:              # SeekHead
            continue
        for e2, o2, s2 in _ebml_elems(head, off, off + size):
            if e2 != 0x4DBB:               # Seek
                continue
            sid = spos = None
            for e3, o3, s3 in _ebml_elems(head, o2, o2 + s2):
                val = int.from_bytes(head[o3:o3 + s3], "big")
                if e3 == 0x53AB:
                    sid = val
                elif e3 == 0x53AC:
                    spos = val
            if sid is not None and spos is not None:
                out[sid] = spos
        break
    return out


async def _mkv_segment_plan(chat: int, msg: int):
    """[(התחלה, משך, זמן-seek-מפוצה)] ואורך הקובץ, מתוך ה-Cues.

    ראה fix_vh_matroska.py: זמן ה-seek אינו זמן ההתחלה, כי ffmpeg נוסע
    ל-cue שלפני מה שביקשו. הפיצוי נמדד ואומת.
    """
    url = _vf_local_url(chat, msg)
    head = await _vf_fetch(url, 0, 65535)
    seg = None
    for eid, off, _ in _ebml_elems(head, 0, len(head)):
        if eid == 0x18538067:              # Segment
            seg = off
            break
    if seg is None:
        raise HTTPException(415, "לא נמצא Segment ב-EBML")
    table = _mkv_seek_table(head, seg)

    # TimecodeScale + Duration
    scale, dur = 1000000, None
    ipos = table.get(0x1549A966)
    blob, base = (head, seg) if ipos is None else (
        await _vf_fetch(url, seg + ipos, seg + ipos + 4095), 0)
    for eid, off, size in _ebml_elems(blob, base, len(blob)):
        if eid != 0x1549A966:              # Info
            continue
        for e2, o2, s2 in _ebml_elems(blob, off, off + size):
            if e2 == 0x2AD7B1:
                scale = int.from_bytes(blob[o2:o2 + s2], "big")
            elif e2 == 0x4489:
                raw = bytes(blob[o2:o2 + s2])
                if len(raw) in (4, 8):
                    dur = struct.unpack(">f" if len(raw) == 4 else ">d",
                                        raw)[0]
        break
    if not dur:
        raise HTTPException(415, "אין Duration בכותרת ה-MKV")
    total = dur * scale / 1e9

    cpos = table.get(0x1C53BB6B)
    if cpos is None:
        raise HTTPException(415, "אין Cues — בלי אינדקס אין נקודות חיתוך")
    cb = await _vf_fetch(url, seg + cpos, seg + cpos + 4 * 1024 * 1024)
    times = []
    for eid, off, size in _ebml_elems(cb, 0, len(cb)):
        if eid != 0x1C53BB6B:              # Cues
            continue
        for e2, o2, s2 in _ebml_elems(cb, off, off + size):
            if e2 != 0xBB:                 # CuePoint
                continue
            for e3, o3, s3 in _ebml_elems(cb, o2, o2 + s2):
                if e3 == 0xB3:             # CueTime
                    times.append(
                        int.from_bytes(cb[o3:o3 + s3], "big") * scale / 1e9)
        break
    cues = sorted(set(t for t in times if 0 <= t < total))
    if len(cues) < 4:
        raise HTTPException(415, f"רק {len(cues)} נקודות מפתח — מעט מדי")

    plan = []
    i = 0
    while i < len(cues) - 1:
        start = cues[i]
        j = i + 1
        # שני מרווחים לפחות: בלי זה זמן ה-seek המפוצה עובר את סוף המקטע.
        while j < len(cues) - 1 and (j - i < 2 or cues[j] - start
                                     < _MKV_SEG_TARGET):
            j += 1
        end = cues[j]
        seek = None if i == 0 else cues[i + 1] + 0.10
        plan.append((start, end - start, seek))
        i = j
    if plan:
        s0, _, sk = plan[-1]
        plan[-1] = (s0, max(total - s0, 0.1), sk)
    log.info("vh-mkv: %s/%s — %d מקטעים מ-%d נקודות מפתח, %.0f שניות",
             chat, msg, len(plan), len(cues), total)
    return plan, total


async def _vf_info_or_mkv(chat: int, msg: int):
    """מידע ל-/vh. MP4 כמו קודם; MKV — תוכנית מ-Cues."""
    try:
        return await _vf_header_for(chat, msg)
    except HTTPException as e:
        if e.status_code != 415:
            raise
        key = (int(chat), int(msg))
        ent = _mkv_plan_cache.get(key)
        now = time.time()
        if ent and now - ent[0] < _MKV_PLAN_TTL:
            return ent[1]
        if await _vf_sniff_container(chat, msg) not in ("matroska", "webm"):
            raise
        plan, total = await _mkv_segment_plan(chat, msg)
        info = {"segments": plan, "header": None, "moov_at_end": False,
                "moov_start": None, "moov_len": None, "audio": [],
                "audio_ok": False, "duration": total, "size": None}
        _mkv_plan_cache[key] = (now, info)
        return info


'''

# ── 2. שני נתיבי /vh קוראים למידע דרך העוטף ─────────────────────────────
A2 = '''    info = await _vf_header_for(chat_id, message_id)
    if info["segments"] is None:
        url = _vf_local_url(chat_id, message_id)'''
N2 = '''    info = await _vf_info_or_mkv(chat_id, message_id)
    if info["segments"] is None:
        url = _vf_local_url(chat_id, message_id)'''

A3 = '''    info = await _vf_header_for(chat_id, message_id)
    # בונים את התוכנית אם היא חסרה, במקום לדחות.'''
N3 = '''    info = await _vf_info_or_mkv(chat_id, message_id)
    # בונים את התוכנית אם היא חסרה, במקום לדחות.'''

# ── 3. הפלייליסט והמקטע — פריטי תוכנית באורך 2 או 3 ─────────────────────
A4 = "    longest = max(d for _, d in segs)"
N4 = "    longest = max(s[1] for s in segs)"

A5 = "    for i, (_, d) in enumerate(segs):"
N5 = "    for i, d in ((n, s[1]) for n, s in enumerate(segs)):"

A6 = "    start, dur = segs[seg]"
N6 = '''    ent = segs[seg]
    start, dur = ent[0], ent[1]
    # ב-MKV זמן ה-seek שונה מזמן ההתחלה — ראה fix_vh_matroska.py.
    seek_at = ent[2] if len(ent) > 2 and ent[2] is not None else start'''

A7 = '"-ss", f"{start:.3f}", "-to", f"{start + dur:.3f}", "-i", src,'
N7 = '"-ss", f"{seek_at:.3f}", "-to", f"{start + dur:.3f}", "-i", src,'

# ── 4. /vodinfo מפנה ל-/vh במקום /vt ────────────────────────────────────
A8 = '''        out = {"container": _cont, "browser_ok": False, "audio_ok": False,
               "kind": "hls",
               "url": f"{base}/vt/{chat_id}/{message_id}/index.m3u8{q}"}'''
N8 = '''        # ‎/vh ולא ‎/vt: אותה המרה של קול, אבל פלייליסט VOD שלם, ולכן
        # דילוג והמשך-צפייה עובדים. ראה fix_vh_matroska.py.
        #
        # אבל רק אם באמת אפשר לבנות תוכנית מ-Cues. בונים אותה כאן ולא
        # מניחים: ל-AVI אין אינדקס כזה בכלל, ויש גם קובצי MKV בלי Cues,
        # ושליחתם ל-‎/vh הייתה מחזירה 415 במקום לנגן. התוצאה נשמרת
        # במטמון, ולכן הבקשה הראשונה ל-‎/vh כבר מהירה.
        _route = "vt"
        if _cont in ("matroska", "webm"):
            try:
                await _vf_info_or_mkv(chat_id, message_id)
                _route = "vh"
            except Exception as _pe:
                log.info("vodinfo: %s/%s בלי תוכנית Cues (%s) — נשאר /vt",
                         chat_id, message_id, _pe)
        out = {"container": _cont, "browser_ok": False, "audio_ok": False,
               "kind": "hls",
               "url": f"{base}/{_route}/{chat_id}/{message_id}/index.m3u8{q}"}'''

EDITS = [("_vf_sniff_container", A1, N1 + A1),
         ("קריאת מידע בפלייליסט", A2, N2),
         ("קריאת מידע במקטע", A3, N3),
         ("חישוב TARGETDURATION", A4, N4),
         ("לולאת EXTINF", A5, N5),
         ("פירוק פריט תוכנית", A6, N6),
         ("ארגומנט -ss", A7, N7),
         ("כתובת ב-/vodinfo", A8, N8)]


def validate(s):
    compile(s, PATH, "exec")
    names = {n.name for n in ast.walk(ast.parse(s))
             if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))}
    for f in ("_mkv_segment_plan", "_vf_info_or_mkv", "_mkv_seek_table",
              "_vf_header_for", "vodfix_playlist", "vodfix_segment",
              "vodfix_info"):
        assert f in names, f"{f} חסרה"
    # _vf_header_for חייב להמשיך לזרוק 415, אחרת /vodinfo מאבד native_ok
    assert 'raise HTTPException(415, "אין ftyp — לא קובץ MP4")' in s, \
        "_vf_header_for שונה — native_ok בסיכון"
    assert '"native_ok"' in s, "native_ok נעלם מ-/vodinfo"
    tail = s.split("async def vodfix_info")[-1]
    assert '_route = "vt"' in tail, "/vodinfo לא בוחר מסלול"
    assert '{_route}/{chat_id}' in tail, "/vodinfo לא משתמש במסלול שנבחר"
    # שני נתיבי /vh עברו לעוטף, ועוד קריאה אחת מ-/vodinfo לבדיקת המסלול.
    assert s.count("info = await _vf_info_or_mkv(chat_id, message_id)") == 2, \
        "לא שני נתיבי /vh עברו לעוטף"
    assert s.count("_vf_info_or_mkv(chat_id, message_id)") == 3, \
        "מספר הקריאות לעוטף אינו כצפוי"


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""

    if arg == "--revert":
        if not os.path.exists(BAK):
            print(f"❌ אין גיבוי ב-{BAK}")
            return 1
        shutil.copyfile(BAK, PATH)
        print("✓ שוחזר — /vodinfo חוזר להחזיר /vt.")
        print("  הרץ:  systemctl restart zovex-bot")
        return 0

    if not os.path.exists(PATH):
        print(f"❌ לא נמצא {PATH}")
        return 1

    with open(PATH, encoding="utf-8") as f:
        s = f.read()

    if MARK in s:
        print("כבר מותקן. אין מה לעשות.")
        return 0

    for need, why in (("_ebml_elems", "fix_vodinfo_duration.py"),
                      ("_vf_sniff_container", "fix_vodinfo_container.py"),
                      ("_mkv_audio_codecs", "fix_vodinfo_audio.py")):
        if need not in s:
            print(f"❌ הרץ קודם {why}.")
            return 1

    out = s
    for name, a, b in EDITS:
        n = out.count(a)
        if n != 1:
            print(f"❌ העוגן '{name}' נמצא {n} פעמים (ציפיתי 1).")
            print("   main.py שונה ממה שציפיתי — לא נוגע בכלום.")
            return 1
        out = out.replace(a, b, 1)

    try:
        validate(out)
    except Exception as e:
        print(f"❌ התוצאה לא תקינה ({e}) — לא נכתב כלום.")
        return 1

    print(f"יעד:   {PATH}")
    print("שינוי: /vh יתמוך ב-MKV, ו-/vodinfo יפנה אליו במקום /vt")
    if arg == "--check":
        print("--check: שום דבר לא נכתב.")
        return 0

    if not os.path.exists(BAK):
        shutil.copyfile(PATH, BAK)
    tmp = PATH + ".tmp_vhmkv"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, PATH)
    print(f"✓ הוחל · גיבוי: {BAK}")
    print("  הרץ:  systemctl restart zovex-bot")
    print("  לביטול:  python3 fix_vh_matroska.py --revert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
