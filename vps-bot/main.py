"""
Telegram Stream-on-Demand Server
ארכיטקטורה מפושטת: בוט אחד, מחובר ב-MTProto (לא Bot API HTTP), שמזרים
ישירות מהצ'אט המקורי שבו הוא קיבל את הקובץ. אין userbot, אין
SESSION_STRING, אין copy/forward ל-Saved Messages.
"""

import os
import random
import re
import sys
import gzip
import json
import time
import hmac
import asyncio
import logging
import itertools
import httpx
from urllib.parse import quote, urljoin, urlparse
from typing import AsyncGenerator, Optional
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait, FileReferenceExpired
from pyrogram.session import Session, Auth
from pyrogram.file_id import FileId
from pyrogram.raw import functions, types as raw_types
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from huggingface_hub import HfApi, hf_hub_download
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

# ── משתני סביבה ──────────────────────────────────────────────────────────────
REQUIRED_ENV_VARS = ["API_ID", "API_HASH", "BOT_TOKEN"]
_missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
if _missing:
    sys.exit(f"❌ חסרים משתני סביבה: {', '.join(_missing)}")

API_ID    = int(os.environ["API_ID"])
API_HASH  = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
PORT      = int(os.environ.get("PORT", 8000))

BASE_URL = (
    os.environ.get("BASE_URL")
    or os.environ.get("RENDER_EXTERNAL_URL")
    or f"http://localhost:{PORT}"
).rstrip("/")

stats = {
    "started_at": datetime.utcnow().isoformat(),
    "files_processed": 0,
    "links_generated": 0,
    "last_file": None,
    "last_ping": None,
}

# ── Storage פשוט (JSON files) + session persistent ────────────────────────────
# בשרת ה-VPS יש דיסק קבוע, אז שומרים את הנתונים ב-/opt/zovex-bot/data (ולא
# ב-/tmp שנמחק באתחול). זה קריטי לקובץ ה-session — הוא מחזיק את ה-peer cache
# (access_hash של כל צ'אט), ובלעדיו הקישורים הישנים מפסיקים לעבוד אחרי אתחול.
DATA_DIR = Path(os.environ.get("DATA_DIR", "/opt/zovex-bot/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
PROGRESS_FILE = DATA_DIR / "progress.json"
HISTORY_FILE  = DATA_DIR / "history.json"
SESSION_NAME  = "stream_bot"
SESSION_FILE  = DATA_DIR / f"{SESSION_NAME}.session"

# in_memory=False ⇒ Pyrogram שומר קובץ session.db מקומי (כולל peer cache —
# ה-access_hash של כל צ'אט/עובד שהבוט אי-פעם דיבר איתו). בלי זה, כל הפעלה
# מחדש של ה-Space מוחקת את הקאש הזה וכל הקישורים הישנים (chat_id/message_id)
# מפסיקים לעבוד כי MTProto לא מצליח לפתור (resolve) את הצ'אט בלי access_hash.
bot_client = Client(
    name=SESSION_NAME,
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=False,
    workdir=str(DATA_DIR),
)

api = FastAPI(title="Telegram Stream Server")

# ── CORS ─────────────────────────────────────────────────────────────────
# היה allow_origins=["*"] עם allow_credentials=True — צירוף ש-FastAPI מממש
# ע"י החזרת ה-Origin שנשלח + Access-Control-Allow-Credentials:true, כלומר
# *כל* אתר זר יכול לקרוא תשובות מה-API בשם המבקר. עכשיו רשימה סגורה: האתר
# עצמו (same-origin ממילא לא צריך CORS) ו-GitHub Pages הישן. האפליקציה
# היא native — היא לא שולחת Origin ולכן לא מושפעת מכאן כלל.
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "CORS_ALLOWED_ORIGINS",
    "https://zovex.duckdns.org,https://davidggjg.github.io"
).split(",") if o.strip()]
api.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# נקודות המדיה (relay/stream) מוגשות מכל מקום, גם מ-origin "null" — זה ה-origin
# של ה-WebView באפליקציה, שבו נגן ה-HLS (Shaka) מושך את ה-m3u8 והמקטעים דרך
# fetch. נעילת ה-CORS ל-API היא נכונה (נתוני משתמשים), אבל היא שברה שידורים
# חיים באפליקציה. מדיה היא תוכן ציבורי בלי הרשאות — לכן ACAO:* לה בטוח. מוסיפים
# ישירות לתגובות (לא ב-middleware) כדי לא לגעת ב-streaming הרגיש.
CORS_MEDIA = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Range",
    "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges",
}

# ── גיבוי קבוע ל-HF Dataset ────────────────────────────────────────────────
# /tmp נמחק בכל הפעלה-מחדש/התעוררות של ה-Space (זה מה שגרם ל"היסטוריה
# ו'המשך צפייה' לא עובדים" — הכל נמחק ברקע בלי שגיאה גלויה). כדי לשמור
# את הנתונים לצמיתות בלי לשלם על Persistent Storage, מגבים אותם ל-Dataset
# פרטי משלך ב-Hugging Face, ומשחזרים ממנו כל עלייה מחדש של השרת.
# דורש שני Secrets ב-Settings של ה-Space:
#   HF_TOKEN      — טוקן עם הרשאת כתיבה (huggingface.co/settings/tokens)
#   DATA_REPO_ID  — למשל "davidhzhdhd/zovex-data" (Dataset ריק שיצרת מראש)
HF_TOKEN     = os.environ.get("HF_TOKEN")
DATA_REPO_ID = os.environ.get("DATA_REPO_ID", "").strip()

# מפתח לקישור "ריענון שרת" (/restart?key=...) - כדי שאפשר יהיה לתת למישהו
# קישור פשוט ללחוץ עליו כשהשרת נתקע, בלי לתת לו גישה לחשבון Hugging Face
# עצמו. חובה להגדיר RESTART_KEY ב-Settings → Secrets של ה-Space (כל מחרוזת
# שרירותית שתבחרי) - בלי זה ה-endpoint חסום לגמרי.
RESTART_KEY = os.environ.get("RESTART_KEY", "").strip()

# ── הגנת hotlink (אופציונלי) על קישורי הסטרימינג ─────────────────────────────
# אם מגדירים HOTLINK_REFERERS (רשימה מופרדת בפסיקים, למשל
# "davidggjg.github.io,zovex1.netlify.app,213.139.78.39") — רק בקשות עם Referer
# שמכיל אחד מהם (או בלי Referer בכלל, בשביל האפליקציה/וידאו ישיר) יורשו. זה
# חוסם אתרים אחרים שמנסים להטמיע את הזרם אצלם. כברירת מחדל ריק ⇒ לא חוסם כלום.
HOTLINK_REFERERS = [r.strip() for r in os.environ.get("HOTLINK_REFERERS", "").split(",") if r.strip()]

def check_hotlink(request: Request):
    if not HOTLINK_REFERERS:
        return  # הגנה כבויה — התנהגות רגילה
    ref = request.headers.get("referer") or request.headers.get("origin") or ""
    if not ref:
        return  # אפליקציה / תג <video> ישיר — אין referer, מרשים
    if any(allowed in ref for allowed in HOTLINK_REFERERS):
        return
    raise HTTPException(status_code=403, detail="hotlink not allowed")

def is_local_request(request: Request) -> bool:
    """True רק אם הבקשה באמת מקומית (curl מהשרת ל-127.0.0.1). בקשה שהגיעה דרך
    nginx נושאת X-Forwarded-For — ואז היא *לא* מקומית, גם אם ה-socket הוא
    127.0.0.1. קריטי כדי ש-/content/relink ו-/admin/migrate לא ייחשפו לציבור
    ברגע שיש reverse proxy."""
    if request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip"):
        return False
    return bool(request.client) and request.client.host in ("127.0.0.1", "::1")
_hf_api = HfApi(token=HF_TOKEN) if (HF_TOKEN and DATA_REPO_ID) else None

if not _hf_api:
    log.warning(
        "⚠️ HF_TOKEN/DATA_REPO_ID לא מוגדרים — היסטוריה/המשך-צפייה יימחקו "
        "בכל הפעלה-מחדש של ה-Space. הוסיפי אותם ב-Settings → Secrets."
    )

def restore_from_dataset():
    """מושך את הגיבוי האחרון של progress.json/history.json/session מה-Dataset,
    אם קיים — כדי ש-/tmp יתחיל עם הנתונים האמיתיים ולא ריק.
    קריטי לקרוא לזה *לפני* bot_client.start(), אחרת Pyrogram כבר יצר
    session ריק במקום ושחזור השם הזה יידרס/יתעלם."""
    if not _hf_api:
        return
    for fname, path in (
        ("progress.json", PROGRESS_FILE),
        ("history.json", HISTORY_FILE),
        (f"{SESSION_NAME}.session", SESSION_FILE),
    ):
        try:
            downloaded = hf_hub_download(
                repo_id=DATA_REPO_ID, repo_type="dataset", filename=fname, token=HF_TOKEN,
            )
            path.write_bytes(Path(downloaded).read_bytes())
            log.info("✅ שוחזר %s מה-Dataset", fname)
        except Exception as e:
            log.info("אין עדיין %s ב-Dataset (%s) — מתחילים ריק", fname, e)

def backup_to_dataset(fname: str, path: Path):
    """מעלה את הקובץ הנוכחי ל-Dataset ברקע (לא חוסם את הבקשה עצמה)."""
    if not _hf_api:
        return
    try:
        _hf_api.upload_file(
            path_or_fileobj=str(path),
            path_in_repo=fname,
            repo_id=DATA_REPO_ID,
            repo_type="dataset",
            commit_message=f"עדכון {fname}",
        )
    except Exception as e:
        log.warning("⚠️ גיבוי %s ל-Dataset נכשל: %s", fname, e)

def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}

def save_json(path: Path, data: dict, backup_name: Optional[str] = None):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if backup_name:
        # ברקע — כדי לא להאט את התשובה למשתמש
        asyncio.create_task(asyncio.to_thread(backup_to_dataset, backup_name, path))

# ── Pydantic models ───────────────────────────────────────────────────────────
class ProgressUpdate(BaseModel):
    media_id: str
    position: float   # שניות
    duration: float   # אורך כולל

class HistoryItem(BaseModel):
    media_id: str
    title: str
    thumbnail_url: Optional[str] = ""

# ── User/Progress/History Endpoints ──────────────────────────────────────────

@api.post("/api/progress")
async def update_progress(
    data: ProgressUpdate,
    x_user_id: str = Header(..., description="Google User ID")
):
    db = load_json(PROGRESS_FILE)
    if x_user_id not in db:
        db[x_user_id] = {}
    db[x_user_id][data.media_id] = {
        "position": data.position,
        "duration": data.duration,
        "updated": time.time()
    }
    save_json(PROGRESS_FILE, db, "progress.json")
    return {"ok": True}

@api.get("/api/progress/{media_id}")
async def get_progress(
    media_id: str,
    x_user_id: str = Header(..., description="Google User ID")
):
    db = load_json(PROGRESS_FILE)
    return db.get(x_user_id, {}).get(media_id, {"position": 0, "duration": 0})

@api.get("/api/history")
async def get_history(
    x_user_id: str = Header(..., description="Google User ID")
):
    db = load_json(HISTORY_FILE)
    return db.get(x_user_id, [])

@api.post("/api/history")
async def add_history(
    item: HistoryItem,
    x_user_id: str = Header(..., description="Google User ID")
):
    db = load_json(HISTORY_FILE)
    if x_user_id not in db:
        db[x_user_id] = []
    # הסר כפילות של אותו media_id
    db[x_user_id] = [h for h in db[x_user_id] if h.get("media_id") != item.media_id]
    db[x_user_id].insert(0, {
        "media_id": item.media_id,
        "title": item.title,
        "thumbnail_url": item.thumbnail_url or "",
        "watched_at": time.time()
    })
    db[x_user_id] = db[x_user_id][:50]  # מקסימום 50 פריטים בהיסטוריה
    save_json(HISTORY_FILE, db, "history.json")
    return {"ok": True}

# ── Stream helpers ────────────────────────────────────────────────────────────

def parse_range(range_header: str, file_size: int) -> tuple[int, int]:
    try:
        _, ranges = range_header.split("=")
        start_str, end_str = ranges.split("-")
        start = int(start_str) if start_str else 0
        end   = int(end_str)   if end_str   else file_size - 1
        return start, min(end, file_size - 1)
    except Exception:
        raise HTTPException(status_code=416, detail="Invalid Range header")

FETCH_MESSAGE_TIMEOUT_SECS = 20

async def fetch_message(chat_id: int, message_id: int) -> Message:
    for attempt in range(5):
        try:
            msg = await asyncio.wait_for(
                bot_client.get_messages(chat_id, message_id), timeout=FETCH_MESSAGE_TIMEOUT_SECS
            )
            return msg
        except FloodWait as e:
            log.warning("FloodWait %ss", e.value)
            await asyncio.sleep(e.value)
        except asyncio.TimeoutError:
            # תיקון: בלי ה-timeout הזה, חיבור MTProto תקוע היה גורם לקריאה הזו
            # להישאר תלויה לנצח בלי שגיאה - כל בקשת /stream הייתה נתקעת בלי
            # תשובה. עכשיו זה נכשל אחרי 20 שניות וממשיך לנסיון הבא.
            log.warning(
                "fetch_message timeout (נסיון %d/5) עבור chat=%s msg=%s",
                attempt + 1, chat_id, message_id,
            )
    raise HTTPException(status_code=504, detail="Telegram timeout")

PYROGRAM_CHUNK_SIZE = 1024 * 1024
# תיקון: בלי timeout כאן, חיבור MTProto תקוע גורם ל-__anext__() להישאר תלוי
# לנצח - זה בדיוק מה שגרם לבקשות /stream להיתקע בלי תשובה בכלל, גם על
# קבצים שכבר עבדו בעבר. עכשיו תקיעה כזו נכשלת אחרי CHUNK_FETCH_TIMEOUT_SECS
# ונכנסת לאותה לוגיקת retry שכבר קיימת למטה (except Exception).
CHUNK_FETCH_TIMEOUT_SECS = 20

# ── Rolling-buffer stream sessions ──────────────────────────────────────────
# הבעיה שהייתה: לכל בקשת Range קטנה (וידאו-פלייר שולח המון כאלה תוך כדי
# צפייה רגילה) נפתח מחדש session שלם מול טלגרם (auth key + handshake) —
# זה מה שגרם ל"טעינה" כל כמה שניות. הפתרון: session אחד לכל סרטון, ששומר
# buffer בזיכרון סביב הנקודה שנצפית — קצת אחורה (לחזרה מהירה כמה שניות
# אחורה בלי בקשה חדשה לטלגרם) וקצת קדימה (prefetch, כדי שהחלק הבא כבר
# מוכן כשהפלייר יבקש אותו). session חדש נפתח רק בקפיצה גדולה (seek רחוק).
#
# הערה: הגרסה הזו נועלת lock אחד פשוט על כל בקשה (כן — זה אומר שבקשות
# Range מקבילות לאותו סרטון מתורות זו מאחורי זו). ניסינו גרסה "חכמה" יותר
# עם Condition שמאפשרת שיתוף אמיתי בין בקשות מקבילות, אבל היא התגלתה
# כבעלת סיכון תקיעה אמיתי (deadlock) כשכמה משימות prefetch התנגשו —
# אז חזרנו לגרסה הזו, פשוטה ומאומתת (נבדקה בסימולציה), כדי לוודא
# נכונות קודם כל. אם עדיין יש האטה בבקשות מקבילות אחרי זה — נדע שהצוואר
# בקבוק האמיתי הוא רוחב-פס/CPU של ה-Space עצמו, לא הלוגיקה.
BEHIND_KEEP_BYTES  = 2 * 1024 * 1024   # ~אחורה שנשמר בזיכרון לחזרה מהירה
AHEAD_TARGET_BYTES = 6 * 1024 * 1024   # ~קדימה שמנסים לשמור מוכן מראש
SESSION_IDLE_SECS  = 90                # session לא בשימוש X שניות → נסגר

# תיקון: כמה פעמים לנסות מחדש כשטלגרם מחזיר שגיאה זמנית/מתנתק באמצע
# הזרמה, לפני שמוותרים בפועל. בלי זה, כל הפרעה חד-פעמית (timeout, ניתוק
# רגעי) הייתה גורמת לעצירה שקטה של ה-buffer באמצע התגובה - ומכיוון
# שה-Content-Length כבר נשלח ללקוח מראש (כדי לתמוך ב-Range/Seek), התוצאה
# הייתה בדיוק השגיאה RuntimeError: Response content shorter than
# Content-Length שראינו בלוגים.
MAX_TRANSIENT_RETRIES = 5

STREAM_SESSIONS: dict[str, "StreamSession"] = {}
STREAM_SESSIONS_LOCK = asyncio.Lock()

class StreamSession:
    def __init__(self, chat_id: int, message_id: int, msg: Message, media):
        self.chat_id = chat_id
        self.message_id = message_id
        self.msg = msg
        self.media = media
        self.file_size = media.file_size
        self.lock = asyncio.Lock()   # מגן על buf/buf_start/gen בלבד
        self.buf = bytearray()
        self.buf_start = 0        # האופסט של buf[0] בקובץ המקורי
        self.gen = None           # ה-generator הפעיל של bot_client.stream_media
        self.prefetch_task: Optional[asyncio.Task] = None
        self.last_used = time.time()

    async def _restart_generator(self, start_offset: int):
        offset_chunks = start_offset // PYROGRAM_CHUNK_SIZE
        self.gen = bot_client.stream_media(self.msg, offset=offset_chunks, limit=0)
        pos = offset_chunks * PYROGRAM_CHUNK_SIZE
        self.buf = bytearray()
        self.buf_start = pos

    def _trim(self, keep_from: int):
        if keep_from > self.buf_start:
            drop = keep_from - self.buf_start
            if drop > 0:
                self.buf = self.buf[drop:]
                self.buf_start += drop

    async def ensure(self, pos: int, want_end: int):
        """מוודא שה-buffer מכסה לפחות עד want_end (או עד סוף הקובץ), החל
        מ-pos. פותח generator חדש רק אם pos מחוץ ל-buffer הנוכחי.

        תיקון: בגרסה הקודמת רק StopAsyncIteration (סוף קובץ אמיתי) היה
        נתפס - כל שגיאה אחרת מטלגרם (ניתוק רגעי, timeout, FloodWait
        באמצע הזרמה) הייתה עוצרת את הלולאה בלי שגיאה גלויה, ומחזירה
        buffer קצר יותר ממה שהובטח ב-Content-Length. עכשיו שגיאות זמניות
        גורמות ל-retry (פתיחת generator מחדש מאותה נקודה), עד
        MAX_TRANSIENT_RETRIES פעמים, לפני שבאמת מוותרים."""
        want_end = min(want_end, self.file_size)
        async with self.lock:
            buf_end = self.buf_start + len(self.buf)
            in_range = self.gen is not None and self.buf_start <= pos <= buf_end
            if not in_range:
                await self._restart_generator(pos)
                buf_end = self.buf_start + len(self.buf)

            retries_left = MAX_TRANSIENT_RETRIES
            while buf_end < want_end:
                if self.gen is None:
                    # הגענו לסוף הקובץ בפועל - אין מה לעשות יותר
                    if buf_end >= self.file_size:
                        break
                    # "סוף" מוקדם מדי / generator נסגר בלי שהגענו לסוף
                    # האמיתי - ננסה שוב מהמקום הנוכחי
                    if retries_left <= 0:
                        log.error(
                            "ensure(): נגמרו הנסיונות (%d) ב-offset %d, "
                            "מוותר - התגובה תהיה קצרה מהמובטח",
                            MAX_TRANSIENT_RETRIES, buf_end,
                        )
                        break
                    retries_left -= 1
                    await self._restart_generator(buf_end)
                    buf_end = self.buf_start + len(self.buf)
                    continue
                try:
                    chunk = await asyncio.wait_for(self.gen.__anext__(), timeout=CHUNK_FETCH_TIMEOUT_SECS)
                except StopAsyncIteration:
                    self.gen = None
                    continue
                except FloodWait as e:
                    log.warning("FloodWait %ss באמצע הזרמה, ממתין ומנסה שוב", e.value)
                    await asyncio.sleep(e.value)
                    continue
                except Exception as e:
                    log.warning(
                        "שגיאה זמנית בהזרמה מטלגרם ב-offset %d: %s (%d נסיונות נותרו)",
                        buf_end, e, retries_left,
                    )
                    if retries_left <= 0:
                        log.error(
                            "ensure(): נגמרו הנסיונות (%d) ב-offset %d, "
                            "מוותר - התגובה תהיה קצרה מהמובטח",
                            MAX_TRANSIENT_RETRIES, buf_end,
                        )
                        self.gen = None
                        break
                    retries_left -= 1
                    await self._restart_generator(buf_end)
                    buf_end = self.buf_start + len(self.buf)
                    continue
                self.buf.extend(chunk)
                buf_end = self.buf_start + len(self.buf)
                retries_left = MAX_TRANSIENT_RETRIES  # התקדמות תקינה מאפסת את המונה

            self._trim(max(0, pos - BEHIND_KEEP_BYTES))
            self.last_used = time.time()

    async def prefetch_ahead(self):
        """ממשיך למשוך עוד קדימה ברקע (best-effort) אחרי שסופקה בקשה, כדי
        שהחלק הבא כבר יהיה מוכן בזיכרון כשהפלייר יבקש אותו. שומר על *משימת
        prefetch אחת בלבד* בכל רגע נתון per session — כדי לא ליצור שרשרת
        משימות מתנגשות (זה מה שגרם לתקיעה בגרסה הקודמת)."""
        if self.prefetch_task is not None and not self.prefetch_task.done():
            return
        async def _run():
            try:
                async with self.lock:
                    pos = self.buf_start + len(self.buf)
                    target = min(self.file_size, pos + AHEAD_TARGET_BYTES)
                if target > pos:
                    await asyncio.wait_for(self.ensure(pos, target), timeout=20)
            except Exception:
                pass
        self.prefetch_task = asyncio.create_task(_run())

async def get_session(chat_id: int, message_id: int, client_key: str) -> "StreamSession":
    # תיקון: המפתח כלל בעבר רק chat_id:message_id - כלומר כל מי שצפה באותו
    # קובץ בו-זמנית שיתף איתם session אחד עם buffer/מיקום אחד משותף. אם שני
    # צופים נמצאים בנקודות רחוקות בקובץ (אחד בדקה 2, שני בדקה 40), כל בקשה
    # "בעטה" את הבאפר של השני החוצה וגרמה לפתיחת session חדש מול טלגרם כל
    # שנייה-שתיים - בדיוק מה שראינו בלוגים (חיבורים נפתחים ונסגרים שוב ושוב
    # בלי שום שגיאה אמיתית). עכשיו כל לקוח (מזוהה לפי IP) מקבל session נפרד
    # לאותו קובץ, כך שהם לא דורכים זה על זה - בלי לפגוע באופטימיזציה
    # המקורית (אותו צופה, בקשות Range עוקבות, עדיין חולק את אותו buffer).
    key = f"{chat_id}:{message_id}:{client_key}"
    async with STREAM_SESSIONS_LOCK:
        sess = STREAM_SESSIONS.get(key)
        if sess:
            return sess
    msg = await fetch_message(chat_id, message_id)
    if not msg or not msg.media:
        raise HTTPException(status_code=404, detail="No media found")
    media = msg.audio or msg.video or msg.document or msg.video_note
    if not media:
        raise HTTPException(status_code=415, detail="Unsupported media type")
    sess = StreamSession(chat_id, message_id, msg, media)
    async with STREAM_SESSIONS_LOCK:
        STREAM_SESSIONS[key] = sess
    return sess

async def reap_idle_sessions():
    """מנקה sessions שלא נעשה בהם שימוש זמן מה, כדי לא לצבור זיכרון/חיבורים."""
    while True:
        await asyncio.sleep(30)
        now = time.time()
        async with STREAM_SESSIONS_LOCK:
            dead = [k for k, s in STREAM_SESSIONS.items() if now - s.last_used > SESSION_IDLE_SECS]
            for k in dead:
                del STREAM_SESSIONS[k]

async def stream_session_range(sess: "StreamSession", start: int, end: int) -> AsyncGenerator[bytes, None]:
    """מזרים את הטווח המבוקש. אם יש download workers — משתמש במשיכה מקבילה
    (מהירה פי כמה); אחרת נופל חזרה למנגנון ה-buffer החד-חיבורי המקורי."""
    pos = start
    if download_workers:
        # ── מסלול מקבילי: pool_stream_window מטפל בעצמו בחלונות + pipeline ──
        try:
            async for data in pool_stream_window(sess.msg, start, end + 1):
                pos += len(data)
                sess.last_used = time.time()
                yield data
        except Exception as e:
            log.error("משיכה מקבילה נכשלה ב-offset %d: %s", pos, e)
    else:
        # ── מסלול fallback: buffer + generator יחיד (המנגנון המקורי) ──
        while pos <= end:
            chunk_target = min(end + 1, pos + PYROGRAM_CHUNK_SIZE)
            await sess.ensure(pos, chunk_target)
            async with sess.lock:
                rel_start = pos - sess.buf_start
                available_end = min(len(sess.buf), end + 1 - sess.buf_start)
                if rel_start < 0 or rel_start >= available_end:
                    break
                data = bytes(sess.buf[rel_start:available_end])
                sess.last_used = time.time()
            yield data
            pos += len(data)
        asyncio.create_task(sess.prefetch_ahead())
    # אם לא הגענו עד הסוף שהובטח - ה-Content-Length כבר נשלח ללקוח מראש, אז
    # חייבים לשלוח את מספר הבייטים המובטח, אחרת uvicorn קורס עם
    # RuntimeError: Response content shorter than Content-Length.
    if pos <= end:
        log.error("stream_session_range: חסרים %d בייטים — מנתק כדי שהנגן יבקש שוב",
                  end - pos + 1)
        raise StreamGap(f"missing {end - pos + 1} bytes")

class StreamGap(Exception):
    """משיכה מטלגרם נכשלה ואי אפשר להשלים את הטווח שהובטח.

    זורקים במקום למלא אפסים. מילוי אפסים סיפק ללקוח בדיוק את מספר הבייטים
    שב-Content-Length, ולכן הנגן כלל לא נכנס למצב טעינה — הוא קיבל "הכל",
    ניסה לפענח זבל, והתמונה קפאה על הפריים האחרון בלי ספינר ובלי התאוששות.
    ניתוק באמצע התשובה, לעומת זאת, נראה ללקוח כשגיאת רשת על הטווח הזה — וכל
    נגן יודע לבקש אותו מחדש.
    """


# ── Stream bot pool: ריבוי בוטים לתוכן בערוץ (רוטציה + זיהוי חניקה) ──────────
# תובנה מהבדיקות: בוט *טרי* מושך מהערוץ ב-~4.2 MB/s, אבל בוט שנחנק (FLOOD_WAIT
# מרוב שימוש) יורד ל-0.65. הפתרון: pool של בוטים (כולם אדמינים בערוץ), השרת
# מסובב ביניהם, וכשבוט נחנק (FloodWait/timeout) מסמן אותו ב-cooldown ומדלג לבא.
STREAM_CHANNEL_ID = int(os.environ.get("STREAM_CHANNEL_ID", "0"))
STREAM_BOTS_FILE = DATA_DIR.parent / "stream_bots.txt"   # /opt/zovex-bot/stream_bots.txt
_stream_bots: list = []
_stream_rr = 0
_stream_rr_lock = asyncio.Lock()

# ── ריבוי ערוצי אחסון + גלישה אוטומטית ────────────────────────────────────────
# ערוץ טלגרם מוגבל במספר הודעות; כשהוא מתמלא עוברים לערוץ הבא. מזהי-הודעה
# סדרתיים בערוץ, אז copied.id ≈ מספר הקבצים בערוץ — כשהוא חוצה את הסף עוברים
# הלאה. הכתובת של כל קובץ כוללת את מזהה-הערוץ שלו, אז הגשה עובדת מכל הערוצים
# (בתנאי שהבוטים חברים בכולם). רשימת הערוצים ב-stream_channels.txt (ID בכל שורה),
# והערוץ הראשי (STREAM_CHANNEL_ID) תמיד ראשון.
STREAM_CHANNELS_FILE = DATA_DIR.parent / "stream_channels.txt"
CHANNEL_MAX_MESSAGES = int(os.environ.get("CHANNEL_MAX_MESSAGES", "950000"))
def _load_stream_channels() -> list:
    chans = []
    if STREAM_CHANNEL_ID:
        chans.append(STREAM_CHANNEL_ID)
    if STREAM_CHANNELS_FILE.exists():
        try:
            for line in STREAM_CHANNELS_FILE.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    cid = int(line)
                except ValueError:
                    continue
                if cid not in chans:
                    chans.append(cid)
        except Exception as e:
            log.warning("קריאת stream_channels.txt נכשלה: %s", e)
    return chans or ([STREAM_CHANNEL_ID] if STREAM_CHANNEL_ID else [])
STREAM_CHANNELS = _load_stream_channels()
_active_idx = 0

def current_upload_channel() -> int:
    """הערוץ שאליו מעלים עכשיו קבצים חדשים (האחרון שעדיין לא מלא)."""
    if not STREAM_CHANNELS:
        return STREAM_CHANNEL_ID
    return STREAM_CHANNELS[min(_active_idx, len(STREAM_CHANNELS) - 1)]

def note_uploaded_msg_id(chat_id: int, msg_id: int):
    """אחרי העלאה: אם הערוץ הפעיל חצה את הסף — עוברים לערוץ הבא."""
    global _active_idx
    if not STREAM_CHANNELS or chat_id != STREAM_CHANNELS[min(_active_idx, len(STREAM_CHANNELS) - 1)]:
        return
    if msg_id >= CHANNEL_MAX_MESSAGES:
        if _active_idx < len(STREAM_CHANNELS) - 1:
            _active_idx += 1
            log.warning("📦 ערוץ %s מלא (msg %s ≥ %s) — עובר לערוץ הבא: %s",
                        chat_id, msg_id, CHANNEL_MAX_MESSAGES, STREAM_CHANNELS[_active_idx])
        else:
            log.critical("🛑 כל הערוצים מלאים! הוסף ערוץ חדש (stream_channels.txt / פאנל).")

async def resolve_active_channel():
    """בהפעלה: מוצא את הערוץ הפעיל (הראשון שעדיין לא מלא) לפי מזהה-ההודעה האחרון.
    דורש userbot ב-pool (רק חשבון יכול לקרוא היסטוריה). אם אין — נשאר על 0
    והמעבר יקרה אוטומטית כשהעתקה תחזיר id מעל הסף."""
    global _active_idx
    ub = _pick_pool_userbot() if "_pick_pool_userbot" in globals() else None
    if not ub or len(STREAM_CHANNELS) < 2:
        return
    for i, ch in enumerate(STREAM_CHANNELS):
        try:
            last_id = 0
            async for m in ub["client"].get_chat_history(ch, limit=1):
                last_id = m.id
            if last_id < CHANNEL_MAX_MESSAGES:
                _active_idx = i
                log.info("📦 ערוץ פעיל: %s (הודעה אחרונה %s)", ch, last_id)
                return
        except Exception as e:
            log.warning("בדיקת ערוץ %s נכשלה: %s", ch, e)
    _active_idx = len(STREAM_CHANNELS) - 1

async def _pool_noop(client, message):
    pass  # handler ריק — רק כדי שהלקוח יקבל עדכוני ערוץ וישמור את ה-peer


# שגיאת הזיהוי האחרונה לכל חבר pool — כדי שהפאנל יוכל להציג *למה* הוא לא
# מחובר, במקום רק "לא מחובר". בלי זה אין דרך לדעת אם הבוט לא חבר בערוץ,
# ה-session פג, או שזו סתם תקלת רשת רגעית.
_peer_errors: dict = {}


async def _resolve_peer(client, name) -> bool:
    """מוודא שהלקוח מזהה את ערוץ התוכן.

    בלי זיהוי, *כל* משיכת מדיה של אותו חבר pool נכשלת ב-'Peer id invalid',
    הוא נכנס ל-cooldown, יוצא, נכשל שוב — לולאה אינסופית. קודם הכישלון כאן
    נבלע ב-except: pass בלי שום לוג, ולכן התקלה הייתה בלתי נראית לגמרי
    והתגלתה רק מתלונות של צופים ("הלייב עובד והסרטים נתקעים").
    """
    if not STREAM_CHANNEL_ID:
        return True
    try:
        await asyncio.wait_for(client.get_chat(STREAM_CHANNEL_ID), timeout=20)
        return True
    except Exception as e:
        first = e

    # מעבר על רשימת הצ'אטים ממלא את המטמון המקומי ב-access_hash של כל ערוץ
    # שהחשבון חבר בו — וזה מה שחסר כדי לפתור מזהה מספרי. עובד רק לחשבון
    # משתמש; לבוטים טלגרם לא מאפשר get_dialogs, ולכן הם תלויים בכך שתגיע
    # הודעה חדשה מהערוץ. הרשאות אדמין לא רלוונטיות לשום כיוון כאן.
    try:
        n = 0
        async for _ in client.get_dialogs(limit=500):
            n += 1
        if n:
            await asyncio.wait_for(client.get_chat(STREAM_CHANNEL_ID), timeout=20)
            log.info("✅ %s זיהה את הערוץ אחרי סריקת %d צ'אטים", name, n)
            return True
    except Exception:
        pass

    log.warning("⚠️ %s לא מזהה את ערוץ התוכן (%s) — ינוסה שוב ברקע", name, first)
    _peer_errors[name] = f"{type(first).__name__}: {first}"
    return False


async def peer_retry_loop():
    """ריפוי עצמי לחברי pool שלא זיהו את הערוץ בעלייה.

    קריטי במיוחד ל-userbot: הוא מוגדר no_updates=True + in_memory=True, כלומר
    לא מקבל עדכונים (אז הודעה חדשה בערוץ *לא* תלמד אותו) ולא שומר כלום לדיסק.
    get_chat היא הדרך היחידה שלו לזהות את הערוץ — ואם היא נכשלה פעם אחת
    בעלייה (למשל בגלל תקלת רשת רגעית), הוא נשאר מושבת עד ה-restart הבא.
    """
    while True:
        await asyncio.sleep(60)
        for b in [x for x in _stream_bots if not x.get("peer_ok")]:
            if await _resolve_peer(b["client"], b["name"]):
                b["peer_ok"] = True
                b["cooldown_until"] = 0.0
                log.info("✅ %s זיהה את ערוץ התוכן וחזר לפעולה", b["name"])

def _is_bot_token(s: str) -> bool:
    return bool(re.match(r'^\d{5,}:[A-Za-z0-9_-]{20,}$', (s or "").strip()))

# כמה זמן לתת להתחברות של חבר pool. 40 היה קצר מדי: כשעולים 16 בזה אחר זה
# טלגרם מאט את ההתחברויות, וחמישה בוטים תקינים לגמרי נפלו על timeout.
POOL_START_TIMEOUT = float(os.environ.get("POOL_START_TIMEOUT", "75"))
POOL_START_ATTEMPTS = int(os.environ.get("POOL_START_ATTEMPTS", "3"))

async def _start_one_pool_bot(i, tok: str, timeout: float = None):
    """מעלה חבר pool בודד (טוקן בוט או session string של חשבון) ומוסיף לרשימה."""
    c = None
    try:
        if _is_bot_token(tok):
            c = Client(f"pool_bot_{i}", api_id=API_ID, api_hash=API_HASH, bot_token=tok,
                       in_memory=False, no_updates=False, workdir=str(DATA_DIR))
            kind = "bot"
        else:
            # session string = חשבון משתמש (userbot) — בד"כ מהיר יותר מבוט
            c = Client(f"pool_user_{i}", api_id=API_ID, api_hash=API_HASH,
                       session_string=tok, in_memory=True, no_updates=True)
            kind = "user"
        c.add_handler(MessageHandler(_pool_noop, filters.channel))
        await asyncio.wait_for(c.start(), timeout=timeout or POOL_START_TIMEOUT)
        name = f"{kind}_{i}"
        # שומרים את המזהה פעם אחת בעלייה: בלעדיו הפאנל מציג bot_5/user_8 בלבד
        # ואי אפשר לדעת איזה בוט זה בפועל (למשל את מי להוסיף לערוץ).
        who = ""
        try:
            me = await asyncio.wait_for(c.get_me(), timeout=15)
            who = ("@" + me.username) if me.username else (me.first_name or "")
        except Exception:
            pass
        entry = {"client": c, "name": name, "cooldown_until": 0.0,
                 "token": tok, "kind": kind, "peer_ok": True, "who": who}
        if STREAM_CHANNEL_ID:
            entry["peer_ok"] = await _resolve_peer(c, name)
        _stream_bots.append(entry)
        log.info("✅ pool %s %s עלה (%d פעילים)", kind, i, len(_stream_bots))
        return None
    except Exception as e:
        # שם הטיפוס חייב להיכנס ללוג: str(asyncio.TimeoutError()) הוא מחרוזת
        # ריקה, ולכן השורה הזו הודפסה כ"לא עלה: " בלי שום סיבה — והכשל הנפוץ
        # ביותר היה בדיוק זה.
        log.warning("⚠️ pool member %s לא עלה: %s: %s", i, type(e).__name__, e)
        if c is not None:
            # לשחרר את קובץ ה-session, אחרת הניסיון החוזר ייתקל בו נעול
            try:
                await c.stop()
            except Exception:
                pass
        # מחזירים את הסיבה האמיתית: הפאנל הציג עד עכשיו ניחוש קבוע על הרשאות
        # אדמין, גם כשהכשל היה session פגום, טוקן שגוי או תקלת רשת.
        return f"{type(e).__name__}: {e}"

async def start_stream_pool():
    if not STREAM_BOTS_FILE.exists():
        log.info("אין stream_bots.txt — pool בוטים לא פעיל")
        return
    tokens = [t.strip() for t in STREAM_BOTS_FILE.read_text().splitlines() if t.strip()]
    # מעלים אחד-אחד עם הפוגה בין בוט לבוט. הצפת טלגרם בעשרות התחברויות בו-זמנית
    # (מה שקרה עם BATCH=8) גורמת לחסימת IP → כל הבוטים "לא עלה" ולולאת קריסה.
    # לאט ויציב עדיף. POOL_START_DELAY ניתן לכוונון דרך משתנה סביבה.
    delay = float(os.environ.get("POOL_START_DELAY", "4"))
    failed = []
    for i, tok in enumerate(tokens):
        if await _start_one_pool_bot(i, tok) is not None:
            failed.append((i, tok))
        await asyncio.sleep(delay)
    log.info("🚀 stream pool: %d/%d בוטים פעילים", len(_stream_bots), len(tokens))
    asyncio.create_task(warm_stream_pool())
    if failed:
        # ניסיון חוזר ברקע. כשל בעלייה הוא כמעט תמיד timeout זמני ולא בוט
        # פגום, אבל עד עכשיו הוא היה סופי: הבוט נעלם מהבריכה עד ה-restart הבא.
        # ברקע כדי לא לעכב את עליית השרת.
        asyncio.create_task(_retry_failed_pool_members(failed, len(tokens), delay))

