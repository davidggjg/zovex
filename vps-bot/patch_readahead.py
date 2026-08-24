#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""קריאה-מראש: מורידים את החלון הבא בזמן שמגישים את הנוכחי.

עד עכשיו הלולאה הייתה סדרתית — חלון יורד, מוגש, ורק כשהצופה סיים לצרוך אותו
מתחילה הורדת הבא. כל זמן הצפייה הרשת עמדה בטלה, וכשהבאפר נגמר הנגן חיכה
להורדה שלמה. זה ה"נתקע באמצע".

בטוח להרצה חוזרת. גיבוי + בדיקת קומפילציה + שחזור אוטומטי בכשל.
"""
import pathlib, py_compile, shutil, sys, time

P = pathlib.Path("/opt/zovex-bot/main.py")
s = P.read_text(encoding="utf-8")
done = []

OLD_FN = 'async def channel_stream_range_parallel(chat_id, message_id, start, end):\n    """גרסה מקבילה עם *התחלה מהירה*: מעבדת חלון-אחר-חלון, וכל חלון נמשך בכמה\n    תת-טווחים במקביל. קריטי לזמן-התחלה: הגשה מתבצעת רק אחרי שכל תת-הטווחים של\n    החלון הושלמו — לכן חלון ראשון גדול (16MB) גרם ל-TTFB של כמה שניות ("לוקח\n    מלא זמן להיפעל"). הפתרון: רמפת-האצה — החלונות הראשונים קטנים (הבייט הראשון\n    מגיע כמעט מיד והנגינה מתחילה), ואז גדלים לחלון המלא למהירות שיא."""\n    parts = max(2, STREAM_PARALLEL_PARTS)\n    full_window = max(STREAM_PARALLEL_WINDOW, parts * 512 * 1024)\n    MIN_PART = 512 * 1024   # לא לפצל לחתיכות קטנות מדי\n    # רמפה: 1MB → 4MB → מלא. חלון ראשון קטן = TTFB נמוך; אחר כך מהירות מלאה.\n    ramp = [1 * 1024 * 1024, 4 * 1024 * 1024]\n    pos = start\n    idx = 0\n    while pos <= end:\n        window = min(ramp[idx] if idx < len(ramp) else full_window, full_window)\n        idx += 1\n        wend = min(pos + window - 1, end)\n        total = wend - pos + 1\n        n = max(1, min(parts, total // MIN_PART))\n        step = -(-total // n)   # ceil\n        ranges = []\n        s = pos\n        while s <= wend:\n            e2 = min(s + step - 1, wend)\n            ranges.append((s, e2))\n            s = e2 + 1\n        # קודם מנסים את מסלול ה-media bands (חיבורים מקבילים לאותו DC) —\n        # נמדד פי ~70 מהר יותר ממשיכה דרך בוט בחיבור יחיד. אם הוא לא זמין\n        # או נכשל, נופלים בשקט למסלול הבוטים הוותיק.\n        fast = await _media_bands_fetch(chat_id, message_id, pos, wend)\n        if fast is not None:\n            yield fast\n        else:\n            # מושכים את כל תת-הטווחים של החלון במקביל, ומגישים לפי הסדר\n            results = await asyncio.gather(\n                *[_fetch_subrange(chat_id, message_id, a, b) for a, b in ranges])\n            for r in results:\n                yield r\n        pos = wend + 1\n\n'
NEW_FN = 'async def channel_stream_range_parallel(chat_id, message_id, start, end):\n    """גרסה מקבילה עם *התחלה מהירה*: מעבדת חלון-אחר-חלון, וכל חלון נמשך בכמה\n    תת-טווחים במקביל. קריטי לזמן-התחלה: הגשה מתבצעת רק אחרי שכל תת-הטווחים של\n    החלון הושלמו — לכן חלון ראשון גדול (16MB) גרם ל-TTFB של כמה שניות ("לוקח\n    מלא זמן להיפעל"). הפתרון: רמפת-האצה — החלונות הראשונים קטנים (הבייט הראשון\n    מגיע כמעט מיד והנגינה מתחילה), ואז גדלים לחלון המלא למהירות שיא."""\n    parts = max(2, STREAM_PARALLEL_PARTS)\n    full_window = max(STREAM_PARALLEL_WINDOW, parts * 512 * 1024)\n    MIN_PART = 512 * 1024   # לא לפצל לחתיכות קטנות מדי\n    # רמפה: 1MB → 4MB → מלא. חלון ראשון קטן = TTFB נמוך; אחר כך מהירות מלאה.\n    ramp = [1 * 1024 * 1024, 4 * 1024 * 1024]\n    async def _fetch_window(wstart, wend):\n        """מחזיר את כל בייטי החלון. קודם מסלול ה-media bands (חיבורים מקבילים\n        לאותו DC — נמדד פי ~70 ממשיכה בחיבור יחיד), ואם הוא נכשל נופלים בשקט\n        למסלול הבוטים הוותיק."""\n        fast = await _media_bands_fetch(chat_id, message_id, wstart, wend)\n        if fast is not None:\n            return fast\n        total_w = wend - wstart + 1\n        n = max(1, min(parts, total_w // MIN_PART))\n        step = -(-total_w // n)\n        rngs, s = [], wstart\n        while s <= wend:\n            e2 = min(s + step - 1, wend)\n            rngs.append((s, e2))\n            s = e2 + 1\n        results = await asyncio.gather(\n            *[_fetch_subrange(chat_id, message_id, a, b) for a, b in rngs])\n        return b"".join(results)\n\n    def _window_end(p, i):\n        w = min(ramp[i] if i < len(ramp) else full_window, full_window)\n        return min(p + w - 1, end)\n\n    # קריאה-מראש: עד עכשיו הלולאה הייתה סדרתית לחלוטין — מורידה חלון, מגישה\n    # אותו, ורק *אחרי* שהצופה סיים לצרוך אותו מתחילה להוריד את הבא. כלומר כל\n    # זמן הצפייה הרשת עמדה בטלה, וכשהבאפר של הנגן נגמר הוא נאלץ להמתין להורדה\n    # שלמה — זה בדיוק ה"נתקע באמצע". כאן מתחילים להוריד את החלון הבא *לפני*\n    # שמגישים את הנוכחי, כך שברוב המקרים הוא כבר מוכן כשהנגן מגיע אליו.\n    pos, idx = start, 0\n    ahead = None            # (task, next_pos, next_end)\n    try:\n        while pos <= end:\n            wend = _window_end(pos, idx)\n            idx += 1\n            if ahead is not None and ahead[1] == pos:\n                data = await ahead[0]\n                ahead = None\n            else:\n                data = await _fetch_window(pos, wend)\n\n            # מדליקים את החלון הבא לפני ההגשה — ההורדה רצה בזמן הצפייה.\n            npos = wend + 1\n            if npos <= end and STREAM_READAHEAD:\n                nend = _window_end(npos, idx)\n                ahead = (asyncio.create_task(_fetch_window(npos, nend)), npos, nend)\n\n            yield data\n            pos = npos\n    finally:\n        # הצופה עזב באמצע — לא משאירים הורדה מיותרת רצה ברקע.\n        if ahead is not None:\n            ahead[0].cancel()\n            # אם המשימה כבר הספיקה להיכשל, cancel() לא עושה כלום והחריגה נשארת\n            # "לא נאספה" — asyncio מדפיס אז אזהרה מלאה עם traceback, לכל צופה\n            # שעוזב באמצע. הקולבק אוסף אותה ומשתיק את הרעש.\n            ahead[0].add_done_callback(\n                lambda t: t.cancelled() or t.exception())\n\n'
CONST  = '# קריאה-מראש של חלון אחד קדימה. עלות: עוד חלון אחד בזיכרון לכל צופה פעיל\n# (ברירת מחדל 16MB). אפשר לכבות ב-STREAM_READAHEAD=0 אם הזיכרון נהיה צר.\nSTREAM_READAHEAD = os.environ.get("STREAM_READAHEAD", "1") not in ("0", "false", "no")\n'

if "STREAM_READAHEAD" in s and "ahead = (asyncio.create_task" in s:
    print("כבר מוחל — אין מה לעשות.")
    sys.exit(0)

if "STREAM_READAHEAD" not in s:
    anchor = "STREAM_PARALLEL_WINDOW = int("
    if anchor not in s:
        print("### לא נמצאה נקודת העיגון לקבוע — עוצר בלי לשנות כלום ###")
        sys.exit(1)
    e = s.index("\n", s.index(anchor)) + 1
    s = s[:e] + CONST + s[e:]
    done.append("הקבוע STREAM_READAHEAD (ניתן לכיבוי ב-STREAM_READAHEAD=0)")

if OLD_FN not in s:
    print("### הפונקציה channel_stream_range_parallel בשרת אינה תואמת למצופה ###")
    print("### לא שונה כלום. שלח לי את הפלט של:")
    print("###   grep -n 'async def channel_stream_range_parallel' /opt/zovex-bot/main.py")
    sys.exit(1)
s = s.replace(OLD_FN, NEW_FN, 1)
done.append("לולאת ההזרמה -> קריאה-מראש של חלון אחד")

bak = P.with_name("main_before_readahead_%d.py" % time.time())
shutil.copy2(P, bak)
P.write_text(s, encoding="utf-8")
try:
    py_compile.compile(str(P), doraise=True)
except Exception as e:
    shutil.copy2(bak, P)
    print("### הקומפילציה נכשלה — שוחזר הגיבוי ###")
    print(e)
    sys.exit(1)
print("הוחל:")
for d in done:
    print("   + " + d)
print("\n   גיבוי: " + bak.name)
print("\n   עכשיו:  sudo systemctl restart zovex-bot")
