// ─────────────────────────────────────────────────────────────────────────────
// מערכת העיצוב של ZOVEX לאתר — נגזרת ישירה מזו של האפליקציה.
//
// המקור: zovex-android/src/theme/tokens.js. הערכים זהים בכוונה, כי
// המטרה היא שהאתר והאפליקציה ייראו אותו מוצר. מה שהשתנה הוא רק
// הצורה: כאן זה CSS, שם React Native.
//
// הצבעים נחשפים גם כמשתני CSS על ‎:root‎ (ראו injectTokens), כדי
// שאפשר יהיה להשתמש בהם גם מתוך מחרוזות style ו-keyframes בלי לייבא.
//
// למה קובץ אחד ולא theme context: ZOVEX כהה בלבד, אין החלפת ערכת
// נושא בזמן ריצה, ולכן אובייקט קבוע הוא הזול והפשוט ביותר.
// ─────────────────────────────────────────────────────────────────────────────

export const colors = {
  bg: "#07070C",
  surface: "#11121A",
  surfaceElevated: "#1A1C28",
  primary: "#E50924",
  primaryHi: "#FF3348",
  text: "#F7F7F9",
  textSecondary: "#A6A9B3",
  textMuted: "#737783",
  border: "#292D37",
  success: "#3CBF8A",
  warning: "#F2B84B",

  overlay: "rgba(0,0,0,0.65)",
  scrim: "rgba(8,9,13,0.92)",
  focusTint: "rgba(229,9,36,0.18)",
  hairline: "rgba(255,255,255,0.10)",

  // "זכוכית": משטח כהה כמעט-אטום עם קו דק בהיר בקצה. באתר אפשר גם
  // backdrop-filter אמיתי, ולכן הוא נוסף — עם נפילה חזרה לרקע האטום
  // במנועים שאינם תומכים.
  glass: "rgba(24,26,38,0.94)",
  glassBorder: "rgba(255,255,255,0.12)",
  glassActive: "rgba(255,255,255,0.14)",
  glowRed: "rgba(229,9,36,0.55)",
};

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, xxl: 24, xxxl: 32 };
export const radius = { sm: 8, card: 12, button: 12, pill: 999, hero: 28 };

export const font = {
  hero: 32, screenTitle: 26, section: 19,
  cardTitle: 15, body: 14, label: 13, caption: 12,
  weightBold: 800, weightMed: 600,
};

export const motion = { fast: 120, base: 180, slow: 220 };

// ── עומק ────────────────────────────────────────────────────────────────
//
// מה שגורם למשטח להיראות צף ולא מודבק הוא שלוש שכבות ביחד, ולא צל
// אחד גדול:
//
//   1. קו פנימי בהיר בקצה העליון — "השתקפות" של אור מלמעלה. זה
//      הפרט שהכי מזוהה עם המראה של אפל, והוא גם הזול ביותר.
//   2. קו חיצוני דק שמפריד מהרקע.
//   3. צל רך ורחב עם היסט כלפי מטה, ולא טשטוש סימטרי.
//
// הצל כהה מאוד (0.55–0.8) כי הרקע עצמו כהה; צל חיוור על רקע כהה
// פשוט אינו נראה.
export const depth = (level = 2) => {
  const d = { 1: [10, 24, 0.5], 2: [16, 36, 0.6], 3: [24, 56, 0.72] }[level] || [16, 36, 0.6];
  const [y, blur, alpha] = d;
  return {
    boxShadow: [
      "inset 0 1px 0 rgba(255,255,255,0.07)",
      "0 0 0 1px rgba(255,255,255,0.07)",
      `0 ${y}px ${blur}px -${Math.round(blur / 3)}px rgba(0,0,0,${alpha})`,
    ].join(", "),
  };
};

// תנועה: עלייה קלה במגע/ריחוף. העקומה היא ease-out חד בהתחלה ורך
// בסוף — זה מה שגורם לתנועה להרגיש "חיה" ולא ליניארית.
export const lift = {
  transition: "transform 220ms cubic-bezier(0.22, 1, 0.36, 1), box-shadow 220ms ease",
};

