#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_hls_audio.py — ממיר אודיו של ערוצים חיים ל-AAC כשצריך.

הבעיה:
    main.py:2522   return ["-c", "copy", "-bsf:a", "aac_adtstoasc"]
    main.py:2532   "-c:a", "copy", "-bsf:a", "aac_adtstoasc",

בערוצים חיים האודיו מועתק תמיד כמו שהוא. הקוד כבר יודע (שורה 7483)
שדפדפן מפענח רק mp4a/mp3/opus/flac — ויש מערכת שלמה שמתקנת את זה
ב-VOD. בשידור חי הפער הזה נשאר פתוח.

ערוץ ששולח AC-3 או MP2 (סטנדרט נפוץ בערוצי ספורט) מגיע לצופה כך:
  • באתר  — וידאו תקין, בלי קול. הדפדפן לא מפענח את הזרם.
  • באפליקציה — לרוב לא מנגן בכלל.

בנוסף, `-bsf:a aac_adtstoasc` הוא מסנן שעובד על AAC בלבד. הפעלתו על
AC-3 מכשילה את ffmpeg כולו — כלומר במקרים מסוימים לא רק שאין קול,
הערוץ פשוט לא עולה.

התיקון בודק את קודק האודיו פעם בשעה לכל ערוץ (כמו שכבר נעשה לווידאו):
AAC ממשיך ב-copy בלי עלות, וכל השאר מומר ל-AAC. המרת אודיו זולה —
אחוז-שניים מליבה, לעומת קידוד וידאו ששורף ליבה שלמה.

    python3 fix_hls_audio.py --check
    python3 fix_hls_audio.py
    python3 fix_hls_audio.py --revert
