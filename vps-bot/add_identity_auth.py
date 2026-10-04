#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""add_identity_auth — שהזהות תהיה מה שהשרת אימת, לא מה שהלקוח אמר.

## התקלה

ארבעה נתיבי קריאה מחזירים מידע אישי לפי מזהה שהלקוח שולח, בלי שום
אימות:

    GET /feedback/mine?user_id=...        שיחת התמיכה המלאה
    GET /api/history                      היסטוריית הצפייה
    GET /api/favorites                    המועדפים
    GET /api/progress/{media_id}          המיקום השמור

ובמשוב המזהה הוא ‎"g:" + כתובת המייל‎. כלומר **מי שיודע מייל של
משתמש קורא את כל שיחת התמיכה שלו** — בלי כלים, בלי סיסמה, משורת
כתובת בדפדפן.

זה לא תיאורטי: ביומנים נמצאו 19 קריאות מוצלחות ל-‎/feedback/mine‎
מכתובת סורקת, כולל ניסיונות הזרקה בשדה ‎user_id‎. במקרה הזה הן
החזירו ריק — הסורק בדק רק את החשבונות שהוא עצמו יצר. הבא בתור
לא יסתפק בזה.

## הפתרון

השרת מאמת מול גוגל **פעם אחת** בכניסה ומנפיק אסימון חתום ב-HMAC.
אחר כך כל בקשה נבדקת מול חתימה מקומית, בלי אף קריאת רשת.

שני סוגי אישורים, כי שני הלקוחות מחזיקים דברים שונים:

    אפליקציה → ‎id_token‎      (Google Sign-In, כבר מתקבל ונזרק)
    אתר      → ‎access_token‎  (זרימת OAuth2 הקיימת)

## ההחלה מדורגת — וזה העיקר

משתמש נכנס לרשימת ה"מאומתים" רק אחרי שהציג אסימון תקף **פעם אחת**.
עד אז הוא עובד בדיוק כמו קודם.

כלומר ברגע ההחלה **שום לקוח אינו נשבר** — לא אפליקציה ישנה, לא
דפדפן שלא רוענן. ההגנה נסגרת לכל משתמש בנפרד, ברגע שהוא מעדכן.
אחרי שהעדכון יתפשט אפשר להפוך את זה לחובה גורפת בשורה אחת.

## למה לא middleware

‎BaseHTTPMiddleware‎ של Starlette מאגר תשובות זורמות, וההערה בקוד
מציינת במפורש שנמנעו ממנו "כדי לא לגעת ב-streaming הרגיש". פיצ'ר
אבטחה ששובר וידאו לכל המשתמשים אינו שיפור אבטחה.

    python3 add_identity_auth.py --check
    python3 add_identity_auth.py
    python3 add_identity_auth.py --revert

אחרי ההחלה:  systemctl restart zovex-bot
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_identity_auth"
MARK = "add_identity_auth"

# ── 1. המודול עצמו, מיד אחרי רישום ה-CORS ───────────────────────────────
A_CORS = '''api.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
'''

