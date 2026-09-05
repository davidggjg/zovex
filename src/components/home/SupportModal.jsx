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

export default function SupportModal({ open, onClose, user, loginWithGoogle }) {
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
          // זכוכית שקופה למחצה: הזוהר של AmbientGlow שכבר יושב מאחורי כל
          // האתר נראה דרך הכרטיס במקום שכרטיס שטוח יסתיר אותו לגמרי — אותה
          // תחושת עומק שכבר יש בשאר האתר, מורחבת לכאן.
          background: "linear-gradient(180deg, rgba(24,24,32,0.66) 0%, rgba(13,13,19,0.82) 100%)",
          backdropFilter: "blur(22px) saturate(160%)",
          WebkitBackdropFilter: "blur(22px) saturate(160%)",
          borderRadius: "20px 20px 0 0", border: "1px solid rgba(255,255,255,0.12)",
          borderBottom: "none", display: "flex", flexDirection: "column", overflow: "hidden",
          boxShadow: "0 -12px 48px rgba(0,0,0,0.55)",
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
          <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "30px 26px", textAlign: "center", gap: 14 }}>
            <div style={{ fontSize: 40 }}>🔒</div>
            <div style={{ color: "#fff", fontSize: 17, fontWeight: 800 }}>אנא התחברו עם Google כדי לכתוב לתמיכה</div>
            <div style={{ color: "#9a9aa5", fontSize: 13, lineHeight: 1.6, maxWidth: 330 }}>
              ההתחברות מאפשרת לנו לענות לכם אישית ולעקוב אחרי הפנייה.
            </div>
            {loginWithGoogle && (
              <button onClick={loginWithGoogle} style={{
                marginTop: 2, background: "#fff", color: "#3c3c3c", border: "none",
                borderRadius: 12, padding: "11px 22px", fontSize: 14, fontWeight: 700,
                cursor: "pointer", display: "flex", alignItems: "center", gap: 10,
                fontFamily: "inherit", boxShadow: "0 4px 14px rgba(0,0,0,0.3)",
              }}>
                <svg width="18" height="18" viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.2l6.7-6.7C35.7 2.4 30.2 0 24 0 14.8 0 6.9 5.4 2.8 13.3l7.8 6.1C12.5 13 17.8 9.5 24 9.5z"/><path fill="#4285F4" d="M46.6 24.5c0-1.6-.1-3.1-.4-4.5H24v8.5h12.7c-.5 2.9-2.2 5.3-4.7 6.9l7.3 5.7c4.3-4 6.3-9.9 7.3-16.6z"/><path fill="#FBBC05" d="M10.6 28.6A14.7 14.7 0 0 1 9.5 24c0-1.6.3-3.2.8-4.6L2.5 13.3A23.8 23.8 0 0 0 0 24c0 3.8.9 7.4 2.5 10.6l8.1-6z"/><path fill="#34A853" d="M24 48c6.2 0 11.4-2 15.2-5.5l-7.3-5.7c-2 1.4-4.6 2.2-7.9 2.2-6.2 0-11.5-4.2-13.4-9.9l-7.9 6.1C6.9 42.6 14.8 48 24 48z"/><path fill="none" d="M0 0h48v48H0z"/></svg>
                התחבר עם Google
              </button>
            )}
            <a href={TELEGRAM_GROUP} target="_blank" rel="noreferrer" style={{
              marginTop: loginWithGoogle ? 0 : 6, color: "#9ecbff", fontSize: 13, textDecoration: "none",
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
