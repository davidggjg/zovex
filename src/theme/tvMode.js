// ─────────────────────────────────────────────────────────────────────────────
// מצב טלוויזיה באתר.
//
// באפליקציה יש ‎Platform.isTV‎ ו-‎TvFocusable‎, ורכיב נייטיב שמדווח
// פוקוס. בדפדפן אין מקבילה: טלוויזיה פשוט מריצה דפדפן, ולרוב מדווחת
// על עצמה כמחשב. לכן הזיהוי הוא משולב — מחרוזת הדפדפן, יכולת המצביע,
// והמרחק מהמסך כפי שהוא משתקף בגודל החלון.
//
// ההחלטה שמרנית בכוונה: טעות לכיוון "זו טלוויזיה" על מחשב רגיל גרועה
// הרבה יותר מטעות לכיוון השני, כי היא מגדילה הכול ומשנה את הניווט
// למישהו שיש לו עכבר.
//
// שתי הפונקציות כאן טהורות ונבדקות ב-scripts/test-tv.mjs.
// ─────────────────────────────────────────────────────────────────────────────

const TV_UA = /\b(smart-?tv|smarttv|googletv|android tv|androidtv|appletv|crkey|chromecast|hbbtv|netcast|viera|bravia|aquos|webos|web0s|tizen|roku|playstation|xbox|dtv|large screen)\b/i;

export function detectTv({ ua = "", width = 0, height = 0,
                           coarsePointer = false, hasTouch = false } = {}) {
  if (TV_UA.test(ua)) return true;
  // מסך ענק, בלי מגע, עם מצביע גס (שלט) — זו טלוויזיה גם אם מחרוזת
  // הדפדפן אינה מסגירה אותה. בלי תנאי המגע כל מסך גדול עם מסך מגע
  // היה נכנס לכאן.
  if (!hasTouch && coarsePointer && width >= 1280) return true;
  return false;
}

export function detectTvFromWindow(win = typeof window !== "undefined" ? window : null) {
  if (!win) return false;
  const mq = (q) => { try { return !!win.matchMedia && win.matchMedia(q).matches; } catch { return false; } };
  return detectTv({
    ua: win.navigator?.userAgent || "",
    width: win.innerWidth || 0,
    height: win.innerHeight || 0,
    coarsePointer: mq("(pointer: coarse)") || mq("(hover: none)"),
    hasTouch: (win.navigator?.maxTouchPoints || 0) > 0,
  });
}

// ── ניווט בחצים ─────────────────────────────────────────────────────────
//
// בחירה גאומטרית: מבין המועמדים בכיוון הנכון, הקרוב ביותר — עם משקל
// גדול יותר לסטייה בציר המשני, כדי שחץ ימינה בשורה לא יקפוץ לשורה
// אחרת רק מפני שהיא קרובה יותר בקו אווירי.
//
// העבודה היא על מלבנים ולא על אלמנטים, כדי שאפשר יהיה לבדוק את זה
// בלי דפדפן.
// שני שלבים, וזה ההבדל בין ניווט שמרגיש נכון לאחד שקופץ:
//
//   1. מועמדים שחופפים לנוכחי בציר המשני — אותה שורה לחצים אופקיים,
//      אותה עמודה לאנכיים. מביניהם, הקרוב ביותר בציר הראשי.
//   2. רק אם אין אף חופף — הקרוב ביותר לפי מרחק משוקלל.
//
// בלי שלב 1, כרטיס בשורה הבאה שנמצא קרוב יותר בקו אווירי "גונב" את
// חץ ימינה. נתפס בבדיקה: כרטיס במרחק 1000 באותה שורה הפסיד לכרטיס
// במרחק 60 בשורה שמתחת.
const CROSS_WEIGHT = 3;

const overlaps = (a1, a2, b1, b2) => Math.min(a2, b2) - Math.max(a1, b1) > 0;

export function nextInDirection(rects, currentIndex, dir) {
  const cur = rects[currentIndex];
  if (!cur) return -1;
  const horizontal = dir === "left" || dir === "right";
  const cx = cur.x + cur.width / 2;
  const cy = cur.y + cur.height / 2;
  const EPS = 2;

  let bestAligned = -1, bestAlignedD = Infinity;
  let bestAny = -1, bestAnyScore = Infinity;

  rects.forEach((r, i) => {
    if (i === currentIndex) return;
    const x = r.x + r.width / 2;
    const y = r.y + r.height / 2;
    const dx = x - cx;
    const dy = y - cy;
    if (dir === "right" && dx <= EPS) return;
    if (dir === "left" && dx >= -EPS) return;
    if (dir === "down" && dy <= EPS) return;
    if (dir === "up" && dy >= -EPS) return;

    const main = horizontal ? Math.abs(dx) : Math.abs(dy);
    const cross = horizontal ? Math.abs(dy) : Math.abs(dx);
    const aligned = horizontal
      ? overlaps(cur.y, cur.y + cur.height, r.y, r.y + r.height)
      : overlaps(cur.x, cur.x + cur.width, r.x, r.x + r.width);

    if (aligned && main < bestAlignedD) { bestAlignedD = main; bestAligned = i; }
    const score = main + cross * CROSS_WEIGHT;
    if (score < bestAnyScore) { bestAnyScore = score; bestAny = i; }
  });

  return bestAligned !== -1 ? bestAligned : bestAny;
}

export const KEY_TO_DIR = {
  ArrowRight: "right", ArrowLeft: "left", ArrowUp: "up", ArrowDown: "down",
};
