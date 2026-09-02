import { useState, useEffect, useRef, useCallback } from "react";
import { X, Send as SendIcon } from "lucide-react";

// ─────────────────────────────────────────────────────────────────────────────
// צ'אט תמיכה באתר. עד עכשיו כפתור התמיכה הוביל לטלגרם, ושם אין דרך לדעת מי
// כתב: אין אימייל, אין חשבון, ואי אפשר לחסום מישהו שכותב דברים פוגעניים.
// כאן ההודעה נשלחת עם המזהה "g:<email>" — אותו פורמט שהאפליקציה שולחת, כך
// ששני הערוצים מגיעים לאותו שרשור בדשבורד — ולכן לכל הודעה יש כתובת שאפשר
// לחסום.
//
// לכן גם רק מחוברים יכולים לכתוב: בלי אימייל אין מה לחסום, וזו כל הנקודה.
// מי שאינו מחובר מקבל הסבר וקישור לקבוצת הטלגרם, שהיא ערוץ נפרד שבו יש
// שליטה משלה — ולא נכנס לתיבת התמיכה.
// ─────────────────────────────────────────────────────────────────────────────

const KINDS = [
  { k: "support", label: "תמיכה 💬" },
  { k: "review", label: "חוות דעת ⭐" },
  { k: "tip", label: "טיפ 💡" },
];

const TELEGRAM_GROUP = "https://t.me/ZOVE8";

// נקודות הקצה יושבות על אותו דומיין שממנו מוגש האתר, ולכן נתיב יחסי —
// בלי CORS ובלי תלות בכתובת חיצונית שעלולה להתיישן.
async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

