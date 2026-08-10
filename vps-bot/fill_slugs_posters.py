"""משלים slug אנגלי ופוסטר לפריטים שחסר להם, לפי TMDB.

למה TMDB ולא תעתיק: המוסכמה הקיימת בחלק מהפריטים היא תעתיק עברי ("פטריק"
→ ptryk), שנותן כתובות לא קריאות ולא מועילות ל-SEO. TMDB מחזיר את השם
האנגלי האמיתי (Patrick) וגם פוסטר רשמי — שני החוסרים באותה שאילתה.

הרצה:
    /opt/zovex-bot/venv/bin/python fill_slugs_posters.py          # תצוגה בלבד
    /opt/zovex-bot/venv/bin/python fill_slugs_posters.py --apply  # מבצע

בטיחות: ברירת המחדל היא dry-run. ב---apply נוצר גיבוי לפני הכתיבה.
"""
import json
import os
import re
import sys
import time
import pathlib
import unicodedata
import urllib.parse
import urllib.request

DATA = pathlib.Path('/opt/zovex-bot/data/content.json')
ENV = pathlib.Path('/opt/zovex-bot/.env')
TMDB_IMG = 'https://image.tmdb.org/t/p/w500'
APPLY = '--apply' in sys.argv
# --heavy: מחליף גם פוסטרים כבדים במיוחד. נמדד: תמונות base44 שוקלות ~1.9MB
# כל אחת (תמונה בגודל מלא בכרטיסייה של 150px), מול ~0.1MB לאותו פוסטר מ-TMDB.
HEAVY = '--heavy' in sys.argv
HEAVY_HOSTS = ('base44.app',)


def read_env(key: str) -> str:
    try:
        for line in ENV.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                if k.strip() == key:
                    return v.strip().strip('"').strip("'")
    except Exception:
        pass
    return ''


API_KEY = read_env('TMDB_API_KEY')


def slugify(s: str) -> str:
    """שם אנגלי → slug נקי לכתובת."""
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[''`]", '', s)
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return re.sub(r'-+', '-', s).strip('-')


def tmdb(query: str, year: str = '', want_tv=None):
    """מחזיר (שם_אנגלי, פוסטר) או (None, None). מדרג לפי התאמת שנה וסוג."""
    if not API_KEY or not query:
        return None, None
    url = 'https://api.themoviedb.org/3/search/multi?' + urllib.parse.urlencode({
        'api_key': API_KEY, 'query': query, 'language': 'en-US', 'include_adult': 'false'})
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            res = json.load(r).get('results', [])
    except Exception as e:
        print('   ! TMDB נכשל: %s' % e)
        return None, None

    best, best_score = None, -1
    for it in res:
        mt = it.get('media_type')
        if mt not in ('movie', 'tv'):
            continue
        title = it.get('title') or it.get('name') or ''
        if not title:
            continue
        date = it.get('release_date') or it.get('first_air_date') or ''
        score = 0
        if year and date[:4] == str(year):
            score += 3
        if want_tv is not None and ((mt == 'tv') == want_tv):
            score += 2
        if it.get('poster_path'):
            score += 1
        score += min(it.get('popularity', 0), 50) / 100.0
        if score > best_score:
            best, best_score = it, score
    if not best:
        return None, None
    title = best.get('title') or best.get('name') or ''
    poster = (TMDB_IMG + best['poster_path']) if best.get('poster_path') else None
    return title, poster


def has(e, k):
    v = e.get(k)
    return bool(v and str(v).strip())


def is_heavy_poster(e) -> bool:
    u = e.get('thumbnail_url') or ''
    return any(h in u for h in HEAVY_HOSTS)


def main():
    if not API_KEY:
        print('❌ אין TMDB_API_KEY ב-.env — אי אפשר להמשיך')
        return
    d = json.loads(DATA.read_text(encoding='utf-8'))

    live = [e for e in d if e.get('category') == 'שידורים חיים']
    rest = [e for e in d if e.get('category') != 'שידורים חיים']
    movies = [e for e in rest if not e.get('series_name')]
    series = {}
    for e in rest:
        if e.get('series_name'):
            series.setdefault(e['series_name'], []).append(e)

    slugs_taken = {e.get('custom_slug') for e in d if has(e, 'custom_slug')}
    changed = 0

    def uniq(slug):
        if slug not in slugs_taken:
            return slug
        for i in range(2, 50):
            c = '%s-%d' % (slug, i)
            if c not in slugs_taken:
                return c
        return None

    print('═══ סרטים ═══')
    for e in movies:
        need_slug = not has(e, 'custom_slug')
        need_post = not has(e, 'thumbnail_url') or (HEAVY and is_heavy_poster(e))
        if not (need_slug or need_post):
            continue
        title, poster = tmdb(e.get('title', ''), e.get('year', ''), want_tv=False)
        if not title:
            print('  ? %-30s — לא נמצא ב-TMDB' % (e.get('title') or '')[:30])
            continue
        if need_slug:
            s = uniq(slugify(title))
            if s:
                e['custom_slug'] = s
                slugs_taken.add(s)
                changed += 1
                print('  slug   %-28s → %s' % ((e.get('title') or '')[:28], s))
        if need_post and poster:
            was_heavy = is_heavy_poster(e)
            e['thumbnail_url'] = poster
            changed += 1
            print('  פוסטר  %-28s → TMDB%s' % ((e.get('title') or '')[:28],
                                               '  (החליף כבד)' if was_heavy else ''))
        time.sleep(0.3)

    print('\n═══ סדרות ═══')
    for name, eps in series.items():
        need_slug = not any(has(x, 'custom_slug') for x in eps)
        need_post = (not any(has(x, 'thumbnail_url') for x in eps)
                     or (HEAVY and any(is_heavy_poster(x) for x in eps)))
        if not (need_slug or need_post):
            continue
        yr = next((x.get('year') for x in eps if x.get('year')), '')
        title, poster = tmdb(name, yr, want_tv=True)
        if not title:
            print('  ? %-30s — לא נמצא ב-TMDB' % name[:30])
            continue
        if need_slug:
            s = uniq(slugify(title))
            if s:
                for x in eps:          # סדרה מאחסנת את אותו slug בכל הפרקים
                    x['custom_slug'] = s
                slugs_taken.add(s)
                changed += 1
                print('  slug   %-28s → %-24s (%d פרקים)' % (name[:28], s, len(eps)))
        if need_post and poster:
            n = 0
            for x in eps:
                if not has(x, 'thumbnail_url') or (HEAVY and is_heavy_poster(x)):
                    x['thumbnail_url'] = poster
                    n += 1
            changed += 1
            print('  פוסטר  %-28s → TMDB (%d פרקים)' % (name[:28], n))
        time.sleep(0.3)

    print('\n─────────────────────')
    if not changed:
        print('אין מה לעדכן.')
        return
    if not APPLY:
        print('%d שינויים — תצוגה בלבד. להרצה אמיתית: הוסף --apply' % changed)
        return
    bak = DATA.with_name('content_before_slugs_%d.json' % int(time.time()))
    bak.write_text(DATA.read_text(encoding='utf-8'), encoding='utf-8')
    DATA.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')
    print('בוצעו %d שינויים. גיבוי: %s' % (changed, bak.name))


if __name__ == '__main__':
    main()
