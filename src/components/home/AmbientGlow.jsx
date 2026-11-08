import { useEffect, useMemo, useRef } from "react";

/**
 * רקע נוזלי מאחורי כל התוכן.
 *
 * ## מה לא עבד קודם
 *
 * שלוש גרסאות, שלוש דרכים להיכשל: כתמים רוויים בכל גוון (נראה
 * מלוכלך), אדום־סגול חזק (המסך קיבל גוון סגלגל), ואפור כמעט־ניטרלי
 * (שטוח ומת). המשותף לכולן: **צורות שעומדות במקום.** כתם סטטי נקרא
 * תמיד כ"כתם צבע על רקע", יהיה הגוון אשר יהיה.
 *
 * ## מה עושה את ההבדל
 *
 * תנועה שמערבבת. כל צורה נעה, מסתובבת ומשנה גודל בקצב משלה, ומעליהן
 * טשטוש אחד גדול — כך הגבולות ביניהן נמסים זה לזה, והעין קוראת נוזל
 * ולא עיגולים. זה אותו עיקרון של "silk/mesh gradient": אין קו בשום
 * מקום, רק מעברים.
 *
 * הזמנים ראשוניים זה לזה בכוונה (37/53/71/89 שניות), כך שהצירוף
 * אינו חוזר על עצמו במחזור קצר ואין תחושת לולאה.
 *
 * ## אילוצים
 *
 * · ‎transform‎ בלבד — מתנהל ב-compositor ולא מצייר מחדש פריסה.
 * · §14 של apple-design אוסר תנודה סביב 0.2Hz ותנועת רקע גדולה;
 *   המחזורים כאן הם עשרות שניות, והכל נעצר תחת
 *   ‎prefers-reduced-motion‎.
 * · הטשטוש יושב על **עטיפה אחת** ולא על כל צורה: מסנן אחד במקום
 *   ארבעה.
 * · דקורטיבי בלבד — ‎pointerEvents: none‎ ו-‎aria-hidden‎.
 */

function hashOf(seed) {
  let h = 0;
  for (const ch of String(seed || "zovex")) h = (h * 31 + ch.codePointAt(0)) >>> 0;
  return h;
}

export const AMBIENT_KEYFRAMES = `
@keyframes zvFlowA {
  0%   { transform: translate3d(0,0,0) rotate(0deg) scale(1); }
  33%  { transform: translate3d(6%, 4%, 0) rotate(40deg) scale(1.18); }
  66%  { transform: translate3d(-4%, 7%, 0) rotate(80deg) scale(0.92); }
  100% { transform: translate3d(0,0,0) rotate(120deg) scale(1); }
}
@keyframes zvFlowB {
  0%   { transform: translate3d(0,0,0) rotate(0deg) scale(1.08); }
  50%  { transform: translate3d(-7%, -5%, 0) rotate(-55deg) scale(0.88); }
  100% { transform: translate3d(0,0,0) rotate(-110deg) scale(1.08); }
}
@keyframes zvFlowC {
  0%   { transform: translate3d(0,0,0) rotate(0deg) scale(0.95); }
  40%  { transform: translate3d(5%, -6%, 0) rotate(60deg) scale(1.22); }
  100% { transform: translate3d(0,0,0) rotate(140deg) scale(0.95); }
}
/* אין כאן אנימציית filter, בכוונה.
   הייתה כזו (סחיפת גוון על כל השכבה) והיא גרמה לריצוד: הדפדפן
   מחשב מחדש טשטוש של 80px על שטח גדול מהמסך בכל פריים, וזה חורג
   מה-compositor אל ציור מלא. על טלפון זה נראה כמו הבהוב שחור.
   §11 של apple-design אומר את זה במפורש — להנפיש transform
   ו-opacity בלבד. התנועה כאן מגיעה מהצורות עצמן. */
@media (prefers-reduced-motion: reduce) {
  .zv-blob { animation: none !important; }
  /* בלי פרלקסה: הערך נשאר 0 וה-transform מתבטל. */
  .zv-parallax { transform: none !important; }
}
`;

