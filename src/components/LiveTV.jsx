import { useState, useEffect, useMemo, useRef } from "react";

// ── דף השידורים החי (מדריך TV) ───────────────────────────────────────────
// טאבים לפי קטגוריה, רשימת ערוצים, כפתור "פליי" גדול (פותח את הנגן הקיים),
// ומתחת — "עכשיו / הבא" + לוח מלא של הערוץ הנבחר, עם כפתור "הזכר לי".
// הלוח נמשך מ-/epg.json (נבנה בשרת כל שעתיים). הזמנים שם הם epoch שניות.

const CATS = [
  ["הכל", () => true],
  ["חדשות וערוצים", n => /קשת|רשת|כאן|מכאן|ערוץ 9|ערוץ 14|ערוץ 24|ערוץ 98|הכנסת|c14|i24/i.test(n)],
  ["דרמות טורקיות", n => /טורקי|ויוה|viva/i.test(n)],
  ["yes", n => /yes/i.test(n)],
  ["HOT", n => /hot|הוט/i.test(n)],
  ["ספורט", n => /ספורט|sport|one|יורוספורט|eurosport/i.test(n)],
  ["ילדים", n => /ניק|ניקל|הופ|לולי|ג'?וניור|גוניור|baby|בייבי|דיסני|דסני|זום|wiz|קריוקי|סלקום|טין/i.test(n)],
  ["דוקו ולייף", n => /discovery|דיסקברי|national|נשיונל|history|היסטור|food|אוכל|בריאות|health|חיים טובים|good|ים תיכוני|e!/i.test(n)],
  ["סרטים ובידור", n => /cinema|סינמה|movies|סרטים|bolly|הודי|קומדי|comedy|דרמה|drama|action|אקשן|קולנוע|בידור/i.test(n)],
];

const catOf = (name) => (CATS.find(([, m], i) => i > 0 && m(name || "")) || CATS[0])[0];

// now/next מתוך מערך תוכניות (ממויין לפי start)
function nowNext(programs) {
  const t = Date.now() / 1000;
  let now = null, next = null;
  for (const p of programs) {
    if (p.start <= t && t < p.end) now = p;
    else if (p.start > t && !next) next = p;
  }
  return { now, next };
}

const fmt = (ep) =>
  new Date(ep * 1000).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });

// מפתח slug לערוץ (כמו ש-Home מחשב) — כדי להתאים ל-epg.json
const chSlug = (ch) =>
  ch.custom_slug || encodeURIComponent((ch.title || ch.name || "").replace(/ /g, "-"));

// "הזכר לי" — באפליקציה (WebView) שולח לנייטיב; בדפדפן התראה מקומית (כל עוד פתוח)
function remind(program, channelTitle) {
  const when = program.start * 1000;
  if (when - Date.now() < 0) return;
  const bridge = window.ReactNativeWebView;
  if (bridge && bridge.postMessage) {
    bridge.postMessage(JSON.stringify({
      type: "remind", at: program.start, title: channelTitle, program: program.title,
    }));
    return "sent";
  }
  if ("Notification" in window) {
    const arm = () => {
      const ms = when - Date.now();
      if (ms > 0 && ms < 24 * 3600 * 1000) {
        setTimeout(() => {
          try { new Notification(`מתחיל עכשיו: ${program.title}`, { body: channelTitle }); } catch {}
        }, ms);
      }
    };
    if (Notification.permission === "granted") { arm(); return "armed"; }
    if (Notification.permission !== "denied") {
      Notification.requestPermission().then(p => { if (p === "granted") arm(); });
      return "armed";
    }
  }
  return "unsupported";
}

