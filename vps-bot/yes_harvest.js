// ─────────────────────────────────────────────────────────────────────────
// אוסף את לוח השידורים של yes מתוך הדפדפן, ומוריד אותו כקובץ JSON.
//
// למה מהדפדפן: svc.yes.co.il מוגן ב-Akamai ומחזיר 403 לכל גישה שאינה
// דפדפן אמיתי — נבדקו curl רגיל, curl עם עוגיות, וחיקוי טביעת TLS של
// ארבעה דפדפנים, גם משרת ישראלי. דפדפן אמיתי עם סשן פעיל עובר בקלות.
//
// שימוש: פותחים https://www.yes.co.il/content/tv/broadcast
//         → כלי פיתוח → Console → מדביקים את כל הקובץ → Run
//         בסוף יורד הקובץ yes-epg.json.
//
// עדין בכוונה: 4 בקשות במקביל עם השהיה קצרה, כדי לא להיראות כמו התקפה.
// ─────────────────────────────────────────────────────────────────────────
(async () => {
  const API = 'https://svc.yes.co.il/api/content/broadcast-schedule';
  const DAYS = 2;                 // היום + מחר
  const PAR = 4;                  // בקשות במקביל

  const box = document.createElement('pre');
  box.style.cssText = 'position:fixed;inset:0;z-index:999999;margin:0;padding:16px;' +
    'background:#000;color:#0f0;font-size:16px;overflow:auto;direction:ltr;white-space:pre-wrap';
  document.body.appendChild(box);
  const say = t => { box.textContent = t; };

  const dstr = d => `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;

  say('מביא רשימת ערוצים…');
  let channels;
  try {
    const r = await fetch(`${API}/channels?page=0&pageSize=1000`);
    channels = (await r.json()).items || [];
  } catch (e) {
    say('נכשל בהבאת רשימת הערוצים:\n' + e);
    return;
  }
  if (!channels.length) { say('הרשימה חזרה ריקה'); return; }

  const dates = [];
  for (let i = 0; i < DAYS; i++) {
    const d = new Date(); d.setDate(d.getDate() + i); dates.push(dstr(d));
  }

  const jobs = [];
  for (const c of channels) for (const d of dates) jobs.push({ c, d });

  const out = {};
  let done = 0, failed = 0;

  const worker = async () => {
    while (jobs.length) {
      const { c, d } = jobs.shift();
      const id = c.channelId;
      try {
        const r = await fetch(`${API}/channels/${id}?date=${d}&ignorePastItems=false`);
        const items = (await r.json()).items || [];
        if (items.length) {
          (out[id] = out[id] || { name: c.title, programs: [] }).programs.push(
            ...items.map(p => ({ start: p.starts, end: p.ends, title: p.title,
                                 desc: p.description || '' })));
        }
      } catch { failed++; }
      done++;
      if (done % 5 === 0 || !jobs.length) {
        say(`נאספו ${done}/${done + jobs.length}\n` +
            `ערוצים עם לוח: ${Object.keys(out).length}\n` +
            (failed ? `כשלים: ${failed}\n` : '') +
            `\nאל תסגור את הדף…`);
      }
      await new Promise(s => setTimeout(s, 120));   // עדין על השרת שלהם
    }
  };
  await Promise.all(Array.from({ length: PAR }, worker));

  // מסירים כפילויות (אותה תוכנית יכולה לחזור בין שני הימים)
  let total = 0;
  for (const id of Object.keys(out)) {
    const seen = new Set();
    out[id].programs = out[id].programs
      .filter(p => { const k = p.start + p.title; if (seen.has(k)) return false; seen.add(k); return true; })
      .sort((a, b) => (a.start < b.start ? -1 : 1));
    total += out[id].programs.length;
  }

  const blob = new Blob([JSON.stringify({ source: 'yes', generated: Date.now(), channels: out })],
                        { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'yes-epg.json';
  document.body.appendChild(a); a.click();

  say(`✅ הסתיים\n\nערוצים: ${Object.keys(out).length}\nתוכניות: ${total}\n` +
      (failed ? `כשלים: ${failed}\n` : '') +
      `\nהקובץ yes-epg.json ירד להורדות.\nאם לא — לחץ כאן:`);
  a.textContent = '⬇ הורד yes-epg.json';
  a.style.cssText = 'display:block;margin-top:20px;color:#0ff;font-size:20px';
})();
