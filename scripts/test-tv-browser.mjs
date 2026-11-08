// בודק בדפדפן אמיתי שמצב הטלוויזיה נדלק רק בטלוויזיה, ושחצים מזיזים פוקוס.
import { createRequire } from 'node:module';
const { chromium } = createRequire(import.meta.url)('playwright');
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { join, extname } from 'node:path';
const DIST='dist', PORT=8867;
const T={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json'};
// הבנייה הרגילה יוצאת עם base=/zovex/, ולכן הנכסים מבוקשים מ-
// /zovex/assets/… . שרת שמגיש מהשורש החזיר להם index.html, הדפדפן
// סירב לטעון מודול עם MIME של HTML, והבדיקה "נכשלה" על בנייה תקינה.
const BASE = await readFile(join(DIST, 'index.html'), 'utf8')
  .then(h => (h.match(/src="(\/[^"]*?)assets\//) || [, '/'])[1])
  .catch(() => '/');
const strip = u => (BASE !== '/' && u.startsWith(BASE)) ? '/' + u.slice(BASE.length) : u;

const srv=createServer(async(req,res)=>{
  const p0=strip(decodeURIComponent(req.url.split('?')[0]));
  if (/^\/(content|feedback|api)/.test(p0)) { res.writeHead(200,{'Content-Type':'application/json'}); return res.end('[]'); }
  let p=join(DIST,p0);
  try{if((await stat(p)).isDirectory())p=join(p,'index.html');}catch{p=join(DIST,'index.html');}
  try{const b=await readFile(p);res.writeHead(200,{'Content-Type':T[extname(p)]||'application/octet-stream'});res.end(b);}
  catch{res.writeHead(404);res.end('x');}});
await new Promise(r=>srv.listen(PORT,r));
const br=await chromium.launch();
let failed=0;
const check=(n,c,e='')=>{console.log(`  ${c?'✅':'❌'} ${n}${e?'  '+e:''}`);if(!c)failed++;};

const open = async (ua, viewport) => {
  const ctx = await br.newContext({ userAgent: ua, viewport });
  const pg = await ctx.newPage();
  await pg.goto(`http://127.0.0.1:${PORT}${BASE}`, { waitUntil: 'domcontentloaded' });
  await pg.getByText('דלג',{exact:false}).first().click({timeout:10000}).catch(()=>{});
  await pg.waitForTimeout(2500);
  return { ctx, pg };
};

// ① טלוויזיה
{
  const { ctx, pg } = await open(
    'Mozilla/5.0 (SMART-TV; LINUX; Tizen 6.0) AppleWebKit/537.36 Chrome/76 Safari/537.36',
    { width: 1920, height: 1080 });
  check('מצב טלוויזיה נדלק', await pg.evaluate(() => document.documentElement.getAttribute('data-tv')) === '1');
  const fs = await pg.evaluate(() => getComputedStyle(document.documentElement).fontSize);
  check('הטקסט הוגדל', parseFloat(fs) >= 20, fs);
  // השוואה לפי אינדקס ברשימת המיקוד, לא לפי HTML: שני כפתורים דומים
  // נראים זהים כשחותכים את ה-outerHTML, והבדיקה הקודמת "נכשלה" בגלל זה.
  const moved = await pg.evaluate(async () => {
    const SEL = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"]), [data-tv-focus]';
    const idx = () => [...document.querySelectorAll(SEL)].indexOf(document.activeElement);
    const press = async (key) => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
      await new Promise(r => setTimeout(r, 350));
      return idx();
    };
    const before = idx();
    const a1 = await press('ArrowDown');
    const seq = [a1];
    for (const k of ['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp']) seq.push(await press(k));
    return { before, a1, seq, n: document.querySelectorAll(SEL).length };
  });
  check('החץ הראשון נותן פוקוס', moved.a1 !== -1 && moved.a1 !== moved.before, JSON.stringify(moved));
  check('חצים נוספים מזיזים את הפוקוס', new Set(moved.seq).size > 1, JSON.stringify(moved.seq));
  await ctx.close();
}
// ② מחשב רגיל — אסור שישתנה כלום
{
  const { ctx, pg } = await open(
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36',
    { width: 1366, height: 820 });
  check('במחשב מצב הטלוויזיה כבוי', await pg.evaluate(() => document.documentElement.getAttribute('data-tv')) === null);
  const fs = await pg.evaluate(() => getComputedStyle(document.documentElement).fontSize);
  check('במחשב הטקסט לא הוגדל', parseFloat(fs) < 20, fs);
  await ctx.close();
}
await br.close(); srv.close();
console.log(failed ? `\n❌ ${failed} נכשלו` : '\n✅ הכל עבר');
process.exit(failed?1:0);
