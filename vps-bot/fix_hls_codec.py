#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ממיר ל-H.264 רק את הערוצים שחייבים, ומשאיר את השאר כמו שהם.

מה נמדד: ערוץ שעובד ב-VLC ובגוגל ולא באתר ולא באפליקציה. פענוח ה-init.mp4
שהרלֵיי מייצר לו הראה:

    מסלול וידאו → קודק: mp4v          (MPEG-4 Part 2, מתקופת DivX)
    מסלול אודיו → קודק: mp4a, 48kHz   (AAC תקין)

`mp4v` אינו H.264. VLC מנגן אותו, אבל Media Source Extensions בדפדפנים תומך
רק ב-avc1/avc3 ובאופן חלקי ב-HEVC/VP9/AV1 — לא ב-mp4v. לכן זה מסך שחור באתר
ובאפליקציה בעוד הקישור עצמו "עובד".

הסיבה בקוד היא שורה אחת: הצינור מריץ `-c copy`, כלומר מעתיק גם וידאו וגם
אודיו ורק מחליף מיכל. ערוץ שמקורו H.264 יוצא תקין; ערוץ שמקורו משהו אחר יוצא
כמו שהוא, ונשבר בדפדפן.

למה לא פשוט להמיר את כולם: 56 ערוצים עוברים דרך הצינור הזה. קידוד חי של כולם
היה מכלה את המעבד של השרת ופוגע גם בצפייה בסרטים. לכן קודק המקור נבדק פעם
אחת ב-ffprobe, נשמר בזיכרון לשעה, ורק מי שאינו H.264 מומר. עבור הרוב לא
משתנה כלום ולא נצרך מעבד נוסף.

אם ffprobe אינו מותקן, או שהבדיקה נכשלה — חוזרים להתנהגות הנוכחית בדיוק
(`-c copy`). עדיף להשאיר ערוץ כמו שהוא מאשר להעמיס קידוד על סמך ניחוש.

    python3 fix_hls_codec.py --check   # בודק בלי לשנות
    python3 fix_hls_codec.py           # מחיל
    python3 fix_hls_codec.py --undo    # מחזיר
