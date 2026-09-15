"""test_vh_cache.py — בודק את מטמון /vh על תהליכים וקבצים אמיתיים.

הקוד נשלף מתוך main.py המתוקן עצמו ולא מועתק לכאן, כדי שהבדיקה לא
תבדוק עותק שהתיישן. ffmpeg מוחלף בפקודות sh שמתנהגות כמוהו — מצליחות,
נכשלות, או מוציאות פלט ריק — ולכן אפשר להריץ את זה בלי מדיה ובלי שרת.

    python3 test_vh_cache.py /opt/zovex-bot/main.py
"""
import ast, asyncio, os, sys, time, logging, tempfile, textwrap
from pathlib import Path

MAIN = Path(sys.argv[1] if len(sys.argv) > 1 else '/opt/zovex-bot/main.py')
if '# [fix_vh_cache]' not in MAIN.read_text(encoding='utf-8'):
    sys.exit(f'{MAIN} לא מכיל את טלאי המטמון — אין מה לבדוק')
SRC = MAIN.read_text(encoding='utf-8')
tree = ast.parse(SRC)
lines = SRC.splitlines(True)

WANT_FN = {'_vf_sem', '_vf_cache_path', '_vf_cache_sweep', '_vf_cached_response',
           '_vf_build_to_cache', '_vf_schedule_readahead'}
WANT_VAR = {'_VF_CACHE_DIR', '_VF_CACHE_MAX', '_VF_READAHEAD',
            '_VF_MAX_ENCODERS', '_vf_build_locks', '_vf_readahead',
            '_vf_encode_sem', '_vf_sweep_at'}
chunks = []
for n in tree.body:
    name = getattr(n, 'name', None)
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and name in WANT_FN:
        chunks.append(''.join(lines[n.lineno - 1:n.end_lineno]))
    elif isinstance(n, (ast.Assign, ast.AnnAssign)):
        tgt = n.targets[0] if isinstance(n, ast.Assign) else n.target
        if isinstance(tgt, ast.Name) and tgt.id in WANT_VAR:
            chunks.append(''.join(lines[n.lineno - 1:n.end_lineno]))
print(f'נשלפו {len(chunks)} הגדרות מתוך הקובץ המתוקן')

CACHE = tempfile.mkdtemp(prefix='vhcache-')
env = {
    'os': os, 'time': time, 'asyncio': asyncio, 'Path': Path,
    'log': logging.getLogger('t'),
    'HTTPException': type('HTTPException', (Exception,), {}),
    'StreamingResponse': lambda gen, **kw: ('RESP', kw.get('headers', {}), gen),
    'CORS_MEDIA': {'Access-Control-Allow-Origin': '*'},
}
exec(''.join(chunks), env)
# תקרה קטנה כדי שהניקוי ייבדק באמת, ותיקייה זמנית
env['_VF_CACHE_DIR'] = Path(CACHE)
env['_VF_CACHE_MAX'] = 300_000
env['_VF_READAHEAD'] = 2

ok = lambda c, m: print(('  ✓ ' if c else '  ✗ ') + m) or c
results = []

