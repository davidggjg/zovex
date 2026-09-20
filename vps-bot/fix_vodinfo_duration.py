#!/usr/bin/env python3
"""fix_vodinfo_duration — ‎/vodinfo יחזיר גם את אורך הסרט לקובץ MKV.

## הבעיה

בהמרה של ‎/vt הרשימה **גדלה תוך כדי**: ffmpeg ממיר בזמן שצופים, וכל מה
שיש ברשימה הוא מה שכבר הומר. הנגן קורא ממנה את האורך, ולכן מציג
0:00 / 0:00 בהתחלה ואז מספר שמטפס. מדווח: "לא מראה כמה זמן הסרט".

## הפתרון

הקובץ עצמו יודע. ב-Matroska יש SeekHead בתחילת הקובץ שמצביע על Info,
ובתוכו TimecodeScale ו-Duration. שתי בקשות Range קטנות, בלי לגעת בגוף
הקובץ בכלל.

נמדד על הקובץ של דוד (935MB): **3 שניות**, והתוצאה 6036.16 שניות =
100.6 דקות — בדיוק אורכו של קורליין.

## למה קובץ נפרד ולא עדכון של fix_vodinfo_container

הגיבוי של אותו פאצ' נוצר לפני שהוחלו פאצ'ים מאוחרים יותר (למשל
fix_vt_copy_video). ‎--revert עליו היה מחזיר את main.py לאחור ומוחק
אותם בשקט. תוספת נפרדת לא נוגעת בגיבוי ההוא בכלל, ולכן אפשר להריץ
אותה בכל סדר.

    python3 fix_vodinfo_duration.py --check
    python3 fix_vodinfo_duration.py
    python3 fix_vodinfo_duration.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_vodinfo_duration"
MARK = "_mkv_duration"

# ── עוגן 1: הפונקציות החדשות, לפני מזהה המכולה ─────────────────────────
A1 = "async def _vf_sniff_container(chat: int, msg: int) -> str:"
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


'''

# ── עוגן 2: התשובה עצמה ────────────────────────────────────────────────
A2 = '''        return {"container": _cont, "browser_ok": False, "audio_ok": False,
                "kind": "hls",
                "url": f"{base}/vt/{chat_id}/{message_id}/index.m3u8{q}"}
'''
N2 = '''        # האורך נשלח בנפרד: ההמרה ב-/vt זורמת, כלומר הרשימה גדלה תוך כדי
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


def validate(s):
    compile(s, PATH, "exec")
    names = {n.name for n in ast.walk(ast.parse(s))
             if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))}
    for f in ("_mkv_duration", "_ebml_vint", "_ebml_elems",
              "_vf_sniff_container", "vodfix_info"):
        assert f in names, f"{f} חסרה"
    assert '"duration"' in s, "האורך לא נכנס לתשובה"


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

    with open(PATH, encoding="utf-8") as f:
        s = f.read()

    if MARK in s:
        print("כבר מותקן. אין מה לעשות.")
        return 0

    if "_vf_sniff_container" not in s:
        print("❌ הרץ קודם fix_vodinfo_container.py.")
        return 1

    for name, anchor in (("_vf_sniff_container", A1), ("תשובת /vodinfo", A2)):
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
    print("שינוי: /vodinfo יחזיר duration לקובץ MKV")
    if arg == "--check":
        print("--check: שום דבר לא נכתב.")
        return 0

    if not os.path.exists(BAK):
        shutil.copyfile(PATH, BAK)
    tmp = PATH + ".tmp_vid"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, PATH)
    print(f"✓ הוחל · גיבוי: {BAK}")
    print("  הרץ:  systemctl restart zovex-bot")
    print("  לביטול:  python3 fix_vodinfo_duration.py --revert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