"""
import datetime, glob, os, pathlib, py_compile, re, shutil, sys, tempfile

TARGET = pathlib.Path("/opt/zovex-bot/main.py")
DONE_MARK = "_hls_codec_args"

HELPERS = '''
# ── בחירת הקודק לערוצים חיים ────────────────────────────────────────────────
# הצינור הזה עשה `-c copy` על הכול, כלומר החליף מיכל בלי לגעת בזרמים. זה נכון
# ויעיל לערוץ שמקורו H.264 — אבל ערוץ שמקורו MPEG-4 Part 2 יצא מכאן כ-mp4v,
# ושום דפדפן אינו מפענח mp4v ב-MSE. התוצאה היא ערוץ שעובד ב-VLC ומסך שחור
# באתר.
#
# הבדיקה נעשית פעם אחת לערוץ ונשמרת לשעה, כי קידוד חי של 56 ערוצים היה מכלה
# את המעבד. מי שכבר H.264 ממשיך ב-copy ולא עולה כלום.
_HLS_VCODEC_TTL = 3600
_hls_vcodec_cache: dict = {}


def _hls_probe_vcodec(url: str):
    """שם קודק הווידאו של המקור, או None אם לא ניתן לברר. חוסם."""
    import shutil as _sh, subprocess
    exe = _sh.which("ffprobe")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name",
             "-of", "default=nw=1:nk=1", "-analyzeduration", "3000000",
             "-probesize", "3000000", url],
            capture_output=True, text=True, timeout=25).stdout.strip().splitlines()
        return out[0].strip() if out else None
    except Exception as e:
        log.warning("hls_codec: ffprobe נכשל על %s: %s", url, e)
        return None


async def _hls_codec_args(host: str, path: str, src: str):
    """הארגומנטים שקובעים איך לטפל בזרמים. copy כברירת מחדל."""
    key = f"{host}/{path}"
    now = time.time()
    ent = _hls_vcodec_cache.get(key)
    if ent is None or now - ent[0] > _HLS_VCODEC_TTL:
        loop = asyncio.get_running_loop()
        codec = await loop.run_in_executor(None, _hls_probe_vcodec, src)
        _hls_vcodec_cache[key] = (now, codec)
        ent = _hls_vcodec_cache[key]
        log.info("hls_codec: %s → קודק מקור %s", key, codec or "לא ידוע")
    codec = ent[1]
    # לא ידוע, או כבר H.264 — לא נוגעים. זו ההתנהגות שהייתה כאן תמיד.
    if not codec or codec == "h264":
        return ["-c", "copy", "-bsf:a", "aac_adtstoasc"]
    # קודק שדפדפן לא יפענח: ממירים וידאו בלבד, ומשאירים את האודיו כמו שהוא
    # (הוא כבר AAC, ולכן גם מסנן ה-ADTS נשאר).
    return [
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-profile:v", "main", "-pix_fmt", "yuv420p",
        "-g", "48", "-sc_threshold", "0",
        "-b:v", "2000k", "-maxrate", "2400k", "-bufsize", "4000k",
        # תקרת רוחב: מגבילה את עלות הקידוד ומונעת מערוץ אחד לחנוק את השרת.
        "-vf", "scale=min(1280\\,iw):-2",
        "-c:a", "copy", "-bsf:a", "aac_adtstoasc",
    ]

'''


def _fail(msg):
    print("❌ " + msg)
    print("   לא שונה כלום.")
    sys.exit(1)


def apply_edits(src: str) -> str:
    # ① הכנסת פונקציות העזר לפני הפונקציה שמריצה את ffmpeg של הערוצים.
    m = re.search(r'\n(async def _hls_fix_start\s*\()', src)
    if not m:
        m = re.search(r'\n(def _hls_fix_start\s*\()', src)
    if not m:
        _fail("לא נמצאה הפונקציה שמפעילה את ffmpeg של הערוצים")
    src = src[:m.start()] + "\n" + HELPERS + src[m.start():]

    # ② חישוב הארגומנטים לפני רשימת הארגומנטים.
    pat_src = re.compile(
        r'(\n(?P<ind>[ \t]+)src = f"http://127\.0\.0\.1:\{PORT\}/hls-relay/'
        r'\{host\}/\{path\}"\n)(?P=ind)args = \[')
    if len(pat_src.findall(src)) != 1:
        _fail(f"עוגן ה-src נמצא {len(pat_src.findall(src))} פעמים (ציפינו לאחת)")
    src = pat_src.sub(
        lambda mm: mm.group(1) + mm.group('ind') +
        "_codec = await _hls_codec_args(host, path, src)\n" +
        mm.group('ind') + "args = [", src, count=1)

    # ③ החלפת "-c", "copy" ומסנן האודיו בארגומנטים המחושבים. הביטוי סובלני
    #    לרווחים ולהערה שבסוף השורה, כי הקובץ בשרת אינו זהה לזה שבריפו.
    pat_copy = re.compile(
        r'\n([ \t]+)"-c",\s*"copy",[^\n]*\n'
        r'(?:[ \t]*#[^\n]*\n)*'
        r'[ \t]*"-bsf:a",\s*"aac_adtstoasc",[^\n]*\n')
    n = len(pat_copy.findall(src))
    if n != 1:
        _fail(f'עוגן ה-copy נמצא {n} פעמים (ציפינו לאחת)')
    src = pat_copy.sub(lambda mm: f'\n{mm.group(1)}*_codec,\n', src, count=1)
    return src


def undo():
    baks = sorted(glob.glob(str(TARGET) + ".bak-hlscodec-*"))
    if not baks:
        _fail("לא נמצא גיבוי")
    shutil.copy2(baks[-1], TARGET)
    print(f"↩️  שוחזר מ-{os.path.basename(baks[-1])}")
    print("   הרץ:  systemctl restart zovex-bot")


def main():
    if not TARGET.exists():
        _fail(f"לא נמצא {TARGET}")
    src = TARGET.read_text(encoding="utf-8")

    if DONE_MARK in src:
        print("✓ כבר מוחל. אין מה לעשות.")
        return

    out = apply_edits(src)

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

    bak = f"{TARGET}.bak-hlscodec-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print("✅ הוחל.")
    print(f"   גיבוי: {os.path.basename(bak)}")
    print()
    have = shutil.which("ffprobe")
    print(f"   ffprobe: {'יש — ' + have if have else 'אין! בלעדיו לא ישתנה כלום'}")
    print()
    print("   הרץ:   systemctl restart zovex-bot")
    print("   נסיגה: python3 fix_hls_codec.py --undo")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