async def _retry_failed_pool_members(failed, total, delay):
    for attempt in range(2, POOL_START_ATTEMPTS + 1):
        await asyncio.sleep(30)
        log.info("🔁 סבב %d: מנסה שוב %d חברי pool שלא עלו", attempt, len(failed))
        still = []
        for i, tok in failed:
            # תקציב זמן גדל בכל סבב — מי שלא הספיק ב-75 שניות בזמן שכל
            # הבריכה עלתה יחד, בדרך כלל מספיק כשהעומס הזה כבר מאחורינו.
            if await _start_one_pool_bot(i, tok, timeout=POOL_START_TIMEOUT * attempt) is not None:
                still.append((i, tok))
            await asyncio.sleep(delay)
        log.info("🚀 stream pool: %d/%d בוטים פעילים", len(_stream_bots), total)
        if not still:
            return
        failed = still
    log.warning("⚠️ %d חברי pool לא עלו גם אחרי %d סבבים — ראה את השגיאות למעלה",
                len(failed), POOL_START_ATTEMPTS)

async def warm_stream_pool():
    """מחמם מראש את חיבור-המדיה (DC) של כל בוט ב-pool. בלי זה, הפליי הראשון של
    כל בוט אחרי restart פותח חיבור טרי לטלגרם (Connecting→Session→Ping) שלוקח
    כמה שניות — וזה מה שגרם ל'פליי לוקח מיליון שנה'. חתיכה אחת מכל בוט מספיקה
    כדי לפתוח ולשמור את החיבור."""
    if not _stream_bots or not STREAM_CHANNEL_ID:
        return
    msg_id = None
    for e in load_content():
        u = e.get("video_url") or e.get("video_id") or ""
        m = re.search(r"/stream/-?\d+/(\d+)", u)
        if m:
            msg_id = int(m.group(1))
            break
    if msg_id is None:
        return
    for b in _stream_bots:
        try:
            msg = await asyncio.wait_for(_get_bot_msg(b, STREAM_CHANNEL_ID, msg_id), timeout=25)
            if not msg:
                continue
            async for _chunk in b["client"].stream_media(msg, offset=0):
                break  # חתיכה אחת — רק כדי לפתוח את חיבור ה-DC
            # גם בריכת החיבורים המקבילים של הבוט. בלי זה היא נבנית אצל הצופה
            # הראשון שנוחת עליו, וכיוון שהבחירה היא round-robin על כל הבריכה,
            # כמעט כל בקשה בדקות הראשונות שילמה בניית 4 חיבורים מאפס.
            if STREAM_MEDIA_CONNS > 0:
                media = msg.video or msg.audio or msg.document or msg.video_note
                if media:
                    dc_id, _loc = _file_location(media)
                    await get_media_session_pool_gen(
                        b["client"], b["name"], dc_id, STREAM_MEDIA_CONNS)
            log.info("🔥 חוממה מדיה: %s", b["name"])
        except Exception as e:
            log.warning("⚠️ חימום %s נכשל: %s", b.get("name"), e)
        await asyncio.sleep(0.4)
    log.info("🔥 pool מחומם — פליי ראשון יהיה מהיר")

# כל כמה זמן לנסות להחיות בוטים מודחים. הבדיקה רצה *מחוץ* למסלול הצפייה,
# כך שהצופה לעולם לא משלם על ניסיון החייאה.
REVIVE_EVERY = int(os.environ.get("STREAM_REVIVE_EVERY", "120"))
REVIVE_AFTER_CHOKES = int(os.environ.get("STREAM_REVIVE_AFTER_CHOKES", "2"))


async def revive_stream_pool():
    """מחזיר לחיים בוטים שה-session שלהם תקוע.

    למה זה נדרש: cooldown (גם מתגבר) רק *מסתיר* בוט מת — הוא לא מתקן אותו.
    בלי החייאה הבריכה שוחקת מ-21 בוטים ל-12 עד ה-restart הבא, וכל בוט שנשחק
    מגדיל את העומס על הנותרים. חיבור MTProto תקוע לא מחזיר שגיאה שאפשר לתפוס
    (הוא פשוט לא חוזר), ולכן אין ל-Pyrogram סיכוי לזהות אותו לבד — הדרך היחידה
    היא stop()+start() שבונים session טרי.
    """
    if not STREAM_CHANNEL_ID:
        return
    while True:
        await asyncio.sleep(REVIVE_EVERY)
        for b in list(_stream_bots):
            if b.get("chokes", 0) < REVIVE_AFTER_CHOKES:
                continue
            name = b["name"]
            try:
                # קודם בדיקה זולה: אולי הוא כבר התאושש מעצמו וחבל להפיל session.
                await asyncio.wait_for(b["client"].get_me(), timeout=10)
                b["chokes"] = 0
                b["fails"] = 0
                b["cooldown_until"] = 0.0
                log.info("✅ %s התאושש — חזר לרוטציה", name)
                continue
            except Exception:
                pass
            log.warning("♻️ %s תקוע — מרים session מחדש", name)
            try:
                # stop() על לקוח תקוע עלול להיתקע בעצמו — עוטפים בתקציב.
                await asyncio.wait_for(b["client"].stop(), timeout=20)
            except Exception:
                pass
            try:
                await asyncio.wait_for(b["client"].start(), timeout=POOL_START_TIMEOUT)
                # ה-session החדש לא מכיר את הערוץ, וה-file_reference הישן שייך
                # ל-session שמת — שניהם חייבים להיבנות מחדש, אחרת הבוט "עלה"
                # אבל ייכשל בכל משיכה.
                b["peer_ok"] = await _resolve_peer(b["client"], name)
                for k in [k for k in _bot_msg_cache if k[0] == name]:
                    _bot_msg_cache.pop(k, None)
                b["chokes"] = 0
                b["fails"] = 0
                b["speed"] = None
                b["cooldown_until"] = 0.0
                log.info("✅ %s הורם מחדש וחזר לרוטציה", name)
            except Exception as e:
                # נשאר מודח; הסבב הבא ינסה שוב.
                log.warning("⚠️ הרמת %s נכשלה: %s: %s", name, type(e).__name__, e)
            await asyncio.sleep(2)   # לא מציפים את טלגרם בהתחברויות


async def stop_stream_pool():
    for b in _stream_bots:
        try:
            await b["client"].stop()
        except Exception:
            pass
    _stream_bots.clear()

# ── בחירת בוט לפי ביצועים ────────────────────────────────────────────────────
# נמדד על השרת, אותו קובץ ואותו רגע: bot_7 נתן 6.79 MB/s, bot_3 נתן 0.36,
# וארבעה מתוך שמונה נכשלו לגמרי. כלומר המגבלה היא לכל חשבון בנפרד ולא על
# השרת. בחירה round-robin עיוורת ניתבה צופים לבוטים התקועים באותה תדירות
# כמו לתקינים — ומכאן שאותה בקשה בדיוק לקחה פעם 3 שניות ופעם 59.
#
# לכל בוט נשמר ממוצע נע של הקצב שהוא סיפק. הבחירה היא "הטוב מבין שניים
# אקראיים": מטה את התנועה לבוטים המהירים בלי לרכז את כולם על אחד, ובלי
# לדרוש דירוג גלובלי שמתיישן.
BOT_SPEED_ALPHA = 0.3          # משקל המדידה האחרונה בממוצע הנע

def note_bot_speed(bot, mb_per_sec: float):
    prev = bot.get("speed")
    bot["speed"] = (mb_per_sec if prev is None
                    else prev * (1 - BOT_SPEED_ALPHA) + mb_per_sec * BOT_SPEED_ALPHA)

def _bot_score(bot) -> float:
    # בוט שטרם נמדד מקבל ציון ביניים כדי שייבחר וייבדק, אבל לא יגבר על מוכח
    return bot["speed"] if bot.get("speed") is not None else 1.0

async def pick_stream_bot():
    now = time.time()
    async with _stream_rr_lock:
        global _stream_rr
        healthy = [b for b in _stream_bots if b["cooldown_until"] < now]
        pool = healthy or _stream_bots
        if not pool:
            return None
        if len(pool) == 1:
            return pool[0]
        a = pool[_stream_rr % len(pool)]
        _stream_rr += 1
        b = pool[random.randrange(len(pool))]
        return a if _bot_score(a) >= _bot_score(b) else b


# באיזו הסתברות להעדיף בוט שההודעה כבר במטמון שלו. לא 100%: בהעדפה מוחלטת
# הצופה הראשון היה "נועל" את הסרט על בוט אחד למשך 15 דקות, וכל שאר הצופים
# באותו סרט היו נדחסים לאותו חשבון. הדליפה של ~15% מחממת בוטים נוספים ברקע,
# כך שקבוצת החמים גדלה מעצמה ככל שהסרט נצפה יותר.
WARM_BIAS = float(os.environ.get("STREAM_WARM_BIAS", "0.85"))

# מי מושך *כרגע* חלון עבור איזה פריט. קריטי: בריכת חיבורי המדיה מוחזרת כאותם
# אובייקטים בדיוק לכל מי שמבקש את אותו (בוט, DC) — כלומר שתי משיכות בו-זמנית
# של אותו בוט חולקות את אותם 4 חיבורים. נמדד על השרת הזה: 4 חיבורים נותנים
# 10.5 MB/s ו-8 בקשות מקבילות עליהם נותנות 0.96 — פי 10 פחות. מרגע שנוספה
# קריאה-מראש רצו שני חלונות במקביל, והעדפת הבוט החם שלחה את שניהם לאותו בוט:
# החלונות חרגו מהתקציב, שני timeouts רצופים הפילו את הבריכה, ושני החלונות
# נפלו יחד — תקיעה של 30–60 שניות כל כמה דקות בצפייה רצופה.
_inflight_bots: dict = {}      # (chat_id, message_id) -> set(שמות בוטים)


async def pick_stream_bot_for(chat_id, message_id, exclude=None):
    """כמו pick_stream_bot, אבל מעדיף בוט שכבר משך את ההודעה הזו.

    נמדד על השרת אחרי הדחת הבוטים התקועים: חלק מהבקשות חזרו ב-0.56 שניות
    (5.4 MB/s) ואחרות ב-8.7 — וההפרש היה בדיוק 8 שניות, כלומר מלוא תקציב
    שליפת ההודעה שנשרף על בוט תקוע לפני המעבר לבא. בוט "חם" מחזיר את ההודעה
    מהמטמון בלי קריאת רשת כלל, ולכן הוא לא יכול להיתקע שם — מה שמסלק את
    מקור השונות האחרון במקום לקצר את העונש עליו.
    """
    now = time.time()
    busy = set(_inflight_bots.get((chat_id, message_id)) or ())
    if exclude:
        busy |= set(exclude)          # בוטים שכבר נכשלו על החלון הזה
    free = [b for b in _stream_bots
            if b["cooldown_until"] < now and b["name"] not in busy]
    # אם *כל* הבריכה עסוקה בפריט הזה, עדיף להצטרף לבוט תפוס מאשר לא להגיש
    # כלום — אבל אז שווה גם לוותר על העדפת החם, כדי לא לרכז שוב על אותו אחד.
    if not free:
        return await pick_stream_bot()
    if random.random() < WARM_BIAS:
        warm = [b for b in free
                if (_bot_msg_cache.get((b["name"], chat_id, message_id))
                    or (None, 0.0))[1] > now]
        if warm:
            if len(warm) == 1:
                return warm[0]
            a = warm[random.randrange(len(warm))]
            b = warm[random.randrange(len(warm))]
            return a if _bot_score(a) >= _bot_score(b) else b
    if len(free) == 1:
        return free[0]
    a = free[random.randrange(len(free))]
    b = free[random.randrange(len(free))]
    return a if _bot_score(a) >= _bot_score(b) else b

# כמה כשלים *רצופים* לפני שמדיחים בוט. כשל בודד הוא בדרך כלל רעש רגעי של
# טלגרם, לא בוט חולה. הדחה על כשל ראשון יצרה מפל: בוט נחנק ← נשארים פחות ←
# העומס על הנותרים גדל ← גם הם נחנקים. וזה גם מה שגרם למספר הבוטים ה"בריאים"
# לקפוץ בין 4 ל-16 כל כמה דקות.
CHOKE_AFTER_FAILS = int(os.environ.get("STREAM_CHOKE_AFTER_FAILS", "3"))

# עונש מתגבר. cooldown קבוע של 30 שניות נראה הגיוני, אבל מול בוט שה-session
# שלו *תקוע* הוא אסון: הבוט חוזר לתור כל חצי דקה, כל בחירה בו שורפת את מלוא
# תקציב שליפת ההודעה, והוא לעולם לא יוצא מהמשחק. נמדד בשרת: 9 מתוך 21 בוטים
# תקועים ← ~43% מהחלונות שילמו 20 שניות ← 6 MB/s צנחו מתחת ל-0.03.
# עם הכפלה פי 4 בכל חניקה רצופה (30ש' → 2ד' → 8ד' → 30ד') בוט מת יוצא
# מהרוטציה תוך כדקתיים, בעוד בוט שנתקל ברעש רגעי חוזר מיד אחרי 30 שניות.
CHOKE_BACKOFF_MAX = int(os.environ.get("STREAM_CHOKE_BACKOFF_MAX", "1800"))

# מתי בפעם האחרונה בוט כלשהו מהבריכה סיפק בייטים בהצלחה. ה-Watchdog משתמש
# בזה כעדות חיה לכך שטלגרם מגיב — ראה telegram_watchdog.
_last_pool_success = 0.0


def _mark_ok(bot):
    """משיכה הצליחה — מאפסים את מונה הכשלים הרצופים ואת דרגת העונש."""
    global _last_pool_success
    _last_pool_success = time.time()
    if bot.get("fails"):
        bot["fails"] = 0
    if bot.get("chokes"):
        bot["chokes"] = 0

def _mark_choked(bot, seconds, err=None, hard=False, escalate=True):
    # "Peer id invalid" הוא לא חניקה אלא בוט ששכח את הערוץ: cooldown לבדו לא
    # יעזור לו, הוא פשוט ייכשל שוב בעוד 30 שניות. מסמנים אותו כדי ש-
    # peer_retry_loop ינסה לזהות עבורו את הערוץ מחדש.
    peer_bad = err is not None and "peer id invalid" in str(err).lower()
    if peer_bad:
        bot["peer_ok"] = False
    # FloodWait ו-peer פגום הם ודאיים — מדיחים מיד. כל השאר צריך לחזור על עצמו.
    if not (hard or peer_bad):
        bot["fails"] = bot.get("fails", 0) + 1
        if bot["fails"] < CHOKE_AFTER_FAILS:
            log.info("בוט %s נכשל (%d/%d) — עדיין בשירות",
                     bot["name"], bot["fails"], CHOKE_AFTER_FAILS)
            return
        bot["fails"] = 0
    # FloodWait מגיע עם זמן ההמתנה שטלגרם עצמו ביקש — אותו לא מכפילים.
    n = bot.get("chokes", 0)
    if escalate:
        bot["chokes"] = n + 1
        seconds = min(CHOKE_BACKOFF_MAX, int(seconds * (4 ** min(n, 5))))
    bot["cooldown_until"] = time.time() + seconds
    log.warning("🥵 בוט %s נחנק (חניקה %d) — cooldown %ds",
                bot["name"], n + 1 if escalate else n, seconds)

# cache של אובייקט ההודעה — *per-bot*. קריטי: ה-file_reference בתוך ההודעה
# תקף רק בהקשר של הסשן שששלף אותו. שיתוף בין בוטים גרם ל-FILE_REFERENCE_EXPIRED
# (הקישור נשבר אחרי כמה שניות). לכן כל בוט מחזיק cache משלו, וכשה-reference
# פג — שולפים מחדש עם אותו בוט. ל-metadata (גודל/mime) אין בעיית reference.
_bot_msg_cache: dict = {}   # (bot_name, chat_id, message_id) -> (msg, expires_at)
_BOT_MSG_TTL = 900          # 15 דק' — נשאר "חם" לאורך צפייה שלמה (בקשות Range
                            # פרוסות על כל אורך הסרט). אם ה-file_reference פג
                            # באמצע — נתפס כ-FileReferenceExpired ונשלף מחדש.
_BOT_MSG_CACHE_MAX = 4000   # תקרת רשומות — מעליה מנקים פגי-תוקף ואז ישנים

async def _get_bot_msg(bot, chat_id, message_id, force=False):
    """שולף את ההודעה עבור בוט מסוים (cache פר-בוט). force=True מכריח שליפה טרייה."""
    key = (bot["name"], chat_id, message_id)
    now = time.time()
    if not force:
        c = _bot_msg_cache.get(key)
        if c and c[1] > now:
            return c[0]
    msg = await asyncio.wait_for(
        bot["client"].get_messages(chat_id, message_id), timeout=20)
    if msg and (msg.video or msg.audio or msg.document or msg.video_note):
        # ניקוי רשומות שפג תוקפן: בלי זה המטמון גדל בלי הגבלה (12 בוטים ×
        # אלפי פריטים = עשרות אלפי אובייקטי Message בזיכרון) — דליפת זיכרון
        # שמצטברת עד שהשירות נחנק. מנקים רק כשהמטמון גדול, כדי לא לבזבז זמן.
        if len(_bot_msg_cache) > _BOT_MSG_CACHE_MAX:
            for k, v in [(k, v) for k, v in _bot_msg_cache.items() if v[1] <= now]:
                _bot_msg_cache.pop(k, None)
            # אם עדיין גדול מדי (הכול עדיין בתוקף) — זורקים את הישנים ביותר
            if len(_bot_msg_cache) > _BOT_MSG_CACHE_MAX:
                for k, _ in sorted(_bot_msg_cache.items(), key=lambda kv: kv[1][1]
                                   )[:len(_bot_msg_cache) - _BOT_MSG_CACHE_MAX]:
                    _bot_msg_cache.pop(k, None)
        _bot_msg_cache[key] = (msg, now + _BOT_MSG_TTL)
        return msg
    return None


# תקציב שליפת ההודעה בכל מסלול הזרמה. ל-_get_bot_msg יש timeout של 20 שניות,
# והוא נספר *מחוץ* לתקציב החלון — כלומר בוט עם session תקוע גבה 20 שניות מלאות
# לפני שהחלון בכלל התחיל, ובמסלולי הגיבוי (לולאה על 4 בוטים) עד 80 שניות
# לבקשה אחת. ההודעה שמורה במטמון 15 דקות ובוט בריא מחזיר אותה ממנו מיידית
# (וגם קר — פחות משתי שניות), ולכן 8 שניות הן מרווח נדיב לכל בוט חי.
MSG_FETCH_BUDGET = float(os.environ.get("STREAM_MSG_FETCH_BUDGET", "8"))


async def _get_bot_msg_fast(bot, chat_id, message_id):
    """כמו _get_bot_msg אבל עם תקציב קצר, וחניקה מיידית של בוט שנתקע.

    session תקוע לא מחזיר שגיאה — הוא פשוט לא חוזר, ולכן הוא מתחזה ל"בוט איטי"
    ולא מודח לעולם. נמדד בשרת: 9 מתוך 21 בוטים במצב הזה ניתבו אליהם ~43%
    מהחלונות, וכל אחד שילם את מלוא ה-timeout. מחזיר None אם הבוט נתקע.
    """
    try:
        return await asyncio.wait_for(
            _get_bot_msg(bot, chat_id, message_id), timeout=MSG_FETCH_BUDGET)
    except asyncio.TimeoutError:
        # חניקה מיידית (hard) בלי לחכות לשלושה כשלים: עם העונש המתגבר, טעות
        # על בוט בריא עולה 30 שניות בלבד, בעוד ההמתנה לשלוש מכות עלתה יותר
        # מדקה של צפייה תקועה בכל סיבוב.
        log.warning("שליפת ההודעה מ-%s נתקעה (%.0fs) — חונק", bot["name"], MSG_FETCH_BUDGET)
        note_bot_speed(bot, 0.0)
        _mark_choked(bot, 30, hard=True)
        return None


def _purge_msg_cache(chat_id, message_id):
    """מנקה את הודעת ה-cache של *כל* הבוטים עבור פריט מסוים. כשה-file_reference
    פג הוא פג גלובלית (לכל הבוטים), ולכן ניקוי של בוט אחד לא הספיק — הבקשה
    הבאה נחתה על בוט אחר עם reference ישן וכשלה שוב, והסרט נשאר "תקוע" עד
    כניסה מחדש. ניקוי כולל מאלץ שליפת הודעה טרייה בבקשה הבאה → התאוששות מיידית."""
    for k in [k for k in _bot_msg_cache if k[1] == chat_id and k[2] == message_id]:
        _bot_msg_cache.pop(k, None)

async def channel_get_media(chat_id, message_id):
    """מחזיר את ה-media של ההודעה מהערוץ (metadata בלבד — אין בעיית reference)."""
    for _ in range(min(max(1, len(_stream_bots)), 5)):
        bot = await pick_stream_bot_for(chat_id, message_id)
        if bot is None:
            return None
        try:
            msg = await _get_bot_msg_fast(bot, chat_id, message_id)
            if msg:
                return msg.video or msg.audio or msg.document or msg.video_note
        except FloodWait as e:
            _mark_choked(bot, e.value, hard=True, escalate=False)
        except Exception as e:
            log.warning("channel_get_media שגיאה (%s): %s", chat_id, e)
            _mark_choked(bot, 30, e)
    return None

async def channel_stream_range(chat_id, message_id, start, end):
    """מזרים [start, end] מהערוץ דרך בוט מה-pool. כל בוט שולף את ההודעה של עצמו
    (file_reference תקף רק בהקשר שלו). בוט שנחנק בהתחלה → עוברים לבא."""
    CHUNK = PYROGRAM_CHUNK_SIZE
    pos = start
    for _ in range(min(max(1, len(_stream_bots)), 4)):
        bot = await pick_stream_bot_for(chat_id, message_id)
        if bot is None:
            break
        try:
            msg = await _get_bot_msg_fast(bot, chat_id, message_id)
            if msg is None:
                continue          # כבר נחנק בתוך _get_bot_msg_fast אם נתקע
            off_chunks = pos // CHUNK
            produced = off_chunks * CHUNK
            async for chunk in bot["client"].stream_media(msg, offset=off_chunks):
                c_start = produced
                c_end = produced + len(chunk)
                lo = max(pos, c_start) - c_start
                hi = min(end + 1, c_end) - c_start
                if lo < hi:
                    yield chunk[lo:hi]
                    pos = c_start + hi
                produced = c_end
                if produced > end:
                    break
            break  # הצלחה
        except FileReferenceExpired:
            # ה-reference פג (גלובלית) — מנקים לכל הבוטים ונותנים סיבוב נוסף
            _purge_msg_cache(chat_id, message_id)
            if pos > start:
                break   # כבר שלחנו בייטים — אי אפשר להתחיל מחדש
        except FloodWait as e:
            _mark_choked(bot, e.value, hard=True, escalate=False)
            if pos > start:
                break   # כבר שלחנו בייטים — אי אפשר להחליף בוט באמצע
        except Exception as e:
            log.warning("channel stream שגיאה: %s", e)
            _mark_choked(bot, 30, e)
            if pos > start:
                break
    if pos <= end:
        log.error("channel stream: חסרים %d בייטים — מנתק כדי שהנגן יבקש שוב",
                  end - pos + 1)
        raise StreamGap(f"missing {end - pos + 1} bytes")

# ── הזרמה מקבילה (FastTelethon-style, בטוח) ─────────────────────────────────
# במקום צינור אחד ל-~4MB/s, מפצלים כל "חלון" של הסרט לכמה תת-טווחים שנמשכים
# בו-זמנית דרך כמה בוטים שונים מה-pool (כל בוט = חיבור נפרד לטלגרם), ומגישים
# לפי הסדר. זה עוקף את תקרת החיבור הבודד בלי לשמור שום דבר לדיסק (pass-through).
# נשלט ע"י STREAM_PARALLEL_PARTS. ברירת המחדל היא 4 (הזרמה מקבילה פעילה):
# חיבור טלגרם בודד חסום ל-~1.25MB/s, ולכן צינור יחיד לא עומד בקצב של סרט
# 1080p בזמן-אמת → הבאפר מתרוקן והנגן "נתקע" באמצע. המסלול המקביל (media-bands,
# ~70x) כבר קיים, מוקשח, ועם נפילה בטוחה חזרה למסלול הבוט הבודד — לכן הוא מופעל
# כברירת מחדל. אפשר לכבות עם STREAM_PARALLEL_PARTS=1.
STREAM_PARALLEL_PARTS  = int(os.environ.get("STREAM_PARALLEL_PARTS", "4"))
STREAM_PARALLEL_WINDOW = int(os.environ.get("STREAM_PARALLEL_WINDOW", str(16 * 1024 * 1024)))
# קריאה-מראש של חלון אחד קדימה. עלות: עוד חלון אחד בזיכרון לכל צופה פעיל
# (ברירת מחדל 16MB). אפשר לכבות ב-STREAM_READAHEAD=0 אם הזיכרון נהיה צר.
STREAM_READAHEAD = os.environ.get("STREAM_READAHEAD", "1") not in ("0", "false", "no")
# כמה זמן מחכים לבוט בודד לפני שמוותרים עליו ועוברים לבא. ניתן לכוונון מ-.env.
SUBRANGE_TIMEOUT = int(os.environ.get("STREAM_SUBRANGE_TIMEOUT", "25"))

# תקרה קשיחה על מספר לחיצות-היד הבו-זמניות במסלול הוותיק. הניסיונות החוזרים
# במסלול המהיר מונעים מהסופה להתחיל, אבל אינם מצילים אותה אחרי שהתחילה: כשכל
# החלונות נכשלים, קצב לחיצות היד יורד רק פי 1.2. התקרה הזו חוסמת את זה מלמעלה
# בלי קשר לשיעור הכשלים. מכוילת גבוה בכוונה — בעומס תקין היא לא נוגעת בכלום,
# והיא נכנסת לפעולה רק במצב החריג.
LEGACY_FETCH_LIMIT = int(os.environ.get("STREAM_LEGACY_LIMIT", "8"))
_legacy_sem = None


def _legacy_semaphore():
    """נוצר בעצלתיים: ברמת המודול עוד אין event loop רץ."""
    global _legacy_sem
    if _legacy_sem is None:
        _legacy_sem = asyncio.Semaphore(LEGACY_FETCH_LIMIT)
    return _legacy_sem

async def _fetch_subrange(chat_id, message_id, lo, hi) -> bytes:
    """מושך את הבייטים [lo, hi] (כולל) דרך בוט מה-pool, עם ניסיונות על כמה בוטים.
    מחזיר תמיד בדיוק (hi-lo+1) בייטים (משלים באפסים אם נכשל — לשמירת Content-Length)."""
    CHUNK = PYROGRAM_CHUNK_SIZE
    need = hi - lo + 1
    for _ in range(min(max(1, len(_stream_bots)), 4)):
        bot = await pick_stream_bot_for(chat_id, message_id)
        if bot is None:
            break
        try:
            msg = await _get_bot_msg_fast(bot, chat_id, message_id)
            if msg is None:
                continue          # כבר נחנק בתוך _get_bot_msg_fast אם נתקע

            async def _pull():
                out = bytearray()
                off_chunks = lo // CHUNK
                produced = off_chunks * CHUNK
                async for chunk in bot["client"].stream_media(msg, offset=off_chunks):
                    c_start = produced
                    c_end = produced + len(chunk)
                    a = max(lo, c_start) - c_start
                    b = min(hi + 1, c_end) - c_start
                    if a < b:
                        out += chunk[a:b]
                    produced = c_end
                    if produced > hi:
                        break
                return out

            # timeout חובה: ל-stream_media אין מגבלת זמן משלו, וכשהחיבור של הבוט
            # ל-DC של טלגרם נופל בלולאה (Retrying upload.GetFile) הלולאה תלויה
            # לנצח. החלון המקבילי מוגש רק כשכל תת-הטווחים הסתיימו, ולכן בוט תקוע
            # אחד הקפיא את כל הבקשה גם כששאר ה-pool בריא — הצופה קיבל 0 בייטים.
            # התור מחוץ ל-wait_for בכוונה: זמן ההמתנה בתור לא ייחשב כאיטיות של
            # הבוט ולא יחניק אותו בטעות. כל מחזיק חסום ל-SUBRANGE_TIMEOUT, ולכן
            # התור מתקדם תמיד ואי אפשר להיתקע בו לנצח.
            async with _legacy_semaphore():
                out = await asyncio.wait_for(_pull(), timeout=SUBRANGE_TIMEOUT)
            if len(out) >= need:
                _mark_ok(bot)
                return bytes(out[:need])
            raise StreamGap(f"subrange short: {len(out)}/{need}")
        except asyncio.TimeoutError:
            log.warning("subrange: %s לא סיפק בייטים תוך %ds — עובר לבוט אחר",
                        bot["name"], SUBRANGE_TIMEOUT)
            _mark_choked(bot, 30)
        except FileReferenceExpired:
            _purge_msg_cache(chat_id, message_id)
        except FloodWait as e:
            _mark_choked(bot, e.value, hard=True, escalate=False)
        except Exception as e:
            log.warning("subrange שגיאה: %s", e)
            _mark_choked(bot, 30, e)
    raise StreamGap(f"no bot could serve {need} bytes")

# כמה חיבורי media מקבילים לכל משיכה. נמדד על השרת הזה מול DC4:
#   חיבור אחד → 0.14 MB/s ·  4 חיבורים → 10.5 MB/s ·  8 חיבורים → 0.96 MB/s
# כלומר 4 הוא האופטימום; מעבר לזה טלגרם מגביל ויצירת החיבורים עולה יותר ממה
# שהיא מחזירה. 0 מכבה לגמרי וחוזר למסלול הבוטים.
STREAM_MEDIA_CONNS = int(os.environ.get("STREAM_MEDIA_CONNS", "4"))
# תקציב הזמן למשיכה במסלול המהיר. הערך הראשון (8 + 2 לכל MB) היה ניחוש בלי
# מדידה, והתברר כקצר מדי: נמדדו 20 חיתוכים מול נפילה אחת בלבד למסלול האיטי,
# כלומר כמעט כל בקשה נחתכה באמצע משיכה תקינה, זרקה את מה שכבר נמשך והתחילה
# מאפס במסלול איטי יותר. הנפילה אחורה יקרה, ולכן עדיף להמתין למשיכה שמתקדמת.
# 14 + 4/MB נקבע *לפני* שתוקן באג הרצועות, כשכל משיכה הורידה פי 3-4 מהנדרש
# ולכן באמת הייתה איטית. אחרי התיקון המשיכות מהירות בהרבה והתקציב הפך רחב
# מדי: הוא הפך לזמן ההמתנה הקבוע שכל חיבור מת גובה לפני הנפילה אחורה.
MEDIA_BANDS_TIMEOUT = int(os.environ.get("STREAM_MEDIA_BANDS_TIMEOUT", "6"))
MEDIA_BANDS_PER_MB = float(os.environ.get("STREAM_MEDIA_BANDS_PER_MB", "3"))
MEDIA_BANDS_MAX = int(os.environ.get("STREAM_MEDIA_BANDS_MAX", "35"))


# עד כמה זמן FloodWait כדאי "לרכוב" בתוך רצועה לפני ויתור. FloodWait קצר
# (טלגרם מבקש להאט לרגע) עדיף לספוג מאשר להפיל את כל החלון; FloodWait ארוך
# עדיף לזרוק — החלון ייפול אחורה למסלול אחר ולא יחזיק את הצופה תקוע.
MEDIA_BAND_FLOOD_CAP = int(os.environ.get("STREAM_BAND_FLOOD_CAP", "8"))

# כמה בוטים לנסות במסלול המהיר לפני שנופלים למסלול הוותיק. המהיר משתמש
# בבריכת חיבורים קיימת ולא פותח כלום; הוותיק פותח session שלם לכל תת-טווח.
# כל ניסיון נוסף כאן חוסך עד 16 לחיצות יד — ראה ההסבר ב-_fetch_window.
MEDIA_BANDS_TRIES = int(os.environ.get("STREAM_BANDS_TRIES", "3"))


# מונה timeouts רצופים לכל (בוט, DC). מתאפס בכל הצלחה, כך שרק *רצף* אמיתי
# נחשב לבריכה מתה — חלון איטי מזדמן לא מפיל כלום.
_band_timeouts: dict = {}
BAND_TIMEOUT_LIMIT = int(os.environ.get("STREAM_BAND_TIMEOUT_LIMIT", "2"))


def _is_dead_conn(err) -> bool:
    """האם השגיאה מעידה על *חיבור מת* (ואז כדאי להפיל ולבנות בריכה טרייה),
    להבדיל מהאטה רגעית (FloodWait/timeout) שבה הבריכה בריאה. הפלת בריכה על
    כל האטה גרמה ל-thrash מתמיד: כל כמה דקות כל החיבורים נהרסו ונבנו, והסרט
    נתקע בזמן הבנייה."""
    return isinstance(err, (ConnectionError, OSError, EOFError, RuntimeError))


# ניסיונות חוזרים ברמת הבלוק הבודד. עד היום בלוק שנכשל הפיל את כל הרצועה,
# ואיתה את החלון, ואיתו את בריכת החיבורים — ואז הבקשה נפלה למסלול שפותח
# session שלם לכל משיכה. כלומר תקלה רגעית אחת ייצרה עשרות בקשות נוספות מול
# טלגרם, וזה בדיוק מה שהעמיס את החשבונות עד שהם נחנקו. ניסיון חוזר על אותו
# חיבור, עם השהיה שמכפילה את עצמה, עולה בקשה אחת ולא מפיל כלום.
BLOCK_RETRIES = int(os.environ.get("STREAM_BLOCK_RETRIES", "4"))
BLOCK_BACKOFF_START = float(os.environ.get("STREAM_BLOCK_BACKOFF", "0.1"))
BLOCK_BACKOFF_MAX = float(os.environ.get("STREAM_BLOCK_BACKOFF_MAX", "8"))


async def _get_block(session: Session, location, offset: int, limit: int) -> bytes:
    """מושך בלוק בודד, עם ניסיונות חוזרים והשהיה מכפילה.

    FloodWait קצר: ישנים בדיוק כמה שטלגרם ביקש. שגיאת חיבור רגעית: משהים
    ומנסים שוב על אותו חיבור. רק אחרי שכל הניסיונות נכשלו הכשל עולה למעלה.
    """
    backoff = BLOCK_BACKOFF_START
    last = None
    for attempt in range(max(1, BLOCK_RETRIES)):
        try:
            r = await session.invoke(functions.upload.GetFile(
                location=location, offset=offset, limit=limit, precise=False))
            return getattr(r, "bytes", b"")
        except FloodWait as e:
            # FloodWait ארוך אינו האטה רגעית — עדיף לוותר ולתת לחלון ליפול
            # לבוט אחר מאשר להחזיק את הצופה תקוע.
            if e.value > MEDIA_BAND_FLOOD_CAP:
                raise
            await asyncio.sleep(e.value + 0.5)
            continue
        except (OSError, ConnectionError, EOFError, asyncio.TimeoutError) as e:
            last = e
            if attempt == BLOCK_RETRIES - 1:
                raise
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BLOCK_BACKOFF_MAX)
    if last is not None:
        raise last
    return b""


