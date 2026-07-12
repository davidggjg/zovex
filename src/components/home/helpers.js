// ─── constants ────────────────────────────────────────────────
export const BACKEND_URL = "https://davidhzhdhd-my-telegram-bot.hf.space";

// ─── Backend API helper ──────────────────────────────
export async function apiCall(path, method = "GET", body = null, userId = null) {
  try {
    const headers = { "Content-Type": "application/json" };
    if (userId) headers["x-user-id"] = userId;
    const res = await fetch(`${BACKEND_URL}${path}`, {
      method, headers,
      body: body ? JSON.stringify(body) : undefined
    });
    if (!res.ok) {
      console.warn(`[zovex] apiCall ${method} ${path} → HTTP ${res.status}. הבקאש (${BACKEND_URL}) לא מחזיר תשובה תקינה — היסטוריה/המשך צפייה לא יישמרו.`);
      return null;
    }
    return await res.json();
  } catch (e) {
    console.warn(`[zovex] apiCall ${method} ${path} נכשל — הבקאש (${BACKEND_URL}) כנראה לא זמין/ישן/חסום ע"י CORS. שגיאה:`, e);
    return null;
  }
}

export const SPIN = `@keyframes spin { to { transform: rotate(360deg); } } @keyframes livePulse { 0%,100%{box-shadow:0 0 0 0 rgba(255,255,255,.7)} 50%{box-shadow:0 0 0 8px rgba(255,255,255,0)} } @keyframes livePulseDot { 0%,100%{box-shadow:0 0 0 0 rgba(229,9,20,.6)} 50%{box-shadow:0 0 0 6px rgba(229,9,20,0)} } html,body{overscroll-behavior:none;}`;

// ─── localStorage helpers ──────────────────────────────────────
export function ls(key, fallback = null) {
  try { const v = localStorage.getItem(key); return v !== null ? v : fallback; } catch { return fallback; }
}
export function lsSet(key, val) { try { localStorage.setItem(key, val); } catch {} }
export function lsDel(key) { try { localStorage.removeItem(key); } catch {} }
export function lsJson(key, fallback = null) {
  try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch { return fallback; }
}

export function extractVideoInfo(url) {
  if (!url) return { type: "direct", video_id: "" };
  if (url.includes("<iframe")) {
    const m = url.match(/src=["']([^"']+)['"]/);
    if (m) url = m[1];
  }
  if (!url.startsWith("http")) return { type: "direct", video_id: url };
  if (url.includes("youtube.com") || url.includes("youtu.be")) {
    const m = url.match(/(?:v=|youtu\.be\/)([^&/?]+)/);
    return { type: "youtube", video_id: m?.[1] || url };
  }
  if (url.includes("drive.google.com")) {
    const m = url.match(/\/d\/([^/]+)/);
    return { type: "drive", video_id: m?.[1] || url };
  }
  if (url.includes("vimeo.com")) {
    const m = url.match(/vimeo\.com\/(\d+)/);
    return { type: "vimeo", video_id: m?.[1] || url };
  }
  if (url.includes("dailymotion.com")) {
    const m = url.match(/video\/([^_]+)/);
    return { type: "dailymotion", video_id: m?.[1] || url };
  }
  if (url.includes("streamable.com")) {
    const m = url.match(/streamable\.com\/([^?]+)/);
    return { type: "streamable", video_id: m?.[1] || url };
  }
  if (url.includes("rumble.com")) {
    const m = url.match(/embed\/([^?/]+)/);
    return { type: "rumble", video_id: m?.[1] || url };
  }
  if (url.includes("archive.org")) {
    const m = url.match(/details\/([^?/]+)/);
    return { type: "archive", video_id: m?.[1] || url };
  }
  if (url.includes("kan.org.il")) {
    const m = url.match(/id=(\d+)/);
    return { type: "kan", video_id: m?.[1] || url };
  }
  if (url.includes("ok.ru")) {
    const m = url.match(/video\/(\d+)/);
    return { type: "okru", video_id: m?.[1] || url };
  }
  if (url.includes("t.me")) return { type: "telegram", video_id: url.replace("https://t.me/", "") };
  if (url.includes("kaltura.com") || url.match(/^\d+\/\d+\/[a-zA-Z0-9_]+$/)) {
    const m = url.match(/\/p\/(\d+).*uiconf_id\/(\d+).*entry_id=([^&]+)/);
    if (m) return { type: "kaltura", video_id: `${m[1]}/${m[2]}/${m[3]}` };
    return { type: "kaltura", video_id: url };
  }
  return { type: "direct", video_id: url };
}
