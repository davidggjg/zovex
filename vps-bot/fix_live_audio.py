#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_live_audio.py — ערוץ חי שהקול שלו פגום במקור, וכרום מסרב לו.

ניקולודיאון. דוד אמר "זה לא בעיה של הספק, לא כל דבר צריך להאשים את
הספק" — והוא צדק, אני טעיתי. הוא פתח את אותה כתובת בנגן רגיל והערוץ
מתנגן מצוין. לכן הלכתי לבדוק מה שונה **אצלנו**, ופתחתי את האתר בכרום.

מה שכרום אמר, מילה במילה:

    PipelineStatus::PIPELINE_ERROR_DECODE:
      Failed to send audio packet for decoding:
      {timestamp=15981979 duration=21333 size=344 is_key_frame=1}
    VIDEOJS: ERROR: (CODE:3 MEDIA_ERR_DECODE)

הווידאו דווקא תקין לגמרי — 1920x1080, הבאפר מתמלא ל-16 ואז ל-21 שניות.
זה **מפענח הקול** של כרום שדוחה את החבילות, ואז כל צינור הניגון נופל.

ובמקביל, ffmpeg על מקטע אחד של אותו ערוץ:
    ניקולודיאון (720):  291 שגיאות פענוח AAC, קוד יציאה 0
    ספורט 5 (120):        0 שגיאות
כלומר הזרם באמת פגום — אבל ffmpeg, VLC והנגן של סמסונג פשוט מדלגים על
מה שלא תקין וממשיכים. כרום לא סלחן: הוא מפיל את כל הניגון.

ולכן זה בר-תיקון אצלנו, בלי לבקש כלום מהספק: מספיק לפענח את הקול
ולקודד אותו מחדש. ffmpeg כבר מוכיח שהוא מסוגל לקרוא אותו (יצא בקוד 0),
ומה שייצא יהיה AAC נקי שכרום מקבל.

שני חלקים:

1. main.py — ‎_hls_codec_args מחליט היום לפי **קודק הווידאו בלבד**, ואם
   הוא H.264 הוא מחזיר "-c copy" לכל הזרמים. לכן הקול הפגום עובר כמו
   שהוא גם במסלול ה-_fix. נוסף מבחן תקינות לקול: מפענחים ארבע שניות
   וסופרים שגיאות, וכשיש יותר מדי — מקודדים את הקול מחדש ומשאירים את
   הווידאו ב-copy. קידוד קול בלבד הוא שבריר מליבה, ולכן זה זול.

2. הקטלוג — 54 מתוך 105 הערוצים כבר עוברים דרך /hls-relay/_fix/,
   וניקולודיאון לא. ‎--channel מעביר אותו לשם.

    python3 fix_live_audio.py --check
    python3 fix_live_audio.py --channel "ניקולודיון" --check
    python3 fix_live_audio.py --channel "ניקולודיון"
    python3 fix_live_audio.py --revert