N_CORS = A_CORS + '''
# ── [add_identity_auth] זהות מאומתת ─────────────────────────────────────
#
# עד כאן הזהות הייתה מה שהלקוח הצהיר: user_id בשורת השאילתה, או
# x-user-id בכותרת. אף אחד לא בדק אותה. ומכיוון שמזהה המשוב הוא
# "g:" + המייל, מי שידע מייל קרא את כל שיחת התמיכה של אותו אדם.
#
# מכאן: גוגל מאמתת פעם אחת, השרת חותם, וכל בקשה נבדקת מקומית.
ZX_CLIENT_ID = os.environ.get(
    "GOOGLE_CLIENT_ID",
    "537028202942-tra1klpqsbu6uo475gshp5r43m68h47m.apps.googleusercontent.com")
ZX_VERIFIED_FILE = DATA_DIR / "verified_users.json"
ZX_TOKEN_TTL = int(os.environ.get("ZX_TOKEN_TTL", str(30 * 86400)))
_zx_cache = {"mtime": -1.0, "ids": set()}


def _zx_secret() -> bytes:
    """הפרדת תחום. אותו SIGN_SECRET חותם גם כתובות הזרמה, ובלי
    הקידומת הזו חתימה של זרם הייתה מתקבלת כאסימון זהות."""
    return ("zx-identity-v1:" + (SIGN_SECRET or "")).encode()


def _zx_b64(b: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _zx_unb64(s: str) -> bytes:
    import base64
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _zx_sig(body: str) -> str:
    import hashlib
    return _zx_b64(hmac.new(_zx_secret(), body.encode(), hashlib.sha256).digest())


def _zx_make_token(sub: str, email: str) -> str:
    body = _zx_b64(json.dumps(
        {"s": sub, "e": email, "x": int(time.time()) + ZX_TOKEN_TTL},
        separators=(",", ":")).encode())
    return body + "." + _zx_sig(body)


def _zx_read_token(tok: str):
    """(sub, email) או None. אינו זורק: אסימון פגום = לא מאומת, ולא 500."""
    try:
        body, sig = (tok or "").split(".", 1)
        if not hmac.compare_digest(sig, _zx_sig(body)):
            return None
        d = json.loads(_zx_unb64(body))
        if int(d.get("x", 0)) < time.time():
            return None
        return str(d.get("s") or ""), str(d.get("e") or "")
    except Exception:
        return None


def _zx_verified() -> set:
    """נקרא בכל בקשה מוגנת, ולכן נשמר במטמון לפי זמן השינוי."""
    try:
        mt = ZX_VERIFIED_FILE.stat().st_mtime
    except OSError:
        return set()
    if mt != _zx_cache["mtime"]:
        try:
            _zx_cache["ids"] = set(json.loads(
                ZX_VERIFIED_FILE.read_text(encoding="utf-8")))
            _zx_cache["mtime"] = mt
        except Exception:
            return _zx_cache["ids"]
    return _zx_cache["ids"]


def _zx_mark_verified(ids) -> None:
    cur = _zx_verified()
    new = cur | {i for i in ids if i}
    if new != cur:
        ZX_VERIFIED_FILE.write_text(
            json.dumps(sorted(new), ensure_ascii=False), encoding="utf-8")
        _zx_cache["mtime"] = -1.0


def _zx_require(token: str, claimed: str) -> None:
    """עוצר רק מי שכבר הוכיח פעם אחת שהוא יודע להציג אסימון.

    משתמש שמעולם לא התחבר מלקוח מעודכן אינו ברשימה, ולכן ממשיך
    לעבוד. בלי התנאי הזה כל אפליקציה שלא עודכנה הייתה נשברת ברגע
    ההחלה — וזה מחיר שאי אפשר לשלם על תיקון אבטחה.
    """
    claimed = (claimed or "").strip()
    if not claimed or claimed not in _zx_verified():
        return
    ident = _zx_read_token(token)
    if not ident:
        raise HTTPException(status_code=401, detail="נדרשת התחברות מחדש")
    sub, email = ident
    if claimed != sub and claimed != "g:" + email:
        raise HTTPException(status_code=403, detail="הזהות אינה תואמת")


class ZxSessionReq(BaseModel):
    id_token: Optional[str] = ""
    access_token: Optional[str] = ""


@api.post("/auth/session")
async def zx_auth_session(req: ZxSessionReq):
    """מאמת מול גוגל ומנפיק אסימון. הקריאה היחידה שיוצאת לרשת."""
    sub = email = ""
    try:
        async with httpx.AsyncClient(timeout=15) as cx:
            if req.id_token:
                r = await cx.get("https://oauth2.googleapis.com/tokeninfo",
                                 params={"id_token": req.id_token})
                d = r.json() if r.status_code == 200 else {}
                # aud חייב להיות **שלנו**. בלי הבדיקה הזו כל אסימון
                # גוגל תקף מכל אפליקציה אחרת בעולם היה מתקבל כאן.
                if d.get("aud") == ZX_CLIENT_ID:
                    sub, email = str(d.get("sub") or ""), str(d.get("email") or "")
            elif req.access_token:
                r = await cx.get(
                    "https://www.googleapis.com/oauth2/v3/userinfo",
                    headers={"Authorization": "Bearer " + req.access_token})
                d = r.json() if r.status_code == 200 else {}
                sub, email = str(d.get("sub") or ""), str(d.get("email") or "")
    except Exception as e:
        raise HTTPException(status_code=503, detail="אימות מול גוגל נכשל: %s" % e)
    if not sub or not email:
        raise HTTPException(status_code=401, detail="האישור מגוגל אינו תקף")
    _zx_mark_verified([sub, "g:" + email])
    return {"token": _zx_make_token(sub, email), "expires_in": ZX_TOKEN_TTL}
'''

# ── 2–5. ארבעת המטפלים שמחזירים מידע אישי ───────────────────────────────
A_PROG = '''async def get_progress(
    media_id: str,
    x_user_id: str = Header(..., description="Google User ID")
):
'''
N_PROG = '''async def get_progress(
    media_id: str,
    x_user_id: str = Header(..., description="Google User ID"),
    x_zovex_auth: str = Header("", alias="x-zovex-auth"),
):
    _zx_require(x_zovex_auth, x_user_id)   # [add_identity_auth]
'''

