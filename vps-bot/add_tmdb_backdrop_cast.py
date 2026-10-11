#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""add_tmdb_backdrop_cast — מוסיף לכל כותר חדש שעולה: תמונת רקע רחבה
(backdrop) לבאנר הגיבור, ורשימת שחקנים (שם+תמונה) לדף הפריט.

## רקע

הקוד הזה כבר נכתב בקומיט a98f3c9 בריפו — אבל main.py בריפו הוא רק
גיבוי חד-כיווני מהשרת (backup_to_git.sh, שרת→ריפו בלבד), ו-
deploy_all.sh מפרוס רשימה קבועה מראש של fix_*.py/add_*.py, לא מושך
את main.py עצמו. כלומר הקומיט ההוא פשוט אף פעם לא הגיע לשרת. זה
סקריפט פריסה תקני לאותו שינוי, בנוי אוטומטית מתוך ה-diff של הקומיט
(git diff 97cda3f..a98f3c9 -- vps-bot/main.py, 97cda3f = הגיבוי
האחרון הידוע של המצב החי) כדי שהטקסט — כולל התגובות בעברית — יהיה
זהה ב-100% למה שכבר נכתב, בלי הקלדה חוזרת שעלולה לטעות.

## מה זה מוסיף

* TMDB_IMG_BACKDROP/TMDB_IMG_PROFILE — קבועי URL לתמונות רחבות/פרופיל.
* tmdb_search מחזירה גם "backdrop" לכל תוצאה — TMDB כבר נותן את זה
  באותה תשובה, בלי קריאה נוספת.
* tmdb_credits(tmdb_id, media_type) — פונקציה חדשה: עד 10 שחקנים
  מובילים (שם+תמונה) לכותר שכבר נבחר. נכשלת בשקט לרשימה ריקה.
  נקראת פעם אחת לכותר, לא לכל אחד מ-6 המועמדים של tmdb_search.
* add_movie_entry הופכת ל-async (כדי לקרוא ל-tmdb_credits) — וכל 7
  מקומות הקריאה לה (אומתו כרגע: בדיוק 7, ראה validate) מקבלים await.
* add_episode_entry: year/backdrop_url/cast מגיעים מ-meta (שמגיע
  מ-_series_tmdb, שמושך cast פעם אחת לסדרה כולה, לא לכל פרק).
* _LITE_DROP מוסיפה "cast" לרשימת השדות הכבדים שמוצאים מ-/content/lite
  ונמשכים לפי דרישה מ-/content/item/{id} — בדיוק כמו description.
  backdrop_url *לא* מצטרף בכוונה: HeroBanner צריך אותו מראש בלי
  "רגע פתיחה", בניגוד ל-cast/description.

תוכן קיים (שהועלה *לפני* הפריסה הזו) לא נוגע — אין backfill. זה
מתחיל לפעול רק על כותרים חדשים מרגע ההפעלה.

## בטיחות

