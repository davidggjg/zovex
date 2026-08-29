// ─────────────────────────────────────────────────────────────────────────
// מגלה את כתובות ה-API של לוח השידורים של HOT, מתוך הדפדפן.
//
// למה צריך את זה: hot.net.il מחזיר 302 לדף הבית לכל גישה שאינה דפדפן
// אמיתי — כולל robots.txt — כך שאי אפשר לגלות מבחוץ באילו כתובות הדף
// משתמש. הסקריפט הזה קורא את זה מתוך הדפדפן עצמו, שם המידע כבר קיים.
//
// איך זה עובד: performance.getEntriesByType('resource') מחזיק את *כל*
// הבקשות שהדף כבר ביצע מאז שנטען — גם לפני שהודבק הסקריפט. לכן אין צורך
// לרענן. בנוסף מותקנת האזנה ל-fetch ול-XHR כדי לתפוס בקשות עתידיות
// (למשל כשמחליפים יום או ערוץ).
//
// אחר כך הוא מנסה למשוך כל כתובת חשודה ולבדוק אם חוזר JSON, ומדפיס את
// המפתחות העליונים — כדי שאפשר יהיה לכתוב את הקוצר האמיתי בלי ניחושים.
//
// שימוש: פותחים את דף לוח השידורים של HOT → Console → מדביקים → Run.
// ─────────────────────────────────────────────────────────────────────────
(async () => {
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;inset:0;z-index:2147483647;background:#000;color:#0f0;' +
    'font:13px/1.45 monospace;padding:12px;overflow:auto;direction:ltr;white-space:pre-wrap';
  document.body.appendChild(box);
  const out = [];
  const say = t => { box.textContent = t; };

  // ── 1 · אוספים כתובות ────────────────────────────────────────────────
  const seen = new Set();
  const SKIP = /\.(png|jpe?g|gif|webp|svg|ico|css|woff2?|ttf|mp4|m3u8|ts)(\?|$)|google|gtag|gtm|facebook|doubleclick|hotjar|analytics|sentry|cdn-cgi/i;
  const KEEP = /api|json|graphql|schedule|guide|epg|program|broadcast|channel|lineup|listing|tvguide|luach/i;

  const add = u => {
    try { u = new URL(u, location.href).href; } catch { return; }
    if (SKIP.test(u) || !KEEP.test(u)) return;
    seen.add(u);
  };

  performance.getEntriesByType('resource').forEach(e => add(e.name));

  const of = window.fetch;
  window.fetch = function (i, ...r) { add(typeof i === 'string' ? i : (i && i.url) || ''); return of.apply(this, [i, ...r]); };
  const ox = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (m, u, ...r) { add(u); return ox.apply(this, [m, u, ...r]); };

  say(`נמצאו ${seen.size} כתובות חשודות.\n\nאם המספר קטן — החלף יום או ערוץ בלוח,\nוהרץ שוב. אחרת: ממתין 6 שניות ומתחיל לבדוק…`);
  await new Promise(s => setTimeout(s, 6000));

  // ── 2 · בודקים איזו מהן מחזירה JSON ─────────────────────────────────
  const urls = [...seen].slice(0, 30);
  out.push(`HOT · נבדקו ${urls.length} כתובות`, '');
  let hits = 0;

  for (const u of urls) {
    let line = u.length > 150 ? u.slice(0, 150) + '…' : u;
    try {
      const r = await fetch(u, { credentials: 'include' });
      const ct = (r.headers.get('content-type') || '').split(';')[0];
      const txt = await r.text();
      const isJson = /json/i.test(ct) || /^[\s]*[[{]/.test(txt);
      out.push(`${r.status} ${isJson ? 'JSON' : ct || '?'} ${txt.length}B`);
      out.push('  ' + line);
      if (isJson) {
        hits++;
        try {
          const j = JSON.parse(txt);
          const keys = Array.isArray(j) ? `array[${j.length}] of ${Object.keys(j[0] || {}).slice(0, 12)}`
                                        : Object.keys(j).slice(0, 14).join(',');
          out.push('  keys: ' + keys);
        } catch { /* לא JSON תקין */ }
        out.push('  ' + txt.slice(0, 220).replace(/\s+/g, ' '));
      }
      out.push('');
    } catch (e) {
      out.push(`ERR ${e.name}`, '  ' + line, '');
    }
    await new Promise(s => setTimeout(s, 150));
  }

  out.unshift(`✅ ${hits} כתובות מחזירות JSON`, '');
  const text = out.join('\n');
  say(text);

  // ── 3 · מקלים על ההעתקה ─────────────────────────────────────────────
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.cssText = 'width:100%;height:150px;margin-top:14px;background:#111;color:#0f0;font:12px monospace';
  box.appendChild(ta);
  const btn = document.createElement('button');
  btn.textContent = '📋 העתק הכל';
  btn.style.cssText = 'display:block;margin:10px 0;padding:12px 18px;font-size:16px';
  btn.onclick = () => { ta.select(); document.execCommand('copy'); btn.textContent = '✓ הועתק'; };
  box.insertBefore(btn, ta);
})();
