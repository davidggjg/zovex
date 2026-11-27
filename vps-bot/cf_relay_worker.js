// ZOVEX · Cloudflare Worker — ממסר HLS חתום (http → https + CORS)
//
// שימוש:  https://<worker>.workers.dev/r/<base64url(url)>/<sig>/i.m3u8
//   sig = base64url(HMAC-SHA256(SECRET, url)) — 22 התווים הראשונים.
// הקישור נוצר בשרת (zv-cflink). בלי חתימה תקפה ⇒ 403, כך שאף אחד אחר לא יכול
// להשתמש בממסר. רשימות m3u8 נכתבות מחדש: כל קטע/תת-רשימה/מפתח עובר גם הוא
// דרך הממסר, חתום. Workers לא מורשים לפנות לכתובת IP ישירה, ולכן IP מוחלף
// אוטומטית בשם ‎<ip>.sslip.io‎ (שירות DNS חינמי שמצביע על אותו IP).
//
// הגדרה: Settings → Variables and Secrets → Secret בשם SECRET.

const enc = new TextEncoder();
let _key = null, _keySecret = null;

const b64u = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)))
  .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const ub64 = (s) => {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  return decodeURIComponent(escape(atob(s + "===".slice((s.length + 3) % 4))));
};
const tob64u = (str) => btoa(unescape(encodeURIComponent(str)))
  .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

async function hmacKey(secret) {
  if (_key && _keySecret === secret) return _key;
  _key = await crypto.subtle.importKey("raw", enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  _keySecret = secret;
  return _key;
}
async function sign(secret, url) {
  const k = await hmacKey(secret);
  return b64u(await crypto.subtle.sign("HMAC", k, enc.encode(url))).slice(0, 22);
}
function timingSafeEq(a, b) {
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

// Workers לא פונים ל-IP ישיר — ממירים לשם sslip.io שמצביע על אותו IP
function fetchableUrl(u) {
  const x = new URL(u);
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(x.hostname)) x.hostname = x.hostname + ".sslip.io";
  return x.toString();
}

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
  "Access-Control-Allow-Headers": "Range, Content-Type",
  "Access-Control-Expose-Headers": "Content-Length, Content-Range",
};

async function relayPath(secret, origin, absUrl) {
  const sig = await sign(secret, absUrl);
  const name = /\.m3u8(\?|$)/i.test(absUrl) ? "i.m3u8" : /\.key(\?|$)/i.test(absUrl) ? "k.key" : "s.ts";
  return `${origin}/r/${tob64u(absUrl)}/${sig}/${name}`;
}

async function rewritePlaylist(text, baseUrl, secret, origin) {
  const out = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) { out.push(raw); continue; }
    if (line.startsWith("#")) {
      // ‎URI="..."‎ בתגיות KEY / MAP / MEDIA / I-FRAME-STREAM-INF
      const m = line.match(/URI="([^"]+)"/);
      if (m) {
        const abs = new URL(m[1], baseUrl).toString();
        out.push(line.replace(m[0], `URI="${await relayPath(secret, origin, abs)}"`));
      } else out.push(line);
      continue;
    }
    out.push(await relayPath(secret, origin, new URL(line, baseUrl).toString()));
  }
  return out.join("\n");
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    if (request.method !== "GET" && request.method !== "HEAD") return new Response("method", { status: 405, headers: CORS });
    const secret = env.SECRET;
    if (!secret) return new Response("SECRET לא הוגדר ב-Worker", { status: 500, headers: CORS });

    const u = new URL(request.url);
    const m = u.pathname.match(/^\/r\/([A-Za-z0-9_-]+)\/([A-Za-z0-9_-]{22})(?:\/[^/]*)?$/);
    if (!m) return new Response("ZOVEX relay", { status: 404, headers: CORS });

    let target;
    try { target = ub64(m[1]); } catch { return new Response("bad", { status: 400, headers: CORS }); }
    if (!/^https?:\/\//i.test(target)) return new Response("bad", { status: 400, headers: CORS });
    if (!timingSafeEq(await sign(secret, target), m[2])) return new Response("forbidden", { status: 403, headers: CORS });

    const hdrs = { "User-Agent": "Mozilla/5.0", "Accept": "*/*" };
    const range = request.headers.get("Range");
    if (range) hdrs["Range"] = range;

    let up;
    try {
      up = await fetch(fetchableUrl(target), { headers: hdrs, redirect: "follow", cf: { cacheTtl: 0 } });
    } catch (e) {
      return new Response("upstream: " + e.message, { status: 502, headers: CORS });
    }

    const ct = (up.headers.get("content-type") || "").toLowerCase();
    const isPlaylist = ct.includes("mpegurl") || /\.m3u8(\?|$)/i.test(target);
    if (isPlaylist && up.ok) {
      const text = await up.text();
      if (text.trimStart().startsWith("#EXTM3U")) {
        // כתובת הבסיס: אחרי הפניות (redirect) — לפי הכתובת הסופית, אבל עם ה-IP המקורי
        const base = up.url && !up.url.includes(".sslip.io") ? up.url : target;
        const body = await rewritePlaylist(text, base, secret, u.origin);
        return new Response(body, { status: 200, headers: {
          ...CORS, "Content-Type": "application/vnd.apple.mpegurl", "Cache-Control": "no-cache" } });
      }
      return new Response(text, { status: up.status, headers: { ...CORS, "Content-Type": ct || "text/plain" } });
    }

    const out = new Headers(CORS);
    for (const h of ["content-type", "content-length", "content-range", "accept-ranges"]) {
      const v = up.headers.get(h); if (v) out.set(h, v);
    }
    if (!out.has("content-type")) out.set("content-type", "video/mp2t");
    out.set("Cache-Control", "no-cache");
    return new Response(request.method === "HEAD" ? null : up.body, { status: up.status, headers: out });
  },
};
