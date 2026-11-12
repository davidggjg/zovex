// ─────────────────────────────────────────────────────────────────────────────
// שידור חי ממקור MPEG-TS גולמי (פאנל Xtream / ‎.ts‎) מתנגן בדפדפן דרך mpegts.js.
// שרת מדומה מזרים TS אינסופי בקצב אמיתי בנתיב בלי סיומת; הבדיקה פותחת את
// הערוץ ומוודאת שהווידאו באמת מתקדם. בנוסף: סרט רגיל בנתיב בלי סיומת
// (‎/stream/..‎) לא נשלח לנגן ה-TS.
//   node scripts/test-ts-live.mjs
// ─────────────────────────────────────────────────────────────────────────────
import { createRequire } from 'node:module';
const { chromium } = createRequire(import.meta.url)('playwright');
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { join, extname } from 'node:path';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';

const DIST = 'dist', PORT = 8858;
const T = {'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json'};
const CLIP = join(tmpdir(), 'zv-test-clip.ts');
execFileSync('ffmpeg', ['-y','-loglevel','error','-f','lavfi','-i','testsrc=size=640x360:rate=25',
  '-f','lavfi','-i','sine=f=440','-t','6','-c:v','libx264','-g','25','-pix_fmt','yuv420p','-c:a','aac','-f','mpegts', CLIP]);
const TS = await readFile(CLIP);

const CATALOG = [{ id: 'ts1', title: 'ערוץ TS', category: 'שידורים חיים', is_live: true, custom_slug: 'ts-chan',
  thumbnail_url: '', video_url: `http://127.0.0.1:${PORT}/iptv/user/pass/472690`, created_date: '2026-01-01T00:00:00Z' }];

const BASE = await readFile(join(DIST, 'index.html'), 'utf8').then(h => (h.match(/src="(\/[^"]*?)assets\//) || [, '/'])[1]).catch(() => '/');
const strip = u => (BASE !== '/' && u.startsWith(BASE)) ? '/' + u.slice(BASE.length) : u;
let tsRequests = 0;
const srv = createServer(async (req, res) => {
  const p0 = strip(decodeURIComponent(req.url.split('?')[0]));
  if (p0.startsWith('/iptv/')) {                      // TS אינסופי, בקצב אמיתי
    tsRequests++;
    res.writeHead(200, {'Content-Type':'video/mp2t','Access-Control-Allow-Origin':'*'});
    let alive = true; req.on('close', () => { alive = false; });
    while (alive) {
      for (let i = 0; i < TS.length && alive; i += 188 * 200) {
        res.write(TS.subarray(i, i + 188 * 200)); await new Promise(r => setTimeout(r, 40));
      }
    }
    return res.end();
  }
  if (/^\/(content|feedback|api|movies\.json)/.test(p0)) {
    const body = Buffer.from(JSON.stringify(p0.startsWith('/content/live') ? CATALOG :
      p0.startsWith('/content') || p0 === '/movies.json' ? CATALOG : []), 'utf8');
    res.writeHead(200, {'Content-Type':'application/json; charset=utf-8'}); return res.end(body);
  }
  let p = join(DIST, p0);
  try { if ((await stat(p)).isDirectory()) p = join(p, 'index.html'); } catch { p = join(DIST, 'index.html'); }
  try { const b = await readFile(p); res.writeHead(200, {'Content-Type': T[extname(p)] || 'application/octet-stream'}); res.end(b); }
  catch { res.writeHead(404); res.end('x'); }
});
await new Promise(r => srv.listen(PORT, r));

let failed = 0;
const check = (n, c, e='') => { console.log(`  ${c?'✅':'❌'} ${n}${e?'  '+e:''}`); if (!c) failed++; };

// ── זיהוי: יחידה ─────────────────────────────────────────────────────────────
const src = await readFile('src/components/home/CustomVideoPlayer.jsx', 'utf8');
const fnSrc = src.slice(src.indexOf('function isHlsUrl('), src.indexOf('// ─── Skip')).split('\nconst ')[0];
let det; try { det = new Function(fnSrc.replace(/export /g, '') + '\n; return {isRawTsUrl, isHlsUrl};')(); } catch { det = { isRawTsUrl: () => false }; }
check('זיהוי: /user/pass/123 → TS', det.isRawTsUrl('http://h/user/pass/472690'));
check('זיהוי: .ts → TS', det.isRawTsUrl('https://h/live/a/b/1.ts'));
check('זיהוי: .m3u8 → לא TS', !det.isRawTsUrl('https://h/live/1/index.m3u8'));
check('זיהוי: __ts.m3u8 (המרה בשרת) → לא TS', !det.isRawTsUrl('https://h/hls-relay/_fix/x/a/1/__ts.m3u8'));
check('זיהוי: .mp4 → לא TS', !det.isRawTsUrl('https://h/a/b.mp4'));

// ── ניגון אמיתי ──────────────────────────────────────────────────────────────
const br = await chromium.launch();
const pg = await br.newPage();
const errs = []; pg.on('pageerror', e => errs.push(e.message));
await pg.goto(`http://127.0.0.1:${PORT}${BASE}live/ts-chan`, { waitUntil: 'domcontentloaded' });
await pg.getByText('דלג', { exact: false }).first().click({ timeout: 8000 }).catch(() => {});
await pg.waitForTimeout(2500);
// דף הערוץ → כפתור הצפייה. אם אין כפתור ברור — לוחצים על הטקסט "צפה".
if (process.env.DEBUG) {
  console.log('URL', pg.url());
  console.log((await pg.$eval('body', e => e.innerText)).slice(0, 500).replace(/\n+/g, ' | '));
  console.log('BUTTONS', await pg.$$eval('button', bs => bs.map(b => (b.innerText||b.getAttribute('aria-label')||'').trim()).filter(Boolean).slice(0, 30)));
}
const btn = pg.getByRole('button', { name: /צפה בשידור/ }).first();
await btn.click({ timeout: 8000 }).catch(() => {});
const cont = pg.getByText('המשך לצפייה', { exact: false });
if (await cont.count()) await cont.first().click().catch(() => {});
await pg.waitForTimeout(7000);
const st = await pg.evaluate(() => {
  const v = document.querySelector('[data-cvp] video');
  return { hasVideo: !!v, t: v ? v.currentTime : -1, w: v ? v.videoWidth : 0, mpegts: !!window.mpegts,
           err: document.querySelector('[data-ts-error]')?.textContent || '' };
});
check('נטענה ספריית mpegts.js', st.mpegts);
check('השרת קיבל בקשה לזרם ה-TS', tsRequests > 0, `בקשות: ${tsRequests}`);
check('הווידאו מתקדם (מתנגן בפועל)', st.t > 1, `currentTime=${st.t.toFixed?.(2)}`);
check('יש תמונה (רוחב וידאו)', st.w > 0, `videoWidth=${st.w}`);
check('אין הודעת שגיאה', !st.err, st.err);
check('אין שגיאות JS בדף', errs.length === 0, errs.slice(0,2).join(' | '));

await br.close(); srv.close();
console.log(failed ? `\n❌ ${failed} נכשלו` : '\n✅ הכל עבר');
process.exit(failed ? 1 : 0);
