import json, pathlib, shutil
from datetime import datetime

# ── ביטול שדרוג הערוצים ─────────────────────────────────────────────────
# מחזיר את 22 הערוצים ששודרגו ל-siauliairsavlt חזרה לספק המקורי
# (embyil/mcquack), שאליו לשרת יש נתיב רשת מהיר יותר ולכן הם רצים חלק.
# הערוצים ה-6 שנוספו (ניק ג'וניור, E!, yes דוקו, טורקיות+) *נשארים*.
# הרצה:  python3 revert_iptv_upgrade.py   ואז restart. Idempotent.

DATA = pathlib.Path('/opt/zovex-bot/data')
CONTENT = DATA / 'content.json'
B = 'https://zovex.duckdns.org/hls-relay/'

# שם-הערוץ → הקישור המקורי (כפי שהיה לפני השדרוג)
ORIG = {
    'HOT cinema 4':      B + '_fix/tv.embyil.tv/live/240/chunks.m3u8',
    'HOT cinema1':       B + '_fix/tv.embyil.tv/live/210/chunks.m3u8',
    'HOT cinema 3':      B + '_fix/tv.embyil.tv/live/230/chunks.m3u8',
    'Hotcinema2':        B + '_fix/tv.embyil.tv/live/220/chunks.m3u8',
    'HOT 3':             B + 'tv.embyil.tv/live/270/chunks.m3u8',
    'HOT בידור':         B + 'tv.embyil.tv/live/340/chunks.m3u8',
    'ויוה פרימיום':      B + 'tv.embyil.tv/live/680/chunks.m3u8',
    'ערוץ 24':           B + 'stream.mcquack.net/42/index.m3u8',
    'ערוץ ההיסטוריה':    B + 'tv.embyil.tv/live/691/chunks.m3u8',
    'נשיונל גאוגרפיק':   B + 'tv.embyil.tv/live/693/chunks.m3u8',
    'נשיונל ווילד':      B + 'tv.embyil.tv/live/694/chunks.m3u8',
    'ספורט 5':           B + 'stream.mcquack.net/41/index.m3u8',
    'ספורט 5 גולד':      B + 'tv.embyil.tv/live/150/chunks.m3u8',
    'ספורט 5 סטארס':     B + '_fix/tv.embyil.tv/live/140/chunks.m3u8',
    'one 1':             B + 'tv.embyil.tv/live/160/chunks.m3u8',
    'one 2':             B + 'tv.embyil.tv/live/170/chunks.m3u8',
    'הוט זון':           B + 'stream.mcquack.net/379/index.m3u8',
    'ים תיכוני':         B + 'stream.mcquack.net/46/index.m3u8',
    'ערוץ 9':            B + 'tv.embyil.tv/live/60/chunks.m3u8',
    'Yes Movies Action': B + 'stream.mcquack.net/380/index.m3u8',
    'הופ!':              B + 'stream.mcquack.net/44/index.m3u8',
    'ערוץ גוניור':       B + 'tv.embyil.tv/live/760/chunks.m3u8',
}

stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
shutil.copy2(CONTENT, CONTENT.with_suffix(f'.json.bak-{stamp}'))
print('גיבוי:', CONTENT.with_suffix(f'.json.bak-{stamp}').name)

d = json.loads(CONTENT.read_text(encoding='utf-8'))
reverted = skip = miss = 0
seen = set()
for e in d:
    if e.get('is_live') and e.get('title') in ORIG:
        seen.add(e['title'])
        want = ORIG[e['title']]
        if e.get('video_url') == want:
            skip += 1
        else:
            e['video_url'] = want; reverted += 1
            print(f'  ↩ הוחזר: {e["title"]}')
miss = [t for t in ORIG if t not in seen]
CONTENT.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
print(f'\nהוחזרו {reverted}, כבר-מקורי {skip}' + (f', לא נמצאו: {miss}' if miss else ''))
print('הפעל מחדש:  systemctl restart zovex-bot')
