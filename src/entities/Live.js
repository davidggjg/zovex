const GITHUB_REPO = import.meta.env.VITE_GITHUB_REPO || 'davidggjg/zovex';
const GITHUB_FILE = 'public/live.json';
const BASE_PATH = import.meta.env.BASE_URL || '/';

function getToken() {
  try { return localStorage.getItem('github_token') || ''; } catch { return ''; }
}

async function fetchLive() {
  try {
    const res = await fetch(`${BASE_PATH}live.json?t=` + Date.now());
    if (!res.ok) throw new Error('failed');
    return await res.json();
  } catch {
    try {
      const res2 = await fetch(`https://raw.githubusercontent.com/${GITHUB_REPO}/main/${GITHUB_FILE}?t=` + Date.now());
      if (!res2.ok) throw new Error('failed');
      return await res2.json();
    } catch { return { url: '' }; }
  }
}

async function saveToGitHub(data) {
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
    const content = btoa(unescape(encodeURIComponent(JSON.stringify(data, null, 2))));
    const body = { message: 'Update live stream', content };
    if (sha) body.sha = sha;
    await fetch(`https://api.github.com/repos/${GITHUB_REPO}/contents/${GITHUB_FILE}`, {
      method: 'PUT',
      headers: { 'Authorization': `token ${token}`, 'Content-Type': 'application/json', 'Accept': 'application/vnd.github.v3+json' },
      body: JSON.stringify(body)
    });
  } catch (e) { console.error('Live save failed:', e); }
}

export const Live = {
  async get() {
    return await fetchLive();
  },
  async set(url) {
    const data = { url: url || '' };
    await saveToGitHub(data);
    return data;
  },
  async clear() {
    const data = { url: '' };
    await saveToGitHub(data);
    return data;
  }
};
