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
from pyrogram.types import Message
from pyrogram.errors import FloodWait
from pyrogram.session import Session, Auth
from pyrogram.file_id import FileId
from pyrogram.raw import functions, types as raw_types
from pyrogram.handlers import MessageHandler
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

async def _pool_noop(client, message):
    pass  # handler ריק — רק כדי שהלקוח יקבל עדכוני ערוץ וישמור את ה-peer

async def start_stream_pool():
    if not STREAM_BOTS_FILE.exists():
        log.info("אין stream_bots.txt — pool בוטים לא פעיל")
        return
    tokens = [t.strip() for t in STREAM_BOTS_FILE.read_text().splitlines() if t.strip()]
    for i, tok in enumerate(tokens):
        try:
            c = Client(f"pool_bot_{i}", api_id=API_ID, api_hash=API_HASH, bot_token=tok,
                       in_memory=False, no_updates=False, workdir=str(DATA_DIR))
            c.add_handler(MessageHandler(_pool_noop, filters.channel))
            await asyncio.wait_for(c.start(), timeout=40)
            if STREAM_CHANNEL_ID:
                try:
                    await c.get_chat(STREAM_CHANNEL_ID)
                except Exception:
                    pass  # יזוהה כשיגיע פוסט חדש לערוץ
            _stream_bots.append({"client": c, "name": f"pool_{i}", "cooldown_until": 0.0})
            log.info("✅ pool bot %d עלה (%d פעילים)", i, len(_stream_bots))
        except Exception as e:
            log.warning("⚠️ pool bot %d לא עלה: %s", i, e)
        await asyncio.sleep(2)
    log.info("🚀 stream pool: %d בוטים פעילים", len(_stream_bots))

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

async def channel_get_media(chat_id, message_id):
    """מנסה כמה בוטים עד שאחד פותר את ההודעה. מחזיר (media) או None."""
    for _ in range(min(max(1, len(_stream_bots)), 5)):
        bot = await pick_stream_bot()
        if bot is None:
            return None
        try:
            msg = await asyncio.wait_for(
                bot["client"].get_messages(chat_id, message_id), timeout=20)
            media = msg.video or msg.audio or msg.document or msg.video_note
            if media:
                return media
        except FloodWait as e:
            _mark_choked(bot, e.value)
        except Exception as e:
            log.warning("channel_get_media שגיאה (%s): %s", chat_id, e)
            _mark_choked(bot, 30)
    return None

async def channel_stream_range(chat_id, message_id, start, end):
    """מזרים [start, end] מהערוץ דרך בוט מה-pool. בוט שנחנק בהתחלה → עוברים לבא."""
    CHUNK = PYROGRAM_CHUNK_SIZE
    pos = start
    for _ in range(min(max(1, len(_stream_bots)), 4)):
        bot = await pick_stream_bot()
        if bot is None:
            break
        try:
            msg = await asyncio.wait_for(
                bot["client"].get_messages(chat_id, message_id), timeout=20)
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
            channel_stream_range(chat_id, message_id, start, end),
            status_code=206, media_type=mime_type, headers=headers)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Disposition": disposition,
    }
    return StreamingResponse(
        channel_stream_range(chat_id, message_id, 0, file_size - 1),
        status_code=200, media_type=mime_type, headers=headers)

# ── Stream Route ──────────────────────────────────────────────────────────────

@api.get("/stream/{chat_id}/{message_id}")
async def stream(chat_id: int, message_id: int, request: Request):
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
WATCHDOG_TIMEOUT_SECS = 20
WATCHDOG_MAX_CONSECUTIVE_FAILURES = 2

async def telegram_watchdog():
    consecutive_failures = 0
    await asyncio.sleep(WATCHDOG_CHECK_INTERVAL_SECS)
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
    # ה-workers/pool עולים ברקע כדי לא לעכב את עליית השרת
    asyncio.create_task(start_download_workers())
    asyncio.create_task(start_stream_pool())
    asyncio.create_task(keep_alive())
    asyncio.create_task(reap_idle_sessions())
    asyncio.create_task(backup_session_periodically())
    asyncio.create_task(telegram_watchdog())
    log.info("All systems ready ✅ BASE_URL=%s", BASE_URL)

@api.on_event("shutdown")
async def shutdown():
    await stop_download_workers()
    await stop_stream_pool()
    await bot_client.stop()
    if _hls_relay_client:
        await _hls_relay_client.aclose()
    # גיבוי אחרון-רגע — תופס גם peer-ים שנוספו בין הגיבוי התקופתי האחרון לכיבוי
    if SESSION_FILE.exists():
        backup_to_dataset(f"{SESSION_NAME}.session", SESSION_FILE)

if __name__ == "__main__":
    uvicorn.run("main:api", host="0.0.0.0", port=PORT, log_level="info")
