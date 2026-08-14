"""מאתר מתי ואיך נמחק תוכן מהקטלוג, לפי הגיבויים האוטומטיים.

השרת שומר עותק של content.json לפני כל שמירה (עד 30 אחרונים). השוואה בין
גיבויים עוקבים מראה בדיוק באיזו שמירה נעלמו פריטים, כמה, ואילו — וזה מזהה את
הגורם הרבה יותר טוב מקריאת קוד.

הרצה:  python3 diag_deletions.py
"""
import json, pathlib, datetime, collections

DATA = pathlib.Path('/opt/zovex-bot/data')
CUR = DATA / 'content.json'
BAKS = DATA / 'content_backups'

def load(p):
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        return d if isinstance(d, list) else []
    except Exception:
        return []

def key(e):
    """מזהה יציב לפריט — id אם יש, אחרת כותרת+פרק."""
    return e.get('id') or f"{e.get('title')}|{e.get('season_number')}|{e.get('episode_number')}"

def when(p):
    try:
        return datetime.datetime.fromtimestamp(int(p.stem.split('_')[1]))
    except Exception:
        return datetime.datetime.fromtimestamp(p.stat().st_mtime)

snaps = sorted(BAKS.glob('content_*.json'), key=when) if BAKS.exists() else []
if not snaps:
    print('אין גיבויים בכלל — הבעיה עצמה: אין ממה לשחזר ואי אפשר לאבחן.')
    raise SystemExit

print(f'{len(snaps)} גיבויים, מ-{when(snaps[0]):%d/%m %H:%M} עד {when(snaps[-1]):%d/%m %H:%M}\n')

print('═══ גודל הקטלוג לאורך זמן ═══')
rows = [(when(p), load(p), p.name) for p in snaps]
rows.append((datetime.datetime.now(), load(CUR), 'content.json (נוכחי)'))
prev_n = None
drops = []
for ts, arr, name in rows:
    n = len(arr)
    delta = '' if prev_n is None else f'{n - prev_n:+d}'
    flag = ''
    if prev_n is not None and n < prev_n:
        flag = '  ← ירידה'
        drops.append((ts, prev_n, n, name))
    print(f'  {ts:%d/%m %H:%M}  {n:6}  {delta:>7}{flag}')
    prev_n = n

if not drops:
    print('\n✅ אף גיבוי לא מראה ירידה במספר הפריטים.')
    print('   כלומר המחיקה לא קרתה דרך שמירה רגילה — או שהיא ישנה מהגיבוי הראשון.')
else:
    print(f'\n═══ {len(drops)} ירידות — מה נעלם בכל אחת ═══')
    for i, (ts, before, after, name) in enumerate(drops):
        idx = next(j for j, (t, _, nm) in enumerate(rows) if nm == name)
        gone_keys = {key(e) for e in rows[idx - 1][1]} - {key(e) for e in rows[idx][1]}
        gone = [e for e in rows[idx - 1][1] if key(e) in gone_keys]
        cats = collections.Counter(e.get('category') or '(ריק)' for e in gone)
        series = collections.Counter(e.get('series_name') for e in gone if e.get('series_name'))
        print(f'\n  ── {ts:%d/%m %H:%M}   {before} → {after}  (נעלמו {len(gone)}) ──')
        print(f'     קטגוריות: {dict(cats.most_common(5))}')
        if series:
            print(f'     סדרות:    {dict(series.most_common(5))}')
        for e in gone[:6]:
            print(f'       · {e.get("title")}  [{e.get("category")}]')

print('\n═══ בדיקת דרגון בול ═══')
for ts, arr, name in rows:
    hits = [e for e in arr if 'דרגון' in (e.get('title') or '') or
            'דרגון' in (e.get('series_name') or '') or
            'dragon' in (e.get('title') or '').lower()]
    if hits:
        print(f'  {ts:%d/%m %H:%M}  {name}: {len(hits)} פריטים')
if not any('דרגון' in (e.get('title') or '') or 'dragon' in (e.get('title') or '').lower()
           for _, arr, _ in rows for e in arr):
    print('  לא נמצא באף גיבוי — נמחק לפני שהגיבוי הישן ביותר נוצר.')
