import { ArrowRight, Play, Bell, BellRing } from "lucide-react";
import { useEffect, useState } from "react";

// ── דף ערוץ שידור חי ─────────────────────────────────────────────────────
// אותו מבנה כמו דף סרט: תמונה למעלה, שם, כפתור צפייה — ומתחת לוח השידורים
// של *הערוץ הזה בלבד*: מה משודר עכשיו, ומה עומד לשדר.
//
// הלוח נמשך מ-/epg.json (נבנה בשרת כל שעתיים). לא לכל ערוץ יש לוח — ערוצי
// VOD וסרטים רצופים אין להם לוח לינארי מטבעם — ובמקרה כזה הדף פשוט מציג
// את הערוץ בלי החלק התחתון, במקום להציג "אין מידע" מיותר.

const fmt = (ep) =>
  new Date(ep * 1000).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });

const chSlug = (ch) =>
  (ch && (ch.custom_slug ||
    encodeURIComponent((ch.title || ch.name || "").replace(/ /g, "-")))) || "";

// "הזכר לי": באפליקציה נשלח לצד הנייטיב שיתזמן התראה; בדפדפן מתוזמנת
// התראה מקומית שתעבוד כל עוד הלשונית פתוחה.
function remind(program, channelTitle) {
  const when = program.start * 1000;
  if (when <= Date.now()) return false;
  const bridge = typeof window !== "undefined" && window.ReactNativeWebView;
  if (bridge && bridge.postMessage) {
    bridge.postMessage(JSON.stringify({
      type: "remind", at: program.start,
      channel: channelTitle, program: program.title,
    }));
    return true;
  }
  if (typeof Notification === "undefined") return false;
  const arm = () => {
    const ms = when - Date.now();
    if (ms > 0 && ms < 24 * 3600 * 1000) {
      setTimeout(() => {
        try { new Notification(`מתחיל עכשיו: ${program.title}`, { body: channelTitle }); }
        catch { /* הדפדפן חסם — אין מה לעשות */ }
      }, ms);
    }
  };
  if (Notification.permission === "granted") { arm(); return true; }
  if (Notification.permission !== "denied") {
    Notification.requestPermission().then(p => { if (p === "granted") arm(); });
    return true;
  }
  return false;
}

