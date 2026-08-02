"""
Telegram Stream-on-Demand Server
ארכיטקטורה מפושטת: בוט אחד, מחובר ב-MTProto (לא Bot API HTTP), שמזרים
ישירות מהצ'אט המקורי שבו הוא קיבל את הקובץ. אין userbot, אין
SESSION_STRING, אין copy/forward ל-Saved Messages.
"""

import os
import re
import sys
import json
import time
import hmac
import asyncio
import logging
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

# ── CORS — חיוני כדי שהאתר (GitHub Pages) יוכל לשלוח קריאות לשרת ──────────
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        remaining = end - pos + 1
        log.error("stream_session_range: ממלא %d בייטים ריקים (טלגרם לא הצליח לספק)", remaining)
        yield b"\x00" * remaining

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

def _is_bot_token(s: str) -> bool:
    return bool(re.match(r'^\d{5,}:[A-Za-z0-9_-]{20,}$', (s or "").strip()))

async def _start_one_pool_bot(i, tok: str):
    """מעלה חבר pool בודד (טוקן בוט או session string של חשבון) ומוסיף לרשימה."""
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
        await asyncio.wait_for(c.start(), timeout=40)
        if STREAM_CHANNEL_ID:
            try:
                await c.get_chat(STREAM_CHANNEL_ID)
            except Exception:
                pass  # יזוהה כשיגיע פוסט חדש לערוץ
        _stream_bots.append({"client": c, "name": f"{kind}_{i}", "cooldown_until": 0.0,
                             "token": tok, "kind": kind})
        log.info("✅ pool %s %s עלה (%d פעילים)", kind, i, len(_stream_bots))
    except Exception as e:
        log.warning("⚠️ pool member %s לא עלה: %s", i, e)

async def start_stream_pool():
    if not STREAM_BOTS_FILE.exists():
        log.info("אין stream_bots.txt — pool בוטים לא פעיל")
        return
    tokens = [t.strip() for t in STREAM_BOTS_FILE.read_text().splitlines() if t.strip()]
    # מעלים אחד-אחד עם הפוגה בין בוט לבוט. הצפת טלגרם בעשרות התחברויות בו-זמנית
    # (מה שקרה עם BATCH=8) גורמת לחסימת IP → כל הבוטים "לא עלה" ולולאת קריסה.
    # לאט ויציב עדיף. POOL_START_DELAY ניתן לכוונון דרך משתנה סביבה.
    delay = float(os.environ.get("POOL_START_DELAY", "4"))
    for i, tok in enumerate(tokens):
        await _start_one_pool_bot(i, tok)
        await asyncio.sleep(delay)
    log.info("🚀 stream pool: %d/%d בוטים פעילים", len(_stream_bots), len(tokens))
    asyncio.create_task(warm_stream_pool())

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
            log.info("🔥 חוממה מדיה: %s", b["name"])
        except Exception as e:
            log.warning("⚠️ חימום %s נכשל: %s", b.get("name"), e)
        await asyncio.sleep(0.4)
    log.info("🔥 pool מחומם — פליי ראשון יהיה מהיר")

async def stop_stream_pool():
    for b in _stream_bots:
        try:
            await b["client"].stop()
        except Exception:
            pass
    _stream_bots.clear()

async def pick_stream_bot():
    now = time.time()
    async with _stream_rr_lock:
        global _stream_rr
        healthy = [b for b in _stream_bots if b["cooldown_until"] < now]
        pool = healthy or _stream_bots
        if not pool:
            return None
        b = pool[_stream_rr % len(pool)]
        _stream_rr += 1
        return b

def _mark_choked(bot, seconds):
    bot["cooldown_until"] = time.time() + seconds
    log.warning("🥵 בוט %s נחנק — cooldown %ds", bot["name"], seconds)

# cache של אובייקט ההודעה — *per-bot*. קריטי: ה-file_reference בתוך ההודעה
# תקף רק בהקשר של הסשן שששלף אותו. שיתוף בין בוטים גרם ל-FILE_REFERENCE_EXPIRED
# (הקישור נשבר אחרי כמה שניות). לכן כל בוט מחזיק cache משלו, וכשה-reference
# פג — שולפים מחדש עם אותו בוט. ל-metadata (גודל/mime) אין בעיית reference.
_bot_msg_cache: dict = {}   # (bot_name, chat_id, message_id) -> (msg, expires_at)
_BOT_MSG_TTL = 120          # 2 דקות — מספיק לרצף בקשות Range של אותה צפייה

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
        _bot_msg_cache[key] = (msg, now + _BOT_MSG_TTL)
        return msg
    return None

