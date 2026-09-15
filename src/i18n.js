// ── שפה באתר ─────────────────────────────────────────────────────────────────
// אותה גישה ואותם מפתחות כמו באפליקציה (zovex-android/src/i18n), כדי ששני
// המילונים לא יתפצלו לשני נוסחים שונים לאותו טקסט.
//
// עברית היא ברירת המחדל ולא "שפה נוספת": כל התוכן עברי, ורוב המבקרים לא
// ייגעו בבורר הזה לעולם.

const KEY = 'zovex_lang_v1';
export const LANGS = { he: 'עברית', en: 'English' };
export const DEFAULT_LANG = 'he';

const STRINGS = {
  he: {
    'common.search': 'חפש סרט או סדרה…',
    'common.all': 'הכל',
    'common.live': 'שידורים חיים',
    'common.history': 'היסטוריה',
    'common.favorites': 'מועדפים',
    'common.close': 'סגור',
    'common.retry': 'נסה שוב',
    'common.loading': 'טוען…',
    'common.noResults': 'לא נמצאו תוצאות',
    'common.language': 'שפה',
    'home.continueWatching': 'המשך צפייה',
    'home.downloadApp': 'הורידו את אפליקציית ZOVEX לאנדרואיד',
    'detail.play': 'הפעל',
    'detail.trailer': 'טריילר',
    'auth.signIn': 'התחברות',
    'auth.signOut': 'התנתקות',
    'player.speed': 'מהירות הפעלה',
    'player.speedNormal': 'רגיל',
    'player.resumeTitle': 'להמשיך מאיפה שעצרת?',
    'player.resumeYes': 'המשך מכאן',
    'player.resumeNo': 'התחל מההתחלה',
  },
  en: {
    'common.search': 'Search for a movie or series…',
    'common.all': 'All',
    'common.live': 'Live TV',
    'common.history': 'History',
    'common.favorites': 'Favorites',
    'common.close': 'Close',
    'common.retry': 'Try again',
    'common.loading': 'Loading…',
    'common.noResults': 'No results found',
    'common.language': 'Language',
    'home.continueWatching': 'Continue watching',
    'home.downloadApp': 'Get the ZOVEX app for Android',
    'detail.play': 'Play',
    'detail.trailer': 'Trailer',
    'auth.signIn': 'Sign in',
    'auth.signOut': 'Sign out',
    'player.speed': 'Playback speed',
    'player.speedNormal': 'Normal',
    'player.resumeTitle': 'Resume where you left off?',
    'player.resumeYes': 'Resume',
    'player.resumeNo': 'Start from the beginning',
  },
};

function read() {
  try {
    const v = localStorage.getItem(KEY);
    return LANGS[v] ? v : DEFAULT_LANG;
  } catch {
    return DEFAULT_LANG;   // גלישה פרטית / אחסון חסום
  }
}

let current = read();

export function getLanguage() {
  return current;
}

export function isRTL() {
  return current === 'he';
}

// בדפדפן כיוון הכתיבה הוא תכונה על <html> ומתחלף מיד — בניגוד לאפליקציה,
// שבה RTL הוא הגדרה ברמת המערכת ודורש הפעלה מחדש.
export function applyDir() {
  try {
    const el = document.documentElement;
    el.setAttribute('lang', current);
    el.setAttribute('dir', isRTL() ? 'rtl' : 'ltr');
  } catch {}
}

export function setLanguage(lang) {
  if (!LANGS[lang] || lang === current) return false;
  current = lang;
  try { localStorage.setItem(KEY, lang); } catch {}
  applyDir();
  // רענון מלא ולא ניסיון לצייר מחדש: הטקסטים פזורים בעשרות רכיבים שאינם
  // מנויים לשינוי שפה, ורענון מבטיח שלא יישאר חצי מסך בשפה הקודמת.
  try { window.location.reload(); } catch {}
  return true;
}

// t('common.search') → הטקסט בשפה הנוכחית.
// נפילה בשלושה שלבים: השפה הנוכחית → עברית → המפתח עצמו. מפתח חסר מציג
// טקסט ולא שובר עמוד, כך שאפשר לתרגם בהדרגה.
export function t(key, vars) {
  const dict = STRINGS[current] || STRINGS[DEFAULT_LANG];
  let s = dict[key];
  if (s == null) s = STRINGS[DEFAULT_LANG][key];
  if (s == null) return key;
  if (vars) for (const k of Object.keys(vars)) s = s.split(`{${k}}`).join(String(vars[k]));
  return s;
}

applyDir();
