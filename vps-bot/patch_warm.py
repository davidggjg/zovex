#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""העדפת בוט שכבר מחזיק את ההודעה — מקצר את זמן ההתחלה של סרט.

נמדד בשרת: אותה בקשה חזרה פעם ב-0.56 שניות ופעם ב-8.72. ההפרש הוא בדיוק
תקציב שליפת ההודעה שנשרף על בוט תקוע. בוט שכבר מחזיק את ההודעה במטמון עונה
בלי קריאת רשת, ולכן לא יכול להיתקע שם.

בטוח להרצה חוזרת. גיבוי + בדיקת קומפילציה + שחזור אוטומטי בכשל.
"""
import pathlib, py_compile, shutil, sys, time

P = pathlib.Path("/opt/zovex-bot/main.py")
s = P.read_text(encoding="utf-8")
orig = s
done = []

WARM = '\n# באיזו הסתברות להעדיף בוט שההודעה כבר במטמון שלו. לא 100%: בהעדפה מוחלטת\n# הצופה הראשון היה "נועל" את הסרט על בוט אחד למשך 15 דקות, וכל שאר הצופים\n# באותו סרט היו נדחסים לאותו חשבון. הדליפה של ~15% מחממת בוטים נוספים ברקע,\n# כך שקבוצת החמים גדלה מעצמה ככל שהסרט נצפה יותר.\nWARM_BIAS = float(os.environ.get("STREAM_WARM_BIAS", "0.85"))\n\n\nasync def pick_stream_bot_for(chat_id, message_id):\n    """כמו pick_stream_bot, אבל מעדיף בוט שכבר משך את ההודעה הזו.\n\n    נמדד על השרת אחרי הדחת הבוטים התקועים: חלק מהבקשות חזרו ב-0.56 שניות\n    (5.4 MB/s) ואחרות ב-8.7 — וההפרש היה בדיוק 8 שניות, כלומר מלוא תקציב\n    שליפת ההודעה שנשרף על בוט תקוע לפני המעבר לבא. בוט "חם" מחזיר את ההודעה\n    מהמטמון בלי קריאת רשת כלל, ולכן הוא לא יכול להיתקע שם — מה שמסלק את\n    מקור השונות האחרון במקום לקצר את העונש עליו.\n    """\n    now = time.time()\n    if random.random() < WARM_BIAS:\n        warm = [b for b in _stream_bots\n                if b["cooldown_until"] < now\n                and (_bot_msg_cache.get((b["name"], chat_id, message_id))\n                     or (None, 0.0))[1] > now]\n        if warm:\n            if len(warm) == 1:\n                return warm[0]\n            a = warm[random.randrange(len(warm))]\n            b = warm[random.randrange(len(warm))]\n            return a if _bot_score(a) >= _bot_score(b) else b\n    return await pick_stream_bot()\n\n'

if "pick_stream_bot_for" in s:
    print("כבר מוחל — אין מה לעשות.")
    sys.exit(0)

anchor = "# כמה כשלים *רצופים* לפני שמדיחים בוט."
if anchor not in s:
    print("### לא נמצאה נקודת העיגון — עוצר בלי לשנות כלום ###")
    sys.exit(1)
s = s.replace(anchor, WARM + anchor, 1)
done.append("בורר שמעדיף בוט חם (85%)")

subs = [
 ("    if STREAM_MEDIA_CONNS <= 0:\n        return None\n    bot = await pick_stream_bot()\n",
  "    if STREAM_MEDIA_CONNS <= 0:\n        return None\n    bot = await pick_stream_bot_for(chat_id, message_id)\n",
  "_media_bands_fetch", 1),
 ("    for _ in range(min(max(1, len(_stream_bots)), 5)):\n        bot = await pick_stream_bot()\n",
  "    for _ in range(min(max(1, len(_stream_bots)), 5)):\n        bot = await pick_stream_bot_for(chat_id, message_id)\n",
  "channel_get_media", 1),
 ("    for _ in range(min(max(1, len(_stream_bots)), 4)):\n        bot = await pick_stream_bot()\n",
  "    for _ in range(min(max(1, len(_stream_bots)), 4)):\n        bot = await pick_stream_bot_for(chat_id, message_id)\n",
  "channel_stream_range + _fetch_subrange", 2),
]
for old, new, label, want in subs:
    n = s.count(old)
    if n != want:
        print("### %s: נמצאו %d מופעים במקום %d — עוצר בלי לשנות כלום ###" % (label, n, want))
        sys.exit(1)
    s = s.replace(old, new)
    done.append("%s -> בורר חם" % label)

bak = P.with_name("main_before_warm_%d.py" % time.time())
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