async def channel_get_media(chat_id, message_id):
    """מחזיר את ה-media של ההודעה מהערוץ (metadata בלבד — אין בעיית reference)."""
    for _ in range(min(max(1, len(_stream_bots)), 5)):
        bot = await pick_stream_bot()
        if bot is None:
            return None
        try:
            msg = await _get_bot_msg(bot, chat_id, message_id)
            if msg:
                return msg.video or msg.audio or msg.document or msg.video_note
        except FloodWait as e:
            _mark_choked(bot, e.value)
        except Exception as e:
            log.warning("channel_get_media שגיאה (%s): %s", chat_id, e)
            _mark_choked(bot, 30)
    return None

async def channel_stream_range(chat_id, message_id, start, end):
    """מזרים [start, end] מהערוץ דרך בוט מה-pool. כל בוט שולף את ההודעה של עצמו
    (file_reference תקף רק בהקשר שלו). בוט שנחנק בהתחלה → עוברים לבא."""
    CHUNK = PYROGRAM_CHUNK_SIZE
    pos = start
    for _ in range(min(max(1, len(_stream_bots)), 4)):
        bot = await pick_stream_bot()
        if bot is None:
            break
        try:
            msg = await _get_bot_msg(bot, chat_id, message_id)
            if msg is None:
                _mark_choked(bot, 15)
                continue
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
            # ה-reference פג — נזרוק את ה-cache של הבוט ונתן לו סיבוב נוסף
            _bot_msg_cache.pop((bot["name"], chat_id, message_id), None)
            if pos > start:
                break   # כבר שלחנו בייטים — אי אפשר להתחיל מחדש
        except FloodWait as e:
            _mark_choked(bot, e.value)
            if pos > start:
                break   # כבר שלחנו בייטים — אי אפשר להחליף בוט באמצע
        except Exception as e:
            log.warning("channel stream שגיאה: %s", e)
            _mark_choked(bot, 30)
            if pos > start:
                break
    if pos <= end:
        yield b"\x00" * (end - pos + 1)

# ── הזרמה מקבילה (FastTelethon-style, בטוח) ─────────────────────────────────
# במקום צינור אחד ל-~4MB/s, מפצלים כל "חלון" של הסרט לכמה תת-טווחים שנמשכים
# בו-זמנית דרך כמה בוטים שונים מה-pool (כל בוט = חיבור נפרד לטלגרם), ומגישים
# לפי הסדר. זה עוקף את תקרת החיבור הבודד בלי לשמור שום דבר לדיסק (pass-through).
# נשלט ע"י STREAM_PARALLEL_PARTS (ברירת מחדל 1 = ההתנהגות הישנה, בלי סיכון).
STREAM_PARALLEL_PARTS  = int(os.environ.get("STREAM_PARALLEL_PARTS", "1"))
STREAM_PARALLEL_WINDOW = int(os.environ.get("STREAM_PARALLEL_WINDOW", str(16 * 1024 * 1024)))

async def _fetch_subrange(chat_id, message_id, lo, hi) -> bytes:
    """מושך את הבייטים [lo, hi] (כולל) דרך בוט מה-pool, עם ניסיונות על כמה בוטים.
    מחזיר תמיד בדיוק (hi-lo+1) בייטים (משלים באפסים אם נכשל — לשמירת Content-Length)."""
    CHUNK = PYROGRAM_CHUNK_SIZE
    need = hi - lo + 1
    for _ in range(min(max(1, len(_stream_bots)), 4)):
        bot = await pick_stream_bot()
        if bot is None:
            break
        try:
            msg = await _get_bot_msg(bot, chat_id, message_id)
            if msg is None:
                _mark_choked(bot, 15)
                continue
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
            if len(out) >= need:
                return bytes(out[:need])
            return bytes(out) + b"\x00" * (need - len(out))
        except FileReferenceExpired:
            _bot_msg_cache.pop((bot["name"], chat_id, message_id), None)
        except FloodWait as e:
            _mark_choked(bot, e.value)
        except Exception as e:
            log.warning("subrange שגיאה: %s", e)
            _mark_choked(bot, 30)
    return b"\x00" * need

