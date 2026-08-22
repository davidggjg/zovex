"""מחיל על השרת החי את ה-offload של בניית הקטלוג ל-thread.

הרקע: כל השרת רץ על event-loop יחיד בתהליך אחד (uvicorn בלי workers — הכרחי
כי קליינטי טלגרם מחזיקים session/loop אחד). הזרמת הווידאו וגם נקודות /content*
חולקות את אותו loop. בניית הקטלוג (טעינת 10MB, חתימת ~11k קישורים, json.dumps,
gzip) רצה סינכרונית על ה-loop — ולכן הבקשה הראשונה לכל גרסת-תוכן הקפיאה את כל
השרת ל~1-2ש, וגם הנגן נתקע. כאן מעבירים את הבנייה ל-asyncio.to_thread.

בטיחות: גיבוי לפני, py_compile אחרי, ואם משהו נכשל — שחזור אוטומטי. הסקריפט
אידמפוטנטי: אם כבר הוחל, הוא מזהה ומדלג.

הרצה על השרת:
    sudo /opt/zovex-bot/venv/bin/python /opt/zovex-bot/patch_loop_offload.py
    # ואז:  sudo systemctl restart zovex-bot
"""
import py_compile
import shutil
import sys
import time
import pathlib

LIVE = pathlib.Path("/opt/zovex-bot/main.py")

# ── כל תיקון: (תיאור, טקסט-ישן, טקסט-חדש). אם הישן לא נמצא אבל החדש כבר שם —
# מדלגים (כבר הוחל). אם שניהם לא נמצאים — עוצרים, כי הקובץ החי שונה מהצפוי.

OLD_CACHED = '''def _cached_payload(key: str, ver: int, build, ttl: float = CONTENT_CACHE_TTL):
    """גוף מוכן למפתח נתון. build() נקרא רק כשהמטמון פג או שהתוכן השתנה."""
    now = time.time()
    c = _JSON_CACHE.get(key)
    if c and c["ver"] == ver and (now - c["built"]) < ttl:
        return c
    raw = json.dumps(build(), ensure_ascii=False).encode("utf-8")
    c = {"ver": ver, "built": now, "raw": raw,
         # רמה 5: כמעט אותו יחס דחיסה כמו 6 בכשליש מהזמן, וזה רץ פעם אחת
         "gz": gzip.compress(raw, 5) if len(raw) > 4096 else None}
    if len(_JSON_CACHE) >= _JSON_CACHE_MAX:
        _JSON_CACHE.pop(next(iter(_JSON_CACHE)), None)
    _JSON_CACHE[key] = c
    return c'''

NEW_CACHED = '''def _fresh(c, ver, ttl, now=None):
    return c and c["ver"] == ver and ((now or time.time()) - c["built"]) < ttl


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
        return _store_payload(key, entry)'''

OLD_LITE = '''        c = _cached_payload(key, ver,
                            lambda: _lite_items()[:limit] if limit else _lite_items())
        etag = f'W/"l{ver}-{limit}"'
        return _serve_cached(request, c, etag, {"X-Content-Version": str(ver)})
    # limit חריג — נבנה בלי לשמור
    items = _lite_items()[:limit]'''

NEW_LITE = '''        c = await _cached_payload_async(key, ver,
                            lambda: _lite_items()[:limit] if limit else _lite_items())
        etag = f'W/"l{ver}-{limit}"'
        return _serve_cached(request, c, etag, {"X-Content-Version": str(ver)})
    # limit חריג — נבנה בלי לשמור (עדיין ב-thread כדי לא לחסום את ה-loop)
    items = await asyncio.to_thread(lambda: _lite_items()[:limit])'''

OLD_LIVE = '''    c = _cached_payload("live", ver,
                        lambda: [e for e in _lite_items() if e.get("is_live")])'''

NEW_LIVE = '''    c = await _cached_payload_async("live", ver,
                        lambda: [e for e in _lite_items() if e.get("is_live")])'''

OLD_INDEX = '''def _items_by_id(ver: int) -> dict:
    now = time.time()
    if _item_index["ver"] != ver or (now - _item_index["built"]) >= CONTENT_CACHE_TTL:
        _item_index.update(ver=ver, built=now,
                           by_id={str(e.get("id")): e
                                  for e in _expand_urls(load_content())})
    return _item_index["by_id"]


@api.get("/content/item/{item_id}")
async def content_item(item_id: str):
    """פריט בודד עם כל השדות — משמש למשיכת התיאור כשפותחים סרט/סדרה."""
    e = _items_by_id(get_content_version()).get(item_id)'''

