"""דשבורד ניהול — FastAPI. קורא את אותו SQLite כמו הבוט.

כניסה: Telegram Login Widget. מאמתים את החתימה מול טוקן הבוט, בודקים שהמשתמש
ב-OWNER_IDS, ומנפיקים עוגיית סשן חתומה. רק בעלים נכנסים.

מוגש דרך nginx על הדומיין הראשי (הווידג'ט של טלגרם דורש דומיין תואם).
"""
import hashlib
import hmac
import time
from pathlib import Path

import aiosqlite
from fastapi import Cookie, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import config

import os  # noqa: E402

app = FastAPI(title="ZOVEX Bot Panel")
_STATIC = Path(__file__).parent / "static"

# הקידומת שדרכה nginx מגיש את הדשבורד (למשל /panel). משמש לעוגייה ולהפניה.
PANEL_BASE = os.environ.get("PANEL_BASE", "/panel").rstrip("/")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "")

SESSION_TTL = 7 * 24 * 3600
_SECRET = (config.DASHBOARD_SECRET or config.BOT_TOKEN or "zovex").encode()


# ── סשן חתום (בלי תלות חיצונית) ───────────────────────────────────────────────
def _sign(uid: int) -> str:
    exp = int(time.time()) + SESSION_TTL
    body = f"{uid}.{exp}"
    sig = hmac.new(_SECRET, body.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{sig}"


def _verify_session(token: str) -> int | None:
    try:
        uid, exp, sig = token.split(".")
        body = f"{uid}.{exp}"
        good = hmac.new(_SECRET, body.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(good, sig):
            return None
        if int(exp) < time.time():
            return None
        return int(uid)
    except Exception:
        return None


def _require_owner(session: str | None) -> int:
    uid = _verify_session(session or "")
    if uid is None or uid not in config.OWNER_IDS:
        raise HTTPException(401, "לא מחובר")
    return uid


# ── אימות Telegram Login Widget ──────────────────────────────────────────────
def _verify_telegram(data: dict) -> bool:
    recv = data.pop("hash", None)
    check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret = hashlib.sha256(config.BOT_TOKEN.encode()).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, recv or ""):
        return False
    return time.time() - int(data.get("auth_date", 0)) < 86400


@app.get("/auth/telegram")
async def auth_telegram(request: Request):
    data = dict(request.query_params)
    if not _verify_telegram(dict(data)):
        return HTMLResponse("<h3>אימות נכשל</h3>", status_code=403)
    uid = int(data.get("id", 0))
    if uid not in config.OWNER_IDS:
        return HTMLResponse("<h3>אין הרשאה — רק בעלים</h3>", status_code=403)
    resp = RedirectResponse(PANEL_BASE + "/")
    resp.set_cookie("zx_session", _sign(uid), max_age=SESSION_TTL, path=PANEL_BASE or "/",
                    httponly=True, samesite="lax", secure=True)
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse(PANEL_BASE + "/")
    resp.delete_cookie("zx_session", path=PANEL_BASE or "/")
    return resp


# ── API (בעלים בלבד) ──────────────────────────────────────────────────────────
async def _rows(q, params=()):
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(q, params)
        return [dict(r) for r in await cur.fetchall()]


@app.get("/api/me")
async def api_me(zx_session: str = Cookie(None)):
    return {"owner_id": _require_owner(zx_session)}


@app.get("/api/stats")
async def api_stats(zx_session: str = Cookie(None)):
    _require_owner(zx_session)
    from . import db
    return await db.stats()


@app.get("/api/channels")
async def api_channels(status: str = "", zx_session: str = Cookie(None)):
    _require_owner(zx_session)
    if status:
        return await _rows("SELECT * FROM channels WHERE status=? ORDER BY added_at DESC", (status,))
    return await _rows("SELECT * FROM channels ORDER BY added_at DESC")


@app.post("/api/channels/{chat_id}/{action}")
async def api_channel_action(chat_id: int, action: str, zx_session: str = Cookie(None)):
    _require_owner(zx_session)
    if action not in ("approve", "reject"):
        raise HTTPException(400, "פעולה לא חוקית")
    from . import db
    await db.set_channel_status(chat_id, "approved" if action == "approve" else "rejected")
    return {"ok": True}


@app.get("/api/content")
async def api_content(q: str = "", limit: int = 50, zx_session: str = Cookie(None)):
    _require_owner(zx_session)
    if q:
        return await _rows(
            "SELECT * FROM content WHERE norm LIKE ? ORDER BY added_at DESC LIMIT ?",
            (f"%{q.lower()}%", limit))
    return await _rows("SELECT * FROM content ORDER BY added_at DESC LIMIT ?", (limit,))


@app.get("/api/users")
async def api_users(limit: int = 100, zx_session: str = Cookie(None)):
    _require_owner(zx_session)
    return await _rows("SELECT * FROM users ORDER BY last_seen DESC LIMIT ?", (limit,))


@app.get("/api/requests")
async def api_requests(limit: int = 100, zx_session: str = Cookie(None)):
    _require_owner(zx_session)
    return await _rows("SELECT * FROM requests ORDER BY at DESC LIMIT ?", (limit,))


# ── דף הדשבורד ────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    html = html.replace("{{BOT_USERNAME}}", BOT_USERNAME).replace("{{PANEL_BASE}}", PANEL_BASE)
    return HTMLResponse(html)
