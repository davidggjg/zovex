"""בודק אילו שידורים חיים באמת עובדים ואילו מתים.

הערוצים החיים לא מגיעים מטלגרם אלא מספק IPTV חיצוני, דרך ה-hls-relay. כשהם
"לא עובדים" זה כמעט תמיד אחד משלושה: הספק נפל, הטוקן פג, או שהערוץ הוסר
אצלו. הסקריפט הזה מושך את ה-playlist של כל ערוץ ואומר בדיוק מי חי ומי לא —
במקום לנחש ערוץ-ערוץ.

הרצה:
    /opt/zovex-bot/venv/bin/python /opt/zovex-bot/check_live.py           # הכל
    /opt/zovex-bot/venv/bin/python /opt/zovex-bot/check_live.py --bad     # רק תקולים
    /opt/zovex-bot/venv/bin/python /opt/zovex-bot/check_live.py --timeout 8
"""
import json
import pathlib
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

DATA = pathlib.Path('/opt/zovex-bot/data/content.json')
LIVE_CATEGORY = 'שידורים חיים'
ONLY_BAD = '--bad' in sys.argv
TIMEOUT = 6
for i, a in enumerate(sys.argv):
    if a == '--timeout' and i + 1 < len(sys.argv):
        TIMEOUT = int(sys.argv[i + 1])

UA = 'Mozilla/5.0 (SmartTV) AppleWebKit/537.36 Chrome/120 Safari/537.36'


def probe(entry):
    """מושך את תחילת ה-playlist ומחזיר (סטטוס, פרט)."""
    url = entry.get('video_url') or entry.get('video_id') or ''
    name = entry.get('title') or entry.get('name') or '?'
    if not url:
        return name, 'NO_URL', 'אין כתובת בכלל'
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read(2048).decode('utf-8', 'ignore')
            ms = int((time.time() - t0) * 1000)
            if r.status != 200:
                return name, 'HTTP_%d' % r.status, '%dms' % ms
            # playlist תקין של HLS מתחיל ב-#EXTM3U
            if '#EXTM3U' in body:
                n = body.count('#EXT-X-STREAM-INF') + body.count('#EXTINF')
                return name, 'OK', '%dms, %d מקטעים' % (ms, n)
            return name, 'NOT_HLS', 'התשובה אינה playlist (%dms)' % ms
    except urllib.error.HTTPError as e:
        return name, 'HTTP_%d' % e.code, str(e.reason)[:40]
    except Exception as e:
        return name, type(e).__name__, str(e)[:50]


def main():
    d = json.loads(DATA.read_text(encoding='utf-8'))
    live = [e for e in d if e.get('is_live') or e.get('category') == LIVE_CATEGORY]
    if not live:
        print('לא נמצאו שידורים חיים בקטלוג.')
        return
    print('בודק %d ערוצים (timeout %ds)...\n' % (len(live), TIMEOUT))

    with ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(probe, live))

    ok = [r for r in results if r[1] == 'OK']
    bad = [r for r in results if r[1] != 'OK']

    if not ONLY_BAD and ok:
        print('── עובדים (%d) ──' % len(ok))
        for name, _, detail in sorted(ok):
            print('  ✅ %-32s %s' % (name[:32], detail))
        print()

    if bad:
        print('── תקולים (%d) ──' % len(bad))
        by_reason = {}
        for name, status, detail in bad:
            by_reason.setdefault(status, []).append((name, detail))
        for status in sorted(by_reason):
            print('  [%s] — %d ערוצים' % (status, len(by_reason[status])))
            for name, detail in sorted(by_reason[status])[:40]:
                print('     ✗ %-30s %s' % (name[:30], detail))
        print()

    print('─────────────────────')
    print('סה"כ %d | עובדים %d | תקולים %d' % (len(results), len(ok), len(bad)))
    if bad and len(bad) > len(results) * 0.6:
        print('\nרוב הערוצים תקולים — כמעט בוודאות הספק החיצוני נפל או שהטוקן פג,')
        print('ולא תקלה אצלנו. שווה לבדוק מול הספק לפני שנוגעים בקוד.')


if __name__ == '__main__':
    main()
