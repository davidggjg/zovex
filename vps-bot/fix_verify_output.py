#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_verify_output — _fix בודק את הפלט של עצמו, לא את הקלט.

## הדפוס שחוזר

ארבע פעמים בסיבוב הזה נמצאה בדיקה שבדקה את הצורה ולא את הדבר עצמו:

  1. ‎stderr=DEVNULL‎ — שגיאת ffmpeg נזרקה, ולכן 36 כשלים לא הופיעו ביומן.
  2. ‎_fix‎ החזיר 200 כי נוצר קובץ ‎.m4s‎, בלי לבדוק שיש בו וידאו.
  3. ‎_hls_no_idr‎ ניבא על הקלט במקום למדוד את הפלט.
  4. הריליי אישר כל תשובה שמתחילה ב-‎#EXTM3U‎, כולל playlist ריק.

זה הפאץ' ל-(2) ול-(3), והוא מחליף ניבוי במדידה.

## מה נמדד

הסריקה של כל 105 ערוצי השידור החי מצאה עשרה ערוצים שהמקור שלהם
open-GOP — אפס IDR, פריימי I עם recovery point SEI, ו-‎frame_mbs_only=0‎:

    hot-family-backup · turkish-drama-3 · Torki2 · Dramottorki
    Hotspo · Hotril · HOT8 · hotfrns · HOTGOLD · 5plus

וחמישה מהם עוברים דרך ‎_fix‎ — **והפלט של ‎_fix‎ יצא open-GOP בעצמו.**
זו ההוכחה שחיפשתי: אם ‎_hls_no_idr‎ בשרת הייתה מחזירה "אין IDR",
‎_fix‎ היה מקודד מחדש ומייצר IDR, כפי שאומת (32 IDR, ‎frame_mbs_only=1‎).
היא מחזירה "יש IDR", ולכן נבחר ‎-c:v copy‎ — והעתקה משמרת בדיוק את
הבעיה שההמרה הייתה אמורה לפתור.

למה היא מחזירה False בשרת — לא הצלחתי לקבוע, וגם לא צריך: הבדיקה
ההזאת מנבאה מה יקרה במקום לבדוק מה קרה, וזו התקלה האמיתית.

## מה משתנה

‎_fix‎ סורק את הפלט שהוא בעצמו ייצר — ‎init.mp4‎ יחד עם הסגמנט הראשון —
ומחפש בו IDR. אין IDR? הפרופיל נחשב כשל, ffmpeg נהרג, והערוץ עובר
לפרופיל הקידוד המלא, שאומת כמייצר 32 IDR וזרם פרוגרסיבי.

הסריקה נעשית דרך ffmpeg עם ‎h264_mp4toannexb‎, כי ב-fMP4 יחידות ה-NAL
נשמרות באורך-קידומת ולא בקודי פתיחה — סריקת ‎00 00 01‎ ישירות על
‎.m4s‎ פשוט לא הייתה מוצאת כלום, והייתה מדווחת על כל ערוץ כשבור.

## למה זה לא יכול להישבר מאותה סיבה

הבדיקה רצה על קבצים מקומיים שאנחנו כתבנו, בלי רשת ובלי הספק. אין בה
תלות בבדיקה המקדימה, ולכן היא אינה יכולה להיכשל מאותה סיבה שהיא נכשלת.

## למה זה לא מזיק

* רצה **פעם אחת** לכל הפעלה של ffmpeg לערוץ, על סגמנט אחד.
* ערוץ שהפלט שלו תקין ממשיך בפרופיל ‎copy‎ בדיוק כמו היום.
* כשלון בבדיקה עצמה (ffmpeg חסר, קובץ שנמחק) נחשב "תקין" ואינו מפעיל
  קידוד מחדש — ספק אינו משנה התנהגות.
* ‎HLS_VERIFY_OUT=0‎ בסביבה מכבה את זה לגמרי.

    python3 fix_verify_output.py --check
    python3 fix_verify_output.py
    python3 fix_verify_output.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_verify_output"
MARK = "fix_verify_output"
NEEDS = ("fix_live_robust", "fix_idr_probe_log")

A_HELPER = '''async def _hls_fix_start(host: str, path: str, profile: int = 0) -> Optional[dict]:
'''

