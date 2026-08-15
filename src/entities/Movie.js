const GITHUB_REPO = import.meta.env.VITE_GITHUB_REPO || 'davidggjg/zovex';
const GITHUB_FILE = 'public/movies.json';
const BASE_PATH = import.meta.env.BASE_URL || '/';
// כשהאתר רץ על השרת — מושכים את התוכן מ-/content (אותו origin) במקום מגיטהאב.
const CONTENT_URL = import.meta.env.VITE_CONTENT_URL || '';

function getToken() {
  try { return localStorage.getItem('github_token') || ''; } catch { return ''; }
}

let _movies = null;      // מה שיש בזיכרון עכשיו — מנה ראשונה או קטלוג מלא
let _full = null;        // הקטלוג המלא, אחרי שהגיע
let _fullPromise = null;
let _loadedAt = 0;

// טעינה דו-שלבית. נמדד: הקטלוג המלא הוא ~950KB דחוס ולוקח ~4 שניות לפרסר
// (בטלפון הרבה יותר) — והכל לפני שמצוירת כרטיסייה אחת. 800 הפריטים
// הראשונים במצב רזה הם 62KB ומפוענחים כמעט מיידית, אז המסך נצבע מיד
// והשאר מגיע ברקע. אין כאן cache-buster בכוונה: השרת מחזיר ETag לפי מונת
// הגרסה, כך שכניסה חוזרת מקבלת 304 ריק במקום להוריד הכל שוב.
const FIRST_PAGE = 800;

async function _tryJson(url) {
  try {
    const r = await fetch(url);
    if (r.ok) return await r.json();
  } catch {}
  return null;
}

// נטען ברקע אחרי הציור הראשון; onFull נקרא כשהקטלוג המלא זמין (לחיפוש).
// כמה קוראים יכולים להמתין לאותה הורדה, וגם מי שמבקש אחרי שהיא כבר הסתיימה
// מקבל את התוצאה מיד — בלי זה טעינה מוקדמת הייתה "בולעת" את הקטלוג המלא
// והמסך היה נשאר עם 800 הפריטים הראשונים בלבד.
function _loadFullInBackground(onFull) {
  if (_full) { onFull && onFull(_full); return; }
  if (!_fullPromise) {
    _fullPromise = (async () => {
      const all = await _tryJson('/content/lite')
               || await _tryJson(`${BASE_PATH}movies.json`);
      if (all && all.length) { _full = all; _movies = all; }
      return _full;
    })();
  }
  if (onFull) _fullPromise.then(all => { if (all) onFull(all); });
}

// מתחיל למשוך את הקטלוג מיד עם עליית האפליקציה, בלי לחכות למסך הכניסה.
// עד עכשיו useMovieLibrary היה מותקן רק אחרי "התחבר" או "דלג", ולכן כל
// ההורדה והפרסור התחילו רק אחרי הלחיצה — המשתמש בהה במסך הכניסה בזמן
// שהרשת הייתה פנויה לגמרי, ואז חיכה עוד כמה שניות. מכאן זה רץ במקביל,
// והרשימה כבר בזיכרון כשהמסך נטען.
let _prefetch = null;
export function prefetchMovies() {
  if (!_prefetch) _prefetch = fetchMovies().catch(() => null);
  return _prefetch;
}

// כמה זמן תוצאה נחשבת טרייה. מכסה את הפער בין הטעינה המוקדמת לבין הרכבת
// המסך, ולא פוגע ברענון בחזרה ללשונית — הוא ממילא מוגבל לפעם בדקה.
const FRESH_MS = 30000;

async function fetchMovies(onFull) {
  if (_movies && Date.now() - _loadedAt < FRESH_MS) {
    _loadFullInBackground(onFull);
    return _movies;
  }
  // רענון אמיתי — הקטלוג המלא נמשך שוב, לא מוגש מהזיכרון
  _full = null;
  _fullPromise = null;
  // שלב 1 — מעט פריטים, ציור מיידי.
  const first = await _tryJson(`/content/lite?limit=${FIRST_PAGE}`);
  if (first && first.length) {
    _movies = first;
    _loadedAt = Date.now();
    _loadFullInBackground(onFull);
    return _movies;
  }
  // נפילה אחורה: קטלוג מלא ישירות (שרת), ואז גיטהאב.
  const full = await _tryJson(CONTENT_URL || '/content')
            || await _tryJson(`${BASE_PATH}movies.json`)
            || await _tryJson(`https://raw.githubusercontent.com/${GITHUB_REPO}/main/${GITHUB_FILE}`);
  _movies = _full = full || [];
  _loadedAt = Date.now();
  return _movies;
}

