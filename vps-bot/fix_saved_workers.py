#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
הופך את מספר החיבורים המקבילים לניתן לשינוי מהשרת.

המדידה עד כה: חיבור אחד 0.93MB/שנ׳, ארבעה 1.10, שמונה 1.00 — כלומר המעבר
מ-4 ל-8 לא הוסיף דבר. יש טענה שעם 16-20 חיבורים המצב שונה. במקום לבנות APK
לכל ניסיון, המספר מגיע עכשיו מהשרת בתשובת begin, והאפליקציה מצייתת לו.

כך אפשר למדוד 12, 16, 20 בשלוש פקודות ובלי התקנה חדשה:

    systemctl set-environment SAVED_UPLOAD_WORKERS=16
    systemctl restart zovex-bot

או דרך systemctl edit zovex-bot כדי שיישמר אחרי אתחול.

מוגבל ל-32: מעבר לזה זה כבר לא ניסוי אלא הצפה של הראוטר הביתי, שהוא עצמו
חשוד כשהקו מתנהג רע.

דורש ש-fix_saved_parallel.py כבר הוחל.

    python3 fix_saved_workers.py          # מחיל
    python3 fix_saved_workers.py --undo   # מחזיר
"""
import datetime, glob, os, pathlib, py_compile, shutil, sys, tempfile

TARGET = pathlib.Path("/opt/zovex-bot/main.py")

CONST_OLD = '''SAVED_PART_SIZE = 8 * 1024 * 1024     # גודל חלק. גם יחידת הניסיון־מחדש.
'''

CONST_NEW = '''SAVED_PART_SIZE = 8 * 1024 * 1024     # גודל חלק. גם יחידת הניסיון־מחדש.


def _saved_workers():
    """כמה חיבורים מקבילים האפליקציה תפתח. ניתן לשינוי בלי לבנות APK."""
    try:
        n = int(os.environ.get("SAVED_UPLOAD_WORKERS", "8"))
    except (TypeError, ValueError):
        return 8
    return max(1, min(32, n))
'''

RETURN_OLD = '''    return {"ok": True, "job": job_id, "part_size": job["part_size"],
            "n_parts": job["n_parts"]}
'''

RETURN_NEW = '''    return {"ok": True, "job": job_id, "part_size": job["part_size"],
            "n_parts": job["n_parts"], "workers": _saved_workers()}
'''

EDITS = [
    ("קבוע גודל החלק", CONST_OLD, CONST_NEW),
    ("תשובת begin", RETURN_OLD, RETURN_NEW),
]

DONE_MARK = "def _saved_workers("


def _fail(msg):
    print("❌ " + msg)
    print("   לא שונה כלום.")
    sys.exit(1)


def apply_edits(src):
    for label, old, new in EDITS:
        n = src.count(old)
        if n != 1:
            _fail(f"{label}: נקודת העיגון נמצאה {n} פעמים (ציפינו לאחת)")
        src = src.replace(old, new, 1)
    return src


def undo():
    baks = sorted(glob.glob(str(TARGET) + ".bak-workers-*"))
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
    if "/panel/saved-upload/begin" not in src:
        _fail("fix_saved_parallel.py לא הוחל — הרץ אותו קודם")

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

    bak = f"{TARGET}.bak-workers-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print("✅ הוחל.")
    print(f"   גיבוי: {os.path.basename(bak)}")
    print()
    print(f"   כרגע: {os.environ.get('SAVED_UPLOAD_WORKERS', '8')} חיבורים")
    print("   לשינוי:  systemctl set-environment SAVED_UPLOAD_WORKERS=16")
    print("            systemctl restart zovex-bot")
    print("   נסיגה:   python3 fix_saved_workers.py --undo")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