export default function AmbientGlow({ seed }) {
  const layerRef = useRef(null);

  // ── פרלקסה בגלילה ───────────────────────────────────────────────────
  //
  // השכבות נעות בקצב שונה מהתוכן, וזה מה שיוצר עומק: המוח מפרש
  // הפרש מהירויות כמרחק. בלי זה הרקע "מודבק" לתוכן וכל התחושה
  // התלת־ממדית אובדת, גם כשהצורות עצמן זזות.
  //
  // הערך נכתב כמשתנה CSS ונקרא ב-transform, ולכן אין כאן שום
  // חישוב פריסה — רק הזזה ב-compositor. העדכון ב-
  // requestAnimationFrame ולא בכל אירוע scroll: אירועי גלילה
  // מגיעים הרבה יותר מהר מקצב הציור, וכתיבה בכל אחד מהם היא עבודה
  // שנזרקת.
  useEffect(() => {
    const el = layerRef.current;
    if (!el) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    let raf = 0;
    const apply = () => {
      raf = 0;
      const y = window.scrollY || 0;
      el.style.setProperty("--zv-sy", String(y));
    };
    const onScroll = () => { if (!raf) raf = requestAnimationFrame(apply); };
    apply();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => { window.removeEventListener("scroll", onScroll); if (raf) cancelAnimationFrame(raf); };
  }, []);

  const blobs = useMemo(() => {
    const h = hashOf(seed);
    // טווח צר של גוונים קרים. ה-seed מזיז בתוכו, ולא בוחר גוון חדש:
    // כך קטגוריה מרגישה שונה בלי שהמסך יחליף צבע.
    const base = 178 + (h % 46);           // 178–224: טורקיז עד כחול
    const SZ = (v) => `min(${v}vmax, 1250px)`;
    return [
      // ‎par‎ = כמה השכבה "נגררת" עם הגלילה. ערכים שונים = שכבות
      // במרחקים שונים. שלילי אצל אחת כדי שהן גם יחצו זו את זו.
      { hue: base,       sat: 62, lig: 48, top: "-26%", left: "38%", size: SZ(96),  a: 0.42, anim: "zvFlowA", dur: "37s", par: 0.18 },
      { hue: base + 34,  sat: 58, lig: 44, top: "28%",  left: "-28%", size: SZ(104), a: 0.34, anim: "zvFlowB", dur: "53s", par: -0.10 },
      { hue: base - 26,  sat: 55, lig: 46, top: "62%",  left: "34%",  size: SZ(92),  a: 0.30, anim: "zvFlowC", dur: "71s", par: 0.30 },
      { hue: base + 62,  sat: 48, lig: 42, top: "6%",   left: "74%",  size: SZ(80),  a: 0.24, anim: "zvFlowB", dur: "89s", par: -0.22 },
    ];
  }, [seed]);

  return (
    <div
      aria-hidden="true"
      style={{
        position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none",
        overflow: "hidden",
        background: "linear-gradient(165deg, #0E1620 0%, #0B1119 50%, #080C12 100%)",
      }}
    >
      {/* העטיפה נושאת את הטשטוש — מסנן אחד לכל הצורות יחד, וזה גם
          מה שממיס את הגבולות ביניהן לנוזל אחד. */}
      <div
        ref={layerRef}
        className="zv-flow"
        style={{
          position: "absolute", inset: "-20%",
          // ── אין כאן filter בכלל, וזו הנקודה ─────────────────────
          //
          // טשטוש על ההורה מאלץ את הדפדפן לרנדר את כל תת-העץ לטקסטורה
          // אחת ולטשטש אותה. כל עוד הילדים נעים, הטקסטורה הזו נבנית
          // **מחדש בכל פריים** — על שטח גדול מהמסך. זה מה שגרם
          // להבהוב השחור בטלפון, ולא רק אנימציית ה-hue שהוסרה לפניו.
          //
          // הרכות מגיעה מהשיפוע עצמו: radial-gradient שדועך לאפס
          // כבר נראה כמו ענן, ולא צריך מסנן כדי לרכך אותו. התוצאה
          // זהה למראה, והעלות היא אפס ציור — רק הרכבה.
          // נקרא על ידי כל שכבה דרך calc(). ברירת מחדל 0 כדי
          // שהחישוב יהיה תקף עוד לפני הגלילה הראשונה.
          "--zv-sy": 0,
        }}>
        {blobs.map((b, i) => (
          // שתי שכבות ולא אחת: ה-transform של הצורה כבר תפוס על ידי
          // אנימציית הזרימה, ואי אפשר להוסיף עליו גם את הפרלקסה.
          // העטיפה נושאת את ההזזה לפי הגלילה, והילד את הזרימה.
          <div
            key={i}
            className="zv-parallax"
            style={{
              position: "absolute", inset: 0,
              transform: `translate3d(0, calc(var(--zv-sy, 0) * ${b.par}px), 0)`,
              willChange: "transform",
            }}
          >
          <div
            className="zv-blob"
            style={{
              position: "absolute",
              top: b.top, left: b.left, width: b.size, height: b.size,
              borderRadius: "50%",
              background:
                `radial-gradient(circle at 50% 50%,` +
                ` hsla(${b.hue},${b.sat}%,${b.lig}%,${b.a}) 0%,` +
                ` hsla(${b.hue},${b.sat}%,${b.lig - 10}%,${(b.a * 0.5).toFixed(3)}) 45%,` +
                ` hsla(${b.hue},${b.sat}%,${b.lig - 20}%,0) 72%)`,
              animation: `${b.anim} ${b.dur} ease-in-out infinite`,
              willChange: "transform",
            }}
          />
          </div>
        ))}
      </div>

      {/* מסך כהה עדין: שומר על קריאות הטקסט בלי להחזיר את האפור.
          מתחזק כלפי מטה, שם יושבות כותרות השורות. */}
      <div style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        background:
          "linear-gradient(180deg, rgba(8,12,18,0.18) 0%, rgba(8,12,18,0.34) 55%, rgba(8,12,18,0.50) 100%)",
      }} />

      {/* גרעין נגד banding — שיפועים גדולים על מסך כהה מייצרים פסים. */}
      <div style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        opacity: 0.03, mixBlendMode: "overlay",
        backgroundImage:
          "url(\"data:image/svg+xml;utf8," +
          "<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'>" +
          "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='3'/></filter>" +
          "<rect width='160' height='160' filter='url(%23n)'/></svg>\")",
        backgroundSize: "160px 160px",
      }} />
    </div>
  );
}
