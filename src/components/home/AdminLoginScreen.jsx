import { useState } from "react";

// קודי כניסה לפאנל ניהול — מאוחסנים כ-SHA-256 hash (חד-כיווני) ולא כטקסט גלוי
const PIN_HASH = "8d969eef6ecad3c29a3a629280e686cf0c3f5d5a86aff3ca12020c923adc6c92";
const LETTER_HASH = "ec16ba3d1a06d5fc8356030cefd2cc72f654217c6260401afd25e02cac369a52";

async function sha256(text) {
  const enc = new TextEncoder().encode(text);
  const buf = await crypto.subtle.digest("SHA-256", enc);
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
}

export default function AdminLoginScreen({ onSuccess, onCancel }) {
  const [pinInput, setPinInput] = useState("");
  const [letterInput, setLetterInput] = useState("");
  const [loginError, setLoginError] = useState("");

  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "100vh", background: "#111", fontFamily: "Arial", direction: "rtl" }}>
      <div style={{ background: "#1e1e1e", padding: 40, borderRadius: 20, width: 320, boxShadow: "0 8px 40px rgba(0,0,0,.5)" }}>
        <h2 style={{ color: "#e50914", textAlign: "center", marginBottom: 28, fontSize: 22 }}>כניסת מנהל</h2>
        <div style={{ marginBottom: 16 }}>
          <label style={{ color: "#aaa", fontSize: 13, display: "block", marginBottom: 7 }}>קוד PIN</label>
          <input type="password" inputMode="numeric" value={pinInput} onChange={e => setPinInput(e.target.value)} placeholder="קוד PIN" style={{ width: "100%", padding: 12, borderRadius: 8, border: "1px solid #333", background: "#2a2a2a", color: "#fff", fontSize: 16, outline: "none", boxSizing: "border-box" }} />
        </div>
        <div style={{ marginBottom: 22 }}>
          <label style={{ color: "#aaa", fontSize: 13, display: "block", marginBottom: 7 }}>קוד אותיות</label>
          <input type="password" value={letterInput} onChange={e => setLetterInput(e.target.value.toUpperCase())} placeholder="קוד אותיות" style={{ width: "100%", padding: 12, borderRadius: 8, border: "1px solid #333", background: "#2a2a2a", color: "#fff", fontSize: 16, outline: "none", boxSizing: "border-box" }} />
        </div>
        {loginError && <p style={{ color: "#ff4d4d", textAlign: "center", marginBottom: 14, fontSize: 14 }}>{loginError}</p>}
        <button onClick={async () => {
          const [pinH, letH] = await Promise.all([sha256(pinInput), sha256(letterInput)]);
          if (pinH === PIN_HASH && letH === LETTER_HASH) onSuccess();
          else setLoginError("קודים שגויים.");
        }} style={{ width: "100%", background: "#e50914", color: "#fff", border: "none", padding: 14, borderRadius: 10, fontSize: 16, fontWeight: "bold", cursor: "pointer" }}>כניסה</button>
        <button onClick={onCancel} style={{ width: "100%", background: "none", color: "#666", border: "none", padding: 10, marginTop: 8, cursor: "pointer", fontSize: 14 }}>ביטול</button>
      </div>
    </div>
  );
}