export default function SupportModal({ open, onClose, user }) {
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [kind, setKind] = useState("support");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef(null);

  const userId = user?.email ? "g:" + user.email : null;

  const load = useCallback(async () => {
    if (!userId) { setLoading(false); return; }
    try {
      const d = await api(`/feedback/mine?user_id=${encodeURIComponent(userId)}`);
      setMessages(Array.isArray(d.messages) ? d.messages : []);
    } catch {
      setError("לא ניתן לטעון את השיחה כרגע");
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => { if (open) { setLoading(true); setError(""); load(); } }, [open, load]);

  // רענון בזמן שהחלון פתוח, כדי שתשובה מהמנהל תופיע בלי לרענן את הדף
  useEffect(() => {
    if (!open || !userId) return;
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [open, userId, load]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages.length]);

  const send = async () => {
    const body = text.trim();
    if (!body || !userId || sending) return;
    setSending(true);
    setError("");
    // מוסיפים מיד לתצוגה כדי שההודעה לא "תיעלם" בזמן ההמתנה לשרת
    const optimistic = { from: "user", text: body, ts: new Date().toISOString(), kind };
    setMessages(m => [...m, optimistic]);
    setText("");
    try {
      await api("/feedback/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userId, name: user.name || "", email: user.email,
          text: body, kind,
        }),
      });
      load();
    } catch {
      setError("השליחה נכשלה. נסה שוב.");
      setMessages(m => m.filter(x => x !== optimistic));
      setText(body);
    } finally {
      setSending(false);
    }
  };

  if (!open) return null;

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 400, direction: "rtl",
        background: "rgba(0,0,0,0.72)", backdropFilter: "blur(6px)",
        display: "flex", alignItems: "flex-end", justifyContent: "center",
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: "100%", maxWidth: 520, height: "min(86vh, 640px)",
          background: "linear-gradient(180deg, #15151c 0%, #0d0d12 100%)",
          borderRadius: "20px 20px 0 0", border: "1px solid rgba(255,255,255,0.09)",
          borderBottom: "none", display: "flex", flexDirection: "column", overflow: "hidden",
        }}
      >
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "14px 16px", borderBottom: "1px solid rgba(255,255,255,0.07)",
        }}>
          <div style={{ color: "#fff", fontSize: 16, fontWeight: 800 }}>תמיכה</div>
          <button onClick={onClose} aria-label="סגור" style={{
            background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: "50%", width: 32, height: 32, cursor: "pointer",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <X size={16} color="#fff" />
          </button>
        </div>

        {!userId ? (
          <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "30px 26px", textAlign: "center", gap: 12 }}>
            <div style={{ fontSize: 40 }}>🔒</div>
            <div style={{ color: "#fff", fontSize: 17, fontWeight: 800 }}>צריך להתחבר כדי לכתוב לתמיכה</div>
            <div style={{ color: "#9a9aa5", fontSize: 13, lineHeight: 1.6, maxWidth: 330 }}>
              ההתחברות מאפשרת לנו לענות לך אישית ולעקוב אחרי הפנייה. אפשר להתחבר
              מהתפריט למעלה.
            </div>
            <a href={TELEGRAM_GROUP} target="_blank" rel="noreferrer" style={{
              marginTop: 6, color: "#9ecbff", fontSize: 13, textDecoration: "none",
            }}>
              או הצטרפו לקבוצת הטלגרם ←
            </a>
          </div>
        ) : (
          <>
            <div style={{ flex: 1, overflowY: "auto", padding: "14px 14px 6px" }}>
              {loading ? (
                <div style={{ color: "#888", textAlign: "center", padding: 30, fontSize: 13 }}>טוען…</div>
              ) : messages.length === 0 ? (
                <div style={{ color: "#8a8a95", textAlign: "center", padding: "34px 20px", fontSize: 13, lineHeight: 1.7 }}>
                  אין עדיין הודעות.<br />כתבו לנו — בעיה, בקשה לסרט, או סתם חוות דעת.
                </div>
              ) : (
                messages.map((m, i) => {
                  const mine = m.from === "user";
                  return (
                    <div key={i} style={{ display: "flex", justifyContent: mine ? "flex-start" : "flex-end", marginBottom: 9 }}>
                      <div style={{
                        maxWidth: "78%", padding: "9px 13px", borderRadius: 15,
                        background: mine ? "#e50914" : "rgba(255,255,255,0.08)",
                        color: mine ? "#fff" : "#e8e8ee",
                        fontSize: 14, lineHeight: 1.5, whiteSpace: "pre-wrap", wordBreak: "break-word",
                      }}>
                        {m.text}
                      </div>
                    </div>
                  );
                })
              )}
              <div ref={endRef} />
            </div>

            {!!error && (
              <div style={{ color: "#ff8b8b", fontSize: 12, padding: "0 16px 6px" }}>{error}</div>
            )}

            <div style={{ padding: "10px 14px 16px", borderTop: "1px solid rgba(255,255,255,0.07)" }}>
              <div style={{ display: "flex", gap: 7, marginBottom: 9 }}>
                {KINDS.map(k => (
                  <button key={k.k} onClick={() => setKind(k.k)} style={{
                    padding: "6px 12px", borderRadius: 18, cursor: "pointer", fontFamily: "inherit",
                    fontSize: 12, fontWeight: 700,
                    background: kind === k.k ? "#e50914" : "rgba(255,255,255,0.06)",
                    color: kind === k.k ? "#fff" : "#a5a5b0",
                    border: "1px solid " + (kind === k.k ? "#e50914" : "rgba(255,255,255,0.1)"),
                  }}>{k.label}</button>
                ))}
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
                <textarea
                  value={text}
                  onChange={e => setText(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                  placeholder="כתבו הודעה…"
                  rows={2}
                  style={{
                    flex: 1, resize: "none", borderRadius: 14, padding: "10px 12px",
                    background: "rgba(255,255,255,0.055)", border: "1px solid rgba(255,255,255,0.11)",
                    color: "#fff", fontSize: 14, fontFamily: "inherit", outline: "none", lineHeight: 1.45,
                  }}
                />
                <button
                  onClick={send}
                  disabled={sending || !text.trim()}
                  aria-label="שלח"
                  style={{
                    width: 44, height: 44, borderRadius: "50%", flexShrink: 0, border: "none",
                    background: text.trim() ? "#e50914" : "rgba(255,255,255,0.08)",
                    cursor: text.trim() && !sending ? "pointer" : "default",
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}
                >
                  <SendIcon size={18} color="#fff" />
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