A_HIST = '''async def get_history(
    x_user_id: str = Header(..., description="Google User ID")
):
'''
N_HIST = '''async def get_history(
    x_user_id: str = Header(..., description="Google User ID"),
    x_zovex_auth: str = Header("", alias="x-zovex-auth"),
):
    _zx_require(x_zovex_auth, x_user_id)   # [add_identity_auth]
'''

A_FAV = '''async def get_favorites(x_user_id: str = Header(..., description="Google User ID")):
    db = load_json(FAVORITES_FILE)
'''
N_FAV = '''async def get_favorites(x_user_id: str = Header(..., description="Google User ID"),
                        x_zovex_auth: str = Header("", alias="x-zovex-auth")):
    _zx_require(x_zovex_auth, x_user_id)   # [add_identity_auth]
    db = load_json(FAVORITES_FILE)
'''

A_MINE = '''async def feedback_mine(user_id: str):
'''
N_MINE = '''async def feedback_mine(user_id: str,
                        x_zovex_auth: str = Header("", alias="x-zovex-auth")):
    # [add_identity_auth] כאן המזהה הוא "g:" + המייל — כלומר ניתן
    # לניחוש לחלוטין. זה הנתיב שנסרק בפועל, 19 פעמים.
    _zx_require(x_zovex_auth, user_id)
'''

EDITS = [
    ("מודול הזהות", A_CORS, N_CORS, 1),
    ("מיקום שמור", A_PROG, N_PROG, 1),
    ("היסטוריה", A_HIST, N_HIST, 1),
    ("מועדפים", A_FAV, N_FAV, 1),
    ("שיחת תמיכה", A_MINE, N_MINE, 1),
]


def fn_source(src: str, name: str) -> str:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError("לא נמצאה הפונקציה %s" % name)


def validate(out: str) -> None:
    compile(out, "main.py", "exec")

    # ── כל ארבעת המטפלים באמת קוראים לשומר ──────────────────────────────
    for fn, claimed in (("get_progress", "x_user_id"),
                        ("get_history", "x_user_id"),
                        ("get_favorites", "x_user_id"),
                        ("feedback_mine", "user_id")):
        body = fn_source(out, fn)
        assert "_zx_require(" in body, "%s אינו מוגן" % fn
        assert "x_zovex_auth" in body, "%s אינו מקבל את הכותרת" % fn
        assert "_zx_require(x_zovex_auth, %s)" % claimed in body, \
            "%s מעביר לשומר את הערך הלא נכון" % fn
        # והשומר לפני כל קריאת נתונים, לא אחריה
        i_g = body.index("_zx_require(")
        for reader in ("load_json(", "load_feedback()"):
            if reader in body:
                assert i_g < body.index(reader), \
                    "%s קורא נתונים לפני הבדיקה" % fn

    # ── והמנגנון עצמו, מורץ ─────────────────────────────────────────────
    import json as _json
    import time as _time
    import hmac as _hmac
    ns = {"os": os, "json": _json, "time": _time, "hmac": _hmac,
          "SIGN_SECRET": "sekrit", "HTTPException": _FakeHTTP,
          "ZX_TOKEN_TTL": 3600, "_zx_cache": {"mtime": -1.0, "ids": set()},
          "_VERIFIED": set()}
    for fn in ("_zx_secret", "_zx_b64", "_zx_unb64", "_zx_sig",
               "_zx_make_token", "_zx_read_token", "_zx_require"):
        exec(fn_source(out, fn), ns)
    # ‎_zx_verified‎ קורא מהדיסק — מחליפים אותו ברשימה בזיכרון
    ns["_zx_verified"] = lambda: ns["_VERIFIED"]

    make, read, need = ns["_zx_make_token"], ns["_zx_read_token"], ns["_zx_require"]

    tok = make("12345", "a@b.com")
    assert read(tok) == ("12345", "a@b.com"), "הלוך-חזור נכשל"

    # חתימה מזויפת
    body, sig = tok.split(".", 1)
    assert read(body + "." + sig[:-2] + "xx") is None, "חתימה שגויה התקבלה"
    # ועריכה של המטען בלי לעדכן חתימה
    bad = ns["_zx_b64"](_json.dumps(
        {"s": "99999", "e": "evil@b.com", "x": int(_time.time()) + 99}).encode())
    assert read(bad + "." + sig) is None, "מטען שהוחלף התקבל"
    assert read("") is None and read("zzz") is None, "אסימון פגום הפיל"

    # פג תוקף
    ns["ZX_TOKEN_TTL"] = -10
    assert read(make("1", "a@b.com")) is None, "אסימון שפג התקבל"
    ns["ZX_TOKEN_TTL"] = 3600

    # ── ההתנהגות המדורגת ────────────────────────────────────────────────
    need("", "12345")                      # לא ברשימה ⇒ עובר
    need("garbage", "g:a@b.com")           # גם עם אסימון אשפה
    ns["_VERIFIED"] = {"12345", "g:a@b.com"}

    _raised(need, "", "12345", 401, "מאומת בלי אסימון לא נחסם")
    _raised(need, "garbage", "12345", 401, "אסימון פגום התקבל")
    need(tok, "12345")                     # האמיתי עובר
    need(tok, "g:a@b.com")                 # וגם בצורת המייל

    # אסימון תקף של משתמש אחד, מול זהות של **אחר שגם הוא מאומת**.
    # הקורבן חייב להיות ברשימה, אחרת השומר יוצא מוקדם בדרך הישנה
    # והבדיקה עוברת בריק — זו בדיוק הטעות שהייתה כאן בניסוח הראשון.
    ns["_VERIFIED"] = {"12345", "g:a@b.com", "77777", "g:victim@b.com"}
    _raised(need, tok, "77777", 403, "אסימון של אחד פתח זהות של אחר")
    _raised(need, tok, "g:victim@b.com", 403,
            "אסימון של אחד פתח מייל של אחר")

    # ── השוואת החתימה חייבת להיות בזמן קבוע ─────────────────────────────
    # ‎==‎ על מחרוזות יוצא ברגע ההבדל הראשון, ולכן זמן התשובה מדליף כמה
    # תווים נכונים — אפשר לבנות חתימה תו-תו. התנהגותית ‎==‎ ו-
    # ‎compare_digest‎ זהים לחלוטין (שניהם דוחים את אותם קלטים), ולכן
    # שום בדיקה מורצת לא תתפוס את ההחלפה. רק טענה על הקוד תתפוס.
    rd = fn_source(out, "_zx_read_token")
    assert "hmac.compare_digest(" in rd, \
        "השוואת החתימה אינה בזמן קבוע — השתמש ב-hmac.compare_digest"
    assert "sig ==" not in rd and "== _zx_sig" not in rd, \
        "נשארה השוואת חתימה רגילה"

    # ── והפרדת התחום ────────────────────────────────────────────────────
    s1 = ns["_zx_secret"]()
    assert s1.startswith(b"zx-identity-v1:"), "אין הפרדת תחום"
    assert b"sekrit" in s1, "הסוד אינו בשימוש"

    # ── aud נבדק ────────────────────────────────────────────────────────
    sess = fn_source(out, "zx_auth_session")
    assert 'd.get("aud") == ZX_CLIENT_ID' in sess, \
        "aud אינו נבדק — אסימון מכל אפליקציית גוגל אחרת היה מתקבל"
    assert "_zx_mark_verified" in sess, "הנפקה אינה מסמנת את המשתמש"


