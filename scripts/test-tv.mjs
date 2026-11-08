// בדיקות לזיהוי טלוויזיה ולניווט בחצים.
import { detectTv, nextInDirection } from '../src/theme/tvMode.js';
let failed = 0;
const check = (n, c, e='') => { console.log(`  ${c?'✅':'❌'} ${n}${e?'  '+e:''}`); if(!c) failed++; };

// ── זיהוי ──
const UAS = {
  'Android TV': 'Mozilla/5.0 (Linux; Android 10; BRAVIA 4K GB ) AppleWebKit/537.36 Chrome/83 Safari/537.36',
  'Tizen (סמסונג)': 'Mozilla/5.0 (SMART-TV; LINUX; Tizen 6.0) AppleWebKit/537.36 Chrome/76 Safari/537.36',
  'webOS (LG)': 'Mozilla/5.0 (Web0S; Linux/SmartTV) AppleWebKit/537.36 Chrome/68 Safari/537.36',
};
for (const [name, ua] of Object.entries(UAS))
  check(`מזוהה: ${name}`, detectTv({ ua, width: 1920, height: 1080 }) === true);

check('מחשב רגיל אינו טלוויזיה',
  detectTv({ ua: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120', width: 1920, height: 1080,
             coarsePointer: false, hasTouch: false }) === false);
check('מק עם מסך גדול אינו טלוויזיה',
  detectTv({ ua: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605', width: 2560, height: 1440 }) === false);
check('טלפון אינו טלוויזיה',
  detectTv({ ua: 'Mozilla/5.0 (Linux; Android 13; Pixel 7) Chrome/120 Mobile',
             width: 412, height: 915, coarsePointer: true, hasTouch: true }) === false);
check('טאבלט גדול עם מגע אינו טלוויזיה',
  detectTv({ ua: 'Mozilla/5.0 (iPad; CPU OS 17_0) Safari/605', width: 1366, height: 1024,
             coarsePointer: true, hasTouch: true }) === false);
check('מסך גדול עם שלט ובלי מגע — כן טלוויזיה',
  detectTv({ ua: 'Mozilla/5.0 (X11; Linux) Chrome/90', width: 1920, height: 1080,
             coarsePointer: true, hasTouch: false }) === true);

// ── ניווט ──
// שתי שורות של שלושה כרטיסים. RTL אינו משנה את הגאומטריה.
const R = (x, y) => ({ x, y, width: 200, height: 120 });
const grid = [R(0,0), R(220,0), R(440,0),
              R(0,160), R(220,160), R(440,160)];
check('ימינה בתוך שורה', nextInDirection(grid, 0, 'right') === 1);
check('שמאלה בתוך שורה', nextInDirection(grid, 2, 'left') === 1);
check('למטה לשורה הבאה', nextInDirection(grid, 1, 'down') === 4);
check('למעלה לשורה הקודמת', nextInDirection(grid, 4, 'up') === 1);
check('בקצה ימין אין לאן', nextInDirection(grid, 2, 'right') === -1);
check('בשורה העליונה אין למעלה', nextInDirection(grid, 0, 'up') === -1);

// הכרטיס הקרוב בקו אווירי נמצא בשורה אחרת — חץ ימינה חייב להישאר בשורה.
const tricky = [R(0,0), R(1000,0), R(60,130)];
check('חץ ימינה אינו קופץ לשורה אחרת', nextInDirection(tricky, 0, 'right') === 1);
check('אינדקס לא קיים מחזיר -1', nextInDirection(grid, 99, 'down') === -1);

console.log(failed ? `\n❌ ${failed} נכשלו` : '\n✅ הכל עבר');
process.exit(failed ? 1 : 0);
