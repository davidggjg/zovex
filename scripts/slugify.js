// ─────────────────────────────────────────────────────────────────────────────
// מקור אמת יחיד לבניית ה-slug לכתובת.
//
// עד כה הלוגיקה שוכפלה ב-generate-sitemap.js וב-prerender-routes.js. זה
// מסוכן: אם השניים חלוקים בתו אחד, ה-sitemap מצביע על כתובת שונה מזו
// שהתיקייה נוצרה תחתיה — nginx נופל ל-try_files ומגיש את דף הבית,
// וגוגל מדווח "עותק משוכפל בלי קנוני". לכן קובץ אחד, ששניהם מייבאים.
//
// ## הבאג שתוקן כאן
//
// ‎slugifyMovie‎ החזיר את ‎custom_slug‎ **כמו שהוא**, בלי ניקוי. הפריט
// "עלי ג'י: אני מי?" קיבל custom_slug ‎"AliG:WhoIzI?"‎ — עם נקודתיים
// ועם סימן שאלה. נקודתיים אינה חוקית בנתיב קובץ, וסימן שאלה פותח
// query string, ולכן התיקייה שנוצרה מעולם לא התאימה לכתובת: הדף הגיש
// את דף הבית, וגוגל סירב לאנדקס אותו. ‎cleanForUrl‎ ידעה להסיר בדיוק
// את התווים האלה — אבל הופעלה רק על הנתיב מהכותרת, לא על custom_slug.
//
// מעכשיו custom_slug עובר דרך אותו ניקוי. slug תקין (אותיות, ספרות,
// מקפים) אינו משתנה כלל — cleanForUrl אינה נוגעת בהם — ולכן כתובות
// קיימות שעובדות נשארות זהות.
// ─────────────────────────────────────────────────────────────────────────────

export function cleanForUrl(name) {
  return String(name || "")
    .replace(/[:–—"'`?#\[\]@!$&()*+,;=.]/g, " ")
    // גם לוכסן, בקסלאש, אחוז ורווח קשיח — כולם שוברים נתיב או כתובת,
    // ולא היו ברשימה המקורית. לוכסן ב-slug היה יוצר תת-תיקייה מדומה.
    .replace(/[/\\%]/g, " ")
    .trim()
    .replace(/\s+/g, "-");
}

// slug סופי לפריט. custom_slug עובר ניקוי אבל **לא** encodeURIComponent,
// כי הוא ASCII מראש (נוצר ב-seo_fix.py) וכך היה גם קודם; רק הכותרת,
// שעשויה להיות עברית, מקודדת.
export function slugifyMovie(movie) {
  if (movie.custom_slug) return cleanForUrl(movie.custom_slug);
  const base = encodeURIComponent(cleanForUrl(movie.title));
  return `${base}-${(movie.id || "").slice(0, 6)}`;
}

export function slugifySeries(seriesName, customSlug) {
  if (customSlug) return cleanForUrl(customSlug);
  return encodeURIComponent(cleanForUrl(seriesName));
}