NEW_INDEX = '''def _item_index_fresh(ver: int) -> bool:
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
    e = (await _items_by_id_async(get_content_version())).get(item_id)'''

# מקדימים \n כדי ש-"def _content_response" לא יימצא כתת-מחרוזת בתוך
# "async def _content_response" (אחרת ריצה חוזרת תיצור "async async def").
OLD_CONTENT_RESP = '\ndef _content_response(request: Request) -> Response:'
NEW_CONTENT_RESP = '\nasync def _content_response(request: Request) -> Response:'

OLD_FULL_BUILD = '''    ver = get_content_version()
    c = _cached_payload("full", ver, lambda: _expand_urls(load_content()))
    return _serve_cached(request, c, f'W/"c{ver}"', {"X-Content-Version": str(ver)})'''
NEW_FULL_BUILD = '''    ver = get_content_version()
    c = await _cached_payload_async("full", ver, lambda: _expand_urls(load_content()))
    return _serve_cached(request, c, f'W/"c{ver}"', {"X-Content-Version": str(ver)})'''

OLD_CALL1 = '''    כותרת X-Content-Version מאפשרת לפאנל לדעת על איזו גרסה הוא עורך (optimistic lock)."""
    return _content_response(request)'''
NEW_CALL1 = '''    כותרת X-Content-Version מאפשרת לפאנל לדעת על איזו גרסה הוא עורך (optimistic lock)."""
    return await _content_response(request)'''

OLD_CALL2 = '''    """כינוי ל-/content בשם הקובץ שהאתר רגיל אליו (לקראת מעבר האתר לשרת)."""
    return _content_response(request)'''
NEW_CALL2 = '''    """כינוי ל-/content בשם הקובץ שהאתר רגיל אליו (לקראת מעבר האתר לשרת)."""
    return await _content_response(request)'''

PATCHES = [
    ("cache helpers → async offload", OLD_CACHED, NEW_CACHED),
    ("content_lite → await", OLD_LITE, NEW_LITE),
    ("content_live → await", OLD_LIVE, NEW_LIVE),
    ("item index → async", OLD_INDEX, NEW_INDEX),
    ("_content_response → async", OLD_CONTENT_RESP, NEW_CONTENT_RESP),
    ("full build → await", OLD_FULL_BUILD, NEW_FULL_BUILD),
    ("content_get caller → await", OLD_CALL1, NEW_CALL1),
    ("movies.json caller → await", OLD_CALL2, NEW_CALL2),
]


def main():
    if not LIVE.exists():
        print("❌ אין %s" % LIVE)
        sys.exit(1)
    src = LIVE.read_text(encoding="utf-8")

    # מזהים מה כבר הוחל: הסימן הוודאי הוא הפונקציה האסינכרונית.
    already = "_cached_payload_async" in src

    out = src
    applied, skipped, missing = [], [], []
    for name, old, new in PATCHES:
        if old in out:
            out = out.replace(old, new, 1)
            applied.append(name)
        elif new in out or (already and new.strip() and new.strip() in out):
            skipped.append(name)
        else:
            missing.append(name)

    if missing:
        print("❌ קטעים לא נמצאו בקובץ החי (אולי כבר שונה ידנית):")
        for m in missing:
            print("   -", m)
        print("לא שוניתי כלום. בדוק ידנית לפני שממשיכים.")
        sys.exit(2)

    if not applied:
        print("✓ כבר מוחל — אין מה לשנות. (%d קטעים כבר קיימים)" % len(skipped))
        return

    # גיבוי → כתיבה → קומפילציה. בכשל: שחזור.
    bak = LIVE.with_name("main_before_loopoffload_%d.py" % int(time.time()))
    shutil.copy2(LIVE, bak)
    LIVE.write_text(out, encoding="utf-8")
    try:
        py_compile.compile(str(LIVE), doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak, LIVE)
        print("❌ קומפילציה נכשלה — שוחזר הגיבוי. שגיאה:\n%s" % e)
        sys.exit(3)

    print("✅ הוחל בהצלחה. שונו %d קטעים:" % len(applied))
    for a in applied:
        print("   +", a)
    if skipped:
        print("   (דילוג על %d שכבר היו מוחלים)" % len(skipped))
    print("גיבוי: %s" % bak.name)
    print("\nעכשיו הפעל מחדש:  sudo systemctl restart zovex-bot")


if __name__ == "__main__":
    main()
