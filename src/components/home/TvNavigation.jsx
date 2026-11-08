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
      const rects = all.map((el) => {
        const r = el.getBoundingClientRect();
        // קואורדינטות מסמך ולא חלון: אחרת גלילה משנה את התשובה.
        return { x: r.left + window.scrollX, y: r.top + window.scrollY,
                 width: r.width, height: r.height };
      });
      let idx = all.indexOf(document.activeElement);
      if (idx === -1) {
        // אין פוקוס — החץ הראשון מתחיל מהאלמנט הגלוי העליון.
        idx = rects.reduce((b, r, i) =>
          (r.y < rects[b].y ? i : b), 0);
        all[idx].focus({ preventScroll: true });
        all[idx].scrollIntoView({ block: "center", inline: "center" });
        e.preventDefault();
        return;
      }
      const next = nextInDirection(rects, idx, dir);
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
