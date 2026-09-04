#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מוסיף endpoint קריאה-בלבד שמחזיר את הגודל של כל מטמון גלובלי בקובץ.

## למה

נמדד: אחרי restart של zovex-bot, `VmRSS` היה 646MB. כמה שעות אחר כך, באותו
תהליך (בלי restart נוסף) — 896MB. עלייה של 250MB, בלי גידול מקביל במספר
ה-sockets הפתוחים (180 → 181) — כלומר זו לא דליפת חיבורי רשת, זו הצטברות
בתוך הזיכרון של פייתון עצמו.

בקובץ יש 27 מבני נתונים גלובליים (dict/list/set) שיכולים לצבור מצב. חלקם
מוגבלים במפורש בקוד (`_bot_msg_cache` עם `_BOT_MSG_CACHE_MAX=4000`,
`_hls_seg_cache` עם `HLS_SEG_CACHE_MAX=250MB`) — אלה כבר נבדקו ונראים תקינים
בעיצוב. אחרים (`_prewarm_seen`, `_hls_vcodec_cache`, `_payload_locks`,
`_media_sessions_locks` ועוד) לא נראתה להם שום תקרה או ניקוי כשעברתי על
הקובץ, אבל אי אפשר לדעת אם הם באמת גדלים בלי למדוד — ואין שום endpoint קיים
שחושף את הגודל שלהם. `/media-auth/stats` חושף רק את `_MEDIA_AUTH_KEYS`.

## מה התיקון עושה

מוסיף `/debug/caches`, שמחזיר JSON עם `len()` (ואצל `_hls_seg_cache` גם
`_seg_cache_bytes()` בפועל) של כל אחד מהמבנים. **לא נוגע בשום קוד קיים** —
רק קורא ערכים שכבר שם. אין דריסה, אין סיכון לפגוע בלוגיקת ההזרמה.

    python3 add_mem_debug.py --check
    python3 add_mem_debug.py && systemctl restart zovex-bot
    python3 add_mem_debug.py --undo

## איך קוראים את התוצאה

    curl -s http://127.0.0.1:8000/debug/caches | python3 -m json.tool