N_HELPER = '''# [fix_verify_output]
# כיבוי בסביבה, בלי לבטל את הפאץ'.
HLS_VERIFY_OUT = os.environ.get("HLS_VERIFY_OUT", "1") not in ("0", "false", "no")


def _hls_out_has_idr(outdir) -> bool:
    """האם הפלט ש-ffmpeg ייצר מכיל IDR.

    סורק את init.mp4 יחד עם הסגמנט הראשון. **חייב** לעבור דרך
    h264_mp4toannexb: ב-fMP4 יחידות ה-NAL נשמרות באורך-קידומת ולא
    בקודי פתיחה, וסריקת 00 00 01 ישירות על .m4s לא הייתה מוצאת כלום
    והייתה מדווחת על כל ערוץ כשבור.

    מחזיר True בכל מקרה של ספק — קובץ חסר, ffmpeg שנכשל, פלט ריק —
    כדי שתקלה בבדיקה לא תפעיל קידוד מחדש בלי סיבה.
    """
    try:
        import subprocess, tempfile
        init = outdir / "init.mp4"
        segs = sorted(outdir.glob("*.m4s"),
                      key=lambda p: p.stat().st_mtime)
        if not init.exists() or not segs:
            return True
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
            fh.write(init.read_bytes())
            fh.write(segs[0].read_bytes())
            joined = fh.name
        try:
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-v", "error", "-i", joined,
                 "-map", "0:v:0", "-c", "copy",
                 "-bsf:v", "h264_mp4toannexb", "-f", "h264", "-"],
                capture_output=True, timeout=25)
        finally:
            try:
                os.unlink(joined)
            except OSError:
                pass
        idr, slices = _h264_count_nals(r.stdout or b"")
        if not slices:
            log.warning("verify_out: לא נקראו slices מהפלט — לא משנים החלטה")
            return True
        log.info("verify_out: פלט %s · slices=%d · IDR=%d",
                 outdir.name, slices, idr)
        return idr > 0
    except Exception as e:
        log.warning("verify_out: נכשל — %s: %s", type(e).__name__, e)
        return True


async def _hls_fix_start(host: str, path: str, profile: int = 0) -> Optional[dict]:
'''

A_OK = '''        if ok:
            if _hls_fix_profile.get(key) != profile:
                _hls_fix_profile[key] = profile
                log.info("hls_fix: %s עובד בפרופיל %s", key, profile)
            break
'''

N_OK = '''        # [fix_verify_output] "נוצר סגמנט" אינו הצלחה.
        # profile 0 הוא -c:v copy, והעתקה של זרם open-GOP מייצרת פלט
        # שנראה תקין ואינו נגיש: ffmpeg מצליח, הקובץ קיים, ואין בו אף
        # IDR — ולכן MSE לא יכול להתחיל והנגן נתקע על 0:00 בלי שגיאה.
        # נמדד: חמישה ערוצים שעוברים דרך _fix יצאו open-GOP בפלט.
        # כאן זה נתפס, והערוץ נופל לפרופיל הקידוד המלא שאומת כמייצר IDR.
        if ok and profile == 0 and HLS_VERIFY_OUT:
            loop = asyncio.get_running_loop()
            if not await loop.run_in_executor(
                    None, _hls_out_has_idr, ent["dir"]):
                log.warning("hls_fix: %s — הפלט של profile 0 בלי IDR, "
                            "עובר לקידוד מלא", key)
                ok = False
                why = "פלט בלי IDR"
        if ok:
            if _hls_fix_profile.get(key) != profile:
                _hls_fix_profile[key] = profile
                log.info("hls_fix: %s עובד בפרופיל %s", key, profile)
            break
'''

EDITS = [("עוזר האימות", A_HELPER, N_HELPER), ("ענף ההצלחה", A_OK, N_OK)]