export default function LiveTV({ channel, onPlay, onClose }) {
  const [programs, setPrograms] = useState(null);   // null = עדיין טוען
  const [reminded, setReminded] = useState({});
  const [, tick] = useState(0);

  useEffect(() => {
    let alive = true;
    fetch("/epg.json")
      .then(r => (r.ok ? r.json() : null))
      .then(d => {
        if (!alive) return;
        const entry = d && d.channels && d.channels[chSlug(channel)];
        setPrograms((entry && entry.programs) || []);
      })
      .catch(() => alive && setPrograms([]));
    return () => { alive = false; };
  }, [channel]);

  // מרענן "עכשיו/הבא" בלי למשוך שוב
  useEffect(() => {
    const id = setInterval(() => tick(x => x + 1), 60000);
    return () => clearInterval(id);
  }, []);

  const now = Date.now() / 1000;
  const list = programs || [];
  const current = list.find(p => p.start <= now && now < p.end);
  const upcoming = list.filter(p => p.end > now);
  const title = channel?.title || channel?.name || "שידור חי";

  return (
    <div style={{ background: "#111", minHeight: "100vh", direction: "rtl", fontFamily: "Arial, sans-serif", color: "#fff" }}>
      <button onClick={onClose} aria-label="חזרה"
        style={{ position: "fixed", top: 15, right: 15, zIndex: 100, background: "rgba(0,0,0,.7)", border: "none", color: "#fff", borderRadius: "50%", width: 44, height: 44, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer" }}>
        <ArrowRight size={22} />
      </button>

      {/* תמונת הערוץ */}
      <div style={{ position: "relative" }}>
        {channel?.thumbnail_url
          ? <img src={channel.thumbnail_url} alt="" onError={e => { e.target.style.display = "none"; }}
              style={{ width: "100%", height: "55vw", maxHeight: 380, objectFit: "cover", display: "block" }} />
          : <div style={{ width: "100%", height: "40vw", maxHeight: 240, background: "linear-gradient(135deg,#2a2a2a,#111)" }} />}
        <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 130, background: "linear-gradient(transparent,#111)" }} />
      </div>

      <div style={{ padding: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 900, margin: "0 0 8px" }}>{title}</h1>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14, alignItems: "center" }}>
          <span style={{ background: "#e50914", color: "#fff", padding: "4px 12px", borderRadius: 20, fontSize: 12, fontWeight: "bold", display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#fff", display: "inline-block" }} />
            שידור חי
          </span>
        </div>

        {/* מה משודר עכשיו */}
        {current && (
          <div style={{ margin: "0 0 18px" }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#ddd", marginBottom: 6 }}>עכשיו משודר 📺</div>
            <div style={{ fontSize: 16, fontWeight: 800, color: "#fff" }}>{current.title}</div>
            <div style={{ fontSize: 13, color: "#e50914", marginTop: 3 }}>
              {fmt(current.start)} – {fmt(current.end)}
            </div>
            {current.desc && <p style={{ fontSize: 14, lineHeight: 1.8, color: "#bbb", margin: "8px 0 0" }}>{current.desc}</p>}
          </div>
        )}

        <button onClick={() => onPlay(channel)}
          style={{ width: "100%", background: "#e50914", color: "#fff", border: "none", padding: 16, fontSize: 17, fontWeight: "bold", borderRadius: 12, display: "flex", alignItems: "center", justifyContent: "center", gap: 10, cursor: "pointer" }}>
          <Play fill="white" size={20} /> צפה בשידור החי
        </button>

        {/* לוח השידורים של הערוץ — רק אם יש */}
        {upcoming.length > 0 && (
          <div style={{ marginTop: 26 }}>
            <div style={{ fontSize: 14, fontWeight: 900, marginBottom: 12 }}>לוח שידורים</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {upcoming.slice(0, 40).map((p, i) => {
                const isNow = current && p.start === current.start;
                const key = p.start + "_" + i;
                const done = reminded[key];
                return (
                  <div key={key}
                    style={{ display: "flex", gap: 12, alignItems: "center", background: isNow ? "rgba(229,9,20,.12)" : "#1a1a1a", borderRadius: 12, padding: 10, border: "1px solid " + (isNow ? "#e50914" : "#2a2a2a") }}>
                    <span style={{ fontVariantNumeric: "tabular-nums", color: isNow ? "#e50914" : "#888", fontWeight: 800, fontSize: 14, width: 46, flexShrink: 0, textAlign: "center" }}>
                      {fmt(p.start)}
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 14, fontWeight: isNow ? 800 : 700, color: "#fff" }}>{p.title || "—"}</div>
                      {p.desc && <div style={{ fontSize: 12, color: "#888", marginTop: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.desc}</div>}
                    </div>
                    {isNow
                      ? <span style={{ color: "#e50914", fontSize: 12, fontWeight: 800, flexShrink: 0 }}>● עכשיו</span>
                      : <button
                          onClick={() => { if (remind(p, title)) setReminded(s => ({ ...s, [key]: true })); }}
                          title="הזכר לי כשמתחיל"
                          style={{ background: done ? "#e50914" : "transparent", color: "#fff", border: "1px solid " + (done ? "#e50914" : "#444"), borderRadius: 8, padding: "6px 10px", fontSize: 12, cursor: "pointer", display: "flex", alignItems: "center", gap: 5, flexShrink: 0 }}>
                          {done ? <BellRing size={13} /> : <Bell size={13} />}
                          {done ? "יזכיר" : "הזכר לי"}
                        </button>}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
