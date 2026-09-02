#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
חוסם כתיבה לתמיכה למי שנחסם, ומחייב זיהוי כדי לכתוב בכלל.

הרקע: כפתור התמיכה באתר הוביל לטלגרם. שם אין אימייל ואין חשבון, ולכן מי
שכותב דברים פוגעניים אינו ניתן לזיהוי ולא ניתן לחסימה. הצ'אט החדש באתר
שולח את המזהה "g:<email>" — אבל זה לבדו לא מספיק:

  · add_bans.py הוסיף /panel/bans ו-/api/access, כלומר חסימה *כניסה לאתר*.
    הוא לא נגע ב-/feedback/send, ולכן מי שנחסם המשיך לכתוב לתיבת התמיכה —
    בדיוק הדבר שהחסימה נועדה למנוע.
  · הגבלה בצד הלקוח לבדה חסרת ערך מול מי שמתאמץ: אפשר לשלוח POST ישירות
    עם כל user_id. הבדיקה חייבת להיות בשרת.

שני התיקונים כאן:
  1. בקשה בלי אימייל מזוהה נדחית. אורח יכול לצפות, לא לכתוב.
  2. בקשה מאימייל חסום נדחית ב-403.

דורש ש-add_bans.py כבר הוחל (הוא זה שיצר את load_bans ו-_norm_email).

    python3 fix_feedback_bans.py          # מחיל
    python3 fix_feedback_bans.py --undo   # מחזיר
"""
import datetime, glob, os, pathlib, py_compile, shutil, sys, tempfile

TARGET = pathlib.Path("/opt/zovex-bot/main.py")

OLD = '''@api.post("/feedback/send")
async def feedback_send(req: FeedbackSendReq):
    text = (req.text or "").strip()
    if not req.user_id or not text:
        raise HTTPException(status_code=400, detail="חסר משתמש או טקסט")
'''

NEW = '''@api.post("/feedback/send")
async def feedback_send(req: FeedbackSendReq):
    text = (req.text or "").strip()
    if not req.user_id or not text:
        raise HTTPException(status_code=400, detail="חסר משתמש או טקסט")
    # ── זיהוי וחסימה ────────────────────────────────────────────────────
    # הבדיקה כאן ולא רק בממשק: אפשר לשלוח POST ישירות עם כל user_id, ולכן
    # הגבלה בצד הלקוח לבדה אינה שווה דבר מול מי שמתאמץ.
    #
    # האימייל נלקח מהשדה, ואם הוא ריק — מהמזהה עצמו: הלקוחות שולחים
    # "g:<email>" למשתמש מחובר ו-"d:<אקראי>" לאורח, כך שאורח פשוט לא יעבור
    # את התנאי הזה.
    _mail = (req.email or "").strip()
    if not _mail and req.user_id.startswith("g:"):
        _mail = req.user_id[2:]
    _mail = _norm_email(_mail)
    if not _mail or "@" not in _mail:
        raise HTTPException(status_code=401,
                            detail="צריך להתחבר כדי לכתוב לתמיכה")
    _rec = load_bans().get(_mail)
    if _rec:
        raise HTTPException(status_code=403,
                            detail=_rec.get("message") or BAN_MESSAGE)
'''


def _fail(msg):
    print("❌ " + msg)
    print("   לא שונה כלום.")
    sys.exit(1)


def undo():
    baks = sorted(glob.glob(str(TARGET) + ".bak-fbban-*"))
    if not baks:
        _fail("לא נמצא גיבוי")
    shutil.copy2(baks[-1], TARGET)
    print(f"↩️  שוחזר מ-{os.path.basename(baks[-1])}")
    print("   הרץ:  systemctl restart zovex-bot")


def main():
    if not TARGET.exists():
        _fail(f"לא נמצא {TARGET}")
    src = TARGET.read_text(encoding="utf-8")

    if "צריך להתחבר כדי לכתוב לתמיכה" in src:
        print("✓ כבר מוחל. אין מה לעשות.")
        return
    for dep, why in (("/panel/bans", "add_bans.py לא הוחל — הרץ אותו קודם"),
                     ("def load_bans", "חסרה load_bans"),
                     ("def _norm_email", "חסרה _norm_email"),
                     ("BAN_MESSAGE", "חסרה BAN_MESSAGE")):
        if dep not in src:
            _fail(why)
    if src.count(OLD) != 1:
        _fail(f"נקודת העיגון נמצאה {src.count(OLD)} פעמים (ציפינו לאחת)")

    out = src.replace(OLD, NEW, 1)
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

    bak = f"{TARGET}.bak-fbban-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print("✅ הוחל.")
    print(f"   גיבוי: {os.path.basename(bak)}")
    print()
    print("   הרץ:   systemctl restart zovex-bot")
    print("   נסיגה: python3 fix_feedback_bans.py --undo")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
