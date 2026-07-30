import { useState, useEffect, useRef, useCallback } from "react";
import { X, Send } from "lucide-react";
import { apiCall, ls, lsSet } from "./helpers";

// ─── תמיכה / צ'אט עם המנהלים (אתר) ────────────────────────────────────────────
// המשתמש כותב (תמיכה / חוות דעת / טיפ), המנהל רואה בפאנל ומגיב, והתשובה מופיעה
// כאן. טלגרם נשאר כאופציה. זהה בהתנהגות לצ'אט שבאפליקציה.
const DEVICE_KEY = "zovex_device_id";
const KINDS = [
  { k: "support", label: "תמיכה 💬" },
  { k: "review", label: "חוות דעת ⭐" },
  { k: "tip", label: "טיפ 💡" },
];

function resolveUserId(user) {
  if (user && user.email) return "g:" + user.email;
  let id = ls(DEVICE_KEY);
  if (!id) {
    id = "d:" + Math.random().toString(36).slice(2) + Date.now().toString(36);
    lsSet(DEVICE_KEY, id);
  }
  return id;
}

export default function SupportChat({ open, onClose, user }) {
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [kind, setKind] = useState("support");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const userIdRef = useRef(null);
  const scrollRef = useRef(null);
  const pollRef = useRef(null);

  const refresh = useCallback(async () => {
    const id = userIdRef.current;
    if (!id) return;
    const th = await apiCall(`/feedback/mine?user_id=${encodeURIComponent(id)}`, "GET");
    if (th && Array.isArray(th.messages)) setMessages(th.messages);
    setLoading(false);
  }, []);

  useEffect(() => {
    if (!open) {
      if (pollRef.current) clearInterval(pollRef.current);
      return;
    }
    userIdRef.current = resolveUserId(user);
    setLoading(true);
    refresh();
    pollRef.current = setInterval(refresh, 15000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [open, user, refresh]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages]);

  const send = useCallback(async () => {
    const t = text.trim();
    if (!t || sending) return;
    setSending(true);
    setMessages((m) => [...m, { from: "user", text: t, kind, ts: new Date().toISOString() }]);
    setText("");
    const ok = await apiCall("/feedback/send", "POST", {
      user_id: userIdRef.current, name: user?.name || "", email: user?.email || "",
      text: t, kind,
    });
    setSending(false);
    if (ok) refresh();
  }, [text, sending, kind, user, refresh]);

  if (!open) return null;
  const kindLabel = (k) => (KINDS.find((x) => x.k === k) || {}).label || "";

  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, zIndex: 10001, background: "rgba(0,0,0,0.6)", display: "flex", alignItems: "flex-end", justifyContent: "center", direction: "rtl" }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ width: "100%", maxWidth: 460, background: "#141414", borderRadius: "18px 18px 0 0", padding: "12px 14px 16px", maxHeight: "88vh", display: "flex", flexDirection: "column", boxShadow: "0 -4px 30px rgba(0,0,0,.5)" }}
      >
        {/* כותרת */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
          <button onClick={onClose} style={{ background: "none", border: "none", color: "#aaa", cursor: "pointer", padding: 4, display: "flex" }} aria-label="סגור">
            <X size={20} />
          </button>
          <div style={{ color: "#fff", fontSize: 16, fontWeight: 800 }}>תמיכה וצ'אט עם המנהלים</div>
          <div style={{ width: 22 }} />
        </div>

        {/* סוג ההודעה */}
        <div style={{ display: "flex", gap: 8, justifyContent: "center", marginBottom: 8 }}>
          {KINDS.map((x) => (
            <button
              key={x.k}
              onClick={() => setKind(x.k)}
              style={{ padding: "6px 12px", borderRadius: 16, fontSize: 13, fontWeight: 600, cursor: "pointer", border: "1px solid " + (kind === x.k ? "#e50914" : "#333"), background: kind === x.k ? "#e50914" : "#222", color: kind === x.k ? "#fff" : "#bbb" }}
            >
              {x.label}
            </button>
          ))}
        </div>

        {/* היסטוריה */}
        <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", minHeight: 140, maxHeight: "46vh", padding: "4px 2px" }}>
          {loading ? (
            <div style={{ color: "#888", textAlign: "center", padding: 30 }}>טוען…</div>
          ) : messages.length === 0 ? (
            <div style={{ color: "#888", fontSize: 14, textAlign: "center", padding: "30px 10px", lineHeight: 1.6 }}>
              כתבו לנו כל דבר — בעיה, חוות דעת או רעיון לשיפור.<br />נקרא ונחזור אליכם כאן 💙
            </div>
          ) : (
            messages.map((m, i) => {
              const mine = m.from === "user";
              return (
                <div key={i} style={{ display: "flex", justifyContent: mine ? "flex-end" : "flex-start", margin: "5px 0" }}>
                  <div style={{ maxWidth: "82%", borderRadius: 14, padding: "8px 12px", background: mine ? "#e50914" : "#262626", borderBottomRightRadius: mine ? 4 : 14, borderBottomLeftRadius: mine ? 14 : 4 }}>
                    {mine && m.kind ? <div style={{ color: "rgba(255,255,255,.75)", fontSize: 11, marginBottom: 2 }}>{kindLabel(m.kind)}</div> : null}
                    {!mine ? <div style={{ color: "#e50914", fontSize: 11, fontWeight: 700, marginBottom: 2 }}>ZOVEX · צוות</div> : null}
                    <div style={{ color: mine ? "#fff" : "#eee", fontSize: 14, lineHeight: 1.45, whiteSpace: "pre-wrap" }}>{m.text}</div>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* תיבת כתיבה */}
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end", marginTop: 8 }}>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder="כתבו הודעה…"
            rows={1}
            style={{ flex: 1, background: "#1e1e1e", border: "1px solid #2a2a2a", borderRadius: 14, color: "#fff", padding: "10px 14px", fontSize: 14, resize: "none", maxHeight: 100, outline: "none", direction: "rtl" }}
          />
          <button
            onClick={send}
            disabled={!text.trim() || sending}
            style={{ background: !text.trim() || sending ? "#3a1416" : "#e50914", border: "none", borderRadius: 14, padding: "11px 16px", color: "#fff", fontWeight: 800, cursor: !text.trim() || sending ? "default" : "pointer", display: "flex", alignItems: "center", gap: 5 }}
          >
            <Send size={15} fill="white" />
          </button>
        </div>

        {/* טלגרם כאופציה */}
        <a href="https://t.me/ZOVE8" target="_blank" rel="noreferrer" style={{ display: "block", textAlign: "center", color: "#5b9bd5", fontSize: 13, fontWeight: 600, textDecoration: "none", paddingTop: 12 }}>
          או פנו אלינו בטלגרם ➤
        </a>
      </div>
    </div>
  );
}
