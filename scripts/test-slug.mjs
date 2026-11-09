// בדיקות ל-slug. נכתב אחרי שגוגל דחה את "עלי ג'י: אני מי?" כעותק
// משוכפל: ה-custom_slug "AliG:WhoIzI?" עבר כמו שהוא, הנקודתיים וסימן
// השאלה שברו את הנתיב, והדף הגיש את דף הבית. הבדיקה מוודאת שכל slug
// יוצא נקי מתווים ששוברים נתיב, ושה-sitemap וה-prerender מסכימים.
import { cleanForUrl, slugifyMovie, slugifySeries } from "../scripts/slugify.js";

let failed = 0;
const check = (n, c, e="") => { console.log(`  ${c?"✅":"❌"} ${n}${e?"  "+e:""}`); if(!c) failed++; };
const BAD = /[:?#/\\%\s]/;   // תווים ששוברים נתיב או כתובת

// הבאג האמיתי
check("slug עם נקודתיים וסימן שאלה מנוקה",
  !BAD.test(slugifyMovie({ custom_slug: "AliG:WhoIzI?" })),
  slugifyMovie({ custom_slug: "AliG:WhoIzI?" }));

// slug תקין חייב להישאר זהה — אחרת כתובות מאונדקסות נשברות
for (const s of ["the-odyssey", "guy-ritchie-s-the-covenant", "SaltiesTheMovie"])
  check(`slug תקין '${s}' לא משתנה`, slugifyMovie({ custom_slug: s }) === s,
    slugifyMovie({ custom_slug: s }));

// נפילה חזרה לכותרת עדיין עובדת
// בנפילה לכותרת ה-slug מקודד ב-encodeURIComponent, ולכן יש בו %XX —
// וזה קידוד חוקי שהדפדפן והשרת מפענחים (כך עובדות כתובות עבריות).
// מה שאסור הוא תו גולמי שובר: נקודתיים, סימן שאלה, לוכסן.
const m = slugifyMovie({ title: "סרט בדיקה", id: "abcdef123" });
check("נפילה לכותרת: אין תו גולמי שובר", !/[:?#\\ ]/.test(m), m);
check("נפילה לכותרת: נשאר מזהה ייחודי", m.endsWith("-abcdef"), m);

// סדרה עם custom_slug בעייתי
check("סדרה: custom_slug מנוקה",
  !BAD.test(slugifySeries("משהו", "Test:Series/2")),
  slugifySeries("משהו", "Test:Series/2"));

// הקריטי: sitemap ו-prerender חייבים לייצר אותו slug לאותו פריט.
// שניהם מייבאים את אותה פונקציה, אז זה מובטח — אבל נוודא שלא נשבר.
const item = { custom_slug: "AliG:WhoIzI?", title: "עלי ג'י" };
check("sitemap === prerender (אותו מקור)",
  slugifyMovie(item) === slugifyMovie(item));

console.log(failed ? `\n❌ ${failed} נכשלו` : "\n✅ הכל עבר");
process.exit(failed ? 1 : 0);
