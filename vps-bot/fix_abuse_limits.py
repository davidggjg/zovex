#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_abuse_limits — הגנה מספאם ומניפוח קבצים בנקודות הציבוריות.

נקודות שכל אחד יכול לקרוא להן (מכל אפליקציה, לא רק שלנו):
  /feedback/send, /feedback/mine, /api/progress, /api/history
לא היה עליהן שום גבול: אפשר היה להציף את התמיכה, ולנפח את הקבצים
(feedback/progress/history) עם אלפי מזהי-משתמש מזויפים עד שהשרת נחנק.

מה נוסף (middleware אחד, לא נוגע ב-streaming ולא ב-/content):
  · מגבלת קצב לכל IP: שליחת תמיכה 5 ל-10 דקות ו-30 ליום; קריאת תמיכה 60/דקה;
    התקדמות/היסטוריה 600/דקה.
  · עד 50 מזהי-משתמש שונים ל-IP ביום (נגד יצירת "משתמשים" מזויפים בהמוניהם).
  · מזהה משתמש: עד 128 תווים, רק אותיות/ספרות/-_.:@
  · גוף בקשה עד 16KB בנקודות האלה.
  · בתמיכה: שם עד 80, אימייל עד 120, סוג מתוך רשימה, עד 300 הודעות לשיחה.
חריגה = 429 עם הודעה בעברית. STREAM_ABUSE=0 מכבה.

    python3 fix_abuse_limits.py --check | (ריק) | --revert
אחרי ההחלה: systemctl restart zovex-bot
"""
import os, shutil, sys
PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
MARKER = "[fix_abuse_limits]"

A1 = '@api.post("/feedback/send")\nasync def feedback_send(req: FeedbackSendReq):'
N1 = '''# [fix_abuse_limits] מגבלות קצב לנקודות הציבוריות (תמיכה/התקדמות/היסטוריה)
_ABUSE_ON = os.environ.get("STREAM_ABUSE", "1") != "0"
_abuse_hits: dict = {}     # (ip, bucket) -> [timestamps]
_abuse_uids: dict = {}     # ip -> (day, set(uids))
_ABUSE_RULES = {           # bucket: [(חלון בשניות, מקסימום), ...]
    "fb_send": [(600, 5), (86400, 30)],
    "fb_read": [(60, 60)],
    "user":    [(60, 600)],
}
_UID_RE = re.compile(r"^[A-Za-z0-9_\\-.:@]{1,128}$")

def _abuse_bucket(method: str, path: str):
    if path == "/feedback/send" and method == "POST": return "fb_send"
    if path == "/feedback/mine": return "fb_read"
    if path.startswith("/api/progress") or path.startswith("/api/history"): return "user"
    return None

def _abuse_check(ip: str, bucket: str) -> bool:
    now = time.time()
    rules = _ABUSE_RULES[bucket]
    lst = [t for t in _abuse_hits.get((ip, bucket), []) if now - t < rules[-1][0]]
    for win, mx in rules:
        if sum(1 for t in lst if now - t < win) >= mx:
            _abuse_hits[(ip, bucket)] = lst
            return False
    lst.append(now); _abuse_hits[(ip, bucket)] = lst
    if len(_abuse_hits) > 20000:          # ניקוי זיכרון
        for k in list(_abuse_hits)[:5000]: _abuse_hits.pop(k, None)
    return True

def _abuse_uid_ok(ip: str, uid: str) -> bool:
    day = int(time.time() // 86400)
    d, s = _abuse_uids.get(ip, (day, set()))
    if d != day: s = set()
    if uid not in s:
        if len(s) >= 50: return False
        s.add(uid)
    _abuse_uids[ip] = (day, s)
    if len(_abuse_uids) > 20000: _abuse_uids.clear()
    return True

class _AbuseASGI:
    """ASGI טהור: נוגע רק בנתיבי תמיכה/התקדמות/היסטוריה; כל השאר (וידאו!) עובר כמו שהוא."""
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not _ABUSE_ON:
            return await self.app(scope, receive, send)
        bucket = _abuse_bucket(scope.get("method", ""), scope.get("path", ""))
        if bucket is None:
            return await self.app(scope, receive, send)
        request = Request(scope)
        async def deny(code, msg):
            await JSONResponse({"detail": msg}, status_code=code)(scope, receive, send)
        try:
            if int(request.headers.get("content-length") or 0) > 16384:
                return await deny(413, "הבקשה גדולה מדי")
        except ValueError:
            return await deny(400, "בקשה לא תקינה")
        ip = _client_ip(request)
        if not _abuse_check(ip, bucket):
            return await deny(429, "יותר מדי בקשות — נסה שוב מאוחר יותר")
        uid = request.headers.get("x-user-id") or request.query_params.get("user_id")
        if uid is not None:
            if not _UID_RE.match(uid):
                return await deny(400, "מזהה משתמש לא תקין")
            if scope.get("method") == "POST" and not _abuse_uid_ok(ip, uid):
                return await deny(429, "יותר מדי משתמשים מאותה כתובת")
        return await self.app(scope, receive, send)

api.add_middleware(_AbuseASGI)

@api.post("/feedback/send")
async def feedback_send(req: FeedbackSendReq):'''

A2 = '''    if req.name:  th["name"] = req.name
    if req.email: th["email"] = req.email
    if req.fcm_token: th["fcm_token"] = req.fcm_token
    th["messages"].append({"from": "user", "text": text[:4000],
                           "ts": datetime.utcnow().isoformat(), "kind": req.kind or "support"})'''
N2 = '''    if not _UID_RE.match(req.user_id or ""):          # [fix_abuse_limits]
        raise HTTPException(status_code=400, detail="מזהה משתמש לא תקין")
    if req.name:  th["name"] = req.name[:80]
    if req.email: th["email"] = req.email[:120]
    if req.fcm_token: th["fcm_token"] = req.fcm_token[:300]
    _kind = req.kind if req.kind in ("support", "review", "tip", "bug", "request") else "support"
    th["messages"].append({"from": "user", "text": text[:4000],
                           "ts": datetime.utcnow().isoformat(), "kind": _kind})
    th["messages"] = th["messages"][-300:]   # [fix_abuse_limits] גג לשיחה'''

EDITS = [("middleware", A1, N1), ("שדות תמיכה", A2, N2)]

def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read()
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        out = src
        for _, a, n in EDITS: out = out.replace(n, a, 1)
        compile(out, "main.py", "exec")
        shutil.copy2(PATH, PATH + ".bak_abuse"); open(PATH, "w", encoding="utf-8").write(out)
        print("✓ שוחזר"); return 0
    if MARKER in src: print("✓ כבר מותקן"); return 0
    out = src
    for name, a, n in EDITS:
        c = out.count(a); assert c == 1, f"עוגן '{name}': נמצא {c} פעמים"
        out = out.replace(a, n, 1)
    for need in ("JSONResponse", "def _client_ip", "Request"):
        assert need in out, f"חסר {need} ב-main.py"
    compile(out, "main.py", "exec")
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    shutil.copy2(PATH, PATH + ".bak_abuse"); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", PATH + ".bak_abuse"); return 0

if __name__ == "__main__": sys.exit(main())