"""
import os, re, shutil, sys
from pathlib import Path

MAIN = Path(os.environ.get("ZOVEX_MAIN", "/opt/zovex-bot/main.py"))
MARK = "# [fix_hls_audio]"
BACKUP = MAIN.with_name(MAIN.name + ".bak_hlsaudio")

PROBE_ANCHOR = '''def _hls_probe_vcodec(url: str):'''

PROBE_FN = '''def _hls_probe_acodec(url: str):
    """שם קודק האודיו של המקור, או None. חוסם.  ''' + MARK + '''
    דפדפן מפענח AAC/MP3/Opus/FLAC בלבד (ראה _VF_BROWSER_AUDIO). ערוץ
    ששולח AC-3 או MP2 מגיע לצופה עם וידאו ובלי קול."""
    import shutil as _sh, subprocess
    exe = _sh.which("ffprobe")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name",
             "-of", "default=nw=1:nk=1", "-analyzeduration", "3000000",
             "-probesize", "3000000", url],
            capture_output=True, text=True, timeout=25).stdout.strip().splitlines()
        return out[0].strip() if out else None
    except Exception as e:
        log.warning("hls_codec: ffprobe אודיו נכשל על %s: %s", url, e)
        return None


'''

# ── הפונקציה שמרכיבה את ארגומנטי ffmpeg ──────────────────────────────
OLD_ARGS = '''    codec = ent[1]
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
    ]'''

NEW_ARGS = '''    codec = ent[1]
    ''' + MARK + ''' האודיו נבדק בנפרד מהווידאו. עד כאן הוא הועתק תמיד,
    # וערוץ ב-AC-3 הגיע לצופה עם וידאו ובלי קול. aac_adtstoasc הוא מסנן
    # ל-AAC בלבד — הפעלתו על AC-3 מפילה את ffmpeg כולו, ולכן הוא נוסף
    # רק כשהאודיו באמת AAC.
    akey = f"a:{host}/{path}"
    aent = _hls_vcodec_cache.get(akey)
    if aent is None or now - aent[0] > _HLS_VCODEC_TTL:
        loop = asyncio.get_running_loop()
        acodec = await loop.run_in_executor(None, _hls_probe_acodec, src)
        _hls_vcodec_cache[akey] = (now, acodec)
        aent = _hls_vcodec_cache[akey]
        log.info("hls_codec: %s → קודק אודיו %s", key, acodec or "לא ידוע")
    acodec = aent[1]
    if acodec == "aac":
        audio = ["-c:a", "copy", "-bsf:a", "aac_adtstoasc"]
    elif acodec:
        # המרת אודיו עולה אחוז-שניים מליבה, לעומת ליבה שלמה לווידאו.
        log.info("hls_codec: %s ממיר אודיו %s → aac", key, acodec)
        audio = ["-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "48000"]
    else:
        # לא הצלחנו לברר. copy בלי המסנן: אם זה לא AAC המסנן יפיל את
        # ffmpeg, ובלעדיו לפחות הווידאו ימשיך לעבוד.
        audio = ["-c:a", "copy"]

    # לא ידוע, או כבר H.264 — לא נוגעים בווידאו.
    if not codec or codec == "h264":
        return ["-c:v", "copy"] + audio
    return [
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-profile:v", "main", "-pix_fmt", "yuv420p",
        "-g", "48", "-sc_threshold", "0",
        "-b:v", "2000k", "-maxrate", "2400k", "-bufsize", "4000k",
        # תקרת רוחב: מגבילה את עלות הקידוד ומונעת מערוץ אחד לחנוק את השרת.
        "-vf", "scale=min(1280\\,iw):-2",
    ] + audio'''


def validate(src: str) -> None:
    compile(src, str(MAIN), "exec")
    # הפונקציה חייבת להיות מוגדרת לפני השימוש בה
    d = src.index("def _hls_probe_acodec(")
    u = src.index("_hls_probe_acodec, src")
    if u < d:
        sys.exit("✗ שימוש ב-_hls_probe_acodec לפני ההגדרה — יקרוס בזמן ריצה")
    if "-c:a" not in src:
        sys.exit("✗ ארגומנטי האודיו נעלמו")


def main() -> None:
    if "--revert" in sys.argv:
        if not BACKUP.exists():
            sys.exit(f"אין גיבוי ב-{BACKUP}")
        shutil.copy2(BACKUP, MAIN)
        print(f"✓ שוחזר מ-{BACKUP}")
        return

    if not MAIN.exists():
        sys.exit(f"לא נמצא: {MAIN}")
    src = MAIN.read_text(encoding="utf-8")
    if MARK in src:
        print("✓ כבר מוחל — לא משנה כלום")
        return

    for name, anchor in (("הפונקציה _hls_probe_vcodec", PROBE_ANCHOR),
                         ("בלוק ארגומנטי הקודק", OLD_ARGS)):
        n = src.count(anchor)
        if n != 1:
            sys.exit(f"✗ {name}: נמצא {n} פעמים במקום אחת — "
                     f"הקובץ בשרת שונה ממה שציפיתי, לא נוגעים")

    out = src.replace(PROBE_ANCHOR, PROBE_FN + PROBE_ANCHOR, 1)
    out = out.replace(OLD_ARGS, NEW_ARGS, 1)
    validate(out)

    print("שינויים:")
    print("   ✓ נוספה _hls_probe_acodec — בדיקת קודק אודיו, נשמרת לשעה")
    print("   ✓ אודיו AAC  → copy (ללא עלות, כמו היום)")
    print("   ✓ אודיו אחר → המרה ל-AAC 160k סטריאו")
    print("   ✓ aac_adtstoasc מופעל רק על AAC (על AC-3 הוא מפיל את ffmpeg)")

    if "--check" in sys.argv:
        print("\n--check: נבדק (תחביר + סדר הגדרה) ולא נכתב.")
        return

    shutil.copy2(MAIN, BACKUP)
    MAIN.write_text(out, encoding="utf-8")
    print(f"\n✓ הוחל. גיבוי: {BACKUP}")
    print("  הפעל:  systemctl restart zovex-bot")
    print("  ⚠ restart מנתק צופים פעילים — לעשות כשאין תנועה.")


if __name__ == "__main__":
    main()
