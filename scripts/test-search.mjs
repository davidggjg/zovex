// ─────────────────────────────────────────────────────────────────────────────
// חיפוש: הקלדה חייבת להראות תוצאות על אותו מסך.
//
// נכתב אחרי רגרסיה אמיתית: שכבת החיפוש כיסתה את כל המסך והציגה
// "התוצאות מתעדכנות מאחור — סגור כדי לראות אותן". המשתמש הקליד
// "ספורט 4" וראה מסך ריק.
//
//   node scripts/test-search.mjs
// ─────────────────────────────────────────────────────────────────────────────
import { createRequire } from 'node:module';
const { chromium, devices } = createRequire(import.meta.url)('playwright');
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { join, extname } from 'node:path';

const DIST = 'dist', PORT = 8857;
const T = {'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json'};

// קטלוג מדומה: שני פריטים שאפשר לחפש.
const CATALOG = [
  { id: 'a1', title: 'ספורט 4', category: 'שידורים חיים', is_live: true,
    thumbnail_url: '', video_url: 'https://x/1.m3u8', created_date: '2026-01-01T00:00:00Z' },
  { id: 'b2', title: 'משהו אחר לגמרי', category: 'סרטים',
    thumbnail_url: '', video_url: 'https://x/2.mp4', created_date: '2026-01-02T00:00:00Z' },
];

const BASE = await readFile(join(DIST, 'index.html'), 'utf8')
  .then(h => (h.match(/src="(\/[^"]*?)assets\//) || [, '/'])[1]).catch(() => '/');
const strip = u => (BASE !== '/' && u.startsWith(BASE)) ? '/' + u.slice(BASE.length) : u;

const srv = createServer(async (req, res) => {
  const p0 = strip(decodeURIComponent(req.url.split('?')[0]));
  if (/^\/(content|feedback|api|movies\.json)/.test(p0)) {
    const body = Buffer.from(JSON.stringify(
      p0.startsWith('/content/live') ? CATALOG.filter(x => x.is_live) :
      p0.startsWith('/content') || p0 === '/movies.json' ? CATALOG : []), 'utf8');
    res.writeHead(200, {'Content-Type':'application/json; charset=utf-8','Content-Length':String(body.length)});
    return res.end(body);
  }
  let p = join(DIST, p0);
  try { if ((await stat(p)).isDirectory()) p = join(p, 'index.html'); } catch { p = join(DIST, 'index.html'); }
  try { const b = await readFile(p); res.writeHead(200, {'Content-Type': T[extname(p)] || 'application/octet-stream'}); res.end(b); }
  catch { res.writeHead(404); res.end('x'); }
});
await new Promise(r => srv.listen(PORT, r));

let failed = 0;
const check = (n, c, e='') => { console.log(`  ${c?'✅':'❌'} ${n}${e?'  '+e:''}`); if (!c) failed++; };

const br = await chromium.launch();
const ctx = await br.newContext({ ...devices['Pixel 7'] });
const pg = await ctx.newPage();
await pg.goto(`http://127.0.0.1:${PORT}${BASE}`, { waitUntil: 'domcontentloaded' });
await pg.getByText('דלג', { exact: false }).first().click({ timeout: 15000 }).catch(() => {});
await pg.waitForTimeout(3000);

await pg.getByText('חיפוש', { exact: true }).first().click({ timeout: 10000 });
await pg.waitForTimeout(400);
check('נפתחה תיבת חיפוש', await pg.locator('input[placeholder*="חפש"]').count() > 0);

await pg.locator('input[placeholder*="חפש"]').first().fill('ספורט');
await pg.waitForTimeout(1200);

const txt = await pg.$eval('body', e => e.innerText);
check('אין הודעת "סגור כדי לראות"', !txt.includes('סגור כדי לראות'), txt.slice(0,70).replace(/\n/g,' | '));
check('התוצאה מופיעה על אותו מסך', txt.includes('ספורט 4'), txt.slice(0,110).replace(/\n/g,' | '));
check('מה שלא תואם אינו מופיע', !txt.includes('משהו אחר לגמרי'));

// שורת החיפוש אינה מכסה את המסך
const cover = await pg.evaluate(() => {
  const inp = document.querySelector('input[placeholder*="חפש"]');
  if (!inp) return 1;
  let el = inp.parentElement;
  while (el && getComputedStyle(el).position !== 'fixed') el = el.parentElement;
  if (!el) return 1;
  const r = el.getBoundingClientRect();
  return (r.height * r.width) / (innerHeight * innerWidth);
});
check('השכבה אינה מכסה את המסך', cover < 0.25, Math.round(cover * 100) + '% מהמסך');

await br.close(); srv.close();
console.log(failed ? `\n❌ ${failed} נכשלו` : '\n✅ הכל עבר');
process.exit(failed ? 1 : 0);
