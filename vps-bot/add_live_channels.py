import json, pathlib, uuid, re
from datetime import datetime

P = pathlib.Path('/opt/zovex-bot/data/content.json')
BASE = 'https://zovex.duckdns.org/hls-relay/'
LOGO = 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/'
SKY = 'https://raw.githubusercontent.com/skydrome/tvg-logos/master/'

# (מספר ערוץ, שם, slug, לוגו, צריך_fix)
NEW = [
    # ── דרמות בינלאומיות ──
    ('600', 'דרמות טורקיות 3', 'turkish-drama-3', LOGO + 'turkish-dramas-channel-3-il.png', 0),
    ('610', 'דרמות ספרדיות 1', 'spanish-drama-1', LOGO + 'vamos-channel-il.png', 0),
    ('620', 'דרמות ספרדיות 2', 'spanish-drama-2', LOGO + 'vamos-channel-il.png', 0),
    ('630', 'דרמות הודיות 1', 'indian-drama-1', LOGO + 'hot-bollywood-il.png', 0),
    ('640', 'דרמות הודיות 2', 'indian-drama-2', LOGO + 'hot-bombay-il.png', 0),
    ('660', 'ויוה איסטנבול', 'viva-istanbul', LOGO + 'viva-il.png', 0),
    ('670', "ויוה וינטג'", 'viva-vintage', LOGO + 'viva-vintage-il.png', 0),
    ('680', 'ויוה פרימיום', 'viva-premium', LOGO + 'viva-premium-il.png', 0),
    ('690', 'ויוה טלנובלות', 'viva-telenovelas', LOGO + 'viva-plus-il.png', 0),
    # ── ילדים ונוער ──
    ('570', 'סלקום קידס', 'cellcom-kids', LOGO + 'hop-il.png', 0),
    ('700', "דיסני ג'וניור", 'disney-junior', SKY + 'disney.il.png', 0),
    ('719', 'ערוץ הכוכבים', 'star-channel', LOGO + 'star-channel-il.png', 0),
    ('720', 'ניקולודיון', 'nickelodeon', SKY + 'Nickelodeon.us.png', 0),
    ('740', 'טין ניק', 'teen-nick', 'https://raw.githubusercontent.com/taksssss/tv/main/icon/TEENNICK.png', 0),
    ('750', 'ערוץ לולי', 'lolly', LOGO + 'hot-lolly-il.png', 0),
    ('760', 'ערוץ גוניור', 'junior', LOGO + 'junior-channel-il.png', 0),
    ('780', 'בייבי', 'baby', LOGO + 'baby-channel-il.png', 0),
    # ── דוקו וטבע ──
    ('490', 'פרי דוקו', 'free-doco', LOGO + 'yes-doco-il.png', 0),
    ('691', 'ערוץ ההיסטוריה', 'history', LOGO + 'history-channel-il.png', 0),
    ('693', 'נשיונל גאוגרפיק', 'natgeo', SKY + 'NatGeo.us.png', 0),
    ('694', 'נשיונל ווילד', 'natgeo-wild', SKY + 'NatGeo.us.png', 0),
    # ── מוזיקה ──
    ('520', 'קריוקי', 'karaoke', LOGO + 'hot-music-il.png', 0),
    # ── אחר ──
    ('60', 'ערוץ 9', 'channel9', LOGO + 'channel9-il.png', 0),
    ('320', 'הוט משפחה גיבוי', 'hot-family-backup', LOGO + 'hot-cinema-family-il.png', 1),
]

# ערוצים שכבר באתר וזקוקים ל-_fix (open-GOP — Shaka נתקע עליהם)
FIX_EXISTING = ['230', '240', '250', '280', '330']

d = json.loads(P.read_text(encoding='utf-8'))

# אילו מספרי ערוץ כבר קיימים
have = set()
for e in d:
    m = re.search(r'tv\.embyil\.tv/live/(\d+)/', e.get('video_url') or '')
    if m:
        have.add(m.group(1))

# ── 1. תיקון קיימים ──
fixed = 0
for e in d:
    u = e.get('video_url') or ''
    m = re.search(r'tv\.embyil\.tv/live/(\d+)/', u)
    if m and m.group(1) in FIX_EXISTING and '_fix' not in u:
        e['video_url'] = BASE + '_fix/tv.embyil.tv/live/%s/chunks.m3u8' % m.group(1)
        if e.get('video_id'):
            e['video_id'] = e['video_url']
        fixed += 1
        print('תוקן:  %-22s → _fix' % e.get('title'))

# ── 2. הוספת חדשים ──
added = skipped = 0
for cid, name, slug, logo, needfix in NEW:
    if cid in have:
        print('דילוג: %-22s (כבר קיים)' % name)
        skipped += 1
        continue
    url = BASE + ('_fix/' if needfix else '') + 'tv.embyil.tv/live/%s/chunks.m3u8' % cid
    d.insert(0, {
        'id': str(uuid.uuid4()),
        'created_date': datetime.utcnow().isoformat() + 'Z',
        'title': name,
        'video_url': url,
        'video_id': None,
        'thumbnail_url': logo,
        'custom_slug': slug,
        'category': 'שידורים חיים',
        'is_live': True,
        'type': None,
        'series_name': None,
        'season_number': None,
        'episode_number': None,
        'episode_title': None,
        'year': None,
        'description': '',
    })
    added += 1
    print('נוסף:  %-22s %s%s' % (name, cid, '  [_fix]' if needfix else ''))

P.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')
print('\n─────────────────────')
print('נוספו: %d | תוקנו: %d | דילוגים: %d' % (added, fixed, skipped))