async def channel_stream_range_parallel(chat_id, message_id, start, end):
    """גרסה מקבילה: מעבדת חלון-אחר-חלון, וכל חלון נמשך בכמה תת-טווחים במקביל."""
    parts = max(2, STREAM_PARALLEL_PARTS)
    window = max(STREAM_PARALLEL_WINDOW, parts * 512 * 1024)
    MIN_PART = 512 * 1024   # לא לפצל לחתיכות קטנות מדי
    pos = start
    while pos <= end:
        wend = min(pos + window - 1, end)
        total = wend - pos + 1
        n = max(1, min(parts, total // MIN_PART))
        step = -(-total // n)   # ceil
        ranges = []
        s = pos
        while s <= wend:
            e2 = min(s + step - 1, wend)
            ranges.append((s, e2))
            s = e2 + 1
        # מושכים את כל תת-הטווחים של החלון במקביל, ומגישים לפי הסדר
        results = await asyncio.gather(
            *[_fetch_subrange(chat_id, message_id, a, b) for a, b in ranges])
        for r in results:
            yield r
        pos = wend + 1

def _channel_range_gen(chat_id, message_id, start, end):
    """בורר בין הזרמה מקבילה (אם הופעלה) לרגילה."""
    if STREAM_PARALLEL_PARTS > 1 and len(_stream_bots) >= 2:
        return channel_stream_range_parallel(chat_id, message_id, start, end)
    return channel_stream_range(chat_id, message_id, start, end)

async def stream_from_channel(chat_id: int, message_id: int, request: Request):
    media = await channel_get_media(chat_id, message_id)
    if not media:
        raise HTTPException(status_code=503, detail="No media / no healthy bot")
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
        }
        return StreamingResponse(
            _channel_range_gen(chat_id, message_id, start, end),
            status_code=206, media_type=mime_type, headers=headers)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Disposition": disposition,
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
                             headers={"Content-Disposition": "inline"})

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
HLS_RELAY_ALLOWED_HOSTS = {"stream.mcquack.net"}

# לקוח משותף אחד עם keep-alive, לא לקוח חדש (וחיבור TCP חדש) בכל בקשה -
# תיקון: "מנגן שנייה ונתקע 10 שניות" קרה כי כל מקטע וידאו (כ-3.6MB, 5
# שניות תוכן) חיכה קודם להוריד את כל הקובץ מ-mcquack.net *ואז* להתחיל
# לשלוח אותו הלאה ללקוח - הכפלה של זמן ההמתנה בפועל (הורדה מלאה + שליחה
# מלאה, ברצף, לא במקביל), וזה בנוסף לתקורה של חיבור TCP חדש בכל פעם.
_hls_relay_client: Optional[httpx.AsyncClient] = None

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


def _is_hls_manifest(path: str) -> bool:
    return path.endswith(".m3u8")


def _rewrite_hls_manifest(text: str, base_url: str) -> str:
    out_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(line)
            continue
        absolute = urljoin(base_url, stripped)
        parsed = urlparse(absolute)
        if parsed.hostname not in HLS_RELAY_ALLOWED_HOSTS:
            out_lines.append(line)  # לא ידוע לנו - עדיף להשאיר כמו שהוא מלשבור לגמרי
            continue
        relayed = f"/hls-relay/{parsed.hostname}/{parsed.path.lstrip('/')}"
        if parsed.query:
            relayed += f"?{parsed.query}"
        out_lines.append(relayed)
    return "\n".join(out_lines)


@api.get("/hls-relay/{host}/{path:path}")
async def hls_relay(host: str, path: str, request: Request):
    check_hotlink(request)
    if host not in HLS_RELAY_ALLOWED_HOSTS:
        raise HTTPException(403, "host not allowed")
    upstream_url = f"http://{host}/{path}"
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
                resp = await _hls_relay_client.get(upstream_url)
            except httpx.HTTPError as e:
                raise HTTPException(502, f"hls_relay: upstream fetch failed - {e}")
            rewritten = _rewrite_hls_manifest(resp.text, upstream_url)
            _hls_manifest_cache[upstream_url] = (now + MANIFEST_CACHE_TTL, rewritten)
        return Response(
            content=rewritten,
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-cache"},
        )

    # מקטעי וידאו (.ts) - מוזרם (streaming) לצופה שביקש ראשון, כדי שיתחיל
    # לקבל בייטים ברגע שהם מגיעים מהמקור בלי לחכות למקטע השלם. אם מגיעה
    # בקשה מקבילה לאותו מקטע בדיוק (כמה צופים על אותו ערוץ) - היא "מצטרפת"
    # לזרימה הקיימת במקום לפתוח עוד בקשה זהה למקור.
    async def _proxy_segment():
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
            async with _hls_relay_client.stream("GET", upstream_url) as resp:
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    yield chunk
        except httpx.HTTPError as e:
            log.error("hls_relay: segment stream failed - %s", e)
        finally:
            done_event.set()
            _hls_segment_inflight.pop(upstream_url, None)

    return StreamingResponse(
        _proxy_segment(),
        media_type="video/mp2t",
        headers={"Cache-Control": "public, max-age=86400"},
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
    # מאחורי nginx/פרוקסי — קח את ה-IP האמיתי אם יש
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def check_panel_password(request: Request, password: str):
    """מאמת את סיסמת הפאנל עם הגנת brute-force. זורק HTTPException אם נכשל/חסום."""
    ip = _client_ip(request)
    now = time.time()
    fails = [t for t in _auth_fails.get(ip, []) if now - t < AUTH_LOCK]
    # אם יש יותר מדי כישלונות בחלון האחרון — חסום
    recent = [t for t in fails if now - t < AUTH_WINDOW]
    if len(recent) >= AUTH_MAX_FAILS:
        _auth_fails[ip] = fails
        raise HTTPException(status_code=429, detail="יותר מדי ניסיונות — נסה שוב בעוד כמה דקות")
    ok = bool(PANEL_PASSWORD) and hmac.compare_digest(password or "", PANEL_PASSWORD)
    if not ok:
        fails.append(now)
        _auth_fails[ip] = fails
        raise HTTPException(status_code=401, detail="סיסמה שגויה")
    # הצלחה — נקה כישלונות קודמים מאותו IP
    _auth_fails.pop(ip, None)

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
SIGN_TTL = int(os.environ.get("STREAM_SIGN_TTL", "21600"))  # 6 שעות — מספיק לסרט ארוך
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
    # קטע לטיני רציף (מילים באנגלית/ספרות) — עדיף ל-TMDB (בסיס נתונים אנגלי)
    latin = " ".join(re.findall(r"[A-Za-z0-9][A-Za-z0-9'&:!]*", base)).strip()
    if latin and latin.lower() != base.lower():
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
        if len(c) >= 2 and k not in seen:
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

async def tmdb_search(query: str) -> list:
    """מחזיר עד 6 תוצאות TMDB (movie/tv). לכל תוצאה: שם עברי לתצוגה (title),
    שם אנגלי (en_title) לקישור נקי, שנה, פוסטר, סוג. תמיד מושך גם עברית וגם
    אנגלית כדי שגם לתוכן עברי יהיה שם אנגלי לכתובת (slug)."""
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
                    })
    except Exception as e:
        log.warning("tmdb_search נכשל: %s", e)
    out = he_out or en_out          # עברית עדיפה לתצוגה; אם אין — אנגלית
    for o in out:                    # מצמידים שם אנגלי לכל תוצאה (לקישור)
        o["en_title"] = en_map.get((o["tmdb_id"], o["type"])) or o.get("original") or o["title"]
    return out[:6]

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
    """slug לכתובת: מעדיף שם אנגלי; נופל לתעתיק עברי; ואז ל-tmdb id."""
    base = _slug_base(en_title) or _slug_base(he_title)
    if base:
        return f"{base}-{tmdb_id}" if tmdb_id else base
    return f"movie-{tmdb_id}" if tmdb_id else ""

