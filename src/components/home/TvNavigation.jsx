import { useEffect } from "react";
import { detectTvFromWindow, nextInDirection, KEY_TO_DIR } from "@/theme/tvMode";

// ─────────────────────────────────────────────────────────────────────────────
// ניווט בשלט כשהאתר נפתח בטלוויזיה.
//
// טלוויזיה מריצה דפדפן רגיל ומדווחת על עצמה כמחשב, ולכן האתר נראה שם
// כמו מסך מחשב קטן ממרחק שלושה מטרים, בלי שום סימון למה שהשלט מצביע
// עליו. באפליקציה זה נפתר ב-TvFocusable; כאן אין מקבילה, אז זה נבנה
// מהדפדפן עצמו.
//
// הבחירה היא על אלמנטים שממילא ניתנים למיקוד (כפתורים, קישורים), ולכן
// אין כאן רשימת מיקוד משלנו שצריך לתחזק — רק הזזה שלו לפי גאומטריה.
//
// במחשב ובטלפון הרכיב אינו עושה דבר: הוא יוצא מיד אם הזיהוי אומר
// שזו לא טלוויזיה.
// ─────────────────────────────────────────────────────────────────────────────
const SEL = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"]), [data-tv-focus]';

export default function TvNavigation() {
  useEffect(() => {
    if (!detectTvFromWindow()) return;
    document.documentElement.setAttribute("data-tv", "1");

    const onKey = (e) => {
      const dir = KEY_TO_DIR[e.key];
      if (!dir) return;
      const all = [...document.querySelectorAll(SEL)].filter((el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      });
      if (all.length < 2) return;
      // קואורדינטות **חלון** ולא מסמך.
      //
      // הגרסה הקודמת הוסיפה ‎scrollY‎ לכל אלמנט, וזה שגוי לאלמנט
      // ‎position: fixed‎: הוא אינו זז עם הגלילה, ולכן ההוספה דחפה
      // אותו אלפי פיקסלים מטה במפה — כלומר סרגל הניווט התחתון היה
      // תמיד "רחוק מאוד למטה", והחץ מעולם לא הגיע אליו. זה בדיוק מה
      // שדוד תיאר: בטלוויזיה אי אפשר להגיע לסרגל עם השלט.
      //
      // מערכת החלון נכונה לשניהם: ‎getBoundingClientRect‎ כבר מחזיר
      // את המיקום על המסך, וזה גם מה שהמשתמש רואה — ניווט בשלט הוא
      // תמיד ביחס למה שמוצג, לא למסמך כולו.
      const rects = all.map((el) => {
        const r = el.getBoundingClientRect();
        return { x: r.left, y: r.top, width: r.width, height: r.height };
      });
      let idx = all.indexOf(document.activeElement);
      if (idx === -1) {
        // אין פוקוס — מתחילים מהאלמנט הגלוי הראשון על המסך, ולא
        // מהעליון במסמך (שעשוי להיות מגולל הרחק מעל).
        const vh = window.innerHeight;
        const onScreen = rects
          .map((r, i) => ({ r, i }))
          .filter(({ r }) => r.y + r.height > 0 && r.y < vh);
        const pool = onScreen.length ? onScreen : rects.map((r, i) => ({ r, i }));
        idx = pool.reduce((b, c) => (c.r.y < b.r.y ? c : b)).i;
        all[idx].focus({ preventScroll: true });
        all[idx].scrollIntoView({ block: "center", inline: "center" });
        e.preventDefault();
        return;
      }
      let next = nextInDirection(rects, idx, dir);

      // ── מסלול ודאי לסרגל הצף ─────────────────────────────────────
      //
      // בחירה גאומטרית לבדה אינה מבטיחה שאפשר להגיע לסרגל התחתון:
      // הוא ‎position: fixed‎, הוא מרחף מעל התוכן, ולפי המיקום הוא
      // תמיד "למטה" — אבל כך גם כל שאר התוכן שמתחת לקיפול. לכן
      // בטלוויזיה היה אפשר לגלול שורות בלי להגיע אליו אף פעם.
      //
      // כאן זה לא נשאר ליד המקרה: חץ למטה שאין לו יעד מעביר לסרגל,
      // וחץ למעלה מתוך הסרגל חוזר לתוכן. ודאי, ולא תלוי בגאומטריה.
      const nav = document.querySelector("nav");
      const inNav = nav && nav.contains(all[idx]);
      if (dir === "down" && !inNav) {
        const navItem = nav && all.find((el) => nav.contains(el));
        const atBottom =
          window.innerHeight + window.scrollY >= document.body.scrollHeight - 8;
        if (navItem && (next === -1 || atBottom)) next = all.indexOf(navItem);
      }
      if (dir === "up" && inNav) {
        // יציאה מהסרגל: לאלמנט הנמוך ביותר שעל המסך ואינו בתוכו.
        const vh = window.innerHeight;
        let best = -1, bestY = -Infinity;
        all.forEach((el, i) => {
          if (nav.contains(el)) return;
          const r = rects[i];
          if (r.height > 0 && r.y < vh - 110 && r.y > bestY) { bestY = r.y; best = i; }
        });
        if (best !== -1) next = best;
      }

      if (next === -1) return;        // אין לאן — נותנים לדפדפן לגלול
      e.preventDefault();
      all[next].focus({ preventScroll: true });
      all[next].scrollIntoView({ block: "center", inline: "center",
                                 behavior: "smooth" });
    };

    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.documentElement.removeAttribute("data-tv");
    };
  }, []);

  return null;
}
