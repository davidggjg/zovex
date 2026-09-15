#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_vh_video.py — הווידאו של סמולוויל הוא MPEG-4 Part 2. שום דפדפן לא
מפענח את זה, ולכן /vh במצבו הנוכחי לא יכול לעזור לאתר.

איך זה נמדד, ולא נוחש:
    פירקתי את המקטע שהשרת מגיש. ה-PMT של ‎/vh/.../s0.ts אומר:

        stream_type=0x0f  pid=257   AAC ADTS      ← ההמרה לקול עבדה
        stream_type=0x10  pid=256   MPEG-4 Part 2 ← הווידאו הועתק כמו שהוא

    ובגוף הזרם: 133 קודי VOP, קוד VOS אחד, VOL אחד, ואפס NAL של H.264.
    כלומר וידאו MPEG-4 Visual (Xvid/DivX), Simple Profile Level 3.

    ואז פתחתי את האתר בכרום אמיתי (לא Chromium — לזה אין H.264 בכלל,
    וזו הייתה מדידה מזוהמת שכמעט הטעתה אותי), טענתי את shaka מאותו
    מקום שהאתר טוען ממנו (‎/vendor/shaka-player.compiled.js, v4.7.11)
    וקראתי ל-load על הכתובת החתומה של הפרק:

        load הצליח ב-2.7 שניות
        רצועות: אחת. codecs="mp4a.40.2", videoCodec=null, videoId=null
        videoWidth=0  videoHeight=0
        currentTime=6.05  readyState=4  בלי שגיאה

    כלומר shaka **לא נכשל** — הוא זרק את רצועת הווידאו בשקט וניגן קול
    בלבד. זה מה שהצופה באתר מקבל: מסך שחור עם סאונד.
    MediaSource.isTypeSupported('video/mp4; codecs="mp4v.20.3"') מחזיר
    false בכרום אמיתי, ולכן אין דרך לנגן את הרצועה הזאת בדפדפן.

למה זה עובד באפליקציה ולא באתר:
    האפליקציה מנגנת ב-ExoPlayer עם מפענחי ה-FFmpeg של Media3 — הוא
    מפענח MPEG-4 Part 2 בלי בעיה. בדפדפן אין מפענח כזה בכלל: לא בכרום,
    לא בפיירפוקס ולא בספארי. גם המפרק של shaka וגם זה של video.js
    (mux.js) יודעים להוציא מ-MPEG-TS רק H.264 + AAC.

    לכן אין כאן שרשרת נפילה שתעזור: video.js היה מגיע לאותה מסקנה.
    צריך להמיר את הווידאו עצמו.

מה הסקריפט עושה ב-main.py:
    1. מוסיף זיהוי קודק וידאו מתוך ה-stsd (_vf_video_codecs), באותו
       סגנון בדיוק כמו _vf_audio_codecs שכבר קיים.
    2. מוסיף info["video"] ו-info["video_ok"] ל-_vf_header_for.
    3. במקטע של /vh: במקום "-c:v copy" קבוע, הווידאו מומר ל-H.264 רק
       כשהקודק המקורי לא נתמך בדפדפן. כל השאר ממשיך להיות copy — אפס
       עלות מעבד לכל מה שעבד עד עכשיו.
    4. /vodinfo מחזיר גם video ו-video_ok, ומנתב ל-/vh גם כשהקול תקין
       אבל הווידאו לא. בלי זה פריט כזה היה נשלח ל-/stream ונשאר שבור.

מה זה עולה — נמדד בייצור אחרי ההתקנה, ולא הוערך:
    בניית מקטע (‎10 שניות תוכן, כולל משיכת המקור מטלגרם):
        s0    1,447,788 בייט   4.02 שניות
        s40   1,472,416 בייט   7.86 שניות
        s120    742,600 בייט   4.39 שניות
        s220    787,344 בייט   4.08 שניות

    כלומר פי 1.3–2.5 מהזמן האמיתי על שני ליבות, ולא פי כמה כפי שהערכתי
    לפני המדידה. נגינה רצופה בכרום: load ב-2.7 שניות, 608x336, שתי
    תקיעות בעשרים השניות הראשונות ואז הבאפר מקדים את הנגינה בכ-15
    שניות באופן יציב (בשנייה 60 הנגינה ב-52.2 והבאפר ב-67.1).

    המרווח דק. בזמן שמשכתי ארבעה מקטעים במקביל, ‎/content/lite החזיר
    פעם אחת timeout מ-nginx. אם יופיעו גמגומים אצל כמה צופים במקביל:
        VODFIX_VIDEO_THREADS=4      (מהיר יותר למקטע, פחות צופים במקביל)
        VODFIX_X264_PRESET=ultrafast (כפול מהר, קבצים גדולים יותר)
    HEVC ייכנס לאותו מסלול ויהיה כבד משמעותית.

    הפתרון הזול לטווח ארוך הוא לקודד את 215 הפרקים פעם אחת ל-H.264
    ולהחליף אותם בטלגרם. אז /vh לא נדרש בכלל והאתר מנגן MP4 רגיל.

    python3 fix_vh_video.py --check
    python3 fix_vh_video.py
    python3 fix_vh_video.py --revert