class _FakeHTTP(Exception):
    def __init__(self, status_code=0, detail="", **kw):
        self.status_code = status_code
        super().__init__(detail)


def _raised(fn, *args):
    want, msg = args[-2], args[-1]
    try:
        fn(*args[:-2])
    except _FakeHTTP as e:
        assert e.status_code == want, \
            "%s (קיבלנו %s, ציפינו %s)" % (msg, e.status_code, want)
        return
    raise AssertionError(msg)


def main() -> None:
    if not os.path.exists(PATH):
        sys.exit("אין קובץ ב-%s (אפשר MAIN_PY=...)" % PATH)
    with open(PATH, encoding="utf-8") as fh:
        src = fh.read()

    if "--revert" in sys.argv:
        if not os.path.exists(BAK):
            sys.exit("אין גיבוי ב-%s" % BAK)
        shutil.copy2(BAK, PATH)
        print("✓ שוחזר מ-%s" % BAK)
        return

    if MARK in src:
        print("כבר מותקן.")
        return

    out = src
    for label, a, n, want in EDITS:
        got = out.count(a)
        if got != want:
            sys.exit("✗ העוגן '%s' נמצא %d פעמים (צפוי %d) — לא נוגע בכלום."
                     % (label, got, want))
        out = out.replace(a, n)

    validate(out)
    print("✓ כל הבדיקות עברו")
    if "--check" in sys.argv:
        print("--check: שום דבר לא נכתב.")
        return

    shutil.copy2(PATH, BAK)
    with open(PATH, "w", encoding="utf-8") as fh:
        fh.write(out)
    print("✓ הוחל. גיבוי: %s" % BAK)
    print()
    print("systemctl restart zovex-bot")
    print()
    print("שום לקוח אינו נשבר עכשיו: ההגנה חלה רק על מי שכבר הציג אסימון.")
    print("השלב הבא הוא לגרום ללקוחות לקרוא ל-/auth/session ולשלוח את")
    print("האסימון בכותרת x-zovex-auth.")


if __name__ == "__main__":
    main()