export default function LiveTV({ channels = [], onPlay, onClose, initialSlug, isDesktop }) {
  const [epg, setEpg] = useState(null);
  const [cat, setCat] = useState("הכל");
  const [selSlug, setSelSlug] = useState(initialSlug || null);
  const [reminded, setReminded] = useState({});
  const listRef = useRef(null);

  useEffect(() => {
    let live = true;
    fetch("/epg.json").then(r => r.ok ? r.json() : null)
      .then(d => { if (live && d && d.channels) setEpg(d.channels); })
      .catch(() => {});
    return () => { live = false; };
  }, []);

  // ריענון "עכשיו/הבא" כל דקה בלי למשוך מחדש
  const [, tick] = useState(0);
  useEffect(() => { const id = setInterval(() => tick(x => x + 1), 60000); return () => clearInterval(id); }, []);

  const shown = useMemo(
    () => channels.filter(c => cat === "הכל" || catOf(c.title || c.name) === cat),
    [channels, cat]
  );

  const selected = useMemo(
    () => channels.find(c => chSlug(c) === selSlug) || shown[0] || channels[0],
    [channels, selSlug, shown]
  );

  const selProgs = (epg && selected && epg[chSlug(selected)]?.programs) || [];
  const { now, next } = nowNext(selProgs);
  const upcoming = selProgs.filter(p => p.end > Date.now() / 1000);

  const wrap = { minHeight: "100vh", background: "#0a0a0a", color: "#fff", fontFamily: "Arial, sans-serif", direction: "rtl" };
  const bell = (p) => {
    const key = chSlug(selected) + p.start;
    const done = reminded[key];
    return (
      <button
        onClick={() => { const r = remind(p, selected.title || selected.name); if (r) setReminded(s => ({ ...s, [key]: true })); }}
        style={{
          background: done ? "#e50914" : "transparent", color: "#fff",
          border: "1px solid " + (done ? "#e50914" : "#444"), borderRadius: 6,
          padding: "4px 10px", fontSize: 12, cursor: "pointer", whiteSpace: "nowrap",
        }}
        title="הזכר לי כשמתחיל"
      >{done ? "✓ יזכיר" : "🔔 הזכר לי"}</button>
    );
  };

  return (
    <div style={wrap}>
      {/* כותרת */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px", borderBottom: "1px solid #1c1c1c", position: "sticky", top: 0, background: "#0a0a0a", zIndex: 5 }}>
        <button onClick={onClose} style={{ background: "none", border: "none", color: "#fff", fontSize: 24, cursor: "pointer" }}>→</button>
        <span style={{ fontSize: 20, fontWeight: 800 }}>📺 שידורים חיים</span>
      </div>

      {/* טאבים של קטגוריות */}
      <div style={{ display: "flex", gap: 8, overflowX: "auto", padding: "12px 18px", WebkitOverflowScrolling: "touch" }}>
        {CATS.map(([c]) => (
          <button key={c} onClick={() => setCat(c)}
            style={{
              background: cat === c ? "#e50914" : "#1a1a1a", color: "#fff",
              border: "none", borderRadius: 20, padding: "7px 16px", fontSize: 14,
              fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap",
            }}>{c}</button>
        ))}
      </div>

      <div style={{ display: isDesktop ? "flex" : "block", gap: 20, padding: "8px 18px 40px", alignItems: "flex-start" }}>
        {/* רשימת ערוצים */}
        <div ref={listRef} style={{ flex: isDesktop ? "0 0 320px" : "unset", display: "grid", gridTemplateColumns: isDesktop ? "1fr" : "repeat(auto-fill,minmax(120px,1fr))", gap: 10, marginBottom: 20 }}>
          {shown.map(ch => {
            const on = selected && chSlug(ch) === chSlug(selected);
            const prog = (epg && epg[chSlug(ch)]?.programs) || [];
            const cur = nowNext(prog).now;
            return (
              <button key={chSlug(ch)} onClick={() => setSelSlug(chSlug(ch))}
                style={{
                  display: "flex", alignItems: "center", gap: 10, textAlign: "right",
                  background: on ? "#181818" : "#111", border: "1px solid " + (on ? "#e50914" : "#222"),
                  borderRadius: 10, padding: 8, cursor: "pointer", color: "#fff",
                }}>
                <img src={ch.thumbnail_url} alt="" style={{ width: 46, height: 46, borderRadius: 8, objectFit: "cover", background: "#000", flexShrink: 0 }}
                  onError={e => { e.target.style.visibility = "hidden"; }} />
                <span style={{ overflow: "hidden" }}>
                  <span style={{ display: "block", fontWeight: 700, fontSize: 14, whiteSpace: "nowrap", textOverflow: "ellipsis", overflow: "hidden" }}>{ch.title || ch.name}</span>
                  {cur && <span style={{ display: "block", fontSize: 12, color: "#e50914", whiteSpace: "nowrap", textOverflow: "ellipsis", overflow: "hidden" }}>{cur.title}</span>}
                </span>
              </button>
            );
          })}
        </div>

        {/* פאנל הערוץ הנבחר */}
        {selected && (
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 14 }}>
              <img src={selected.thumbnail_url} alt="" style={{ width: 64, height: 64, borderRadius: 10, objectFit: "cover", background: "#000" }}
                onError={e => { e.target.style.visibility = "hidden"; }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 22, fontWeight: 800 }}>{selected.title || selected.name}</div>
                {now
                  ? <div style={{ fontSize: 14, color: "#bbb" }}>עכשיו: <b style={{ color: "#fff" }}>{now.title}</b> · {fmt(now.start)}-{fmt(now.end)}</div>
                  : <div style={{ fontSize: 14, color: "#777" }}>אין מידע על השידור הנוכחי</div>}
              </div>
              <button onClick={() => onPlay(selected)}
                style={{ background: "#e50914", color: "#fff", border: "none", borderRadius: 8, padding: "12px 22px", fontSize: 16, fontWeight: 800, cursor: "pointer", whiteSpace: "nowrap" }}>
                ▶ צפה
              </button>
            </div>

            {next && (
              <div style={{ fontSize: 13, color: "#999", marginBottom: 16 }}>
                הבא: <b style={{ color: "#ccc" }}>{next.title}</b> · {fmt(next.start)}
              </div>
            )}

            {/* לוח מלא */}
            <div style={{ fontSize: 15, fontWeight: 800, margin: "6px 0 10px" }}>לוח שידורים</div>
            {upcoming.length === 0 ? (
              <div style={{ color: "#777", fontSize: 14, padding: "10px 0" }}>אין לוח שידורים זמין לערוץ זה.</div>
            ) : (
              <div>
                {upcoming.map((p, i) => {
                  const isNow = now && p.start === now.start;
                  return (
                    <div key={p.start + "_" + i}
                      style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 8px", borderBottom: "1px solid #171717", background: isNow ? "rgba(229,9,20,0.08)" : "transparent" }}>
                      <span style={{ fontVariantNumeric: "tabular-nums", color: isNow ? "#e50914" : "#888", fontWeight: 700, fontSize: 14, width: 48, flexShrink: 0 }}>{fmt(p.start)}</span>
                      <span style={{ flex: 1, minWidth: 0 }}>
                        <span style={{ display: "block", fontSize: 14, fontWeight: isNow ? 800 : 600 }}>{p.title || "—"}</span>
                        {p.desc && <span style={{ display: "block", fontSize: 12, color: "#888", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.desc}</span>}
                      </span>
                      {isNow ? <span style={{ color: "#e50914", fontSize: 12, fontWeight: 800 }}>● עכשיו</span> : bell(p)}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
