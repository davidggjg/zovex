#!/usr/bin/env python3
"""fix_vodinfo_audio — ‎/vodinfo יגיד גם איזה קול יש בקובץ, ולא רק "לא דפדפן".

## מה קרה

דווח מהשטח: "סרטים וסדרות שום דבר לא משדר, רק מסך שחור עם וידיאו שבור".

השורש הוא שגיאה בהיגיון של האפליקציה, ומקורה כאן. ‎/vodinfo מחזיר
`browser_ok: false` לכל קובץ MKV — וזה **נכון**, כי שום דפדפן לא פותח
MKV. אבל האפליקציה השתמשה בפסק הדין הזה כדי להחליט עבור **הנגן
הנייטיבי**, ש*כן* מנגן MKV מצוין. הבעיה שלו היא רצועות קול מסוימות
בלבד.

כלומר האפליקציה שלחה להמרה בשרת את כל קבצי ה-MKV בקטלוג, כשרק חלק
קטן מהם באמת צריך זאת. וההמרה מוגבלת:

    _VT_MAX = int(os.environ.get("VT_MAX_CONCURRENT", "2"))
    if alive >= _VT_MAX: return None        # → 503

הצופה השלישי ואילך קיבל 503 — מסך שחור.

## מה מוסיפים

הקובץ אומר בעצמו מה יש בו. ב-Matroska, SeekHead מצביע על Tracks, ובכל
TrackEntry יש TrackType (2 = אודיו) ו-CodecID. שתי בקשות Range קטנות.

נמדד על הקובץ שדווח: `V_MPEG4/ISO/AVC` + `A_AC3 (heb)`.

לכן ‎/vodinfo יחזיר עכשיו גם:

    "audio":     ["A_AC3"]
    "native_ok": false

`native_ok` הוא השדה שהאפליקציה צריכה: האם נגן נייטיבי באנדרואיד
יסתדר עם הקול. AAC/MP3/Opus/Vorbis/FLAC/PCM — כן. AC-3, E-AC-3, DTS,
TrueHD, MLP — אנדרואיד לא מחייב יצרנים לכלול להם מפענח, ולכן לא.

`browser_ok` נשאר false כמו שהיה: לאתר זה הפסק דין הנכון, ואין שינוי
בהתנהגותו.

## למה זה משנה את העומס

רק קבצים עם קול בעייתי באמת יגיעו להמרה. שאר ה-MKV — הרוב — ינוגנו
מקומית, בלי מעבד בשרת, בלי תקרת מקביליות, ובלי 503.

    python3 fix_vodinfo_audio.py --check
    python3 fix_vodinfo_audio.py
    python3 fix_vodinfo_audio.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_vodinfo_audio"
MARK = "_mkv_audio_codecs"

# ── עוגן 1: הפונקציה החדשה, לפני מזהה המכולה ──────────────────────────────
A1 = "async def _vf_sniff_container(chat: int, msg: int) -> str:"
N1 = '''# קודקי קול שאנדרואיד אינו מחויב לפענח. אנדרואיד לא מחייב יצרנים לכלול
# מפענח Dolby/DTS, וברוב הטלפונים הוא פשוט לא קיים — ExoPlayer מדלג על
# הרצועה בשקט ומקבלים וידאו בלי קול. כל השאר (AAC, MP3, Opus, Vorbis,
# FLAC, PCM) מפוענח בכל מכשיר.
_MKV_HARD_AUDIO = ("A_AC3", "A_EAC3", "A_DTS", "A_TRUEHD", "A_MLP")


async def _mkv_audio_codecs(chat: int, msg: int):
    """שמות קודקי הקול מתוך Tracks של Matroska, או [] אם לא ניתן לברר."""
    try:
        url = _vf_local_url(chat, msg)
        head = await _vf_fetch(url, 0, 65535)
        seg = None
        for eid, off, _ in _ebml_elems(head, 0, len(head)):
            if eid == 0x18538067:              # Segment
                seg = off
                break
        if seg is None:
            return []
        tracks_at = None
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
                if sid == 0x1654AE6B:          # Tracks
                    tracks_at = spos
            break
        # בלי SeekHead — Tracks יושב ליד ההתחלה וכבר נקרא.
        blob, base_off = (head, seg) if tracks_at is None else (
            await _vf_fetch(url, seg + tracks_at, seg + tracks_at + 65535), 0)
        out = []
        for eid, off, size in _ebml_elems(blob, base_off, len(blob)):
            if eid != 0x1654AE6B:
                continue
            for e2, o2, s2 in _ebml_elems(blob, off, off + size):
                if e2 != 0xAE:                 # TrackEntry
                    continue
                ttype = codec = None
                for e3, o3, s3 in _ebml_elems(blob, o2, o2 + s2):
                    if e3 == 0x83:             # TrackType
                        ttype = int.from_bytes(blob[o3:o3 + s3], "big")
                    elif e3 == 0x86:           # CodecID
                        codec = bytes(blob[o3:o3 + s3]).decode(
                            "latin1", "replace").rstrip("\\x00")
                if ttype == 2 and codec:
                    out.append(codec)
            break
        return out
    except Exception as e:
        log.warning("vodinfo: קריאת רצועות MKV נכשלה: %s", e)
        return []


'''

# ── עוגן 2: התשובה ל-MKV, כפי שהותקנה ע"י fix_vodinfo_duration ───────────
A2 = '''        _dur = await _mkv_duration(chat_id, message_id) \\
            if _cont in ("matroska", "webm") else None
        out = {"container": _cont, "browser_ok": False, "audio_ok": False,
               "kind": "hls",
               "url": f"{base}/vt/{chat_id}/{message_id}/index.m3u8{q}"}
        if _dur:
            out["duration"] = _dur
        return out
'''
N2 = '''        _dur = await _mkv_duration(chat_id, message_id) \\
            if _cont in ("matroska", "webm") else None
        out = {"container": _cont, "browser_ok": False, "audio_ok": False,
               "kind": "hls",
               "url": f"{base}/vt/{chat_id}/{message_id}/index.m3u8{q}"}
        if _dur:
            out["duration"] = _dur
        # ── מה שנגן נייטיבי צריך לדעת ─────────────────────────────────
        # browser_ok הוא פסק דין על דפדפנים, והאפליקציה אינה דפדפן:
        # ExoPlayer מנגן MKV מצוין, ורק קודקי קול מסוימים מפילים אותו.
        # ראה fix_vodinfo_audio.py — שימוש ב-browser_ok כדי להחליט עבור
        # הנגן הנייטיבי שלח להמרה את כל ה-MKV בקטלוג, והתקרה של
        # VT_MAX_CONCURRENT החזירה 503 לכל צופה שלישי.
        if _cont in ("matroska", "webm"):
            _au = await _mkv_audio_codecs(chat_id, message_id)
            if _au:
                out["audio"] = _au
                out["native_ok"] = not any(
                    c.upper().startswith(_MKV_HARD_AUDIO) for c in _au)
        return out
'''


def validate(s):
    compile(s, PATH, "exec")
    names = {n.name for n in ast.walk(ast.parse(s))
             if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))}
    for f in ("_mkv_audio_codecs", "_mkv_duration", "_ebml_elems",
              "_vf_sniff_container", "vodfix_info"):
        assert f in names, f"{f} חסרה"
    assert '"native_ok"' in s, "native_ok לא נכנס לתשובה"
    assert s.count("_MKV_HARD_AUDIO") == 2, "רשימת הקודקים לא נוצרה פעם אחת"


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

    if "_mkv_duration" not in s:
        print("❌ הרץ קודם fix_vodinfo_duration.py.")
        return 1

    for name, anchor in (("_vf_sniff_container", A1), ("תשובת MKV", A2)):
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
    print("שינוי: /vodinfo יחזיר audio ו-native_ok לקובץ MKV")
    if arg == "--check":
        print("--check: שום דבר לא נכתב.")
        return 0

    if not os.path.exists(BAK):
        shutil.copyfile(PATH, BAK)
    tmp = PATH + ".tmp_via"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, PATH)
    print(f"✓ הוחל · גיבוי: {BAK}")
    print("  הרץ:  systemctl restart zovex-bot")
    print("  לביטול:  python3 fix_vodinfo_audio.py --revert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
