import json, pathlib, shutil, re
from datetime import datetime

# ── שדרוג ערוצים דרך נתיב _fix (תואם אפליקציה) ──────────────────────────
# הבעיה: siauliairsavlt מגיש HLS ב-MPEG-TS. נגן ה-Shaka בדפדפן שולחני מפענח
# TS, אבל ב-WebView של האפליקציה (אנדרואיד) הוא לא — ולכן הערוצים "עובדים
# באתר, לא באפליקציה". הפתרון: להזרים אותם דרך /hls-relay/_fix/ שבו ffmpeg
# ממיר ל-fMP4 (בדיוק כמו embyil שכן עובד באפליקציה). אותו נגן, פורמט תואם.
#
# הסקריפט: (1) משדרג את 22 הערוצים ל-HD של siauliairsavlt דרך _fix,
#          (2) מפנה גם את 6 הנוספים ל-_fix,
#          (3) ממיר כל ערוץ siauliairsavlt "גולמי" שנותר ל-_fix (הוותיקים).
# מגבה, idempotent. הרצה:  python3 upgrade_iptv_fix.py  ואז restart.
#
# הערה: _fix מפעיל ffmpeg per-ערוץ-נצפה (copy, עומס CPU נמוך), עם ~5-10ש
# המתנה בהדלקה הראשונה. הריפר סוגר ערוצים לא-נצפים. העומס מתון.

DATA = pathlib.Path('/opt/zovex-bot/data')
CONTENT = DATA / 'content.json'
PROVIDER = 'sewv654wfcsdwfi87fwvgbngh.siauliairsavlt.pw'
TOKEN = 'F5GDYXTUM2QBV3'
B = 'https://zovex.duckdns.org/hls-relay/'
def fixurl(cid): return f'{B}_fix/{PROVIDER}/iptv/{TOKEN}/{cid}/index.m3u8'

# 22 שדרוגי HD (שם → מזהה)
UPGRADES = {
    'HOT cinema 4': '2356', 'HOT cinema1': '2357', 'HOT cinema 3': '2372',
    'Hotcinema2': '12215', 'HOT 3': '2367', 'HOT בידור': '12219',
    'ויוה פרימיום': '12226', 'ערוץ 24': '12237', 'ערוץ ההיסטוריה': '12265',
    'נשיונל גאוגרפיק': '12247', 'נשיונל ווילד': '12248', 'ספורט 5': '2341',
    'ספורט 5 גולד': '12254', 'ספורט 5 סטארס': '12278', 'one 1': '2340',
    'one 2': '12231', 'הוט זון': '2360', 'ים תיכוני': '12211', 'ערוץ 9': '2331',
    'Yes Movies Action': '12280', 'הופ!': '12244', 'ערוץ גוניור': '2366',
}
# 6 הנוספים (שם → מזהה)
ADDS = {
    "ניק ג'וניור": '2337', 'E!': '12243', 'yes דוקו': '12258',
    'הדרמות הטורקיות+': '12257', 'הדרמות הטורקיות 2': '12262', 'הדרמות הטורקיות 3': '12264',
}

stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
shutil.copy2(CONTENT, CONTENT.with_suffix(f'.json.bak-{stamp}'))
print('גיבוי:', CONTENT.with_suffix(f'.json.bak-{stamp}').name)

d = json.loads(CONTENT.read_text(encoding='utf-8'))
by_title = {}
for e in d:
    if e.get('is_live'):
        by_title.setdefault(e.get('title'), []).append(e)

up = add = swept = 0
for title, cid in {**UPGRADES, **ADDS}.items():
    want = fixurl(cid)
    for e in by_title.get(title, []):
        if e.get('video_url') != want:
            e['video_url'] = want
            if title in UPGRADES: up += 1
            else: add += 1
            print(f'  ✓ {title} → _fix/{cid}')

# המרת כל שאר ערוצי siauliairsavlt הגולמיים ל-_fix (הוותיקים: yes, ספורט 1-3...)
raw_re = re.compile(r'/hls-relay/(' + re.escape(PROVIDER) + r'/)')
for e in d:
    if not e.get('is_live'):
        continue
    u = e.get('video_url', '')
    if PROVIDER in u and '_fix' not in u:
        e['video_url'] = raw_re.sub(r'/hls-relay/_fix/\1', u)
        swept += 1
        print(f'  ↻ (ותיק) {e.get("title")} → _fix')

CONTENT.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
print(f'\nשודרגו {up}, נוספים→_fix {add}, ותיקים→_fix {swept}')
print('הפעל מחדש:  systemctl restart zovex-bot')
