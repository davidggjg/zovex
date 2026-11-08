// ─────────────────────────────────────────────────────────────────────────────
// בורר הקטגוריות: כל פריט חייב להיות לחיץ, לא רק גלוי.
//
// נכתב אחרי שתי תקלות אמיתיות באותו מקום: כפתור סגירה לבן ‎fixed‎
// שריחף מעל הרשימה וכיסה את "היסטוריה", ואחר כך סרגל הניווט
// (zIndex 999) שכיסה את שתי השורות התחתונות של הגיליון.
//
// לכן הבדיקה אינה שואלת "האם הפריט מצויר" אלא "מי נמצא מעליו
// בנקודה שבה המשתמש לוחץ" — elementFromPoint.
//
//   node scripts/test-categories.mjs
// ─────────────────────────────────────────────────────────────────────────────
import { createRequire } from 'node:module';
const { chromium, devices } = createRequire(import.meta.url)('playwright');
import { spawn } from 'node:child_process';
import { readFile } from 'node:fs/promises';
const srv = spawn('node', ['scripts/serve-dist.mjs', '8850'], { stdio: 'ignore' });
await new Promise(r => setTimeout(r, 2500));
const BASE = await readFile('dist/index.html', 'utf8')
  .then(h => (h.match(/src="(\/[^"]*?)assets\//) || [, '/'])[1]).catch(() => '/');
let failed = 0;
const check = (n, c, e='') => { console.log(`  ${c?'✅':'❌'} ${n}${e?'  '+e:''}`); if(!c) failed++; };
const br = await chromium.launch();
const ctx = await br.newContext({ ...devices['Pixel 7'] });
const pg = await ctx.newPage();
await pg.goto(`http://127.0.0.1:8850${BASE}`, { waitUntil: 'domcontentloaded' });
await pg.getByText('דלג', { exact: false }).first().click({ timeout: 15000 }).catch(()=>{});
await pg.waitForTimeout(3500);
await pg.getByText('קטגוריות:', { exact: false }).first().click({ timeout: 10000 });
await pg.waitForTimeout(900);
// כל פריט ברשימה: האם הוא גלוי ולא מכוסה?
const r = await pg.evaluate(() => {
  const sheet = [...document.querySelectorAll('div')].find(d =>
    d.style.maxHeight === '86vh');
  if (!sheet) return { sheet: false };
  const items = [...sheet.querySelectorAll('button')].filter(b => b.innerText.trim());
  // גבולות אזור הגלילה בתוך הגיליון. פריט שנגלל מחוץ לו אינו
  // "מכוסה" — צריך רק לגלול אליו. בלי ההבחנה הזו הבדיקה מדווחת
  // על כל פריט שמתחת לקיפול, וזה ממצא שווא.
  const sr = sheet.getBoundingClientRect();
  const bad = [];
  for (const b of items) {
    const r2 = b.getBoundingClientRect();
    if (r2.height === 0) continue;
    const cx = r2.left + r2.width / 2, cy = r2.top + r2.height / 2;
    if (cy < 0 || cy > innerHeight) continue;          // מחוץ למסך = גלילה, תקין
    if (cy < sr.top + 2 || cy > sr.bottom - 2) continue; // נגלל מחוץ לגיליון
    const top = document.elementFromPoint(cx, cy);
    if (top && !b.contains(top) && top !== b) {
      const cs = getComputedStyle(top);
      bad.push(b.innerText.trim().replace(/\s+/g,' ') + ' ← ' + top.tagName +
               ' z=' + cs.zIndex + ' pos=' + cs.position);
    }
  }
  return { sheet: true, n: items.length,
           names: items.map(b => b.innerText.trim().replace(/\s+/g, ' ')), covered: bad };
});
check('הגיליון נפתח', r.sheet === true);
check('יש קטגוריות ברשימה', (r.n || 0) >= 5, String(r.n));
// שתי תקלות אמיתיות נתפסו כאן: כפתור סגירה צף שכיסה את הפריט
// האחרון ("היסטוריה"), ואחר כך סרגל הניווט (zIndex 999) שכיסה את
// שתי השורות התחתונות. לכן הבדיקה עוברת על כל פריט גלוי ושואלת
// מי באמת נמצא מעליו בנקודה שבה לוחצים.
check('אף קטגוריה אינה מכוסה', (r.covered || []).length === 0,
      (r.covered || []).join(' | '));
await br.close(); srv.kill();
console.log(failed ? `\n❌ ${failed} נכשלו` : '\n✅ הכל עבר');
process.exit(failed ? 1 : 0);
