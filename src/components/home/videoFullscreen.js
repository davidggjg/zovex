// ─────────────────────────────────────────────────────────────────────────────
// כניסה למסך מלא בווידאו, לפי מה שהפלטפורמה באמת מאפשרת.
//
// ## מה שנמדד ותועד
//
// באייפון אין Fullscreen API על אלמנטים כלל — לא requestFullscreen ולא
// webkitRequestFullscreen (באייפד ובמק כן). הדבר היחיד שיכול להיכנס
// למסך מלא הוא אלמנט <video> עצמו, דרך webkitEnterFullscreen, והמצב
// מדווח על האלמנט (webkitDisplayingFullscreen, webkitbeginfullscreen,
// webkitendfullscreen) ולא על המסמך.
//
// ## למה הכפתור לא עשה כלום
//
// הקריאה הייתה עטופה ב-try/catch ריק. ל-webkitEnterFullscreen יש תנאים
// מוקדמים — מטא-דאטה טעונה, ו-webkitSupportsFullscreen שאינו false —
// וכשהם אינם מתקיימים היא נכשלת בשקט. אותו דבר ב-requestFullscreen,
// שמחזיר Promise: דחייה בלי catch אינה מגיעה לשום מקום. שתי הדרכים
// נכשלו באותה צורה: כלום לא קורה, ואין מה לראות בקונסול.
//
// הפונקציה כאן מחזירה null בהצלחה, או מחרוזת בעברית שמסבירה מה נכשל.
// היא הוצאה מהרכיב כדי שאפשר יהיה לבדוק אותה: ראו scripts/test-fullscreen.mjs.
//
// אין כאן setTimeout לפני הקריאה, בכוונה: דחייה הייתה מאבדת את הרשאת
// הלחיצה של המשתמש, וזו דרישה של ספארי.
// ─────────────────────────────────────────────────────────────────────────────
export function iosEnterFullscreen(v) {
  if (!v) return "הנגן עדיין לא נטען";

  const hasEnter = typeof v.webkitEnterFullscreen === "function";
  const hasPresentation = typeof v.webkitSetPresentationMode === "function";
  if (!hasEnter && !hasPresentation) return "הדפדפן הזה אינו תומך במסך מלא לווידאו";

  // readyState 0 = עוד אין מטא-דאטה, והקריאה תיכשל. לומר זאת עדיף
  // מלא לעשות כלום.
  if (v.readyState === 0) return "הווידאו עדיין נטען — נסה שוב בעוד רגע";

  if (hasEnter && v.webkitSupportsFullscreen !== false) {
    try {
      v.webkitEnterFullscreen();
      return null;
    } catch (e) {
      if (!hasPresentation) return "מסך מלא נדחה (" + ((e && e.name) || "שגיאה") + ")";
    }
  }

  // מסלול שני: webkitSetPresentationMode. קיים בספארי במק ובאייפד,
  // ובגרסאות iOS חדשות גם בטלפון, ולעיתים זמין כשהראשון אינו.
  if (hasPresentation) {
    try {
      v.webkitSetPresentationMode("fullscreen");
      return null;
    } catch (e) {
      return "מסך מלא נדחה (" + ((e && e.name) || "שגיאה") + ")";
    }
  }

  return "הזרם הזה אינו תומך במסך מלא במכשיר הזה";
}