כל אחד מ-16 העוגנים אומת שהוא מופיע **פעם אחת בדיוק** בתוך main.py
החי שנשלף מהשרת (גיבוי 97cda3f) — לא מנחש. לפני כתיבה בפועל: בדיקת
קומפילציה מלאה לקובץ המתוקן (compile), ובדיקה שבכל הקובץ — לא רק
במה שנערך כאן — אין אף קריאה ל-add_movie_entry( בלי await (היא
הופכת ל-async; קריאה בלי await הייתה מחזירה coroutine במקום dict
ונשברת בשקט, בלי Exception גלוי). tmdb_credits נבדקת גם התנהגותית
מול httpx מדומה (מיון, חיתוך ל-10, דילוג על שם ריק, כשלים שקטים).

**דורש restart** — main.py נטען פעם אחת בעליית התהליך, בניגוד
לתיקוני content.json/admin.html הקודמים. הסקריפט לא מפעיל restart
לבד — בכוונה, כדי שתבחר מתי (לא תוך כדי שמישהו צופה):

    python3 add_tmdb_backdrop_cast.py --check
    python3 add_tmdb_backdrop_cast.py
    systemctl restart zovex-bot     # ← נדרש כדי שהשינוי ייכנס לתוקף
    python3 add_tmdb_backdrop_cast.py --revert    # (משחזר; restart שוב אחרי)
"""
import os
import re
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_add_tmdb_backdrop_cast"
MARK = "TMDB_IMG_BACKDROP"

EDITS = [
    ('קבועי תמונה (backdrop/profile)', 'STREAM_PUBLIC_BASE = os.environ.get("STREAM_PUBLIC_BASE", BASE_URL).rstrip("/")\nNEW_UPLOADS_FILE = DATA_DIR / "new_uploads.json"\nTMDB_IMG = "https://image.tmdb.org/t/p/w500"\n\n# ── קישורים ניידים (portable) — לא שומרים את הכתובת בתוך הקישור ────────────────\n# הקישורים שלנו נשמרים עם מציין-מקום %BASE% במקום הכתובת (IP/דומיין). השרת', 'STREAM_PUBLIC_BASE = os.environ.get("STREAM_PUBLIC_BASE", BASE_URL).rstrip("/")\nNEW_UPLOADS_FILE = DATA_DIR / "new_uploads.json"\nTMDB_IMG = "https://image.tmdb.org/t/p/w500"\n# גב (backdrop) רוחבי לבאנר הגיבור — w780 מאוזן בין איכות על רוחב מסך מלא לגודל\n# קובץ; w500 (TMDB_IMG) נועד לפוסטר הצר ונראה מטושטש כשנמתח לרוחב מלא.\nTMDB_IMG_BACKDROP = "https://image.tmdb.org/t/p/w780"\n# תמונת שחקן קטנה (אווטאר עגול) — w185 מספיק, ואין טעם למשוך w500 לעיגול 60px.\nTMDB_IMG_PROFILE = "https://image.tmdb.org/t/p/w185"\n\n# ── קישורים ניידים (portable) — לא שומרים את הכתובת בתוך הקישור ────────────────\n# הקישורים שלנו נשמרים עם מציין-מקום %BASE% במקום הכתובת (IP/דומיין). השרת', 1),
    ('tmdb_search: שדה backdrop', '                    bucket.append({\n                        "tmdb_id": tid, "type": mt, "title": title, "year": (date or "")[:4],\n                        "poster": (TMDB_IMG + it["poster_path"]) if it.get("poster_path") else "",\n                        "overview": (it.get("overview") or "")[:300],\n                        "original": orig,\n                        # מטא לזיהוי קטגוריה אוטומטי (ז\'אנר/מוצא/שפה)', '                    bucket.append({\n                        "tmdb_id": tid, "type": mt, "title": title, "year": (date or "")[:4],\n                        "poster": (TMDB_IMG + it["poster_path"]) if it.get("poster_path") else "",\n                        # רוחבי (סצנה/עמדה), לא הפוסטר הצר — לבאנר הגיבור. TMDB\n                        # כבר מחזיר אותו בתוצאת החיפוש עצמה, בלי קריאה נוספת.\n                        "backdrop": (TMDB_IMG_BACKDROP + it["backdrop_path"]) if it.get("backdrop_path") else "",\n                        "overview": (it.get("overview") or "")[:300],\n                        "original": orig,\n                        # מטא לזיהוי קטגוריה אוטומטי (ז\'אנר/מוצא/שפה)', 1),
    ('פונקציה חדשה tmdb_credits', "        out.sort(key=_yr_rank)\n    return out[:6]\n\n# ── זיהוי קטגוריה אוטומטי מ-TMDB (ז'אנר/מוצא/שפה) ────────────────────────────\n# מ-genre_ids של TMDB: 16=אנימציה, 27=אימה, 10751=משפחה, 10762=ילדים (טלוויזיה).\n# מוצא/שפה: JP/ja=יפני (אנימה), IL/he=ישראלי. מיפוי לקטגוריות האתר. הבחירה", '        out.sort(key=_yr_rank)\n    return out[:6]\n\nasync def tmdb_credits(tmdb_id, media_type: str) -> list:\n    """שחקנים מובילים (עד 10) לכותר שכבר אותר ב-TMDB (tmdb_id ידוע) — שם\n    ותמונת פרופיל. נקראת פעם אחת לכותר נבחר (לא לכל מועמד ב-tmdb_search,\n    שמחזיר עד 6 — זה היה מבזבז 5 קריאות שלא ישמשו לעולם).\n\n    נכשלת בשקט לרשימה ריקה: חוסר קאסט לא אמור לעצור או לעכב העלאה."""\n    if not TMDB_API_KEY or not tmdb_id or media_type not in ("movie", "tv"):\n        return []\n    try:\n        async with httpx.AsyncClient(timeout=12) as cx:\n            r = await cx.get(f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/credits",\n                              params={"api_key": TMDB_API_KEY})\n            if r.status_code != 200:\n                return []\n            cast = sorted(r.json().get("cast") or [], key=lambda c: c.get("order", 999))\n            out = []\n            for c in cast[:10]:\n                name = (c.get("name") or "").strip()\n                if not name:\n                    continue\n                prof = c.get("profile_path")\n                out.append({"name": name, "photo": (TMDB_IMG_PROFILE + prof) if prof else ""})\n            return out\n    except Exception as e:\n        log.warning("tmdb_credits נכשל (%s %s): %s", media_type, tmdb_id, e)\n        return []\n\n# ── זיהוי קטגוריה אוטומטי מ-TMDB (ז\'אנר/מוצא/שפה) ────────────────────────────\n# מ-genre_ids של TMDB: 16=אנימציה, 27=אימה, 10751=משפחה, 10762=ילדים (טלוויזיה).\n# מוצא/שפה: JP/ja=יפני (אנימה), IL/he=ישראלי. מיפוי לקטגוריות האתר. הבחירה', 1),
    ('add_movie_entry: async + קריאה ל-tmdb_credits', '    c, n = _dup_index()\n    return c["ep"].get(k) or n["ep"].get(k)\n\ndef add_movie_entry(chosen: dict, channel_msg_id: int, file_unique_id: str = "", chat_id=None,\n                    category: str = None, to_content: bool = False) -> dict:\n    """בונה כניסת סרט חדשה מהבחירה ב-TMDB + הקישור לערוץ.\n    to_content=False → שומר ל-new_uploads.json (ממתין לאישור).\n    to_content=True  → מוסיף ישירות ל-content.json (עולה לאתר) עם category.\n    שומר קישור נייד (%BASE%) — הכתובת האמיתית מוזרקת בזמן ההגשה/התצוגה.\n    chat_id = הערוץ שאליו הועתק הקובץ (לתמיכה בריבוי ערוצים)."""\n    chat_id = chat_id or STREAM_CHANNEL_ID\n    stream_url = stored_stream_url(channel_msg_id, chat_id)\n    en_title = chosen.get("en_title") or chosen.get("original") or chosen["title"]\n    entry = {\n        "id": _slugify(en_title, chosen["tmdb_id"]) + "-" + str(channel_msg_id),\n        "title": chosen["title"],', '    c, n = _dup_index()\n    return c["ep"].get(k) or n["ep"].get(k)\n\nasync def add_movie_entry(chosen: dict, channel_msg_id: int, file_unique_id: str = "", chat_id=None,\n                    category: str = None, to_content: bool = False) -> dict:\n    """בונה כניסת סרט חדשה מהבחירה ב-TMDB + הקישור לערוץ.\n    to_content=False → שומר ל-new_uploads.json (ממתין לאישור).\n    to_content=True  → מוסיף ישירות ל-content.json (עולה לאתר) עם category.\n    שומר קישור נייד (%BASE%) — הכתובת האמיתית מוזרקת בזמן ההגשה/התצוגה.\n    chat_id = הערוץ שאליו הועתק הקובץ (לתמיכה בריבוי ערוצים).\n\n    async (ולא עוד sync) כדי לקרוא ל-tmdb_credits כאן — פעם אחת, לכותר\n    שכבר נבחר, ולא לכל אחד מ-6 המועמדים שמחזיר tmdb_search."""\n    chat_id = chat_id or STREAM_CHANNEL_ID\n    stream_url = stored_stream_url(channel_msg_id, chat_id)\n    en_title = chosen.get("en_title") or chosen.get("original") or chosen["title"]\n    cast = await tmdb_credits(chosen.get("tmdb_id"), chosen.get("type") or "movie")\n    entry = {\n        "id": _slugify(en_title, chosen["tmdb_id"]) + "-" + str(channel_msg_id),\n        "title": chosen["title"],', 1),
    ('add_movie_entry: backdrop_url/cast ב-entry', '        "tmdb_id": chosen["tmdb_id"],\n        "video_url": stream_url,\n        "thumbnail_url": chosen.get("poster", ""),\n        "description": chosen.get("overview", ""),\n        "channel_id": chat_id,\n        "channel_msg_id": channel_msg_id,\n        "file_unique_id": file_unique_id,', '        "tmdb_id": chosen["tmdb_id"],\n        "video_url": stream_url,\n        "thumbnail_url": chosen.get("poster", ""),\n        # רוחבי לבאנר הגיבור — ראה ההסבר ליד TMDB_IMG_BACKDROP. ריק לתוכן\n        # ישן/בלי tmdb_id; הלקוח נופל חזרה לטיפול הקודם (blur+contain) אז.\n        "backdrop_url": chosen.get("backdrop", ""),\n        "description": chosen.get("overview", ""),\n        # שחקנים מובילים (שם+תמונה) — ריק כשאין TMDB_API_KEY/tmdb_id/קאסט\n        # ב-TMDB. הלקוח מסתיר את השורה כולה כשזה ריק, לא מציג משבצות ריקות.\n        "cast": cast,\n        "channel_id": chat_id,\n        "channel_msg_id": channel_msg_id,\n        "file_unique_id": file_unique_id,', 1),
    ('add_episode_entry: year מ-meta', '        "season_number": ep["season"],\n        "episode_number": ep["episode"],\n        "episode_title": "",\n        "year": "",\n        "category": category,\n        "type": "telegram",\n        "media_kind": "tv",', '        "season_number": ep["season"],\n        "episode_number": ep["episode"],\n        "episode_title": "",\n        # שנת עליית האוויר הראשונה של הסדרה (מ-TMDB, ברמת הסדרה כולה —\n        # לא לכל פרק בנפרד). ריק לסדרה לא-מזוהה, בדיוק כמו poster/overview.\n        "year": meta.get("year", ""),\n        "category": category,\n        "type": "telegram",\n        "media_kind": "tv",', 1),
    ('add_episode_entry: backdrop_url/cast ב-entry', '        "en_title": meta.get("en_title", ""),\n        "video_url": stored_stream_url(channel_msg_id, chat_id),\n        "thumbnail_url": meta.get("poster", ""),\n        "description": meta.get("overview", ""),\n        "channel_id": chat_id,\n        "channel_msg_id": channel_msg_id,\n        "file_unique_id": file_unique_id,', '        "en_title": meta.get("en_title", ""),\n        "video_url": stored_stream_url(channel_msg_id, chat_id),\n        "thumbnail_url": meta.get("poster", ""),\n        # ראה ההסבר המלא ליד add_movie_entry/TMDB_IMG_BACKDROP — אותם שדות,\n        # ברמת הסדרה: meta מגיע פעם אחת מה-cache של _series_tmdb, לא נמשך\n        # בנפרד לכל פרק.\n        "backdrop_url": meta.get("backdrop", ""),\n        "description": meta.get("overview", ""),\n        "cast": meta.get("cast") or [],\n        "channel_id": chat_id,\n        "channel_msg_id": channel_msg_id,\n        "file_unique_id": file_unique_id,', 1),
    ('await add_movie_entry — _handle_custom_name', '    options = await tmdb_search(name)\n    if not options:\n        # אין זיהוי — שומרים בשם המדויק שהוקלד\n        entry = add_movie_entry(\n            {"title": name, "year": "", "tmdb_id": 0, "type": "movie",\n             "poster": "", "overview": ""}, pending["channel_msg_id"],\n            pending.get("file_unique_id", ""), pending.get("dest_channel"))', '    options = await tmdb_search(name)\n    if not options:\n        # אין זיהוי — שומרים בשם המדויק שהוקלד\n        entry = await add_movie_entry(\n            {"title": name, "year": "", "tmdb_id": 0, "type": "movie",\n             "poster": "", "overview": ""}, pending["channel_msg_id"],\n            pending.get("file_unique_id", ""), pending.get("dest_channel"))', 1),
    ('await add_movie_entry — _handle_drive_upload (2 מקומות)', '            return\n        query, options = await smart_tmdb_search(fname)\n        if options:\n            entry = add_movie_entry(options[0], channel_msg_id, fuid, dest_channel)\n            await _edit(f"✅ נוסף לרשימת ההעלאות: {entry[\'title\']} ({entry.get(\'year\') or \'?\'}).\\nבדוק ואשר בפאנל.")\n        else:\n            entry = add_movie_entry(\n                {"title": query or fname, "year": "", "tmdb_id": 0, "type": "movie",\n                 "poster": "", "overview": ""}, channel_msg_id, fuid, dest_channel)\n            await _edit(f"✅ נוסף לרשימת ההעלאות בשם: {entry[\'title\']}.\\nבדוק ואשר בפאנל.")', '            return\n        query, options = await smart_tmdb_search(fname)\n        if options:\n            entry = await add_movie_entry(options[0], channel_msg_id, fuid, dest_channel)\n            await _edit(f"✅ נוסף לרשימת ההעלאות: {entry[\'title\']} ({entry.get(\'year\') or \'?\'}).\\nבדוק ואשר בפאנל.")\n        else:\n            entry = await add_movie_entry(\n                {"title": query or fname, "year": "", "tmdb_id": 0, "type": "movie",\n                 "poster": "", "overview": ""}, channel_msg_id, fuid, dest_channel)\n            await _edit(f"✅ נוסף לרשימת ההעלאות בשם: {entry[\'title\']}.\\nבדוק ואשר בפאנל.")', 1),
    ('await add_movie_entry — on_select (שמירה ללא זיהוי)', '        return\n    if idx == "save":\n        raw = pending.get("raw_name") or f"קובץ {pending[\'channel_msg_id\']}"\n        entry = add_movie_entry(\n            {"title": raw, "year": "", "tmdb_id": 0, "type": "movie",\n             "poster": "", "overview": ""}, pending["channel_msg_id"],\n            pending.get("file_unique_id", ""), pending.get("dest_channel"))', '        return\n    if idx == "save":\n        raw = pending.get("raw_name") or f"קובץ {pending[\'channel_msg_id\']}"\n        entry = await add_movie_entry(\n            {"title": raw, "year": "", "tmdb_id": 0, "type": "movie",\n             "poster": "", "overview": ""}, pending["channel_msg_id"],\n            pending.get("file_unique_id", ""), pending.get("dest_channel"))', 1),
    ('await add_movie_entry — on_select (אישור בחירה)', '                f"הוסף אותה ידנית בפאנל.")\n            await cq.answer("כבר קיים")\n            return\n    entry = add_movie_entry(chosen, pending["channel_msg_id"],\n                            pending.get("file_unique_id", ""), pending.get("dest_channel"))\n    _pending_uploads.pop(cmid, None)\n    poster_line = f"\\n🖼 {entry[\'thumbnail_url\']}" if entry["thumbnail_url"] else ""', '                f"הוסף אותה ידנית בפאנל.")\n            await cq.answer("כבר קיים")\n            return\n    entry = await add_movie_entry(chosen, pending["channel_msg_id"],\n                            pending.get("file_unique_id", ""), pending.get("dest_channel"))\n    _pending_uploads.pop(cmid, None)\n    poster_line = f"\\n🖼 {entry[\'thumbnail_url\']}" if entry["thumbnail_url"] else ""', 1),
    ('_series_tmdb: משיכת cast לסדרה', '        try:\n            opts = await tmdb_search(name)\n            tv = next((o for o in opts if o.get("type") == "tv"), None)\n        except Exception as e:\n            log.warning("import: חיפוש סדרה ב-TMDB נכשל: %s", e)\n        _series_cache[key] = tv', '        try:\n            opts = await tmdb_search(name)\n            tv = next((o for o in opts if o.get("type") == "tv"), None)\n            # קאסט נמשך כאן — פעם אחת לסדרה כולה, בזכות ה-cache שעוטף את\n            # הפונקציה הזאת — ולא בכל פרק (חלק מהסדרות כאן מאות פרקים;\n            # קריאת credits לכל אחד הייתה מכפילה בקשות TMDB בלי צורך).\n            # backdrop כבר יושב בתוך tv עצמו — tmdb_search מצרף אותו לכל\n            # תוצאה, אין קריאה נוספת בשבילו.\n            if tv and tv.get("tmdb_id"):\n                tv["cast"] = await tmdb_credits(tv["tmdb_id"], "tv")\n        except Exception as e:\n            log.warning("import: חיפוש סדרה ב-TMDB נכשל: %s", e)\n        _series_cache[key] = tv', 1),
    ('meta: backdrop/cast/year מ-tv', '                            en = tv.get("en_title") or tv.get("original") or tv.get("title")\n                            meta = {"poster": tv.get("poster", ""), "overview": tv.get("overview", ""),\n                                    "tmdb_id": tv.get("tmdb_id", 0), "en_title": en,\n                                    "custom_slug": _custom_slug(en, tv.get("title", ""), tv.get("tmdb_id"))}\n                            add_episode_entry(ep, new_id, fuid, dest, category=cat, meta=meta, to_content=True)\n                            _import["to_site"] += 1', '                            en = tv.get("en_title") or tv.get("original") or tv.get("title")\n                            meta = {"poster": tv.get("poster", ""), "overview": tv.get("overview", ""),\n                                    "tmdb_id": tv.get("tmdb_id", 0), "en_title": en,\n                                    "backdrop": tv.get("backdrop", ""), "cast": tv.get("cast") or [],\n                                    "year": tv.get("year", ""),\n                                    "custom_slug": _custom_slug(en, tv.get("title", ""), tv.get("tmdb_id"))}\n                            add_episode_entry(ep, new_id, fuid, dest, category=cat, meta=meta, to_content=True)\n                            _import["to_site"] += 1', 1),
    ('await add_movie_entry — bulk import (זוהה)', '                    elif options:\n                        ch = dict(options[0]); ch["year"] = ch.get("year") or ryear\n                        cat = _auto_category(ch)\n                        add_movie_entry(ch, new_id, fuid, dest, category=cat, to_content=True)\n                        _import["to_site"] += 1\n                        if ch.get("tmdb_id"):\n                            try: seen_mov_tmdb.add(int(ch["tmdb_id"]))', '                    elif options:\n                        ch = dict(options[0]); ch["year"] = ch.get("year") or ryear\n                        cat = _auto_category(ch)\n                        await add_movie_entry(ch, new_id, fuid, dest, category=cat, to_content=True)\n                        _import["to_site"] += 1\n                        if ch.get("tmdb_id"):\n                            try: seen_mov_tmdb.add(int(ch["tmdb_id"]))', 1),
    ('await add_movie_entry — bulk import (לא זוהה)', '                        # לא זוהה ב-TMDB — נכנס לאישור מסומן (tmdb_id=0) לטיפול נפרד\n                        _import["unmatched"] += 1; _import["to_pending"] += 1\n                        cap_title = (cap.splitlines()[0].strip() if cap.strip() else "") or clean_name(fname)\n                        add_movie_entry({"title": cap_title or f"קובץ {new_id}",\n                                         "year": ryear, "tmdb_id": 0, "type": "movie",\n                                         "poster": "", "overview": ""}, new_id, fuid, dest)\n                        seen_mov_title.add((_norm_title(cap_title), str(ryear or "")))', '                        # לא זוהה ב-TMDB — נכנס לאישור מסומן (tmdb_id=0) לטיפול נפרד\n                        _import["unmatched"] += 1; _import["to_pending"] += 1\n                        cap_title = (cap.splitlines()[0].strip() if cap.strip() else "") or clean_name(fname)\n                        await add_movie_entry({"title": cap_title or f"קובץ {new_id}",\n                                         "year": ryear, "tmdb_id": 0, "type": "movie",\n                                         "poster": "", "overview": ""}, new_id, fuid, dest)\n                        seen_mov_title.add((_norm_title(cap_title), str(ryear or "")))', 1),
    ('_LITE_DROP: הוספת cast', '# הפתרון: מסירים את description (32% מהמשקל, מוצג רק כשפותחים פריט) ואת\n# video_id הכפול (זהה ל-video_url ב-6709 פריטים; הפרונט ממילא נופל אחורה\n# ל-video_url). video_url נשאר — בלעדיו אי אפשר לנגן.\n_LITE_DROP = ("description",)\n# ה-limit-ים שנשמרים במטמון. כל ערך אחר מוגש מהרשימה בלי גוף שמור, כדי\n# ש-?limit=123 מכל מיני מקורות לא ימלא את הזיכרון בגרסאות של אותו קטלוג.\n_LITE_LIMITS = (0, 800)', '# הפתרון: מסירים את description (32% מהמשקל, מוצג רק כשפותחים פריט) ואת\n# video_id הכפול (זהה ל-video_url ב-6709 פריטים; הפרונט ממילא נופל אחורה\n# ל-video_url). video_url נשאר — בלעדיו אי אפשר לנגן.\n#\n# cast מצטרף לאותו חריג מאותה סיבה בדיוק: רשימת שחקנים+תמונות (עד 10 לכל\n# פריט) מוצגת רק כשפותחים פריט, ונמשכת לפי דרישה מ-/content/item/{id} —\n# בדיוק כמו description. backdrop_url *נשאר* בקטלוג המלא בכוונה: זו כתובת\n# בודדת (לא מערך), וה-HeroBanner קורא אותה ישירות מתוך movies שכבר בזיכרון\n# בלי בקשה נוספת — בניגוד ל-description/cast, אין לו רגע "פתיחת פריט".\n_LITE_DROP = ("description", "cast")\n# ה-limit-ים שנשמרים במטמון. כל ערך אחר מוגש מהרשימה בלי גוף שמור, כדי\n# ש-?limit=123 מכל מיני מקורות לא ימלא את הזיכרון בגרסאות של אותו קטלוג.\n_LITE_LIMITS = (0, 800)', 1),
]


def validate(out: str) -> None:
    """קומפילציה מלאה + בדיקה ממוקדת שאף קריאה ל-add_movie_entry לא
    נשארה בלי await, ועוד בדיקה התנהגותית אמיתית ל-tmdb_credits."""
    try:
        compile(out, PATH, "exec")
    except SyntaxError as e:
        sys.exit(f"✗ הקובץ המתוקן לא מתקמפל: {e}")

    # כל קריאה ל-add_movie_entry( בקובץ *כולו* (לא רק מה שנערך כאן)
    # חייבת לבוא אחרי "await " או להיות שורת ה-def עצמה ("async def ").
    # פונקציה שהפכה ל-async וקריאה בלעדיה מחזירה coroutine ולא dict —
    # תקלה שקטה, בלי Exception גלוי.
    bad = []
    for m in re.finditer(r"add_movie_entry\(", out):
        i = m.start()
        prefix = out[max(0, i - 20):i]
        if prefix.endswith("async def ") or prefix.endswith("await "):
            continue
        bad.append(out.count("\n", 0, i) + 1)
    if bad:
        sys.exit(f"✗ {len(bad)} קריאות ל-add_movie_entry( בלי await, "
                  f"בשורות {bad} — זה נשבר בשקט (מחזיר coroutine). עוצר.")

    assert MARK in out, "הקבוע TMDB_IMG_BACKDROP חסר"
    assert '"backdrop_url": chosen.get("backdrop", "")' in out, "backdrop_url חסר ב-add_movie_entry"
    assert '"cast": cast,' in out, "cast חסר ב-add_movie_entry"
    assert '"backdrop_url": meta.get("backdrop", "")' in out, "backdrop_url חסר ב-add_episode_entry"
    assert '"cast": meta.get("cast") or [],' in out, "cast חסר ב-add_episode_entry"
    assert '"year": meta.get("year", "")' in out, "year חסר ב-add_episode_entry"
    assert 'tv["cast"] = await tmdb_credits(tv["tmdb_id"], "tv")' in out, "משיכת cast לסדרה חסרה"
    assert '_LITE_DROP = ("description", "cast")' in out, "_LITE_DROP לא עודכן"

    _test_tmdb_credits(out)


def _test_tmdb_credits(out: str) -> None:
    """מחלץ את tmdb_credits כפונקציה עצמאית ומריץ אותה מול httpx מדומה —
    לא רק 'הטקסט נמצא', אלא שההתנהגות בפועל נכונה."""
    import asyncio
    import types
    import unittest.mock as mock

    start = out.index("async def tmdb_credits(")
    lines = out[start:].splitlines(keepends=True)
    body = [lines[0]]
    for ln in lines[1:]:
        if ln.strip() == "" or ln[:1] in (" ", "\t"):
            body.append(ln)
            continue
        break          # דה-דנט לעמודה 0 — כאן הפונקציה נגמרת (לא תוך
                        # כדי שורה ריקה *בתוך* ה-docstring עצמו)
    fn_src = "".join(body)

    class FakeResp:
        def __init__(self, status_code, data):
            self.status_code = status_code
            self._data = data
        def json(self):
            return self._data

    class FakeClient:
        def __init__(self, status=200, data=None, raise_exc=None):
            self._status, self._data, self._raise = status, data, raise_exc
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, url, params=None):
            if self._raise:
                raise self._raise
            return FakeResp(self._status, self._data)

    def make_client(status=200, data=None, raise_exc=None):
        return lambda timeout=None: FakeClient(status, data, raise_exc)

    ns = {
        "httpx": types.SimpleNamespace(AsyncClient=make_client()),
        "log": mock.MagicMock(),
        "TMDB_API_KEY": "fake-key",
        "TMDB_IMG_PROFILE": "https://image.tmdb.org/t/p/w185",
    }
    exec(compile(fn_src, "<tmdb_credits>", "exec"), ns)
    fn = ns["tmdb_credits"]

    # 1) בלי API key — ריק, בלי לגעת ברשת בכלל
    ns["TMDB_API_KEY"] = ""
    assert asyncio.run(fn(123, "movie")) == [], "אמור להיות ריק בלי API key"
    ns["TMDB_API_KEY"] = "fake-key"

    # 2) בלי tmdb_id — ריק
    assert asyncio.run(fn(0, "movie")) == [], "אמור להיות ריק עם tmdb_id=0"
    assert asyncio.run(fn(None, "movie")) == [], "אמור להיות ריק עם tmdb_id=None"

    # 3) media_type לא תקין — ריק
    assert asyncio.run(fn(123, "person")) == [], "אמור להיות ריק ל-media_type לא תקין"

    # 4) תשובה תקינה: מיון לפי order (עולה — billing הכי גבוה קודם),
    #    חיתוך ל-10, photo נבנה נכון מ-profile_path
    cast_in = [{"name": f"Actor{i}", "order": i, "profile_path": f"/p{i}.jpg"}
               for i in range(12)]
    ns["httpx"].AsyncClient = make_client(200, {"cast": cast_in})
    out_cast = asyncio.run(fn(123, "tv"))
    assert len(out_cast) == 10, f"ציפיתי ל-10 (חיתוך אחרי מיון), קיבלתי {len(out_cast)}"
    assert [c["name"] for c in out_cast] == [f"Actor{i}" for i in range(10)], \
        "המיון לפי order או החיתוך ל-10 שגויים"
    assert out_cast[0]["photo"] == "https://image.tmdb.org/t/p/w185/p0.jpg", "בניית photo שגויה"

    # 4ב) שם ריק *בתוך* ה-10 הראשונים לפי order נופל בלי תחליף (לא
    #     מוחלף במס' 11) — זו ההתנהגות בפועל של cast[:10] ואז סינון,
    #     לא "10 שחקנים עם שם" מובטח. גם profile_path=None → photo ריק.
    cast_gap = [{"name": "", "order": 0, "profile_path": ""}] + \
               [{"name": f"B{i}", "order": i + 1, "profile_path": None} for i in range(9)]
    ns["httpx"].AsyncClient = make_client(200, {"cast": cast_gap})
    out_gap = asyncio.run(fn(123, "tv"))
    assert len(out_gap) == 9, f"שם ריק בתוך ה-10 הראשונים אמור ליפול בלי תחליף, קיבלתי {len(out_gap)}"
    assert out_gap[0]["photo"] == "", "profile_path=None אמור לתת photo ריק"

    # 5) סטטוס לא 200 — ריק
    ns["httpx"].AsyncClient = make_client(404, {})
    assert asyncio.run(fn(123, "movie")) == [], "אמור להיות ריק על סטטוס לא 200"

    # 6) חריגת רשת — ריק, לא זורקת הלאה
    ns["httpx"].AsyncClient = make_client(raise_exc=ConnectionError("boom"))
    assert asyncio.run(fn(123, "movie")) == [], "חריגת רשת אמורה להיבלע לרשימה ריקה"


def main() -> None:
    if not os.path.exists(PATH):
        sys.exit(f"אין קובץ ב-{PATH} (אפשר MAIN_PY=...)")
    with open(PATH, encoding="utf-8") as fh:
        src = fh.read()

    if "--revert" in sys.argv:
        if not os.path.exists(BAK):
            sys.exit(f"אין גיבוי ב-{BAK}")
        shutil.copy2(BAK, PATH)
        print(f"✓ שוחזר מ-{BAK}")
        print("⚠ דורש restart כדי שהשחזור ייכנס לתוקף: systemctl restart zovex-bot")
        return

    if MARK in src:
        print("כבר מותקן.")
        return

    out = src
    for label, a, n, want in EDITS:
        got = out.count(a)
        if got != want:
            sys.exit(f"✗ העוגן '{label}' נמצא {got} פעמים (צפוי {want}) — לא נוגע בכלום.")
        out = out.replace(a, n)

    validate(out)
    print(f"✓ כל הבדיקות עברו ({len(EDITS)} עריכות)")
    if "--check" in sys.argv:
        print("--check: שום דבר לא נכתב.")
        return

    shutil.copy2(PATH, BAK)
    with open(PATH, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(f"✓ הוחל. גיבוי: {BAK}")
    print()
    print("⚠ דורש restart כדי שהשינוי ייכנס לתוקף (main.py נטען פעם אחת")
    print("  בעליית התהליך) — תבחר מתי, לא בהכרח עכשיו:")
    print("  systemctl restart zovex-bot")


if __name__ == "__main__":
    main()
