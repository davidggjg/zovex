// ─────────────────────────────────────────────────────────────────────────────
// בדיקות לבחירת מסלול המסך המלא.
//
// נכתב אחרי תקלה אמיתית: באייפון כפתור המסך המלא לא עשה כלום. הקריאה
// ל-webkitEnterFullscreen הייתה עטופה ב-try/catch ריק, ולכן כל כישלון
// — מטא-דאטה שלא נטענה, זרם שאינו תומך, דחייה של המכשיר — נראה בדיוק
// אותו דבר: שום דבר.
//
// כל מקרה כאן הוא אחד מאלה, ומוודא שהוא מזוהה ומדווח.
//
//   node scripts/test-fullscreen.mjs
// ─────────────────────────────────────────────────────────────────────────────
import { iosEnterFullscreen } from '../src/components/home/videoFullscreen.js';

let failed = 0;
const check = (name, cond, extra = '') => {
  console.log(`  ${cond ? '✅' : '❌'} ${name}${extra ? '  ' + extra : ''}`);
  if (!cond) failed++;
};

// ① אין אלמנט וידאו עדיין
check('בלי אלמנט וידאו — מדווח ולא קורס',
  iosEnterFullscreen(null) === 'הנגן עדיין לא נטען');

// ② דפדפן בלי שום API של מסך מלא לווידאו (אנדרואיד ישן, פיירפוקס)
check('בלי API — מדווח',
  iosEnterFullscreen({ readyState: 4 }) === 'הדפדפן הזה אינו תומך במסך מלא לווידאו');

// ③ אייפון תקין: המטא-דאטה נטענה, הקריאה עוברת
let called = 0;
const iphone = { readyState: 1, webkitSupportsFullscreen: true,
                 webkitEnterFullscreen() { called++; } };
check('אייפון תקין — נכנס למסך מלא', iosEnterFullscreen(iphone) === null && called === 1);

// ④ המטא-דאטה עוד לא נטענה. זה הכישלון השקט שהיה: הקריאה נדחית
//    והמשתמש לא יודע למה.
called = 0;
check('מטא-דאטה חסרה — מדווח ולא קורא',
  iosEnterFullscreen({ readyState: 0, webkitEnterFullscreen() { called++; } })
    === 'הווידאו עדיין נטען — נסה שוב בעוד רגע' && called === 0);

// ⑤ webkitSupportsFullscreen=false (זרם שאינו נתמך) ויש מסלול שני
let pres = null;
check('לא נתמך — נופל ל-webkitSetPresentationMode',
  iosEnterFullscreen({ readyState: 4, webkitSupportsFullscreen: false,
                       webkitEnterFullscreen() { throw new Error('לא אמור להיקרא'); },
                       webkitSetPresentationMode(m) { pres = m; } }) === null
  && pres === 'fullscreen');

// ⑥ webkitSupportsFullscreen=false ואין מסלול שני
check('לא נתמך ואין חלופה — מדווח',
  iosEnterFullscreen({ readyState: 4, webkitSupportsFullscreen: false,
                       webkitEnterFullscreen() {} })
    === 'הזרם הזה אינו תומך במסך מלא במכשיר הזה');

// ⑦ הקריאה זורקת, ויש מסלול שני
pres = null;
check('זריקה — נופל למסלול השני',
  iosEnterFullscreen({ readyState: 4,
                       webkitEnterFullscreen() { const e = new Error('x'); e.name = 'InvalidStateError'; throw e; },
                       webkitSetPresentationMode(m) { pres = m; } }) === null
  && pres === 'fullscreen');

// ⑧ הקריאה זורקת ואין מסלול שני — שם השגיאה מגיע למשתמש
check('זריקה בלי חלופה — שם השגיאה מדווח',
  iosEnterFullscreen({ readyState: 4,
                       webkitEnterFullscreen() { const e = new Error('x'); e.name = 'InvalidStateError'; throw e; } })
    === 'מסך מלא נדחה (InvalidStateError)');

// ⑨ webkitSupportsFullscreen לא מוגדר כלל (מק, אייפד) — לא חוסם
called = 0;
check('השדה אינו מוגדר — לא חוסם',
  iosEnterFullscreen({ readyState: 2, webkitEnterFullscreen() { called++; } }) === null
  && called === 1);

// ⑩ גם מסלול שני שזורק מדווח ולא קורס
check('שני המסלולים נכשלו — מדווח',
  iosEnterFullscreen({ readyState: 4, webkitSupportsFullscreen: false,
                       webkitEnterFullscreen() {},
                       webkitSetPresentationMode() { const e = new Error('x'); e.name = 'NotAllowedError'; throw e; } })
    === 'מסך מלא נדחה (NotAllowedError)');

console.log(failed ? `\n❌ ${failed} נכשלו` : '\n✅ הכל עבר');
process.exit(failed ? 1 : 0);
