/* ZOVEX · zv-auth — חתימת בקשות בסגנון MSL (אתר + פאנל).
   מפתח ECDH P-256 שלא ניתן לייצוא נשמר ב-IndexedDB; מפתח ה-HMAC המשותף נגזר
   (ECDH+HKDF) ואף פעם לא עובר ברשת. כל בקשה מוגנת נחתמת עם זמן + nonce. */
(function () {
  if (window.__zvAuth) return; window.__zvAuth = true;
  const ORIG = window.fetch.bind(window);
  const enc = new TextEncoder();
  const b64u = b => btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const ub64 = s => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), c => c.charCodeAt(0));
  const ADMIN = ["/content/mutate", "/content/save", "/content/relink"];
  function protectedPath(m, p) {
    if (p.startsWith("/content")) return m === "GET" && !ADMIN.includes(p);
    return p === "/feedback/send" || p === "/feedback/mine" || p.startsWith("/api/progress") ||
      p.startsWith("/api/history") || p.startsWith("/api/favorites") || p === "/api/refresh-stream";
  }

  // ── IndexedDB (CryptoKey נשמר כאובייקט, נשאר non-extractable) ──
  function db() {
    return new Promise((res, rej) => { const r = indexedDB.open("zv-auth", 1);
      r.onupgradeneeded = () => r.result.createObjectStore("s");
      r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
  }
  async function idb(op, val) {
    try { const d = await db(); return await new Promise((res, rej) => {
      const tx = d.transaction("s", op === "get" ? "readonly" : "readwrite"), st = tx.objectStore("s");
      const r = op === "get" ? st.get("cur") : op === "del" ? st.delete("cur") : st.put(val, "cur");
      r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); }); } catch { return null; }
  }

  let mem = null, pending = null;
  async function turnstile() {
    try {
      const cfg = await (await ORIG("/api/auth/config", { cache: "no-store" })).json();
      if (!cfg.turnstile_sitekey) return "";
      if (!window.turnstile) await new Promise((res, rej) => { const s = document.createElement("script");
        s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"; s.async = true;
        s.onload = res; s.onerror = rej; document.head.appendChild(s); });
      const box = document.createElement("div"); box.style.cssText = "position:fixed;bottom:0;left:0;z-index:2147483647";
      document.body.appendChild(box);
      return await new Promise(res => { const t = setTimeout(() => res(""), 20000);
        window.turnstile.render(box, { sitekey: cfg.turnstile_sitekey, size: "flexible", appearance: "interaction-only",
          callback: tok => { clearTimeout(t); setTimeout(() => box.remove(), 500); res(tok); },
          "error-callback": () => { clearTimeout(t); box.remove(); res(""); } }); });
    } catch { return ""; }
  }
  async function handshake() {
    const kp = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, false, ["deriveBits"]);
    const pub = b64u(await crypto.subtle.exportKey("raw", kp.publicKey));
    const ts = await turnstile();
    const r = await ORIG("/api/auth/session", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pub, plat: "web", turnstile: ts }) });
    if (!r.ok) throw new Error("auth " + r.status);
    const d = await r.json();
    const spub = await crypto.subtle.importKey("raw", ub64(d.spub), { name: "ECDH", namedCurve: "P-256" }, false, []);
    const bits = await crypto.subtle.deriveBits({ name: "ECDH", public: spub }, kp.privateKey, 256);
    const hk = await crypto.subtle.importKey("raw", bits, "HKDF", false, ["deriveKey"]);
    const key = await crypto.subtle.deriveKey({ name: "HKDF", hash: "SHA-256", salt: enc.encode(d.sid), info: enc.encode("zovex-v1") },
      hk, { name: "HMAC", hash: "SHA-256", length: 256 }, false, ["sign"]);
    const s = { sid: d.sid, exp: d.exp * 1000, key };
    await idb("put", s); return s;
  }
  async function session(force) {
    if (!force && mem && mem.exp - Date.now() > 120000) return mem;
    if (!force && !mem) { const s = await idb("get"); if (s && s.key && s.exp - Date.now() > 120000) return (mem = s); }
    if (!pending) pending = handshake().then(s => (mem = s)).finally(() => { pending = null; });
    return pending;
  }
  async function sign(s, method, pathq) {
    const t = String(Date.now()), n = b64u(crypto.getRandomValues(new Uint8Array(12)));
    const sig = b64u(await crypto.subtle.sign("HMAC", s.key, enc.encode(`${method}\n${pathq}\n${t}\n${n}`)));
    return { "X-ZV-S": s.sid, "X-ZV-T": t, "X-ZV-N": n, "X-ZV-Sig": sig };
  }
  async function zvFetch(input, init) {
    let url, method;
    try { url = new URL(input instanceof Request ? input.url : String(input), location.href);
      method = String((init && init.method) || (input instanceof Request ? input.method : "GET")).toUpperCase();
    } catch { return ORIG(input, init); }
    if (url.origin !== location.origin || !protectedPath(method, url.pathname)) return ORIG(input, init);
    const go = async force => {
      let s; try { s = await session(force); } catch { return ORIG(input, init); }
      const h = new Headers((init && init.headers) || (input instanceof Request ? input.headers : undefined));
      const add = await sign(s, method, url.pathname + url.search);
      for (const k in add) h.set(k, add[k]);
      return ORIG(input instanceof Request ? new Request(input, { headers: h }) : input, { ...(init || {}), headers: h });
    };
    let r = await go(false);
    if (r.status === 401) {
      const d = await r.clone().json().catch(() => ({}));
      if (d.zv === "reauth") { mem = null; await idb("del"); r = await go(true); }
    }
    return r;
  }
  window.fetch = zvFetch;
  window.zvAuth = { session, sign, protectedPath };
})();
