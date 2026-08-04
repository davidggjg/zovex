#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# AppMod · שירות חנות האפליקציות (נפרד לגמרי משרת הסרטים)
#   • מגיש את האתר (index.html) ואת רשימת האפליקציות (/apps/content)
#   • קבלה: Bot API (getUpdates) — טלגרם פותר את הערוץ בשרת שלו, בלי Peer id invalid
#   • הורדה: Pyrogram stream_media לפי file_id — בלי הגבלת 20MB, בלי לפתור את הערוץ
#   • פאנל ניהול קטן לעריכת פרטים (אייקון/תיאור/קטגוריה/צילומי מסך)
# רץ על פורט 8001 (שרת הסרטים על 8000) — לא נוגעים אחד בשני.
#
# למה שתי טכנולוגיות?
#   בוטים לא יכולים לפתור ערוץ פרטי ב-Pyrogram (Peer id invalid / CheckChatInvite
#   אסור לבוטים), אז *קבלת* הפוסטים חייבת לעבור דרך Bot API. אבל Bot API מגביל
#   הורדות ל-20MB, ו-APK גדול מזה — לכן *ההורדה* עוברת דרך Pyrogram לפי file_id,
#   ש-מקודד בתוכו את כל מה שצריך (dc/מזהה/access_hash) ולא דורש לפתור את הערוץ.
# ─────────────────────────────────────────────────────────────────────────────
import os, re, json, time, asyncio, logging, uuid
import urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from pyrogram import Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("appmod")

# ── הגדרות (מ-.env / משתני סביבה) ────────────────────────────────────────────
BOT_TOKEN   = os.environ["APPS_BOT_TOKEN"]                       # הטוקן של בוט האפליקציות
API_ID      = int(os.environ.get("APPS_API_ID", os.environ.get("API_ID", "0")))
API_HASH    = os.environ.get("APPS_API_HASH", os.environ.get("API_HASH", ""))
CHANNEL_ID  = int(os.environ.get("APPS_CHANNEL_ID", "-1004358130306"))
PANEL_PASS  = os.environ.get("APPS_PANEL_PASSWORD", "changeme")
PUBLIC_BASE = os.environ.get("APPS_PUBLIC_BASE", "https://appmod.duckdns.org").rstrip("/")
DATA_DIR    = Path(os.environ.get("APPS_DATA_DIR", "/opt/appmod/data"))
HERE        = Path(__file__).resolve().parent
DATA_DIR.mkdir(parents=True, exist_ok=True)
APPS_FILE   = DATA_DIR / "apps.json"
CATS_FILE   = DATA_DIR / "categories.json"
OFFSET_FILE = DATA_DIR / "update_offset.txt"

BOT_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
DEFAULT_CATS = ["כללי"]

def load_apps() -> list:
    if APPS_FILE.exists():
        try: return json.loads(APPS_FILE.read_text(encoding="utf-8"))
        except Exception: return []
    return []

def save_apps(arr: list):
    APPS_FILE.write_text(json.dumps(arr, ensure_ascii=False, indent=2), encoding="utf-8")

def load_cats() -> list:
    if CATS_FILE.exists():                     # אם נשמר (גם ריק) — מכבדים בדיוק
        try:
            c = json.loads(CATS_FILE.read_text(encoding="utf-8"))
            if isinstance(c, list): return c
        except Exception: pass
        return []
    return list(DEFAULT_CATS)                   # רק בפעם הראשונה — זריעת ברירת מחדל

def save_cats(arr: list):
    clean = [str(x).strip() for x in arr if str(x).strip()]
    seen, out = set(), []
    for c in clean:
        if c not in seen: seen.add(c); out.append(c)   # מכבד גם רשימה ריקה
    CATS_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out

def human_size(n) -> str:
    n = float(n or 0)
    for u in ("B","KB","MB","GB"):
        if n < 1024 or u == "GB":
            return (f"{n:.0f} {u}" if u in ("B","KB") else f"{n:.1f} {u}")
        n /= 1024
    return f"{n:.1f} GB"

def clean_app_name(fname: str) -> str:
    n = re.sub(r"\.apk$", "", fname or "", flags=re.I)
    n = re.sub(r"[._]+", " ", n)
    n = re.sub(r"\b(v?\d+(\.\d+)+|mod|premium|pro|apk|android)\b", " ", n, flags=re.I)
    return re.sub(r"\s+", " ", n).strip() or "אפליקציה"

# ── לקוח Pyrogram — לשימוש *רק להורדה* לפי file_id (לא מאזין לעדכונים) ─────────
# no_updates=True: לא מושך עדכונים כלל, כדי לא להתנגש עם ה-getUpdates של ה-Bot API.
bot = Client("appmod_dl", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN,
             in_memory=True, no_updates=True, workdir=str(DATA_DIR))

