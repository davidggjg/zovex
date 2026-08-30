#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מוסיף לשרת חסימת גישה לפי כתובת מייל.

מה זה עושה: רשימת מיילים חסומים בקובץ אחד, נקודת קצה שהלקוחות שואלים בה
"האם המייל הזה חסום", ונקודת קצה מוגנת-סיסמה לניהול הרשימה מהפאנל.

למה בהוספה ולא בעריכה: ה-main.py שרץ בשרת שונה מכל עותק שיש בגיט (הוא
מדווח ערכים שאינם באף ענף), ולכן כל עריכה בתוך קוד קיים היא ניחוש. הבלוק
כאן נוסף *לפני* השורה האחרונה בקובץ ולא נוגע באף שורה קיימת, כך שהסיכון
מוגבל להוספה עצמה.

בטוח: מגבה · בודק שהתוצאה מתקמפלת לפני שכותב · --undo מחזיר.

    python3 add_bans.py          # מחיל
    python3 add_bans.py --undo   # מחזיר את הגיבוי האחרון
"""
import datetime, glob, os, pathlib, py_compile, shutil, sys, tempfile

TARGET = pathlib.Path("/opt/zovex-bot/main.py")
ANCHOR = 'if __name__ == "__main__":'

BLOCK = '''
# ── חסימת גישה לפי מייל ───────────────────────────────────────────────────────
# הגלישה נשארת פתוחה לאורחים; החסימה חלה על מי שמחובר עם חשבון גוגל, לפי
# כתובת המייל שלו. המייל הוא המזהה היחיד שזהה באתר ובאפליקציה (המזהה של
# גוגל שונה בין הפלטפורמות), ולכן חסימה אחת תופסת בשניהם.
BANS_FILE = DATA_DIR / "bans.json"

def _norm_email(e: str) -> str:
    return (e or "").strip().lower()

def load_bans() -> dict:
    try:
        if BANS_FILE.exists():
            return json.loads(BANS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("קריאת bans.json נכשלה: %s", e)
    return {}

def save_bans(d: dict):
    tmp = BANS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(BANS_FILE)          # כתיבה אטומית

BAN_MESSAGE = "הגישה שלך נחסמה"

@api.get("/api/access")
async def check_access(email: str = ""):
    """הלקוח שואל לפני שהוא נותן להיכנס. אורח בלי מייל — תמיד מותר."""
    e = _norm_email(email)
    if not e:
        return {"blocked": False}
    rec = load_bans().get(e)
    if not rec:
        return {"blocked": False}
    return {"blocked": True, "message": rec.get("message") or BAN_MESSAGE}

class BansReq(BaseModel):
    password: str
    action: str                      # list / add / remove
    email: Optional[str] = None
    message: Optional[str] = None

@api.post("/panel/bans")
async def panel_bans(req: BansReq, request: Request):
    check_panel_password(request, req.password)
    d = load_bans()
    if req.action == "add":
        e = _norm_email(req.email)
        if not e or "@" not in e:
            raise HTTPException(status_code=400, detail="כתובת מייל לא תקינה")
        d[e] = {"message": (req.message or "").strip() or BAN_MESSAGE,
                "ts": datetime.utcnow().isoformat()}
        save_bans(d)
    elif req.action == "remove":
        e = _norm_email(req.email)
        if d.pop(e, None) is not None:
            save_bans(d)
    elif req.action != "list":
        raise HTTPException(status_code=400, detail="פעולה לא מוכרת")
    return {"bans": [{"email": k, **v} for k, v in sorted(d.items())]}

'''


def _fail(msg):
    print("❌ " + msg)
    print("   לא שונה כלום.")
    sys.exit(1)


def undo():
    baks = sorted(glob.glob(str(TARGET) + ".bak-bans-*"))
    if not baks:
        _fail("לא נמצא גיבוי")
    shutil.copy2(baks[-1], TARGET)
    print(f"↩️  שוחזר מ-{os.path.basename(baks[-1])}")
    print("   הרץ:  systemctl restart zovex-bot")


def main():
    if not TARGET.exists():
        _fail(f"לא נמצא {TARGET}")
    src = TARGET.read_text(encoding="utf-8")

    if "/panel/bans" in src:
        print("✓ כבר מוחל. אין מה לעשות.")
        return
    if src.count(ANCHOR) != 1:
        _fail(f"העוגן נמצא {src.count(ANCHOR)} פעמים (ציפינו לאחת)")
    # דרישות מהקובץ הקיים — אם אחת חסרה, הבלוק לא יעבוד ועדיף לעצור
    for need in ("DATA_DIR", "check_panel_password", "class BaseModel",
                 "from pydantic import", "log ="):
        if need in src:
            continue
        if need == "class BaseModel" and "from pydantic import" in src:
            continue
        if need == "log =" and "log = logging" in src:
            continue
        _fail(f"לא נמצא '{need}' בקובץ — הבלוק מסתמך עליו")

    out = src.replace(ANCHOR, BLOCK + ANCHOR, 1)

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as t:
        t.write(out); tmp = t.name
    try:
        py_compile.compile(tmp, doraise=True)
    except py_compile.PyCompileError as e:
        os.unlink(tmp); _fail(f"הקוד המשולב לא מתקמפל: {e}")
    os.unlink(tmp)

    bak = f"{TARGET}.bak-bans-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print("✅ הוחל.")
    print(f"   גיבוי: {os.path.basename(bak)}")
    print()
    print("   הרץ:   systemctl restart zovex-bot")
    print("   בדוק:  curl -s 'http://127.0.0.1:8000/api/access?email=test@test.com'")
    print("   נסיגה: python3 add_bans.py --undo")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
