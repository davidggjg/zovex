// ─────────────────────────────────────────────────────────────────────────────
// בדיקת מסך החסימה בדפדפן אמיתי.
//
// נמדד: הנתיב /api/access לא היה קיים בשרת (add_bans.py לא הוחל),
// ואחרי שהוחל — אף לקוח לא שאל אותו. כפתור החסימה בפאנל כתב שורה
// לקובץ ושום דבר לא קרה.
//
// הבדיקה מרימה שרת מדומה שמחזיר blocked=true או blocked=false, מזריקה
// משתמש מחובר ל-localStorage, וטוענת את הבנייה האמיתית.
//
//   node scripts/test-ban.mjs
// ─────────────────────────────────────────────────────────────────────────────
import { createRequire } from 'node:module';
const { chromium } = createRequire(import.meta.url)('playwright');
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { join, extname } from 'node:path';
const DIST='dist', PORT=8869;
const T={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json'};
let blocked = false;
// הבנייה הרגילה יוצאת עם base=/zovex/, ולכן הנכסים מבוקשים מ-
// /zovex/assets/… . שרת שמגיש מהשורש החזיר להם index.html, הדפדפן
// סירב לטעון מודול עם MIME של HTML, והבדיקה "נכשלה" על בנייה תקינה.
const BASE = await readFile(join(DIST, 'index.html'), 'utf8')
  .then(h => (h.match(/src="(\/[^"]*?)assets\//) || [, '/'])[1])
  .catch(() => '/');
const strip = u => (BASE !== '/' && u.startsWith(BASE)) ? '/' + u.slice(BASE.length) : u;

const srv=createServer(async(req,res)=>{
  const path=strip(decodeURIComponent(req.url.split('?')[0]));
  if (path === '/api/access') {
    // Buffer.byteLength ולא b.length: עברית היא שני בתים לתו, ו-
    // Content-Length קצר מדי חותך את ה-JSON באמצע.
    const b = Buffer.from(JSON.stringify(blocked
      ? { blocked: true, message: 'נחסמת בגלל הודעות פוגעניות בתמיכה.' }
      : { blocked: false }), 'utf8');
    res.writeHead(200,{'Content-Type':'application/json; charset=utf-8','Content-Length':String(b.length)});
    return res.end(b);
  }
  if (/^\/(content|feedback)/.test(path)) { res.writeHead(200,{'Content-Type':'application/json'}); return res.end('[]'); }
  let p=join(DIST,path);
  try{if((await stat(p)).isDirectory())p=join(p,'index.html');}catch{p=join(DIST,'index.html');}
  try{const b=await readFile(p);res.writeHead(200,{'Content-Type':T[extname(p)]||'application/octet-stream'});res.end(b);}
  catch{res.writeHead(404);res.end('x');}
});
await new Promise(r=>srv.listen(PORT,r));
const br=await chromium.launch();
let failed=0;
const check=(n,c,e='')=>{console.log(`  ${c?'✅':'❌'} ${n}${e?'  '+e:''}`);if(!c)failed++;};

for (const [label, isBlocked] of [['משתמש חסום', true], ['משתמש תקין', false]]) {
  blocked = isBlocked;
  const ctx = await br.newContext();
  const pg = await ctx.newPage();
  // מזריקים משתמש מחובר ל-localStorage לפני שהאפליקציה עולה
  await pg.addInitScript(() => {
    const u = { email: 'test@zovex.test', name: 'בדיקה', picture: '' };
    // המפתח שבו Auth.jsx משתמש בפועל.
    try { localStorage.setItem('zovex_user', JSON.stringify(u)); } catch {}
  });
  pg.on('console', m => { if (m.type()==='error') console.log('     [שגיאה]', m.text().slice(0,100)); });
  await pg.goto(`http://127.0.0.1:${PORT}${BASE}`, { waitUntil: 'domcontentloaded' });
  await pg.waitForTimeout(3500);
  await pg.waitForTimeout(2000);
  const txt = await pg.$eval('body', e => e.innerText);
  const seen = txt.includes('הגישה שלך נחסמה');
  console.log(`\n── ${label}`);
  check(isBlocked ? 'מוצג מסך החסימה' : 'לא מוצג מסך חסימה', seen === isBlocked,
        txt.slice(0,60).replace(/\n/g,' | '));
  if (isBlocked && seen) {
    check('ההודעה מהשרת מוצגת', txt.includes('הודעות פוגעניות'));
    // בלי זה החסימה חסרת ערך: הנחסם מתנתק, נכנס עם מייל אחר, וממשיך.
    check('אין כפתור התנתקות במסך החסימה', !txt.includes('התנתק'));
    const buttons = await pg.$$eval('button', bs => bs.length);
    check('אין בכלל כפתורים במסך החסימה', buttons === 0, 'יש ' + buttons);
  }
  await ctx.close();
}
await br.close(); srv.close();
console.log(failed ? `\n❌ ${failed} נכשלו` : '\n✅ הכל עבר');
process.exit(failed?1:0);