async def main():
    B = env['_vf_build_to_cache']; P = env['_vf_cache_path']
    dest = P(-100, 9250, 0)

    print('\n1. בנייה מוצלחת → הקובץ במטמון, בלי .part שנשאר')
    args = ['sh', '-c', 'head -c 120000 /dev/zero']
    r = await B(-100, 9250, 0, args, dest)
    results.append(ok(r and dest.exists() and dest.stat().st_size == 120000,
                      f'נכתב {dest.stat().st_size if dest.exists() else 0} בייט'))
    results.append(ok(not list(Path(CACHE).rglob('*.part')), 'אין קבצי .part'))
    results.append(ok(not env['_vf_build_locks'], 'מילון המנעולים התרוקן'))

    print('\n2. קריאה שנייה → לא מקודדת שוב')
    t0 = time.time()
    r = await B(-100, 9250, 0, ['sh', '-c', 'sleep 5; echo x'], dest)
    results.append(ok(r and time.time() - t0 < 1, f'חזר ב-{time.time()-t0:.2f}s בלי להריץ'))

    print('\n3. ffmpeg שנכשל → לא נשמר כלום, ואין .part')
    d2 = P(-100, 9250, 1)
    r = await B(-100, 9250, 1, ['sh', '-c', 'echo boom >&2; exit 1'], d2)
    results.append(ok(r is False and not d2.exists(), 'לא נוצר קובץ מטמון'))
    results.append(ok(not list(Path(CACHE).rglob('*.part')), 'אין .part שנשאר'))

    print('\n4. פלט ריק בקוד יציאה 0 → נדחה גם הוא')
    d3 = P(-100, 9250, 2)
    r = await B(-100, 9250, 2, ['sh', '-c', 'exit 0'], d3)
    results.append(ok(r is False and not d3.exists(), 'קובץ באורך אפס לא נכנס'))

    print('\n5. שתי בקשות במקביל לאותו מקטע → קידוד אחד')
    d4 = P(-100, 9250, 3)
    runs = Path(CACHE) / 'runs'
    a = ['sh', '-c', f'echo r >> {runs}; head -c 50000 /dev/zero']
    await asyncio.gather(B(-100, 9250, 3, a, d4), B(-100, 9250, 3, a, d4))
    n = runs.read_text().count('r') if runs.exists() else 0
    results.append(ok(n == 1, f'ffmpeg רץ {n} פעם'))

    print('\n6. ניקוי לפי תקרה (300KB)')
    env['_vf_sweep_at'] = 0
    for i in range(10, 16):
        p = P(-100, 9250, i); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'x' * 60000)
        os.utime(p, (time.time() - (100 - i), time.time() - (100 - i)))
    before = sum(f.stat().st_size for f in Path(CACHE).rglob('s*.ts'))
    env['_vf_cache_sweep']()
    after = sum(f.stat().st_size for f in Path(CACHE).rglob('s*.ts'))
    results.append(ok(after <= 300_000 and after < before,
                      f'{before//1000}KB → {after//1000}KB (תקרה 300KB)'))
    oldest_gone = not P(-100, 9250, 10).exists()
    newest_here = P(-100, 9250, 15).exists()
    results.append(ok(oldest_gone and newest_here, 'הישן נמחק, החדש נשאר'))

    print('\n7. שער הדקה — סריקה שנייה מיד לא עושה כלום')
    for i in range(20, 26):
        p = P(-100, 9250, i); p.write_bytes(b'x' * 60000)
    big = sum(f.stat().st_size for f in Path(CACHE).rglob('s*.ts'))
    env['_vf_cache_sweep']()
    same = sum(f.stat().st_size for f in Path(CACHE).rglob('s*.ts'))
    results.append(ok(same == big, f'לא סרק שוב ({same//1000}KB ללא שינוי)'))

    print('\n8. קידום מראש — לא מכפיל, ומדלג על מה שבמטמון')
    env['_vf_seg_args'] = lambda c, m, i, s: ['sh', '-c', 'head -c 1000 /dev/zero']
    exec("def _vf_seg_args(c,m,i,s):\n return ['sh','-c','head -c 1000 /dev/zero']", env)
    info = {'segments': [(0, 10)] * 8, 'header': None}
    S = env['_vf_schedule_readahead']
    S(-100, 9250, 0, info); S(-100, 9250, 0, info)
    await asyncio.sleep(1.5)
    built = [i for i in (1, 2) if P(-100, 9250, i).exists()]
    results.append(ok(set(built) == {1, 2}, f'נבנו מראש: {built}'))
    results.append(ok(not env['_vf_readahead'], 'סט הקידום-מראש התרוקן'))

    print('\n9. הגשה מהדיסק → Content-Length אמיתי')
    resp = env['_vf_cached_response'](dest)
    cl = resp[1].get('Content-Length')
    body = b''.join(resp[2])
    results.append(ok(cl == '120000' and len(body) == 120000,
                      f'Content-Length={cl}, גוף={len(body)}'))

asyncio.run(main())
print(f"\n{'='*52}\n{sum(results)}/{len(results)} עברו")
sys.exit(0 if all(results) else 1)