def _all_entries() -> list:
    """כל הכניסות לבדיקת כפילויות — גם התוכן החי (content.json) וגם ההעלאות
    הממתינות (new_uploads.json). ככה קובץ שכבר קיים באתר לא יתווסף שוב."""
    try:
        return load_content() + load_new_uploads()
    except Exception:
        return load_new_uploads()

def _norm_title(s: str) -> str:
    """נרמול שם להשוואה: אותיות קטנות, בלי גרשיים/סימני פיסוק/רווחים כפולים."""
    s = (s or "").lower()
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

def add_movie_entry(chosen: dict, channel_msg_id: int, file_unique_id: str = "", chat_id=None) -> dict:
    """בונה כניסת סרט חדשה מהבחירה ב-TMDB + הקישור לערוץ, ושומר ל-new_uploads.json.
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
    }
    lst = load_new_uploads()
    # מניעת כפילות — לפי (ערוץ+מזהה הודעה) וגם לפי הקובץ עצמו (file_unique_id)
    lst = [e for e in lst if not (e.get("channel_msg_id") == channel_msg_id and (e.get("channel_id") or STREAM_CHANNEL_ID) == chat_id)
           and not (file_unique_id and e.get("file_unique_id") == file_unique_id)]
    lst.append(entry)
    save_new_uploads(lst)
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
_SOURCE_TAGS = re.compile(r'^(?:זירה\s*מדיה|נתי\s*מדיה|נתי\s*מידע|zira\s*media|zira|nati\s*media)\s*', re.I)

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

def add_episode_entry(ep: dict, channel_msg_id: int, file_unique_id: str = "", chat_id=None) -> dict:
    """מוסיף פרק סדרה אוטומטית ל-new_uploads (בלי TMDB) — לאישור בפאנל + פוסטר.
    chat_id = הערוץ שאליו הועתק הקובץ (לתמיכה בריבוי ערוצים)."""
    chat_id = chat_id or STREAM_CHANNEL_ID
    entry = {
        "id": _slugify(ep["series"], "ep") + f"-s{ep['season']}e{ep['episode']}-{channel_msg_id}",
        "title": ep["series"],
        # slug נקי לכתובת הסדרה (תעתיק אם השם עברי) — כל הפרקים חולקים אותו
        "custom_slug": _slug_base(ep["series"]) or None,
        "series_name": ep["series"],
        "season_number": ep["season"],
        "episode_number": ep["episode"],
        "episode_title": "",
        "year": "",
        "category": "סדרות",
        "type": "telegram",
        "media_kind": "tv",
        "tmdb_id": 0,
        "video_url": stored_stream_url(channel_msg_id, chat_id),
        "thumbnail_url": "",
        "description": "",
        "channel_id": chat_id,
        "channel_msg_id": channel_msg_id,
        "file_unique_id": file_unique_id,
        "added_at": datetime.utcnow().isoformat(),
    }
    lst = load_new_uploads()
    lst = [e for e in lst if not (e.get("channel_msg_id") == channel_msg_id and (e.get("channel_id") or STREAM_CHANNEL_ID) == chat_id)
           and not (file_unique_id and e.get("file_unique_id") == file_unique_id)]
    lst.append(entry)
    save_new_uploads(lst)
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
            f" ({dup.get('year') or '?'})\n\n🔗 קישור סטרימינג:\n{sign_stream_url(expand_base(dup['video_url']))}")
        return
    status = await message.reply_text("⏳ מעלה לערוץ...")
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
    return th

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
    return load_app_version()

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

def save_content(arr: list):
    # גיבוי בטיחות לפני דריסה — content.json הוא מקור האמת, ורוצים אפשרות לשחזר
    # אם מישהו מחק/דרס בטעות. שומרים עד 10 גיבויים אחרונים.
    try:
        if CONTENT_FILE.exists():
            CONTENT_BAK_DIR.mkdir(parents=True, exist_ok=True)
            bak = CONTENT_BAK_DIR / f"content_{int(time.time())}.json"
            bak.write_text(CONTENT_FILE.read_text(encoding="utf-8"), encoding="utf-8")
            baks = sorted(CONTENT_BAK_DIR.glob("content_*.json"))
            for old in baks[:-10]:
                old.unlink(missing_ok=True)
    except Exception as e:
        log.warning("גיבוי content נכשל (ממשיכים בשמירה): %s", e)
    CONTENT_FILE.write_text(json.dumps(arr, ensure_ascii=False, indent=2), encoding="utf-8")

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
    await _start_one_pool_bot(uid, tok)          # מנסה להעלות אותו מיד
    if len(_stream_bots) <= before:
        raise HTTPException(status_code=400,
            detail="לא עלה — ודא שהוא חבר/אדמין בערוץ ושהטוקן/session נכון")
    try:                                          # נשמר לקובץ כדי לשרוד restart
        with open(STREAM_BOTS_FILE, "a", encoding="utf-8") as f:
            f.write(tok + "\n")
    except Exception as e:
        log.warning("שמירת טוקן לקובץ נכשלה: %s", e)
    return {"ok": True, "active": len(_stream_bots)}

class PoolPwReq(BaseModel):
    password: str

@api.post("/pool/list")
async def pool_list(req: PoolPwReq, request: Request):
    check_panel_password(request, req.password)
    now = time.time()
    bots = [{"name": b["name"],
             "status": "פעיל" if b["cooldown_until"] < now else "מתקרר",
             "kind": b.get("kind", "bot"),
             "token_tail": (b.get("token") or "")[-6:]} for b in _stream_bots]
    return {"active": len(_stream_bots), "in_file": len(_pool_tokens_in_file()), "bots": bots}

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
           "skipped": 0, "errors": 0, "msg": "מוכן", "started": 0}

def _pick_pool_userbot():
    for b in _stream_bots:
        if b.get("kind") == "user":
            return b
    return None

async def _bulk_import_worker(source, per_min: int, limit: int):
    ub = _pick_pool_userbot()
    if not ub:
        _import.update(running=False, msg="אין userbot ב-pool — הוסף חשבון-משתמש בטאב 'בוטים'")
        return
    client = ub["client"]
    _import.update(running=True, source=str(source), found=0, imported=0,
                   skipped=0, errors=0, msg="סורק את הערוץ...", started=int(time.time()))
    per_min = max(1, int(per_min or 5))     # כמה קבצים להעביר בכל דקה
    window_start = time.time()
    batch = 0
    # טוענים פעם אחת את מה שכבר קיים (מהיר — בלי לקרוא קבצים בכל פריט)
    seen_fuid, seen_ep = set(), set()
    for e in load_content() + load_new_uploads():
        if e.get("file_unique_id"):
            seen_fuid.add(e["file_unique_id"])
        if e.get("series_name") and e.get("episode_number") is not None:
            try:
                seen_ep.add((_norm_series(e["series_name"]), int(e.get("season_number") or 1), int(e["episode_number"])))
            except Exception:
                pass
    done = 0
    try:
        async for msg in client.get_chat_history(source):
            if not _import["running"]:
                _import["msg"] = "נעצר ידנית"; break
            media = msg.video or msg.document
            if not media:
                continue
            fname = getattr(media, "file_name", "") or (msg.caption or "") or ""
            if msg.document and not re.search(r'\.(mkv|mp4|avi|mov|webm|m4v|ts)$', fname, re.I):
                continue  # מסמך שאינו וידאו
            _import["found"] += 1
            fuid = getattr(media, "file_unique_id", "") or ""
            if fuid and fuid in seen_fuid:
                _import["skipped"] += 1; continue
            ep = parse_episode_info(fname)
            if ep:
                epkey = (_norm_series(ep["series"]), ep["season"], ep["episode"])
                if epkey in seen_ep:
                    _import["skipped"] += 1; continue
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
                    add_episode_entry(ep, new_id, fuid, dest)
                    seen_ep.add((_norm_series(ep["series"]), ep["season"], ep["episode"]))
                else:
                    _q, options = await smart_tmdb_search(fname)
                    if options:
                        add_movie_entry(options[0], new_id, fuid, dest)
                    else:
                        add_movie_entry({"title": clean_name(fname) or f"קובץ {new_id}",
                                         "year": "", "tmdb_id": 0, "type": "movie",
                                         "poster": "", "overview": ""}, new_id, fuid, dest)
                if fuid:
                    seen_fuid.add(fuid)
                _import["imported"] += 1
            except Exception as e:
                log.warning("import: הוספה נכשלה: %s", e); _import["errors"] += 1
            done += 1
            _import["msg"] = f"מייבא... ({_import['imported']} נוספו, {_import['skipped']} דילוגים)"
            if limit and done >= limit:
                _import["msg"] = f"הגיע למגבלה ({limit}) — הרץ שוב להמשך"; break
            # קצב: אחרי per_min העברות, ממתין עד סוף הדקה (טפטוף עדין + זמן לאשר)
            batch += 1
            if batch >= per_min:
                wait = max(0, 60 - (time.time() - window_start))
                _import["msg"] = (f"הועברו {per_min} קבצים בדקה זו — ממתין {int(wait)}ש "
                                  f"({_import['imported']} סה\"כ). אפשר לאשר בפאנל בינתיים.")
                slept = 0
                while slept < wait and _import["running"]:
                    await asyncio.sleep(1); slept += 1
                window_start = time.time(); batch = 0
        else:
            _import["msg"] = "הסתיים — עבר על כל הערוץ ✅"
    except Exception as e:
        log.exception("bulk import failed")
        _import["msg"] = f"שגיאה: {e}"
    _import["running"] = False

class ImportStartReq(BaseModel):
    password: str
    source: str
    per_min: int = 5     # כמה קבצים להעביר בכל דקה (טפטוף)
    limit: int = 0       # מגבלת סה"כ (0 = עד שהערוץ נגמר / עצירה ידנית)

@api.post("/import/start")
async def import_start(req: ImportStartReq, request: Request):
    check_panel_password(request, req.password)
    if _import["running"]:
        raise HTTPException(status_code=400, detail="ייבוא כבר רץ")
    src = (req.source or "").strip()
    if not src:
        raise HTTPException(status_code=400, detail="חסר מקור (שם/לינק/ID של הערוץ)")
    if not _pick_pool_userbot():
        raise HTTPException(status_code=400, detail="אין userbot ב-pool — הוסף חשבון-משתמש בטאב 'בוטים'")
    try:
        src_val = int(src)          # תמיכה ב-ID מספרי (-100...)
    except ValueError:
        src_val = src               # שם משתמש/לינק
    asyncio.create_task(_bulk_import_worker(src_val, int(req.per_min or 5), max(0, int(req.limit or 0))))
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

@api.get("/content")
async def content_get():
    """קריאה פומבית — האתר/הפאנל מושכים מכאן את כל התוכן (עם הכתובת האמיתית)."""
    return _expand_urls(load_content())

@api.get("/movies.json")
async def content_movies_alias():
    """כינוי ל-/content בשם הקובץ שהאתר רגיל אליו (לקראת מעבר האתר לשרת)."""
    return _expand_urls(load_content())

class ContentSaveReq(BaseModel):
    password: str
    movies: list

@api.post("/content/save")
async def content_save(req: ContentSaveReq, request: Request):
    """שמירת המערך המלא (list/create/update/delete/saveAll כולם עוברים דרך זה)."""
    check_panel_password(request, req.password)
    if not isinstance(req.movies, list):
        raise HTTPException(status_code=400, detail="movies חייב להיות מערך")
    # מכווצים את הכתובת שלנו חזרה ל-%BASE% כדי שהקישורים יישארו ניידים
    save_content(_collapse_urls(req.movies))
    return {"ok": True, "count": len(req.movies)}

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

async def telegram_watchdog():
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
                log.critical("💥 Watchdog: החיבור לטלגרם תקוע - מפעיל restart אוטומטי לתהליך")
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
_media_sessions: dict = {}          # dc_id -> list[Session]
_media_sessions_lock = asyncio.Lock()

async def _make_media_session(dc_id: int) -> Session:
    test_mode = await bot_client.storage.test_mode()
    home_dc = await bot_client.storage.dc_id()
    if dc_id == home_dc:
        auth_key = await bot_client.storage.auth_key()
    else:
        auth_key = await Auth(bot_client, dc_id, test_mode).create()
    session = Session(bot_client, dc_id, auth_key, test_mode, is_media=True)
    await session.start()
    if dc_id != home_dc:
        for _ in range(3):
            exported = await bot_client.invoke(functions.auth.ExportAuthorization(dc_id=dc_id))
            try:
                await session.invoke(functions.auth.ImportAuthorization(
                    id=exported.id, bytes=exported.bytes))
                break
            except Exception as e:
                log.warning("ImportAuthorization ל-DC %d נכשל, מנסה שוב: %s", dc_id, e)
    log.info("✅ נוצר media session ל-DC %d", dc_id)
    return session

async def get_media_session_pool(dc_id: int, n: int) -> list:
    async with _media_sessions_lock:
        pool = _media_sessions.get(dc_id, [])
        while len(pool) < n:
            try:
                pool.append(await _make_media_session(dc_id))
            except Exception as e:
                log.error("יצירת media session נכשלה: %s", e)
                break
        _media_sessions[dc_id] = pool
    return pool[:n]

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
        sessions = await get_media_session_pool(dc_id, conn)
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
    _hls_relay_client = httpx.AsyncClient(timeout=15)
    # הכל עולה בהדרגה ברקע כדי לא להציף את טלגרם בעשרות חיבורים בבת אחת (מה
    # שגרם לחסימת IP: כל הבוטים "לא עלה", Watchdog הרג את התהליך, ולולאת קריסה).
    asyncio.create_task(seed_content_if_empty())
    asyncio.create_task(keep_alive())
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
