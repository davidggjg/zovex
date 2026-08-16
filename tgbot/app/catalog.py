"""מקור התוכן הראשוני — מאגר ZOVEX הקיים (/content/lite), עם מטמון וחיפוש.

הבוט מגיש תוכן משני מקורות: המאגר הגדול הקיים (11K+ פריטים) והתוכן החדש
מהערוצים המחוברים (db.search_content). כאן מטופל המאגר הקיים.
"""
import re
import time

import httpx
from loguru import logger

from .config import ZOVEX_CONTENT_URL, CATALOG_TTL

_STREAM_RE = re.compile(r"/stream/(-?\d+)/(\d+)")
_catalog: list = []
_at = 0.0


def norm(s) -> str:
    """נרמול חיפוש — זהה לאתר/אפליקציה: ניקוד, גרשיים, רווחים."""
    s = "" if s is None else str(s)
    s = s.lower()
    s = re.sub(r"[֑-ׇ]", "", s)
    s = re.sub(r"[\"'`׳״‘’“”]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def ref(item):
    """(chat_id, message_id) מהקישור של הפריט, או None."""
    for k in ("video_url", "video_id"):
        m = _STREAM_RE.search(str(item.get(k) or ""))
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


async def get_catalog() -> list:
    global _catalog, _at
    if _catalog and time.time() - _at < CATALOG_TTL:
        return _catalog
    try:
        async with httpx.AsyncClient(timeout=30) as cx:
            r = await cx.get(ZOVEX_CONTENT_URL)
            r.raise_for_status()
            data = r.json()
        if isinstance(data, list) and data:
            for e in data:
                e["_hay"] = norm(" ".join(str(e.get(k) or "") for k in
                                          ("title", "name", "series_name", "en_title", "original_title")))
            _catalog = data
            _at = time.time()
            logger.info(f"קטלוג ZOVEX נטען — {len(_catalog)} פריטים")
    except Exception as e:
        logger.error(f"טעינת קטלוג נכשלה: {e}")
    return _catalog


async def search(query: str):
    """מחזיר (movies, series_names) מהמאגר הקיים."""
    toks = norm(query).split()
    if not toks:
        return [], []
    catalog = await get_catalog()
    movies, series = [], {}
    for e in catalog:
        if e.get("is_live"):
            continue
        if not all(t in (e.get("_hay") or "") for t in toks):
            continue
        sn = e.get("series_name")
        if sn:
            series.setdefault(sn, e)
        elif ref(e):
            movies.append(e)
    return movies, list(series.values())


async def episodes(series_name: str):
    catalog = await get_catalog()
    eps = [e for e in catalog if e.get("series_name") == series_name and ref(e)]
    eps.sort(key=lambda e: ((e.get("season_number") or 0), (e.get("episode_number") or 0)))
    return eps
