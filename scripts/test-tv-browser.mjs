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
// ①ב הסרגל התחתון חייב להיות בר-הגעה עם השלט.
//    נכשל קודם: TvNavigation הוסיף scrollY גם לאלמנט position:fixed,
//    והסרגל "נדחף" אלפי פיקסלים מטה במפה — החץ מעולם לא הגיע אליו.
{
  const { ctx, pg } = await open(
    'Mozilla/5.0 (SMART-TV; LINUX; Tizen 6.0) AppleWebKit/537.36 Chrome/76 Safari/537.36',
    { width: 1920, height: 1080 });
  // התרחיש שבאמת מבדיל: גוללים לתחתית העמוד ומתמקדים בכרטיס
  // האחרון שעל המסך. הסרגל הצף נמצא ויזואלית ממש מתחתיו, ולכן חץ
  // אחד למטה חייב להגיע אליו.
  //
  // עם קואורדינטות מסמך הסרגל ממופה ל-y של scrollY+גובה המסך —
  // כלומר הרחק מתחת לכל התוכן — ואין שום מועמד "מתחת" לכרטיס
  // האחרון שקרוב יותר ממנו, אז החץ קופץ למקום אחר או לשום מקום.
  const reached = await pg.evaluate(async () => {
    const nav = document.querySelector('nav');
    if (!nav) return 'אין סרגל';
    window.scrollTo(0, document.body.scrollHeight);
    await new Promise(r => setTimeout(r, 500));
    const SEL = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';
    const vh = window.innerHeight;
    // הכרטיס הנמוך ביותר שעדיין על המסך ואינו בתוך הסרגל
    const cand = [...document.querySelectorAll(SEL)]
      .filter(el => !nav.contains(el))
      .map(el => ({ el, r: el.getBoundingClientRect() }))
      .filter(({ r }) => r.height > 0 && r.top > 0 && r.top < vh - 120)
      .sort((a, b) => b.r.top - a.r.top)[0];
    if (!cand) return 'לא נמצא כרטיס מתאים';
    cand.el.focus({ preventScroll: true });
    const inNav = () => !!(document.activeElement && nav.contains(document.activeElement));
    for (let i = 0; i < 3; i++) {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
      await new Promise(r => setTimeout(r, 150));
      if (inNav()) return true;
    }
    return false;
  });
  check('השלט מגיע לסרגל התחתון', reached === true, String(reached));

  // ויציאה חזרה: חץ למעלה מתוך הסרגל חייב להחזיר לתוכן, אחרת
  // המשתמש נכנס לסרגל ונתקע בו.
  const back = await pg.evaluate(async () => {
    const nav = document.querySelector('nav');
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
    await new Promise(r => setTimeout(r, 250));
    return !!(document.activeElement && !nav.contains(document.activeElement));
  });
  check('חץ למעלה יוצא מהסרגל חזרה לתוכן', back === true);
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
  // הסרגל נמתח קודם על כל רוחב המסך במחשב, וארבעה פריטים נפרשו
  // מקצה לקצה. באפליקציה זה נראה נכון רק כי מסך טלפון צר.
  const navW = await pg.evaluate(() => {
    const n = document.querySelector('nav');
    return n ? Math.round(n.getBoundingClientRect().width) : -1;
  });
  check('במחשב הסרגל אינו נמתח על כל הרוחב', navW > 0 && navW <= 460, navW + 'px');
  await ctx.close();
}
await br.close(); srv.close();
console.log(failed ? `\n❌ ${failed} נכשלו` : '\n✅ הכל עבר');
process.exit(failed?1:0);