// כל שינוי בפאנל שומר את *כל* המערך, ולכן חייב לעבוד על הקטלוג המלא.
// fetchMovies מחזיר את 800 הפריטים הראשונים ברגע שהם מוכנים — עריכה על
// בסיס זה הייתה שומרת 800 פריטים ומוחקת את כל השאר.
async function fetchAll() {
  if (_full) return _full;
  await fetchMovies();
  if (_fullPromise) {
    const all = await _fullPromise;
    if (all && all.length) return all;
  }
  return _movies || [];
}

async function saveToGitHub(movies) {
  const token = getToken();
  if (!token) { console.warn('No GitHub token'); return; }
  try {
    const getRes = await fetch(`https://api.github.com/repos/${GITHUB_REPO}/contents/${GITHUB_FILE}`, {
      headers: { 'Authorization': `token ${token}`, 'Accept': 'application/vnd.github.v3+json' }
    });
    const fileData = await getRes.json();
    const sha = fileData.sha;
    const content = btoa(unescape(encodeURIComponent(JSON.stringify(movies, null, 2))));
    await fetch(`https://api.github.com/repos/${GITHUB_REPO}/contents/${GITHUB_FILE}`, {
      method: 'PUT',
      headers: { 'Authorization': `token ${token}`, 'Content-Type': 'application/json', 'Accept': 'application/vnd.github.v3+json' },
      body: JSON.stringify({ message: 'Update movies', content, sha })
    });
    _movies = movies;
    await fetch(`https://api.github.com/repos/${GITHUB_REPO}/actions/workflows/deploy.yml/dispatches`, {
      method: 'POST',
      headers: { 'Authorization': `token ${token}`, 'Content-Type': 'application/json', 'Accept': 'application/vnd.github.v3+json' },
      body: JSON.stringify({ ref: 'main' })
    });
  } catch (e) { console.error('GitHub save failed:', e); }
}

// התיאור לא נשלח בקטלוג הרזה (32% מהמשקל, ומוצג רק כשפותחים פריט), אז מושכים
// אותו לפי דרישה. הזיכרון המקומי מונע בקשה חוזרת לאותו פריט.
const _descCache = new Map();
export async function loadDescription(id) {
  if (!id) return '';
  if (_descCache.has(id)) return _descCache.get(id);
  try {
    const r = await fetch(`/content/item/${encodeURIComponent(id)}`);
    if (r.ok) {
      const d = await r.json();
      const t = d.description || '';
      _descCache.set(id, t);
      return t;
    }
  } catch {}
  _descCache.set(id, '');
  return '';
}

export const Movie = {
  // onFull (אופציונלי) נקרא כשהקטלוג המלא הגיע ברקע — מאפשר למסך להתעדכן
  // בלי לחסום את הציור הראשון.
  async list(orderBy = '-created_date', limit = 100000, onFull = null) {
    const sortSlice = (arr) => {
      const s = [...(arr || [])];
      if (orderBy.startsWith('-')) s.reverse();
      return s.slice(0, limit);
    };
    _movies = await fetchMovies(onFull ? (all) => onFull(sortSlice(all)) : null);
    return sortSlice(_movies);
  },
  async create(data) {
    const movies = await fetchAll();
    const newMovie = { ...data, id: crypto.randomUUID(), created_date: new Date().toISOString() };
    const updated = [newMovie, ...movies];
    _movies = updated;
    await saveToGitHub(updated);
    return newMovie;
  },
  async update(id, data) {
    const movies = await fetchAll();
    const updated = movies.map(m => m.id === id ? { ...m, ...data } : m);
    _movies = updated;
    await saveToGitHub(updated);
    return updated.find(m => m.id === id);
  },
  async delete(id) {
    const movies = await fetchAll();
    const updated = movies.filter(m => m.id !== id);
    _movies = updated;
    await saveToGitHub(updated);
    return { id };
  },
  async saveAll(movies) {
    _movies = movies;
    await saveToGitHub(movies);
    return movies;
  }
};
