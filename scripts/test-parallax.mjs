// ─────────────────────────────────────────────────────────────────────────────
// רקע: פרלקסה בגלילה, ועצירה מלאה תחת תנועה מופחתת.
//
// הפרלקסה היא מה שיוצר את תחושת העומק — המוח מפרש הפרש מהירויות
// בין הרקע לתוכן כמרחק. בלעדיה הרקע "מודבק" לתוכן גם כשהצורות
// עצמן זזות.
//
// §14 של apple-design דורש שתנועת רקע גדולה תיעצר כשהמשתמש ביקש
// תנועה מופחתת, ולכן זה נבדק כאן ולא נסמך על כוונה.
//
// דורש שרת מקומי על 8853 (scripts/serve-dist.mjs או serve.mjs).
//   node scripts/test-parallax.mjs
// ─────────────────────────────────────────────────────────────────────────────
import { createRequire } from 'node:module';
const { chromium, devices } = createRequire(import.meta.url)('playwright');
import { spawn } from 'node:child_process';
// מרים את שרת ה-dist בעצמו, כדי שהבדיקה תרוץ עצמאית.
const srv = spawn('node', ['scripts/serve-dist.mjs', '8853'], { stdio: 'ignore' });
await new Promise(r => setTimeout(r, 2500));
// נכנסים דרך ה-base של הבנייה, אחרת ה-Router לא מתאים אף מסלול.
const { readFile } = await import('node:fs/promises');
const BASE = await readFile('dist/index.html', 'utf8')
  .then(h => (h.match(/src="(\/[^"]*?)assets\//) || [, '/'])[1]).catch(() => '/');
const br = await chromium.launch();
let failed = 0;
const check = (n,c,e='') => { console.log(`  ${c?'✅':'❌'} ${n}${e?'  '+e:''}`); if(!c) failed++; };

for (const [label, reduced] of [['רגיל', false], ['תנועה מופחתת', true]]) {
  const ctx = await br.newContext({ ...devices['Pixel 7'],
    reducedMotion: reduced ? 'reduce' : 'no-preference' });
  const pg = await ctx.newPage();
  await pg.goto(`http://127.0.0.1:8853${BASE}`, { waitUntil: 'domcontentloaded' });
  await pg.getByText('דלג', { exact: false }).first().click({ timeout: 15000 }).catch(()=>{});
  await pg.waitForTimeout(3000);
  // "אין אלמנט" ו"אין תזוזה" חייבים להיות שונים: אחרת דף שבור
  // "עובר" את בדיקת התנועה המופחתת.
  const read = () => pg.evaluate(() => {
    const el = document.querySelector('.zv-parallax');
    return el ? getComputedStyle(el).transform : 'MISSING';
  });
  const before = await read();
  check(`${label}: שכבת הרקע קיימת`, before !== 'MISSING', before);
  await pg.evaluate(() => window.scrollTo(0, 1200));
  await pg.waitForTimeout(600);
  const after = await read();
  if (reduced) check(`${label}: הפרלקסה כבויה`, after === 'none' || after === before, `${before} → ${after}`);
  else check(`${label}: הפרלקסה זזה עם הגלילה`, after !== before, `${before} → ${after}`);
  await ctx.close();
}
await br.close(); srv.kill();
console.log(failed ? `\n❌ ${failed} נכשלו` : '\n✅ הכל עבר');
process.exit(failed?1:0);
