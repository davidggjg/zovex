const GITHUB_REPO = import.meta.env.VITE_GITHUB_REPO || 'davidggjg/zovex-11';
const GITHUB_FILE = 'public/movies.json';
const BASE_PATH = import.meta.env.BASE_URL || '/';

function getToken() {
  try { return localStorage.getItem('github_token') || ''; } catch { return ''; }
}

let _movies = null;

async function fetchMovies() {
  try {
    const res = await fetch(`${BASE_PATH}movies.json?t=` + Date.now());
    if (!res.ok) throw new Error('failed');
    _movies = await res.json();
    return _movies;
  } catch {
    try {
      const res2 = await fetch(`https://raw.githubusercontent.com/${GITHUB_REPO}/main/${GITHUB_FILE}?t=` + Date.now());
      if (!res2.ok) throw new Error('failed');
      _movies = await res2.json();
      return _movies;
    } catch { return []; }
  }
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

export const Movie = {
  async list(orderBy = '-created_date', limit = 2000) {
    _movies = await fetchMovies();
    let sorted = [...(_movies || [])];
    if (orderBy.startsWith('-')) sorted.reverse();
    return sorted.slice(0, limit);
  },
  async create(data) {
    const movies = await fetchMovies();
    const newMovie = { ...data, id: crypto.randomUUID(), created_date: new Date().toISOString() };
    const updated = [newMovie, ...movies];
    _movies = updated;
    await saveToGitHub(updated);
    return newMovie;
  },
  async update(id, data) {
    const movies = await fetchMovies();
    const updated = movies.map(m => m.id === id ? { ...m, ...data } : m);
    _movies = updated;
    await saveToGitHub(updated);
    return updated.find(m => m.id === id);
  },
  async delete(id) {
    const movies = await fetchMovies();
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
