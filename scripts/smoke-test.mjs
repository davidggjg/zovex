// ─────────────────────────────────────────────────────────────────────────────
// בדיקת עשן לבנייה: טוען את dist/ בדפדפן אמיתי ונכשל על מסך לבן.
//
// נכתב אחרי תקלה אמיתית: Home.jsx מייבא hooks בשמם ולא את React עצמו,
// וקוד שהשתמש ב-React.useMemo עבר קומפילציה בלי הערה — ונפל רק בדפדפן.
// האתר עלה עם מסך לבן, ואיש לא ידע עד שמשתמש דיווח.
//
// Vite אינו תופס גלובל שאינו מוגדר; רק הרצה אמיתית תופסת. זו הבדיקה
// שהייתה חוסכת את זה.
//
//   node scripts/smoke-test.mjs
// ─────────────────────────────────────────────────────────────────────────────
import { createRequire } from 'node:module';
// playwright מותקן גלובלית בסביבת הבנייה ולא כתלות של הפרויקט, ולכן
// import רגיל אינו פותר אותו מתוך תיקיית הפרויקט.
const { chromium } = createRequire(import.meta.url)('playwright');
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { join, extname } from 'node:path';

const DIST = 'dist';
const PORT = 8899;
const TYPES = {'.html':'text/html','.js':'text/javascript','.css':'text/css',
               '.json':'application/json','.svg':'image/svg+xml','.png':'image/png',
               '.ico':'image/x-icon','.webp':'image/webp','.jpg':'image/jpeg'};

const server = createServer(async (req, res) => {
  let p = join(DIST, decodeURIComponent(req.url.split('?')[0]));
  try {
    if ((await stat(p)).isDirectory()) p = join(p, 'index.html');
  } catch {
    p = join(DIST, 'index.html');          // נפילה חזרה ל-SPA
  }
  try {
    const buf = await readFile(p);
    res.writeHead(200, {'Content-Type': TYPES[extname(p)] || 'application/octet-stream'});
    res.end(buf);
  } catch {
    res.writeHead(404); res.end('not found');
  }
});

await new Promise(r => server.listen(PORT, r));
const browser = await chromium.launch();
const page = await browser.newPage();
const errors = [];
page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 200)); });
page.on('pageerror', e => errors.push('PAGEERROR: ' + String(e).slice(0, 200)));

let failed = false;
try {
  await page.goto(`http://127.0.0.1:${PORT}/`, {waitUntil: 'load', timeout: 25000});
  await page.waitForTimeout(4000);
  const len = await page.$eval('#root', el => el.innerHTML.length);
  // שגיאות רשת צפויות כאן (אין גישה ל-API), ולכן נספרות רק שגיאות
  // שמעידות על קוד שבור.
  const fatal = errors.filter(e =>
    /is not defined|Cannot read|undefined is not|Minified React error/.test(e));

  console.log(`תוכן ב-#root: ${len} תווים`);
  console.log(`שגיאות קריטיות: ${fatal.length}`);
  fatal.slice(0, 8).forEach(e => console.log('  ❌ ' + e));

  if (len < 500) { console.log('❌ מסך לבן — האתר לא רונדר'); failed = true; }
  if (fatal.length) { console.log('❌ שגיאות קוד בזמן ריצה'); failed = true; }
  if (!failed) console.log('✅ הבנייה נטענת ומרנדרת');
} catch (e) {
  console.log('❌ הטעינה נכשלה: ' + e.message);
  failed = true;
} finally {
  await browser.close();
  server.close();
}
process.exit(failed ? 1 : 0);
