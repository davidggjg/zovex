// ─────────────────────────────────────────────────────────────────────────────
// בדיקת מסך מלא בנגן האמיתי, בדפדפן אמיתי, בסביבה שמדמה אייפון.
//
// באייפון אין Fullscreen API על אלמנטים, והדרך היחידה היא
// webkitEnterFullscreen על אלמנט ה-<video>. הבדיקה מסירה את ה-API
// מהאלמנטים, שותלת webkitEnterFullscreen על הווידאו, מרכיבה את הנגן,
// ולוחצת על כפתור המסך המלא — ובודקת שהקריאה אכן יצאה, שהמצב התעדכן,
// ושיציאה חוזרת עובדת.
//
// זו אינה בדיקה על אייפון אמיתי: היא מוודאת שהקוד בוחר את המסלול הנכון
// ושאין כשל שקט. אימות סופי מחייב מכשיר.
//
//   node scripts/test-player-ios.mjs
// ─────────────────────────────────────────────────────────────────────────────
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium, devices } = require('playwright');
const { createServer } = await import('vite');

let failed = 0;
const check = (name, cond, extra = '') => {
  console.log(`  ${cond ? '✅' : '❌'} ${name}${extra ? '  ' + extra : ''}`);
  if (!cond) failed++;
};

const vite = await createServer({
  root: process.cwd(),
  base: '/',   // ברירת המחדל בפרויקט היא /zovex/ — כאן מגישים מהשורש
  server: { port: 8895, strictPort: true },
  logLevel: 'error',
});
await vite.listen();

const browser = await chromium.launch();
const ctx = await browser.newContext({ ...devices['iPhone 13'] });
const page = await ctx.newPage();
const errors = [];
page.on('pageerror', e => errors.push(String(e).slice(0, 200)));
page.on('console', m => { if (m.type() === 'error') console.log('   [console]', m.text().slice(0,200)); });
const warns = [];
page.on('console', m => { if (m.text().includes('[zovex][fullscreen]')) warns.push(m.text()); });

await page.addInitScript(() => {
  // אייפון: אין Fullscreen API על אלמנטים, ואין fullscreenElement.
  delete Element.prototype.requestFullscreen;
  delete Element.prototype.webkitRequestFullscreen;
  Object.defineProperty(document, 'fullscreenElement', { get: () => null, configurable: true });
  Object.defineProperty(document, 'webkitFullscreenElement', { get: () => null, configurable: true });

  window.__calls = [];
  window.__mode = 'ok';   // ok | notready | throw
  let displaying = false;
  HTMLVideoElement.prototype.webkitEnterFullscreen = function () {
    if (window.__mode === 'throw') { const e = new Error('x'); e.name = 'InvalidStateError'; throw e; }
    window.__calls.push('enter'); displaying = true;
    this.dispatchEvent(new Event('webkitbeginfullscreen'));
  };
  HTMLVideoElement.prototype.webkitExitFullscreen = function () {
    window.__calls.push('exit'); displaying = false;
    this.dispatchEvent(new Event('webkitendfullscreen'));
  };
  Object.defineProperty(HTMLVideoElement.prototype, 'webkitDisplayingFullscreen',
    { get: () => displaying, configurable: true });
  Object.defineProperty(HTMLVideoElement.prototype, 'webkitSupportsFullscreen',
    { get: () => window.__mode !== 'nosupport', configurable: true });
});

await page.goto('http://127.0.0.1:8895/scripts/iostest/harness.html', { waitUntil: 'load' });
await page.waitForSelector('[data-cvp] video', { timeout: 15000 });
await page.waitForTimeout(400);

check('הנגן עלה', await page.locator('[data-cvp]').count() === 1);
check('אלמנט וידאו נוצר', await page.locator('[data-cvp] video').count() >= 1);

// הפקדים נעלמים אחרי כמה שניות, ונגיעה במסך כדי להחזירם נוחתת על
// כפתורים אחרים. לכן הלחיצה היא ישירות על הכפתור ב-DOM.
//
// מגבלה שיש לציין: לחיצה כזו אינה "trusted", ולכן היא אינה בודקת את
// דרישת הרשאת הלחיצה של ספארי — רק את בחירת המסלול והדיווח. הדרישה
// הזו נשמרת בקוד בכך שאין setTimeout לפני הקריאה.
const clickFs = async () => {
  // הגנת הלחיצה הכפולה בנגן היא 600ms; בלי ההמתנה הזו הבדיקה הבאה
  // נבלעת על ידה והתוצאה נראית ככישלון של הפיצ'ר.
  await page.waitForTimeout(700);
  const ok = await page.evaluate(() => {
    const bs = [...document.querySelectorAll('[data-cvp] button')];
    const b = bs[bs.length - 1];
    if (!b || !b.querySelector('svg.lucide-maximize, svg.lucide-minimize')) return false;
    b.click();
    return true;
  });
  if (!ok) throw new Error('כפתור המסך המלא לא נמצא במקום הצפוי');
  await page.waitForTimeout(500);
};

