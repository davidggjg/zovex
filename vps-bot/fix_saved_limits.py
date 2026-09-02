#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
עוצר העלאה שאין לה סיכוי — לפני שהיא נשלחת, ולא אחרי.

שני קירות אפשריים בהעלאת קובץ גדול, ושניהם היו מתגלים רק בסוף:

  · טלגרם מגביל קובץ ל-2GB בחשבון רגיל ול-4GB ב-Premium. קובץ של 3.34GB
    מחשבון שאינו Premium היה עובר במלואו מהטלפון לשרת — שעה על רשת סלולרית —
    ורק אז נדחה בשלב ②.
  · הקובץ הזמני נכתב לדיסק של השרת. אם אין שם מספיק מקום, הקליטה נופלת
    באמצע על "No space left on device", וגם זה רק אחרי שהכול כבר הועבר.

התיקון בודק את שניהם מיד עם קבלת הכותרות, לפי Content-Length, ומחזיר שגיאה
מוסברת תוך שנייה. בנוסף /panel/entry-code מחזיר עכשיו את המגבלה ואת המקום
הפנוי, כדי שהאפליקציה תדע להזהיר עוד לפני שנבחר קובץ.

אם לא ניתן לברר אם החשבון Premium (כשל רשת מול טלגרם) לא חוסמים — עדיף לנסות
מאשר לדחות העלאה תקינה על סמך ניחוש.

התיקון עצמאי ואינו תלוי ב-fix_saved_video_meta.py; אפשר להריץ בכל סדר.

    python3 fix_saved_limits.py          # מחיל
    python3 fix_saved_limits.py --undo   # מחזיר
"""
import datetime, glob, os, pathlib, py_compile, shutil, sys, tempfile

TARGET = pathlib.Path("/opt/zovex-bot/main.py")

# ── מגבלת החשבון ─────────────────────────────────────────────────────────────
HELPER_OLD = '''@api.post("/panel/entry-code")
'''

HELPER_NEW = '''# מגבלת טלגרם לפי סוג החשבון. נשמרת לשעה: is_premium אינו משתנה בתדירות
# שמצדיקה קריאת רשת בכל בקשה.
_saved_premium = {"at": 0.0, "premium": None}
SAVED_LIMIT_FREE = 2 * 1024 ** 3
SAVED_LIMIT_PREMIUM = 4 * 1024 ** 3


async def _saved_max_size():
    """הגודל המרבי שהחשבון המחובר יכול לשלוח, או 0 אם אין חשבון."""
    bot = _pick_userbot()
    if bot is None:
        return 0
    now = time.time()
    if _saved_premium["premium"] is None or now - _saved_premium["at"] > 3600:
        try:
            me = await bot["client"].get_me()
            _saved_premium["premium"] = bool(getattr(me, "is_premium", False))
            _saved_premium["at"] = now
        except Exception as e:
            # לא הצלחנו לברר. לא חוסמים על סמך ניחוש — מחזירים את התקרה
            # הגבוהה ונותנים לטלגרם עצמו לומר לא, אם בכלל.
            log.warning("בדיקת Premium נכשלה: %s", e)
            return SAVED_LIMIT_PREMIUM
    return SAVED_LIMIT_PREMIUM if _saved_premium["premium"] else SAVED_LIMIT_FREE


def _saved_free_disk():
    """מקום פנוי בדיסק שאליו נכתב הקובץ הזמני."""
    import shutil as _sh
    try:
        SAVED_TMP_DIR.mkdir(parents=True, exist_ok=True)
        return _sh.disk_usage(str(SAVED_TMP_DIR)).free
    except Exception:
        return 0


@api.post("/panel/entry-code")
'''

# ── תשובת קוד הכניסה: מוסיפה את המגבלה ואת המקום הפנוי ───────────────────────
ENTRY_OLD = '''    bot = _pick_userbot()
    return {"ok": True, "account": (bot or {}).get("who") or "",
            "ready": bot is not None}
'''

ENTRY_NEW = '''    bot = _pick_userbot()
    _max = await _saved_max_size()
    return {"ok": True, "account": (bot or {}).get("who") or "",
            "ready": bot is not None,
            "premium": bool(_saved_premium.get("premium")),
            "max_size": _max,
            "free_disk": _saved_free_disk()}
'''

# ── דחייה מוקדמת בהעלאה עצמה ─────────────────────────────────────────────────
GUARD_OLD = '''    _check_upload_code(request, request.headers.get("x-upload-code", ""))
    if _pick_userbot() is None:
        raise HTTPException(status_code=503,
                            detail="אין חשבון משתמש מחובר בשרת")
'''

GUARD_NEW = '''    _check_upload_code(request, request.headers.get("x-upload-code", ""))
    if _pick_userbot() is None:
        raise HTTPException(status_code=503,
                            detail="אין חשבון משתמש מחובר בשרת")

    # ── שני קירות שנבדקים כאן ולא בסוף ──────────────────────────────────
    # שניהם היו מתגלים רק אחרי שהקובץ כולו עבר מהטלפון — שעה על רשת
    # סלולרית — ולכן הם נבדקים מול Content-Length ברגע שהכותרות מגיעות.
    _declared = int(request.headers.get("content-length") or 0)
    if _declared:
        _gb = 1073741824
        _max = await _saved_max_size()
        if _max and _declared > _max:
            raise HTTPException(status_code=413, detail=(
                f"הקובץ {_declared / _gb:.2f}GB, וטלגרם מגביל את החשבון הזה "
                f"ל-{_max // _gb}GB. חשבון Premium מגיע ל-4GB."))
        _free = _saved_free_disk()
        # שוליים של חצי ג'יגה: הקובץ אינו הדבר היחיד שכותב לדיסק הזה.
        if _free and _free < _declared + 512 * 1024 * 1024:
            raise HTTPException(status_code=507, detail=(
                f"אין מספיק מקום בשרת: פנויים {_free / _gb:.1f}GB "
                f"והקובץ {_declared / _gb:.2f}GB"))
'''

EDITS = [
    ("פונקציות המגבלה", HELPER_OLD, HELPER_NEW),
    ("תשובת קוד הכניסה", ENTRY_OLD, ENTRY_NEW),
    ("הדחייה המוקדמת", GUARD_OLD, GUARD_NEW),
]

DONE_MARK = "async def _saved_max_size("


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
    baks = sorted(glob.glob(str(TARGET) + ".bak-limits-*"))
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
    if "/panel/saved-upload" not in src:
        _fail("add_saved_upload.py לא הוחל — הרץ אותו קודם")

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

    bak = f"{TARGET}.bak-limits-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print("✅ הוחל.")
    print(f"   גיבוי: {os.path.basename(bak)}")
    print()
    print("   הרץ:   systemctl restart zovex-bot")
    print("   נסיגה: python3 fix_saved_limits.py --undo")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
