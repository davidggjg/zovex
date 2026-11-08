// בדיקות לבחירת האיכות. נכתב אחרי באג אמיתי: הגרסה הראשונה בחרה את
// הווריאנט הנמוך, כי (bH - aH) הוא מספר וכל מספר שאינו אפס הוא
// truthy — גם שלילי.
import { bestVariant } from '../src/components/home/videoQuality.js';

let failed = 0;
const check = (name, cond, extra = '') => {
  console.log(`  ${cond ? '✅' : '❌'} ${name}${extra ? '  ' + extra : ''}`);
  if (!cond) failed++;
};

const T = (height, bandwidth, id) => ({ height, bandwidth, id });

check('בוחר את הגובה הגדול ביותר',
  bestVariant([T(360, 800e3, 'a'), T(1080, 5e6, 'b'), T(720, 2e6, 'c')]).id === 'b');

check('גם כשהגבוה ראשון ברשימה',
  bestVariant([T(1080, 5e6, 'b'), T(360, 800e3, 'a')]).id === 'b');

check('גם כשהגבוה אחרון',
  bestVariant([T(240, 4e5, 'x'), T(360, 8e5, 'y'), T(2160, 2e7, 'z')]).id === 'z');

check('באותו גובה — קצב הסיביות מכריע',
  bestVariant([T(1080, 4e6, 'lo'), T(1080, 9e6, 'hi')]).id === 'hi');

check('וריאנט בלי גובה אינו גובר על 720p',
  bestVariant([T(undefined, 9e6, 'audio'), T(720, 2e6, 'v')]).id === 'v');

check('רשימה באורך 1', bestVariant([T(480, 1e6, 'only')]).id === 'only');
check('רשימה ריקה מחזירה null', bestVariant([]) === null);
check('קלט שאינו מערך מחזיר null', bestVariant(undefined) === null);

// סדר הפוך: אותה רשימה הפוכה חייבת להחזיר את אותו וריאנט
const list = [T(360, 8e5, 'a'), T(1080, 5e6, 'b'), T(720, 2e6, 'c')];
check('התוצאה אינה תלויה בסדר',
  bestVariant(list).id === bestVariant([...list].reverse()).id);

console.log(failed ? `\n❌ ${failed} נכשלו` : '\n✅ הכל עבר');
process.exit(failed ? 1 : 0);