// ── זכוכית אמיתית ───────────────────────────────────────────────────────
//
// ‎colors.glass‎ הוא ‎rgba(24,26,38,0.94)‎ — כמעט אטום. זה נכון
// *באפליקציה*: ב-React Native אין טשטוש רקע בלי ספרייה נייטיבית,
// ולכן "זכוכית" שם היא משטח כהה עם קו בהיר בקצה. בדפדפן יש
// ‎backdrop-filter‎ אמיתי, ורקע ב-94% אטימות פשוט מכסה אותו — מה
// שיוצא הוא פס שחור, לא זכוכית.
//
// לכן לאתר יש ערך משלו: רקע שקוף הרבה יותר, טשטוש חזק, והעלאת
// רוויה — הרוויה היא מה שגורם לצבעים שמתחת "לזלוג" דרך הזכוכית
// במקום להיראות אפורים, וזה הפרט שהכי מזוהה עם המראה הזה.
//
// שלוש שכבות בתוך ה-background: שיפוע לבן עדין מלמעלה למטה
// (האור), ומעליו גוון כהה — כך המשטח נראה כמו לוח זכוכית מואר
// מלמעלה ולא כמו מלבן צבוע.
// ── חומר: זכוכית ────────────────────────────────────────────────────────
//
// לפי skills/apple-design §12. הנוסחה שם היא רקע חצי־שקוף + טשטוש
// + העלאת רוויה + **קצה עליון בהיר** — "האור שנתפס בחומר". הקצה
// הבהיר הוא הפרט שהופך משטח שקוף למשהו שנראה כמו לוח ולא כמו חור.
//
// ‎colors.glass‎ של האפליקציה הוא 94% אטום, וזה נכון שם: ב-React
// Native אין טשטוש רקע בלי ספרייה נייטיבית. בדפדפן רקע כזה פשוט
// מכסה את ה-backdrop-filter, ומה שיוצא הוא פס שחור — בדיוק מה
// שנראה בסרגל התחתון. לכן לאתר יש חומר משלו.
//
// §12 גם קובע את ההיררכיה: משטח גדול נקרא עבה יותר — טשטוש חזק
// יותר וצל עמוק יותר מצ'יפ קטן. לכן ‎weight‎ ולא ערך אחד לכולם.
const MATERIAL = {
  chip:    { blur: 18, bg: 0.30, edge: 0.14, sat: 170 },
  panel:   { blur: 26, bg: 0.38, edge: 0.16, sat: 180 },
  chrome:  { blur: 36, bg: 0.46, edge: 0.20, sat: 190 },
};

export function glass(weight = "panel") {
  const m = MATERIAL[weight] || MATERIAL.panel;
  return {
    background:
      `linear-gradient(180deg, rgba(255,255,255,0.09) 0%, rgba(255,255,255,0.025) 48%, rgba(255,255,255,0.01) 100%), ` +
      `rgba(16,17,25,${m.bg})`,
    backdropFilter: `blur(${m.blur}px) saturate(${m.sat}%)`,
    WebkitBackdropFilter: `blur(${m.blur}px) saturate(${m.sat}%)`,
    border: `1px solid rgba(255,255,255,${m.edge * 0.6})`,
    borderTopColor: `rgba(255,255,255,${m.edge})`,
    boxShadow: `inset 0 1px 0 rgba(255,255,255,${m.edge})`,
  };
}

// זכוכית + צל, לשכבות שצפות מעל התוכן. §12: משטח גדול = צל עמוק יותר.
export function glassFloating(weight = "chrome", level = 3) {
  const g = glass(weight);
  return { ...g, boxShadow: `${g.boxShadow}, ${depth(level).boxShadow}` };
}

export const glassPanel = glass("panel");

// מזריק את הצבעים כמשתני CSS. נקרא פעם אחת מ-main/App.
export function injectTokens() {
  const r = document.documentElement;
  for (const [k, v] of Object.entries(colors)) r.style.setProperty(`--z-${k}`, v);
  for (const [k, v] of Object.entries(spacing)) r.style.setProperty(`--z-space-${k}`, `${v}px`);
  for (const [k, v] of Object.entries(radius)) r.style.setProperty(`--z-radius-${k}`, `${v}px`);
  r.style.setProperty("color-scheme", "dark");
}

export default { colors, spacing, radius, font, motion, depth, lift,
                 glass, glassFloating, glassPanel, injectTokens };
