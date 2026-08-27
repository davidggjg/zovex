import json, pathlib, uuid, shutil
from datetime import datetime, timezone

# ── שדרוג + הוספת ערוצי IPTV ─────────────────────────────────────────────
# מקור: אתר israelstreamhub (אותו ספק siauliairsavlt שכבר משרת 23 ערוצים אצלנו).
#   1. משדרג ~22 ערוצים שיושבים אצלנו על ספקים חלשים (embyil/mcquack) ל-HD/FHD
#      של הספק הזה — *מחליף קישור*, לא מכפיל.
#   2. מוסיף ערוצים שאין לנו (ניק ג'וניור, E!, yes דוקו, 3× דרמות טורקיות+).
# הרצה על השרת:  python3 upgrade_iptv_channels.py   ואז restart לשירות.
# הסקריפט idempotent — הרצה חוזרת לא תשנה כלום.

DATA = pathlib.Path('/opt/zovex-bot/data')
CONTENT = DATA / 'content.json'
RELAY_HOSTS = DATA / 'relay_hosts.json'

PROVIDER = 'sewv654wfcsdwfi87fwvgbngh.siauliairsavlt.pw'
TOKEN = 'F5GDYXTUM2QBV3'
def url(cid): return f'https://zovex.duckdns.org/hls-relay/{PROVIDER}/iptv/{TOKEN}/{cid}/index.m3u8'

# ── שדרוגים: שם-ערוץ-קיים-אצלנו → מזהה חדש (איכות גבוהה) ─────────────────
UPGRADES = {
    'HOT cinema 4': '2356',      # HD
    'HOT cinema1':  '2357',      # FHD
    'HOT cinema 3': '2372',      # FHD
    'Hotcinema2':   '12215',     # HD
    'HOT 3':        '2367',      # FHD
    'HOT בידור':    '12219',     # HD
    'ויוה פרימיום': '12226',     # HD
    'ערוץ 24':      '12237',     # HD (היה mcquack)
    'ערוץ ההיסטוריה':'12265',    # FHD
    'נשיונל גאוגרפיק':'12247',   # HD
    'נשיונל ווילד': '12248',     # WILD FHD
    'ספורט 5':      '2341',      # 5SPORT FHD (היה mcquack)
    'ספורט 5 גולד': '12254',     # Gold HD
    'ספורט 5 סטארס':'12278',     # Stars FHD
    'one 1':        '2340',      # ONE HD
    'one 2':        '12231',     # ONE 2 HD
    'הוט זון':      '2360',      # HOT Zone HD (היה mcquack)
    'ים תיכוני':    '12211',     # HD (היה mcquack)
    'ערוץ 9':       '2331',      # FHD
    'Yes Movies Action':'12280', # HD (היה mcquack)
    'הופ!':         '12244',     # HD (היה mcquack)
    'ערוץ גוניור':  '2366',      # ג'וניור HD (נשאר נפרד מדיסני/ניק)
}

# ── הוספות: (מזהה, שם, slug, לוגו) ──────────────────────────────────────
TURK = 'https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRMvuBu2RUSz1BIuI78He2_cfq5BqHrwaQFNT1uxHRCcQ&s=10'
LOGO = 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries'
ADDS = [
    ('2337',  "ניק ג'וניור",       'nick-jr',       f'{LOGO}/israel/nick-jr-il.png'),
    ('12243', 'E!',                 'e-channel',     f'{LOGO}/united-states/e-entertainment-us.png'),
    ('12258', 'yes דוקו',          'yes-doco',      f'{LOGO}/israel/yes-doco-il.png'),
    ('12257', 'הדרמות הטורקיות+',   'turkish-plus',  TURK),
    ('12262', 'הדרמות הטורקיות 2',  'turkish-plus-2',TURK),
    ('12264', 'הדרמות הטורקיות 3',  'turkish-plus-3',TURK),
]

# ── 1. גיבוי ─────────────────────────────────────────────────────────────
stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
bak = CONTENT.with_suffix(f'.json.bak-{stamp}')
shutil.copy2(CONTENT, bak)
print('גיבוי נשמר:', bak)

# ── 2. רישום המארח ברשימה הלבנה (אם חסר) ─────────────────────────────────
hosts = {}
if RELAY_HOSTS.exists():
    raw = json.loads(RELAY_HOSTS.read_text(encoding='utf-8'))
    hosts = raw if isinstance(raw, dict) else {h: {'scheme': 'http', 'port': 80} for h in raw}
if PROVIDER not in hosts:
    hosts[PROVIDER] = {'scheme': 'http', 'port': 80}
    RELAY_HOSTS.write_text(json.dumps(hosts, ensure_ascii=False, indent=1), encoding='utf-8')
    print('נוסף לרשימה הלבנה:', PROVIDER)

# ── 3. שדרוגים ───────────────────────────────────────────────────────────
d = json.loads(CONTENT.read_text(encoding='utf-8'))
by_title = {}
for e in d:
    if e.get('is_live'):
        by_title.setdefault(e.get('title'), []).append(e)

upgraded = up_skip = missing = 0
for title, cid in UPGRADES.items():
    new = url(cid)
    ents = by_title.get(title)
    if not ents:
        print('  ⚠ לא נמצא לשדרוג:', title); missing += 1; continue
    for e in ents:
        if e.get('video_url') == new:
            up_skip += 1
        else:
            e['video_url'] = new
            upgraded += 1
            print(f'  ↑ שודרג: {title}  →  {cid}')

# ── 4. הוספות ────────────────────────────────────────────────────────────
have_titles = {e.get('title') for e in d}
have_slugs = {e.get('custom_slug') for e in d if e.get('custom_slug')}
added = add_skip = 0
for cid, title, slug, logo in ADDS:
    if title in have_titles or slug in have_slugs:
        add_skip += 1; continue
    d.append({
        'id': f'live_{uuid.uuid4()}',
        'is_live': True,
        'title': title,
        'video_url': url(cid),
        'video_id': None,
        'category': 'שידורים חיים',
        'custom_slug': slug,
        'thumbnail_url': logo,
        'type': None, 'series_name': None,
        'created_date': datetime.now(timezone.utc).isoformat(),
    })
    have_titles.add(title); have_slugs.add(slug)
    added += 1
    print(f'  + נוסף: {title}  ({cid})')

# ── 5. שמירה ─────────────────────────────────────────────────────────────
CONTENT.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
print(f'\nסיכום: שודרגו {upgraded} (כבר-מעודכן {up_skip}, חסר {missing}) · '
      f'נוספו {added} (כבר-קיים {add_skip})')
print('עכשיו הפעל מחדש:  systemctl restart zovex-bot')
