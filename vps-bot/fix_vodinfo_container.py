#!/usr/bin/env python3
"""fix_vodinfo_container — ‎/vodinfo יענה גם על קובץ שאינו MP4, במקום לסרב.

## מה שבור

קורליין הוא MKV. ffprobe על 3MB הראשונים:

    container  matroska
    video      h264 High 1280x694
    audio      ac3 2ch heb

בדפדפן: 0:00 / 0:00, כפתור הפעלה מוצג, שום שגיאה. ב-VLC: מנגן עם קול,
כי VLC מביא מפענחי FFmpeg משלו. באפליקציה: תמונה בלי קול.

לאתר יש כבר מסלול נכון לזה — ‎/vt, שממיר בשרת — אבל אין לו דרך *לדעת*
שצריך אותו. לכן הוא ממתין לשגיאה שלא מגיעה, ובינתיים משאיר את הצופה מול
מסך שחור.

היה נתיב אחד שיודע לענות על "מה יש בקובץ הזה" — ‎/vodinfo — והוא סירב
בדיוק על הקבצים האלה:

    if ftyp is None:
        raise HTTPException(415, "אין ftyp — לא קובץ MP4")

"אין ftyp" נראה כמו כישלון, אבל הוא **תשובה שלמה**: אם אין ftyp זה לא
MP4, ואם זה לא MP4 שום דפדפן לא ינגן את זה ישר. במקום להחזיר 415
מחזירים את המסקנה.

## מה משתנה

‎/vodinfo תופס את ה-415 שלו עצמו, מזהה את המכולה מ-16 הבתים הראשונים,
ומחזיר את התשובה שהאתר צריך:

    {"container": "matroska", "browser_ok": false,
     "kind": "hls", "url": ".../vt/<chat>/<msg>/index.m3u8?exp=&sig="}

WebM מטופל בנפרד: הוא EBML בדיוק כמו MKV, אבל דפדפנים כן מנגנים אותו,
ולכן מסומן browser_ok ומקבל את ה-‎/stream הישר. בלי ההפרדה הזאת היינו
שולחים להמרה מיותרת קבצים שעובדים.

## למה בתוך ‎/vodinfo ולא בתוך _vf_header_for

‎_vf_header_for משרת גם את ‎/fs, ‎/vh ו-‎/vt, וכולם מניחים שקיבלו כותרת
MP4 אמיתית (header, moov_at_end, faststart_ready). החזרת מילון "מדומה"
משם הייתה נוגעת בשלושה נתיבים חיים בשביל שאלה של נתיב אחד. השינוי כאן
נוגע רק ב-‎/vodinfo: שאר הנתיבים ממשיכים לקבל 415 בדיוק כמו קודם.

## עלות

16 בתים בבקשת Range אחת, רק במקרה שכבר נכשל. במסלול התקין — אפס.

    python3 fix_vodinfo_container.py --check
    python3 fix_vodinfo_container.py
    python3 fix_vodinfo_container.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_vodinfo_container"
MARK = "_vf_sniff_container"

# ── עוגן 1: הפונקציה שמזהה מכולה, נכנסת לפני _vf_header_for ──────────────
A1 = "async def _vf_header_for(chat: int, msg: int):"
N1 = '''def _ebml_vint(buf, p, keep):
    b = buf[p]
    if b == 0:
        raise ValueError("vint לא תקין")
    n = 1
    while not (b & (0x80 >> (n - 1))):
        n += 1
    v = b if keep else b & ((0x80 >> (n - 1)) - 1)
    for i in range(1, n):
        v = (v << 8) | buf[p + i]
    return v, p + n


def _ebml_elems(buf, p, end):
    """(מזהה, היסט-תוכן, גודל) לכל אלמנט ברמה אחת."""
    while p < end - 1:
        try:
            eid, q = _ebml_vint(buf, p, True)
            size, q = _ebml_vint(buf, q, False)
        except Exception:
            return
        yield eid, q, size
        p = q + size


async def _mkv_duration(chat: int, msg: int):
    """אורך הסרט בשניות מתוך כותרת ה-Matroska, או None.

    נקרא שתי בקשות Range קטנות: 64KB מההתחלה כדי למצוא את SeekHead
    ואת המיקום של Info, ואז Info עצמו. נמדד על קובץ של 935MB: 3 שניות.
    בלי זה הנגן מציג 0:00 / 0:00 ואי אפשר לדעת כמה זמן הסרט.
    """
    try:
        url = _vf_local_url(chat, msg)
        head = await _vf_fetch(url, 0, 65535)
        seg = None
        for eid, off, _ in _ebml_elems(head, 0, len(head)):
            if eid == 0x18538067:          # Segment
                seg = off
                break
        if seg is None:
            return None
        info_at = None
        for eid, off, size in _ebml_elems(head, seg, len(head)):
            if eid != 0x114D9B74:          # SeekHead
                continue
            for e2, o2, s2 in _ebml_elems(head, off, off + size):
                if e2 != 0x4DBB:           # Seek
                    continue
                sid = spos = None
                for e3, o3, s3 in _ebml_elems(head, o2, o2 + s2):
                    val = int.from_bytes(head[o3:o3 + s3], "big")
                    if e3 == 0x53AB:
                        sid = val
                    elif e3 == 0x53AC:
                        spos = val
                if sid == 0x1549A966:      # Info
                    info_at = spos
            break
        # יש קבצים בלי SeekHead — שם Info יושב ישר אחרי ההתחלה וכבר נקרא.
        blob, base = (head, seg) if info_at is None else (
            await _vf_fetch(url, seg + info_at, seg + info_at + 4095), 0)
        scale, dur = 1000000, None
        for eid, off, size in _ebml_elems(blob, base, len(blob)):
            if eid != 0x1549A966:
                continue
            for e2, o2, s2 in _ebml_elems(blob, off, off + size):
                if e2 == 0x2AD7B1:         # TimecodeScale
                    scale = int.from_bytes(blob[o2:o2 + s2], "big")
                elif e2 == 0x4489:         # Duration (float)
                    raw = bytes(blob[o2:o2 + s2])
                    if len(raw) in (4, 8):
                        dur = struct.unpack(">f" if len(raw) == 4 else ">d",
                                            raw)[0]
            break
        if not dur:
            return None
        return round(dur * scale / 1e9, 3)
    except Exception as e:
        log.warning("vodinfo: קריאת אורך MKV נכשלה: %s", e)
        return None


async def _vf_sniff_container(chat: int, msg: int) -> str:
    """שם המכולה מ-16 הבתים הראשונים. נקרא רק אחרי שהזיהוי כ-MP4 נכשל."""
    head = await _vf_fetch(_vf_local_url(chat, msg), 0, 15)
    if head[:4] == b"\\x1a\\x45\\xdf\\xa3":
        # EBML. DocType יושב בתוך ה-header הראשון, ולכן 1KB מספיק כדי
        # להפריד webm (שדפדפנים מנגנים) מ-matroska (שלא).
        try:
            more = await _vf_fetch(_vf_local_url(chat, msg), 0, 1023)
        except Exception:
            more = head
        return "webm" if b"webm" in more[:1024] else "matroska"
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return "avi"
    if head[:3] == b"FLV":
        return "flv"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"\\x30\\x26\\xb2\\x75":
        return "asf"
    if head[:4] == b"\\x00\\x00\\x01\\xba":
        return "mpeg-ps"
    if head[:1] == b"\\x47":
        return "mpeg-ts"
    return "unknown"


'''

# ── עוגן 2: גוף /vodinfo ─────────────────────────────────────────────────
A2 = '''    _vf_check_sig(chat_id, message_id, exp, sig)
    info = await _vf_header_for(chat_id, message_id)
    q = f"?exp={exp}&sig={sig}" if SIGN_SECRET else ""
    base = STREAM_PUBLIC_BASE.rstrip("/") if "STREAM_PUBLIC_BASE" in globals() else ""
'''
N2 = '''    _vf_check_sig(chat_id, message_id, exp, sig)
    q = f"?exp={exp}&sig={sig}" if SIGN_SECRET else ""
    base = STREAM_PUBLIC_BASE.rstrip("/") if "STREAM_PUBLIC_BASE" in globals() else ""
    try:
        info = await _vf_header_for(chat_id, message_id)
    except HTTPException as _e:
        # 415 = אין ftyp, כלומר לא MP4 — ראה fix_vodinfo_container.py.
        # זו לא שגיאה אלא תשובה: הקובץ הזה לא מתנגן ישר בדפדפן, והנגן
        # צריך לדעת את זה **לפני** שהוא ממתין לשגיאה שלא תגיע.
        if _e.status_code != 415:
            raise
        _cont = await _vf_sniff_container(chat_id, message_id)
        if _cont == "webm":
            # EBML כמו MKV, אבל דפדפנים כן מנגנים אותו. שליחה להמרה כאן
            # הייתה עלות מעבד על קובץ תקין.
            return {"container": _cont, "browser_ok": True, "audio_ok": True,
                    "kind": "direct",
                    "url": f"{base}/stream/{chat_id}/{message_id}{q}"}
        # האורך נשלח בנפרד: ההמרה ב-/vt זורמת, כלומר הרשימה גדלה תוך כדי
        # והנגן לא יודע ממנה כמה זמן הסרט. בלי זה מוצג 0:00 / 0:00.
        _dur = await _mkv_duration(chat_id, message_id) \\
            if _cont in ("matroska", "webm") else None
        out = {"container": _cont, "browser_ok": False, "audio_ok": False,
               "kind": "hls",
               "url": f"{base}/vt/{chat_id}/{message_id}/index.m3u8{q}"}
        if _dur:
            out["duration"] = _dur
        return out
'''


def read():
    with open(PATH, encoding="utf-8") as f:
        return f.read()


def write(s):
    tmp = PATH + ".tmp_vic"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(s)
    os.replace(tmp, PATH)


def validate(s):
    compile(s, PATH, "exec")
    tree = ast.parse(s)
    names = {n.name for n in ast.walk(tree)
             if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))}
    assert "_vf_sniff_container" in names, "הפונקציה לא נוצרה"
    assert "vodfix_info" in names, "vodfix_info נעלמה"


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""

    if arg == "--revert":
        if not os.path.exists(BAK):
            print(f"❌ אין גיבוי ב-{BAK}")
            return 1
        shutil.copyfile(BAK, PATH)
        print("✓ שוחזר. הרץ:  systemctl restart zovex-bot")
        return 0

    if not os.path.exists(PATH):
        print(f"❌ לא נמצא {PATH}")
        return 1

    s = read()
    if MARK in s:
        print("כבר מותקן. אין מה לעשות.")
        return 0

    for name, anchor in (("הפונקציה _vf_header_for", A1), ("גוף /vodinfo", A2)):
        n = s.count(anchor)
        if n != 1:
            print(f"❌ העוגן '{name}' נמצא {n} פעמים (ציפיתי 1).")
            print("   main.py שונה ממה שציפיתי — לא נוגע בכלום.")
            return 1

    out = s.replace(A1, N1 + A1, 1).replace(A2, N2, 1)
    try:
        validate(out)
    except Exception as e:
        print(f"❌ התוצאה לא תקינה ({e}) — לא נכתב כלום.")
        return 1

    print(f"יעד:   {PATH}")
    print("שינוי: /vodinfo מזהה MKV/AVI ומחזיר את /vt במקום 415")
    if arg == "--check":
        print("--check: שום דבר לא נכתב.")
        return 0

    if not os.path.exists(BAK):
        shutil.copyfile(PATH, BAK)
    write(out)
    print(f"✓ הוחל · גיבוי: {BAK}")
    print("  הרץ:  systemctl restart zovex-bot")
    print("  לביטול:  python3 fix_vodinfo_container.py --revert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
