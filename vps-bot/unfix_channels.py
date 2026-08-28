import json, pathlib, shutil
from datetime import datetime

# ── ביטול _fix לערוצים בעייתיים ─────────────────────────────────────────
# חלק מזרמי siauliairsavlt פגומים במקור (מקטעים זעירים, ffmpeg לא מצליח
# להעתיק את הווידאו) — דרך _fix הם יוצאים אודיו-בלבד / מסך שחור. הדפדפן
# "סבל" את הזרם הגולמי, אז מחזירים אותם ל-passthrough גולמי (בלי _fix):
# עובד באתר כמו קודם. (באפליקציה זרם פגום כזה ממילא לא ינוגן — מקור אחר.)
# הרצה:  python3 unfix_channels.py   ואז restart. Idempotent.

SLUGS = ['sport-2']            # להוסיף כאן slug של כל ערוץ שיוצא שחור אחרי _fix

DATA = pathlib.Path('/opt/zovex-bot/data')
CONTENT = DATA / 'content.json'

stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
shutil.copy2(CONTENT, CONTENT.with_suffix(f'.json.bak-{stamp}'))
print('גיבוי:', CONTENT.with_suffix(f'.json.bak-{stamp}').name)

d = json.loads(CONTENT.read_text(encoding='utf-8'))
fixed = 0
for e in d:
    if e.get('is_live') and e.get('custom_slug') in SLUGS:
        u = e.get('video_url', '')
        if '/hls-relay/_fix/' in u:
            e['video_url'] = u.replace('/hls-relay/_fix/', '/hls-relay/')
            fixed += 1
            print(f'  ↩ {e.get("title")} ({e.get("custom_slug")}) → גולמי (בלי _fix)')

CONTENT.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
print(f'\nהוחזרו {fixed}. הפעל מחדש:  systemctl restart zovex-bot')
