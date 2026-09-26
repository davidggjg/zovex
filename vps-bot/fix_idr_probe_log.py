#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_idr_probe_log — בדיקת ה-IDR מפסיקה לבלוע את מה שראתה.

## למה זה נדרש

ההפניה האוטומטית (fix_live_autofix) מותקנת על השרת — נמדד מבחוץ:
‎/hls-relay/_fix/<ספק>:7070/...‎ מחזיר 200 במקום 403, כלומר תיקון הפורט
פועל. אבל המסלול הרגיל ממשיך להחזיר 200 בלי הפניה, גם אחרי בקשות
חוזרות, וגם עם פרמטר שמבטל מטמון (‎?zx=1‎ → 200 גם הוא, כלומר זה אינו
מטמון של nginx).

ההפניה תלויה בתשובה אחת: האם ‎_hls_probe_no_idr‎ קבע שאין IDR. הפקודה
שהוא מריץ אומתה כאן מול אותה כתובת בדיוק והחזירה 5,136,571 בתים,
404 slices ואפס IDR — כלומר "צריך המרה". אם בשרת היא מחזירה אחרת, זה
או שה-ffmpeg שם נכשל או שהוא החזיר פחות ממה שנדרש.

ואת זה אי אפשר לדעת, כי הפונקציה:

    return not _h264_has_idr(r.stdout or b"")
    except Exception:
        return False

בולעת את קוד היציאה, את ה-stderr ואת מספר הבתים. וגם ההיגיון
"לא נמצאו slices ⇒ תקין" נכון כמדיניות אבל אינו מבחין בין "יש IDR"
לבין "לא הצלחתי לקרוא" — שתי מסקנות שונות לגמרי שמודפסות אותו דבר.

## מה משתנה

רק דיווח. אין שינוי בשום החלטה, ובשום מצב אין החלטה חדשה:

* ‎_hls_probe_no_idr‎ מודפס ליומן עם מספר הבתים שהתקבלו, מספר ה-slices,
  מספר ה-IDR, קוד היציאה של ffmpeg ושתי שורות ה-stderr האחרונות.
* חריגה נרשמת עם הסוג וההודעה במקום להיעלם.
* המסקנה עצמה זהה בדיוק: אין IDR ⇒ True, יש ⇒ False, ספק ⇒ False.

זה מה שיהפוך את הסיבוב הבא לתשובה: שורה אחת ביומן תגיד אם ffmpeg על
השרת בכלל הצליח לקרוא את הזרם, וכמה הוא ראה.

    python3 fix_idr_probe_log.py --check
    python3 fix_idr_probe_log.py
    python3 fix_idr_probe_log.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_idr_probe_log"
MARK = "fix_idr_probe_log"
NEEDS = ("fix_live_opengop",)

A_PROBE = '''    try:
        import subprocess
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-v", "error", "-t", "8",
             "-i", src, "-map", "0:v:0", "-c", "copy", "-f", "h264", "-"],
            capture_output=True, timeout=60)
        return not _h264_has_idr(r.stdout or b"")
    except Exception:
        return False                # ספק — מתנהגים כמו קודם
'''

N_PROBE = '''    # [fix_idr_probe_log] המסקנה זהה, אבל מה שראינו נרשם.
    # קודם כל אלה נבלעו — קוד היציאה, ה-stderr ומספר הבתים — ולכן
    # "יש IDR" ו-"לא הצלחתי לקרוא את הזרם" נראו ביומן אותו דבר, בזמן
    # שהן שתי מסקנות שונות לגמרי.
    try:
        import subprocess
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-v", "error", "-t", "8",
             "-i", src, "-map", "0:v:0", "-c", "copy", "-f", "h264", "-"],
            capture_output=True, timeout=60)
        data = r.stdout or b""
        idr, slices = _h264_count_nals(data)
        err = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        log.info("idr_probe: %d בתים · slices=%d · IDR=%d · rc=%s%s",
                 len(data), slices, idr, r.returncode,
                 (" · " + " | ".join(err[-2:])) if err else "")
        if not slices:
            # אין slices זה "לא הצלחתי לקרוא", לא "יש IDR". ההחלטה נשארת
            # זהה — לא משנים התנהגות בספק — אבל היא נאמרת במפורש.
            log.warning("idr_probe: לא נקראו slices בכלל — לא משנים התנהגות")
            return False
        return idr == 0
    except Exception as e:
        log.warning("idr_probe: נכשל — %s: %s", type(e).__name__, e)
        return False                # ספק — מתנהגים כמו קודם
'''