# ── Bot API (HTTP) — קבלת פוסטים מהערוץ ──────────────────────────────────────
def _api(method: str, params: dict = None, timeout: int = 65) -> dict:
    """קריאה סינכרונית ל-Bot API (רצה ב-thread כדי לא לחסום את asyncio)."""
    data = urllib.parse.urlencode(params or {}).encode()
    req = urllib.request.Request(f"{BOT_API}/{method}", data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def load_offset() -> int:
    try: return int(OFFSET_FILE.read_text().strip())
    except Exception: return 0

def save_offset(v: int):
    try: OFFSET_FILE.write_text(str(v))
    except Exception: pass

def _is_apk_doc(doc: dict) -> bool:
    fn = (doc.get("file_name") or "").lower()
    mt = (doc.get("mime_type") or "").lower()
    return fn.endswith(".apk") or "android.package" in mt

# ── הרשאות: רק מנהלי הערוץ יכולים להוסיף אפליקציות דרך הבוט ───────────────────
_admin_ids: set = set()
_admin_ts: float = 0.0

def get_admin_ids(force: bool = False) -> set:
    global _admin_ids, _admin_ts
    if not force and _admin_ids and (time.time() - _admin_ts) < 300:
        return _admin_ids
    try:
        r = _api("getChatAdministrators", {"chat_id": CHANNEL_ID}, 20)
        ids = {m["user"]["id"] for m in r.get("result", []) if m.get("user")}
        if ids:
            _admin_ids, _admin_ts = ids, time.time()
    except Exception as e:
        log.warning("getChatAdministrators נכשל: %s", e)
    return _admin_ids

def add_from_post(post: dict):
    """מוסיף APK לחנות מתוך הודעת ערוץ (Bot API). מחזיר את הרשומה או None אם כבר קיים."""
    doc = post.get("document")
    if not doc or not _is_apk_doc(doc):
        return None
    chat_id = post.get("chat", {}).get("id", CHANNEL_ID)
    msg_id  = post.get("message_id")
    apps = load_apps()
    if any(a.get("channel_msg_id") == msg_id and a.get("channel_id") == chat_id for a in apps):
        return None
    cap  = (post.get("caption") or "").strip()
    name = (cap.splitlines()[0].strip() if cap else "") or clean_app_name(doc.get("file_name", ""))
    cats = load_cats()
    entry = {
        "id": uuid.uuid4().hex[:12],
        "name": name, "category": cats[0] if cats else "",
        "image": "", "icon": "", "banner": "",
        "description": cap if cap else "",
        "version": "", "size": human_size(doc.get("file_size", 0)),
        "updated": datetime.utcnow().strftime("%d/%m/%Y"),
        "screenshots": [],
        "channel_id": chat_id, "channel_msg_id": msg_id,
        "file_id": doc.get("file_id", ""),
        "file_name": doc.get("file_name", "app.apk"),
        "file_size": doc.get("file_size", 0),
    }
    apps.insert(0, entry)
    save_apps(apps)
    log.info("✅ APK חדש נוסף: %s (msg %s)", name, msg_id)
    return entry

def handle_private_message(msg: dict):
    """שליחת APK בפרטי לבוט → מעביר לערוץ (ארכיון) ומוסיף לחנות. מנהלי ערוץ בלבד."""
    chat_id = msg.get("chat", {}).get("id")
    uid = (msg.get("from") or {}).get("id")
    doc = msg.get("document")
    if not doc:
        _api("sendMessage", {"chat_id": chat_id,
             "text": "שלח לי קובץ APK ואוסיף אותו לחנות אוטומטית."}, 20)
        return
    if uid not in get_admin_ids() and uid not in get_admin_ids(force=True):
        _api("sendMessage", {"chat_id": chat_id,
             "text": "⛔ רק מנהלי הערוץ יכולים להוסיף אפליקציות."}, 20)
        return
    if not _is_apk_doc(doc):
        _api("sendMessage", {"chat_id": chat_id, "text": "זה לא קובץ APK. שלח קובץ .apk."}, 20)
        return
    # מעביר לערוץ (מקור הורדה יציב + ארכיון), משתמש שוב ב-file_id
    params = {"chat_id": CHANNEL_ID, "document": doc["file_id"]}
    cap = (msg.get("caption") or "").strip()
    if cap: params["caption"] = cap
    try:
        r = _api("sendDocument", params, 90)
    except Exception as e:
        log.warning("sendDocument לערוץ נכשל: %s", e)
        _api("sendMessage", {"chat_id": chat_id, "text": "ההעברה לערוץ נכשלה, נסה שוב."}, 20)
        return
    post = r.get("result")
    entry = add_from_post(post) if post else None
    name = entry["name"] if entry else clean_app_name(doc.get("file_name", ""))
    _api("sendMessage", {"chat_id": chat_id,
         "text": f"✅ «{name}» נוסף לחנות.\nערוך פרטים (אייקון/תיאור/קטגוריה) בפאנל:\n{PUBLIC_BASE}/apps/admin"}, 20)

async def poll_loop():
    """לולאת long-polling של getUpdates — מאזינה לערוץ ולהודעות פרטיות."""
    # מבטלים webhook אם הוגדר בעבר (אחרת getUpdates מחזיר 409)
    try:
        await asyncio.to_thread(_api, "deleteWebhook", {"drop_pending_updates": "false"}, 20)
    except Exception as e:
        log.warning("deleteWebhook: %s", e)
    offset = load_offset()
    log.info("📡 מאזין לערוץ %s דרך Bot API (offset=%s)", CHANNEL_ID, offset)
    allowed = json.dumps(["channel_post", "edited_channel_post", "message"])
    while True:
        try:
            resp = await asyncio.to_thread(_api, "getUpdates", {
                "offset": offset, "timeout": 50, "allowed_updates": allowed,
            }, 65)
            for upd in resp.get("result", []):
                offset = upd["update_id"] + 1
                post = upd.get("channel_post") or upd.get("edited_channel_post")
                msg  = upd.get("message")
                try:
                    if post:
                        await asyncio.to_thread(add_from_post, post)
                    elif msg and (msg.get("chat") or {}).get("type") == "private":
                        await asyncio.to_thread(handle_private_message, msg)
                except Exception as e:
                    log.warning("עיבוד עדכון נכשל: %s", e)
            save_offset(offset)
        except Exception as e:
            log.warning("getUpdates נכשל: %s", e)
            await asyncio.sleep(3)

# ── FastAPI ──────────────────────────────────────────────────────────────────
api = FastAPI(title="AppMod")

@api.on_event("startup")
async def _start():
    await bot.start()                       # ללקוח ההורדה (Pyrogram)
    asyncio.create_task(poll_loop())        # לולאת הקבלה (Bot API)
    log.info("בוט AppMod פעיל. ערוץ=%s", CHANNEL_ID)

@api.on_event("shutdown")
async def _stop():
    try: await bot.stop()
    except Exception: pass

@api.get("/", response_class=HTMLResponse)
async def index():
    f = HERE / "index.html"
    return HTMLResponse(f.read_text(encoding="utf-8")) if f.exists() else HTMLResponse("<h1>AppMod</h1>")

@api.get("/apps/content")
async def content():
    """רשימת האפליקציות לתצוגה — מזריק כתובת הורדה מלאה, מסתיר שדות פנימיים."""
    out = []
    for a in load_apps():
        out.append({
            "id": a["id"], "name": a.get("name",""), "category": a.get("category",""),
            "image": a.get("image",""), "icon": a.get("icon",""), "banner": a.get("banner",""),
            "description": a.get("description",""), "version": a.get("version",""),
            "size": a.get("size",""), "updated": a.get("updated",""),
            "screenshots": a.get("screenshots",[]),
            "download": f"/apps/dl/{a['id']}",
        })
    return JSONResponse(out)

@api.get("/apps/cats")
async def public_cats():
    """רשימת הקטגוריות (לגלגלת באתר)."""
    return JSONResponse(load_cats())

@api.get("/apps/dl/{app_id}")
async def download(app_id: str):
    """מזרים את ה-APK מטלגרם ישירות למשתמש (הורדה) לפי file_id."""
    app = next((a for a in load_apps() if a.get("id") == app_id), None)
    if not app:
        raise HTTPException(404, "אפליקציה לא נמצאה")
    file_id = app.get("file_id")
    if not file_id:
        raise HTTPException(404, "הקובץ לא זמין")
    fname = app.get("file_name") or (app.get("name","app") + ".apk")

    async def gen():
        async for chunk in bot.stream_media(file_id):
            yield chunk
    headers = {
        "Content-Disposition": f'attachment; filename="{fname}"',
        "Content-Length": str(app.get("file_size") or 0),
    }
    return StreamingResponse(gen(), media_type="application/vnd.android.package-archive", headers=headers)

# ── פאנל ניהול ───────────────────────────────────────────────────────────────
def check_pass(p):
    if p != PANEL_PASS: raise HTTPException(401, "סיסמה שגויה")

class SaveReq(BaseModel):
    password: str
    apps: list

@api.get("/apps/admin", response_class=HTMLResponse)
async def admin_page():
    f = HERE / "admin.html"
    return HTMLResponse(f.read_text(encoding="utf-8")) if f.exists() else HTMLResponse("<h1>admin.html חסר</h1>")

@api.post("/apps/list")
async def admin_list(req: dict):
    check_pass(req.get("password",""))
    return load_apps()

@api.post("/apps/save")
async def admin_save(req: SaveReq):
    check_pass(req.password)
    if not isinstance(req.apps, list): raise HTTPException(400, "apps חייב להיות מערך")
    save_apps(req.apps)
    return {"ok": True, "count": len(req.apps)}

class CatsReq(BaseModel):
    password: str
    categories: list

@api.post("/apps/cats/save")
async def admin_cats_save(req: CatsReq):
    check_pass(req.password)
    if not isinstance(req.categories, list): raise HTTPException(400, "categories חייב להיות מערך")
    out = save_cats(req.categories)
    return {"ok": True, "categories": out}

@api.get("/ping")
async def ping(): return {"ok": True, "apps": len(load_apps())}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(api, host="127.0.0.1", port=int(os.environ.get("APPS_PORT", "8001")))
