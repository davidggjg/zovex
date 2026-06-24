const GITHUB_REPO = import.meta.env.VITE_GITHUB_REPO || 'davidggjg/zovex';
const GITHUB_FILE = 'public/apikeys.json';
const BASE_PATH = import.meta.env.BASE_URL || '/';

function getToken() {
  try { return localStorage.getItem('github_token') || ''; } catch { return ''; }
}

let _keys = null;

async function fetchKeys() {
  try {
    const res = await fetch(`${BASE_PATH}apikeys.json?t=` + Date.now());
    if (!res.ok) throw new Error('failed');
    _keys = await res.json();
    return _keys;
  } catch {
    try {
      const res2 = await fetch(`https://raw.githubusercontent.com/${GITHUB_REPO}/main/${GITHUB_FILE}?t=` + Date.now());
      if (!res2.ok) throw new Error('failed');
      _keys = await res2.json();
      return _keys;
    } catch { return []; }
  }
}

async function saveToGitHub(keys) {
  const token = getToken();
  if (!token) { console.warn('No GitHub token'); return; }
  try {
    let sha;
    try {
      const getRes = await fetch(`https://api.github.com/repos/${GITHUB_REPO}/contents/${GITHUB_FILE}`, {
        headers: { 'Authorization': `token ${token}`, 'Accept': 'application/vnd.github.v3+json' }
      });
      if (getRes.ok) { const fileData = await getRes.json(); sha = fileData.sha; }
    } catch {}
    const content = btoa(unescape(encodeURIComponent(JSON.stringify(keys, null, 2))));
    const body = { message: 'Update API keys', content };
    if (sha) body.sha = sha;
    await fetch(`https://api.github.com/repos/${GITHUB_REPO}/contents/${GITHUB_FILE}`, {
      method: 'PUT',
      headers: { 'Authorization': `token ${token}`, 'Content-Type': 'application/json', 'Accept': 'application/vnd.github.v3+json' },
      body: JSON.stringify(body)
    });
    _keys = keys;
    await fetch(`https://api.github.com/repos/${GITHUB_REPO}/actions/workflows/deploy.yml/dispatches`, {
      method: 'POST',
      headers: { 'Authorization': `token ${token}`, 'Content-Type': 'application/json', 'Accept': 'application/vnd.github.v3+json' },
      body: JSON.stringify({ ref: 'main' })
    });
  } catch (e) { console.error('GitHub save failed:', e); }
}

export const ApiKey = {
  async list(orderBy = '-created_date', limit = 100) {
    _keys = await fetchKeys();
    let sorted = [...(_keys || [])];
    if (orderBy.startsWith('-')) sorted.reverse();
    return sorted.slice(0, limit);
  },
  async create(data) {
    const keys = await fetchKeys();
    const newKey = { ...data, id: crypto.randomUUID(), created_date: new Date().toISOString() };
    const updated = [newKey, ...keys];
    _keys = updated;
    await saveToGitHub(updated);
    return newKey;
  },
  async update(id, data) {
    const keys = await fetchKeys();
    const updated = keys.map(k => k.id === id ? { ...k, ...data } : k);
    _keys = updated;
    await saveToGitHub(updated);
    return updated.find(k => k.id === id);
  },
  async delete(id) {
    const keys = await fetchKeys();
    const updated = keys.filter(k => k.id !== id);
    _keys = updated;
    await saveToGitHub(updated);
    return { id };
  }
};
