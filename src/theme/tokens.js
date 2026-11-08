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

// משטח זכוכית מוכן לשימוש ב-style של React.
export const glassPanel = {
  background: colors.glass,
  backdropFilter: "blur(14px) saturate(140%)",
  WebkitBackdropFilter: "blur(14px) saturate(140%)",
  border: `1px solid ${colors.glassBorder}`,
};

// מזריק את הצבעים כמשתני CSS. נקרא פעם אחת מ-main/App.
export function injectTokens() {
  const r = document.documentElement;
  for (const [k, v] of Object.entries(colors)) r.style.setProperty(`--z-${k}`, v);
  for (const [k, v] of Object.entries(spacing)) r.style.setProperty(`--z-space-${k}`, `${v}px`);
  for (const [k, v] of Object.entries(radius)) r.style.setProperty(`--z-radius-${k}`, `${v}px`);
  r.style.setProperty("color-scheme", "dark");
}

export default { colors, spacing, radius, font, motion, glassPanel, injectTokens };
