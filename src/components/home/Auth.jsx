import React from "react";

// ─── Google Auth (Google Identity Services — השיטה הרשמית והמאובטחת) ─
// חשוב: יש להחליף כאן ב-Client ID אמיתי מ-Google Cloud Console (OAuth Client ID → Web application)
const GOOGLE_CLIENT_ID = "537028202942-tra1klpqsbu6uo475gshp5r43m68h47m.apps.googleusercontent.com";

function loadGoogleScript() {
  return new Promise((resolve, reject) => {
    if (window.google?.accounts?.oauth2) return resolve();
    const existing = document.getElementById("google-identity-script");
    if (existing) {
      existing.addEventListener("load", () => resolve());
      return;
    }
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.id = "google-identity-script";
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = reject;
    document.head.appendChild(script);
  });
}

// ─── שימו לב ─────────────────────────────────────────────────
// עברנו מ-"One Tap" (החלון הקטן שקופץ בפינה ולפעמים נחסם ע"י הדפדפן
// ולא מוצג לכל המשתמשים) ל-OAuth הרשמי של גוגל (initTokenClient).
// זה פותח חלון אמיתי ומלא של גוגל — בחירת חשבון + כפתור "המשך" —
// בדיוק כמו בכל אתר "רגיל", ותמיד נפתח בלחיצה (לא תלוי בחסימות דפדפן).
function useGoogleAuth() {
  const [user, setUser] = React.useState(() => {
    try {
      const saved = localStorage.getItem("zovex_user");
      return saved ? JSON.parse(saved) : null;
    } catch { return null; }
  });
  const [skipped, setSkipped] = React.useState(() => {
    try { return localStorage.getItem("zovex_skipped") === "1"; } catch { return false; }
  });
  const [googleReady, setGoogleReady] = React.useState(false);
  const tokenClientRef = React.useRef(null);

  const applyUser = React.useCallback((userData) => {
    try { localStorage.setItem("zovex_user", JSON.stringify(userData)); } catch {}
    setUser(userData);
    setSkipped(false);
    try { localStorage.removeItem("zovex_skipped"); } catch {}
  }, []);

  const handleTokenResponse = React.useCallback(async (response) => {
    if (!response || response.error || !response.access_token) return;
    try {
      const res = await fetch("https://www.googleapis.com/oauth2/v3/userinfo", {
        headers: { Authorization: `Bearer ${response.access_token}` },
      });
      if (!res.ok) return;
      const profile = await res.json();
      applyUser({ id: profile.sub, name: profile.name, email: profile.email, picture: profile.picture });
    } catch {}
  }, [applyUser]);

  // טען את ספריית Google וברגע שהיא מוכנה — הכן את חלון ההתחברות המלא
  React.useEffect(() => {
    loadGoogleScript().then(() => {
      if (!window.google?.accounts?.oauth2) return;
      tokenClientRef.current = window.google.accounts.oauth2.initTokenClient({
        client_id: GOOGLE_CLIENT_ID,
        scope: "openid email profile",
        callback: handleTokenResponse,
      });
      setGoogleReady(true);
    }).catch(() => {});
  }, [handleTokenResponse]);

  const loginWithGoogle = () => {
    // פותח חלון גוגל מלא ורגיל: בחירת חשבון → "המשך" → חוזר לאתר
    tokenClientRef.current?.requestAccessToken({ prompt: "select_account" });
  };

  const logout = () => {
    try { localStorage.removeItem("zovex_user"); localStorage.removeItem("zovex_skipped"); } catch {}
    setUser(null); setSkipped(false);
  };

  const skip = () => {
    try { localStorage.setItem("zovex_skipped", "1"); } catch {}
    setSkipped(true);
  };

  return { user, skipped, loginWithGoogle, logout, skip, googleReady };
}

function LandingScreen({ onSkip, onLogin }) {
  return (
    <div style={{ minHeight: "100vh", background: "#fff", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 24, direction: "rtl", fontFamily: "Arial,sans-serif" }}>
      <div style={{ textAlign: "center", marginBottom: 40 }}>
        <h1 style={{ color: "#e50914", fontSize: 42, fontWeight: 900, margin: "0 0 8px", letterSpacing: 2 }}>ZOVEX</h1>
        <p style={{ color: "#666", fontSize: 16, margin: 0 }}>צפייה ישירה בסרטים וסדרות</p>
      </div>

      <div style={{ background: "#f9f9f9", borderRadius: 20, padding: 28, maxWidth: 380, width: "100%", marginBottom: 24, border: "1px solid #eee" }}>
        <h2 style={{ fontSize: 17, fontWeight: 800, margin: "0 0 16px", color: "#111" }}>התחבר לקבל יותר</h2>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {[
            { icon: "▶️", title: "המשך צפייה", desc: "חזור בדיוק למקום שעצרת" },
            { icon: "📋", title: "היסטוריית צפייה", desc: "ראה מה צפית לאחרונה" },
            { icon: "⚡", title: "חוויה אישית", desc: "המלצות שמותאמות לך" },
          ].map((f, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <span style={{ fontSize: 22, flexShrink: 0 }}>{f.icon}</span>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: "#111" }}>{f.title}</div>
                <div style={{ fontSize: 12, color: "#888" }}>{f.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <button onClick={onLogin} style={{ width: "100%", maxWidth: 380, background: "#fff", color: "#444", border: "1.5px solid #ddd", borderRadius: 14, padding: 14, fontSize: 15, fontWeight: 700, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 10, marginBottom: 12, fontFamily: "inherit", boxShadow: "0 2px 8px rgba(0,0,0,.08)" }}>
        <svg width="20" height="20" viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.2l6.7-6.7C35.7 2.4 30.2 0 24 0 14.8 0 6.9 5.4 2.8 13.3l7.8 6.1C12.5 13 17.8 9.5 24 9.5z"/><path fill="#4285F4" d="M46.6 24.5c0-1.6-.1-3.1-.4-4.5H24v8.5h12.7c-.5 2.9-2.2 5.3-4.7 6.9l7.3 5.7c4.3-4 6.3-9.9 7.3-16.6z"/><path fill="#FBBC05" d="M10.6 28.6A14.7 14.7 0 0 1 9.5 24c0-1.6.3-3.2.8-4.6L2.5 13.3A23.8 23.8 0 0 0 0 24c0 3.8.9 7.4 2.5 10.6l8.1-6z"/><path fill="#34A853" d="M24 48c6.2 0 11.4-2 15.2-5.5l-7.3-5.7c-2 1.4-4.6 2.2-7.9 2.2-6.2 0-11.5-4.2-13.4-9.9l-7.9 6.1C6.9 42.6 14.8 48 24 48z"/><path fill="none" d="M0 0h48v48H0z"/></svg>
        התחבר עם Google
      </button>

      <button onClick={onSkip} style={{ width: "100%", maxWidth: 380, background: "none", color: "#999", border: "none", borderRadius: 14, padding: 12, fontSize: 14, cursor: "pointer", fontFamily: "inherit" }}>
        דלג — צפה בלי חשבון
      </button>
      <p style={{ fontSize: 11, color: "#ccc", marginTop: 16, textAlign: "center" }}>דלג = ללא המשך צפייה והיסטוריה</p>
    </div>
  );
}

export { useGoogleAuth, LandingScreen };