// ① הווידאו עוד לא נטען: המשתמש חייב לקבל הסבר ולא שתיקה.
//    readyState נכפה ל-0, כי זה בדיוק המצב שבו הקריאה נדחית בשקט.
await page.evaluate(() => {
  const v = document.querySelector('[data-cvp] video');
  Object.defineProperty(v, 'readyState', { get: () => 0, configurable: true });
});
await clickFs();
const txt1 = await page.locator('[data-cvp]').innerText();
check('מטא-דאטה חסרה — מוצגת הודעה ולא שתיקה', txt1.includes('עדיין נטען'), txt1.split('\n')[0]);
check('לא יצאה קריאה מיותרת', (await page.evaluate(() => window.__calls)).length === 0);

// ② וידאו טעון: הקריאה חייבת לצאת, והמצב להתעדכן מאירוע הווידאו.
await page.evaluate(() => {
  const v = document.querySelector('[data-cvp] video');
  Object.defineProperty(v, 'readyState', { get: () => 4, configurable: true });
});
await clickFs();
check('webkitEnterFullscreen נקרא',
  JSON.stringify(await page.evaluate(() => window.__calls)) === '["enter"]');
check('המצב התעדכן מ-webkitbeginfullscreen',
  await page.evaluate(() => !!document.querySelector('[data-cvp] video').webkitDisplayingFullscreen));

// ③ לחיצה שנייה יוצאת ממסך מלא.
await clickFs();
check('לחיצה שנייה יוצאת ממסך מלא',
  JSON.stringify(await page.evaluate(() => window.__calls)) === '["enter","exit"]');

// ④ המכשיר דוחה: הודעה, לא שתיקה.
await page.evaluate(() => { window.__mode = 'throw'; window.__calls = []; });
await clickFs();
const txt2 = await page.locator('[data-cvp]').innerText();
check('דחייה — מוצגת הודעה', txt2.includes('נדחה'), txt2.split('\n')[0]);
check('הדחייה נרשמה גם בקונסול', warns.length > 0);

// ⑤ כניסה שמצליחה ונשארת: אסור שתופיע אזהרת "המכשיר דחה" אחרי שנייה
//    וחצי. זו הייתה אזהרת שווא שהבדיקה תפסה.
// ההודעה הקודמת נעלמת מעצמה אחרי ארבע שניות. ממתינים לה — וזו גם
// הבדיקה שהיא אכן נעלמת ואינה נשארת על המסך לנצח.
await page.waitForFunction(
  () => !document.querySelector('[data-cvp]').innerText.includes('נדחה'),
  null, { timeout: 6000 });
check('ההודעה נעלמת מעצמה', true);
await page.evaluate(() => { window.__mode = 'ok'; window.__calls = []; });
warns.length = 0;
await clickFs();
await page.waitForTimeout(2200);
check('כניסה מוצלחת אינה מייצרת אזהרת דחייה שקרית',
  !warns.some(w => w.includes('דחה')), warns.join(' | '));
const txt3 = await page.locator('[data-cvp]').innerText();
check('ואין הודעת שגיאה על המסך', !txt3.includes('נדחה') && !txt3.includes('דחה'));

check('אין שגיאות JavaScript', errors.length === 0, errors.join(' | '));

// ── אנדרואיד ודסקטופ: לוודא שלא נשברו ─────────────────────────────────
//
// שם יש Fullscreen API על אלמנטים, והמסלול חייב להישאר requestFullscreen
// על המיכל שלנו (‎[data-cvp]‎) כדי שהפקדים שלנו יישארו גלויים — ולא
// webkitEnterFullscreen על הווידאו, שמחליף אותם בנגן של המערכת.
const ctx2 = await browser.newContext({ ...devices['Pixel 7'] });
const page2 = await ctx2.newPage();
const errors2 = [];
page2.on('pageerror', e => errors2.push(String(e).slice(0, 200)));
await page2.addInitScript(() => {
  window.__req = [];
  window.__videoFs = 0;
  Element.prototype.requestFullscreen = function () {
    window.__req.push(this.getAttribute('data-cvp') !== null ? 'container' : this.tagName);
    return Promise.resolve();
  };
  HTMLVideoElement.prototype.webkitEnterFullscreen = function () { window.__videoFs++; };
});
await page2.goto('http://127.0.0.1:8895/scripts/iostest/harness.html', { waitUntil: 'load' });
await page2.waitForSelector('[data-cvp] video', { timeout: 15000 });
await page2.waitForTimeout(900);
await page2.evaluate(() => {
  const bs = [...document.querySelectorAll('[data-cvp] button')];
  bs[bs.length - 1].click();
});
await page2.waitForTimeout(600);
const req = await page2.evaluate(() => window.__req);
check('אנדרואיד: requestFullscreen על המיכל שלנו', JSON.stringify(req) === '["container"]', JSON.stringify(req));
check('אנדרואיד: לא נפל למסלול האייפון', await page2.evaluate(() => window.__videoFs) === 0);
const t2 = await page2.locator('[data-cvp]').innerText();
check('אנדרואיד: אין הודעת שגיאה', !t2.includes('נדחה') && !t2.includes('עדיין נטען'));
check('אנדרואיד: אין שגיאות JavaScript', errors2.length === 0, errors2.join(' | '));

await browser.close();
await vite.close();
console.log(failed ? `\n❌ ${failed} נכשלו` : '\n✅ הכל עבר');
process.exit(failed ? 1 : 0);