ואחריו:  systemctl restart zovex-bot
"""
import argparse, ast, os, shutil, sys
from pathlib import Path

MAIN = Path(os.environ.get("ZOVEX_MAIN", "/opt/zovex-bot/main.py"))
BAK = MAIN.with_name(MAIN.name + ".bak_vhvideo")
MARK = "# [fix_vh_video]"

# ── 1. רשימת הקודקים ──────────────────────────────────────────────────────────
A1_OLD = '_VF_BROWSER_AUDIO = {"mp4a", ".mp3", "Opus", "opus", "fLaC"}'
A1_NEW = A1_OLD + '''

''' + MARK + '''
# קודקי וידאו כפי שהם מופיעים ב-stsd. MPEG-4 Part 2 (Xvid/DivX) נשמר
# ב-MP4 בתור "mp4v" — וזה מה שיש בסמולוויל.
_VF_VIDEO_FOURCC = ("avc1", "avc3", "avc4", "hvc1", "hev1", "dvh1", "dvhe",
                    "dva1", "dvav", "mp4v", "s263", "h263", "vp08", "vp09",
                    "av01", "mjpg", "jpeg", "SVQ3", "cvid", "div3", "DIV3",
                    "DX50", "XVID", "xvid", "3iv2", "FMP4")
# /vh מגיש MPEG-TS, ולכן "נתמך" כאן פירושו: גם הדפדפן מפענח אותו וגם
# המפרק של shaka/mux.js יודע להוציא אותו מ-TS. בפועל זה H.264 בלבד.
# HEVC היה עובר את הדפדפן בחלק מהמכשירים אבל לא את המפרק, ולכן הוא
# מומר גם הוא.
_VF_BROWSER_VIDEO = {"avc1", "avc3", "avc4"}
_VF_X264_PRESET = os.environ.get("VODFIX_X264_PRESET", "veryfast")
_VF_X264_CRF = os.environ.get("VODFIX_X264_CRF", "23")
_VF_VIDEO_THREADS = os.environ.get("VODFIX_VIDEO_THREADS", "2")


def _vf_vcodec_args(info):
    """ארגומנטי הווידאו למקטע. copy כשמותר, H.264 כשחייבים.

    ‎-g/-keyint_min גדולים ובלי זיהוי חיתוכי סצנה: כל מקטע מתחיל בפריים
    מפתח ממילא (‎-ss לפני הקלט), ופריים מפתח נוסף בתוך מקטע של 10 שניות
    רק מבזבז סיביות. הקפיצה בסרט נעשית בין מקטעים ולא בתוכם.
    """
    if info.get("video_ok", True):
        return ["-c:v", "copy"]
    return ["-c:v", "libx264", "-preset", _VF_X264_PRESET,
            "-crf", _VF_X264_CRF, "-pix_fmt", "yuv420p",
            "-profile:v", "high", "-level", "4.0",
            "-sc_threshold", "0", "-g", "250", "-keyint_min", "250",
            "-threads", _VF_VIDEO_THREADS]'''

# ── 2. זיהוי הקודק מתוך ה-moov ────────────────────────────────────────────────
A2_OLD = '''    walk(0, len(moov))
    return out


async def _vf_header_for(chat: int, msg: int):'''
A2_NEW = '''    walk(0, len(moov))
    return out


''' + MARK + '''
def _vf_video_codecs(moov: bytes):
    """שמות קודקי הווידאו, מתוך אותן טבלאות stsd כמו באודיו."""
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
                    if fmt.startswith(_VF_VIDEO_FOURCC):
                        out.append(fmt)
                    p += esz
    walk(0, len(moov))
    return out


async def _vf_header_for(chat: int, msg: int):'''

# ── 3. השדות במידע על הקובץ ───────────────────────────────────────────────────
A3_OLD = '''            "audio": _vf_audio_codecs(moov), "header": None,'''
A3_NEW = ('''            "audio": _vf_audio_codecs(moov),
            "video": _vf_video_codecs(moov),   ''' + MARK + '''
            "header": None,''')

A4_OLD = '''    info["audio_ok"] = any(c in _VF_BROWSER_AUDIO for c in info["audio"])'''
A4_NEW = A4_OLD + '''
    ''' + MARK + '''
    # בלי רצועת וידאו מזוהה לא ממירים כלום — שינוי התנהגות בלי סיבה הוא
    # הדרך הבטוחה לשבור פריטים שעבדו.
    info["video_ok"] = (not info["video"]
                        or any(c in _VF_BROWSER_VIDEO for c in info["video"]))'''

# ── 4. בניית המקטע ────────────────────────────────────────────────────────────
A5_OLD = '''        "-map", "0:v:0", "-map", "0:a:0?",   # מסלול תמונת השער נשאר בחוץ
        "-c:v", "copy",'''
A5_NEW = '''        "-map", "0:v:0", "-map", "0:a:0?",   # מסלול תמונת השער נשאר בחוץ
        ''' + MARK + '''  copy כברירת מחדל, H.264 רק לקודק שהדפדפן לא מפענח
        *_vf_vcodec_args(info),'''

# ── 5. הניתוב ב-vodinfo ───────────────────────────────────────────────────────
A6_OLD = '''    if info["audio_ok"]:'''
A6_NEW = (MARK + '''  גם וידאו שהדפדפן לא מפענח חייב לעבור ב-/vh
    if info["audio_ok"] and info["video_ok"]:''')

A7_OLD = '''    return {"audio": info["audio"], "audio_ok": info["audio_ok"],'''
A7_NEW = '''    return {"audio": info["audio"], "audio_ok": info["audio_ok"],
            "video": info["video"], "video_ok": info["video_ok"],  ''' + MARK

PATCHES = [("רשימת הקודקים", A1_OLD, A1_NEW),
           ("זיהוי קודק הווידאו", A2_OLD, A2_NEW),
           ("שדה video במידע", A3_OLD, A3_NEW),
           ("video_ok", A4_OLD, A4_NEW),
           ("בניית המקטע", A5_OLD, A5_NEW),
           ("ניתוב ב-vodinfo", A6_OLD, A6_NEW),
           ("תשובת vodinfo", A7_OLD, A7_NEW)]


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True); raise


def validate(src: str) -> None:
    """תחביר, ואחר כך שמות: compile בודק רק תחביר, ופונקציה שנקראת ולא
    קיימת עוברת אותו בשקט ומתפוצצת בייצור."""
    compile(src, str(MAIN), "exec")
    tree = ast.parse(src)
    top = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            top.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    top.add(t.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                top.add((a.asname or a.name).split(".")[0])
    need = ["_vf_video_codecs", "_vf_vcodec_args", "_VF_VIDEO_FOURCC",
            "_VF_BROWSER_VIDEO", "_VF_X264_PRESET", "_VF_X264_CRF",
            "_VF_VIDEO_THREADS"]
    missing = [n for n in need if n not in top]
    if missing:
        sys.exit(f"  ✗ הוגדרו חסרים ברמת המודול: {missing}")
    # התלויות שהקוד החדש מסתמך עליהן וכבר קיימות בקובץ
    for n in ("_mp4_boxes", "_MP4_CONTAINERS", "struct", "os"):
        if n not in top:
            sys.exit(f"  ✗ {n} לא מוגדר ברמת המודול — הקוד החדש נשען עליו")
    print(f"  ✓ תחביר תקין, {len(need)} שמות חדשים מוגדרים, "
          f"4 תלויות קיימות אומתו")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    if a.revert:
        if not BAK.exists():
            sys.exit(f"אין גיבוי ב-{BAK}")
        shutil.copy2(BAK, MAIN)
        print(f"✓ שוחזר מ-{BAK}\n  צריך:  systemctl restart zovex-bot")
        return
    if not MAIN.exists():
        sys.exit(f"לא נמצא: {MAIN}")

    src = MAIN.read_text(encoding="utf-8")
    if MARK in src:
        print("✓ הטלאי כבר מותקן. אין מה לעשות.")
        return

    out = src
    for name, old, new in PATCHES:
        n = out.count(old)
        if n != 1:
            sys.exit(f"  ✗ '{name}': העוגן נמצא {n} פעמים במקום אחת — "
                     f"לא נוגעים בקובץ")
        out = out.replace(old, new, 1)
        print(f"  ✓ {name}")

    print()
    validate(out)

    if a.check:
        print(f"\n--check: שום דבר לא נכתב. "
              f"{len(out) - len(src)} בייטים ייווספו.")
        return

    shutil.copy2(MAIN, BAK)
    atomic_write(MAIN, out)
    # שחזור בייט-בבייט חייב להיות אפשרי, ולכן מאמתים שהגיבוי זהה למקור
    if BAK.read_text(encoding="utf-8") != src:
        sys.exit("  ✗ הגיבוי לא זהה למקור — לא ממשיכים")
    print(f"\n✓ נכתב. גיבוי: {BAK}")
    print("⚠ צריך:  systemctl restart zovex-bot")
    print("  ה-restart מנתק צופים פעילים. לעשות כשאין תנועה.")
    print("\nאחרי ה-restart, לאימות (הכתובת החתומה מגיעה מ-/content/lite):")
    print('  curl -sS "https://zovex.duckdns.org/vodinfo/-1003936100530/9250'
          '?exp=...&sig=..." | python3 -m json.tool')
    print('  אמור להראות  "video": ["mp4v"],  "video_ok": false')


if __name__ == "__main__":
    main()