ואחרי החלק של main.py:  systemctl restart zovex-bot
"""
import argparse, ast, json, os, re, shutil, sys, time
from pathlib import Path

MAIN = Path(os.environ.get("ZOVEX_MAIN", "/opt/zovex-bot/main.py"))
DATA = Path(os.environ.get("ZOVEX_DATA", "/opt/zovex-bot/data"))
CONTENT = DATA / "content.json"
VERSION = DATA / "content_version.txt"
MAIN_BAK = MAIN.with_name(MAIN.name + ".bak_liveaudio")
CONTENT_BAK = CONTENT.with_name("content.json.bak_liveaudio")
MARK = "# [fix_live_audio]"

OLD = '''    codec = ent[1]
    # לא ידוע, או כבר H.264 — לא נוגעים. זו ההתנהגות שהייתה כאן תמיד.
    if not codec or codec == "h264":
        return ["-c", "copy", "-bsf:a", "aac_adtstoasc"]'''

NEW = '''    codec = ent[1]
    ''' + MARK + '''
    # הקול נבדק בנפרד מהווידאו. עד כאן ההחלטה הייתה לפי הווידאו בלבד,
    # ולכן ערוץ עם וידאו H.264 תקין וקול פגום קיבל "-c copy" — והקול
    # הפגום עבר כמו שהוא. כרום דוחה אותו עם PIPELINE_ERROR_DECODE ומפיל
    # את כל הניגון, בעוד VLC ו-ffmpeg פשוט מדלגים וממשיכים.
    aud = await _hls_audio_args(host, path, src)
    if not codec or codec == "h264":
        return ["-c:v", "copy"] + aud'''

OLD2 = '''    # קודק שדפדפן לא יפענח: ממירים וידאו בלבד, ומשאירים את האודיו כמו שהוא
    # (הוא כבר AAC, ולכן גם מסנן ה-ADTS נשאר).
    return ['''
NEW2 = '''    # קודק שדפדפן לא יפענח: ממירים את הווידאו. הקול נקבע בנפרד
    # ב-_hls_audio_args — copy אם הוא תקין, קידוד מחדש אם לא.
    return ['''

OLD3 = '''        "-vf", "scale=min(1280\\,iw):-2",
        "-c:a", "copy", "-bsf:a", "aac_adtstoasc",
    ]'''
NEW3 = '''        "-vf", "scale=min(1280\\,iw):-2",
    ] + aud'''

HELPERS = '''

''' + MARK + '''
_hls_acodec_cache: dict = {}        # host/path -> (זמן, האם הקול פגום)
_HLS_ACODEC_TTL = 6 * 3600
# כמה שורות שגיאה בארבע שניות נחשבות "פגום". ערוץ תקין מחזיר 0; ניקולודיאון
# החזיר מאות. הסף רחוק מספיק משניהם כדי לא להיות רגיש לרעש.
_HLS_AUDIO_BAD_AT = int(os.environ.get("HLS_AUDIO_BAD_AT", "8"))


def _hls_probe_audio_bad(src: str) -> bool:
    """מפענח ארבע שניות של קול בלבד וסופר שגיאות. ריצה חוסמת, ולכן
    נקראת דרך run_in_executor כמו בדיקת הווידאו שלידה."""
    try:
        import subprocess
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-v", "error", "-t", "4",
             "-i", src, "-vn", "-f", "null", "-"],
            capture_output=True, timeout=45)
        n = len([ln for ln in r.stderr.decode("utf-8", "replace").splitlines()
                 if ln.strip()])
        return n >= _HLS_AUDIO_BAD_AT
    except Exception:
        return False        # ספק — לא משנים התנהגות


async def _hls_audio_args(host: str, path: str, src: str) -> list:
    """ארגומנטי הקול. copy כברירת מחדל, קידוד מחדש רק לזרם פגום.

    async ו-run_in_executor ולא קריאה ישירה: הבדיקה מריצה ffmpeg עד 45
    שניות, וקריאה חוסמת כזאת מתוך קורוטינה הייתה מקפיאה את כל השרת —
    בדיוק כמו שבדיקת הווידאו שלידה כבר עושה."""
    key = f"{host}/{path}"
    now = time.time()
    ent = _hls_acodec_cache.get(key)
    if ent is None or now - ent[0] > _HLS_ACODEC_TTL:
        loop = asyncio.get_running_loop()
        bad = await loop.run_in_executor(None, _hls_probe_audio_bad, src)
        _hls_acodec_cache[key] = (now, bad)
        ent = _hls_acodec_cache[key]
        log.info("hls_codec: %s → קול %s", key,
                 "פגום, מקודד מחדש" if bad else "תקין, copy")
    if ent[1]:
        return ["-c:a", "aac", "-ac", "2", "-b:a", "128k", "-ar", "48000"]
    return ["-c:a", "copy", "-bsf:a", "aac_adtstoasc"]

'''


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True); raise


def patch_main(check: bool) -> bool:
    src = MAIN.read_text(encoding="utf-8")
    if MARK in src:
        print("  ✓ main.py כבר מתוקן")
        return False
    for name, old in (("החלטת ה-copy", OLD), ("ההערה בענף ההמרה", OLD2),
                      ("ארגומנטי הקול בענף ההמרה", OLD3)):
        if src.count(old) != 1:
            sys.exit(f"  ✗ '{name}': העוגן נמצא {src.count(old)} פעמים "
                     f"במקום אחת — לא נוגעים")
    out = (src.replace(OLD, NEW, 1).replace(OLD2, NEW2, 1)
              .replace(OLD3, NEW3, 1))

    # העוזרים נכנסים לפני _hls_codec_args, כדי שייקראו בסדר הגיוני בקובץ
    anchor = "async def _hls_codec_args("
    if out.count(anchor) != 1:
        sys.exit("  ✗ לא מצאתי איפה להשתיל את העוזרים")
    out = out.replace(anchor, HELPERS.lstrip("\n") + "\n" + anchor, 1)

    compile(out, str(MAIN), "exec")
    top = set()
    for node in ast.parse(out).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            top.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    top.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            top.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for al in node.names:
                top.add((al.asname or al.name).split(".")[0])
    need = ["_hls_probe_audio_bad", "_hls_audio_args", "_hls_acodec_cache",
            "_HLS_ACODEC_TTL", "_HLS_AUDIO_BAD_AT"]
    miss = [n for n in need if n not in top]
    if miss:
        sys.exit(f"  ✗ הוגדרו חסרים: {miss}")
    for n in ("log", "os", "time", "asyncio"):
        if n not in top:
            sys.exit(f"  ✗ {n} לא מוגדר ברמת המודול")
    print(f"  ✓ main.py: תחביר תקין, {len(need)} שמות חדשים, 3 תלויות אומתו")
    if not check:
        shutil.copy2(MAIN, MAIN_BAK)
        atomic_write(MAIN, out)
        print(f"  ✓ נכתב. גיבוי: {MAIN_BAK}")
    return True


def patch_channel(title: str, check: bool) -> int:
    if not CONTENT.exists():
        sys.exit(f"לא נמצא: {CONTENT}")
    items = json.loads(CONTENT.read_text(encoding="utf-8"))
    rx = re.compile(r"^(.*?)/hls-relay/(?!_fix/)(.+)$")
    plan = []
    for it in items:
        if not it.get("is_live"):
            continue
        if (it.get("title") or "").strip() != title.strip():
            continue
        m = rx.match(str(it.get("video_url") or ""))
        if m:
            plan.append((it, it["video_url"],
                         f"{m.group(1)}/hls-relay/_fix/{m.group(2)}"))
    if not plan:
        print(f"  · {title}: כבר ב-_fix או לא נמצא — לא נוגעים")
        return 0
    for it, old, new in plan:
        print(f"  ✓ {title}")
        print(f"      {old}")
        print(f"      → {new}")
    if check:
        return len(plan)
    shutil.copy2(CONTENT, CONTENT_BAK)
    for it, _, new in plan:
        it["video_url"] = new
    atomic_write(CONTENT, json.dumps(items, ensure_ascii=False, indent=2))
    try:
        v = int(VERSION.read_text().strip()) + 1 if VERSION.exists() else 1
    except Exception:
        v = int(time.time())
    atomic_write(VERSION, str(v))
    print(f"  ✓ נכתב. גיבוי: {CONTENT_BAK} · גרסה {v}")
    return len(plan)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="",
                    help="שם ערוץ להעביר למסלול _fix")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    if a.revert:
        done = []
        if MAIN_BAK.exists():
            shutil.copy2(MAIN_BAK, MAIN); done.append("main.py")
        if CONTENT_BAK.exists():
            shutil.copy2(CONTENT_BAK, CONTENT); done.append("content.json")
        if not done:
            sys.exit("אין גיבויים לשחזור")
        print("✓ שוחזרו: " + ", ".join(done))
        if "main.py" in done:
            print("  צריך: systemctl restart zovex-bot")
        return
    if not MAIN.exists():
        sys.exit(f"לא נמצא: {MAIN}")

    print("שלב 1 — זיהוי קול פגום ב-main.py")
    need_restart = patch_main(a.check)
    n = 0
    if a.channel:
        print(f"\nשלב 2 — העברת {a.channel!r} למסלול _fix")
        n = patch_channel(a.channel, a.check)

    print("\n" + "=" * 62)
    if a.check:
        print("--check: שום דבר לא נכתב.")
        return
    if need_restart:
        print("⚠ main.py השתנה — צריך:  systemctl restart zovex-bot")
        print("  ה-restart מנתק צופים פעילים.")
    if n:
        print("  הערוץ יעבור למסלול החדש ברענון, בלי restart נוסף.")
    print("\nלאימות אחרי ה-restart — לחפש ביומן:")
    print("  journalctl -u zovex-bot -n 200 | grep hls_codec")
    print("  אמור להופיע: קול פגום, מקודד מחדש")


if __name__ == "__main__":
    main()
