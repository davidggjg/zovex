#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""משיכה מקדימה של מקטעי שידור חי.

נמדד: מקטע שמכיל 10 שניות וידאו נמשך מהספק ב-5 עד 16 שניות. מעל 10,
הנגן נופל אחורה ולא מתאושש. כאן מושכים את המקטעים הבאים ברקע בזמן
שהנגן עוד מעכל את רשימת השידור.

תוספת בלבד. בטוח להרצה חוזרת.
"""
import pathlib, py_compile, shutil, sys, time

P = pathlib.Path("/opt/zovex-bot/main.py")
s = P.read_text(encoding="utf-8")
done = []

if "_prefetch_from_manifest" in s:
    print("כבר מוחל — אין מה לעשות.")
    sys.exit(0)

PAIRS = [('_hls_segment_inflight: dict = {}\n\n\n', '_hls_segment_inflight: dict = {}\n\n# ── משיכה מקדימה של מקטעי שידור חי ───────────────────────────────────────────\n# נמדד מול הספק: משיכת manifest לוקחת 0.7–3.0ש ומקטע של 6 שניות עוד 1.6–3.7ש,\n# כך שסבב שלם כמעט משתווה לאורך המקטע עצמו. אין מרווח, וכל עיכוב מרוקן את\n# הבאפר של הנגן — זה מה שנראה למשתמש כ"נתקע ומסתובב".\n#\n# הרעיון: ברגע שנגן מבקש את ה-manifest אנחנו כבר יודעים מה המקטעים הבאים.\n# מושכים אותם ברקע מיד, כך שכשהנגן יבקש אותם הם כבר אצלנו וההמתנה לספק\n# יורדת מהנתיב הקריטי. בלי זה כל מקטע נמשך רק כשמבקשים אותו.\n_hls_seg_cache: dict = {}          # upstream_url -> (expires_at, bytes)\n_hls_prefetching: set = set()\nHLS_PREFETCH_COUNT = int(os.environ.get("HLS_PREFETCH_COUNT", "3"))\nHLS_SEG_TTL = float(os.environ.get("HLS_SEG_TTL", "45"))\nHLS_SEG_CACHE_MAX = int(os.environ.get("HLS_SEG_CACHE_MAX", str(250 * 1024 * 1024)))\n\n\ndef _seg_cache_bytes() -> int:\n    return sum(len(v[1]) for v in _hls_seg_cache.values())\n\n\ndef _seg_cache_evict():\n    """מפנה מקטעים שפגו, ואם עדיין חורגים — את הישנים ביותר."""\n    now = time.time()\n    for k in [k for k, v in _hls_seg_cache.items() if v[0] <= now]:\n        _hls_seg_cache.pop(k, None)\n    if _seg_cache_bytes() <= HLS_SEG_CACHE_MAX:\n        return\n    for k, _ in sorted(_hls_seg_cache.items(), key=lambda kv: kv[1][0]):\n        _hls_seg_cache.pop(k, None)\n        if _seg_cache_bytes() <= HLS_SEG_CACHE_MAX:\n            break\n\n\nasync def _prefetch_one(url: str):\n    if url in _hls_prefetching or url in _hls_seg_cache:\n        return\n    _hls_prefetching.add(url)\n    try:\n        r = await _hls_relay_client.get(url, headers=HLS_RELAY_UPSTREAM_HEADERS)\n        if r.status_code == 200 and r.content:\n            _hls_seg_cache[url] = (time.time() + HLS_SEG_TTL, r.content)\n            _seg_cache_evict()\n    except Exception:\n        pass                      # משיכה מקדימה היא בונוס; כשל בה לא מעניין\n    finally:\n        _hls_prefetching.discard(url)\n\n\ndef _prefetch_from_manifest(manifest_text: str, base_url: str):\n    """מדליק ברקע משיכה של המקטעים האחרונים ב-playlist (החדשים ביותר)."""\n    if HLS_PREFETCH_COUNT <= 0 or _hls_relay_client is None:\n        return\n    segs = [ln.strip() for ln in manifest_text.splitlines()\n            if ln.strip() and not ln.lstrip().startswith("#")]\n    for rel in segs[-HLS_PREFETCH_COUNT:]:\n        try:\n            asyncio.create_task(_prefetch_one(urljoin(base_url, rel)))\n        except Exception:\n            pass\n\n\n', 'פונקציות המשיכה המקדימה'), ('            rewritten = _rewrite_hls_manifest(resp.text, upstream_url)\n            _hls_manifest_cache[upstream_url] = (now + MANIFEST_CACHE_TTL, rewritten)\n', '            rewritten = _rewrite_hls_manifest(resp.text, upstream_url)\n            _hls_manifest_cache[upstream_url] = (now + MANIFEST_CACHE_TTL, rewritten)\n            # מדליקים משיכה מקדימה של המקטעים החדשים בעוד הנגן מעכל את ה-manifest\n            _prefetch_from_manifest(resp.text, upstream_url)\n', 'הפעלת המשיכה מתוך ה-manifest'), ('    async def _proxy_segment():\n        existing = _hls_segment_inflight.get(upstream_url)', '    async def _proxy_segment():\n        # אם המשיכה המקדימה כבר הביאה את המקטע — מגישים אותו מיד, בלי לגעת\n        # בספק בכלל. זה מה שמוציא את ההמתנה לספק מהנתיב הקריטי.\n        hit = _hls_seg_cache.get(upstream_url)\n        if hit and hit[0] > time.time():\n            yield hit[1]\n            return\n\n        existing = _hls_segment_inflight.get(upstream_url)', 'הגשת מקטע מהמטמון'), ('                async for chunk in resp.aiter_bytes():\n                    chunks.append(chunk)\n                    yield chunk\n        except httpx.HTTPError as e:', '                async for chunk in resp.aiter_bytes():\n                    chunks.append(chunk)\n                    yield chunk\n            # שומרים גם מקטע שנמשך רגיל: צופה נוסף שיגיע רגע אחריו (וכל\n            # ניסיון חוזר של אותו נגן) יקבל אותו מיידית במקום למשוך שוב.\n            if chunks:\n                _hls_seg_cache[upstream_url] = (\n                    time.time() + HLS_SEG_TTL, b"".join(chunks))\n                _seg_cache_evict()\n        except httpx.HTTPError as e:', 'שמירת מקטע שנמשך רגיל')]

for old, new, label in PAIRS:
    c = s.count(old)
    if c != 1:
        print("### '%s': נמצאו %d מופעים במקום 1 — לא שונה כלום ###" % (label, c))
        sys.exit(1)
for old, new, label in PAIRS:
    s = s.replace(old, new, 1)
    done.append(label)
bak = P.with_name("main_before_prefetch_%d.py" % time.time())
shutil.copy2(P, bak)
P.write_text(s, encoding="utf-8")
try:
    py_compile.compile(str(P), doraise=True)
except Exception as e:
    shutil.copy2(bak, P)
    print("### הקומפילציה נכשלה — שוחזר הגיבוי ###"); print(e); sys.exit(1)
print("הוחל:")
for d in done: print("   + " + d)
print("\n   גיבוי: " + bak.name)
print("\n   עכשיו:  sudo systemctl restart zovex-bot")