async def _band_fetch(session: Session, location, lo: int, hi: int) -> bytes:
    """מושך בדיוק [lo, hi] דרך חיבור media יחיד ומחזיר את הבייטים."""
    # בלוק של מגהבייט — המקסימום שהפרוטוקול מרשה. בלוק קטן יותר חוסך בייטים
    # אבל מכפיל את מספר הבקשות, והמשאב שנגמר לנו הוא בקשות-לשנייה לכל חשבון
    # (נמדד ~15-20), לא רוחב פס. נבדק: 3MB בבלוקים של 256KB = 13 בקשות מול 4.
    block = MEDIA_CHUNK
    out = bytearray()
    offset = (lo // block) * block
    produced = offset
    while produced <= hi:
        chunk = await _get_block(session, location, offset, block)
        if not chunk:
            break
        c_start, c_end = produced, produced + len(chunk)
        a = max(lo, c_start) - c_start
        b = min(hi + 1, c_end) - c_start
        if a < b:
            out += chunk[a:b]
        produced = c_end
        offset = produced
        if len(chunk) < block:
            break
    return bytes(out)


async def _media_bands_fetch(chat_id, message_id, lo, hi, tried=None):
    """מושך [lo, hi] דרך כמה חיבורי media של *בוט אחד* מהמאגר, במקביל.

    ההבדל מהמסלול הישן: שם הבוט מושך צ'אנק, ממתין לתשובה, ומושך את הבא —
    רוב הזמן עובר בהמתנה. כאן כמה חיבורים של אותו בוט מושכים חלקים שונים
    בו-זמנית.

    קריטי: הבוט נבחר מהמאגר (round-robin), והחיבורים שייכים לו בלבד. גרסה
    קודמת השתמשה במאגר גלובלי מהבוט הראשי, וכל הצופים נדחסו דרך אותם 4
    חיבורים — מהיר לצופה בודד, איטי פי 6 בעומס אמיתי.

    כמו כן ה-file_reference תקף רק בהקשר הבוט ששלף אותו, ולכן שולפים את
    ההודעה דרך אותו בוט (עם המטמון הקיים) ולא דרך הבוט הראשי.

    מחזיר None על כל כשל — והקורא נופל בשקט למסלול הבוטים הוותיק. כשל כאן
    הוא כמעט תמיד תקלת *חיבור* (טלגרם סגר session לא פעיל), לא תקלת בוט —
    ולכן מפילים את החיבורים ולא מסמנים את הבוט כחנוק. הגרסה הקודמת ענישה את
    הבוט על אשמת החיבור, וכך הודחו בזה אחר זה בוטים בריאים לגמרי.
    """
    if STREAM_MEDIA_CONNS <= 0:
        return None
    bot = await pick_stream_bot_for(chat_id, message_id, exclude=tried)
    if bot is None:
        return None
    if tried is not None:
        tried.add(bot["name"])        # שהניסיון הבא על אותו חלון יבחר בוט אחר
    dc_id = gen = None
    # מסמנים את הבוט כתפוס לפריט הזה *מיד* אחרי הבחירה ובלי await ביניהם, כדי
    # שהחלון הבא (קריאה-מראש) לא יבחר בו ויתחרה איתו על אותם ארבעה חיבורים.
    busy_key = (chat_id, message_id)
    _inflight_bots.setdefault(busy_key, set()).add(bot["name"])
    try:
        msg = await _get_bot_msg_fast(bot, chat_id, message_id)
        if msg is None:
            return None
        media = msg.video or msg.audio or msg.document or msg.video_note
        if not media:
            return None
        dc_id, location = _file_location(media)
        sessions, gen = await get_media_session_pool_gen(
            bot["client"], bot["name"], dc_id, STREAM_MEDIA_CONNS, block=False)
        if not sessions:
            # קר: הבריכה עוד לא מוכנה. הגרסה הקודמת נפלה כאן למסלול הבוטים —
            # אבל למשיכת *זנב* (moov בסוף קובץ ענק) המסלול הזה נמדד ב-105 שניות
            # (4 בוטים × 25ש' timeout, כי stream_media לא קופץ ביעילות לאופסט
            # גבוה). לכן במקום זה בונים את החיבורים המהירים כאן ועכשיו (~5ש')
            # ומשתמשים במסלול המהיר, שכן יודע לקפוץ ישר לאופסט. הבנייה קורית
            # פעם אחת לכל DC; שאר הבקשות כבר מקבלות בריכה חמה מיידית.
            sessions, gen = await get_media_session_pool_gen(
                bot["client"], bot["name"], dc_id, STREAM_MEDIA_CONNS, block=True)
        if not sessions:
            return None            # גם הבנייה נכשלה — נופלים למסלול הבוטים
        total = hi - lo + 1
        # החלוקה חייבת ליפול על גבולות של MEDIA_CHUNK. טלגרם מגיש רק חתיכות
        # של 1MB, ו-_band_fetch מיישר כל רצועה למטה לגבול הקרוב — כך שחלוקה
        # של חלון 1MB לארבע רצועות של 256KB גרמה לארבעתן ליישר חזרה לאפס
        # ולהוריד *את אותו המגהבייט* ארבע פעמים: פי 4 תעבורה, אפס מקביליות.
        chunk_lo = (lo // MEDIA_CHUNK) * MEDIA_CHUNK
        n_chunks = (hi - chunk_lo) // MEDIA_CHUNK + 1
        n = max(1, min(len(sessions), n_chunks))
        per_band = -(-n_chunks // n)          # חתיכות שלמות לכל רצועה
        tasks, s = [], lo
        for i in range(n):
            if s > hi:
                break
            e = min(hi, chunk_lo + (i + 1) * per_band * MEDIA_CHUNK - 1)
            tasks.append(_band_fetch(sessions[i], location, s, e))
            s = e + 1
        # התקציב נגזר מגודל *הרצועה* ולא מגודל החלון: הרצועות רצות במקביל,
        # ולכן מה שקובע הוא האיטית שבהן, לא הסכום. הגרסה הקודמת חישבה לפי
        # הסכום ונתנה 18 שניות לחלון של מגהבייט אחד — וכל חיבור מת גבה בדיוק
        # 18.2 שניות של המתנה לפני הנפילה למסלול הגיבוי.
        band_mb = (per_band * MEDIA_CHUNK) / (1024 * 1024)
        budget = min(MEDIA_BANDS_MAX,
                     MEDIA_BANDS_TIMEOUT + band_mb * MEDIA_BANDS_PER_MB)
        t_start = time.time()
        parts = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=budget)
        elapsed = time.time() - t_start
        bad = next((p for p in parts if not isinstance(p, (bytes, bytearray))), None)
        if bad is not None:
            # לא מגישים חלון חלקי — נופלים למסלול אחר. *אבל* מפילים את בריכת
            # החיבורים רק אם הכשל הוא חיבור מת. FloodWait/reference-פג הם רגעיים
            # והבריכה בריאה; הפלה שלה עליהם גרמה ל-thrash והתקיעות "כל כמה דקות".
            if isinstance(bad, FileReferenceExpired):
                # קריטי: FileReferenceExpired מגיע *בתוך* תוצאות ה-gather ולכן
                # ה-except למטה לא תופס אותו. בלי הניקוי ה-reference הפג נשאר
                # במטמון וכל חלון נכשל שוב → הסרט נתקע עד כניסה מחדש.
                _purge_msg_cache(chat_id, message_id)
            elif _is_dead_conn(bad):
                log.warning("media bands (%s) חיבור מת: %s — מרענן חיבורים",
                            bot["name"], type(bad).__name__)
                await drop_media_sessions(bot["name"], dc_id, gen)
            else:
                # FloodWait ארוך או שגיאה רגעית אחרת — בריכה בריאה, לא נוגעים.
                log.info("media bands (%s) חלון נכשל רגעית: %s — fallback",
                         bot["name"], type(bad).__name__)
            return None
        out = bytearray()
        for p in parts:
            out += p
        if len(out) < total:
            return None
        _mark_ok(bot)
        _band_timeouts.pop((bot["name"], dc_id), None)   # חלון שהצליח מאפס את הרצף
        if elapsed > 0:
            note_bot_speed(bot, (total / 1024 / 1024) / elapsed)
        return bytes(out[:total])
    except FileReferenceExpired:
        _purge_msg_cache(chat_id, message_id)
        return None
    except asyncio.TimeoutError:
        # החלון חרג מה-budget. timeout בודד הוא איטיות ולא מוות, והפלת הבריכה
        # על כל אחד כזה היא ה-thrash שהקפיץ תקיעות כל כמה דקות.
        #
        # אבל ההנחה הקודמת — "אם החיבור באמת מת, החלון הבא ייכשל בשגיאת חיבור
        # וזו תפיל אותו" — פשוט אינה נכונה: חיבור MTProto מת *נתקע*, כלומר
        # מתבטא כ-timeout ולא כשגיאה. לכן בריכה מתה לא התרפאתה לעולם, כל חלון
        # עשה timeout, והכל נפל למסלול האיטי (נמדד 3.12MB/s → 0.14MB/s).
        #
        # הפשרה: סופרים timeouts רצופים לאותו (בוט, DC). בודד — מתעלמים; רצף
        # קצר — זו כבר לא איטיות אלא בריכה מתה, ומפילים אותה כדי שתיבנה טרייה.
        key = (bot["name"], dc_id)
        n = _band_timeouts.get(key, 0) + 1
        _band_timeouts[key] = n
        note_bot_speed(bot, 0.0)
        if n >= BAND_TIMEOUT_LIMIT and dc_id is not None and gen is not None:
            log.warning("media bands (%s) %d timeouts רצופים — מרענן חיבורים",
                        bot["name"], n)
            _band_timeouts.pop(key, None)
            await drop_media_sessions(bot["name"], dc_id, gen)
        else:
            log.info("media bands (%s) חלון איטי (timeout %d/%d)",
                     bot["name"], n, BAND_TIMEOUT_LIMIT)
        return None
    except FloodWait as e:
        log.info("media bands (%s) FloodWait %ss — fallback בלי הפלה", bot["name"], e.value)
        return None
    except Exception as e:
        # שם הטיפוס חובה: str(asyncio.TimeoutError()) ריק, והשורה הזו הודפסה
        # כ"נכשל: " בלי סיבה — מה שהסתיר בדיוק את הכשל הנפוץ ביותר כאן.
        log.warning("media bands (%s) נכשל: %s: %s — נופל למסלול הבוטים",
                    bot["name"], type(e).__name__, e)
        note_bot_speed(bot, 0.0)      # כשל מוריד את הציון מיד
        # gen=None פירושו שהכשל קרה עוד לפני שקיבלנו בריכה — אין מה להפיל.
        # מפילים רק על חיבור מת ממש (לא על שגיאה רגעית) כדי לא ליצור thrash.
        if dc_id is not None and gen is not None and _is_dead_conn(e):
            await drop_media_sessions(bot["name"], dc_id, gen)
        return None
    finally:
        s = _inflight_bots.get(busy_key)
        if s is not None:
            s.discard(bot["name"])
            if not s:
                _inflight_bots.pop(busy_key, None)


async def channel_stream_range_parallel(chat_id, message_id, start, end):
    """גרסה מקבילה עם *התחלה מהירה*: מעבדת חלון-אחר-חלון, וכל חלון נמשך בכמה
    תת-טווחים במקביל. קריטי לזמן-התחלה: הגשה מתבצעת רק אחרי שכל תת-הטווחים של
    החלון הושלמו — לכן חלון ראשון גדול (16MB) גרם ל-TTFB של כמה שניות ("לוקח
    מלא זמן להיפעל"). הפתרון: רמפת-האצה — החלונות הראשונים קטנים (הבייט הראשון
    מגיע כמעט מיד והנגינה מתחילה), ואז גדלים לחלון המלא למהירות שיא."""
    parts = max(2, STREAM_PARALLEL_PARTS)
    full_window = max(STREAM_PARALLEL_WINDOW, parts * 512 * 1024)
    MIN_PART = 512 * 1024   # לא לפצל לחתיכות קטנות מדי
    # רמפה: 1MB → 4MB → מלא. חלון ראשון קטן = TTFB נמוך; אחר כך מהירות מלאה.
    ramp = [1 * 1024 * 1024, 4 * 1024 * 1024]
    async def _fetch_window(wstart, wend):
        """מחזיר את כל בייטי החלון. קודם מסלול ה-media bands (חיבורים מקבילים
        לאותו DC — נמדד פי ~70 ממשיכה בחיבור יחיד), ואם הוא נכשל נופלים בשקט
        למסלול הבוטים הוותיק.

        קריטי: המסלול הוותיק בנוי על stream_media, ו-Client.get_file של
        Pyrogram *יוצר session שלם מאפס לכל קריאה* — חיבור, לחיצת יד
        קריפטוגרפית, ExportAuthorization+ImportAuthorization — ומשמיד אותו
        ב-finally. עם 4 תת-טווחים במקביל על עד 4 בוטים זה עד 16 לחיצות יד
        מלאות לכל חלון. נמדד בשרת: 6874 ניסיונות התחברות בחמש דקות (23
        בשנייה) בזמן שהקוד שלנו לא כתב ולו שורת אזהרה אחת.

        וזו לולאה שמזינה את עצמה: כשל במסלול המהיר → גיבוי → הצפת טלגרם
        וה-event loop בלחיצות יד → עוד כשלים במסלול המהיר. לכן מנסים קודם
        כמה בוטים *במסלול המהיר*, שמשתמש בבריכה קיימת ולא פותח כלום, ורק
        אם כולם נכשלו יורדים למסלול היקר.
        """
        tried = set()
        for _ in range(max(1, MEDIA_BANDS_TRIES)):
            fast = await _media_bands_fetch(chat_id, message_id, wstart, wend, tried)
            if fast is not None:
                return fast
        total_w = wend - wstart + 1
        n = max(1, min(parts, total_w // MIN_PART))
        step = -(-total_w // n)
        rngs, s = [], wstart
        while s <= wend:
            e2 = min(s + step - 1, wend)
            rngs.append((s, e2))
            s = e2 + 1
        results = await asyncio.gather(
            *[_fetch_subrange(chat_id, message_id, a, b) for a, b in rngs])
        return b"".join(results)

    def _window_end(p, i):
        w = min(ramp[i] if i < len(ramp) else full_window, full_window)
        return min(p + w - 1, end)

    # קריאה-מראש: עד עכשיו הלולאה הייתה סדרתית לחלוטין — מורידה חלון, מגישה
    # אותו, ורק *אחרי* שהצופה סיים לצרוך אותו מתחילה להוריד את הבא. כלומר כל
    # זמן הצפייה הרשת עמדה בטלה, וכשהבאפר של הנגן נגמר הוא נאלץ להמתין להורדה
    # שלמה — זה בדיוק ה"נתקע באמצע". כאן מתחילים להוריד את החלון הבא *לפני*
    # שמגישים את הנוכחי, כך שברוב המקרים הוא כבר מוכן כשהנגן מגיע אליו.
    pos, idx = start, 0
    ahead = None            # (task, next_pos, next_end)
    try:
        while pos <= end:
            wend = _window_end(pos, idx)
            idx += 1
            if ahead is not None and ahead[1] == pos:
                data = await ahead[0]
                ahead = None
            else:
                data = await _fetch_window(pos, wend)

            # מדליקים את החלון הבא לפני ההגשה — ההורדה רצה בזמן הצפייה.
            npos = wend + 1
            if npos <= end and STREAM_READAHEAD:
                nend = _window_end(npos, idx)
                ahead = (asyncio.create_task(_fetch_window(npos, nend)), npos, nend)

            yield data
            pos = npos
    finally:
        # הצופה עזב באמצע — לא משאירים הורדה מיותרת רצה ברקע.
        if ahead is not None:
            ahead[0].cancel()
            # אם המשימה כבר הספיקה להיכשל, cancel() לא עושה כלום והחריגה נשארת
            # "לא נאספה" — asyncio מדפיס אז אזהרה מלאה עם traceback, לכל צופה
            # שעוזב באמצע. הקולבק אוסף אותה ומשתיק את הרעש.
            ahead[0].add_done_callback(
                lambda t: t.cancelled() or t.exception())

# ── מטמון קצוות הקובץ ────────────────────────────────────────────────────────
# ב-MP4 שלא עבר faststart טבלת האינדקס (moov) יושבת ב*סוף* הקובץ. לכן כל נגן,
# בכל פתיחה, חייב למשוך כמה מגה-בייטים מהקצה לפני שהוא יודע איפה נמצא ולו
# פריים אחד — ורק אז הוא מתחיל. נמדד על ספיידרמן: moov שוקל 7.7MB, ומשיכתו
# ארכה 4.9 שניות ברגע טוב ו-71 ברגע רע.
#
# הבייטים האלה זהים לכל הצופים ולעולם לא משתנים, ולכן מספיק למשוך אותם פעם
# אחת ולהגיש מהדיסק. אותו דבר לראש הקובץ. זה חוסך את ההמתנה הזו בכל פתיחה
# חוזרת של אותו סרט, בלי לגעת באפליקציה.
EDGE_CACHE_DIR = DATA_DIR / "edge_cache"
EDGE_TAIL = int(os.environ.get("STREAM_EDGE_TAIL", str(12 * 1024 * 1024)))
EDGE_HEAD = int(os.environ.get("STREAM_EDGE_HEAD", str(2 * 1024 * 1024)))
EDGE_CACHE_MAX = int(os.environ.get("STREAM_EDGE_CACHE_MAX", str(3 * 1024 ** 3)))
_edge_filling: set = set()

def _edge_path(chat_id, message_id, which) -> Path:
    return EDGE_CACHE_DIR / f"{chat_id}_{message_id}.{which}"

def _edge_region(start, end, file_size):
    """מחזיר ('head'|'tail', תחילת_האזור) אם הטווח נמצא כולו באחד הקצוות."""
    if file_size <= EDGE_HEAD + EDGE_TAIL:
        return None
    if end < EDGE_HEAD:
        return "head", 0
    tail_start = file_size - EDGE_TAIL
    if start >= tail_start:
        return "tail", tail_start
    return None

def _edge_evict():
    """שומר על תקרת הגודל — מוחק את הקבצים שלא נגענו בהם הכי מזמן."""
    try:
        files = [(p.stat().st_atime, p.stat().st_size, p)
                 for p in EDGE_CACHE_DIR.glob("*.*")]
    except OSError:
        return
    total = sum(s for _, s, _ in files)
    for _atime, size, p in sorted(files):
        if total <= EDGE_CACHE_MAX:
            break
        try:
            p.unlink()
            total -= size
        except OSError:
            pass

def _edge_read(chat_id, message_id, which, region_len):
    """קורא אזור קצה מהדיסק. מחזיר None אם אינו שם או אינו שלם."""
    path = _edge_path(chat_id, message_id, which)
    try:
        if path.exists() and path.stat().st_size == region_len:
            os.utime(path, None)                      # לצורך ה-LRU
            return path.read_bytes()
    except OSError:
        pass
    return None


async def _edge_fill(chat_id, message_id, which, region_start, region_len):
    """ממלא אזור קצה *ברקע*. אסור לקרוא לזה בתוך מסלול הבקשה.

    האזור הוא 12MB, והמשיכה שלו מטלגרם לוקחת שניות ולעיתים נתקעת. גרסה
    קודמת עשתה את זה מול הצופה: הבקשה לא החזירה בייט אחד עד שכל האזור
    נמשך, וכשהמשיכה נתקעה הצופה קיבל אפס — גרוע יותר מלא לטמון בכלל, ודווקא
    באזור שכל נגן קורא לפני הפריים הראשון.
    """
    key = (chat_id, message_id, which)
    if key in _edge_filling:
        return
    _edge_filling.add(key)
    try:
        buf = bytearray()
        try:
            async for chunk in _channel_range_gen(chat_id, message_id, region_start,
                                                  region_start + region_len - 1):
                buf += chunk
        except StreamGap:
            return                                    # ננסה שוב בבקשה הבאה
        if len(buf) < region_len:
            return
        path = _edge_path(chat_id, message_id, which)
        try:
            EDGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(bytes(buf))
            tmp.replace(path)
            _edge_evict()
            log.info("מטמון קצה: נשמר %s של %s/%s (%.1fMB)",
                     which, chat_id, message_id, region_len / 1024 / 1024)
        except OSError as e:
            log.warning("מטמון קצה: שמירה נכשלה — %s", e)
    finally:
        _edge_filling.discard(key)


def _channel_range_gen(chat_id, message_id, start, end):
    """בורר בין הזרמה מקבילה (אם הופעלה) לרגילה."""
    if STREAM_PARALLEL_PARTS > 1 and len(_stream_bots) >= 2:
        return channel_stream_range_parallel(chat_id, message_id, start, end)
    return channel_stream_range(chat_id, message_id, start, end)

# חימום-מקדים של בריכות ה-media. "המשך צפייה" קופץ לאמצע הקובץ (לא במטמון
# הקצה) והמסלול המקבילי מסובב בוט אחר לכל חלון — כל בוט קר בונה בריכה מחדש
# (~5ש) בזה אחר זה, ולכן resume חיכה פי-2. כאן, ברגע שפותחים סרט, מדליקים את
# הבנייה של כמה בוטים *במקביל* (block=False רק מדליק את המילוי ברקע ולא ממתין),
# כך שכשהחלונות מסתובבים בין הבוטים הם כבר חמים. ה-cooldown מונע הצפה: אותו DC
# לא מחומם שוב בתוך כמה שניות, גם אם הנגן שולח עשרות בקשות range.
PREWARM_BOTS = int(os.environ.get("STREAM_PREWARM_BOTS", "8"))
PREWARM_COOLDOWN = int(os.environ.get("STREAM_PREWARM_COOLDOWN", "20"))
_prewarm_seen: dict = {}

def _prewarm_dc(dc_id: int):
    now = time.time()
    if now - _prewarm_seen.get(dc_id, 0) < PREWARM_COOLDOWN:
        return
    _prewarm_seen[dc_id] = now
    healthy = [b for b in _stream_bots
               if b["cooldown_until"] < now and b.get("peer_ok", True)]

    async def _run():
        await asyncio.gather(*[
            get_media_session_pool_gen(b["client"], b["name"], dc_id,
                                       STREAM_MEDIA_CONNS, block=False)
            for b in healthy[:PREWARM_BOTS]], return_exceptions=True)
    if healthy:
        asyncio.create_task(_run())


async def stream_from_channel(chat_id: int, message_id: int, request: Request):
    media = await channel_get_media(chat_id, message_id)
    if not media:
        raise HTTPException(status_code=503, detail="No media / no healthy bot")
    # מחממים את בריכות הבוטים ל-DC של הקובץ ברקע, כדי ש'המשך צפייה' יתחיל מהר
    try:
        _prewarm_dc(_file_location(media)[0])
    except Exception:
        pass
    file_size = media.file_size
    mime_type = getattr(media, "mime_type", "application/octet-stream")
    file_name = getattr(media, "file_name", None) or f"file_{message_id}"
    safe_name = file_name.encode("ascii", "ignore").decode("ascii") or f"file_{message_id}"
    disposition = f'inline; filename="{safe_name}"; filename*=UTF-8\'\'{quote(file_name)}'
    range_header = request.headers.get("Range")
    if range_header:
        start, end = parse_range(range_header, file_size)
        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
            "Content-Disposition": disposition,
            **CORS_MEDIA,
        }
        # קצוות הקובץ מוגשים מהדיסק: שם יושבת טבלת האינדקס שכל נגן חייב
        # לקרוא לפני הפריים הראשון, והיא זהה לכל הצופים.
        region = _edge_region(start, end, file_size)
        if region is not None:
            which, region_start = region
            region_len = EDGE_HEAD if which == "head" else EDGE_TAIL
            data = _edge_read(chat_id, message_id, which, region_len)
            if data is not None:
                off = start - region_start
                return Response(content=data[off:off + (end - start + 1)],
                                status_code=206, media_type=mime_type,
                                headers=headers)
            # אין במטמון — ממלאים ברקע ומגישים עכשיו כרגיל, בלי להשהות
            asyncio.create_task(_edge_fill(chat_id, message_id, which,
                                           region_start, region_len))
        return StreamingResponse(
            _channel_range_gen(chat_id, message_id, start, end),
            status_code=206, media_type=mime_type, headers=headers)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Disposition": disposition,
        **CORS_MEDIA,
    }
    return StreamingResponse(
        _channel_range_gen(chat_id, message_id, 0, file_size - 1),
        status_code=200, media_type=mime_type, headers=headers)

# ── Stream Route ──────────────────────────────────────────────────────────────

@api.get("/stream/{chat_id}/{message_id}")
async def stream(chat_id: int, message_id: int, request: Request,
                 exp: int = 0, sig: str = ""):
    check_hotlink(request)
    # אימות קישור חתום: אם מוגדר סוד חתימה — הקישור חייב exp תקף וחתימה נכונה.
    if SIGN_SECRET:
        if not exp or exp < int(time.time()):
            raise HTTPException(status_code=403, detail="הקישור פג תוקף")
        if not hmac.compare_digest(sig, _stream_sig(str(chat_id), str(message_id), exp)):
            raise HTTPException(status_code=403, detail="חתימה שגויה")
    # תוכן בערוץ (chat_id שלילי) → דרך pool הבוטים; תוכן ישן (chat פרטי) → בוט ראשי
    if chat_id < 0 and _stream_bots:
        return await stream_from_channel(chat_id, message_id, request)
    client_key = request.client.host if request.client else "unknown"
    sess = await get_session(chat_id, message_id, client_key)
    file_size = sess.file_size
    mime_type = getattr(sess.media, "mime_type", "application/octet-stream")
    file_name = getattr(sess.media, "file_name", None) or f"file_{message_id}"

    safe_name   = file_name.encode("ascii", "ignore").decode("ascii") or f"file_{message_id}"
    disposition = f'inline; filename="{safe_name}"; filename*=UTF-8\'\'{quote(file_name)}'

    range_header = request.headers.get("Range")
    if range_header:
        start, end = parse_range(range_header, file_size)
        headers = {
            "Content-Range":       f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges":       "bytes",
            "Content-Length":      str(end - start + 1),
            "Content-Disposition": disposition,
        }
        return StreamingResponse(
            stream_session_range(sess, start, end),
            status_code=206, media_type=mime_type, headers=headers,
        )

    headers = {
        "Accept-Ranges":       "bytes",
        "Content-Length":      str(file_size),
        "Content-Disposition": disposition,
    }
    return StreamingResponse(
        stream_session_range(sess, 0, file_size - 1),
        status_code=200, media_type=mime_type, headers=headers,
    )

# ── Cast Route: אודיו→AAC ל-Chromecast ──────────────────────────────────────
# Chromecast לא מפענח AC3/DTS ולפעמים תופס audio-track שגוי → וידאו בלי קול.
# כאן מעבירים את הזרם דרך ffmpeg: הוידאו נשאר כמו שהוא (copy, אפס עומס), והאודיו
# מומר ל-AAC סטריאו יחיד — כך ל-TV יש קול. משמש רק במצב שידור לטלוויזיה; צפייה
# רגילה ממשיכה דרך /stream. ה-input הוא /stream המקומי (מנצל את כל בריכת הבוטים).
@api.get("/cast/{chat_id}/{message_id}")
async def cast_remux(chat_id: int, message_id: int, request: Request,
                     exp: int = 0, sig: str = ""):
    check_hotlink(request)
    if SIGN_SECRET:
        if not exp or exp < int(time.time()):
            raise HTTPException(status_code=403, detail="הקישור פג תוקף")
        if not hmac.compare_digest(sig, _stream_sig(str(chat_id), str(message_id), exp)):
            raise HTTPException(status_code=403, detail="חתימה שגויה")
    # קישור פנימי חתום ל-/stream המקומי (ffmpeg מושך ממנו, דרך בריכת הבוטים)
    iexp = int(time.time()) + SIGN_TTL
    isig = _stream_sig(str(chat_id), str(message_id), iexp) if SIGN_SECRET else ""
    q = f"?exp={iexp}&sig={isig}" if SIGN_SECRET else ""
    src = f"http://127.0.0.1:8000/stream/{chat_id}/{message_id}{q}"
    args = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", src,
        "-map", "0:v:0", "-map", "0:a:0?",       # וידאו ראשון + אודיו ראשון (אם יש)
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ac", "2",
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "-f", "mp4", "pipe:1",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="ffmpeg לא מותקן בשרת")

    async def gen():
        try:
            while True:
                chunk = await proc.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                proc.kill()
            except Exception:
                pass

    return StreamingResponse(gen(), media_type="video/mp4",
                             headers={"Content-Disposition": "inline", **CORS_MEDIA})

# ── HLS Relay (עוקף "http משודרג אוטומטית ל-https ושבור" בדפדפן) ────────────
# חלק מספקי שידור חי (למשל stream.mcquack.net) מגישים רק http:// תקין -
# ה-https שלהם מציג תעודת SSL שלא תואמת לדומיין בכלל (בדקנו ישירות: התעודה
# רשומה על דומיין אחר). דפדפנים/WebView משדרגים אוטומטית כל בקשת מדיה
# מ-http ל-https כשהיא נטענת מתוך דף מאובטח (כמו האתר/אפליקציה שלנו) - השדרוג
# הזה פוגע בתעודה השבורה ונכשל, גם כשה-http המקורי עובד מצוין ומיידי.
# הפתרון: שולפים את הזרם כאן בצד השרת (לא כפוף למדיניות הדפדפן, ול-http
# הרגיל אין שום בעיה) ומגישים אותו הלאה דרך ה-https התקין של ה-Space הזה,
# כולל שכתוב ההפניות היחסיות בתוך ה-m3u8 (גם ה-manifest המקונן וגם המקטעים
# .ts) כך שהכל ממשיך לעבור דרך אותו יחסור.
# רשימת ה-hosts שמותר להעביר דרך ה-relay. *לא* open proxy: רק hosts שהמנהל
# הוסיף במפורש מהפאנל מותרים. הרשימה נשמרת לקובץ כדי לשרוד restart, ותמיד כוללת
# את ברירת המחדל המובנית. stream.mcquack.net מובנה ולא ניתן להסרה כדי שהערוצים
# הקיימים לא יישברו.
# כל host שמור עם ה-origin האמיתי שלו (scheme+port), לא רק השם - חלק מהמקורות
# (למשל tv.embyil.tv:86, https) לא יושבים על http:80 הרגיל, והרלֵיי חייב לפנות
# בדיוק לסכימה/פורט הנכונים כדי שהמקור בכלל יענה.
RELAY_HOSTS_FILE = DATA_DIR / "relay_hosts.json"
_DEFAULT_RELAY_HOSTS = {"stream.mcquack.net": {"scheme": "http", "port": 80}}

def _normalize_relay_origin(scheme, port) -> dict:
    scheme = scheme if scheme in ("http", "https") else "http"
    try:
        port = int(port)
        if not (1 <= port <= 65535):
            raise ValueError
    except (TypeError, ValueError):
        port = 443 if scheme == "https" else 80
    return {"scheme": scheme, "port": port}

def _load_relay_hosts() -> dict:
    hosts = dict(_DEFAULT_RELAY_HOSTS)
    try:
        if RELAY_HOSTS_FILE.exists():
            data = json.loads(RELAY_HOSTS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for h, info in data.items():
                    h = str(h).strip().lower()
                    if not h:
                        continue
                    if isinstance(info, dict):
                        hosts[h] = _normalize_relay_origin(info.get("scheme"), info.get("port"))
                    else:
                        hosts[h] = _normalize_relay_origin("http", 80)
            elif isinstance(data, list):
                # פורמט ישן: רשימת שמות בלבד (מלפני תמיכה בסכימה/פורט) - http:80.
                for h in data:
                    h = str(h).strip().lower()
                    if h:
                        hosts[h] = _normalize_relay_origin("http", 80)
    except Exception as e:
        log.warning("טעינת relay_hosts נכשלה: %s", e)
    return hosts

def _save_relay_hosts(hosts: dict):
    RELAY_HOSTS_FILE.write_text(
        json.dumps({h: hosts[h] for h in sorted(hosts)}, ensure_ascii=False, indent=2),
        encoding="utf-8")

HLS_RELAY_ALLOWED_HOSTS = _load_relay_hosts()

# ולידציית hostname + חסימת כתובות פנימיות/פרטיות (הגנת SSRF): גם ברשימה
# מנוהלת, אסור שהרלֵיי יוכל לפנות ל-localhost/רשת פנימית של השרת.
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")

def _host_is_public(host: str) -> bool:
    try:
        import ipaddress, socket
        for info in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(info[4][0])
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
                return False
        return True
    except Exception:
        return False

class RelayHostReq(BaseModel):
    password: str
    action: str            # list / add / remove
    host: Optional[str] = None
    scheme: Optional[str] = None   # http / https - אופציונלי, נגזר מהכתובת אם לא צוין
    port: Optional[int] = None     # אופציונלי - נגזר מהכתובת/מהסכימה אם לא צוין

@api.post("/api/relay/hosts")
async def relay_hosts_manage(req: RelayHostReq, request: Request):
    """ניהול רשימת ה-hosts המותרים לרלֵיי (מוגן בסיסמת פאנל)."""
    check_panel_password(request, req.password)
    global HLS_RELAY_ALLOWED_HOSTS
    def _result():
        return {
            "hosts": [
                {"host": h, "scheme": info["scheme"], "port": info["port"],
                 "builtin": h in _DEFAULT_RELAY_HOSTS}
                for h, info in sorted(HLS_RELAY_ALLOWED_HOSTS.items())
            ],
            "builtin": sorted(_DEFAULT_RELAY_HOSTS),
        }
    if req.action == "list":
        return _result()
    if req.action == "add":
        raw = (req.host or "").strip().lower()
        scheme, port = None, None
        if "://" in raw:
            p = urlparse(raw)
            h = p.hostname or ""
            scheme = p.scheme if p.scheme in ("http", "https") else None
            port = p.port
        else:
            h = raw.split("/")[0]
            if ":" in h:
                h, _, pp = h.partition(":")
                try:
                    port = int(pp)
                except ValueError:
                    port = None
        if not h or not _HOSTNAME_RE.match(h):
            raise HTTPException(400, "שם host לא תקין")
        # שדות מפורשים בבקשה גוברים על מה שנגזר מהכתובת שהודבקה.
        if req.scheme in ("http", "https"):
            scheme = req.scheme
        if req.port:
            port = req.port
        if port is not None and not (1 <= port <= 65535):
            raise HTTPException(400, "פורט לא תקין")
        if not await asyncio.to_thread(_host_is_public, h):
            raise HTTPException(400, "ה-host לא נגיש או מפנה לכתובת פנימית — נחסם")
        origin = _normalize_relay_origin(scheme or "http", port)
        HLS_RELAY_ALLOWED_HOSTS = {**HLS_RELAY_ALLOWED_HOSTS, h: origin}
        _save_relay_hosts(HLS_RELAY_ALLOWED_HOSTS)
        return _result()
    if req.action == "remove":
        h = (req.host or "").strip().lower()
        if h in _DEFAULT_RELAY_HOSTS:
            raise HTTPException(400, "אי אפשר להסיר host מובנה")
        HLS_RELAY_ALLOWED_HOSTS = {x: v for x, v in HLS_RELAY_ALLOWED_HOSTS.items() if x != h}
        _save_relay_hosts(HLS_RELAY_ALLOWED_HOSTS)
        return _result()
    raise HTTPException(400, "פעולה לא מוכרת")

# לקוח משותף אחד עם keep-alive, לא לקוח חדש (וחיבור TCP חדש) בכל בקשה -
# תיקון: "מנגן שנייה ונתקע 10 שניות" קרה כי כל מקטע וידאו (כ-3.6MB, 5
# שניות תוכן) חיכה קודם להוריד את כל הקובץ מ-mcquack.net *ואז* להתחיל
# לשלוח אותו הלאה ללקוח - הכפלה של זמן ההמתנה בפועל (הורדה מלאה + שליחה
# מלאה, ברצף, לא במקביל), וזה בנוסף לתקורה של חיבור TCP חדש בכל פעם.
_hls_relay_client: Optional[httpx.AsyncClient] = None

# חלק מהמקורות (למשל tv.embyil.tv) חוסמים/מפנים ל-404 בקשות בלי User-Agent
# של דפדפן/נגן אמיתי - ה-UA הדיפולטי של httpx (python-httpx/...) נחסם. אותו
# UA ששימש בבדיקות הידניות מול המקור הזה (diag_live.sh / test_live.sh) ועבד.
HLS_RELAY_UPSTREAM_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"),
}

# השרת הזה משותף עם הזרמת הטלגרם (אותו CPU מוגבל) - כמה צופים בו-זמנית
# באותו ערוץ חי היו יוצרים כמה בקשות נפרדות זהות לגמרי למקור (אותו manifest,
# אותו מקטע), כל אחת מיותרת ומכפילה עומס CPU/רשת בדיוק כשהתוכן דרך טלגרם
# כבר איטי בגלל אותה תחרות על משאבים. שני קאשים קלים מפחיתים כפילות בלי
# לפגוע בזמן התגובה של הצופה היחיד/הראשון: manifest (זעיר, TTL קצר) נשמר
# ישירות; מקטע וידאו (גדול) מוזרם כרגיל לצופה הראשון שמבקש אותו, וכל בקשה
# מקבילה לאותו מקטע בדיוק "מצטרפת" לזרימה הקיימת במקום לפתוח בקשה חדשה משלה.
_hls_manifest_cache: dict = {}
MANIFEST_CACHE_TTL = 1.5
_hls_segment_inflight: dict = {}

# ── משיכה מקדימה של מקטעי שידור חי ───────────────────────────────────────────
# נמדד מול הספק: משיכת manifest לוקחת 0.7–3.0ש ומקטע של 6 שניות עוד 1.6–3.7ש,
# כך שסבב שלם כמעט משתווה לאורך המקטע עצמו. אין מרווח, וכל עיכוב מרוקן את
# הבאפר של הנגן — זה מה שנראה למשתמש כ"נתקע ומסתובב".
#
# הרעיון: ברגע שנגן מבקש את ה-manifest אנחנו כבר יודעים מה המקטעים הבאים.
# מושכים אותם ברקע מיד, כך שכשהנגן יבקש אותם הם כבר אצלנו וההמתנה לספק
# יורדת מהנתיב הקריטי. בלי זה כל מקטע נמשך רק כשמבקשים אותו.
_hls_seg_cache: dict = {}          # upstream_url -> (expires_at, bytes)
_hls_prefetching: set = set()
HLS_PREFETCH_COUNT = int(os.environ.get("HLS_PREFETCH_COUNT", "3"))
HLS_SEG_TTL = float(os.environ.get("HLS_SEG_TTL", "45"))
HLS_SEG_CACHE_MAX = int(os.environ.get("HLS_SEG_CACHE_MAX", str(250 * 1024 * 1024)))


def _seg_cache_bytes() -> int:
    return sum(len(v[1]) for v in _hls_seg_cache.values())


def _seg_cache_evict():
    """מפנה מקטעים שפגו, ואם עדיין חורגים — את הישנים ביותר."""
    now = time.time()
    for k in [k for k, v in _hls_seg_cache.items() if v[0] <= now]:
        _hls_seg_cache.pop(k, None)
    if _seg_cache_bytes() <= HLS_SEG_CACHE_MAX:
        return
    for k, _ in sorted(_hls_seg_cache.items(), key=lambda kv: kv[1][0]):
        _hls_seg_cache.pop(k, None)
        if _seg_cache_bytes() <= HLS_SEG_CACHE_MAX:
            break


async def _prefetch_one(url: str):
    if url in _hls_prefetching or url in _hls_seg_cache:
        return
    _hls_prefetching.add(url)
    try:
        r = await _hls_relay_client.get(url, headers=HLS_RELAY_UPSTREAM_HEADERS)
        if r.status_code == 200 and r.content:
            _hls_seg_cache[url] = (time.time() + HLS_SEG_TTL, r.content)
            _seg_cache_evict()
    except Exception:
        pass                      # משיכה מקדימה היא בונוס; כשל בה לא מעניין
    finally:
        _hls_prefetching.discard(url)


def _prefetch_from_manifest(manifest_text: str, base_url: str):
    """מדליק ברקע משיכה של המקטעים האחרונים ב-playlist (החדשים ביותר)."""
    if HLS_PREFETCH_COUNT <= 0 or _hls_relay_client is None:
        return
    segs = [ln.strip() for ln in manifest_text.splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]
    for rel in segs[-HLS_PREFETCH_COUNT:]:
        try:
            asyncio.create_task(_prefetch_one(urljoin(base_url, rel)))
        except Exception:
            pass


def _is_hls_manifest(path: str) -> bool:
    return path.endswith(".m3u8")


# ספקים רבים מפזרים את המקטעים על שרתי-קצה בכתובות IP שמתחלפות: המניפסט
# מגיע מדומיין אחד, אבל כל מקטע מצביע ל-IP אחר, והרשימה משתנה מיום ליום.
# רשימה לבנה קבועה לא יכולה לעמוד בזה. לכן: מארח שהופיע בתוך מניפסט שאנחנו
# עצמנו משכנו ממארח מאושר — נרשם אוטומטית לזמן קצוב. זה נשאר סגור (רק
# כתובות שהמקור המהימן נתן לנו) בלי לדרוש תחזוקה ידנית.
_relay_learned_hosts: dict = {}          # host -> {"scheme","port","exp"}
RELAY_LEARNED_TTL = int(os.environ.get("RELAY_LEARNED_TTL", "7200"))

def _relay_origin_for(host: str) -> Optional[dict]:
    """מחזיר את מוצא ההעברה למארח — מהרשימה הקבועה או מזו שנלמדה."""
    origin = HLS_RELAY_ALLOWED_HOSTS.get(host)
    if origin is not None:
        return origin
    learned = _relay_learned_hosts.get(host)
    if learned and learned["exp"] > time.time():
        return learned
    if learned:
        _relay_learned_hosts.pop(host, None)
    return None


def _rewrite_hls_manifest(text: str, base_url: str) -> str:
    # לומדים מארחים חדשים רק ממניפסט שהגיע ממארח מאושר
    parent_ok = urlparse(base_url).hostname in HLS_RELAY_ALLOWED_HOSTS
    out_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(line)
            continue
        absolute = urljoin(base_url, stripped)
        parsed = urlparse(absolute)
        if parsed.hostname and _relay_origin_for(parsed.hostname) is None:
            if not parent_ok or parsed.scheme not in ("http", "https"):
                out_lines.append(line)  # לא ידוע לנו - עדיף להשאיר כמו שהוא מלשבור לגמרי
                continue
            _relay_learned_hosts[parsed.hostname] = {
                "scheme": parsed.scheme,
                "port": parsed.port or (443 if parsed.scheme == "https" else 80),
                "exp": time.time() + RELAY_LEARNED_TTL,
            }
            log.info("relay: נלמד מארח מקטעים %s (מתוך %s)",
                     parsed.hostname, urlparse(base_url).hostname)
        # שומרים את הפורט בנתיב המשוכתב: בלעדיו מקטע שיושב על פורט לא-רגיל
        # היה נמשך מהפורט הרשום למארח, ומחזיר 404.
        seg_default = 443 if parsed.scheme == "https" else 80
        seg_host = parsed.hostname
        if parsed.port and parsed.port != seg_default:
            seg_host = f"{seg_host}:{parsed.port}"
        relayed = f"/hls-relay/{seg_host}/{parsed.path.lstrip('/')}"
        if parsed.query:
            relayed += f"?{parsed.query}"
        out_lines.append(relayed)
    return "\n".join(out_lines)


# ── רלֵיי עם המרת מיכל (remux) — לערוצים ש-Shaka נתקע עליהם ──────────────────
# חלק מהמקודדים (למשל ספורט 5 סטארס ב-tv.embyil.tv) משדרים ב-open-GOP: יש
# פריימי I אבל אף IDR. VLC/ffmpeg מנגנים את זה מצוין - הם מסמנים כל פריים I
# כנקודת כניסה. mux.js (שבו Shaka משתמש כדי לפרק MPEG-TS) מחפש אך ורק NAL מסוג
# IDR ומשליך כל פריים עד שימצא אחד; כשאין - הוא ממתין לנצח, וזה ה"ספינר
# האינסופי" באפליקציה. הנגן באפליקציה מוטמע ב-APK ולכן אי אפשר לתקן אותו בלי
# release, אבל אפשר לתקן את *הזרם*: מעבירים אותו דרך ffmpeg ב-copy מוחלט
# (בלי קידוד מחדש - אפס עומס על ה-CPU) ל-fMP4, ושם ffmpeg מסמן כל פריים I
# כ-sync sample. נמדד: סגמנט של ערוץ 140 יצא עם 10 sync samples.
#
# ffmpeg מושך מה-relay המקומי שלנו (127.0.0.1) ולא ישירות מהמקור, כדי לא לשכפל
# את הטיפול ב-TLS/allowlist/User-Agent שכבר קיים ב-hls_relay.
HLS_FIX_DIR = Path("/tmp/zovex-hlsfix")
HLS_FIX_IDLE_SEC = 90          # ffmpeg נסגר אחרי שאין צופים
_hls_fix: dict = {}            # key -> {"proc","dir","last","ready"}
_hls_fix_lock = asyncio.Lock()


def _hls_fix_dir_of(path: str) -> str:
    """התיקייה של הערוץ בתוך הנתיב: live/140/chunks.m3u8 → live/140.
    המפתח נגזר ממנה (ולא מהנתיב המלא) כדי שבקשת ה-playlist ובקשות הסגמנטים
    שאחריה (s13.m4s / init.mp4) יפלו על אותו תהליך ffmpeg."""
    last = path.rsplit("/", 1)[-1]
    if "." in last and "/" in path:
        return path.rsplit("/", 1)[0]
    return path.strip("/")


def _hls_fix_key(host: str, path: str) -> str:
    import hashlib as _h
    return _h.sha1(f"{host}/{_hls_fix_dir_of(path)}".encode()).hexdigest()[:16]


async def _hls_fix_start(host: str, path: str) -> Optional[dict]:
    """מפעיל (או מחזיר קיים) תהליך ffmpeg שממיר את הערוץ ל-HLS/fMP4 מקומי."""
    key = _hls_fix_key(host, path)
    async with _hls_fix_lock:
        ent = _hls_fix.get(key)
        if ent and ent["proc"].returncode is None:
            ent["last"] = time.time()
            return ent
        outdir = HLS_FIX_DIR / key
        try:
            import shutil
            shutil.rmtree(outdir, ignore_errors=True)
            outdir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log.error("hls_fix: יצירת תיקייה נכשלה - %s", e)
            return None
        src = f"http://127.0.0.1:{PORT}/hls-relay/{host}/{path}"
        args = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-fflags", "+genpts", "-i", src,
            "-c", "copy",                       # בלי קידוד מחדש - רק החלפת מיכל
            # AAC ב-MPEG-TS ארוז ב-ADTS, וב-MP4 צריך ASC. בלי הפילטר הזה
            # ffmpeg נכשל על כל חבילת אודיו ("Malformed AAC bitstream") ומייצר
            # פלט קטוע - נתפס בבדיקה מקומית לפני הפריסה.
            "-bsf:a", "aac_adtstoasc",
            "-f", "hls", "-hls_time", "4", "-hls_list_size", "6",
            "-hls_flags", "delete_segments+independent_segments+omit_endlist",
            "-hls_segment_type", "fmp4",
            "-hls_fmp4_init_filename", "init.mp4",
            "-hls_segment_filename", str(outdir / "s%d.m4s"),
            str(outdir / "index.m3u8"),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL)
        except FileNotFoundError:
            log.error("hls_fix: ffmpeg לא מותקן בשרת")
            return None
        ent = {"proc": proc, "dir": outdir, "last": time.time()}
        _hls_fix[key] = ent
        return ent


async def _hls_fix_reaper():
    """סוגר תהליכי ffmpeg של ערוצים שאיש כבר לא צופה בהם."""
    import shutil
    while True:
        await asyncio.sleep(30)
        now = time.time()
        for key, ent in list(_hls_fix.items()):
            if now - ent["last"] < HLS_FIX_IDLE_SEC:
                continue
            try:
                if ent["proc"].returncode is None:
                    ent["proc"].kill()
            except Exception:
                pass
            shutil.rmtree(ent["dir"], ignore_errors=True)
            _hls_fix.pop(key, None)
            log.info("hls_fix: נסגר ערוץ לא פעיל %s", key)


# חייב להירשם *לפני* המסלול הכללי /hls-relay/{host}/{path} — אחרת "_fix" ייחשב
# ל-host. גם חייב לשבת תחת /hls-relay/ כי nginx מעביר רק קידומות מוכרות.
@api.get("/hls-relay/_fix/{host}/{path:path}")
async def hls_relay_fixed(host: str, path: str, request: Request):
    check_hotlink(request)
    if host not in HLS_RELAY_ALLOWED_HOSTS:
        raise HTTPException(403, "host not allowed")

    # קבצים שה-ffmpeg כבר מייצר (init.mp4 / s3.m4s) מוגשים ישירות מהדיסק.
    name = path.rsplit("/", 1)[-1]
    if name == "init.mp4" or name.endswith(".m4s"):
        ent = _hls_fix.get(_hls_fix_key(host, path))
        if not ent:
            raise HTTPException(404, "stream not active")
        ent["last"] = time.time()
        f = ent["dir"] / name
        if not f.exists():
            raise HTTPException(404, "segment not ready")
        return Response(
            content=f.read_bytes(),
            media_type="video/mp4" if name == "init.mp4" else "video/iso.segment",
            headers={"Cache-Control": "public, max-age=60", **CORS_MEDIA},
        )

    # בקשה ל-playlist: מוודאים שה-ffmpeg רץ, מחכים שייווצר, ומשכתבים נתיבים.
    ent = await _hls_fix_start(host, path)
    if ent is None:
        raise HTTPException(502, "hls_fix: לא ניתן להפעיל את ההמרה")
    idx = ent["dir"] / "index.m3u8"
    for _ in range(120):                      # עד ~12 שניות לסגמנטים ראשונים
        if idx.exists() and idx.read_text(encoding="utf-8", errors="ignore").count(".m4s") >= 1:
            break
        if ent["proc"].returncode is not None:
            raise HTTPException(502, "hls_fix: ffmpeg נכשל")
        await asyncio.sleep(0.1)
    else:
        raise HTTPException(504, "hls_fix: הזרם לא התחיל בזמן")

    base = f"/hls-relay/_fix/{host}/{path.rstrip('/')}"
    base = base.rsplit("/", 1)[0] if "." in base.rsplit("/", 1)[-1] else base
    out = []
    for line in idx.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("#EXT-X-MAP:"):
            out.append(f'#EXT-X-MAP:URI="{base}/init.mp4"')
        elif s and not s.startswith("#"):
            out.append(f"{base}/{s}")
        else:
            out.append(line)
    return Response(content="\n".join(out),
                    media_type="application/vnd.apple.mpegurl",
                    headers={"Cache-Control": "no-cache", **CORS_MEDIA})


@api.get("/hls-relay/{host}/{path:path}")
async def hls_relay(host: str, path: str, request: Request):
    check_hotlink(request)
    # ה-host יכול לכלול פורט מפורש: /hls-relay/tv.embyil.tv:7070/...
    # ספק אחד יכול לפזר ערוצים על כמה פורטים באותו דומיין (ספורט 6 יושב על
    # 7070 בעוד השאר על 86), ורשומה אחת למארח לא יכולה לתאר את זה. ההרשאה
    # עדיין נבדקת מול שם המארח בלבד, כך שזה לא פותח שום מארח חדש.
    base_host, _, explicit_port = host.partition(":")
    origin = _relay_origin_for(base_host)
    if origin is None:
        raise HTTPException(403, "host not allowed")
    scheme, port = origin["scheme"], origin["port"]
    if explicit_port.isdigit():
        port = int(explicit_port)
    host = base_host
    default_port = 443 if scheme == "https" else 80
    netloc = host if port == default_port else f"{host}:{port}"
    upstream_url = f"{scheme}://{netloc}/{path}"
    if request.url.query:
        upstream_url += f"?{request.url.query}"

    if _is_hls_manifest(path):
        # manifest זעיר (KB בודדים) - קאש קצר (TTL=1.5s) חוסך בקשה כפולה
        # למקור כשכמה צופים מבקשים בערך באותה שנייה; חייבים גם ככה לקרוא
        # במלואו כדי לשכתב שורה-שורה, אז אין עלות נוספת לשמור את התוצאה.
        now = time.time()
        cached = _hls_manifest_cache.get(upstream_url)
        if cached and cached[0] > now:
            rewritten = cached[1]
        else:
            try:
                resp = await _hls_relay_client.get(upstream_url, headers=HLS_RELAY_UPSTREAM_HEADERS)
            except httpx.HTTPError as e:
                raise HTTPException(502, f"hls_relay: upstream fetch failed - {e}")
            # אם המקור לא החזיר manifest תקין (שגיאה, redirect שלא נופה, דף
            # HTML כלשהו) - חשוב לעצור כאן. אחרת שכתוב-שורה-שורה "יצליח" גם
            # על HTML ומחזיר ללקוח playlist שבור בלי שום שגיאה ברורה.
            if resp.status_code != 200 or not resp.text.lstrip().startswith("#EXTM3U"):
                raise HTTPException(
                    502, f"hls_relay: upstream did not return a valid m3u8 "
                         f"(status {resp.status_code})")
            rewritten = _rewrite_hls_manifest(resp.text, upstream_url)
            _hls_manifest_cache[upstream_url] = (now + MANIFEST_CACHE_TTL, rewritten)
            # מדליקים משיכה מקדימה של המקטעים החדשים בעוד הנגן מעכל את ה-manifest
            _prefetch_from_manifest(resp.text, upstream_url)
        return Response(
            content=rewritten,
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-cache", **CORS_MEDIA},
        )

    # מקטעי וידאו (.ts) - מוזרם (streaming) לצופה שביקש ראשון, כדי שיתחיל
    # לקבל בייטים ברגע שהם מגיעים מהמקור בלי לחכות למקטע השלם. אם מגיעה
    # בקשה מקבילה לאותו מקטע בדיוק (כמה צופים על אותו ערוץ) - היא "מצטרפת"
    # לזרימה הקיימת במקום לפתוח עוד בקשה זהה למקור.
    async def _proxy_segment():
        # אם המשיכה המקדימה כבר הביאה את המקטע — מגישים אותו מיד, בלי לגעת
        # בספק בכלל. זה מה שמוציא את ההמתנה לספק מהנתיב הקריטי.
        hit = _hls_seg_cache.get(upstream_url)
        if hit and hit[0] > time.time():
            yield hit[1]
            return

        existing = _hls_segment_inflight.get(upstream_url)
        if existing is not None:
            chunks, done_event = existing
            idx = 0
            while True:
                while idx < len(chunks):
                    yield chunks[idx]
                    idx += 1
                if done_event.is_set():
                    return
                await asyncio.sleep(0.05)

        chunks = []
        done_event = asyncio.Event()
        _hls_segment_inflight[upstream_url] = (chunks, done_event)
        try:
            async with _hls_relay_client.stream("GET", upstream_url, headers=HLS_RELAY_UPSTREAM_HEADERS) as resp:
                if resp.status_code != 200:
                    log.error("hls_relay: segment upstream returned %s for %s",
                              resp.status_code, upstream_url)
                    return
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    yield chunk
            # שומרים גם מקטע שנמשך רגיל: צופה נוסף שיגיע רגע אחריו (וכל
            # ניסיון חוזר של אותו נגן) יקבל אותו מיידית במקום למשוך שוב.
            if chunks:
                _hls_seg_cache[upstream_url] = (
                    time.time() + HLS_SEG_TTL, b"".join(chunks))
                _seg_cache_evict()
        except httpx.HTTPError as e:
            log.error("hls_relay: segment stream failed - %s", e)
        finally:
            done_event.set()
            _hls_segment_inflight.pop(upstream_url, None)

    return StreamingResponse(
        _proxy_segment(),
        media_type="video/mp2t",
        headers={"Cache-Control": "public, max-age=86400", **CORS_MEDIA},
    )

# ── Ping & Dashboard ──────────────────────────────────────────────────────────

@api.get("/ping")
async def ping():
    stats["last_ping"] = datetime.utcnow().isoformat()
    return JSONResponse({"status": "ok"})

# ── מיגרציה לערוץ (דרך הבוט הראשי — יש לו את כל ה-peers בזיכרון) ─────────────
# מריצים דרך הבוט הרץ (bot_client) כי ה-session הקבוע שלו כבר מכיר גם את
# הצ'אטים המקוריים (הקבצים הישנים) וגם את הערוץ. copy_message מעביר את הקובץ
# עצמו בלי הורדה מחדש. checkpoint לחידוש, טיפול ב-FloodWait.
MIGRATION_PROGRESS_FILE = DATA_DIR / "migration_progress.json"
MIGRATION_OUT_FILE = DATA_DIR / "movies_migrated.json"
MOVIES_SRC_URL = "https://raw.githubusercontent.com/davidggjg/zovex/main/public/movies.json"
_OLD_URL_RE = re.compile(r"https?://[^/]*hf\.space/stream/(-?\d+)/(\d+)")
_migration = {"running": False, "migrated": 0, "failed": 0, "skipped": 0,
              "total": 0, "done": False, "error": None, "last": ""}

def _load_mig_progress():
    if MIGRATION_PROGRESS_FILE.exists():
        try:
            return json.loads(MIGRATION_PROGRESS_FILE.read_text())
        except Exception:
            return {}
    return {}

async def _run_migration(limit: int, new_base: str):
    import urllib.request
    try:
        _migration.update(running=True, done=False, error=None,
                          migrated=0, failed=0, skipped=0, total=0, last="")
        channel = STREAM_CHANNEL_ID
        if not channel:
            _migration.update(error="STREAM_CHANNEL_ID לא מוגדר", running=False, done=True)
            return
        # ודא שהבוט הראשי מזהה את הערוץ
        try:
            await bot_client.get_chat(channel)
        except Exception as e:
            _migration.update(error=f"הבוט הראשי לא מזהה את הערוץ ({e}). הוסף את Davidvvggbot כאדמין ושלח הודעה בערוץ.",
                              running=False, done=True)
            return
        data = json.loads(urllib.request.urlopen(MOVIES_SRC_URL, timeout=60).read().decode())
        progress = _load_mig_progress()
        _migration["total"] = len(data)
        for entry in data:
            url = entry.get("video_url") or entry.get("video_id") or ""
            m = _OLD_URL_RE.search(url)
            if not m:
                continue
            old_chat, old_msg = int(m.group(1)), int(m.group(2))
            key = f"{old_chat}:{old_msg}"
            if key in progress:
                new_id = progress[key]
                _migration["skipped"] += 1
            else:
                if limit and _migration["migrated"] >= limit:
                    continue
                try:
                    res = await bot_client.copy_message(
                        chat_id=channel, from_chat_id=old_chat, message_id=old_msg)
                    new_id = res.id
                    progress[key] = new_id
                    _migration["migrated"] += 1
                    _migration["last"] = f"{key} -> {new_id}"
                    if _migration["migrated"] % 20 == 0:
                        MIGRATION_PROGRESS_FILE.write_text(json.dumps(progress, ensure_ascii=False))
                    await asyncio.sleep(0.7)
                except FloodWait as e:
                    MIGRATION_PROGRESS_FILE.write_text(json.dumps(progress, ensure_ascii=False))
                    await asyncio.sleep(e.value + 1)
                    try:
                        res = await bot_client.copy_message(
                            chat_id=channel, from_chat_id=old_chat, message_id=old_msg)
                        new_id = res.id
                        progress[key] = new_id
                        _migration["migrated"] += 1
                    except Exception:
                        _migration["failed"] += 1
                        continue
                except Exception:
                    _migration["failed"] += 1
                    continue
            new_url = f"{new_base}/stream/{channel}/{new_id}"
            entry["video_url"] = new_url
            entry["video_id"] = new_url
        MIGRATION_PROGRESS_FILE.write_text(json.dumps(progress, ensure_ascii=False))
        MIGRATION_OUT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        _migration.update(running=False, done=True)
        log.info("✅ מיגרציה הושלמה: %d הועברו, %d נכשלו", _migration["migrated"], _migration["failed"])
    except Exception as e:
        log.exception("migration failed")
        _migration.update(error=repr(e), running=False, done=True)

@api.get("/admin/migrate")
async def admin_migrate(request: Request, limit: int = 0, base: str = "http://213.139.78.39"):
    # מותר רק מ-localhost (הרצה מהשרת עצמו)
    if not is_local_request(request):
        raise HTTPException(status_code=403, detail="localhost only")
    if _migration["running"]:
        return JSONResponse({"status": "כבר רץ", **_migration})
    asyncio.create_task(_run_migration(limit, base))
    return JSONResponse({"status": "התחיל", "limit": limit, "base": base})

@api.get("/admin/migrate/status")
async def admin_migrate_status(request: Request):
    if not is_local_request(request):
        raise HTTPException(status_code=403, detail="localhost only")
    return JSONResponse(dict(_migration))

# ── Whitelist מנהלים + פאנל ניהול מאובטח ─────────────────────────────────────
# הבעלים מנהל רשימת Telegram-ID של המנהלים המורשים. רק הם יקבלו מענה מבוט
# ההעלאה. הרשימה נשמרת בשרת (admins.json), ונערכת דרך פאנל אינטרנטי מוגן
# בסיסמה (PANEL_PASSWORD ב-.env).
ADMINS_FILE = DATA_DIR / "admins.json"
PANEL_PASSWORD = os.environ.get("PANEL_PASSWORD", "").strip()

# ── הגנת brute-force על סיסמת הפאנל ─────────────────────────────────────────
# בלי זה אפשר לנחש את הסיסמה באלפי ניסיונות. אחרי כמה כישלונות מ-IP מסוים —
# חוסמים אותו לזמן קצוב. ההשוואה עצמה ב-hmac.compare_digest (זמן קבוע) כדי
# למנוע דליפת מידע דרך תזמון.
_auth_fails: dict = {}          # ip -> [timestamps של כישלונות]
AUTH_MAX_FAILS = 6              # כישלונות מותרים
AUTH_WINDOW = 300              # בחלון של 5 דקות
AUTH_LOCK = 900               # ואז חסימה של 15 דקות

def _client_ip(request: Request) -> str:
    # קריטי לאבטחה: מאחורי nginx (פרוקסי יחיד) יש לקחת את ה-hop *האחרון*
    # ב-X-Forwarded-For — זה שה-nginx הוסיף ($proxy_add_x_forwarded_for),
    # והוא ה-IP האמיתי של הלקוח. הגרסה הקודמת לקחה את ה-hop הראשון, שאותו
    # הלקוח שולט בו לגמרי — כך שאפשר היה לזייף אותו בכל בקשה ולעקוף את חסימת
    # ה-brute-force על סיסמת הפאנל. X-Real-IP (אם nginx מגדיר) עדיף כי הוא
    # תמיד ה-IP האמיתי; נופלים אחורה ל-hop האחרון, ואז ל-socket.
    real = request.headers.get("x-real-ip", "").strip()
    if real:
        return real
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"

# ── שתי רמות גישה ────────────────────────────────────────────────────────────
# הסיסמה הראשית = אדמין, גישה מלאה. סיסמת העורך פותחת פאנל מוגבל: מוסיף תוכן
# ומוחק מעט, ולא יכול לגעת בשידורים חיים ולא למחוק בכמות. האכיפה כאן בשרת
# ולא בממשק — הסתרת כפתורים לא שווה כלום מול בקשה ישירה.
EDITOR_PASSWORD = os.environ.get("EDITOR_PASSWORD", "")
EDITOR_MAX_DELETE = int(os.environ.get("EDITOR_MAX_DELETE", "5"))

def panel_role(request: Request, password: str) -> str:
    """מאמת סיסמה ומחזיר 'admin' או 'editor'. זורק HTTPException אם נכשל/חסום."""
    ip = _client_ip(request)
    now = time.time()
    fails = [t for t in _auth_fails.get(ip, []) if now - t < AUTH_LOCK]
    # אם יש יותר מדי כישלונות בחלון האחרון — חסום
    recent = [t for t in fails if now - t < AUTH_WINDOW]
    if len(recent) >= AUTH_MAX_FAILS:
        _auth_fails[ip] = fails
        raise HTTPException(status_code=429, detail="יותר מדי ניסיונות — נסה שוב בעוד כמה דקות")
    pw = password or ""
    role = None
    # השוואה על bytes ולא על str: hmac.compare_digest על מחרוזת עם תווים
    # לא-ASCII (סיסמה בעברית וכו') זורק TypeError ומפיל את ה-handler במקום
    # להחזיר "שגוי" — מה שהחזיר תשובה ריקה לכל בקשה עם סיסמה כזו.
    pw_b = pw.encode("utf-8", "surrogatepass")
    if PANEL_PASSWORD and hmac.compare_digest(pw_b, PANEL_PASSWORD.encode("utf-8", "surrogatepass")):
        role = "admin"
    elif EDITOR_PASSWORD and hmac.compare_digest(pw_b, EDITOR_PASSWORD.encode("utf-8", "surrogatepass")):
        role = "editor"
    if role is None:
        fails.append(now)
        _auth_fails[ip] = fails
        raise HTTPException(status_code=401, detail="סיסמה שגויה")
    # הצלחה — נקה כישלונות קודמים מאותו IP
    _auth_fails.pop(ip, None)
    return role


def check_panel_password(request: Request, password: str):
    """גישת אדמין בלבד. כל מסך ניהול קיים ממשיך לדרוש את הסיסמה הראשית —
    עורך שינסה להגיע לשם יקבל 403, גם אם הסיסמה שלו תקפה."""
    if panel_role(request, password) != "admin":
        raise HTTPException(status_code=403, detail="הפעולה הזו מותרת למנהל הראשי בלבד")

def load_admins() -> list:
    if ADMINS_FILE.exists():
        try:
            return json.loads(ADMINS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def save_admins(lst: list):
    ADMINS_FILE.write_text(json.dumps(lst, ensure_ascii=False, indent=2), encoding="utf-8")

def is_admin_id(uid) -> bool:
    try:
        uid = int(uid)
    except Exception:
        return False
    return any(int(a.get("id", 0)) == uid for a in load_admins())

class PanelReq(BaseModel):
    password: str
    action: str
    id: Optional[int] = None
    name: Optional[str] = ""

@api.post("/panel/api")
async def panel_api(req: PanelReq, request: Request):
    check_panel_password(request, req.password)
    admins = load_admins()
    if req.action == "list":
        return {"admins": admins}
    if req.action == "add":
        if req.id is None:
            raise HTTPException(400, "חסר id")
        if not any(int(a["id"]) == int(req.id) for a in admins):
            admins.append({"id": int(req.id), "name": req.name or ""})
            save_admins(admins)
        return {"admins": admins}
    if req.action == "remove":
        admins = [a for a in admins if int(a["id"]) != int(req.id)]
        save_admins(admins)
        return {"admins": admins}
    raise HTTPException(400, "פעולה לא מוכרת")

@api.get("/panel", response_class=HTMLResponse)
async def panel_page():
    return HTMLResponse(PANEL_HTML)

# אתר הניהול המלא (תוכן + מנהלים + העלאות) — מוגש מקובץ admin.html שליד main.py.
# הגשה מהשרת עצמו פותרת את בעיית ה-HTTPS↔HTTP: הדף מדבר עם /panel/api ו-/uploads
# ב-same-origin, ועם GitHub/TMDB ב-HTTPS.
ADMIN_HTML_FILE = Path(__file__).parent / "admin.html"

@api.get("/admin", response_class=HTMLResponse)
async def admin_page():
    if ADMIN_HTML_FILE.exists():
        return HTMLResponse(ADMIN_HTML_FILE.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>admin.html לא נמצא בשרת</h1>"
                        "<p>העלה את הקובץ ל-" + str(ADMIN_HTML_FILE) + "</p>",
                        status_code=404)

PANEL_HTML = """<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ZOVEX · ניהול מנהלים</title>
<style>
  * { box-sizing: border-box; }
  body { margin:0; font-family:'Segoe UI',Arial,sans-serif; background:#0a0a0a; color:#eee; }
  .wrap { max-width:520px; margin:0 auto; padding:24px 16px; }
  h1 { color:#e50914; letter-spacing:3px; font-size:24px; }
  .card { background:#161616; border:1px solid #262626; border-radius:14px; padding:18px; margin-bottom:16px; }
  input { width:100%; padding:12px 14px; border-radius:10px; border:1px solid #333; background:#0f0f0f; color:#fff; font-size:15px; margin-bottom:10px; }
  button { background:#e50914; color:#fff; border:none; border-radius:10px; padding:12px 16px; font-size:15px; font-weight:700; cursor:pointer; width:100%; }
  button.sec { background:#2a2a2a; }
  .row { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:12px; border-bottom:1px solid #222; }
  .row:last-child { border-bottom:none; }
  .row .info { text-align:right; }
  .row .id { color:#888; font-size:12px; font-family:monospace; direction:ltr; }
  .rm { background:#3a1414; color:#ff6b6b; width:auto; padding:8px 12px; font-size:13px; }
  .hide { display:none; }
  .err { color:#ff6b6b; font-size:13px; margin-top:6px; }
  .muted { color:#888; font-size:13px; line-height:1.6; }
</style></head><body><div class="wrap">
  <h1>ZOVEX · ניהול מנהלים</h1>

  <div id="login" class="card">
    <div class="muted">הזן את סיסמת הפאנל כדי לנהל את רשימת המנהלים המורשים.</div>
    <br><input id="pw" type="password" placeholder="סיסמת פאנל" onkeydown="if(event.key==='Enter')doLogin()">
    <button onclick="doLogin()">כניסה</button>
    <div id="loginErr" class="err"></div>
  </div>

  <div id="app" class="hide">
    <div class="card">
      <div class="muted">הוסף מנהל לפי <b>Telegram ID</b> (מספרי). רק מנהלים ברשימה יקבלו מענה מבוט ההעלאה.<br>
      טיפ: כדי לדעת את ה-ID של מישהו, שלח לבוט <b>@userinfobot</b> בטלגרם.</div>
      <br>
      <input id="tid" type="number" placeholder="Telegram ID (למשל 123456789)">
      <input id="tname" type="text" placeholder="שם (לזיהוי, לא חובה)">
      <button onclick="addAdmin()">➕ הוסף מנהל</button>
      <div id="addErr" class="err"></div>
    </div>
    <div class="card">
      <div class="muted">מנהלים מורשים:</div>
      <div id="list"></div>
    </div>
  </div>

<script>
let PW = "";
async function api(action, extra={}) {
  const r = await fetch("/panel/api", { method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({ password: PW, action, ...extra }) });
  if (!r.ok) throw new Error((await r.json().catch(()=>({}))).detail || "שגיאה");
  return r.json();
}
async function doLogin() {
  PW = document.getElementById("pw").value;
  try { const d = await api("list"); showApp(d.admins); }
  catch(e){ document.getElementById("loginErr").textContent = e.message; }
}
function showApp(admins) {
  document.getElementById("login").classList.add("hide");
  document.getElementById("app").classList.remove("hide");
  render(admins);
}
function render(admins) {
  const el = document.getElementById("list");
  if (!admins.length) { el.innerHTML = '<div class="muted" style="padding:12px">אין מנהלים עדיין.</div>'; return; }
  el.innerHTML = admins.map(a => `<div class="row">
    <button class="rm" onclick="removeAdmin(${a.id})">הסר</button>
    <div class="info"><div>${a.name||"—"}</div><div class="id">${a.id}</div></div>
  </div>`).join("");
}
async function addAdmin() {
  const id = document.getElementById("tid").value;
  const name = document.getElementById("tname").value;
  if (!id) { document.getElementById("addErr").textContent = "חסר Telegram ID"; return; }
  try { const d = await api("add", { id: parseInt(id), name });
    document.getElementById("tid").value=""; document.getElementById("tname").value="";
    document.getElementById("addErr").textContent=""; render(d.admins); }
  catch(e){ document.getElementById("addErr").textContent = e.message; }
}
async function removeAdmin(id) {
  try { const d = await api("remove", { id }); render(d.admins); } catch(e){ alert(e.message); }
}
</script></div></body></html>"""

# ── בוט העלאה (טוקן נפרד) + זיהוי TMDB ───────────────────────────────────────
# בוט נפרד לגמרי (טוקן משלו) שמקבל קבצים מצוות המנהלים (רק Telegram-ID מורשים
# מ-admins.json). הזרימה: מנהל שולח סרט לבוט → הבוט מעתיק אותו לערוץ התוכן
# (copy_message, בלי הורדה מחדש) → מחפש ב-TMDB לפי שם הקובץ → מציג כפתורים עם
# הצעות (שם+שנה, כי כמה סרטים חולקים שם) → המנהל בוחר → הבוט בונה כניסת סרט,
# מוסיף ל-new_uploads.json ומחזיר קישור סטרימינג. מנהלים לא מקבלים גישה לשרת.
UPLOAD_BOT_TOKEN = os.environ.get("UPLOAD_BOT_TOKEN", "").strip()
TMDB_API_KEY     = os.environ.get("TMDB_API_KEY", "").strip()
STREAM_PUBLIC_BASE = os.environ.get("STREAM_PUBLIC_BASE", BASE_URL).rstrip("/")
NEW_UPLOADS_FILE = DATA_DIR / "new_uploads.json"
TMDB_IMG = "https://image.tmdb.org/t/p/w500"

# ── קישורים ניידים (portable) — לא שומרים את הכתובת בתוך הקישור ────────────────
# הקישורים שלנו נשמרים עם מציין-מקום %BASE% במקום הכתובת (IP/דומיין). השרת
# מזריק את הכתובת האמיתית (STREAM_PUBLIC_BASE) רק בזמן ההגשה (/content), ומכווץ
# בחזרה ל-%BASE% בזמן השמירה. כך, כשמגיע דומיין — משנים משתנה אחד ב-.env
# (STREAM_PUBLIC_BASE) והכל מתעדכן, בלי לשכתב אף קישור.
BASE_TOKEN = "%BASE%"

def stored_stream_url(msg_id, chat_id=None) -> str:
    return f"{BASE_TOKEN}/stream/{chat_id or STREAM_CHANNEL_ID}/{msg_id}"

def expand_base(s):
    return s.replace(BASE_TOKEN, STREAM_PUBLIC_BASE) if isinstance(s, str) else s

# ── קישורים חתומים שפגים (הגנת תוכן) ─────────────────────────────────────────
# כל קישור /stream שמוגש ללקוח מקבל חתימה (HMAC) ותוקף. השרת מאמת אותם ב-/stream
# ודוחה קישור שפג או עם חתימה שגויה. כך קישור שנחלץ (למשל ממכשיר עם רוט) מת
# תוך שעות, אי-אפשר לשתף אותו או לבנות עליו הורדה המונית. שקוף ללקוח — האתר
# והאפליקציה פשוט מקבלים קישור חתום מ-/content ומנגנים.
import hashlib
SIGN_SECRET_FILE = DATA_DIR / "sign_secret.txt"
def _load_or_create_sign_secret() -> str:
    env = os.environ.get("STREAM_SIGN_SECRET", "").strip()
    if env:
        return env
    if SIGN_SECRET_FILE.exists():
        return SIGN_SECRET_FILE.read_text().strip()
    secret = os.urandom(24).hex()
    try:
        SIGN_SECRET_FILE.write_text(secret)
    except Exception:
        pass
    return secret
SIGN_SECRET = _load_or_create_sign_secret()
# 24 שעות. 6 שעות הספיקו לסרט בודד, אבל לא לטאב/אפליקציה שנשארים פתוחים
# ליום שלם — ואז החתימה פגה מתחת לידיים והנגן קיבל 403. יחד עם רענון הקטלוג
# לפי SIG_EPOCH_WINDOW, לקוח מקבל קישורים טריים הרבה לפני שהישנים פגים.
SIGN_TTL = int(os.environ.get("STREAM_SIGN_TTL", "86400"))
_STREAM_PATH_RE = re.compile(r"/stream/(-?\d+)/(\d+)")

def _stream_sig(chat: str, msg: str, exp: int) -> str:
    data = f"{chat}/{msg}/{exp}".encode()
    return hmac.new(SIGN_SECRET.encode(), data, hashlib.sha256).hexdigest()[:32]

def sign_stream_url(url):
    """מוסיף ?exp=&sig= לקישור /stream. משאיר קישורים אחרים כמו שהם."""
    if not isinstance(url, str) or not SIGN_SECRET:
        return url
    m = _STREAM_PATH_RE.search(url)
    if not m or "sig=" in url:
        return url
    exp = int(time.time()) + SIGN_TTL
    sig = _stream_sig(m.group(1), m.group(2), exp)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}exp={exp}&sig={sig}"

def _expand_urls(items: list) -> list:
    for e in items:
        for k in ("video_url", "video_id"):
            v = e.get(k)
            if isinstance(v, str) and BASE_TOKEN in v:
                e[k] = sign_stream_url(v.replace(BASE_TOKEN, STREAM_PUBLIC_BASE))
    return items

def _collapse_urls(items: list) -> list:
    for e in items:
        for k in ("video_url", "video_id"):
            v = e.get(k)
            if isinstance(v, str) and STREAM_PUBLIC_BASE and STREAM_PUBLIC_BASE in v:
                v = v.replace(STREAM_PUBLIC_BASE, BASE_TOKEN)
                # מסירים חתימה/תוקף אם דבקו בקישור (הם מתווספים מחדש בכל הגשה)
                if "/stream/" in v:
                    v = re.sub(r"[?&](exp|sig)=[^&]*", "", v)
                e[k] = v
    return items

upload_bot: Optional[Client] = None
# _pending_uploads: message_id-בערוץ (str) → {"channel_msg_id","chat_id","user_id","fname","options":[...]}
_pending_uploads: dict = {}

def load_new_uploads() -> list:
    if NEW_UPLOADS_FILE.exists():
        try:
            return json.loads(NEW_UPLOADS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def save_new_uploads(lst: list):
    NEW_UPLOADS_FILE.write_text(json.dumps(lst, ensure_ascii=False, indent=2), encoding="utf-8")

# תגיות איכות/מקור/קודק/קבוצות-שחרור שכיחות — יש להסיר משם הקובץ לפני חיפוש TMDB
_JUNK_TAGS = re.compile(
    r"\b(?:1080p|720p|2160p|480p|360p|4k|uhd|fhd|hd|sd|"
    r"x264|x265|h\.?264|h\.?265|hevc|avc|xvid|divx|"
    r"bluray|blu[- ]?ray|brrip|bdrip|webrip|web[- ]?dl|web|hdrip|dvdrip|dvd|hdtv|cam|ts|tc|"
    r"aac|ac3|eac3|dts(?:[- ]?hd)?|ddp?5[.\s]?1|dd5[.\s]?1|dd\+?|truehd|opus|flac|mp3|2ch|6ch|"
    r"10bit|8bit|hdr10?|sdr|dolby|atmos|vision|"
    r"hebdub|hebsub|hebrew|engsub|eng|dubbed|subbed|multi|dual|"
    r"proper|repack|internal|limited|extended|unrated|uncut|remastered|complete|"
    r"amzn|nf|dsnp|hulu|hmax|atvp|itunes|pcok|"
    r"yts|yify|rarbg|evo|fgt|ettv|ctrlhd|ntb|galaxytv|galaxyrg|psa|tgx|mkvcage)\b",
    re.I)
# סימוני עונה/פרק להסרה לפני חיפוש שם הסרט/סדרה
_EP_MARKERS = re.compile(
    r"\bS\s*\d{1,2}\s*E\s*\d{1,3}\b|\b\d{1,2}\s*[xX]\s*\d{1,3}\b|"
    r"ע(?:ונה)?\s*\d{1,2}\s*[·.\-]?\s*פ(?:רק)?\s*\d{1,3}|"
    r"(?:^|\s)פרק\s*\d{1,3}|(?:^|\s)עונה\s*\d{1,2}",
    re.I)

def clean_name(fname: str) -> str:
    """מנקה שם קובץ לשם חיפוש: מוריד סיומת, סוגריים, תגיות איכות/קודק/קבוצה,
    סימוני עונה/פרק ומילות מקור — כדי שיישאר שם נקי לחיפוש ב-TMDB."""
    n = fname or ""
    n = re.sub(r"\.(mkv|mp4|avi|mov|webm|m4v|ts|wmv|flv)$", "", n, flags=re.I)
    # מסירים תוכן בסוגריים מרובעים [group] וגם עברית "מדובב/מתורגם" שדבקה
    n = re.sub(r"\[[^\]]*\]", " ", n)
    n = re.sub(r"[‎‏‪-‮]", "", n)   # תווי כיווניות נסתרים
    n = n.replace(".", " ").replace("_", " ").replace("-", " ")
    n = re.sub(r"[\|/\\]", " ", n)
    n = _SOURCE_TAGS.sub("", n).strip()                # תגית מקור בתחילת השם
    n = re.sub(r"\b(?:מדובב|מתורגם|לצפייה ישירה|צפייה ישירה)\b", " ", n)
    n = _EP_MARKERS.sub(" ", n)                          # סימוני עונה/פרק
    n = _JUNK_TAGS.sub(" ", n)                           # תגיות איכות/מקור/קבוצה
    n = re.sub(r"\(\s*\)|\[\s*\]", " ", n)               # סוגריים ריקים שנשארו
    n = re.sub(r"\s+", " ", n).strip(" -–—·.")
    return n

def _query_candidates(fname: str) -> list:
    """בונה רשימת מועמדים לחיפוש TMDB לפי סדר עדיפות, לטיפול בשמות מעורבים
    עברית+אנגלית. מנסים כל אחד עד שמתקבלות תוצאות:
      1) השם הנקי המלא   2) קטע לטיני בלבד   3) קטע עברי בלבד
      4) השם בלי שנה בסוף. מסננים כפילויות ומחרוזות קצרות מדי."""
    base = clean_name(fname)
    cands = [base]
    # קטע לטיני רציף (מילים באנגלית/ספרות) — עדיף ל-TMDB (בסיס נתונים אנגלי).
    # חייב להכיל אות אמיתית (לא רק ספרות/שנה) כדי לא לחפש "2022" לבד.
    latin = " ".join(re.findall(r"[A-Za-z0-9][A-Za-z0-9'&:!]*", base)).strip()
    if latin and re.search(r"[A-Za-z]", latin) and latin.lower() != base.lower():
        cands.append(latin)
    # קטע עברי רציף
    heb = " ".join(re.findall(r"[א-ת][א-ת'\"״׳]*", base)).strip()
    if heb and heb != base:
        cands.append(heb)
    # בלי שנה בסוף (למשל "Dune 2021" → "Dune")
    noyear = re.sub(r"\b(19|20)\d{2}\b\s*$", "", base).strip()
    if noyear and noyear != base:
        cands.append(noyear)
    out, seen = [], set()
    for c in cands:
        c = c.strip()
        k = c.lower()
        if len(c) >= 2 and not re.fullmatch(r"\d{2,4}", c) and k not in seen:
            seen.add(k); out.append(c)
    return out

async def smart_tmdb_search(fname: str):
    """מחפש ב-TMDB לפי כמה מועמדים (עברית/אנגלית/מלא) עד שמתקבלות תוצאות.
    מחזיר (query_used, options)."""
    last_q = clean_name(fname)
    for q in _query_candidates(fname):
        opts = await tmdb_search(q)
        if opts:
            return q, opts
        last_q = q
    return last_q, []

# ── זיהוי מתוך כיתוב (caption) של קבצי מאגר — שם עברי+אנגלי+שנה בשורות נפרדות ──
_TRAILER_RE = re.compile(r'טריילר|טרילר|trailer|טיזר|teaser|קדימון', re.I)
_YEAR_RE = re.compile(r'(?<!\d)(19\d{2}|20[0-3]\d)(?!\d)')
# שורות מטא-דאטה בכיתוב שאינן חלק מהשם (עוצרים לפניהן)
_CAP_NOISE = re.compile(r'(איכות|ז[\'׳"]?אנר|סוגה|תרגום|תקציר|הועלה|בלעדי|מנויים|'
                        r'צפיות|שיתוף|קרדיט|quality|genre|subtitle)', re.I)

def _recognition_candidates(caption: str, fname: str):
    """מחזיר (candidates, year, is_trailer) לזיהוי מדויק. מעדיף את שורות הכותרת
    שבכיתוב (שם עברי/אנגלי+שנה) על פני שם הקובץ (שלרוב פחות אמין)."""
    caption = caption or ""
    is_trailer = bool(_TRAILER_RE.search(caption))
    m = _YEAR_RE.search(caption) or _YEAR_RE.search(fname or "")
    year = m.group(1) if m else ""
    # שורות כותרת: מתחילת הכיתוב עד השורה הראשונה שהיא מטא-דאטה (עד 2 שורות)
    title_lines = []
    for line in caption.splitlines():
        line = line.strip()
        if not line:
            continue
        if _CAP_NOISE.search(line):
            break
        title_lines.append(line)
        if len(title_lines) >= 2:
            break
    cands = []
    for src in title_lines + [fname or ""]:
        for c in _query_candidates(src):
            if c not in cands:
                cands.append(c)
    return cands, year, is_trailer

async def recognize_media(caption: str, fname: str):
    """זיהוי TMDB מתוך כיתוב+שם קובץ, עם שנה. מחזיר (options, year, is_trailer)."""
    cands, year, is_trailer = _recognition_candidates(caption, fname)
    for q in cands:
        opts = await tmdb_search(q, year)
        if opts:
            return opts, year, is_trailer
    return [], year, is_trailer

async def tmdb_search(query: str, year: str = "") -> list:
    """מחזיר עד 6 תוצאות TMDB (movie/tv). לכל תוצאה: שם עברי לתצוגה (title),
    שם אנגלי (en_title) לקישור נקי, שנה, פוסטר, סוג. תמיד מושך גם עברית וגם
    אנגלית כדי שגם לתוכן עברי יהיה שם אנגלי לכתובת (slug). אם ניתנה שנה —
    תוצאות עם אותה שנה מדורגות ראשונות (דיוק גבוה יותר)."""
    if not TMDB_API_KEY or not query:
        return []
    he_out, en_out, en_map = [], [], {}
    try:
        async with httpx.AsyncClient(timeout=12) as cx:
            for lang in ("he", "en-US"):
                r = await cx.get("https://api.themoviedb.org/3/search/multi",
                                 params={"api_key": TMDB_API_KEY, "query": query,
                                         "language": lang, "include_adult": "false"})
                if r.status_code != 200:
                    continue
                for it in r.json().get("results", []):
                    mt = it.get("media_type")
                    if mt not in ("movie", "tv"):
                        continue
                    title = it.get("title") or it.get("name") or ""
                    orig = it.get("original_title") or it.get("original_name") or ""
                    tid = it.get("id")
                    if not tid:
                        continue
                    if lang == "en-US":
                        # מפת שם אנגלי לכל פריט (לפי מזהה+סוג) — משמש ל-slug
                        en_map[(tid, mt)] = title or orig
                    bucket = en_out if lang == "en-US" else he_out
                    if not title or any(o["tmdb_id"] == tid and o["type"] == mt for o in bucket):
                        continue
                    date = it.get("release_date") or it.get("first_air_date") or ""
                    bucket.append({
                        "tmdb_id": tid, "type": mt, "title": title, "year": (date or "")[:4],
                        "poster": (TMDB_IMG + it["poster_path"]) if it.get("poster_path") else "",
                        "overview": (it.get("overview") or "")[:300],
                        "original": orig,
                        # מטא לזיהוי קטגוריה אוטומטי (ז'אנר/מוצא/שפה)
                        "genre_ids": it.get("genre_ids") or [],
                        "origin": it.get("origin_country") or [],
                        "lang": (it.get("original_language") or "").lower(),
                    })
    except Exception as e:
        log.warning("tmdb_search נכשל: %s", e)
    out = he_out or en_out          # עברית עדיפה לתצוגה; אם אין — אנגלית
    for o in out:                    # מצמידים שם אנגלי לכל תוצאה (לקישור)
        o["en_title"] = en_map.get((o["tmdb_id"], o["type"])) or o.get("original") or o["title"]
    if year:                         # דירוג לפי התאמת שנה (±1 שנה = קרוב)
        def _yr_rank(o):
            oy = o.get("year") or ""
            if oy == year: return 0
            try:
                return 1 if abs(int(oy) - int(year)) <= 1 else 2
            except Exception:
                return 3
        out.sort(key=_yr_rank)
    return out[:6]

# ── זיהוי קטגוריה אוטומטי מ-TMDB (ז'אנר/מוצא/שפה) ────────────────────────────
# מ-genre_ids של TMDB: 16=אנימציה, 27=אימה, 10751=משפחה, 10762=ילדים (טלוויזיה).
# מוצא/שפה: JP/ja=יפני (אנימה), IL/he=ישראלי. מיפוי לקטגוריות האתר. הבחירה
# היא "ניחוש טוב" — המשתמש עובר על זה אחר כך ומתקן במידת הצורך.
def _auto_category(item: dict) -> str:
    g = set(item.get("genre_ids") or [])
    origin = {str(x).upper() for x in (item.get("origin") or [])}
    lang = (item.get("lang") or "").lower()
    is_tv = item.get("type") == "tv"
    is_anim = 16 in g
    is_jp = ("JP" in origin) or (lang == "ja")
    is_il = ("IL" in origin) or (lang == "he")
    if is_tv:
        if is_anim and is_jp:
            return "אנימה"
        if is_il:
            return "סדרות ישראליות"
        if 27 in g:                       # ז'אנר אימה → קטגוריית אימה (גם לסדרות)
            return "אימה"
        # רק תיוג מפורש של ילדים/משפחה → סדרות לילדים (אנימציה למבוגרים כמו
        # ריק ומורטי לא מתויגת ככה ולכן נשארת ב'סדרות')
        if (10762 in g) or (10751 in g):
            return "סדרות לילדים"
        return "סדרות"
    # סרט
    if is_anim and is_jp:
        return "אנימה"
    if 27 in g:
        return "אימה"
    if is_anim or (10751 in g):
        return "סרטים לילדים (מתאים גם למשפחה)"
    return "סרטים"

# ── תעתיק עברית→לטינית (גיבוי ל-slug כשאין שם אנגלי ב-TMDB, למשל תוכן ישראלי) ──
_HE_TRANSLIT = {
    "א": "", "ב": "b", "ג": "g", "ד": "d", "ה": "h", "ו": "v", "ז": "z", "ח": "ch",
    "ט": "t", "י": "y", "כ": "k", "ך": "k", "ל": "l", "מ": "m", "ם": "m", "נ": "n",
    "ן": "n", "ס": "s", "ע": "", "פ": "p", "ף": "p", "צ": "tz", "ץ": "tz", "ק": "k",
    "ר": "r", "ש": "sh", "ת": "t",
}
def _translit_he(s: str) -> str:
    return "".join(_HE_TRANSLIT.get(c, c) for c in (s or ""))

def _slug_base(title: str) -> str:
    """בסיס slug לטיני נקי משם. אם השם עברי — מתעתק אותו קודם."""
    latin = re.sub(r"[a-zA-Z0-9]", "", title or "")  # יש בו תווים לא-לטיניים?
    src = _translit_he(title) if latin.strip() and re.search(r"[א-ת]", title or "") else (title or "")
    return re.sub(r"[^a-zA-Z0-9]+", "-", src).strip("-").lower()

def _slugify(title: str, tmdb_id) -> str:
    return (_slug_base(title) or "movie") + "-" + str(tmdb_id)

def _custom_slug(en_title: str, he_title: str, tmdb_id) -> str:
    """slug נקי לכתובת: מעדיף שם אנגלי; נופל לתעתיק עברי; ואז ל-tmdb id.
    בלי סיומת מספר כברירת מחדל (כתובת יפה: /us). הייחודיות נאכפת ב-add_movie_entry
    (מוסיף סיומת רק אם יש התנגשות)."""
    base = _slug_base(en_title) or _slug_base(he_title)
    if base:
        return base
    return f"movie-{tmdb_id}" if tmdb_id else ""

def _all_entries() -> list:
    """כל הכניסות לבדיקת כפילויות — גם התוכן החי (content.json) וגם ההעלאות
    הממתינות (new_uploads.json). ככה קובץ שכבר קיים באתר לא יתווסף שוב."""
    try:
        return load_content() + load_new_uploads()
    except Exception:
        return load_new_uploads()

def _norm_title(s: str) -> str:
    """נרמול שם להשוואה: אותיות קטנות, בלי ניקוד עברי, בלי גרשיים/פיסוק/שנה/
    רווחים כפולים — כדי ש'אָס' == 'אס' ו'שם 2022' == 'שם'."""
    s = (s or "").lower()
    s = re.sub(r"[֑-ׇ]", "", s)          # ניקוד/טעמים עבריים
    s = re.sub(r"\b(19|20)\d{2}\b", " ", s)         # שנה בתוך השם
    s = re.sub(r"[\"'`׳״’‘“”\-–—_.,:!?()\[\]]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def _norm_series(name: str) -> str:
    """שם סדרה מנורמל להשוואה — כולל כינויים (תאג''ד→תאגד)."""
    return _norm_title(_series_alias(name or ""))

def find_upload_by_fuid(fuid: str):
    """מחזיר כניסה קיימת (בתוכן או בהעלאות) עם אותו file_unique_id, או None."""
    if not fuid:
        return None
    for e in _all_entries():
        if e.get("file_unique_id") and e["file_unique_id"] == fuid:
            return e
    return None

def find_existing_movie(tmdb_id, title: str = "", year: str = ""):
    """מחזיר סרט קיים (בתוכן/בהעלאות) לפי tmdb_id, ואם אין — לפי שם+שנה מנורמלים.
    מונע כפילות של אותו סרט שהועלה שוב (גם באיכות אחרת)."""
    nt, yr = _norm_title(title), str(year or "").strip()
    for e in _all_entries():
        if e.get("series_name") or e.get("episode_number") is not None:
            continue  # פרק סדרה — לא סרט
        if tmdb_id and e.get("tmdb_id") and int(e["tmdb_id"]) == int(tmdb_id):
            return e
        if nt and _norm_title(e.get("title") or e.get("en_title") or "") == nt:
            ey = str(e.get("year") or "").strip()
            if not yr or not ey or yr == ey:
                return e
    return None

def find_existing_episode(series: str, season, episode):
    """מחזיר פרק קיים (בתוכן/בהעלאות) עם אותה סדרה (מנורמלת)+עונה+פרק, או None.
    זו ההגנה מפני 'אותו פרק פעמיים' שגרמה לכפילויות בעבר."""
    ns = _norm_series(series)
    try:
        se, ep = int(season), int(episode)
    except Exception:
        return None
    for e in _all_entries():
        sn = e.get("series_name")
        if not sn or e.get("episode_number") is None:
            continue
        if _norm_series(sn) != ns:
            continue
        try:
            if int(e.get("season_number") or 1) == se and int(e["episode_number"]) == ep:
                return e
        except Exception:
            continue
    return None

def add_movie_entry(chosen: dict, channel_msg_id: int, file_unique_id: str = "", chat_id=None,
                    category: str = None, to_content: bool = False) -> dict:
    """בונה כניסת סרט חדשה מהבחירה ב-TMDB + הקישור לערוץ.
    to_content=False → שומר ל-new_uploads.json (ממתין לאישור).
    to_content=True  → מוסיף ישירות ל-content.json (עולה לאתר) עם category.
    שומר קישור נייד (%BASE%) — הכתובת האמיתית מוזרקת בזמן ההגשה/התצוגה.
    chat_id = הערוץ שאליו הועתק הקובץ (לתמיכה בריבוי ערוצים)."""
    chat_id = chat_id or STREAM_CHANNEL_ID
    stream_url = stored_stream_url(channel_msg_id, chat_id)
    en_title = chosen.get("en_title") or chosen.get("original") or chosen["title"]
    entry = {
        "id": _slugify(en_title, chosen["tmdb_id"]) + "-" + str(channel_msg_id),
        "title": chosen["title"],
        # custom_slug — כתובת נקייה באנגלית (מ-TMDB) במקום עברית מקודדת בכתובת
        "custom_slug": _custom_slug(en_title, chosen["title"], chosen["tmdb_id"]),
        "en_title": en_title,
        "year": chosen["year"],
        "type": "telegram",
        "media_kind": chosen["type"],           # movie / tv
        "tmdb_id": chosen["tmdb_id"],
        "video_url": stream_url,
        "thumbnail_url": chosen.get("poster", ""),
        "description": chosen.get("overview", ""),
        "channel_id": chat_id,
        "channel_msg_id": channel_msg_id,
        "file_unique_id": file_unique_id,
        "added_at": datetime.utcnow().isoformat(),
        # created_date (UTC עם Z) — כדי שהפריט יופיע בבאנר "עלה עכשיו" באתר/אפליקציה
        "created_date": datetime.utcnow().isoformat() + "Z",
    }
    if category:
        entry["category"] = category
    lst = load_content() if to_content else load_new_uploads()
    # מניעת כפילות — לפי (ערוץ+מזהה הודעה) וגם לפי הקובץ עצמו (file_unique_id)
    lst = [e for e in lst if not (e.get("channel_msg_id") == channel_msg_id and (e.get("channel_id") or STREAM_CHANNEL_ID) == chat_id)
           and not (file_unique_id and e.get("file_unique_id") == file_unique_id)]
    # ייחודיות ה-slug הנקי: אם שם אנגלי זהה כבר תפוס ע"י סרט אחר — מוסיפים סיומת
    # (קודם מזהה TMDB, אחרת מספר ההודעה) כדי ששתי כתובות לא יתנגשו.
    want = entry.get("custom_slug")
    if want:
        used = {e.get("custom_slug") for e in (lst + (load_new_uploads() if to_content else load_content())) if e.get("custom_slug")}
        if want in used:
            entry["custom_slug"] = f"{want}-{chosen.get('tmdb_id') or channel_msg_id}"
    lst.append(entry)
    (save_content if to_content else save_new_uploads)(lst)
    return entry

# ── זיהוי פרק סדרה משם הקובץ (להעלאה מרובה) ─────────────────────────────────
# תומך: S01E05 / 1x05 / "עונה 1 פרק 5" / "ע4 פ7" / "פרק 5". שם הסדרה = מה שלפני הסימון.
_EP_PATTERNS = [
    re.compile(r'\bS\s*0*(\d{1,2})\s*E\s*0*(\d{1,3})\b', re.I),   # S01E05
    re.compile(r'\b(\d{1,2})\s*[xX]\s*0*(\d{1,3})\b'),            # 1x05
]
# עונה+פרק בעברית, כולל קיצורים: "עונה 4 פרק 7" / "ע4 פ7" / "ע 4 פ 7"
_HE_SEASON_EP = re.compile(r'ע(?:ונה)?\s*0*(\d{1,2})\s*[·.\-]?\s*פ(?:רק)?\s*0*(\d{1,3})')
# פרק בלבד (עונה תיקבע ל-1). "פ" חייב לבוא בתחילת מילה כדי לא לתפוס אמצע מילה.
_HE_EP_ONLY = re.compile(r'(?:^|\s)פ(?:רק)?\s*0*(\d{1,3})')
_HE_SEASON_ONLY = re.compile(r'(?:^|\s)ע(?:ונה)?\s*0*(\d{1,2})')
# תגיות מקור/ערוץ נפוצות שמופיעות בתחילת שם הקובץ ולא שייכות לשם הסדרה
# תגיות מקור/ערוצים/מעלים שמופיעות בתחילת השם ולא שייכות לשם הסדרה. מוסר
# חזרה על עצמו (תג + אימוג'י + hashtag) עד שנשאר רק השם. פותר פיצול סדרה לכמה
# חלקים בגלל שמות מקור שונים ("חננאל סרטים", "נטפליקס Kids", "השימיה"...).
_SOURCE_TAGS = re.compile(
    r'^(?:(?:'
    r'זירה\s*מדיה|נתי\s*מדיה|נתי\s*מידע|zira\s*media|zira|nati\s*media|'
    r'חננאל(?:\s*סרטים|\s*ס)?|דב\s*סרטים|השימיה|לולו(?:\s*סרטים)?|'
    r'נטפליקס(?:\s*kids)?|netflix(?:\s*kids)?|'
    r'בנק(?:\s*סרטים(?:\s*וסדרות)?)?|כל\s*הסדרות(?:\s*בחיפוש)?|israellasry\w*|'
    r'#\S+|[\U0001F000-\U0001FAFF☀-➿✅❗]+'
    r')[\s\-:·|]*)+', re.I)

# ── כינויי סדרות: שם שמזוהה מהקובץ → שם קנוני באתר. פותר מקרים שבהם שם הקובץ
# מכיל ראשי-תיבות/גרשיים (למשל "תאג''ד") אבל הסדרה באתר נקראת "תאגד". קובץ
# series_aliases.json ניתן לעריכה בשרת להוספת כינויים נוספים בעתיד.
SERIES_ALIASES_FILE = DATA_DIR / "series_aliases.json"
def _norm_alias(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()
def _load_series_aliases() -> dict:
    default = {"תאג''ד": "תאגד", 'תאג"ד': "תאגד", "תאג״ד": "תאגד", "תאג׳׳ד": "תאגד",
               "taagad": "תאגד"}
    if SERIES_ALIASES_FILE.exists():
        try:
            default.update(json.loads(SERIES_ALIASES_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    else:
        try:
            SERIES_ALIASES_FILE.write_text(
                json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return {_norm_alias(k): v for k, v in default.items()}
SERIES_ALIASES = _load_series_aliases()
def _series_alias(name: str) -> str:
    return SERIES_ALIASES.get(_norm_alias(name), name)

def parse_episode_info(fname: str):
    if not fname:
        return None
    n = re.sub(r'\.(mkv|mp4|avi|mov|webm|m4v|ts|wmv|flv)$', '', fname, flags=re.I)
    n = n.replace('.', ' ').replace('_', ' ').replace('-', ' ')
    season = episode = None
    cut = None
    for pat in _EP_PATTERNS:                       # S01E05 / 1x05
        m = pat.search(n)
        if m:
            season, episode, cut = int(m.group(1)), int(m.group(2)), m.start()
            break
    if episode is None:                            # עברית משולב: עונה+פרק / ע4 פ7
        m = _HE_SEASON_EP.search(n)
        if m:
            season, episode, cut = int(m.group(1)), int(m.group(2)), m.start()
    if episode is None:                            # פרק בלבד (+ עונה נפרדת אם יש)
        me = _HE_EP_ONLY.search(n)
        if me:
            episode = int(me.group(1))
            ms = _HE_SEASON_ONLY.search(n)
            season = int(ms.group(1)) if ms else 1
            cut = min(x.start() for x in (ms, me) if x)
    if episode is None:
        return None
    series = clean_name(n[:cut]).strip() if cut else ""
    if not series:
        series = clean_name(n)
    series = _SOURCE_TAGS.sub("", series).strip()  # מסיר תגית מקור מתחילת השם
    series = _series_alias(series)                  # מנרמל כינויים (תאג''ד → תאגד)
    return {"series": series or "סדרה", "season": season or 1, "episode": episode}

def add_episode_entry(ep: dict, channel_msg_id: int, file_unique_id: str = "", chat_id=None,
                      category: str = "סדרות", meta: dict = None, to_content: bool = False) -> dict:
    """מוסיף פרק סדרה. to_content=False → new_uploads (ממתין); True → content (עולה
    לאתר). meta (אופציונלי, מ-TMDB של הסדרה): poster/overview/tmdb_id/en_title/slug
    — משמש כשמעלים ישירות לאתר עם קטגוריה אמיתית.
    chat_id = הערוץ שאליו הועתק הקובץ (לתמיכה בריבוי ערוצים)."""
    chat_id = chat_id or STREAM_CHANNEL_ID
    meta = meta or {}
    slug = meta.get("custom_slug") or (_slug_base(ep["series"]) or None)
    entry = {
        "id": _slugify(ep["series"], "ep") + f"-s{ep['season']}e{ep['episode']}-{channel_msg_id}",
        "title": ep["series"],
        # slug נקי לכתובת הסדרה (תעתיק אם השם עברי) — כל הפרקים חולקים אותו
        "custom_slug": slug,
        "series_name": ep["series"],
        "season_number": ep["season"],
        "episode_number": ep["episode"],
        "episode_title": "",
        "year": "",
        "category": category,
        "type": "telegram",
        "media_kind": "tv",
        "tmdb_id": meta.get("tmdb_id", 0),
        "en_title": meta.get("en_title", ""),
        "video_url": stored_stream_url(channel_msg_id, chat_id),
        "thumbnail_url": meta.get("poster", ""),
        "description": meta.get("overview", ""),
        "channel_id": chat_id,
        "channel_msg_id": channel_msg_id,
        "file_unique_id": file_unique_id,
        "added_at": datetime.utcnow().isoformat(),
        # created_date (UTC עם Z) — כדי שהפריט יופיע בבאנר "עלה עכשיו" באתר/אפליקציה
        "created_date": datetime.utcnow().isoformat() + "Z",
    }
    lst = load_content() if to_content else load_new_uploads()
    lst = [e for e in lst if not (e.get("channel_msg_id") == channel_msg_id and (e.get("channel_id") or STREAM_CHANNEL_ID) == chat_id)
           and not (file_unique_id and e.get("file_unique_id") == file_unique_id)]
    lst.append(entry)
    (save_content if to_content else save_new_uploads)(lst)
    return entry

async def _upload_noop(client, message):
    pass  # שומר את ה-peer של הערוץ ב-cache (כמו ב-pool)

# _awaiting_name: user_id (int) → cmid (str) — מנהל שלחץ "שם אחר" וממתינים
# שיקליד שם ידני בהודעת טקסט הבאה.
_awaiting_name: dict = {}

# נעילה שמעבירה קבצים לערוץ אחד-אחרי-השני (העלאה מרובה בלי FloodWait)
_upload_lock = asyncio.Lock()

def _options_keyboard(cmid, options, raw_name=""):
    """בונה מקלדת: הצעות TMDB + שמירה בשם הגולמי + שם ידני + ביטול."""
    rows = []
    for i, o in enumerate(options):
        label = f"{o['title']} ({o['year'] or '?'}) · {'סדרה' if o['type']=='tv' else 'סרט'}"
        rows.append([InlineKeyboardButton(label, callback_data=f"sel:{cmid}:{i}")])
    if raw_name:
        rows.append([InlineKeyboardButton(f"💾 שמור בשם «{raw_name[:28]}»",
                                          callback_data=f"sel:{cmid}:save")])
    rows.append([InlineKeyboardButton("✏️ שם אחר (הקלד ידני)", callback_data=f"sel:{cmid}:name")])
    rows.append([InlineKeyboardButton("❌ ביטול", callback_data=f"sel:{cmid}:x")])
    return InlineKeyboardMarkup(rows)

async def _handle_custom_name(client: Client, message: Message, uid: int):
    """מנהל הקליד שם ידני אחרי שלחץ 'שם אחר'. מחפשים שוב ב-TMDB לפי השם הזה."""
    cmid = _awaiting_name.pop(uid, None)
    pending = _pending_uploads.get(cmid) if cmid else None
    if not pending:
        await message.reply_text("פג תוקף. שלח שוב את הקובץ.")
        return
    name = (message.text or "").strip()
    if not name:
        _awaiting_name[uid] = cmid  # עדיין מחכים
        await message.reply_text("לא קלטתי שם. הקלד את השם ושלח שוב.")
        return
    pending["raw_name"] = name
    options = await tmdb_search(name)
    if not options:
        # אין זיהוי — שומרים בשם המדויק שהוקלד
        entry = add_movie_entry(
            {"title": name, "year": "", "tmdb_id": 0, "type": "movie",
             "poster": "", "overview": ""}, pending["channel_msg_id"],
            pending.get("file_unique_id", ""), pending.get("dest_channel"))
        _pending_uploads.pop(cmid, None)
        await message.reply_text(
            f"✅ נשמר בשם: <b>{name}</b>\n\n🔗 קישור סטרימינג:\n{sign_stream_url(expand_base(entry['video_url']))}")
        return
    pending["options"] = options
    await message.reply_text(
        f"🎬 לפי «{name}» מצאתי — איזו זו?",
        reply_markup=_options_keyboard(cmid, options, name))

async def on_upload(client: Client, message: Message):
    """מנהל שלח קובץ/וידאו לבוט ההעלאה (או טקסט — לזרימת שם ידני)."""
    uid = message.from_user.id if message.from_user else 0
    if not is_admin_id(uid):
        # לא מורשה — לא עונים כלל (הבעלים ביקש: מי שלא ברשימה, הבוט לא יענה לו)
        log.info("upload_bot: התעלמות מ-uid לא-מורשה %s", uid)
        return
    media = message.video or message.document or message.audio
    if not media:
        # אולי זה שם ידני שממתינים לו
        if uid in _awaiting_name:
            await _handle_custom_name(client, message, uid)
            return
        await message.reply_text("שלח לי קובץ סרט/פרק (וידאו או מסמך) ואני אזהה אותו.")
        return
    # מניעת כפילויות — אותו קובץ בדיוק שכבר הועלה? מחזירים את הקישור הקיים בלי
    # להעלות שוב לערוץ.
    fuid = getattr(media, "file_unique_id", "") or ""
    dup = find_upload_by_fuid(fuid)
    if dup:
        await message.reply_text(
            f"♻️ הקובץ הזה כבר קיים במערכת:\n<b>{dup.get('title','—')}</b>"
            f" ({dup.get('year') or '?'})\n\n🔗 קישור סטרימינג:\n{sign_stream_url(expand_base(dup['video_url']))}",
            quote=True)
        return
    # quote=True → התגובה "מצטטת" את הודעת הקובץ. לחיצה עליה קופצת ישר לקובץ,
    # כך שרואים בדיוק לאיזה קובץ כל תגובה שייכת (חשוב בהעלאה מרובה).
    status = await message.reply_text("⏳ מעלה לערוץ...", quote=True)
    # תור: מעבירים קובץ-קובץ (לא כולם בבת אחת) + retry עם המתנה על FloodWait,
    # כדי שהעלאה מרובה לא תיחסם ע"י טלגרם (420 FLOOD_WAIT).
    channel_msg_id = None
    dest_channel = current_upload_channel()      # הערוץ הפעיל (גלישה אוטומטית כשמתמלא)
    async with _upload_lock:
        for attempt in range(6):
            try:
                copied = await client.copy_message(
                    chat_id=dest_channel,
                    from_chat_id=message.chat.id,
                    message_id=message.id,
                )
                channel_msg_id = copied.id
                note_uploaded_msg_id(dest_channel, channel_msg_id)
                break
            except FloodWait as e:
                wait = int(getattr(e, "value", 30)) + 2
                log.warning("upload_bot: FloodWait %ss (ניסיון %d)", wait, attempt + 1)
                try:
                    await status.edit_text(
                        f"⏳ טלגרם ביקש להמתין {wait} שניות (העלאה מהירה מדי) — "
                        f"ממתין ומנסה שוב אוטומטית, אל תשלח שוב.")
                except Exception:
                    pass
                await asyncio.sleep(wait)
            except Exception as e:
                log.warning("upload_bot: copy_message נכשל: %s", e)
                await status.edit_text(f"❌ ההעלאה לערוץ נכשלה: {e}\n"
                                       f"ודא שבוט ההעלאה הוא אדמין בערוץ.")
                return
        else:
            await status.edit_text("❌ נכשל אחרי כמה ניסיונות (FloodWait). נסה שוב בעוד דקה.")
            return
        # הפוגה קצרה בזמן שהתור נעול — מרווח בין העלאות רצופות שמקטין FloodWait
        await asyncio.sleep(1.5)
    fname = getattr(media, "file_name", None) or (message.caption or "") or ""
    # אם שם הקובץ מכיל סימון פרק (S01E05 / עונה X פרק Y / 1x05) — הוספה אוטומטית
    # כפרק סדרה, בלי TMDB אינטראקטיבי. מתאים להעלאה מרובה (עד 20 קבצים ברצף).
    ep = parse_episode_info(fname)
    if ep:
        # מניעת כפילות פרק: אותה סדרה+עונה+פרק כבר קיימים (בתוכן או בהעלאות)?
        exist = find_existing_episode(ep["series"], ep["season"], ep["episode"])
        if exist:
            add_episode_entry(ep, channel_msg_id, fuid, dest_channel)  # עדיין שומרים ליתר ביטחון
            await status.edit_text(
                f"⚠️ הפרק הזה כבר קיים: <b>{exist.get('series_name', ep['series'])}</b> — "
                f"עונה {ep['season']} פרק {ep['episode']}.\n"
                f"נוסף לרשימת ההעלאות אבל כנראה כפול — בדוק בפאנל לפני אישור.")
            return
        add_episode_entry(ep, channel_msg_id, fuid, dest_channel)
        await status.edit_text(
            f"✅ פרק נוסף: <b>{ep['series']}</b> — עונה {ep['season']} פרק {ep['episode']}\n"
            f"אשר בפאנל («הוסף הכל») והוסף פוסטר לסדרה.")
        return
    await status.edit_text(f"✅ הועלה לערוץ.\n🔎 מחפש ב-TMDB: <b>{clean_name(fname) or '—'}</b>...")
    query, options = await smart_tmdb_search(fname)
    _pending_uploads[str(channel_msg_id)] = {
        "channel_msg_id": channel_msg_id, "chat_id": message.chat.id,
        "dest_channel": dest_channel,
        "user_id": uid, "fname": fname, "options": options,
        "raw_name": query or fname, "file_unique_id": fuid,
    }
    if not options:
        # אין זיהוי אוטומטי — נותנים לבחור: שמור בשם הגולמי או הקלד שם ידני
        await status.edit_text(
            f"⚠️ לא זיהיתי אוטומטית «{query or fname}».\n"
            f"אפשר לשמור בשם הזה, או להקליד שם אחר לחיפוש:",
            reply_markup=_options_keyboard(channel_msg_id, [], query or fname))
        return
    await status.edit_text(
        "🎬 מצאתי כמה התאמות — איזו זו? (או 'שם אחר' אם אף אחת לא נכונה)",
        reply_markup=_options_keyboard(channel_msg_id, options, query))

async def on_select(client: Client, cq: CallbackQuery):
    """מנהל בחר התאמה מ-TMDB / ביקש לשמור בשם גולמי / ביקש להקליד שם ידני."""
    uid = cq.from_user.id if cq.from_user else 0
    if not is_admin_id(uid):
        await cq.answer("לא מורשה", show_alert=True)
        return
    try:
        _, cmid, idx = cq.data.split(":", 2)
    except Exception:
        await cq.answer(); return
    pending = _pending_uploads.get(cmid)
    if not pending:
        await cq.answer("פג תוקף — שלח שוב את הקובץ", show_alert=True)
        return
    if idx == "x":
        _pending_uploads.pop(cmid, None)
        _awaiting_name.pop(uid, None)
        await cq.message.edit_text("בוטל. הקובץ נשאר בערוץ אבל לא נוסף לאתר.")
        await cq.answer()
        return
    if idx == "name":
        _awaiting_name[uid] = cmid
        await cq.message.edit_text("✏️ הקלד את השם המדויק ושלח — אחפש שוב ב-TMDB לפיו.")
        await cq.answer()
        return
    if idx == "save":
        raw = pending.get("raw_name") or f"קובץ {pending['channel_msg_id']}"
        entry = add_movie_entry(
            {"title": raw, "year": "", "tmdb_id": 0, "type": "movie",
             "poster": "", "overview": ""}, pending["channel_msg_id"],
            pending.get("file_unique_id", ""), pending.get("dest_channel"))
        _pending_uploads.pop(cmid, None)
        await cq.message.edit_text(
            f"✅ נשמר בשם: <b>{raw}</b>\n\n🔗 קישור סטרימינג:\n{sign_stream_url(expand_base(entry['video_url']))}")
        await cq.answer("נשמר!")
        return
    try:
        chosen = pending["options"][int(idx)]
    except Exception:
        await cq.answer("בחירה לא תקינה", show_alert=True); return
    # מניעת כפילות: הסרט הזה כבר קיים באתר (לפי TMDB id או שם+שנה)?
    if chosen.get("type") == "movie":
        dup = find_existing_movie(chosen.get("tmdb_id"), chosen.get("title"), chosen.get("year"))
        if dup:
            _pending_uploads.pop(cmid, None)
            await cq.message.edit_text(
                f"♻️ «{chosen['title']}» ({chosen.get('year') or '?'}) כבר קיים באתר — "
                f"לא הוספתי כפילות.\nהקובץ נשאר בערוץ. אם בכל זאת תרצה גרסה נוספת, "
                f"הוסף אותה ידנית בפאנל.")
            await cq.answer("כבר קיים")
            return
    entry = add_movie_entry(chosen, pending["channel_msg_id"],
                            pending.get("file_unique_id", ""), pending.get("dest_channel"))
    _pending_uploads.pop(cmid, None)
    poster_line = f"\n🖼 {entry['thumbnail_url']}" if entry["thumbnail_url"] else ""
    await cq.message.edit_text(
        f"✅ נוסף: <b>{entry['title']}</b> ({entry['year'] or '?'})"
        f"{poster_line}\n\n🔗 קישור סטרימינג:\n{sign_stream_url(expand_base(entry['video_url']))}")
    await cq.answer("נוסף!")

async def start_upload_bot():
    global upload_bot
    if not UPLOAD_BOT_TOKEN:
        log.info("אין UPLOAD_BOT_TOKEN — בוט העלאה לא פעיל")
        return
    try:
        upload_bot = Client("upload_bot", api_id=API_ID, api_hash=API_HASH,
                            bot_token=UPLOAD_BOT_TOKEN, in_memory=False,
                            no_updates=False, workdir=str(DATA_DIR))
        upload_bot.add_handler(MessageHandler(
            on_upload, filters.private & (filters.video | filters.document | filters.audio)))
        upload_bot.add_handler(MessageHandler(on_upload, filters.private & filters.text))
        upload_bot.add_handler(CallbackQueryHandler(on_select, filters.regex(r"^sel:")))
        upload_bot.add_handler(MessageHandler(_upload_noop, filters.channel))
        await asyncio.wait_for(upload_bot.start(), timeout=40)
        if STREAM_CHANNEL_ID:
            try:
                await upload_bot.get_chat(STREAM_CHANNEL_ID)
            except Exception:
                pass  # יזוהה כשיגיע פוסט חדש לערוץ
        log.info("✅ בוט העלאה עלה")
    except Exception as e:
        log.warning("⚠️ בוט העלאה לא עלה: %s", e)
        upload_bot = None

async def stop_upload_bot():
    global upload_bot
    if upload_bot:
        try:
            await upload_bot.stop()
        except Exception:
            pass
        upload_bot = None

# מגישים את הכניסות שנוספו דרך בוט ההעלאה — האתר/מנהל יכולים למשוך אותן ולמזג
# ל-movies.json כשמעדכנים. (רק קריאה; אין כאן חשיפת טוקנים.)
@api.get("/uploads/new")
async def uploads_new():
    # מציגים רק העלאות שעדיין לא נמצאות באתר. אם פריט כבר נוסף ל-content
    # (לפי מזהה ההודעה בערוץ שבקישור) — מסירים אותו אוטומטית מהרשימה (self-heal),
    # כך שהרשימה תמיד משקפת רק את מה שבאמת ממתין.
    items = load_new_uploads()
    present = set()
    for e in load_content():
        u = e.get("video_url") or e.get("video_id") or ""
        m = re.search(r"/stream/-?\d+/(\d+)", u)
        if m:
            present.add(int(m.group(1)))
    pending = [it for it in items if it.get("channel_msg_id") not in present]
    if len(pending) != len(items):
        save_new_uploads(pending)
    return {"count": len(pending), "items": _expand_urls(pending)}

class UploadsClearReq(BaseModel):
    password: str
    channel_msg_ids: list = []

@api.post("/uploads/clear")
async def uploads_clear(req: UploadsClearReq, request: Request):
    """מסיר העלאות שכבר אושרו ונכנסו לאתר (לפי channel_msg_id). ריק = מנקה הכל."""
    check_panel_password(request, req.password)
    if req.channel_msg_ids:
        ids = set(req.channel_msg_ids)
        lst = [e for e in load_new_uploads() if e.get("channel_msg_id") not in ids]
    else:
        lst = []
    save_new_uploads(lst)
    return {"ok": True, "remaining": len(lst)}

class UploadsMergeReq(BaseModel):
    password: str
    series_name: str
    category: str = "סדרות"

@api.post("/uploads/merge")
async def uploads_merge(req: UploadsMergeReq, request: Request):
    """מאחד את *כל* הפרקים הממתינים לסדרה אחת (שם+קטגוריה+slug אחידים) ומוסיף
    אותם לאתר. פותר את הפיצול לכמה סדרות בגלל תגיות מקור/שגיאות כתיב. סרטים
    (בלי מספר פרק) נשארים בממתינים."""
    check_panel_password(request, req.password)
    name = (req.series_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="חסר שם סדרה")
    slug = _slug_base(name) or None
    ups = load_new_uploads()
    content = load_content()
    poster = next((e.get("thumbnail_url") for e in ups if e.get("thumbnail_url")), "")
    merged, remaining = 0, []
    for e in ups:
        is_ep = (e.get("episode_number") is not None) or (e.get("season_number") is not None) or bool(e.get("series_name"))
        if is_ep:
            x = dict(e)
            x["series_name"] = name
            x["title"] = name
            x["custom_slug"] = slug
            x["category"] = req.category
            x["media_kind"] = "tv"
            if poster and not x.get("thumbnail_url"):
                x["thumbnail_url"] = poster
            content.append(x)
            merged += 1
        else:
            remaining.append(e)
    save_content(content)
    save_new_uploads(remaining)
    return {"ok": True, "merged": merged, "series": name, "remaining": len(remaining)}

# ── מערכת תמיכה/משוב: משתמשים כותבים, המנהל רואה בפאנל ומגיב ──────────────────
# feedback.json: { user_id: {user_id,name,email,fcm_token,messages:[{from,text,ts,kind}],
#                            updated, unread_admin, unread_user} }
FEEDBACK_FILE = DATA_DIR / "feedback.json"

def load_feedback() -> dict:
    if FEEDBACK_FILE.exists():
        try:
            return json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_feedback(d: dict):
    FEEDBACK_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

class FeedbackSendReq(BaseModel):
    user_id: str
    name: Optional[str] = ""
    email: Optional[str] = ""
    text: str
    kind: Optional[str] = "support"   # support / review / tip
    fcm_token: Optional[str] = ""

@api.post("/feedback/send")
async def feedback_send(req: FeedbackSendReq):
    text = (req.text or "").strip()
    if not req.user_id or not text:
        raise HTTPException(status_code=400, detail="חסר משתמש או טקסט")
    d = load_feedback()
    th = d.get(req.user_id) or {"user_id": req.user_id, "messages": []}
    if req.name:  th["name"] = req.name
    if req.email: th["email"] = req.email
    if req.fcm_token: th["fcm_token"] = req.fcm_token
    th["messages"].append({"from": "user", "text": text[:4000],
                           "ts": datetime.utcnow().isoformat(), "kind": req.kind or "support"})
    th["updated"] = datetime.utcnow().isoformat()
    th["unread_admin"] = True
    d[req.user_id] = th
    save_feedback(d)
    return {"ok": True}

@api.get("/feedback/mine")
async def feedback_mine(user_id: str):
    d = load_feedback()
    th = d.get(user_id)
    if not th:
        return {"user_id": user_id, "messages": [], "unread_user": False}
    if th.get("unread_user"):
        th["unread_user"] = False
        save_feedback(d)   # סימון כנקרא כשהמשתמש פותח את הצ'אט
    # מחזירים רק את מה שה-UID של המשתמש עצמו צריך. הנקודה הזו לא מאומתת
    # (הזהות היא user_id שהלקוח שולח), ולכן אסור להחזיר ממנה שם/אימייל/טוקן
    # התראות — אלה נשמרים לצד השרת בלבד, לשימוש המנהל והדחיפות.
    return {
        "user_id": user_id,
        "messages": th.get("messages", []),
        "unread_user": False,
    }

class FeedbackReplyReq(BaseModel):
    password: str
    user_id: str
    text: str

@api.post("/feedback/reply")
async def feedback_reply(req: FeedbackReplyReq, request: Request):
    check_panel_password(request, req.password)
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="חסר טקסט")
    d = load_feedback()
    th = d.get(req.user_id)
    if not th:
        raise HTTPException(status_code=404, detail="לא נמצא")
    th["messages"].append({"from": "admin", "text": text[:4000],
                           "ts": datetime.utcnow().isoformat()})
    th["updated"] = datetime.utcnow().isoformat()
    th["unread_user"] = True
    th["unread_admin"] = False
    save_feedback(d)
    asyncio.create_task(send_reply_push(th, text))   # התראה (אם יש טוקן+FCM)
    return {"ok": True}

class FeedbackListReq(BaseModel):
    password: str

@api.post("/feedback/all")
async def feedback_all(req: FeedbackListReq, request: Request):
    check_panel_password(request, req.password)
    d = load_feedback()
    threads = sorted(d.values(), key=lambda t: t.get("updated", ""), reverse=True)
    unread = sum(1 for t in threads if t.get("unread_admin"))
    return {"threads": threads, "unread": unread}

# ── סטטיסטיקות צפייה לפאנל ───────────────────────────────────────────────────
# בלי איסוף נתונים חדש ובלי עומס: מחשבים הכל מ-history.json שכבר נשמר ממילא
# (לכל צפייה יש media_id + watched_at). כדי שרענון הפאנל לא יקרא ויפרסר את
# הקובץ שוב ושוב — התוצאה נשמרת במטמון ומחושבת מחדש רק אם הקובץ השתנה או
# שעברו 60 שניות. כך גם אם פותחים את הפאנל הרבה, השרת כמעט לא מרגיש.
#
# הערה חשובה לפרשנות: נספרות רק צפיות של משתמשים *מחוברים* (יש user_id),
# ובהיסטוריה נשמרת רשומה אחת לכל סרט למשתמש (צפייה חוזרת מעדכנת תאריך).
_stats_cache = {"mtime": None, "built": 0.0, "data": None}
STATS_TTL = 60

class StatsReq(BaseModel):
    password: str

def _build_stats() -> dict:
    hist = load_json(HISTORY_FILE)
    now = time.time()
    day = 86400
    # גבול "היום" = חצות מקומית, כדי שהמספר יתאים למה שמנהל מצפה לראות
    lt = time.localtime(now)
    midnight = now - (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec)

    users_today, users_week = set(), set()
    views_today = views_week = 0
    top_today, top_week = {}, {}
    per_day = {}

    for uid, items in (hist.items() if isinstance(hist, dict) else []):
        if not isinstance(items, list):
            continue
        for it in items:
            ts = it.get("watched_at") or 0
            if not ts:
                continue
            title = (it.get("title") or "").strip() or "(ללא שם)"
            if ts >= midnight:
                users_today.add(uid); views_today += 1
                top_today[title] = top_today.get(title, 0) + 1
            if now - ts <= 7 * day:
                users_week.add(uid); views_week += 1
                top_week[title] = top_week.get(title, 0) + 1
                d = time.strftime("%Y-%m-%d", time.localtime(ts))
                per_day[d] = per_day.get(d, 0) + 1

    def top(dct, n=15):
        return [{"title": k, "views": v}
                for k, v in sorted(dct.items(), key=lambda kv: -kv[1])[:n]]

    return {
        "today":  {"viewers": len(users_today), "views": views_today},
        "week":   {"viewers": len(users_week),  "views": views_week},
        "total_users": len(hist) if isinstance(hist, dict) else 0,
        "top_today": top(top_today),
        "top_week": top(top_week),
        "per_day": [{"date": d, "views": per_day[d]} for d in sorted(per_day)],
        "generated": int(now),
    }

# הנתיב תחת /api בכוונה: nginx מעביר לשרת רק קידומות מסוימות (/api, /app,
# /panel, /feedback, /pool…). נתיב /stats חדש לא היה מועבר והוחזר 405 מ-nginx.
@api.post("/api/stats/summary")
async def stats_summary(req: StatsReq, request: Request):
    check_panel_password(request, req.password)
    try:
        mtime = HISTORY_FILE.stat().st_mtime if HISTORY_FILE.exists() else 0
    except Exception:
        mtime = 0
    c = _stats_cache
    if (c["data"] is not None and c["mtime"] == mtime
            and time.time() - c["built"] < STATS_TTL):
        return {**c["data"], "cached": True}
    data = await asyncio.to_thread(_build_stats)
    _stats_cache.update({"mtime": mtime, "built": time.time(), "data": data})
    return {**data, "cached": False}

async def send_reply_push(thread: dict, text: str):
    """שולח התראת push למשתמש כשהמנהל מגיב. פעיל רק אם הוגדר FCM (מפתח שירות
    Firebase בשרת) ולמשתמש יש fcm_token. אחרת — המשתמש יראה את התשובה בפתיחה."""
    token = thread.get("fcm_token")
    if not token or not _fcm_send:
        return
    try:
        await _fcm_send(token, "תשובה מ-ZOVEX", text[:120])
    except Exception as e:
        log.warning("שליחת push נכשלה: %s", e)

# מוגדר בהמשך אם קיים מפתח Firebase; אחרת נשאר None (התראות כבויות, השאר עובד)
_fcm_send = None

# ── גרסת אפליקציה: דיאלוג עדכון מאולץ / מומלץ ────────────────────────────────
# app_version.json: {"latest","min","url","notes"}. האפליקציה מושכת /app/version
# בהפעלה ומשווה ל-versionName שלה: קטן מ-min → חובה לעדכן (חוסם); קטן מ-latest →
# מוצע לעדכן. המנהל מעדכן דרך /app/version/set (סיסמת פאנל).
APP_VERSION_FILE = DATA_DIR / "app_version.json"
APP_UPDATE_URL_DEFAULT = os.environ.get(
    "APP_UPDATE_URL",
    "https://github.com/davidggjg/zovex-android/releases/latest")

def load_app_version() -> dict:
    if APP_VERSION_FILE.exists():
        try:
            return json.loads(APP_VERSION_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"latest": "1.0.0", "min": "1.0.0", "url": APP_UPDATE_URL_DEFAULT, "notes": ""}

@api.get("/app/version")
async def app_version_get():
    """מחזיר את פרטי הגרסה. שדה apk מצביע תמיד על השרת שלנו (/app/apk) כדי
    שהמשתמש לא ייחשף למקור החיצוני שממנו מגיע הקובץ."""
    v = dict(load_app_version())
    v["apk"] = f"{STREAM_PUBLIC_BASE}/app/apk"
    v["url"] = f"{STREAM_PUBLIC_BASE}/app/apk"
    return v

# ── הגשת ה-APK מהשרת שלנו ────────────────────────────────────────────────────
# האפליקציה מורידה את העדכון מ-/app/apk (הדומיין שלנו) ולא ממקור חיצוני. השרת
# מוריד את הקובץ פעם אחת, שומר אותו במטמון על הדיסק, ומגיש אותו מקומית. כך
# הכתובת שהמשתמש רואה היא רק זו של ZOVEX, וגם ההורדה מהירה יותר.
APK_CACHE_FILE = DATA_DIR / "zovex-latest.apk"
APK_SOURCE_URL = os.environ.get(
    "APK_SOURCE_URL",
    "https://github.com/davidggjg/zovex-android/releases/latest/download/zovex.apk")
_apk_lock = asyncio.Lock()

async def _refresh_apk_cache(force: bool = False) -> bool:
    """מוריד את ה-APK העדכני למטמון המקומי. מחזיר True אם יש קובץ תקין."""
    async with _apk_lock:
        # רענון אם אין קובץ, הוא זעיר (הורדה שנכשלה), או שעברו 6 שעות
        fresh = (APK_CACHE_FILE.exists()
                 and APK_CACHE_FILE.stat().st_size > 1_000_000
                 and (time.time() - APK_CACHE_FILE.stat().st_mtime) < 6 * 3600)
        if fresh and not force:
            return True
        tmp = APK_CACHE_FILE.with_suffix(".part")
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=180) as cli:
                async with cli.stream("GET", APK_SOURCE_URL) as r:
                    if r.status_code != 200:
                        raise RuntimeError(f"HTTP {r.status_code}")
                    with tmp.open("wb") as f:
                        async for chunk in r.aiter_bytes(256 * 1024):
                            f.write(chunk)
            if tmp.stat().st_size < 1_000_000:
                raise RuntimeError("קובץ קטן מדי — כנראה לא APK")
            tmp.replace(APK_CACHE_FILE)
            log.info("✅ APK עודכן במטמון (%.1f MB)", APK_CACHE_FILE.stat().st_size / 1e6)
            return True
        except Exception as e:
            log.warning("רענון APK נכשל: %s", e)
            tmp.unlink(missing_ok=True)
            # אם יש עותק ישן תקין — עדיף להגיש אותו מאשר כלום
            return APK_CACHE_FILE.exists() and APK_CACHE_FILE.stat().st_size > 1_000_000

@api.get("/app/apk")
async def app_apk():
    """מגיש את קובץ ההתקנה מהדומיין שלנו (המשתמש לא רואה מקור חיצוני)."""
    if not await _refresh_apk_cache():
        raise HTTPException(status_code=503, detail="קובץ העדכון אינו זמין כרגע")
    size = APK_CACHE_FILE.stat().st_size

    def _gen():
        with APK_CACHE_FILE.open("rb") as f:
            while True:
                b = f.read(256 * 1024)
                if not b:
                    break
                yield b

    return StreamingResponse(
        _gen(),
        media_type="application/vnd.android.package-archive",
        headers={
            "Content-Length": str(size),
            "Content-Disposition": 'attachment; filename="zovex.apk"',
            "Cache-Control": "no-cache",
        })

class ApkRefreshReq(BaseModel):
    password: str

@api.post("/app/apk/refresh")
async def app_apk_refresh(req: ApkRefreshReq, request: Request):
    """מושך מחדש את ה-APK למטמון (אחרי שפרסמנו בנייה חדשה).
    ההורדה (~60MB) ארוכה יותר מזמן ההמתנה של nginx ולכן החזירה 504 — לכן היא
    רצה ברקע והתשובה חוזרת מיד. בודקים את התוצאה עם /app/apk/status."""
    check_panel_password(request, req.password)
    old = APK_CACHE_FILE.stat().st_size if APK_CACHE_FILE.exists() else 0
    asyncio.create_task(_refresh_apk_cache(force=True))
    return {"ok": True, "started": True, "previous_size": old,
            "hint": "ההורדה רצה ברקע — בדוק עם /app/apk/status בעוד ~30 שניות"}

@api.post("/app/apk/status")
async def app_apk_status(req: ApkRefreshReq, request: Request):
    """מצב מטמון ה-APK: גודל וזמן עדכון אחרון."""
    check_panel_password(request, req.password)
    if not APK_CACHE_FILE.exists():
        return {"exists": False}
    st = APK_CACHE_FILE.stat()
    return {"exists": True, "size": st.st_size,
            "size_mb": round(st.st_size / 1e6, 1),
            "age_seconds": int(time.time() - st.st_mtime),
            "updated": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))}

class AppVersionSetReq(BaseModel):
    password: str
    latest: Optional[str] = None
    min: Optional[str] = None
    url: Optional[str] = None
    notes: Optional[str] = None

@api.post("/app/version/set")
async def app_version_set(req: AppVersionSetReq, request: Request):
    check_panel_password(request, req.password)
    v = load_app_version()
    if req.latest is not None: v["latest"] = req.latest.strip()
    if req.min is not None:    v["min"] = req.min.strip()
    if req.url is not None:     v["url"] = req.url.strip() or APP_UPDATE_URL_DEFAULT
    if req.notes is not None:   v["notes"] = req.notes.strip()
    APP_VERSION_FILE.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "version": v}

# ── מאגר התוכן בשרת (content.json) — מקור האמת החדש, מנותק מגיטהאב ──────────────
# פאנל הניהול טוען את כל הספרייה, עורך בזיכרון, ושומר את המערך המלא חזרה (save).
# האתר יוכל בעתיד למשוך מ-/content או /movies.json במקום מגיטהאב.
CONTENT_FILE = DATA_DIR / "content.json"
CONTENT_SEED_URL = os.environ.get(
    "CONTENT_SEED_URL",
    "https://raw.githubusercontent.com/davidggjg/zovex/main/public/movies.json")

def load_content() -> list:
    if CONTENT_FILE.exists():
        try:
            return json.loads(CONTENT_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

CONTENT_BAK_DIR = DATA_DIR / "content_backups"

# ── גרסת תוכן (optimistic lock) ───────────────────────────────────────────────
# מונה שעולה בכל שמירה. הפאנל טוען את הגרסה הנוכחית, ובשמירה שולח אותה בחזרה.
# אם התוכן כבר השתנה בינתיים (מישהו אחר שמר) — הגרסאות לא תואמות והשרת דוחה את
# השמירה במקום לדרוס. כך שני עורכים במקביל לא מוחקים אחד לשני את העבודה.
CONTENT_VERSION_FILE = DATA_DIR / "content_version.txt"

def get_content_version() -> int:
    try:
        return int(CONTENT_VERSION_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return 0

def _bump_content_version() -> int:
    v = get_content_version() + 1
    try:
        CONTENT_VERSION_FILE.write_text(str(v), encoding="utf-8")
    except Exception as e:
        log.warning("עדכון גרסת content נכשל: %s", e)
    return v

LIVE_CATEGORY = "שידורים חיים"

def _normalize_live_flag(arr: list) -> list:
    """כל פריט בקטגוריית השידורים החיים מקבל is_live=True.
    הנגן באתר/אפליקציה מזהה שידור חי לפי הדגל הזה בלבד; בלעדיו הערוץ נופל
    לרשימת הסרטים הרגילה ומוצג לו סרגל התקדמות עם "אורך" אינסופי במקום LIVE.
    כאן, ולא רק בפאנל, כדי שזה יהיה נכון לכל לקוח ששומר תוכן."""
    for e in arr:
        if e.get("category") == LIVE_CATEGORY and e.get("is_live") is not True:
            e["is_live"] = True
    return arr

# כמה ימים אחורה לשמור גיבוי יומי. "30 הגיבויים האחרונים" נשמע סביר אבל
# בפועל, עם עשרות שמירות בשעה, הוא כיסה שעתיים בלבד — וכל מחיקה מאתמול כבר
# נדחקה החוצה. שומרים גם את האחרונים (לשחזור מיידי) וגם אחד ליום (לחקירה).
CONTENT_BAK_KEEP_RECENT = int(os.environ.get("CONTENT_BAK_KEEP_RECENT", "30"))
CONTENT_BAK_KEEP_DAYS = int(os.environ.get("CONTENT_BAK_KEEP_DAYS", "45"))

def _prune_content_backups():
    """משאיר את N האחרונים, ובנוסף את הגיבוי הראשון של כל יום ל-45 ימים."""
    baks = sorted(CONTENT_BAK_DIR.glob("content_*.json"))
    if len(baks) <= CONTENT_BAK_KEEP_RECENT:
        return
    keep = set(baks[-CONTENT_BAK_KEEP_RECENT:])
    cutoff = time.time() - CONTENT_BAK_KEEP_DAYS * 86400
    first_of_day = {}
    for p in baks:
        try:
            ts = int(p.stem.split("_")[1])
        except (IndexError, ValueError):
            keep.add(p)          # שם לא צפוי — לא נוגעים
            continue
        if ts < cutoff:
            continue             # ישן מדי — יימחק
        day = time.strftime("%Y-%m-%d", time.localtime(ts))
        if day not in first_of_day:
            first_of_day[day] = p
            keep.add(p)
    for p in baks:
        if p not in keep:
            p.unlink(missing_ok=True)


def save_content(arr: list):
    arr = _normalize_live_flag(arr)
    # גיבוי בטיחות לפני דריסה — content.json הוא מקור האמת, ורוצים אפשרות לשחזר
    # אם מישהו מחק/דרס בטעות.
    try:
        if CONTENT_FILE.exists():
            CONTENT_BAK_DIR.mkdir(parents=True, exist_ok=True)
            bak = CONTENT_BAK_DIR / f"content_{int(time.time())}.json"
            bak.write_text(CONTENT_FILE.read_text(encoding="utf-8"), encoding="utf-8")
            _prune_content_backups()
    except Exception as e:
        log.warning("גיבוי content נכשל (ממשיכים בשמירה): %s", e)
    CONTENT_FILE.write_text(json.dumps(arr, ensure_ascii=False, indent=2), encoding="utf-8")
    _bump_content_version()

async def seed_content_if_empty():
    """בהפעלה ראשונה — זורע את content.json מתוך movies.json הקיים בגיטהאב, כדי
    שהפאנל יראה מיד את כל התוכן הקיים. אחרי זה המקור הוא השרת בלבד."""
    if CONTENT_FILE.exists():
        return
    try:
        async with httpx.AsyncClient(timeout=30) as cx:
            r = await cx.get(CONTENT_SEED_URL + "?t=" + str(int(time.time())))
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    save_content(data)
                    log.info("✅ content.json נזרע מ-%d פריטים", len(data))
    except Exception as e:
        log.warning("זריעת content.json נכשלה: %s", e)

@api.get("/admin/tmdb")
async def admin_tmdb(q: str = ""):
    """חיפוש TMDB דרך השרת — המפתח (TMDB_API_KEY) נשאר בשרת, לא בדפדפן."""
    return {"results": await tmdb_search(q)}

# ── ניהול בריכת בוטי הסטרימינג מהפאנל (הוספה/רשימה/הסרה בלי SSH) ──────────────
def _pool_tokens_in_file() -> list:
    if STREAM_BOTS_FILE.exists():
        return [t.strip() for t in STREAM_BOTS_FILE.read_text().splitlines() if t.strip()]
    return []

class PoolAddReq(BaseModel):
    password: str
    token: str

@api.post("/pool/add")
async def pool_add(req: PoolAddReq, request: Request):
    check_panel_password(request, req.password)
    tok = (req.token or "").strip()
    # מקבל טוקן בוט (123456:AA...) או session string של חשבון (מחרוזת ארוכה)
    if not (_is_bot_token(tok) or len(tok) >= 80):
        raise HTTPException(status_code=400, detail="לא טוקן בוט ולא session string תקין")
    if tok in _pool_tokens_in_file() or any(b.get("token") == tok for b in _stream_bots):
        raise HTTPException(status_code=400, detail="כבר קיים בבריכה")
    before = len(_stream_bots)
    uid = f"live_{int(time.time())}"
    err = await _start_one_pool_bot(uid, tok)     # מנסה להעלות אותו מיד
    if len(_stream_bots) <= before:
        raise HTTPException(status_code=400,
            detail="לא עלה — %s" % (err or "סיבה לא ידועה, ראה journalctl"))
    try:                                          # נשמר לקובץ כדי לשרוד restart
        with open(STREAM_BOTS_FILE, "a", encoding="utf-8") as f:
            f.write(tok + "\n")
    except Exception as e:
        log.warning("שמירת טוקן לקובץ נכשלה: %s", e)
    return {"ok": True, "active": len(_stream_bots)}

class PoolPwReq(BaseModel):
    password: str

@api.get("/stream/tune")
async def stream_tune(request: Request, media_conns: Optional[int] = None,
                      parallel_parts: Optional[int] = None,
                      bands_timeout: Optional[int] = None,
                      bands_per_mb: Optional[float] = None):
    """קורא/משנה את פרמטרי ההזרמה *בזמן ריצה*, בלי הפעלה מחדש.

    למה זה קיים: כל השוואה בין תצורות דרשה restart, וכל restart מאפס את בריכת
    הבוטים ואת חיבורי המדיה — כך שההשוואה מדדה גם את החימום ולא רק את התצורה.
    בלי זה אי אפשר להשוות שני מסלולים באותם תנאים.

    localhost בלבד. השינוי לא נשמר — .env נשאר מקור האמת אחרי restart.
    """
    global STREAM_MEDIA_CONNS, STREAM_PARALLEL_PARTS
    global MEDIA_BANDS_TIMEOUT, MEDIA_BANDS_PER_MB
    if not is_local_request(request):
        raise HTTPException(status_code=403, detail="localhost only")
    if media_conns is not None:
        STREAM_MEDIA_CONNS = max(0, media_conns)
    if parallel_parts is not None:
        STREAM_PARALLEL_PARTS = max(1, parallel_parts)
    if bands_timeout is not None:
        MEDIA_BANDS_TIMEOUT = max(1, bands_timeout)
    if bands_per_mb is not None:
        MEDIA_BANDS_PER_MB = max(0.0, bands_per_mb)
    return {"media_conns": STREAM_MEDIA_CONNS,
            "parallel_parts": STREAM_PARALLEL_PARTS,
            "bands_timeout": MEDIA_BANDS_TIMEOUT,
            "bands_per_mb": MEDIA_BANDS_PER_MB,
            "bots": len(_stream_bots),
            "note": "זמני — .env גובר אחרי restart"}

@api.get("/speedtest/bots")
async def speedtest_bots(request: Request, mb: int = 4, n: int = 0):
    """מודד את התפוקה של כל בוט *בנפרד*, באותו רגע, על אותו קובץ.

    זו הבדיקה שמכריעה מאיפה מגיעה התנודתיות: אם כל הבוטים איטיים יחד —
    המגבלה על השרת/ה-IP ואין מה לתקן בקוד. אם חלקם מהירים וחלקם איטיים —
    המגבלה היא לכל חשבון בנפרד, ואז פיזור חכם יותר בין הבוטים כן יעזור.

    localhost בלבד.  /speedtest/bots?mb=4&n=8
    """
    if not is_local_request(request):
        raise HTTPException(status_code=403, detail="localhost only")
    if not STREAM_CHANNEL_ID:
        raise HTTPException(400, "אין ערוץ תוכן מוגדר")
    msg_id = None
    for e in load_content():
        m = re.search(r"/stream/-?\d+/(\d+)", str(e.get("video_url") or ""))
        if m:
            msg_id = int(m.group(1))
            break
    if msg_id is None:
        raise HTTPException(400, "לא נמצא פריט עם קישור לערוץ")

    want = mb * 1024 * 1024
    bots = _stream_bots[:n] if n > 0 else list(_stream_bots)
    out = []
    for bot in bots:
        row = {"bot": bot["name"], "who": bot.get("who", "")}
        t0 = time.time()
        try:
            msg = await _get_bot_msg(bot, STREAM_CHANNEL_ID, msg_id)
            media = msg and (msg.video or msg.document or msg.audio)
            if not media:
                row["error"] = "אין מדיה"
                out.append(row)
                continue
            dc_id, location = _file_location(media)
            sessions, _gen = await get_media_session_pool_gen(
                bot["client"], bot["name"], dc_id, max(1, STREAM_MEDIA_CONNS))
            if not sessions:
                row["error"] = "אין חיבורים"
                out.append(row)
                continue
            per = -(-want // len(sessions))
            tasks = [_band_fetch(sessions[i], location, i * per,
                                 min(want, (i + 1) * per) - 1)
                     for i in range(len(sessions)) if i * per < want]
            t0 = time.time()
            parts = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=60)
            got = sum(len(p) for p in parts if isinstance(p, (bytes, bytearray)))
            el = time.time() - t0
            row.update(mb=round(got / 1024 / 1024, 2), seconds=round(el, 2),
                       mb_per_sec=round(got / 1024 / 1024 / el, 2) if el else 0)
        except Exception as e:
            row["error"] = f"{type(e).__name__}: {e}"[:120]
            row["seconds"] = round(time.time() - t0, 2)
        out.append(row)
    good = [r["mb_per_sec"] for r in out if r.get("mb_per_sec")]
    return {"message_id": msg_id, "conns_per_bot": STREAM_MEDIA_CONNS,
            "bots": out,
            "summary": {"נבדקו": len(out), "הצליחו": len(good),
                        "הכי מהיר": max(good) if good else 0,
                        "הכי איטי": min(good) if good else 0,
                        "חציון": sorted(good)[len(good) // 2] if good else 0}}

@api.post("/pool/list")
async def pool_list(req: PoolPwReq, request: Request):
    check_panel_password(request, req.password)
    now = time.time()
    bots = []
    for b in _stream_bots:
        cd = max(0, int(b["cooldown_until"] - now))
        bots.append({
            "name": b["name"],
            "who": b.get("who", ""),           # @username — לזיהוי איזה בוט זה
            "status": "פעיל" if cd == 0 else "מתקרר",
            "cooldown_left": cd,               # כמה שניות נשארו לעונשין
            # peer_ok: האם הבוט מזהה את ערוץ התוכן. בלעדיו כל משיכת מדיה שלו
            # נכשלת ב-'Peer id invalid' והוא חסר תועלת — גם אם הוא "פעיל".
            "peer_ok": bool(b.get("peer_ok", True)),
            "kind": b.get("kind", "bot"),
            "token_tail": (b.get("token") or "")[-6:],
        })
    healthy = sum(1 for b in bots if b["status"] == "פעיל" and b["peer_ok"])
    return {"active": len(_stream_bots), "healthy": healthy,
            "in_file": len(_pool_tokens_in_file()),
            "channel": STREAM_CHANNEL_ID, "bots": bots}

class PoolNameReq(BaseModel):
    password: str
    name: Optional[str] = None     # ריק = כל מי שלא מזהה את הערוץ

@api.post("/pool/reconnect")
async def pool_reconnect(req: PoolNameReq, request: Request):
    """מנסה מחדש לזהות את ערוץ התוכן עבור בוט (או כל מי שנכשל).
    משמש את הכפתור בפאנל כשבוט מוצג כ'לא מחובר לערוץ'."""
    check_panel_password(request, req.password)
    targets = [b for b in _stream_bots
               if (req.name and b["name"] == req.name) or (not req.name and not b.get("peer_ok", True))]
    if not targets:
        raise HTTPException(404, "לא נמצא בוט מתאים")
    out = []
    for b in targets:
        ok = await _resolve_peer(b["client"], b["name"])
        b["peer_ok"] = ok
        if ok:
            b["cooldown_until"] = 0.0          # מזוהה שוב — משחררים מעונשין
            _peer_errors.pop(b["name"], None)
        # מזהה הבוט: בלי זה אי אפשר לדעת *את מי* להוסיף לערוץ. בוט חייב להיות
        # חבר בערוץ כדי לגשת אליו — אין דרך לעקוף את זה בקוד.
        who = ""
        try:
            me = await asyncio.wait_for(b["client"].get_me(), timeout=10)
            who = ("@" + me.username) if me.username else (me.first_name or "")
        except Exception:
            pass
        out.append({"name": b["name"], "peer_ok": ok, "who": who,
                    "error": _peer_errors.get(b["name"], "")})
    return {"ok": True, "results": out}

class PoolRemoveReq(BaseModel):
    password: str
    name: str

@api.post("/pool/remove")
async def pool_remove(req: PoolRemoveReq, request: Request):
    check_panel_password(request, req.password)
    target = next((b for b in _stream_bots if b["name"] == req.name), None)
    if not target:
        raise HTTPException(status_code=404, detail="בוט לא נמצא")
    tok = target.get("token")
    try:
        await target["client"].stop()
    except Exception:
        pass
    _stream_bots[:] = [b for b in _stream_bots if b["name"] != req.name]
    if tok:                                        # מסירים מהקובץ כדי שלא יחזור ב-restart
        rest = [t for t in _pool_tokens_in_file() if t != tok]
        try:
            STREAM_BOTS_FILE.write_text("\n".join(rest) + ("\n" if rest else ""), encoding="utf-8")
        except Exception as e:
            log.warning("עדכון קובץ הבוטים נכשל: %s", e)
    return {"ok": True, "active": len(_stream_bots)}

# ── ייבוא מרובה ממאגר (ערוץ טלגרם חיצוני) ─────────────────────────────────────
# עובר על ערוץ מקור (של חבר וכו'), מעתיק כל וידאו לערוץ שלנו כדי שכל בוטי ה-pool
# יוכלו להגיש, מזהה שם (TMDB) ומוסיף ל-new_uploads לאישור בפאנל. ההעתקה נעשית
# ע"י חשבון-משתמש (userbot) מה-pool — רק הוא יכול לקרוא ערוץ של מישהו אחר וגם
# לפרסם לערוץ שלנו. איטי בכוונה (טלגרם מגביל) — רץ ברקע ומדלג על כפילויות.
_import = {"running": False, "source": "", "found": 0, "imported": 0,
           "skipped": 0, "errors": 0, "unmatched": 0, "to_site": 0, "to_pending": 0,
           "msg": "מוכן", "started": 0}

def _pick_pool_userbot():
    for b in _stream_bots:
        if b.get("kind") == "user":
            return b
    return None

async def _bulk_import_worker(sources, per_min: int, limit: int, kinds: str = "all",
                              only_matched: bool = False, unmatched_limit: int = 0):
    """סורק מאגר/מאגרים, מעתיק כל וידאו לערוץ שלנו, ומזהה דרך TMDB:
    • זוהה בוודאות → מעלה *ישירות לאתר* עם קטגוריה אוטומטית (לפי ז'אנר/מוצא).
    • לא זוהה → נשאר בהמתנה (new_uploads) לאישור ידני.
    תומך בכמה מאגרים ברצף. איטי בכוונה (per_min בדקה) — טפטוף מבוקר."""
    ub = _pick_pool_userbot()
    if not ub:
        _import.update(running=False, msg="אין userbot ב-pool — הוסף חשבון-משתמש בטאב 'בוטים'")
        return
    client = ub["client"]
    if isinstance(sources, (str, int)):
        sources = [sources]
    sources = [s for s in sources if str(s).strip() != ""]
    _import.update(running=True, source=", ".join(str(s) for s in sources), found=0, imported=0,
                   skipped=0, errors=0, unmatched=0, to_site=0, to_pending=0,
                   msg="מזהה את ערוצי המקור...", started=int(time.time()))
    # ה-userbot רץ in_memory → מטמון ה-peers מתאפס ב-restart. מסנכרנים dialogs
    # פעם אחת כדי לאכלס peers של ערוצי המקור *וגם* של הערוצים שלנו.
    _import["msg"] = "מסנכרן צ'אטים..."
    try:
        async for _d in client.get_dialogs():
            pass
    except Exception as e:
        log.warning("import: get_dialogs נכשל: %s", e)
    per_min = max(1, int(per_min or 10))     # כמה קבצים להעביר בכל דקה
    window_start = time.time()
    batch = 0
    # טוענים פעם אחת את מה שכבר קיים (מהיר — בלי לקרוא קבצים בכל פריט):
    # קובץ (fuid), פרק (סדרה+עונה+פרק), וסרט (tmdb_id / שם+שנה) — למניעת כפילויות
    # מול כל התוכן שכבר באתר.
    seen_fuid, seen_ep, seen_mov_tmdb, seen_mov_title = set(), set(), set(), set()
    for e in load_content() + load_new_uploads():
        if e.get("file_unique_id"):
            seen_fuid.add(e["file_unique_id"])
        if e.get("series_name") and e.get("episode_number") is not None:
            try:
                seen_ep.add((_norm_series(e["series_name"]), int(e.get("season_number") or 1), int(e["episode_number"])))
            except Exception:
                pass
        elif not e.get("series_name"):   # סרט
            if e.get("tmdb_id"):
                try: seen_mov_tmdb.add(int(e["tmdb_id"]))
                except Exception: pass
            t = _norm_title(e.get("title") or e.get("en_title") or "")
            if t:
                seen_mov_title.add((t, str(e.get("year") or "")))
    # סורק את הערוצים שלנו (שהבוט שולח אליהם הכל) ואוסף file_unique_id — כך קובץ
    # שכבר קיים אצלנו (גם אם לא רשום ב-content.json) יידלג. אותו קובץ = אותו fuid.
    _import["msg"] = "מסנכרן את הערוצים שלנו (מניעת כפילויות)..."
    for ch in STREAM_CHANNELS:
        try:
            cnt = 0
            async for m in client.get_chat_history(ch):
                if not _import["running"]:
                    break
                md = m.video or m.document or m.audio
                fu = getattr(md, "file_unique_id", "") if md else ""
                if fu:
                    seen_fuid.add(fu)
                cnt += 1
                if cnt % 1000 == 0:
                    _import["msg"] = f"מסנכרן את הערוצים שלנו... ({len(seen_fuid)} קבצים ידועים)"
        except Exception as e:
            log.warning("import: סריקת ערוץ שלנו %s נכשלה: %s", ch, e)
    log.info("import: %d fuid ידועים לפני סריקת המקור", len(seen_fuid))
    _series_cache: dict = {}   # שם-סדרה מנורמל → התאמת tv מ-TMDB (או None), לחיסכון בקריאות

    async def _series_tmdb(name):
        key = _norm_series(name)
        if key in _series_cache:
            return _series_cache[key]
        tv = None
        try:
            opts = await tmdb_search(name)
            tv = next((o for o in opts if o.get("type") == "tv"), None)
        except Exception as e:
            log.warning("import: חיפוש סדרה ב-TMDB נכשל: %s", e)
        _series_cache[key] = tv
        return tv

    done = 0
    for source in sources:
        if not _import["running"]:
            break
        try:
            await client.get_chat(source)
        except Exception as e:
            log.warning("import: אין גישה למקור %s: %s", source, e)
            _import["msg"] = f"⚠️ דילגתי על מקור {source} (אין גישה — ודא שה-userbot חבר בו)"
            continue
        _import["msg"] = f"סורק מקור {source} ({len(seen_fuid)} קבצים כבר אצלנו)..."
        try:
            async for msg in client.get_chat_history(source):
                if not _import["running"]:
                    _import["msg"] = "נעצר ידנית"; break
                media = msg.video or msg.document
                if not media:
                    continue
                cap = msg.caption or ""
                fname = getattr(media, "file_name", "") or ""
                if msg.document and fname and not re.search(r'\.(mkv|mp4|avi|mov|webm|m4v|ts)$', fname, re.I):
                    continue  # מסמך שאינו וידאו
                # דלג על טריילרים/טיזרים/קדימונים (לא הסרט עצמו)
                if _TRAILER_RE.search(cap):
                    _import["skipped"] += 1; continue
                _import["found"] += 1
                fuid = getattr(media, "file_unique_id", "") or ""
                if fuid and fuid in seen_fuid:
                    _import["skipped"] += 1; continue
                # פרק סדרה? מזהים מהכיתוב או משם הקובץ
                ep = parse_episode_info(cap) or parse_episode_info(fname)
                # סינון לפי בחירת המשתמש: רק סרטים / רק סדרות / משולב
                if (kinds == "movies" and ep) or (kinds == "series" and not ep):
                    continue
                options, ryear = None, ""
                if ep:
                    epkey = (_norm_series(ep["series"]), ep["season"], ep["episode"])
                    if epkey in seen_ep:
                        _import["skipped"] += 1; continue
                else:
                    # סרט — מזהים מועמדי-שם (עברי/אנגלי) + שנה מהכיתוב, לפני ההעתקה
                    cands, ryear, _t = _recognition_candidates(cap, fname)
                    def _title_seen(nt):
                        return bool(nt) and ((nt, str(ryear or "")) in seen_mov_title or (nt, "") in seen_mov_title)
                    # דדופ מול הקיים לפי כל צורת-שם (כולל השם העברי מהכיתוב) + שנה
                    if any(_title_seen(_norm_title(c)) for c in cands):
                        _import["skipped"] += 1; continue
                    # חיפוש TMDB לפי המועמדים
                    options = None
                    for q in cands:
                        options = await tmdb_search(q, ryear)
                        if options:
                            break
                    if options:
                        # כיבוד בחירת "רק סרטים": קובץ בלי סימון פרק בשם עדיין יכול
                        # להיות סדרה לפי TMDB (למשל דרמה יפנית). אם המשתמש ביקש רק
                        # סרטים ו-TMDB אומר שזו סדרה — מדלגים (לא מכניסים סדרה).
                        if kinds == "movies" and options[0].get("type") == "tv":
                            _import["skipped"] += 1; continue
                        if options[0].get("tmdb_id") and int(options[0]["tmdb_id"]) in seen_mov_tmdb:
                            _import["skipped"] += 1; continue
                        if _title_seen(_norm_title(options[0].get("title", ""))):
                            _import["skipped"] += 1; continue
                # ── סינון "עם/בלי זיהוי" (לפני ההעתקה — לא מבזבזים העתקה על מדלגים) ──
                # מזוהה = סרט שנמצא ב-TMDB, או פרק שסדרתו נמצאה ב-TMDB.
                _matched = bool(await _series_tmdb(ep["series"])) if ep else bool(options)
                if not _matched:
                    if only_matched:
                        _import["skipped"] += 1; continue          # "עם זיהוי" — מדלג על לא-מזוהה
                    if unmatched_limit and _import["unmatched"] >= unmatched_limit:
                        _import["skipped"] += 1; continue          # הגיע למכסת הלא-מזוהים
                # העתקה לערוץ הפעיל שלנו (גלישה אוטומטית כשמתמלא) דרך ה-userbot
                new_id = None
                dest = current_upload_channel()
                async with _upload_lock:
                    for attempt in range(6):
                        try:
                            copied = await client.copy_message(dest, source, msg.id)
                            new_id = copied.id
                            note_uploaded_msg_id(dest, new_id)
                            break
                        except FloodWait as e:
                            _import["msg"] = f"טלגרם ביקש להמתין {int(getattr(e,'value',30))}ש — ממתין..."
                            await asyncio.sleep(int(getattr(e, "value", 30)) + 2)
                        except Exception as e:
                            log.warning("import: copy נכשל: %s", e); break
                if not new_id:
                    _import["errors"] += 1; continue
                try:
                    if ep:
                        # זיהוי סדרה ב-TMDB (עם cache) → קטגוריה + פוסטר + תיאור.
                        tv = await _series_tmdb(ep["series"])
                        if tv:
                            cat = _auto_category(tv)
                            en = tv.get("en_title") or tv.get("original") or tv.get("title")
                            meta = {"poster": tv.get("poster", ""), "overview": tv.get("overview", ""),
                                    "tmdb_id": tv.get("tmdb_id", 0), "en_title": en,
                                    "custom_slug": _custom_slug(en, tv.get("title", ""), tv.get("tmdb_id"))}
                            add_episode_entry(ep, new_id, fuid, dest, category=cat, meta=meta, to_content=True)
                            _import["to_site"] += 1
                        else:
                            add_episode_entry(ep, new_id, fuid, dest)   # לא זוהה → בהמתנה
                            _import["to_pending"] += 1; _import["unmatched"] += 1
                        seen_ep.add((_norm_series(ep["series"]), ep["season"], ep["episode"]))
                    elif options:
                        ch = dict(options[0]); ch["year"] = ch.get("year") or ryear
                        cat = _auto_category(ch)
                        add_movie_entry(ch, new_id, fuid, dest, category=cat, to_content=True)
                        _import["to_site"] += 1
                        if ch.get("tmdb_id"):
                            try: seen_mov_tmdb.add(int(ch["tmdb_id"]))
                            except Exception: pass
                        seen_mov_title.add((_norm_title(ch.get("title", "")), str(ch.get("year") or "")))
                    else:
                        # לא זוהה ב-TMDB — נכנס לאישור מסומן (tmdb_id=0) לטיפול נפרד
                        _import["unmatched"] += 1; _import["to_pending"] += 1
                        cap_title = (cap.splitlines()[0].strip() if cap.strip() else "") or clean_name(fname)
                        add_movie_entry({"title": cap_title or f"קובץ {new_id}",
                                         "year": ryear, "tmdb_id": 0, "type": "movie",
                                         "poster": "", "overview": ""}, new_id, fuid, dest)
                        seen_mov_title.add((_norm_title(cap_title), str(ryear or "")))
                    if fuid:
                        seen_fuid.add(fuid)
                    _import["imported"] += 1
                except Exception as e:
                    log.warning("import: הוספה נכשלה: %s", e); _import["errors"] += 1
                done += 1
                _import["msg"] = (f"מייבא... {_import['to_site']} עלו לאתר, "
                                  f"{_import['to_pending']} בהמתנה, {_import['skipped']} דילוגים")
                if limit and done >= limit:
                    _import["msg"] = f"הגיע למגבלה ({limit}) — הרץ שוב להמשך"; _import["running"] = False; break
                # קצב: אחרי per_min העברות, ממתין עד סוף הדקה (טפטוף עדין + זמן לאשר)
                batch += 1
                if batch >= per_min:
                    wait = max(0, 60 - (time.time() - window_start))
                    _import["msg"] = (f"הועברו {per_min} קבצים בדקה זו — ממתין {int(wait)}ש "
                                      f"({_import['to_site']} באתר, {_import['to_pending']} בהמתנה)")
                    slept = 0
                    while slept < wait and _import["running"]:
                        await asyncio.sleep(1); slept += 1
                    window_start = time.time(); batch = 0
        except Exception as e:
            log.exception("bulk import source failed")
            _import["msg"] = f"שגיאה במקור {source}: {e}"
    if _import["running"]:
        _import["msg"] = (f"הסתיים ✅ — {_import['to_site']} עלו לאתר, "
                          f"{_import['to_pending']} נשארו בהמתנה לאישור")
    _import["running"] = False

class ImportStartReq(BaseModel):
    password: str
    source: str
    source2: str = ""    # מאגר שני (אופציונלי) — נסרק אחרי הראשון
    per_min: int = 10    # כמה קבצים להעביר בכל דקה (טפטוף)
    limit: int = 0       # מגבלת סה"כ (0 = עד שהערוץ נגמר / עצירה ידנית)
    kinds: str = "all"   # "all" / "movies" / "series" — מה לייבא
    only_matched: bool = False   # "יבוא עם זיהוי" — רק פריטים שזוהו (מדלג על לא-מזוהים)
    unmatched_limit: int = 0     # "יבוא בלי זיהוי" — כמה לא-מזוהים להביא (0 = ללא הגבלה)

@api.post("/import/start")
async def import_start(req: ImportStartReq, request: Request):
    check_panel_password(request, req.password)
    if _import["running"]:
        raise HTTPException(status_code=400, detail="ייבוא כבר רץ")
    if not _pick_pool_userbot():
        raise HTTPException(status_code=400, detail="אין userbot ב-pool — הוסף חשבון-משתמש בטאב 'בוטים'")
    def _norm_src(s):
        s = (s or "").strip()
        if not s:
            return None
        try:
            return int(s)           # תמיכה ב-ID מספרי (-100...)
        except ValueError:
            return s                # שם משתמש/לינק
    srcs = [x for x in (_norm_src(req.source), _norm_src(req.source2)) if x is not None]
    if not srcs:
        raise HTTPException(status_code=400, detail="חסר מקור (שם/לינק/ID של הערוץ)")
    kinds = req.kinds if req.kinds in ("all", "movies", "series") else "all"
    asyncio.create_task(_bulk_import_worker(srcs, int(req.per_min or 10), max(0, int(req.limit or 0)), kinds,
                                            bool(req.only_matched), max(0, int(req.unmatched_limit or 0))))
    return {"ok": True}

@api.post("/import/status")
async def import_status(req: PoolPwReq, request: Request):
    check_panel_password(request, req.password)
    return dict(_import)

@api.post("/import/stop")
async def import_stop(req: PoolPwReq, request: Request):
    check_panel_password(request, req.password)
    _import["running"] = False
    return {"ok": True}

# ── ניהול ערוצי אחסון (ריבוי ערוצים + גלישה) ─────────────────────────────────
class ChannelAddReq(BaseModel):
    password: str
    channel_id: str

@api.post("/channels/add")
async def channels_add(req: ChannelAddReq, request: Request):
    check_panel_password(request, req.password)
    raw = (req.channel_id or "").strip()
    try:
        cid = int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="מזהה ערוץ חייב להיות מספר (למשל -100...)")
    if cid in STREAM_CHANNELS:
        raise HTTPException(status_code=400, detail="הערוץ כבר ברשימה")
    STREAM_CHANNELS.append(cid)
    # שומרים לקובץ (בלי הערוץ הראשי — הוא תמיד ראשון מ-.env)
    try:
        extra = [c for c in STREAM_CHANNELS if c != STREAM_CHANNEL_ID]
        STREAM_CHANNELS_FILE.write_text("\n".join(str(c) for c in extra) + ("\n" if extra else ""), encoding="utf-8")
    except Exception as e:
        log.warning("שמירת stream_channels.txt נכשלה: %s", e)
    return {"ok": True, "channels": STREAM_CHANNELS}

@api.post("/channels/list")
async def channels_list(req: PoolPwReq, request: Request):
    check_panel_password(request, req.password)
    active = current_upload_channel()
    return {"channels": STREAM_CHANNELS, "active": active,
            "max_per_channel": CHANNEL_MAX_MESSAGES}

# ── מטמון תגובת /content ──────────────────────────────────────────────────────
# בניית התגובה (טעינת 10MB + הרחבה+חתימה של ~10K קישורים) לקחה ~2.5ש בכל בקשה,
# מה שהאט כל טעינת דף באתר. מוחזק כאן גוף JSON מוכן, שנבנה מחדש רק כשהתוכן משתנה
# (לפי הגרסה) או כל CONTENT_CACHE_TTL שניות (כדי לרענן את חתימות הקישורים — הן
# תקפות 6 שעות, אז רענון כל כמה דקות בטוח). כך כמעט כל בקשה מוגשת מיידית.
CONTENT_CACHE_TTL = 180

# מטמון גופי JSON מוכנים — מקודדים ל-bytes וגם דחוסים מראש.
# הגרסה הקודמת שמרה מחרוזת בלבד, כך שכל בקשה עדיין עשתה encode של ~12MB
# ו-nginx דחס אותם מחדש. זה ~1 שנייה של CPU לכל טעינת דף, על אותו תהליך
# שמזרים את הווידאו — ולכן גם הנגן נתקע כשמישהו נכנס לאתר. כאן הכל נבנה
# פעם אחת לגרסה, וכל בקשה היא העתקת בייטים.
_JSON_CACHE: dict = {}
_JSON_CACHE_MAX = 8          # מגן מפני ?limit= שרירותי שינפח את הזיכרון


def _fresh(c, ver, ttl, now=None):
    return c and c["ver"] == ver and ((now or time.time()) - c["built"]) < ttl


# ── רענון כפוי של הקטלוג אצל הלקוח ───────────────────────────────────────────
# הקישורים בקטלוג חתומים ותקפים SIGN_TTL שניות. ה-ETag היה מבוסס על גרסת
# התוכן בלבד, ולכן לקוח שלא ראה שינוי תוכן קיבל 304 לנצח והמשיך להחזיק את
# הקטלוג הישן שלו — עד שהחתימות שבו פגו וכל לחיצה על "נגן" החזירה 403
# ("הקישור פג תוקף"). זה מה שאילץ מחיקה והתקנה מחדש של האפליקציה.
#
# הפתרון: משלבים ב-ETag גם "חלון זמן". כשהחלון מתחלף ה-ETag משתנה, הלקוח
# מוריד קטלוג טרי עם חתימות חדשות, וזה קורה הרבה לפני שהישנות פגות. החלון
# הוא שליש מתוקף החתימה — כלומר שני רענונים לפחות בתוך כל חיים של חתימה.
SIG_EPOCH_WINDOW = max(600, SIGN_TTL // 3)


def _sig_epoch() -> int:
    return int(time.time()) // SIG_EPOCH_WINDOW


def _build_payload_entry(ver: int, build) -> dict:
    """בונה גוף מוכן (טעינה+חתימה+json+gzip). כבד — נועד לרוץ ב-thread."""
    raw = json.dumps(build(), ensure_ascii=False).encode("utf-8")
    return {"ver": ver, "built": time.time(), "raw": raw,
            # רמה 5: כמעט אותו יחס דחיסה כמו 6 בכשליש מהזמן, וזה רץ פעם אחת
            "gz": gzip.compress(raw, 5) if len(raw) > 4096 else None}


def _store_payload(key: str, c: dict) -> dict:
    if len(_JSON_CACHE) >= _JSON_CACHE_MAX:
        _JSON_CACHE.pop(next(iter(_JSON_CACHE)), None)
    _JSON_CACHE[key] = c
    return c


def _cached_payload(key: str, ver: int, build, ttl: float = CONTENT_CACHE_TTL):
    """גוף מוכן למפתח נתון. build() נקרא רק כשהמטמון פג או שהתוכן השתנה.
    גרסה סינכרונית — נשמרת לקוראים שאינם על ה-event loop."""
    c = _JSON_CACHE.get(key)
    if _fresh(c, ver, ttl):
        return c
    return _store_payload(key, _build_payload_entry(ver, build))


# נעילה לכל מפתח: כשכמה משתמשים נכנסים יחד ל-cache קר, רק אחד בונה והשאר
# ממתינים לתוצאה — במקום שכל אחד יריץ בנייה מלאה במקביל וכולם ייתקעו.
_payload_locks: dict = {}


def _payload_lock(key: str) -> asyncio.Lock:
    lk = _payload_locks.get(key)
    if lk is None:
        lk = _payload_locks[key] = asyncio.Lock()
    return lk


async def _cached_payload_async(key: str, ver: int, build, ttl: float = CONTENT_CACHE_TTL):
    """כמו _cached_payload, אבל הבנייה הכבדה רצה ב-thread (asyncio.to_thread)
    כדי לא לחסום את ה-event loop — עליו רצה גם הזרמת הווידאו. בלי זה כל בקשת
    /content ראשונה-לגרסה הקפיאה את השרת ל~1-2ש והנגן נתקע."""
    c = _JSON_CACHE.get(key)
    if _fresh(c, ver, ttl):
        return c
    async with _payload_lock(key):
        c = _JSON_CACHE.get(key)              # אולי כבר נבנה בזמן ההמתנה
        if _fresh(c, ver, ttl):
            return c
        entry = await asyncio.to_thread(_build_payload_entry, ver, build)
        return _store_payload(key, entry)


def _serve_cached(request: Request, c: dict, etag: str, extra: dict = None) -> Response:
    """מגיש גוף מהמטמון, דחוס אם הלקוח תומך, עם ETag ל-304."""
    headers = {"ETag": etag, "Cache-Control": "no-cache", "Vary": "Accept-Encoding"}
    if extra:
        headers.update(extra)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    body = c["raw"]
    if c["gz"] and "gzip" in (request.headers.get("accept-encoding") or ""):
        body, headers["Content-Encoding"] = c["gz"], "gzip"
    return Response(content=body, media_type="application/json", headers=headers)



# ── קטלוג רזה לאתר ────────────────────────────────────────────────────────────
# מדידה: האתר הוריד ופרסר את כל 10,472 הפריטים לפני שצייר פיקסל אחד — 1MB
# דחוס ברשת ועוד ~4 שניות פרסור על שרת חזק (בטלפון: 10-30 שניות, ובזמן הזה
# המסך תקוע והנגן לא מצליח למלא באפר). הכל כדי להציג כ-100 כרטיסיות.
# הפתרון: מסירים את description (32% מהמשקל, מוצג רק כשפותחים פריט) ואת
# video_id הכפול (זהה ל-video_url ב-6709 פריטים; הפרונט ממילא נופל אחורה
# ל-video_url). video_url נשאר — בלעדיו אי אפשר לנגן.
_LITE_DROP = ("description",)
# ה-limit-ים שנשמרים במטמון. כל ערך אחר מוגש מהרשימה בלי גוף שמור, כדי
# ש-?limit=123 מכל מיני מקורות לא ימלא את הזיכרון בגרסאות של אותו קטלוג.
_LITE_LIMITS = (0, 800)


def _lite_items():
    items = []
    for e in _expand_urls(load_content()):
        d = {k: v for k, v in e.items() if k not in _LITE_DROP}
        if d.get("video_id") and d.get("video_id") == d.get("video_url"):
            d.pop("video_id", None)
        items.append(d)
    return items


@api.get("/content/lite")
async def content_lite(request: Request, limit: int = 0):
    """קטלוג לתצוגה. limit>0 מחזיר רק את ה-N הראשונים (ציור מהיר של מסך הבית),
    ואז האתר מושך את השאר ברקע.

    ה-TTL כאן חיוני ולא רק לביצועים: הקישורים חתומים ותקפים 6 שעות, וגרסה
    קודמת רעננה רק כשהתוכן השתנה — כך שיממה בלי עריכה הגישה חתימות פגות.
    """
    ver = get_content_version()
    limit = max(0, limit)
    key = f"lite:{limit}" if limit in _LITE_LIMITS else None
    if key:
        c = await _cached_payload_async(key, ver,
                            lambda: _lite_items()[:limit] if limit else _lite_items())
        etag = f'W/"l{ver}-{limit}-{_sig_epoch()}"'
        return _serve_cached(request, c, etag, {"X-Content-Version": str(ver)})
    # limit חריג — נבנה בלי לשמור (עדיין ב-thread כדי לא לחסום את ה-loop)
    items = await asyncio.to_thread(lambda: _lite_items()[:limit])
    return Response(content=json.dumps(items, ensure_ascii=False),
                    media_type="application/json",
                    headers={"X-Content-Version": str(ver), "Cache-Control": "no-cache"})


@api.get("/content/live")
async def content_live(request: Request):
    """רק השידורים החיים (~230 פריטים, עשרות KB).

    האתר מרענן שידורים חיים כל 5 דקות, וקודם הוריד לשם כך את כל הקטלוג —
    כלומר מגה-בייטים כל רבע שעה לכל לשונית פתוחה, רק כדי לבדוק אם ערוץ אחד
    השתנה.
    """
    ver = get_content_version()
    c = await _cached_payload_async("live", ver,
                        lambda: [e for e in _lite_items() if e.get("is_live")])
    return _serve_cached(request, c, f'W/"v{ver}-{_sig_epoch()}"', {"X-Content-Version": str(ver)})


# אינדקס לפי מזהה. קודם כל בקשה לתיאור סרקה את כל 11,747 הפריטים ובנתה
# מחדש את כל הקישורים החתומים — כלומר פתיחת כרטיסייה עלתה כמו טעינת קטלוג.
_item_index: dict = {"ver": None, "built": 0.0, "by_id": {}}


def _item_index_fresh(ver: int) -> bool:
    return (_item_index["ver"] == ver
            and (time.time() - _item_index["built"]) < CONTENT_CACHE_TTL)


def _build_item_index(ver: int) -> dict:
    """בונה אינדקס id→פריט (חתימת ~11k קישורים). כבד — רץ ב-thread."""
    by_id = {str(e.get("id")): e for e in _expand_urls(load_content())}
    _item_index.update(ver=ver, built=time.time(), by_id=by_id)
    return by_id


_item_index_lock = None


async def _items_by_id_async(ver: int) -> dict:
    if _item_index_fresh(ver):
        return _item_index["by_id"]
    global _item_index_lock
    if _item_index_lock is None:
        _item_index_lock = asyncio.Lock()
    async with _item_index_lock:
        if _item_index_fresh(ver):        # אולי נבנה בזמן ההמתנה
            return _item_index["by_id"]
        return await asyncio.to_thread(_build_item_index, ver)


@api.get("/content/item/{item_id}")
async def content_item(item_id: str):
    """פריט בודד עם כל השדות — משמש למשיכת התיאור כשפותחים סרט/סדרה."""
    e = (await _items_by_id_async(get_content_version())).get(item_id)
    if e is None:
        raise HTTPException(404, "not found")
    return JSONResponse(e, headers={"Cache-Control": "public, max-age=300"})


async def _content_response(request: Request) -> Response:
    """מחזיר את התוכן עם ETag לפי מונה הגרסה.

    התוכן הוא ~10MB (כמגה אחרי gzip) ונשלח בכל טעינת עמוד מחדש, כי לא היו לו
    שום כותרות caching. עם ETag הדפדפן שולח If-None-Match ומקבל 304 ריק כשאין
    שינוי — במקום מגה שלם. Cache-Control: no-cache פירושו "שמור אבל תמיד אמת",
    כך שעדכון תוכן מגיע מיד ואין סכנה שמישהו יראה קטלוג ישן.
    """
    ver = get_content_version()
    c = await _cached_payload_async("full", ver, lambda: _expand_urls(load_content()))
    return _serve_cached(request, c, f'W/"c{ver}-{_sig_epoch()}"', {"X-Content-Version": str(ver)})

@api.get("/content")
async def content_get(request: Request):
    """קריאה פומבית — האתר/הפאנל מושכים מכאן את כל התוכן (עם הכתובת האמיתית).
    כותרת X-Content-Version מאפשרת לפאנל לדעת על איזו גרסה הוא עורך (optimistic lock)."""
    return await _content_response(request)

@api.get("/movies.json")
async def content_movies_alias(request: Request):
    """כינוי ל-/content בשם הקובץ שהאתר רגיל אליו (לקראת מעבר האתר לשרת)."""
    return await _content_response(request)

class ContentSaveReq(BaseModel):
    password: str
    movies: list
    base_version: Optional[int] = None
    confirm_delete: bool = False     # אישור מפורש למחיקה המונית


# כמה פריטים מותר שיעלמו בשמירה אחת בלי אישור מפורש. שמירה מהפאנל שולחת את
# *כל* המערך, ולכן טעינה חלקית, טאב ישן או לחיצה לפני שהכל נטען מוחקים את כל
# מה שלא היה ברשימה — וזה בדיוק "כל יום נמחק תוכן". גרסה קודמת רק גיבתה את
# התוצאה; כאן עוצרים אותה מראש.
CONTENT_DELETE_GUARD = int(os.environ.get("CONTENT_DELETE_GUARD", "50"))

def _content_key(e) -> str:
    return str(e.get("id") or f"{e.get('title')}|{e.get('video_url')}")

def _is_live_item(e) -> bool:
    return e.get("category") == LIVE_CATEGORY or bool(e.get("is_live"))


def _apply_editor_policy(before: list, after: list) -> list:
    """מחזיר את המערך שיישמר בפועל עבור עורך מוגבל.

    שידורים חיים נלקחים תמיד מהמאגר, ומה שהעורך שלח עבורם מתעלמים ממנו.
    זה עדיף על בדיקה שמשווה ערכים: הפאנל נטען פעם אחת ונשאר פתוח, ואם משהו
    השתנה בינתיים העותק שלו מיושן — אז השוואה הייתה חוסמת אותו על פריטים
    שהוא לא נגע בהם. כך הוא לא יכול לשנות שידור חי, וגם לא נחסם בטעות.

    מחיקות מוגבלות למכסה, ורק בתוכן שאינו שידור חי.
    """
    stored_live = {_content_key(e): e for e in before if _is_live_item(e)}
    stored_rest = {_content_key(e): e for e in before if not _is_live_item(e)}

    result, seen_live = [], set()
    for e in after:
        k = _content_key(e)
        if k in stored_live:                 # שידור חי קיים — הגרסה מהמאגר
            result.append(stored_live[k])
            seen_live.add(k)
        elif _is_live_item(e):               # ניסיון להוסיף שידור חי — לא מורשה
            continue
        else:
            result.append(e)
    # שידורים חיים שהעורך השמיט — מוחזרים למקומם
    for k, e in stored_live.items():
        if k not in seen_live:
            result.append(e)

    kept = {_content_key(e) for e in result}
    removed = [e for k, e in stored_rest.items() if k not in kept]
    if len(removed) > EDITOR_MAX_DELETE:
        raise HTTPException(status_code=403, detail=(
            f"⛔ השמירה מוחקת {len(removed)} פריטים, והמותר הוא "
            f"{EDITOR_MAX_DELETE} בכל שמירה. הפעולה בוטלה.\n\n"
            "אם התכוונת למחוק פריט אחד — כנראה הרשימה נטענה חלקית. "
            "רענן את הפאנל ונסה שוב."))
    if removed:
        log.info("עורך מוגבל מחק %d פריטים: %s", len(removed),
                 ", ".join(str(e.get("title"))[:30] for e in removed[:5]))
    return result


class PanelRoleReq(BaseModel):
    password: str

@api.post("/panel/role")
async def panel_role_get(req: PanelRoleReq, request: Request):
    """מזהה את רמת הגישה של הסיסמה. הפאנל קורא לזה בכניסה כדי לדעת מה להציג.
    ההגבלות עצמן נאכפות בשרת בכל פעולה — זה רק כדי לא להציג מסכים חסומים."""
    role = panel_role(request, req.password)
    return {"role": role, "max_delete": EDITOR_MAX_DELETE if role == "editor" else None}

@api.post("/content/save")
async def content_save(req: ContentSaveReq, request: Request):
    """שמירת המערך המלא (list/create/update/delete/saveAll כולם עוברים דרך זה)."""
    role = panel_role(request, req.password)
    if not isinstance(req.movies, list):
        raise HTTPException(status_code=400, detail="movies חייב להיות מערך")
    # ── הגנת עריכה במקביל (optimistic lock) ──────────────────────────────────
    # אם הפאנל שלח base_version והתוכן כבר השתנה מאז (מישהו אחר שמר) — דוחים
    # במקום לדרוס. זה מונע את מחיקת התוכן שקורית כשכמה אנשים עורכים מטאבים ישנים.
    cur_ver = get_content_version()
    if req.base_version is not None and req.base_version != cur_ver:
        raise HTTPException(status_code=409, detail=(
            f"⚠️ התוכן עודכן על ידי מישהו אחר בזמן שערכת (גרסה בשרת {cur_ver}, "
            f"אצלך {req.base_version}). התוכן נטען מחדש — אנא בצע את השינוי שוב "
            "כדי לא לדרוס עבודה של אחרים."))
    # ── הגנת מחיקה המונית ────────────────────────────────────────────────────
    # השמירה דורסת את כל הקטלוג. אם פתאום חסרים עשרות פריטים, כמעט תמיד מדובר
    # בתקלה (רשימה שנטענה חלקית) ולא בכוונה — עוצרים ומבקשים אישור מפורש.
    prev = load_content()
    # מכווצים *לפני* ההשוואה. הקטלוג נשמר עם %BASE% בעוד הפאנל מקבל ושולח
    # כתובת מלאה, ולכן השוואה על הצורה הגולמית הציגה כל שידור חי כאילו
    # השתנה — ועורך נחסם על פריטים שלא נגע בהם בכלל.
    incoming = _collapse_urls(req.movies)
    if role == "editor":
        incoming = _apply_editor_policy(prev, incoming)
    before = len(prev)
    gone = before - len(incoming)
    if gone > CONTENT_DELETE_GUARD and not req.confirm_delete:
        raise HTTPException(status_code=409, detail=(
            f"⛔ השמירה הזו מוחקת {gone} פריטים ({before} → {len(incoming)}) ולכן נעצרה.\n\n"
            "זה קורה כשהרשימה נטענה חלקית — למשל טאב ישן, או שמירה לפני שהתוכן "
            "סיים להיטען. רענן את הפאנל, ודא שכל התוכן מוצג, ובצע את השינוי שוב.\n\n"
            "אם המחיקה מכוונת — שלח שוב עם confirm_delete."))
    if gone > 0:
        log.warning("שמירת תוכן מסירה %d פריטים (%d → %d)%s",
                    gone, before, len(incoming),
                    " — באישור מפורש" if req.confirm_delete else "")
    save_content(incoming)
    return {"ok": True, "count": len(incoming), "version": get_content_version()}

@api.get("/content/relink")
async def content_relink(request: Request, dry: int = 1):
    """מחליף את הקישורים הישנים (hf.space שמת) בקישורי השרת/הערוץ החדשים:
    - טלגרם: לפי מפת המיגרציה (migration_progress.json) → /stream/<ערוץ>/<msg חדש>
    - שידורים חיים: hf.space/hls-relay/… → אותו נתיב אבל דרך השרת החדש
    כל שאר הסוגים (kaltura/drive/youtube וכו') נשארים כמו שהם.
    מותר רק מ-localhost. dry=1 (ברירת מחדל) = תצוגה מקדימה בלי לשמור; dry=0 = מבצע."""
    if not is_local_request(request):
        raise HTTPException(status_code=403, detail="localhost only")
    # מפת המיגרציה: "old_chat:old_msg" -> new_msg_id
    prog = {}
    if MIGRATION_PROGRESS_FILE.exists():
        try:
            prog = json.loads(MIGRATION_PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            prog = {}
    content = load_content()
    stats = {"telegram_relinked": 0, "telegram_unmapped": 0, "live_relinked": 0,
             "total": len(content), "have_map": len(prog), "channel": STREAM_CHANNEL_ID,
             "base": STREAM_PUBLIC_BASE}
    for e in content:
        url = e.get("video_url") or e.get("video_id") or ""
        if not url:
            continue
        # שידורים חיים / hls-relay דרך hf.space → השרת החדש
        idx = url.find("/hls-relay/")
        if "hf.space" in url and idx != -1:
            new = BASE_TOKEN + url[idx:]
            e["video_url"] = new
            if e.get("video_id"):
                e["video_id"] = new
            stats["live_relinked"] += 1
            continue
        # טלגרם ישן hf.space/stream/<chat>/<msg>
        m = _OLD_URL_RE.search(url)
        if not m:
            continue
        key = f"{int(m.group(1))}:{int(m.group(2))}"
        new_msg = prog.get(key)
        if new_msg is None:
            stats["telegram_unmapped"] += 1
            continue
        new = stored_stream_url(new_msg)
        e["video_url"] = new
        e["video_id"] = new
        stats["telegram_relinked"] += 1
    if dry == 0:
        save_content(content)
        stats["saved"] = True
    else:
        stats["saved"] = False
    return stats

# ── ריענון שרת דרך קישור פשוט ──────────────────────────────────────────────
# מיועד לשליחה למישהו שצריך לרענן את השרת בעצמו כשהוא נתקע, בלי גישה
# לחשבון Hugging Face. שולחים לו קישור מהצורה:
#   https://<the-space-url>/restart?key=<RESTART_KEY שהגדרת ב-Secrets>
# לחיצה עליו (או פתיחה בדפדפן) מפילה את התהליך בכוונה - Hugging Face Spaces
# מקים אוטומטית קונטיינר חדש, בדיוק כמו "Restart Space" הידני.
#
# תיקון: בפועל ראינו שכמה קריאות ל-/restart הגיעו תוך פחות משנייה אחת מהדפדפן
# (כנראה רענון כפול/כמה טאבים) - וכל אחת הפילה את התהליך שוב, מה שהיה עלול
# ליצור לולאת-ריענון אינסופית (השרת אף פעם לא מספיק להתייצב). RESTART_COOLDOWN_SECS
# מונע את זה: בקשה נוספת בתוך חלון הזמן הזה מוצגת כ"כבר מתבצע ריענון" בלי
# להפיל את התהליך שוב.
RESTART_COOLDOWN_SECS = 90
_last_restart_requested_at = 0.0

async def _delayed_exit():
    await asyncio.sleep(1)  # לתת לתגובת ה-HTML להישלח ללקוח לפני שהתהליך נופל
    os._exit(0)

@api.get("/restart", response_class=HTMLResponse)
async def restart_server(key: str = ""):
    global _last_restart_requested_at
    if not RESTART_KEY or key != RESTART_KEY:
        return HTMLResponse(
            "<body style='background:#111;color:#e50914;font-family:Arial;"
            "display:flex;align-items:center;justify-content:center;height:100vh;"
            "direction:rtl;font-size:20px'>🚫 קישור לא תקין</body>",
            status_code=403,
        )
    now = time.time()
    if now - _last_restart_requested_at < RESTART_COOLDOWN_SECS:
        return HTMLResponse(
            "<body style='background:#111;color:#f5a623;font-family:Arial;"
            "display:flex;align-items:center;justify-content:center;height:100vh;"
            "direction:rtl;font-size:20px;text-align:center'>"
            "⏳ ריענון כבר בתהליך...<br>אין צורך ללחוץ שוב, המתיני כדקה.</body>"
        )
    _last_restart_requested_at = now
    log.critical("🔄 התבקש ריענון ידני של השרת דרך /restart")
    asyncio.create_task(_delayed_exit())
    return HTMLResponse(
        "<body style='background:#111;color:#fff;font-family:Arial;"
        "display:flex;align-items:center;justify-content:center;height:100vh;"
        "direction:rtl;font-size:20px;text-align:center'>"
        "🔄 השרת מתאתחל מחדש...<br>זה ייקח כ-30-60 שניות.</body>"
    )

@api.get("/", response_class=HTMLResponse)
@api.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    html = f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
  <meta charset="UTF-8">
  <title>Telegram Stream Dashboard</title>
  <style>
    body {{ font-family: 'Segoe UI', sans-serif; background: #0f0f0f; color: #e0e0e0; padding: 24px 16px; }}
    h1 {{ color: #fff; margin-bottom: 20px; }}
    .card {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px; padding: 20px; margin-bottom: 16px; }}
    .row {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #222; font-size: 0.88rem; }}
    .row:last-child {{ border-bottom: none; }}
    .key {{ color: #888; }} .val {{ color: #ddd; }}
    code {{ background: #222; padding: 2px 6px; border-radius: 4px; color: #4f9eff; }}
  </style>
</head>
<body>
  <h1>📡 Telegram Stream Server</h1>
  <div class="card">
    <div class="row"><span class="key">קבצים</span><span class="val">{stats['files_processed']}</span></div>
    <div class="row"><span class="key">קישורים</span><span class="val">{stats['links_generated']}</span></div>
    <div class="row"><span class="key">פעיל מאז</span><span class="val">{stats['started_at'][:10]}</span></div>
    <div class="row"><span class="key">Base URL</span><span class="val">{BASE_URL}</span></div>
  </div>
  <div class="card">
    <p>פורמט URL: <code>{BASE_URL}/stream/CHAT_ID/MESSAGE_ID</code></p>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)

# ── Bot handler ───────────────────────────────────────────────────────────────

# תבניות לזיהוי אוטומטי של מספר פרק, מתוך שם הקובץ ו/או הכיתוב (caption)
# שהמשתמש הוסיף להודעה. נבדקות בסדר הזה - הראשונה שמתאימה מנצחת.
# תומך בכל התבניות שראינו בפועל: S05E239, פרק123 / פרק_123, "One Piece - 869",
# OP-EP1078, [EP] 1050, ep1059, וגם מספר "יבש" בין 3-4 ספרות כמוצא אחרון.
EPISODE_PATTERNS = [
    re.compile(r"[Ss]\d+[Ee](\d{1,4})"),
    re.compile(r"פרק[\s_]*(\d{1,4})"),
    re.compile(r"[Oo]ne[\s_\-]*[Pp]iece\D{0,6}(\d{2,4})\b"),
    re.compile(r"OP-EP(\d{1,4})", re.I),
    re.compile(r"\[EP\]\s*(\d{1,4})", re.I),
    re.compile(r"\bEP\s*[-_]?\s*(\d{1,4})\b", re.I),
    re.compile(r"\b(\d{3,4})\b"),
]

def detect_episode(*texts: str) -> Optional[str]:
    """מנסה לזהות מספר פרק מתוך שם הקובץ/הכיתוב. מחזיר None אם לא נמצא כלום -
    כדי שלא ננחש בטעות, עדיף להציג 'לא זוהה' ולתת למשתמש לציין ידנית."""
    for text in texts:
        if not text:
            continue
        for pattern in EPISODE_PATTERNS:
            m = pattern.search(text)
            if m:
                return m.group(1)
    return None

@bot_client.on_message(filters.private & (filters.video | filters.audio | filters.document | filters.video_note))
async def handle_media(client, message: Message):
    stats["files_processed"] += 1
    wait_msg = await message.reply_text("⏳ מעבד...")
    try:
        media     = message.video or message.audio or message.document or message.video_note
        # תיקון: getattr עם ברירת מחדל לא עוזר אם ה-attribute קיים אבל שווה
        # None (זה מה שקורה בפועל בהרבה video/video_note בלי metadata של שם
        # קובץ) - זה מה שגרם ל"קובץ: None" בהודעות התשובה. עכשיו יש שרשרת
        # גיבויים: שם הקובץ → הכיתוב שהמשתמש כתב → מזהה גנרי לפי message id.
        caption   = (message.caption or "").strip()
        file_name = getattr(media, "file_name", None) or caption or f"file_{message.id}"
        file_size = getattr(media, "file_size", 0)
        size_mb   = round(file_size / 1024 / 1024, 1)
        stream_url = f"{BASE_URL}/stream/{message.chat.id}/{message.id}"
        stats["links_generated"] += 1
        stats["last_file"] = f"{file_name} ({size_mb}MB)"

        episode = detect_episode(file_name, caption)
        episode_line = f"🔢 פרק שזוהה אוטומטית: {episode}\n" if episode else "⚠️ לא זוהה מספר פרק אוטומטית — כדאי לציין ידנית\n"
        # הכיתוב מוצג בנפרד רק אם הוא לא כבר שם הקובץ עצמו (כדי לא לחזור על אותו טקסט פעמיים)
        caption_line = f"📝 כיתוב: {caption}\n" if caption and caption != file_name else ""

        await wait_msg.edit_text(
            f"✅ **קישור סטרימינג מוכן!**\n\n"
            f"📄 קובץ: `{file_name}`\n"
            f"{caption_line}"
            f"{episode_line}"
            f"📦 גודל: {size_mb} MB\n\n"
            f"🔗 **קישור:**\n`{stream_url}`\n\n"
            f"_הקישור תומך ב-Seek מלא ועובד בכל נגן_ 🎬"
        )
        log.info("Stream link: %s (episode=%s)", stream_url, episode)
    except Exception as e:
        log.exception("Error handling media")
        await wait_msg.edit_text(f"❌ שגיאה: {str(e)}")

@bot_client.on_message(filters.private & filters.command("start"))
async def start_command(client, message: Message):
    await message.reply_text(
        "👋 **שלום!**\n\n"
        "שלח לי קובץ וידאו או אודיו ואני אחזיר לך קישור סטרימינג מיידי.\n\n"
        "הקישור עובד בכל נגן ותומך בהזזת הסרגל (Seek) ✅\n\n"
        "פקודות:\n"
        "/scan <from_id> <to_id> — סורק טווח הודעות ישן (לא צריך לשלוח שוב!), "
        "מזהה מספר פרק לכל קובץ, ושולח קובץ JSON מסודר עם הכל.\n"
        "לדוגמה: /scan 1 5300"
    )

@bot_client.on_message(filters.private & filters.command("scan"))
async def scan_command(client, message: Message):
    """
    /scan <from_id> <to_id> — סורק טווח מספרי-הודעה מפורש בצ'אט הזה ומייצר
    קובץ JSON עם קישור סטרימינג + מספר פרק שזוהה אוטומטית לכל קובץ מדיה -
    בלי לשלוח שוב אף קובץ.

    למה טווח מפורש ולא "כל ההיסטוריה" אוטומטית: טלגרם חוסם bot-ים
    (בניגוד ל-userbot-ים) מלהשתמש ב-messages.GetHistory - זו הסיבה
    שניסיון קודם עם get_chat_history נכשל עם "BOT_METHOD_INVALID". השיטה
    שכן עובדת ל-bots (ומוכחת - זו בדיוק מה ש-/stream עצמו עושה בכל בקשה)
    היא שליפת הודעות לפי מספר מזהה מפורש (get_messages), אז כאן עושים את
    זה על טווח שלם, בקבוצות של 200 בכל פעם.

    איך למצוא את הטווח: תסתכלי בקישורים הישנים ששלחתי - הפורמט הוא
    /stream/CHAT_ID/MESSAGE_ID - קחי את המספר הכי קטן והכי גדול שראית.
    """
    chat_id = message.chat.id
    args = message.text.split()
    if len(args) != 3:
        await message.reply_text(
            "שימוש: `/scan <from_id> <to_id>`\n\n"
            "לדוגמה: `/scan 1 5300`\n\n"
            "טיפ: תסתכלי בקישורים הישנים ששלחתי - "
            "/stream/CHAT_ID/**MESSAGE_ID** - זה טווח המספרים לחפש בו."
        )
        return
    try:
        from_id, to_id = int(args[1]), int(args[2])
    except ValueError:
        await message.reply_text("from_id ו-to_id חייבים להיות מספרים שלמים")
        return
    if to_id < from_id:
        await message.reply_text("to_id חייב להיות גדול או שווה ל-from_id")
        return
    if (to_id - from_id) > 20000:
        await message.reply_text("הטווח גדול מדי (מקסימום 20000 בסריקה אחת) - פצלי לכמה קריאות")
        return

    status = await message.reply_text(f"⏳ סורק הודעות {from_id}-{to_id}...")
    results = []
    ids = list(range(from_id, to_id + 1))
    BATCH = 200
    for i in range(0, len(ids), BATCH):
        batch_ids = ids[i:i + BATCH]
        try:
            msgs = await bot_client.get_messages(chat_id, batch_ids)
        except FloodWait as e:
            await asyncio.sleep(e.value)
            try:
                msgs = await bot_client.get_messages(chat_id, batch_ids)
            except Exception as e2:
                log.warning("נכשל שוב אחרי FloodWait ב-batch %d-%d: %s", batch_ids[0], batch_ids[-1], e2)
                continue
        except Exception as e:
            log.warning("שגיאה בשליפת batch %d-%d: %s", batch_ids[0], batch_ids[-1], e)
            continue
        if not isinstance(msgs, list):
            msgs = [msgs]
        for msg in msgs:
            if not msg or getattr(msg, "empty", False):
                continue
            media = msg.video or msg.audio or msg.document or msg.video_note
            if not media:
                continue
            caption = (msg.caption or "").strip()
            file_name = getattr(media, "file_name", None) or caption or f"file_{msg.id}"
            episode = detect_episode(file_name, caption)
            stream_url = f"{BASE_URL}/stream/{chat_id}/{msg.id}"
            results.append({
                "message_id": msg.id,
                "file_name": file_name,
                "caption": caption,
                "episode": episode,
                "url": stream_url,
            })
        if (i // BATCH) % 5 == 0:
            try:
                await status.edit_text(f"⏳ נסרקו {min(i + BATCH, len(ids))}/{len(ids)}, נמצאו {len(results)} קבצים עד כה...")
            except Exception:
                pass

    # מיון: קודם אלה עם פרק מזוהה (לפי מספר), ואחריהם אלה בלי זיהוי בסוף
    results.sort(key=lambda r: (r["episode"] is None, int(r["episode"]) if r["episode"] else 0))

    out_path = DATA_DIR / f"scan_{chat_id}_{from_id}_{to_id}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    identified = sum(1 for r in results if r["episode"])
    await status.edit_text(
        f"✅ סריקה הושלמה!\n\n"
        f"נבדקו {len(ids)} מספרי הודעה, נמצאו {len(results)} קבצי מדיה.\n"
        f"{identified} מתוכם עם מספר פרק שזוהה אוטומטית, {len(results) - identified} בלי זיהוי.\n\n"
        f"שולח קובץ JSON מסודר עם הכל..."
    )
    await client.send_document(
        chat_id, str(out_path),
        caption=f"📊 {len(results)} קבצים, {identified} עם פרק מזוהה"
    )

# ── גיבוי תקופתי לקובץ ה-session ───────────────────────────────────────────────
# בניגוד ל-progress.json/history.json שנשמרים ביוזמת המשתמש (save_json קוראת
# ל-backup_to_dataset אוטומטית), קובץ ה-session מתעדכן ברקע ע"י Pyrogram
# (peer cache) בלי שום "hook" טבעי לתפוס — לכן גיבוי על טיימר קבוע.
SESSION_BACKUP_INTERVAL_SECS = 300

async def backup_session_periodically():
    while True:
        await asyncio.sleep(SESSION_BACKUP_INTERVAL_SECS)
        if SESSION_FILE.exists():
            await asyncio.to_thread(backup_to_dataset, f"{SESSION_NAME}.session", SESSION_FILE)
            log.info("💾 גובה session ל-Dataset")

# ── Keep-alive ────────────────────────────────────────────────────────────────

async def keep_alive():
    await asyncio.sleep(30)
    while True:
        try:
            async with httpx.AsyncClient() as c:
                await c.get(f"{BASE_URL}/ping", timeout=10)
                log.info("Keep-alive ✅")
        except Exception as e:
            log.warning("Keep-alive failed: %s", e)
        await asyncio.sleep(300)

# ── Watchdog: מזהה חיבור טלגרם תקוע ומאתחל את השרת לבד ────────────────────────
# הבעיה שקרתה בפועל: חיבור ה-MTProto הפנימי של Pyrogram נתקע (נשאר "תלוי"
# בלי שגיאה גלויה) - אבל זה לא הפיל את שאר ה-FastAPI, אז keep_alive() למעלה
# המשיך לראות /ping עונה תקין ולחשוב שהכל בסדר, בעוד כל בקשת /stream נתקעה
# לנצח בלי תשובה בכלל. הפתרון: בדיקה תקופתית אמיתית מול טלגרם (get_me - קריאה
# קלה שדורשת תשובה אמיתית מהשרתים של טלגרם) עם timeout קשיח. אם היא נכשלת/
# נתקעת כמה פעמים ברצף - מניחים שהחיבור מת, ומפילים את התהליך בכוונה
# (os._exit) כדי ש-Hugging Face Spaces יקים מחדש קונטיינר נקי לבד - בדיוק מה
# שכפתור "Restart Space" הידני עושה, רק אוטומטית. לא מנסים "לתקן" את חיבור
# ה-Pyrogram מבפנים בלי restart מלא - זו הדרך היחידה שבדוקה בפועל (הכפתור
# הידני שכבר עבד).
WATCHDOG_CHECK_INTERVAL_SECS = 60
WATCHDOG_TIMEOUT_SECS = 25
# 3 כישלונות רצופים (ולא 2) לפני restart — כדי לא להרוג את התהליך על חסימת
# flood זמנית של טלגרם שמתפוגגת לבד. חסימה אמיתית תיכשל 3 פעמים ברצף בכל מקרה.
WATCHDOG_MAX_CONSECUTIVE_FAILURES = 3
# המתנה ארוכה לפני הבדיקה הראשונה — נותנת לכל הבוטים לעלות בהדרגה קודם
WATCHDOG_INITIAL_DELAY_SECS = 120
# תוך כמה שניות אחורה משיכה מוצלחת של בוט מהבריכה נחשבת עדות שטלגרם מגיב.
WATCHDOG_POOL_GRACE = int(os.environ.get("WATCHDOG_POOL_GRACE", "120"))


async def _restart_main_client() -> bool:
    """מרים את הלקוח הראשי מחדש. מחזיר True אם הוא עונה אחרי זה.

    זו הפעולה שה-Watchdog צריך לעשות *לפני* שהוא שוקל להפיל את השירות: אם רק
    ה-session של הבוט הראשי תקוע, בניית אחד חדשה לוקחת שניות ולא נוגעת ב-21
    בוטי הבריכה ולא בצופים שמנגנים באותו רגע.
    """
    try:
        await asyncio.wait_for(bot_client.stop(), timeout=20)
    except Exception:
        pass          # לקוח תקוע עלול להיתקע גם ב-stop; ממשיכים ל-start
    try:
        await asyncio.wait_for(bot_client.start(), timeout=60)
        await asyncio.wait_for(bot_client.get_me(), timeout=WATCHDOG_TIMEOUT_SECS)
        log.info("✅ Watchdog: הלקוח הראשי הורם מחדש ועונה — השירות ממשיך לרוץ")
        return True
    except Exception as e:
        log.error("⚠️ Watchdog: הרמת הלקוח הראשי נכשלה: %s: %s", type(e).__name__, e)
        return False


async def telegram_watchdog():
    """שומר על החיבור לטלגרם — אבל בלי להרוג את השירות על סמך בדיקה אחת.

    הגרסה הקודמת בדקה רק את `bot_client.get_me()`, ואחרי שלושה פספוסים הריצה
    `os._exit(1)`. היא נכתבה ל-Hugging Face Spaces, שם restart של הקונטיינר
    היה הדרך היחידה להתאושש. על ה-VPS, עם `Restart=always`, התוצאה היא שכל
    השירות נהרג — וכל 21 הבוטים צריכים לעלות מחדש, ~90 שניות שבהן הצופה מקבל
    אפס בייטים.

    נמדד בשרת ב-24/08 בשעה 21:25: שלושה פספוסים ב-25 שניות, `os._exit(1)`,
    `Scheduled restart job` — ובדיוק אז הצופה דיווח על תקיעה של חצי דקה עד
    דקה. כלומר "נתקע כל כמה דקות, צריך לצאת ולהיכנס" היה השירות שמפיל את
    עצמו, לא טלגרם ולא הבוטים.

    שני תיקונים:

    1. משיכה מוצלחת של *כל* בוט מהבריכה היא הוכחה שטלגרם מגיב. אם היא קרתה
       בדקותיים האחרונות, ה-ping של הבוט הראשי נתקע מסיבה מקומית (ה-session
       שלו, או event loop עמוס תחת הזרמה) — ואין שום סיבה להפיל את השירות.
    2. גם כשאין הוכחה כזו, קודם מרימים מחדש רק את הלקוח הראשי. הפלת התהליך
       נשארת המוצא האחרון, אחרי שגם זה נכשל.
    """
    consecutive_failures = 0
    await asyncio.sleep(WATCHDOG_INITIAL_DELAY_SECS)
    while True:
        try:
            await asyncio.wait_for(bot_client.get_me(), timeout=WATCHDOG_TIMEOUT_SECS)
            if consecutive_failures > 0:
                log.info("✅ Watchdog: החיבור לטלגרם חזר לענות")
            consecutive_failures = 0
        except Exception as e:
            consecutive_failures += 1
            log.error(
                "⚠️ Watchdog: החיבור לטלגרם לא הגיב תוך %ds (נסיון %d/%d): %s",
                WATCHDOG_TIMEOUT_SECS, consecutive_failures, WATCHDOG_MAX_CONSECUTIVE_FAILURES, e,
            )
            if consecutive_failures >= WATCHDOG_MAX_CONSECUTIVE_FAILURES:
                idle = time.time() - _last_pool_success
                if idle < WATCHDOG_POOL_GRACE:
                    log.warning(
                        "⚠️ Watchdog: הבוט הראשי לא עונה, אבל הבריכה סיפקה "
                        "בייטים לפני %.0f שניות — טלגרם מגיב, לא מפילים את "
                        "השירות. מרים רק את הלקוח הראשי.", idle)
                    await _restart_main_client()
                    consecutive_failures = 0
                elif await _restart_main_client():
                    consecutive_failures = 0
                else:
                    log.critical("💥 Watchdog: החיבור לטלגרם תקוע וגם הרמת הלקוח "
                                 "הראשי נכשלה - מפעיל restart אוטומטי לתהליך")
                    os._exit(1)
        await asyncio.sleep(WATCHDOG_CHECK_INTERVAL_SECS)

# ── Parallel download workers ────────────────────────────────────────────────
# צוואר הבקבוק שמדדנו: חיבור MTProto יחיד מושך מטלגרם ב-~0.17 MB/s בלבד,
# בעוד הרשת של השרת מסוגלת ל-12 MB/s. הפתרון: pool של כמה Client-ים של אותו
# בוט (Pyrogram מאשר מספר חיבורים במקביל לאותו בוט), שכל אחד מושך "רצועה"
# אחרת של הקובץ בו-זמנית — וכך רוחב-הפס האפקטיבי מוכפל במספר ה-workers.
# ה-workers האלה הם להורדה בלבד (no_updates=True) — רק ה-bot_client הראשי
# מטפל בהודעות נכנסות, כדי שלא תהיה כפילות בעיבוד.
# 2 workers עם session קבוע: כל אחד מתחבר פעם אחת בלבד (FLOOD_WAIT הוא חד-פעמי),
# ואז נשאר קבוע ונותן מקביליות מוכחת (~פי 2-3 מהיר יותר). ניתן לשנות דרך env.
NUM_DOWNLOAD_WORKERS = int(os.environ.get("NUM_DOWNLOAD_WORKERS", "0"))
BAND_TIMEOUT_SECS = 45
# גודל "חלון" משיכה מקבילה בהזרמה: כל חלון מפוצל בין ה-workers ונמשך במקביל.
# חלון גדול = פחות פתיחות-stream (שהן יקרות!) = תפוקה גבוהה יותר. חלון ראשון
# קטן = התחלה מהירה. pipeline מושך את החלון הבא בזמן ששולחים את הנוכחי.
PARALLEL_WINDOW_BYTES = int(os.environ.get("PARALLEL_WINDOW_BYTES", str(32 * 1024 * 1024)))
FIRST_WINDOW_BYTES = int(os.environ.get("FIRST_WINDOW_BYTES", str(4 * 1024 * 1024)))
download_workers: list[Client] = []

async def start_download_workers():
    # מדליקים את ה-workers אחד-אחד (לא בבת אחת): טלגרם דוחה כמה התחברויות
    # בו-זמנית עם אותו טוקן בוט. session קבוע (in_memory=False) → כל worker
    # מתחבר פעם אחת בלבד וברסטארט הבא רק מתחבר-מחדש מהר. ניסיונות חוזרים
    # לכל worker כדי לעמוד בכשלים זמניים.
    # ניסיון אחד בלבד לכל worker: אם ההתחברות נכשלת ב-FLOOD_WAIT, אין טעם
    # לנסות שוב מיד (רק מחמיר את החסימה). session קבוע → אחרי התחברות מוצלחת
    # אחת, הפעלות הבאות רק מתחברות-מחדש בלי auth חדש.
    for i in range(NUM_DOWNLOAD_WORKERS):
        w = Client(
            name=f"stream_worker_{i}",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            in_memory=False,      # session קבוע
            no_updates=True,      # הורדה בלבד
            workdir=str(DATA_DIR),
        )
        try:
            await asyncio.wait_for(w.start(), timeout=40)
            download_workers.append(w)
            log.info("✅ worker %d עלה (%d/%d פעילים)", i, len(download_workers), NUM_DOWNLOAD_WORKERS)
        except Exception as e:
            log.warning("⚠️ worker %d לא עלה (יתכן FLOOD_WAIT — ננסה בהפעלה הבאה): %s", i, e)
            try:
                await w.stop()
            except Exception:
                pass
        await asyncio.sleep(3)   # השהיה בין workers כדי לא להציף את ה-auth
    log.info("🚀 סה\"כ %d/%d download workers פעילים", len(download_workers), NUM_DOWNLOAD_WORKERS)

async def stop_download_workers():
    for w in download_workers:
        try:
            await w.stop()
        except Exception:
            pass
    download_workers.clear()

async def _worker_fetch_band(worker: Client, msg: Message,
                             offset_chunks: int, limit_chunks: int) -> int:
    """מושך רצועה של הקובץ (limit_chunks חתיכות של 1MB החל מ-offset_chunks)
    דרך worker נתון, ומחזיר כמה בייטים נמשכו בפועל.

    חשוב: מקבל את ה-Message כבר פתור מהבוט הראשי (שיש לו peer cache), במקום
    שכל worker יפתור בעצמו — worker עם session טרי לא מכיר את הצ'אט ונתקע.
    ה-file_id שבתוך ה-msg תקף לכל חיבור של אותו בוט, אז stream_media עובד."""
    total = 0
    async for chunk in worker.stream_media(msg, offset=offset_chunks, limit=limit_chunks):
        total += len(chunk)
    return total

@api.get("/speedtest/{chat_id}/{message_id}")
async def speedtest(chat_id: int, message_id: int, mb: int = 24, workers: int = 0):
    """מודד מהירות משיכה מקבילה מטלגרם. mb=כמה מגה למשוך, workers=כמה חיבורים
    (0 = כל ה-pool). דוגמה: /speedtest/8658294616/7669?mb=24&workers=4
    להשוואה מול חיבור יחיד: ?workers=1"""
    # פותרים את ההודעה פעם אחת דרך הבוט הראשי (הוא בעל ה-peer cache)
    msg = await fetch_message(chat_id, message_id)
    if not msg or not (msg.video or msg.audio or msg.document or msg.video_note):
        raise HTTPException(status_code=404, detail="No media found")

    pool = download_workers if download_workers else [bot_client]
    n = len(pool) if workers <= 0 else min(workers, len(pool))
    n = max(1, n)
    total_chunks = max(1, mb)                       # ~1MB לחתיכה
    per = (total_chunks + n - 1) // n               # חתיכות לכל worker
    t0 = time.time()
    tasks = []
    for i in range(n):
        off = i * per
        if off >= total_chunks:
            break
        lim = min(per, total_chunks - off)
        tasks.append(asyncio.wait_for(
            _worker_fetch_band(pool[i], msg, off, lim), timeout=BAND_TIMEOUT_SECS))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    elapsed = time.time() - t0
    downloaded = sum(r for r in results if isinstance(r, int))
    errors = [repr(r) for r in results if not isinstance(r, int)]
    speed = (downloaded / elapsed) if elapsed > 0 else 0
    return JSONResponse({
        "workers_used": len(tasks),
        "workers_available": len(download_workers),
        "downloaded_mb": round(downloaded / 1048576, 1),
        "seconds": round(elapsed, 2),
        "speed_mb_per_sec": round(speed / 1048576, 2),
        "errors": errors,
    })

async def _fetch_window(msg: Message, w_start: int, w_end: int) -> bytes:
    """מושך חלון [w_start, w_end) במלואו: מפצל אותו בין ה-workers, כל worker
    פותח stream *אחד* (בלי פתיחות חוזרות) ומושך את הרצועה שלו במלואה, ואז
    מחברים לפי הסדר. זו בדיוק השיטה שנתנה 4.65 MB/s בבדיקה — חיבור אחד לכל
    worker לכל חלון, ולא פתיחה מחדש כל כמה MB."""
    pool = download_workers if download_workers else [bot_client]
    n = len(pool)
    start_chunk = w_start // PYROGRAM_CHUNK_SIZE
    end_chunk = (w_end + PYROGRAM_CHUNK_SIZE - 1) // PYROGRAM_CHUNK_SIZE
    total_chunks = end_chunk - start_chunk
    if total_chunks <= 0:
        return b""
    per = (total_chunks + n - 1) // n

    async def _band(worker: Client, off_chunks: int, lim_chunks: int) -> bytes:
        buf = bytearray()
        async for chunk in worker.stream_media(msg, offset=off_chunks, limit=lim_chunks):
            buf.extend(chunk)
        return bytes(buf)

    tasks = []
    band_starts = []
    for i in range(n):
        off = start_chunk + i * per
        if off >= end_chunk:
            break
        lim = min(per, end_chunk - off)
        tasks.append(asyncio.ensure_future(
            asyncio.wait_for(_band(pool[i], off, lim), timeout=BAND_TIMEOUT_SECS)))
        band_starts.append(off * PYROGRAM_CHUNK_SIZE)

    parts = await asyncio.gather(*tasks)
    out = bytearray()
    for idx, part in enumerate(parts):
        band_start = band_starts[idx]
        lo = max(w_start, band_start) - band_start
        hi = min(w_end, band_start + len(part)) - band_start
        if lo < hi:
            out.extend(part[lo:hi])
    return bytes(out)

async def pool_stream_window(msg: Message, start_byte: int, end_byte: int) -> AsyncGenerator[bytes, None]:
    """מזרים [start_byte, end_byte) בחלונות גדולים מקביליים, עם pipeline: בזמן
    ששולחים חלון ללקוח, החלון הבא כבר נמשך ברקע — כך שאין המתנה בין חלונות.
    החלון הראשון קטן (התחלה מהירה), השאר גדולים (תפוקה גבוהה, מעט פתיחות)."""
    if end_byte <= start_byte:
        return
    pos = start_byte
    win = FIRST_WINDOW_BYTES
    w_end = min(end_byte, pos + win)
    next_task = asyncio.ensure_future(_fetch_window(msg, pos, w_end))
    cur_end = w_end
    while next_task is not None:
        try:
            data = await next_task
        except Exception as e:
            log.error("חלון משיכה נכשל ב-%d: %s", pos, e)
            return
        # מתחילים את החלון הבא *לפני* שמניבים את הנוכחי (pipeline)
        if cur_end < end_byte:
            win = PARALLEL_WINDOW_BYTES
            nxt_end = min(end_byte, cur_end + win)
            next_task = asyncio.ensure_future(_fetch_window(msg, cur_end, nxt_end))
            prev_end, cur_end = cur_end, nxt_end
        else:
            next_task = None
        if data:
            yield data

# ── משיכה מקבילה ללא-auth (שימוש חוזר ב-auth_key הקיים של הבוט) ───────────────
# הטכניקה של FastTelethon: פותחים כמה חיבורי media לאותו DC שמשתמשים ב-auth_key
# שכבר קיים לבוט הראשי — בלי auth.ImportBotAuthorization (מה שנחסם ב-FLOOD_WAIT).
# כל חיבור מושך חלק אחר של הקובץ ב-upload.GetFile במקביל. פותרים את החיבורים
# פעם אחת ושומרים ב-pool לפי DC.
MEDIA_CHUNK = 1024 * 1024
_media_sessions: dict = {}          # (bot_name, dc_id) -> {"born", "gen", "pool"}
# טלגרם סוגר חיבורים לא פעילים; מחזירים אותם לפני שהם מתים עלינו. זו רשת
# ביטחון בלבד — חיבור מת מתגלה ומוחלף דרך הכשל עצמו — ולכן הערך גבוה: מחזור
# תכוף מדי (240 שניות) ביטל את החימום, וכל צופה שנחת אחרי מחזור שילם בנייה
# מחדש של 4 חיבורים.
MEDIA_SESSION_TTL = int(os.environ.get("MEDIA_SESSION_TTL", "1800"))
# כמה זמן להשאיר בריכה שהוחלפה בחיים לפני סגירה, כדי לא לנתק משיכות שרצות
# עליה ברגע ההחלפה.
MEDIA_SESSION_GRACE = int(os.environ.get("MEDIA_SESSION_GRACE", "30"))
# נעילה *פר-בוט* ולא גלובלית: בניית חיבורים לוקחת כמה סבבי רשת, ונעילה אחת
# לכולם הפכה כל בנייה לתור שכל הצופים תקועים בו.
_media_sessions_locks: dict = {}
_media_gen_counter = itertools.count(1)

def _media_lock(key):
    lk = _media_sessions_locks.get(key)
    if lk is None:
        lk = _media_sessions_locks[key] = asyncio.Lock()
    return lk

async def _make_media_session(client, dc_id: int) -> Session:
    """חיבור media נוסף *לאותו לקוח* — עם ה-auth_key שכבר יש לו, בלי אימות מחדש."""
    test_mode = await client.storage.test_mode()
    home_dc = await client.storage.dc_id()
    if dc_id == home_dc:
        auth_key = await client.storage.auth_key()
    else:
        auth_key = await Auth(client, dc_id, test_mode).create()
    session = Session(client, dc_id, auth_key, test_mode, is_media=True)
    await session.start()
    if dc_id != home_dc:
        for _ in range(3):
            exported = await client.invoke(functions.auth.ExportAuthorization(dc_id=dc_id))
            try:
                await session.invoke(functions.auth.ImportAuthorization(
                    id=exported.id, bytes=exported.bytes))
                break
            except Exception as e:
                log.warning("ImportAuthorization ל-DC %d נכשל, מנסה שוב: %s", dc_id, e)
    return session

async def _stop_pool(pool):
    for sess in pool:
        try:
            await sess.stop()
        except Exception:
            pass


async def _retire_pool(pool):
    """סוגר בריכה שהוחלפה, אבל רק אחרי שהות. סגירה מיידית מנתקת משיכות שרצות
    עליה בדיוק ברגע ההחלפה — ואז הצופה מקבל כשל בגלל פעולת תחזוקה."""
    await asyncio.sleep(MEDIA_SESSION_GRACE)
    await _stop_pool(pool)


_media_building: set = set()

async def _fill_pool_bg(client, owner: str, dc_id: int, n: int):
    """משלים בריכה ברקע. הצופה לא ממתין לזה."""
    key = (owner, dc_id)
    try:
        async with _media_lock(key):
            ent = _media_sessions.get(key)
            if ent is None:
                ent = {"born": time.time(), "gen": next(_media_gen_counter), "pool": []}
                _media_sessions[key] = ent
            while len(ent["pool"]) < n:
                try:
                    ent["pool"].append(await _make_media_session(client, dc_id))
                except Exception as e:
                    log.error("יצירת media session ל-%s נכשלה: %s", owner, e)
                    break
    finally:
        _media_building.discard(key)


async def _refresh_pool_bg(client, owner: str, dc_id: int, n: int, old_ent: dict):
    """בונה *דור חדש* של חיבורים ברקע ומחליף את הישן בבת אחת, ואז מוציא את
    הישן לגמלאות (עם גרייס). קריטי: בלי זה, בריכה שפג תוקפה (מעל 30 דק') לא
    התחדשה אף פעם ב-block=False, וכל הזרמה נפלה למסלול הבוט האיטי לצמיתות —
    זה מה שגרם לסרט "להיתקע ולהיטען" אחרי חצי שעה."""
    key = (owner, dc_id)
    try:
        fresh = []
        for _ in range(n):
            try:
                fresh.append(await _make_media_session(client, dc_id))
            except Exception as e:
                log.error("רענון media session ל-%s נכשל: %s", owner, e)
                break
        if fresh:
            async with _media_lock(key):
                _media_sessions[key] = {"born": time.time(),
                                        "gen": next(_media_gen_counter),
                                        "pool": fresh}
            asyncio.create_task(_retire_pool(old_ent["pool"]))
            log.info("media pool ל-%s רוענן (%d חיבורים טריים)", owner, len(fresh))
    finally:
        _media_building.discard(key)


async def get_media_session_pool_gen(client, owner: str, dc_id: int, n: int,
                                     block: bool = True):
    """חיבורי media *פר-בוט*, עם מחזור לפי גיל. מחזיר (pool, gen).

    טלגרם סוגר חיבורים שלא בשימוש. גרסה קודמת שמרה אותם לנצח, ואז כל בקשה
    שנחתה על חיבור מת נתלתה עד ה-timeout והצופה קיבל אפס בייטים.

    ה-gen הוא מזהה הדור של הבריכה. הקורא מחזיר אותו ל-drop_media_sessions
    בזמן כשל, וכך רק *הראשון* שגילה את התקלה מחליף את החיבורים; מי שנכשל
    אחריו על אותו דור מקבל את הבריכה החדשה במקום להרוג גם אותה. בלי זה
    ארבעה צופים במקביל נכנסו ללולאת מוות — כל אחד הרג את החיבורים הטריים
    של האחרים ואף אחד לא סיים למשוך.
    """
    key = (owner, dc_id)
    now = time.time()
    old = None
    # block=False: לא בונים מול הצופה. בנייה של 4 חיבורים לוקחת שניות ארוכות,
    # והיא קרתה *לפני* הבייט הראשון — נמדד זמן-התחלה של 21 שניות ברגע שהבריכה
    # גדלה ל-16 בוטים והבקשות נחתו על בוטים שעוד לא נבנו. הבנייה עוברת לרקע
    # והבקשה הנוכחית נופלת למסלול הבוטים, שמגיש תוך שניות בודדות.
    if not block:
        ent = _media_sessions.get(key)
        if ent is not None and len(ent["pool"]) >= n:
            if (now - ent["born"]) <= MEDIA_SESSION_TTL:
                return ent["pool"][:n], ent["gen"]
            # פג תוקף (מעל 30 דק') — בונים דור חדש ברקע, אבל *עדיין מגישים את
            # הישן* (חי בגרייס) כדי לא ליצור תקיעה באמצע צפייה. הבקשה הבאה כבר
            # תקבל את החדש. בלי זה הזרמה של סרט ארוך נתקעה בדיוק אחרי חצי שעה.
            if key not in _media_building:
                _media_building.add(key)
                asyncio.create_task(_refresh_pool_bg(client, owner, dc_id, n, ent))
            return ent["pool"][:n], ent["gen"]
        if key not in _media_building:
            _media_building.add(key)
            asyncio.create_task(_fill_pool_bg(client, owner, dc_id, n))
        return [], None
    async with _media_lock(key):
        ent = _media_sessions.get(key)
        if ent and (now - ent["born"]) > MEDIA_SESSION_TTL:
            old, ent = ent["pool"], None
            _media_sessions.pop(key, None)
        if ent is None:
            ent = {"born": now, "gen": next(_media_gen_counter), "pool": []}
            _media_sessions[key] = ent
        pool = ent["pool"]
        while len(pool) < n:
            try:
                pool.append(await _make_media_session(client, dc_id))
            except Exception as e:
                log.error("יצירת media session ל-%s נכשלה: %s", owner, e)
                break
        result = (pool[:n], ent["gen"])
    if old:
        asyncio.create_task(_retire_pool(old))
    return result


async def get_media_session_pool(client, owner: str, dc_id: int, n: int) -> list:
    pool, _gen = await get_media_session_pool_gen(client, owner, dc_id, n)
    return pool


async def drop_media_sessions(owner: str, dc_id: int, gen=None):
    """מפיל את חיבורי ה-media של בוט מסוים — הבא בתור ייצור טריים.

    gen: הדור שהקורא עבד מולו. אם הבריכה כבר הוחלפה בינתיים (דור אחר) לא
    נוגעים בה — היא של מישהו אחר וכנראה תקינה.
    """
    key = (owner, dc_id)
    async with _media_lock(key):
        ent = _media_sessions.get(key)
        if ent is None or (gen is not None and ent["gen"] != gen):
            return
        _media_sessions.pop(key, None)
    asyncio.create_task(_retire_pool(ent["pool"]))


def _file_location(media):
    f = FileId.decode(media.file_id)
    return f.dc_id, raw_types.InputDocumentFileLocation(
        id=f.media_id,
        access_hash=f.access_hash,
        file_reference=f.file_reference,
        thumb_size="",
    )

async def _band_getfile(session: Session, location, start_byte: int, end_byte: int) -> int:
    """מושך [start_byte, end_byte) דרך session נתון ב-GetFile, מחזיר כמה בייטים נמשכו."""
    total = 0
    offset = (start_byte // MEDIA_CHUNK) * MEDIA_CHUNK
    while offset < end_byte:
        try:
            r = await session.invoke(functions.upload.GetFile(
                location=location, offset=offset, limit=MEDIA_CHUNK, precise=False))
        except FloodWait as e:
            await asyncio.sleep(e.value)
            continue
        chunk = getattr(r, "bytes", b"")
        if not chunk:
            break
        total += len(chunk)
        offset += len(chunk)
        if len(chunk) < MEDIA_CHUNK:
            break
    return total

@api.get("/speedtest2/{chat_id}/{message_id}")
async def speedtest2(chat_id: int, message_id: int, mb: int = 24, conn: int = 4):
    """בדיקת מהירות למשיכה מקבילה ללא-auth (חיבורים שמשתמשים ב-auth הקיים).
    דוגמה: /speedtest2/8658294616/7669?mb=24&conn=4"""
    try:
        msg = await fetch_message(chat_id, message_id)
        media = msg.video or msg.audio or msg.document or msg.video_note
        if not media:
            raise HTTPException(404, "no media")
        dc_id, location = _file_location(media)
        sessions = await get_media_session_pool(bot_client, "main", dc_id, conn)
        if not sessions:
            return JSONResponse({"error": "no media sessions could be created", "dc_id": dc_id})
        n = len(sessions)
        total_bytes = mb * 1024 * 1024
        per = (total_bytes + n - 1) // n
        t0 = time.time()
        tasks = []
        for i in range(n):
            s = i * per
            if s >= total_bytes:
                break
            e = min(total_bytes, s + per)
            tasks.append(_band_getfile(sessions[i], location, s, e))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.time() - t0
        downloaded = sum(r for r in results if isinstance(r, int))
        errors = [repr(r) for r in results if not isinstance(r, int)]
        speed = downloaded / elapsed if elapsed > 0 else 0
        return JSONResponse({
            "dc_id": dc_id,
            "connections": n,
            "downloaded_mb": round(downloaded / 1048576, 1),
            "seconds": round(elapsed, 2),
            "speed_mb_per_sec": round(speed / 1048576, 2),
            "errors": errors,
        })
    except Exception as e:
        log.exception("speedtest2 failed")
        return JSONResponse({"error": repr(e)}, status_code=500)

# ── Lifecycle ─────────────────────────────────────────────────────────────────

@api.on_event("startup")
async def startup():
    global _hls_relay_client
    restore_from_dataset()
    await bot_client.start()
    # http2=True: tv.embyil.tv (ולפחות ספקים דומים) עונים 200 עם ה-m3u8
    # האמיתי רק על HTTP/2 - על HTTP/1.1 (ברירת המחדל) הם מפנים (301) לדף
    # שבסוף מחזיר 404. דורש את חבילת h2 (pip install h2) - ליפול בעדינות
    # ל-HTTP/1.1 אם היא חסרה, כדי שלא תפיל את כל השרת על תלות אופציונלית.
    try:
        _hls_relay_client = httpx.AsyncClient(timeout=15, follow_redirects=True, http2=True)
    except ImportError:
        log.warning("חבילת h2 לא מותקנת - רלֵיי HLS ירוץ על HTTP/1.1 בלבד "
                     "(pip install h2 כדי לתקן; חלק מהמקורות דורשים HTTP/2)")
        _hls_relay_client = httpx.AsyncClient(timeout=15, follow_redirects=True)
    # הכל עולה בהדרגה ברקע כדי לא להציף את טלגרם בעשרות חיבורים בבת אחת (מה
    # שגרם לחסימת IP: כל הבוטים "לא עלה", Watchdog הרג את התהליך, ולולאת קריסה).
    asyncio.create_task(seed_content_if_empty())
    asyncio.create_task(keep_alive())
    asyncio.create_task(_hls_fix_reaper())   # סוגר ffmpeg של ערוצים ללא צופים
    asyncio.create_task(peer_retry_loop())   # מחזיר לפעולה בוטים ששכחו את הערוץ
    asyncio.create_task(revive_stream_pool())  # מרים מחדש בוטים עם session תקוע
    asyncio.create_task(reap_idle_sessions())
    asyncio.create_task(backup_session_periodically())
    asyncio.create_task(staged_bot_startup())
    log.info("All systems ready ✅ BASE_URL=%s", BASE_URL)

async def staged_bot_startup():
    """מעלה את הבוטים בשלבים, לאט, כדי לא להציף את טלגרם בחיבורים בו-זמנית:
    1) בוט ההעלאה (הכי חשוב — קליטת תוכן)  2) workers להורדה  3) pool אחד-אחד.
    רק אחרי שהכל התייצב מפעילים את ה-Watchdog, כדי שלא יהרוג את התהליך בזמן
    שהבוטים עוד עולים."""
    try:
        await asyncio.sleep(4)                 # שהבוט הראשי יתייצב קודם
        await start_upload_bot()
        await asyncio.sleep(3)
        await start_download_workers()
        await asyncio.sleep(3)
        await start_stream_pool()
        await resolve_active_channel()         # קובע את הערוץ הפעיל (ריבוי ערוצים)
    except Exception as e:
        log.warning("staged_bot_startup: שגיאה בהעלאה מדורגת: %s", e)
    finally:
        # ה-Watchdog מתחיל רק עכשיו — אחרי שכל הבוטים ניסו לעלות
        asyncio.create_task(telegram_watchdog())

@api.on_event("shutdown")
async def shutdown():
    # כל שלב עטוף ב-try/except: אם קליינט של Pyrogram נכשל בעצירה (למשל
    # RuntimeError: "attached to a different loop") — לא רוצים שזה יפיל את כל
    # הכיבוי ויגרום ל-systemd להרוג בכוח (SIGKILL). מכבים כמה שאפשר ובשקט.
    async def _safe(coro, what):
        try:
            await asyncio.wait_for(coro, timeout=15)
        except Exception as e:
            log.warning("shutdown: %s נכשל: %s", what, e)
    await _safe(stop_download_workers(), "workers")
    await _safe(stop_stream_pool(), "pool")
    await _safe(stop_upload_bot(), "upload_bot")
    await _safe(bot_client.stop(), "bot_client")
    if _hls_relay_client:
        await _safe(_hls_relay_client.aclose(), "hls_client")
    # גיבוי אחרון-רגע — תופס גם peer-ים שנוספו בין הגיבוי התקופתי האחרון לכיבוי
    try:
        if SESSION_FILE.exists():
            backup_to_dataset(f"{SESSION_NAME}.session", SESSION_FILE)
    except Exception as e:
        log.warning("shutdown: גיבוי אחרון נכשל: %s", e)

if __name__ == "__main__":
    uvicorn.run("main:api", host="0.0.0.0", port=PORT, log_level="info")