def fn_source(src, name):
    for n in ast.walk(ast.parse(src)):
        if getattr(n, "name", "") == name and isinstance(
                n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ast.get_source_segment(src, n)
    return None


def code_only(fn: str) -> str:
    parts = fn.split('"""')
    body = parts[0] + ("".join(parts[2:]) if len(parts) > 2 else "")
    return "\n".join(l for l in body.splitlines()
                     if not l.strip().startswith("#"))


def validate(s):
    compile(s, PATH, "exec")
    names = [n.name for n in ast.walk(ast.parse(s))
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for f in ("_hls_out_has_idr", "_hls_fix_start", "hls_relay_fixed",
              "_h264_count_nals"):
        assert names.count(f) == 1, f"{f} חסרה או כפולה"

    v = fn_source(s, "_hls_out_has_idr")
    assert "h264_mp4toannexb" in v, \
        "בלי ה-bsf הסריקה על fMP4 לא תמצא כלום ותדווח על כל ערוץ כשבור"
    assert "return True" in v.split("except")[0], "ספק אינו מוחזר כתקין"
    assert "_h264_count_nals" in v, "אינו משתמש במונה המשותף"

    rt = code_only(fn_source(s, "hls_relay_fixed"))
    assert "_hls_out_has_idr" in rt, "האימות אינו נקרא"
    assert "profile == 0" in rt, "האימות רץ גם על פרופיל הגיבוי"
    assert "run_in_executor" in rt, "האימות חוסם את הלולאה"
    # האימות חייב לרוץ לפני שהפרופיל נרשם כמוצלח
    assert rt.index("_hls_out_has_idr") < rt.index("_hls_fix_profile[key] = profile"), \
        "האימות אחרי רישום ההצלחה — הפרופיל השבור ייזכר"

    # ── התנהגות ──────────────────────────────────────────────────────────
    import tempfile
    from pathlib import Path as _P
    ns = {"os": os, "log": type("L", (), {
        "warning": lambda *a: None, "info": lambda *a: None})(),
        "_h264_count_nals": None}

    def nal(t, n=1):
        return (b"\x00\x00\x01" + bytes([t]) + b"\xaa" * 8) * n

    calls = {}

    def fake_count(data):
        calls["data"] = data
        return calls["ret"]
    ns["_h264_count_nals"] = fake_count
    exec(fn_source(s, "_hls_out_has_idr"), ns)
    f = ns["_hls_out_has_idr"]

    d = _P(tempfile.mkdtemp())

    # 1. תיקייה בלי init/סגמנט — ספק, ולכן "תקין"
    calls["ret"] = (0, 0)
    assert f(d) is True, "תיקייה ריקה הפעילה קידוד מחדש"

    # 2. עם קבצים: התוצאה נקבעת לפי המונה. ffmpeg אמיתי ירוץ כאן ויכשל
    #    על קבצים מזויפים, ולכן הבדיקה הזאת מאמתת את מסלול הספק — שגם
    #    הוא חייב להחזיר "תקין".
    (d / "init.mp4").write_bytes(b"\x00" * 32)
    (d / "s0.m4s").write_bytes(nal(1, 5))
    assert f(d) is True, "כשל של ffmpeg על פלט פגום שינה החלטה"

    # 3. והמונה עצמו, שהוא הלוגיקה: אפס IDR עם slices ⇒ צריך קידוד
    ns2 = {}
    exec(fn_source(s, "_h264_count_nals"), ns2)
    cnt = ns2["_h264_count_nals"]
    assert cnt(nal(7, 3) + nal(1, 50)) == (0, 50)
    assert cnt(nal(5, 2) + nal(1, 10)) == (2, 12)
    return True


def main():
    if not os.path.exists(PATH):
        sys.exit(f"לא נמצא {PATH}")
    src = open(PATH, encoding="utf-8").read()

    if "--revert" in sys.argv:
        if not os.path.exists(BAK):
            sys.exit(f"אין גיבוי ב-{BAK}")
        shutil.copy2(BAK, PATH)
        print(f"✓ שוחזר מ-{BAK}")
        return

    if MARK in src:
        print("כבר מותקן.")
        return
    for dep in NEEDS:
        if dep not in src:
            sys.exit(f"✗ דורש {dep}, שאינו מוחל. לא נוגע בכלום.")

    out = src
    for label, a, n in EDITS:
        if out.count(a) != 1:
            sys.exit(f"✗ העוגן '{label}' נמצא {out.count(a)} פעמים — "
                     "לא נוגע בכלום.")
        out = out.replace(a, n)

    validate(out)
    print("✓ כל הבדיקות עברו")
    if "--check" in sys.argv:
        print("--check: שום דבר לא נכתב.")
        return

    shutil.copy2(PATH, BAK)
    with open(PATH, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(f"✓ הוחל. גיבוי: {BAK}")
    print()
    print("מעכשיו ערוץ שההמרה שלו מייצרת פלט בלי IDR עובר לקידוד מלא")
    print("מעצמו. ביומן זה נראה כך:")
    print("  verify_out: פלט <מזהה> · slices=... · IDR=0")
    print("  hls_fix: <מזהה> — הפלט של profile 0 בלי IDR, עובר לקידוד מלא")
    print("  hls_fix: <מזהה> עובד בפרופיל 1")


if __name__ == "__main__":
    main()
