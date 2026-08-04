#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# AppMod · שירות חנות האפליקציות (נפרד לגמרי משרת הסרטים)
#   • מגיש את האתר (index.html) ואת רשימת האפליקציות (/apps/content)
#   • בוט טלגרם שמאזין לערוץ: כל APK שמעלים → נכנס לרשימה אוטומטית
#   • הורדה: /apps/dl/<id> → מזרים את ה-APK מהערוץ למשתמש
#   • פאנל ניהול קטן לעריכת פרטים (אייקון/תיאור/קטגוריה/צילומי מסך)
# רץ על פורט 8001 (שרת הסרטים על 8000) — לא נוגעים אחד בשני.
# ─────────────────────────────────────────────────────────────────────────────
import os, re, json, time, asyncio, logging, uuid
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, Response
from pydantic import BaseModel
from pyrogram import Client, filters

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

def load_apps() -> list:
    if APPS_FILE.exists():
        try: return json.loads(APPS_FILE.read_text(encoding="utf-8"))
        except Exception: return []
    return []

def save_apps(arr: list):
    APPS_FILE.write_text(json.dumps(arr, ensure_ascii=False, indent=2), encoding="utf-8")

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

# ── בוט טלגרם ────────────────────────────────────────────────────────────────
bot = Client("appmod_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN,
             in_memory=True, workdir=str(DATA_DIR))

def _is_apk(msg) -> bool:
    d = getattr(msg, "document", None)
    if not d: return False
    fn = (getattr(d, "file_name", "") or "").lower()
    mt = (getattr(d, "mime_type", "") or "").lower()
    return fn.endswith(".apk") or "android.package" in mt

# יומן אבחון: רושם כל הודעה שהבוט מקבל (עוזר לזהות אם הוא בכלל מקבל מהערוץ)
@bot.on_message(group=1)
async def _debug_any(client, msg):
    try:
        ch = getattr(msg.chat, "id", None)
        d = getattr(msg, "document", None)
        log.info("📩 הודעה התקבלה · chat=%s · doc=%s · שם=%s",
                 ch, bool(d), getattr(d, "file_name", None) if d else None)
    except Exception:
        pass

@bot.on_message(filters.document)
async def on_channel_post(client, msg):
    """כל APK שמועלה (מכל צ'אט שהבוט חבר בו) נכנס אוטומטית לרשימה."""
    try:
        if not _is_apk(msg):
            return
        d = msg.document
        chat_id = getattr(msg.chat, "id", CHANNEL_ID)
        apps = load_apps()
        # דדופ לפי (צ'אט + הודעה)
        if any(a.get("channel_msg_id") == msg.id and a.get("channel_id") == chat_id for a in apps):
            return
        cap = (msg.caption or "").strip()
        name = (cap.splitlines()[0].strip() if cap else "") or clean_app_name(getattr(d, "file_name", ""))
        entry = {
            "id": uuid.uuid4().hex[:12],
            "name": name, "category": "כללי",
            "icon": "", "banner": "",
            "description": cap if cap else "",
            "version": "", "size": human_size(getattr(d, "file_size", 0)),
            "updated": datetime.utcnow().strftime("%d/%m/%Y"),
            "screenshots": [],
            "channel_id": chat_id, "channel_msg_id": msg.id,
            "file_name": getattr(d, "file_name", "app.apk"),
            "file_size": getattr(d, "file_size", 0),
        }
        apps.insert(0, entry)
        save_apps(apps)
        log.info("APK חדש נוסף: %s (msg %s)", name, msg.id)
        try:
            await msg.reply_text(f"✅ «{name}» נוסף לחנות.\nערוך פרטים (אייקון/תיאור) בפאנל:\n{PUBLIC_BASE}/apps/admin",
                                 quote=True)
        except Exception:
            pass
    except Exception as e:
        log.warning("שגיאה בהוספת APK: %s", e)

# ── FastAPI ──────────────────────────────────────────────────────────────────
api = FastAPI(title="AppMod")

@api.on_event("startup")
async def _start():
    await bot.start()
    # קריטי: טוענים את הערוץ למטמון ה-peers. בלי זה, כשמגיע פוסט חדש
    # Pyrogram לא מצליח לזהות את הערוץ (in_memory) ומפיל את העדכון בשקט —
    # ואז ה-handler לא נורה. get_chat מאכלס את ה-access_hash של הערוץ.
    try:
        ch = await bot.get_chat(CHANNEL_ID)
        log.info("✅ ערוץ נטען למטמון: %s (%s)", getattr(ch, "title", ""), CHANNEL_ID)
    except Exception as e:
        log.warning("⚠️ טעינת ערוץ נכשלה: %s", e)
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
            "icon": a.get("icon",""), "banner": a.get("banner",""),
            "description": a.get("description",""), "version": a.get("version",""),
            "size": a.get("size",""), "updated": a.get("updated",""),
            "screenshots": a.get("screenshots",[]),
            "download": f"/apps/dl/{a['id']}",
        })
    return JSONResponse(out)

@api.get("/apps/dl/{app_id}")
async def download(app_id: str):
    """מזרים את ה-APK מהערוץ ישירות למשתמש (הורדה)."""
    app = next((a for a in load_apps() if a.get("id") == app_id), None)
    if not app:
        raise HTTPException(404, "אפליקציה לא נמצאה")
    try:
        msg = await bot.get_messages(app["channel_id"], app["channel_msg_id"])
    except Exception as e:
        raise HTTPException(502, f"שליפת הקובץ נכשלה: {e}")
    if not getattr(msg, "document", None):
        raise HTTPException(404, "הקובץ לא זמין")
    fname = app.get("file_name") or (app.get("name","app") + ".apk")

    async def gen():
        async for chunk in bot.stream_media(msg):
            yield chunk
    headers = {
        "Content-Disposition": f'attachment; filename="{fname}"',
        "Content-Length": str(app.get("file_size") or msg.document.file_size or 0),
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

@api.get("/ping")
async def ping(): return {"ok": True, "apps": len(load_apps())}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(api, host="127.0.0.1", port=int(os.environ.get("APPS_PORT", "8001")))