A_HAS = '''    if not slices:
        return True                 # לא הצלחנו לקרוא — לא משנים התנהגות
    return idr > 0
'''

N_HAS = '''    if not slices:
        return True                 # לא הצלחנו לקרוא — לא משנים התנהגות
    return idr > 0


def _h264_count_nals(data: bytes):
    """[fix_idr_probe_log] (IDR, slices) — אותה סריקה, אבל עם המספרים.

    _h264_has_idr מחזיר בוליאני, ולכן אי אפשר לרשום ביומן כמה נמצא.
    שתי הפונקציות סורקות אותו דבר בדיוק; הבדיקה למטה מאמתת שהן
    מסכימות, כדי שלא תיווצר כאן סריקה שנייה שמתפצלת מהראשונה.
    """
    idr = slices = 0
    i = 0
    while True:
        j = data.find(b"\\x00\\x00\\x01", i)
        if j < 0 or j + 3 >= len(data):
            break
        t = data[j + 3] & 0x1F
        if t == 5:
            idr += 1
        if t in (1, 5):
            slices += 1
        i = j + 3
    return idr, slices
'''

EDITS = [("מונה NAL", A_HAS, N_HAS), ("הבדיקה עצמה", A_PROBE, N_PROBE)]


def fn_source(src, name):
    for n in ast.walk(ast.parse(src)):
        if getattr(n, "name", "") == name and isinstance(
                n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ast.get_source_segment(src, n)
    return None


def validate(s):
    compile(s, PATH, "exec")
    names = [n.name for n in ast.walk(ast.parse(s))
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for f in ("_hls_probe_no_idr", "_h264_has_idr", "_h264_count_nals"):
        assert names.count(f) == 1, f"{f} חסרה או כפולה"

    pr = fn_source(s, "_hls_probe_no_idr")
    assert 'log.info("idr_probe:' in pr, "אין דיווח"
    assert "r.returncode" in pr and "r.stderr" in pr, "קוד היציאה/stderr נבלעים"
    assert "return idr == 0" in pr, "המסקנה השתנתה"

    ns = {}
    for f in ("_h264_has_idr", "_h264_count_nals"):
        exec(fn_source(s, f), ns)
    has, cnt = ns["_h264_has_idr"], ns["_h264_count_nals"]

    def nal(t, n=1):
        return (b"\x00\x00\x01" + bytes([t]) + b"\xaa" * 8) * n

    # שתי הסריקות חייבות להסכים על כל קלט — אחרת נוצרה כאן לוגיקה שנייה
    cases = [b"", nal(7) + nal(5) + nal(1, 9), nal(7, 7) + nal(1, 224),
             nal(5) + b"\x00\x00\x01", nal(6, 3), nal(1, 3) + nal(5, 2)]
    for d in cases:
        idr, sl = cnt(d)
        expect = True if not sl else idr > 0
        assert has(d) is expect, f"הסריקות אינן מסכימות על {len(d)} בתים"

    # והמספרים עצמם
    assert cnt(nal(7, 7) + nal(6, 448) + nal(9, 224) + nal(1, 224)) == (0, 224)
    assert cnt(nal(5, 3) + nal(1, 10)) == (3, 13)
    assert cnt(b"") == (0, 0)

    # ההחלטה: אין slices ⇒ False (לא משנים התנהגות), אין IDR ⇒ True
    src_pr = fn_source(s, "_hls_probe_no_idr")
    assert src_pr.index("if not slices:") < src_pr.index("return idr == 0"), \
        "בדיקת ה-slices אחרי ההחלטה"
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
    print("אין שינוי בשום התנהגות — רק דיווח. אחרי ההפעלה מחדש:")
    print("  1. לבקש את הערוץ פעם אחת")
    print("  2. להמתין כ-40 שניות (הבדיקה רצה ברקע)")
    print("  3. journalctl -u zovex-bot --since '-3 min' | grep -E 'idr_probe|hls_codec|hls_fix'")
    print()
    print("השורה idr_probe תגיד בדיוק מה ffmpeg על השרת הצליח לקרוא.")


if __name__ == "__main__":
    main()
