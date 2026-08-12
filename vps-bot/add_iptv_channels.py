import json, pathlib, uuid, re
from datetime import datetime

# הוספת ערוצי IPTV מהספק החדש לקטלוג, יחד עם רישום המארח ברשימה הלבנה
# של ה-relay. הרצה: python3 add_iptv_channels.py   (ואז restart לשירות)

DATA = pathlib.Path('/opt/zovex-bot/data')
CONTENT = DATA / 'content.json'
RELAY_HOSTS = DATA / 'relay_hosts.json'

PROVIDER = 'sewv654wfcsdwfi87fwvgbngh.siauliairsavlt.pw'
TOKEN = 'F5GDYXTUM2QBV3'
BASE = 'https://zovex.duckdns.org/hls-relay/'

# (מזהה ערוץ אצל הספק, שם, slug, לוגו)
NEW = [
    ('2329', 'קשת 12 — HD', 'keshet-12', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/keshet12-il.png'),
    ('2369', 'ערוץ 98', 'channel-98', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/channel-98-il.png'),
    ('2339', 'הום פלוס', 'home-plus', 'https://base44.app/api/apps/6a79ff23eb41e28b9a83736b/files/mp/public/6a79ff23eb41e28b9a83736b/90fc4a788_591580.png'),
    ('2342', 'yes ישראלי', 'yes-israeli', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/yes-israel-il.png'),
    ('2343', 'yes Drama — HD', 'yes-drama', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/yes-tv-drama-il.png'),
    ('2345', 'yes Comedy — HD', 'yes-comedy', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/yes-tv-comedy-il.png'),
    ('2346', 'yes Action — HD', 'yes-action', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/yes-tv-action-il.png'),
    ('2348', 'yes Movies Comedy', 'yes-movies-comedy', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/yes-tv-comedy-il.png'),
    ('2349', 'קשת 12 — FHD', 'keshet-12-fhd', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/keshet12-il.png'),
    ('2351', 'yes Movies Drama', 'yes-movies-drama', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/yes-movies-drama-il.png'),
    ('2354', 'HOT HBO — HD', 'hot-hbo', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/hot-hbo-il.png'),
    ('2358', 'דיסקברי — FHD', 'discovery', 'https://raw.githubusercontent.com/skydrome/tvg-logos/master/NatGeo.us.png'),
    ('2365', 'yes Movies Kids', 'yes-movies-kids', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/yes-movies-kids-il.png'),
    ('2377', 'Food Network', 'food-network', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/food-channel-il.png'),
    ('2378', 'Health', 'health', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/health-channel-il.png'),
    ('2381', 'מכאן 33', 'makan-33', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/makan-33-il.png'),
    ('2389', 'ספורט 4 — HD', 'sport-4', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/sport4-il.png'),
    ('7203', 'יורוספורט 2', 'eurosport-2', '/zovex/live-logos/sport5.png?v=2'),
    ('12209', 'Food Network — HD', 'food-network-hd', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/food-channel-il.png'),
    ('12217', 'HOT Comedy — HD', 'hot-comedy', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/hot-comedy-il.png'),
    ('12241', 'דיסקברי — HD', 'discovery-hd', 'https://raw.githubusercontent.com/skydrome/tvg-logos/master/NatGeo.us.png'),
    ('12249', 'ספורט 1 — HD', 'sport-1', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/sport1-il.png'),
    ('12250', 'ספורט 2 — HD', 'sport-2', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/sport2-il.png'),
    ('12251', 'ספורט 3 — HD', 'sport-3', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/sport3-il.png'),
    ('12267', 'סרטים הודיים — Bollywood', 'bollywood', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/hot-bollywood-il.png'),
    ('12271', 'yes Movies Comedy — FHD', 'yes-movies-comedy-fhd', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/yes-tv-comedy-il.png'),
    ('12272', 'yes Movies Drama — FHD', 'yes-movies-drama-fhd', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/yes-movies-drama-il.png'),
    ('12273', 'yes Movies Kids — FHD', 'yes-movies-kids-fhd', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/yes-movies-kids-il.png'),
    ('12274', 'HOT Real — HD', 'hot-real', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/hot-real-il.png'),
    ('12281', 'yes Movies Comedy — HD', 'yes-movies-comedy-hd', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/yes-tv-comedy-il.png'),
    ('12283', 'WIZ — HD', 'wiz', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/wiz-il.png'),
    ('12282', 'yes Movies Drama — HD', 'yes-movies-drama-hd', 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/israel/yes-movies-drama-il.png'),
]

# ── 1. רישום המארח ברשימה הלבנה ──────────────────────────────────────────
# הספק עובד ב-HTTP בלבד (HTTPS מסרב לחיבור), ולכן scheme=http ו-port=80.
# המקטעים יושבים על עשרות IP-ים מתחלפים — אותם ה-relay לומד לבד מהמניפסט,
# ואין צורך לרשום אותם כאן.
hosts = {}
if RELAY_HOSTS.exists():
    raw = json.loads(RELAY_HOSTS.read_text(encoding='utf-8'))
    hosts = raw if isinstance(raw, dict) else {h: {'scheme': 'http', 'port': 80} for h in raw}
if PROVIDER not in hosts:
    hosts[PROVIDER] = {'scheme': 'http', 'port': 80}
    RELAY_HOSTS.write_text(json.dumps(hosts, ensure_ascii=False, indent=1), encoding='utf-8')
    print('נוסף לרשימה הלבנה:', PROVIDER)
else:
    print('כבר ברשימה הלבנה:', PROVIDER)

# ── 2. הוספת הערוצים ─────────────────────────────────────────────────────
d = json.loads(CONTENT.read_text(encoding='utf-8'))
have_titles = {e.get('title') for e in d}
have_slugs = {e.get('custom_slug') for e in d if e.get('custom_slug')}
added = skipped = 0

for cid, title, slug, logo in NEW:
    if title in have_titles:
        print('  כבר קיים, מדלג:', title); skipped += 1; continue
    s = slug
    n = 2
    while s in have_slugs:
        s = f'{slug}-{n}'; n += 1
    d.append({
        'title': title,
        'video_url': f'{BASE}{PROVIDER}/iptv/{TOKEN}/{cid}/index.m3u8',
        'video_id': None,
        'thumbnail_url': logo,
        'custom_slug': s,
        'category': 'שידורים חיים',
        'is_live': True,
        'type': None, 'series_name': None, 'season_number': None,
        'episode_number': None, 'episode_title': None, 'year': None,
        'description': '',
        'id': str(uuid.uuid4()),
        'created_date': datetime.utcnow().isoformat() + 'Z',
    })
    have_titles.add(title); have_slugs.add(s); added += 1

CONTENT.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
print(f'\nנוספו {added} ערוצים, דולגו {skipped}. סה"כ בקטלוג: {len(d)}')
print('כעת הפעל מחדש:  sudo systemctl restart zovex-bot')
