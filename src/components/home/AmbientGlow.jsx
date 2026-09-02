import { useMemo } from "react";

/**
 * שכבת זוהר צבעונית מאחורי כל התוכן.
 *
 * מה זה פותר: הרקע היה #0a0a0a שטוח לחלוטין, וזה מה שגורם לאתר להיראות
 * "פשוט" גם כשהתוכן עצמו עשיר. באתרים שנראים יקרים הרקע אינו שחור אלא
 * זוהר כהה שמשתנה תוך כדי גלילה, וזה כל ההבדל בתחושת העומק.
 *
 * למה הגוון נגזר מהקטגוריה ולא מהפוסטרים: שאיבת צבע מתמונה דורשת לצייר
 * אותה ל-canvas, והתמונות כאן מגיעות מדומיינים אחרים — canvas היה נהיה
 * "מזוהם" והקריאה נחסמת. גזירה משם הקטגוריה נותנת את אותה חוויה בדיוק
 * (הרקע מתחלף כשעוברים בין אזורים), עולה אפס, ולא נשברת על CORS.
 *
 * הכל דקורטיבי בלבד: pointerEvents none ו-aria-hidden, כדי שלא יפריע
 * ללחיצות ולא ייקרא ע"י קורא מסך.
 */

// hash יציב → גוון. יציב חשוב: אותה קטגוריה חייבת לקבל אותו צבע בכל
// טעינה, אחרת האתר "מהבהב" בצבע אחר בכל רענון.
function hueOf(seed) {
  let h = 0;
  for (const ch of String(seed || "zovex")) h = (h * 31 + ch.codePointAt(0)) >>> 0;
  return h % 360;
}

export const AMBIENT_KEYFRAMES = `
@keyframes zvDrift {
  0%   { transform: translate3d(0,0,0) scale(1); }
  50%  { transform: translate3d(3%, -2%, 0) scale(1.12); }
  100% { transform: translate3d(0,0,0) scale(1); }
}
@media (prefers-reduced-motion: reduce) {
  .zv-blob { animation: none !important; }
}
`;

export default function AmbientGlow({ seed }) {
  const blobs = useMemo(() => {
    const h = hueOf(seed);
    // שלושה גוונים סמוכים ולא משלימים: משלימים היו יוצרים רקע "מלוכלך"
    // חום־אפור ברגע שהם מתערבבים בטשטוש.
    // הערכים מכוילים מול הדמיה פיקסלית של מה שהדפדפן מצייר בפועל. הגרסה
    // הראשונה (אלפא 0.5/0.38/0.32 עם החשכה 0.62→0.90) יצאה כמעט שחורה
    // לגמרי — שכבת ההחשכה בלעה את כל הצבע ולא נשאר שום אפקט.
    // המידות ב-vmax ולא ב-vw, וזה תיקון ולא העדפה: vw הוא אחוז מ*רוחב*
    // המסך, ובטלפון (390 רוחב על 844 גובה) כתם של 78vw הוא 304 פיקסלים
    // בלבד על מסך בגובה 844 — כיסוי של שליש, שאחרי טשטוש של 72 פיקסלים
    // כמעט נעלם. בדסקטופ אותו ערך הוא 1123 פיקסלים ונראה מצוין, ולכן
    // הכיול המקורי (שנעשה בפרופורציות של מסך רחב) הטעה. vmax נמדד לפי
    // הצלע הגדולה, כך שהאפקט זהה בשני המקרים.
    return [
      { hue: h, top: "-18%", left: "-14%", size: "82vmax", a: 0.66, dur: "26s", delay: "0s" },
      { hue: (h + 38) % 360, top: "22%", left: "44%", size: "74vmax", a: 0.54, dur: "34s", delay: "-8s" },
      { hue: (h + 320) % 360, top: "62%", left: "-6%", size: "78vmax", a: 0.48, dur: "30s", delay: "-16s" },
    ];
  }, [seed]);

  return (
    <div
      aria-hidden="true"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 0,
        pointerEvents: "none",
        overflow: "hidden",
        // לא #0a0a0a אחיד. שחור שטוח לחלוטין הוא מה שגורם למסך להיראות
        // "ריק"; מדרג עדין לכחלחל־כהה נותן עומק עוד לפני שהצבע נכנס.
        background: "linear-gradient(170deg, #101018 0%, #0b0b10 40%, #08080b 100%)",
      }}
    >
      {blobs.map((b, i) => (
        <div
          key={i}
          className="zv-blob"
          style={{
            position: "absolute",
            top: b.top,
            left: b.left,
            width: b.size,
            height: b.size,
            borderRadius: "50%",
            // saturation גבוה עם lightness נמוך: אחרי הטשטוש זה נקרא כזוהר
            // עמוק ולא כפסטל שטוח.
            background: `radial-gradient(circle at 50% 50%, hsla(${b.hue},72%,48%,${b.a}) 0%, hsla(${b.hue},72%,34%,0) 68%)`,
            filter: "blur(72px)",
            animation: `zvDrift ${b.dur} ease-in-out ${b.delay} infinite`,
            willChange: "transform",
            // המעבר בין קטגוריות מתרכך, אחרת הצבע קופץ בבת אחת
            transition: "background 900ms ease",
          }}
        />
      ))}
      {/* שכבת החשכה: בלעדיה הטקסט הלבן מאבד ניגודיות מעל הזוהר */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "linear-gradient(180deg, rgba(8,8,11,0.26) 0%, rgba(8,8,11,0.42) 45%, rgba(8,8,11,0.58) 100%)",
        }}
      />
    </div>
  );
}