מדד ישר מיד אחרי restart, ואז שוב אחרי כמה שעות תחת עומס דומה. מבנה שהמספר
שלו גדל בהתמדה ולא מתייצב הוא החשוד — שם צריך להוסיף תקרה/ניקוי, בדיוק כמו
שכבר נעשה ל-`_bot_msg_cache` ו-`_hls_seg_cache`.
"""
import datetime, glob, os, pathlib, py_compile, shutil, sys, tempfile

TARGET = pathlib.Path("/opt/zovex-bot/main.py")
DONE_MARK = "_MEM_DEBUG_INSTALLED"

# כל שם כאן אומת ישירות מול הקובץ שבשרת (לא מהריפו) ב-04/09, עם grep.
NEEDED = [
    "api = FastAPI",
    "_stream_bots: list = []",
    "_peer_errors: dict = {}",
    "_bot_msg_cache: dict = {}",
    "_band_timeouts: dict = {}",
    "_rate_buckets: dict = {}",
    "_edge_filling: set = set()",
    "_prewarm_seen: dict = {}",
    "_hls_manifest_cache: dict = {}",
    "_hls_segment_inflight: dict = {}",
    "_hls_seg_cache: dict = {}",
    "_hls_prefetching: set = set()",
    "_relay_learned_hosts: dict = {}",
    "_hls_fix: dict = {}",
    "_hls_vcodec_cache: dict = {}",
    "_auth_fails: dict = {}",
    "_pending_uploads: dict = {}",
    "_awaiting_name: dict = {}",
    "_JSON_CACHE: dict = {}",
    "_payload_locks: dict = {}",
    "_media_sessions: dict = {}",
    "_media_sessions_locks: dict = {}",
    "_media_building: set = set()",
    "_saved_jobs: dict = {}",
    "_saved_tasks: set = set()",
    "def _seg_cache_bytes() -> int",
    "HLS_SEG_CACHE_MAX",
]

BLOCK = r'''

# ── חשיפת גודל מטמונים גלובליים (קריאה בלבד) ────────────────────────────────
# נמדד: RSS עלה ב-250MB בין שני מדדים באותו תהליך בלי restart, בזמן שמספר
# ה-sockets הפתוחים כמעט לא זז — כלומר זו הצטברות בזיכרון פייתון, לא דליפת
# חיבורי רשת. אין endpoint קיים שמראה את הגודל של כל אחד מ-27 מבני הנתונים
# הגלובליים בקובץ, אז אי אפשר לדעת איזה מהם אשם בלי לנחש. זה מוסיף רק
# תצפית — לא נוגע בשום התנהגות קיימת.
_MEM_DEBUG_INSTALLED = True


@api.get("/debug/caches")
async def debug_caches():
    """גודל כל מטמון/בריכה גלובלית בתהליך, לאבחון דליפות זיכרון."""
    media_conns = 0
    try:
        media_conns = sum(len(v.get("pool", [])) for v in _media_sessions.values())
    except Exception:
        pass
    return {
        "stream_bots": len(_stream_bots),
        "peer_errors": len(_peer_errors),
        "bot_msg_cache": len(_bot_msg_cache),
        "band_timeouts": len(_band_timeouts),
        "rate_buckets": len(_rate_buckets),
        "edge_filling": len(_edge_filling),
        "prewarm_seen": len(_prewarm_seen),
        "hls_manifest_cache": len(_hls_manifest_cache),
        "hls_segment_inflight": len(_hls_segment_inflight),
        "hls_seg_cache_entries": len(_hls_seg_cache),
        "hls_seg_cache_bytes": _seg_cache_bytes(),
        "hls_seg_cache_max_bytes": HLS_SEG_CACHE_MAX,
        "hls_prefetching": len(_hls_prefetching),
        "relay_learned_hosts": len(_relay_learned_hosts),
        "hls_fix": len(_hls_fix),
        "hls_vcodec_cache": len(_hls_vcodec_cache),
        "auth_fails": len(_auth_fails),
        "pending_uploads": len(_pending_uploads),
        "awaiting_name": len(_awaiting_name),
        "json_cache": len(_JSON_CACHE),
        "payload_locks": len(_payload_locks),
        "media_sessions_pools": len(_media_sessions),
        "media_sessions_locks": len(_media_sessions_locks),
        "media_sessions_total_conns": media_conns,
        "media_building": len(_media_building),
        "saved_jobs": len(_saved_jobs),
        "saved_tasks": len(_saved_tasks),
    }
'''


def _fail(msg):
    print("❌ " + msg)
    print("   לא שונה כלום.")
    sys.exit(1)


def main():
    if not TARGET.exists():
        _fail(f"לא נמצא {TARGET}")
    src = TARGET.read_text(encoding="utf-8")

    if DONE_MARK in src:
        print("✓ כבר מוחל. אין מה לעשות.")
        return

    missing = [n for n in NEEDED if n not in src]
    if missing:
        _fail("חסרים בקובץ שבשרת: " + ", ".join(missing))

    out = src.rstrip("\n") + "\n" + BLOCK

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as t:
        t.write(out)
        tmp = t.name
    try:
        py_compile.compile(tmp, doraise=True)
    except py_compile.PyCompileError as e:
        os.unlink(tmp)
        _fail(f"הקוד המתוקן לא מתקמפל: {e}")
    os.unlink(tmp)

    if "--check" in sys.argv:
        print("✓ הפאץ' מתאים לקובץ ועובר קומפילציה. לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-memdebug-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print("✅ הוחל. נוסף /debug/caches (שום שורה קיימת לא שונתה).")
    print(f"   גיבוי: {os.path.basename(bak)}")
    print()
    print("   הרץ:   systemctl restart zovex-bot")
    print("   בדיקה: curl -s http://127.0.0.1:8000/debug/caches | python3 -m json.tool")
    print("   נסיגה: python3 add_mem_debug.py --undo")


def undo():
    baks = sorted(glob.glob(str(TARGET) + ".bak-memdebug-*"))
    if not baks:
        _fail("לא נמצא גיבוי")
    shutil.copy2(baks[-1], TARGET)
    print(f"↩️  שוחזר מ-{os.path.basename(baks[-1])}")
    print("   הרץ:  systemctl restart zovex-bot")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else main()
