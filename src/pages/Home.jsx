import React, { useState, useMemo, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Search, Send, Play, ArrowRight, X, Loader2, ChevronDown, ChevronUp, Upload, Eye } from "lucide-react";
import { Movie } from "@/entities/Movie";
import { ApiKey } from "@/entities/ApiKey";
import CustomVideoPlayer from "@/components/home/CustomVideoPlayer.jsx";

// ─── constants ────────────────────────────────────────────────
const SECRET_TRIGGER = "ZovexAdmin2026";
const BACKEND_URL = "https://davidhzhdhd-my-telegram-bot.hf.space";

// ─── Backend API helpers ──────────────────────────────
async function apiCall(path, method = "GET", body = null, userId = null) {
  try {
    const headers = { "Content-Type": "application/json" };
    if (userId) headers["x-user-id"] = userId;
    const res = await fetch(`${BACKEND_URL}${path}`, {
      method, headers,
      body: body ? JSON.stringify(body) : undefined
    });
    if (!res.ok) {
      console.warn(`[zovex] apiCall ${method} ${path} → HTTP ${res.status}. הבקאש (${BACKEND_URL}) לא מחזיר תשובה תקינה — היסטוריה/המשך צפייה לא יישמרו.`);
      return null;
    }
    return await res.json();
  } catch (e) {
    console.warn(`[zovex] apiCall ${method} ${path} נכשל — הבקאש (${BACKEND_URL}) כנראה לא זמין/ישן/חסום ע"י CORS. שגיאה:`, e);
    return null;
  }
}
// קודי כניסה לפאנל ניהול — מאוחסנים כ-SHA-256 hash (חד-כיווני) ולא כטקסט גלוי
const PIN_HASH = "8d969eef6ecad3c29a3a629280e686cf0c3f5d5a86aff3ca12020c923adc6c92";
const LETTER_HASH = "ec16ba3d1a06d5fc8356030cefd2cc72f654217c6260401afd25e02cac369a52";

async function sha256(text) {
  const enc = new TextEncoder().encode(text);
  const buf = await crypto.subtle.digest("SHA-256", enc);
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
}
const SPIN = `@keyframes spin { to { transform: rotate(360deg); } } @keyframes livePulse { 0%,100%{box-shadow:0 0 0 0 rgba(255,255,255,.7)} 50%{box-shadow:0 0 0 8px rgba(255,255,255,0)} } @keyframes livePulseDot { 0%,100%{box-shadow:0 0 0 0 rgba(229,9,20,.6)} 50%{box-shadow:0 0 0 6px rgba(229,9,20,0)} } html,body{overscroll-behavior:none;}`;

// ─── helpers ──────────────────────────────────────────────────
function ls(key, fallback = null) {
  try { const v = localStorage.getItem(key); return v !== null ? v : fallback; } catch { return fallback; }
}
function lsSet(key, val) { try { localStorage.setItem(key, val); } catch {} }
function lsDel(key) { try { localStorage.removeItem(key); } catch {} }
function lsJson(key, fallback = null) {
  try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch { return fallback; }
}

function extractVideoInfo(url) {
  if (!url) return { type: "direct", video_id: "" };
  if (url.includes("<iframe")) {
    const m = url.match(/src=["']([^"']+)['"]/);
    if (m) url = m[1];
  }
  if (!url.startsWith("http")) return { type: "direct", video_id: url };
  if (url.includes("youtube.com") || url.includes("youtu.be")) {
    const m = url.match(/(?:v=|youtu\.be\/)([^&/?]+)/);
    return { type: "youtube", video_id: m?.[1] || url };
  }
  if (url.includes("drive.google.com")) {
    const m = url.match(/\/d\/([^/]+)/);
    return { type: "drive", video_id: m?.[1] || url };
  }
  if (url.includes("vimeo.com")) {
    const m = url.match(/vimeo\.com\/(\d+)/);
    return { type: "vimeo", video_id: m?.[1] || url };
  }
  if (url.includes("dailymotion.com")) {
    const m = url.match(/video\/([^_]+)/);
    return { type: "dailymotion", video_id: m?.[1] || url };
  }
  if (url.includes("streamable.com")) {
    const m = url.match(/streamable\.com\/([^?]+)/);
    return { type: "streamable", video_id: m?.[1] || url };
  }
  if (url.includes("rumble.com")) {
    const m = url.match(/embed\/([^?/]+)/);
    return { type: "rumble", video_id: m?.[1] || url };
  }
  if (url.includes("archive.org")) {
    const m = url.match(/details\/([^?/]+)/);
    return { type: "archive", video_id: m?.[1] || url };
  }
  if (url.includes("kan.org.il")) {
    const m = url.match(/id=(\d+)/);
    return { type: "kan", video_id: m?.[1] || url };
  }
  if (url.includes("ok.ru")) {
    const m = url.match(/video\/(\d+)/);
    return { type: "okru", video_id: m?.[1] || url };
  }
  if (url.includes("t.me")) return { type: "telegram", video_id: url.replace("https://t.me/", "") };
  if (url.includes("kaltura.com") || url.match(/^\d+\/\d+\/[a-zA-Z0-9_]+$/)) {
    const m = url.match(/\/p\/(\d+).*uiconf_id\/(\d+).*entry_id=([^&]+)/);
    if (m) return { type: "kaltura", video_id: `${m[1]}/${m[2]}/${m[3]}` };
    return { type: "kaltura", video_id: url };
  }
  return { type: "direct", video_id: url };
}

// ─── HLS player (iframe-based, works on all Android browsers) ─
const HlsPlayer = ({ src }) => {
  const html = `<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{margin:0;padding:0;box-sizing:border-box;background:#000}
html,body{width:100%;height:100%;overflow:hidden}
video{width:100vw;height:100vh;object-fit:contain;display:block}
</style>
</head>
<body>
<video id="v" controls autoplay playsinline></video>
<script src="https://cdnjs.cloudflare.com/ajax/libs/hls.js/1.4.12/hls.min.js"><\/script>
<script>
var v=document.getElementById('v');
var src="${src}";
function tryPlay(){v.play&&v.play().catch(function(){});}
if(window.Hls&&Hls.isSupported()){
  var hls=new Hls({enableWorker:false,lowLatencyMode:true});
  hls.loadSource(src);
  hls.attachMedia(v);
  hls.on(Hls.Events.MANIFEST_PARSED,tryPlay);
}else if(v.canPlayType('application/vnd.apple.mpegurl')){
  v.src=src;
  v.addEventListener('loadedmetadata',tryPlay);
}
<\/script>
</body>
</html>`;
  return (
    <iframe
      srcDoc={html}
      style={{ width: "100%", height: 220, border: "none", display: "block", background: "#000", borderRadius: 10 }}
      allow="autoplay; fullscreen"
      allowFullScreen
    />
  );
};

// ─── Main component ───────────────────────────────────────────
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

export default function Home() {
  const { user, skipped, loginWithGoogle, logout, skip, googleReady } = useGoogleAuth();

  // מסך כניסה — הצג אם לא מחובר ולא דילג
  if (!user && !skipped) {
    return <LandingScreen onLogin={loginWithGoogle} onSkip={skip} />;
  }

  return <HomeMain user={user} onLogout={logout} isGuest={!user && skipped} />;
}

// ─── מונה צופים חיים בפאנל ניהול ─────────────────────────────
// שולף כל 10 שניות, לכל שידור פעיל, כמה צופים יש עליו כרגע (בלי "להצטרף"
// כצופה — endpoint נפרד GET שלא רושם heartbeat). דורש שה-endpoint
// /api/live/:liveId/viewers קיים בשרת (ראה live_viewers_flask.py / live_viewers_express.js).
function useAdminLiveViewerCounts(liveChannels, active) {
  const [counts, setCounts] = useState({});
  const idsKey = liveChannels.map(c => c.id).join(",");
  useEffect(() => {
    if (!active || liveChannels.length === 0) return;
    let stopped = false;
    const poll = async () => {
      const results = await Promise.all(liveChannels.map(async ch => {
        const res = await apiCall(`/api/live/${ch.id}/viewers`, "GET");
        return [ch.id, typeof res?.viewers === "number" ? res.viewers : null];
      }));
      if (!stopped) setCounts(Object.fromEntries(results));
    };
    poll();
    const interval = setInterval(poll, 10000);
    return () => { stopped = true; clearInterval(interval); };
  }, [active, idsKey]);
  return counts;
}

function HomeMain({ user, onLogout, isGuest }) {
  const { slug, episode } = useParams();
  const navigate = useNavigate();
  const [userMenuOpen, setUserMenuOpen] = React.useState(false);
  const userMenuRef = React.useRef(null);

  // סגירת התפריט בלחיצה מחוץ לו
  React.useEffect(() => {
    if (!userMenuOpen) return;
    const onClickOutside = (e) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target)) setUserMenuOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [userMenuOpen]);


  // ── Progress / History (רק למשתמשים מחוברים) ──
  const saveProgress = React.useCallback(async (mediaId, position, duration) => {
    if (!user) return;
    await apiCall("/api/progress", "POST", { media_id: mediaId, position, duration }, user.id);
  }, [user]);

  const loadProgress = React.useCallback(async (mediaId) => {
    if (!user) return 0;
    const res = await apiCall(`/api/progress/${mediaId}`, "GET", null, user.id);
    return res?.position || 0;
  }, [user]);

  const saveHistory = React.useCallback(async (mediaId, title, thumbnailUrl) => {
    if (!user) return;
    // עדכון מיידי של הרשימה המקומית — כך שהיא תופיע מיד בקטגוריית "היסטוריה"
    // בלי לחכות/לדרוש רענון של הדף (זה מה שגרם ל"נכנסתי להיסטוריה ואין כלום")
    const entry = { media_id: mediaId, title, thumbnail_url: thumbnailUrl || "" };
    setHistory(prev => [entry, ...prev.filter(h => h.media_id !== mediaId)]);
    const saved = await apiCall("/api/history", "POST", { media_id: mediaId, title, thumbnail_url: thumbnailUrl || "" }, user.id);
    // אם השרת מחזיר את הרשומה/הרשימה המעודכנת בפועל — נסנכרן איתה בשקט
    if (Array.isArray(saved)) setHistory(saved);
  }, [user]);

  const [history, setHistory] = React.useState([]);
  const refreshHistory = React.useCallback(() => {
    if (!user) return;
    apiCall("/api/history", "GET", null, user.id).then(h => { if (h) setHistory(h); });
  }, [user]);
  React.useEffect(() => { refreshHistory(); }, [refreshHistory]);

  // ── API endpoint: /zovex/api?key=XXX ──
  const [apiMode] = useState(slug === "api");
  const [apiResult, setApiResult] = useState(null);

  useEffect(() => {
    if (slug !== "api") return;
    (async () => {
      const params = new URLSearchParams(window.location.search);
      const key = params.get("key");
      try {
        const keysRes = await fetch(`${import.meta.env.BASE_URL}apikeys.json?t=` + Date.now());
        const keys = keysRes.ok ? await keysRes.json() : [];
        const valid = keys.find(k => k.key === key && k.active);
        if (!valid) {
          setApiResult({ error: "Invalid or inactive API key" });
          return;
        }
        const moviesRes = await fetch(`${import.meta.env.BASE_URL}movies.json?t=` + Date.now());
        const moviesData = moviesRes.ok ? await moviesRes.json() : [];
        setApiResult(moviesData);
      } catch (e) {
        setApiResult({ error: "Server error: " + e.message });
      }
    })();
  }, [slug]);

  if (apiMode) {
    return (
      <pre style={{ direction: "ltr", fontFamily: "monospace", padding: 20, whiteSpace: "pre-wrap", wordBreak: "break-all", margin: 0 }}>
        {apiResult === null ? "" : JSON.stringify(apiResult)}
      </pre>
    );
  }

  // ── state ──
  const [movies, setMovies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("הכל");
  const [visibleCount, setVisibleCount] = useState(40);
  const [selectedMovie, setSelectedMovie] = useState(() => lsJson("zovex_movie"));
  const [selectedSeries, setSelectedSeries] = useState(() => ls("zovex_series"));
  const [openSeasons, setOpenSeasons] = useState({});
  const [seasonLoading, setSeasonLoading] = useState(false);
  const [playerMovie, setPlayerMovie] = useState(() => lsJson("zovex_player"));
  const [resumeSeconds, setResumeSeconds] = useState(0);
  const [kalturaRefreshing, setKalturaRefreshing] = useState(false);
  const [showDonation, setShowDonation] = useState(false);
  const [pendingAction, setPendingAction] = useState(null);
  const [showSeasonMenu, setShowSeasonMenu] = useState(false);
  const [isDesktop, setIsDesktop] = useState(() => { try { return window.innerWidth >= 1024; } catch { return false; } });

  // admin
  const [showAdminLogin, setShowAdminLogin] = useState(false);
  const [showAdmin, setShowAdmin] = useState(false);

  // live streams — מערך של כמה שידורים חיים במקביל, כל אחד עם שם וקישור
  // נשמרים ב-movies.json כתכנים עם category: "שידורים חיים" ו-is_live: true
  const [liveChannels, setLiveChannels] = useState([]); // [{id, name, video_url, type}]
  const [liveNameInput, setLiveNameInput] = useState("");
  const [liveUrlInput, setLiveUrlInput] = useState("");
  const [showLivePlayer, setShowLivePlayer] = useState(null); // האובייקט של הלייב שנפתח, או null
  const [liveSaving, setLiveSaving] = useState(false);
  const [editingLiveId, setEditingLiveId] = useState(null);
  const liveActive = liveChannels.length > 0;
  const [pinInput, setPinInput] = useState("");
  const [letterInput, setLetterInput] = useState("");
  const [loginError, setLoginError] = useState("");
  const [adminTab, setAdminTab] = useState("browse");
  const adminLiveViewerCounts = useAdminLiveViewerCounts(liveChannels, adminTab === "live");
  const [editingMovie, setEditingMovie] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [saving, setSaving] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [formStatus, setFormStatus] = useState({ type: "", message: "" });
  const [tmdbKey, setTmdbKey] = useState(() => ls("zovex_tmdb_key", ""));
  const [tmdbQuery, setTmdbQuery] = useState("");
  const [tmdbResults, setTmdbResults] = useState([]);
  const [tmdbLoading, setTmdbLoading] = useState(false);
  const [isSeries, setIsSeries] = useState(false);
  const [showExistingSeries, setShowExistingSeries] = useState(false);
  const [videoUrlInput, setVideoUrlInput] = useState("");
  const [posterPreview, setPosterPreview] = useState("");
  const [form, setForm] = useState({
    title: "", thumbnail_url: "", category: "", description: "",
    year: String(new Date().getFullYear()),
    series_name: "", season_number: "", episode_number: "", episode_title: "",
    jellyfinServer: "", jellyfinApiKey: "", custom_slug: ""
  });
  const [categories, setCategories] = useState([]);
  const [newCat, setNewCat] = useState("");
  const [editingCat, setEditingCat] = useState(null);
  const [editingCatVal, setEditingCatVal] = useState("");
  const [manageQ, setManageQ] = useState("");
  const fileInputRef = useRef(null);
  const lastScrollY = useRef(0);
  const loadMoreRef = useRef(null);
  const [showCategories, setShowCategories] = useState(true);

  // ── effects ──
  useEffect(() => {
    const onResize = () => setIsDesktop(window.innerWidth >= 1024);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    const onScroll = () => {
      const y = window.scrollY;
      if (y < 10) setShowCategories(true);
      else if (y > lastScrollY.current) setShowCategories(false);
      else setShowCategories(true);
      lastScrollY.current = y;
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // אם הנגן שוחזר מ-localStorage (למשל ריענון דף באמצע צפייה) — טען את המיקום השמור
  useEffect(() => {
    if (playerMovie && user) {
      loadProgress(playerMovie.id).then(pos => setResumeSeconds(pos || 0));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // נקה state כשנכנסים ישירות למסך הבית (ללא slug)
  useEffect(() => {
    if (!slug) {
      setSelectedMovie(null);
      setSelectedSeries(null);
      setPlayerMovie(null);
      lsDel("zovex_movie");
      lsDel("zovex_series");
      lsDel("zovex_player");
    }
  }, []);

  // טעינה אוטומטית כשמגיעים לתחתית
  useEffect(() => {
    if (!loadMoreRef.current) return;
    const obs = new IntersectionObserver(entries => {
      if (entries[0].isIntersecting) setVisibleCount(c => c + 40);
    }, { threshold: 0.1 });
    obs.observe(loadMoreRef.current);
    return () => obs.disconnect();
  });

  const loadMovies = async () => {
    setLoading(true);
    try {
      const all = (await Movie.list("-created_date", 2000)) || [];
      setLiveChannels(all.filter(m => m.is_live === true));
      setMovies(all.filter(m => !m.is_live));
    } catch {}
    setLoading(false);
  };

  // קריאה מ-raw.githubusercontent.com — מתעדכן מיד אחרי שמירה בלי לחכות ל-build
  const loadLiveFromGitHub = async () => {
    try {
      const res = await fetch(`https://raw.githubusercontent.com/davidggjg/zovex/main/public/movies.json?t=` + Date.now());
      if (!res.ok) return;
      const all = await res.json();
      setLiveChannels(all.filter(m => m.is_live === true));
    } catch {}
  };
  useEffect(() => { loadMovies(); }, []);
  useEffect(() => {
    loadLiveFromGitHub();
    // בדוק כל 30 שניות אם יש שידורים חיים חדשים
    const interval = setInterval(loadLiveFromGitHub, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const onPop = () => {
      if (playerMovie) { setPlayerMovie(null); window.history.pushState(null, "", window.location.href); return; }
      if (selectedSeries) { setSelectedSeries(null); window.history.pushState(null, "", window.location.href); return; }
      if (selectedMovie) { setSelectedMovie(null); window.history.pushState(null, "", window.location.href); return; }
    };
    window.history.pushState(null, "", window.location.href);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [playerMovie, selectedSeries, selectedMovie]);

  useEffect(() => {
    if (selectedMovie) document.title = `${selectedMovie.title} | ZOVEX`;
    else if (selectedSeries) document.title = `${selectedSeries} | ZOVEX`;
    else document.title = "ZOVEX - סדרות וסרטים לצפייה ישירה";
  }, [selectedMovie, selectedSeries]);

  useEffect(() => {
    if (!movies.length) return;
    if (slug) {
      // שלב 1: בדוק אם ה-slug תואם custom_slug (כתובת אנגלית קצרה) — לסדרה
      const bySlugSeries = movies.find(m => m.series_name && m.custom_slug === slug);
      if (bySlugSeries) {
        setSelectedSeries(bySlugSeries.series_name);
        if (episode) {
          // תמיכה בפורמט: season-2-episode-5 או episode-5 (עונה 1 כברירת מחדל)
          const seasonMatch = episode.match(/season[^0-9]*(\d+)/i);
          const epMatch = episode.match(/episode[^0-9]*(\d+)/i) || episode.match(/(\d+)$/);
          const seasonNum = seasonMatch ? parseInt(seasonMatch[1]) : 1;
          const epNum = epMatch ? parseInt(epMatch[1]) : 1;
          const ep = movies.find(m =>
            m.series_name === bySlugSeries.series_name &&
            (m.season_number || 1) === seasonNum &&
            (m.episode_number === epNum || String(m.episode_number) === String(epNum))
          );
          if (ep) openWithKalturaRefresh(ep);
        }
        return;
      }
      // שלב 2: בדוק אם ה-slug תואם custom_slug — לסרט
      const bySlugMovie = movies.find(m => !m.series_name && m.custom_slug === slug);
      if (bySlugMovie) {
        setSelectedMovie(bySlugMovie);
        if (episode) openWithKalturaRefresh(bySlugMovie);
        return;
      }
      // שלב 3: fallback - שם בעברית מקודד (כתובת ישנה)
      const decoded = decodeURIComponent(slug).replace(/-/g, " ");
      if (movies.some(m => m.series_name === decoded)) {
        setSelectedSeries(decoded);
        if (episode) {
          const epDecoded = decodeURIComponent(episode).replace(/-/g, " ");
          const seasonMatch = epDecoded.match(/עונה[^0-9]*(\d+)/);
          const epMatch = epDecoded.match(/פרק[^0-9]*(\d+)/) || epDecoded.match(/(\d+)$/);
          const seasonNum = seasonMatch ? parseInt(seasonMatch[1]) : 1;
          const epNum = epMatch ? parseInt(epMatch[1]) : 1;
          const ep = movies.find(m =>
            m.series_name === decoded &&
            (m.season_number || 1) === seasonNum &&
            (m.episode_number === epNum || String(m.episode_number) === String(epNum))
          );
          if (ep) openWithKalturaRefresh(ep);
        }
        return;
      }
      // שלב 4: בדוק אם זה סרט לפי shortId (כתובת ישנה)
      const parts = slug.split("-");
      const shortId = parts[parts.length - 1];
      const found = movies.find(m => m.id.startsWith(shortId));
      if (found) {
        setSelectedMovie(found);
        if (episode) openWithKalturaRefresh(found);
      }
    }
  }, [slug, episode, movies]);

  useEffect(() => { playerMovie ? lsSet("zovex_player", JSON.stringify(playerMovie)) : lsDel("zovex_player"); }, [playerMovie]);
  useEffect(() => { selectedMovie ? lsSet("zovex_movie", JSON.stringify(selectedMovie)) : lsDel("zovex_movie"); }, [selectedMovie]);
  useEffect(() => { selectedSeries ? lsSet("zovex_series", selectedSeries) : lsDel("zovex_series"); }, [selectedSeries]);

  useEffect(() => {
    if (!movies.length) return;
    const saved = lsJson("zovex_cats");
    const fromMovies = [...new Set(movies.map(m => m.category).filter(Boolean))];
    if (saved?.length) {
      const merged = [...saved, ...fromMovies.filter(c => !saved.includes(c))];
      setCategories(merged); lsSet("zovex_cats", JSON.stringify(merged)); return;
    }
    setCategories(fromMovies); lsSet("zovex_cats", JSON.stringify(fromMovies));
  }, [movies]);

  useEffect(() => {
    if (searchTerm === SECRET_TRIGGER) { setSearchTerm(""); setShowAdminLogin(true); }
  }, [searchTerm]);

  useEffect(() => {
    if (!tmdbQuery.trim() || !tmdbKey) { setTmdbResults([]); return; }
    const t = setTimeout(async () => {
      setTmdbLoading(true);
      try {
        const r = await fetch(`https://api.themoviedb.org/3/search/multi?api_key=${tmdbKey}&query=${encodeURIComponent(tmdbQuery)}&language=he`);
        const d = await r.json();
        setTmdbResults((d.results || []).filter(x => x.media_type !== "person").slice(0, 6));
      } catch {}
      setTmdbLoading(false);
    }, 450);
    return () => clearTimeout(t);
  }, [tmdbQuery, tmdbKey]);

  // ── derived ──
  const seriesMap = useMemo(() => {
    const map = {};
    movies.forEach(m => {
      if (!m.series_name) return;
      if (!map[m.series_name]) map[m.series_name] = { name: m.series_name, thumbnail_url: m.thumbnail_url, description: m.description, category: m.category, custom_slug: m.custom_slug, episodes: [] };
      map[m.series_name].episodes.push(m);
    });
    return map;
  }, [movies]);

  const existingSeriesNames = useMemo(() => Object.keys(seriesMap), [seriesMap]);

  const allCategories = useMemo(() => {
    const from = movies.map(m => m.category).filter(Boolean);
    // "שידורים חיים" מסוננת מכאן כי היא נוספת בנפרד למטה — כדי למנוע כפילות
    const base = ["הכל", ...new Set([...categories, ...from])].filter(c => c !== "שידורים חיים");
    let result = liveActive ? [...base, "שידורים חיים"] : base;
    // "היסטוריה" מוצגת רק למשתמשים מחוברים
    if (user) result = [...result, "היסטוריה"];
    return result;
  }, [movies, categories, liveActive, user]);

  const filteredItems = useMemo(() => {
    const q = searchTerm.toLowerCase();
    const cat = selectedCategory;
    // קטגוריית שידורים חיים — מציגה את הערוצים החיים בלבד, לא תכנים רגילים
    if (cat === "שידורים חיים") {
      return liveChannels
        .filter(ch => ch.title.toLowerCase().includes(q))
        .map(ch => ({ ...ch, is_live: true }));
    }
    const regularMovies = movies.filter(m => !m.series_name && (m.title || "").toLowerCase().includes(q) && (cat === "הכל" || m.category === cat));
    const seen = {};
    const seriesList = [];
    movies.forEach(m => {
      if (!m.series_name || seen[m.series_name]) return;
      const matchQ = m.series_name.toLowerCase().includes(q) || (m.title || "").toLowerCase().includes(q);
      const matchC = cat === "הכל" || m.category === cat;
      if (matchQ && matchC) { seen[m.series_name] = true; seriesList.push(seriesMap[m.series_name]); }
    });
    // בקטגוריית "הכל" — שידורים חיים מוצגים ראשונים, למעלה
    const liveItems = cat === "הכל" ? liveChannels.filter(ch => ch.title.toLowerCase().includes(q)).map(ch => ({ ...ch, is_live: true })) : [];
    return [...liveItems, ...seriesList, ...regularMovies];
  }, [movies, searchTerm, selectedCategory, seriesMap, liveChannels]);

  // ── handlers ──
  const saveCats = (c) => { setCategories(c); lsSet("zovex_cats", JSON.stringify(c)); };

  const renameCat = async (oldName, newName) => {
    if (!newName.trim() || newName === oldName) { setEditingCat(null); return; }
    saveCats(categories.map(c => c === oldName ? newName.trim() : c));
    setSaving(true);
    try {
      const all = await Movie.list("-created_date", 2000);
      await Movie.saveAll(all.map(m => m.category === oldName ? { ...m, category: newName.trim() } : m));
    } catch {}
    setSaving(false); loadMovies(); setEditingCat(null); setEditingCatVal("");
  };

  const selectTMDB = (item) => {
    const poster = item.poster_path ? `https://image.tmdb.org/t/p/w500${item.poster_path}` : "";
    setForm(p => ({ ...p, title: item.title || item.name || "", description: item.overview || "", thumbnail_url: poster, year: (item.release_date || item.first_air_date || "").slice(0, 4) || p.year, category: item.media_type === "tv" ? "סדרות" : "סרטים" }));
    setPosterPreview(poster);
    if (item.media_type === "tv") setIsSeries(true);
    setTmdbResults([]); setTmdbQuery("");
  };

  const handleUploadPoster = (e) => {
    const file = e.target.files?.[0]; if (!file) return;
    setUploading(true);
    const reader = new FileReader();
    reader.onload = (ev) => { setForm(p => ({ ...p, thumbnail_url: ev.target.result })); setPosterPreview(ev.target.result); setUploading(false); };
    reader.readAsDataURL(file);
  };

  const resetForm = () => {
    setForm({ title: "", thumbnail_url: "", category: categories[0] || "", description: "", year: String(new Date().getFullYear()), series_name: "", season_number: "", episode_number: "", episode_title: "", jellyfinServer: "", jellyfinApiKey: "", custom_slug: "" });
    setVideoUrlInput(""); setIsSeries(false); setEditingMovie(null);
    setFormStatus({ type: "", message: "" }); setPosterPreview(""); setShowExistingSeries(false);
  };

  const generateAI = async () => {
    if (!form.title) { setFormStatus({ type: "error", message: "הכנס שם קודם" }); return; }
    setAiLoading(true);
    try {
      const res = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: "claude-sonnet-4-20250514", max_tokens: 300, messages: [{ role: "user", content: `כתוב תיאור קצר ומרתק בעברית (3 משפטים, סגנון נטפליקס) ל: "${form.title}". רק התיאור עצמו.` }] })
      });
      const data = await res.json();
      const result = data.content?.[0]?.text;
      if (result) setForm(p => ({ ...p, description: result }));
    } catch {}
    setAiLoading(false);
  };

  const handleSave = async () => {
    if (!form.title || !form.category) { setFormStatus({ type: "error", message: "שם וקטגוריה חובה" }); return; }
    setSaving(true);
    const info = extractVideoInfo(videoUrlInput);
    let autoEpNum = Number(form.episode_number) || null;
    if (isSeries && !editingMovie && !autoEpNum) {
      const serName = form.series_name || form.title;
      const seasonN = Number(form.season_number) || 1;
      const existing = movies.filter(m => m.series_name === serName && (m.season_number || 1) === seasonN).map(m => m.episode_number || 0);
      autoEpNum = existing.length ? Math.max(...existing) + 1 : 1;
    }
    let autoThumb = form.thumbnail_url;
    if (!autoThumb && isSeries) {
      const serName = form.series_name || form.title;
      const ep1 = movies.find(m => m.series_name === serName && (m.season_number || 1) === 1 && (m.episode_number || 1) === 1);
      if (ep1?.thumbnail_url) autoThumb = ep1.thumbnail_url;
    }
    const payload = {
      title: form.title, description: form.description, thumbnail_url: autoThumb,
      category: form.category, year: Number(form.year) || new Date().getFullYear(),
      video_id: info.video_id, type: info.type, video_url: videoUrlInput,
      series_name: isSeries ? (form.series_name || form.title) : null,
      season_number: isSeries ? (Number(form.season_number) || 1) : null,
      episode_number: isSeries ? autoEpNum : null,
      episode_title: isSeries ? form.episode_title : null,
      custom_slug: form.custom_slug ? form.custom_slug.trim().toLowerCase() : null,
    };
    try {
      if (editingMovie) {
        if (payload.series_name && (editingMovie.category !== payload.category || payload.custom_slug !== editingMovie.custom_slug)) {
          const all = await Movie.list("-created_date", 2000);
          await Movie.saveAll(all.map(m => m.id === editingMovie.id ? { ...m, ...payload } : m.series_name === payload.series_name ? { ...m, category: payload.category, custom_slug: payload.custom_slug } : m));
          setFormStatus({ type: "success", message: "עודכן! קטגוריה וכתובת URL עודכנו לכל הסדרה" });
        } else {
          await Movie.update(editingMovie.id, payload);
          setFormStatus({ type: "success", message: "עודכן!" });
        }
      } else {
        await Movie.create(payload);
        setFormStatus({ type: "success", message: "נשמר!" });
      }
      resetForm(); loadMovies();
      setTimeout(() => setFormStatus({ type: "", message: "" }), 3000);
    } catch { setFormStatus({ type: "error", message: "שגיאה בשמירה" }); }
    setSaving(false);
  };

  const handleDelete = async (id, silent = false) => {
    if (!silent && !window.confirm("למחוק?")) return;
    setDeleting(id);
    try { await Movie.delete(id); if (!silent) loadMovies(); } catch {}
    setDeleting(null);
  };

  const handleDeleteSeries = async (serName, episodes) => {
    if (!window.confirm(`למחוק את כל הסדרה "${serName}"? (${episodes.length} פרקים)`)) return;
    try {
      const all = await Movie.list("-created_date", 2000);
      await Movie.saveAll(all.filter(m => m.series_name !== serName));
    } catch {}
    loadMovies();
  };

  const updateSeriesThumbnail = async (seriesName, thumbnailUrl) => {
    if (!seriesName || !thumbnailUrl) return;
    setSaving(true);
    try {
      const all = await Movie.list("-created_date", 2000);
      await Movie.saveAll(all.map(m => m.series_name === seriesName ? { ...m, thumbnail_url: thumbnailUrl } : m));
    } catch {}
    setFormStatus({ type: "success", message: "תמונה עודכנה לסדרה!" });
    loadMovies(); setSaving(false); setTimeout(() => setFormStatus({ type: "", message: "" }), 3000);
  };

  const updateSeriesDescription = async (seriesName, description) => {
    if (!seriesName || !description) return;
    setSaving(true);
    try {
      const all = await Movie.list("-created_date", 2000);
      await Movie.saveAll(all.map(m => m.series_name === seriesName ? { ...m, description } : m));
    } catch {}
    setFormStatus({ type: "success", message: "תיאור עודכן לסדרה!" });
    loadMovies(); setSaving(false); setTimeout(() => setFormStatus({ type: "", message: "" }), 3000);
  };

  const startEdit = (movie) => {
    setEditingMovie(movie); setIsSeries(!!movie.series_name);
    setForm({
      title: movie.title || "", thumbnail_url: movie.thumbnail_url || "",
      category: movie.category || "", description: movie.description || "",
      year: String(movie.year || new Date().getFullYear()),
      series_name: movie.series_name || "", season_number: String(movie.season_number || ""),
      episode_number: String(movie.episode_number || ""), episode_title: movie.episode_title || "",
      jellyfinServer: movie.jellyfin_server || "", jellyfinApiKey: movie.jellyfin_api_key || "",
      custom_slug: movie.custom_slug || "",
    });
    setPosterPreview(movie.thumbnail_url || "");
    let fullUrl = movie.video_url?.startsWith("http") ? movie.video_url : "";
    if (!fullUrl && movie.video_id) {
      const vid = movie.video_id, type = movie.type || "direct";
      if (type === "youtube") fullUrl = `https://www.youtube.com/watch?v=${vid}`;
      else if (type === "drive") fullUrl = `https://drive.google.com/file/d/${vid}/view`;
      else if (type === "vimeo") fullUrl = `https://vimeo.com/${vid}`;
      else if (type === "dailymotion") fullUrl = `https://www.dailymotion.com/video/${vid}`;
      else if (type === "streamable") fullUrl = `https://streamable.com/${vid}`;
      else if (type === "rumble") fullUrl = `https://rumble.com/embed/${vid}`;
      else if (type === "archive") fullUrl = `https://archive.org/details/${vid}`;
      else if (type === "kan") fullUrl = `https://www.kan.org.il/General/Embed.aspx?id=${vid}`;
      else if (type === "okru") fullUrl = `https://ok.ru/video/${vid}`;
      else if (type === "kaltura") { const p = vid.split("/"); fullUrl = `https://cdnapisec.kaltura.com/p/${p[0]}/embedPlaykitJs/uiconf_id/${p[1]}?iframeembed=true&entry_id=${p[2]}`; }
      else fullUrl = vid;
    }
    setVideoUrlInput(fullUrl); setAdminTab("add");
  };

  const openWithKalturaRefresh = async (movie, resumeAt = null) => {
    // שמור להיסטוריה (רק למחוברים)
    saveHistory(movie.id, movie.title, movie.thumbnail_url);
    // המשך צפייה — אם לא הועבר מיקום מפורש, טען את המיקום השמור וקפוץ אליו בדיוק כשהנגן נפתח
    const startAt = resumeAt !== null ? resumeAt : await loadProgress(movie.id);
    setResumeSeconds(startAt || 0);
    // עדכן URL ישירות בלי לגרום ל-re-render של React Router
    // אם יש custom_slug (כתובת אנגלית קצרה) — נשתמש בו במקום השם בעברית
    if (movie.series_name && movie.episode_number) {
      const serSlug = movie.custom_slug ? movie.custom_slug : encodeURIComponent(movie.series_name.replace(/ /g, "-"));
      const seasonNum = movie.season_number || 1;
      const epSlug = movie.custom_slug
        ? `season-${seasonNum}-episode-${movie.episode_number}`
        : encodeURIComponent(`עונה-${seasonNum}-פרק-${movie.episode_number}`);
      window.history.replaceState(null, "", `/zovex/${serSlug}/${epSlug}`);
    } else if (movie.title && !movie.series_name) {
      const movieSlug = movie.custom_slug ? movie.custom_slug : (encodeURIComponent((movie.title || "").replace(/ /g, "-")) + "-" + movie.id.slice(0, 6));
      const watchPart = movie.custom_slug ? "watch" : "watch";
      window.history.replaceState(null, "", `/zovex/${movieSlug}/${watchPart}`);
    }
    const vid = movie.video_id || "";
    const isKaltura = movie.type === "kaltura" || vid.includes("kaltura");
    if (!isKaltura) { setPlayerMovie(movie); return; }
    setKalturaRefreshing(true);
    try { await Promise.race([Movie.update(movie.id, { ...movie, _refreshed: Date.now() }), new Promise((_, r) => setTimeout(() => r(), 9000))]); } catch {}
    setKalturaRefreshing(false); setPlayerMovie(movie);
  };

  // המשך צפייה / היסטוריה — קליק פותח את הנגן ישירות בדיוק בשנייה שנשמרה,
  // בלי לעבור קודם דרך מסך הפרטים ולחצן "המשך לצפייה" נוסף
  const handleContinueWatchingClick = (item) => {
    const action = () => {
      if (item.series_name) setSelectedSeries(item.series_name);
      else setSelectedMovie(item);
      openWithKalturaRefresh(item);
    };
    setPendingAction(() => action); setShowDonation(true);
  };

  const handleItemClick = (item, isSer) => {
    const action = () => {
      if (item.is_live) {
        setShowLivePlayer(item);
        return;
      }
      if (isSer) {
        const slug = item.custom_slug || encodeURIComponent(item.name.replace(/ /g, "-"));
        navigate(`/${slug}`); setSelectedSeries(item.name);
      } else {
        const slug = item.custom_slug || (encodeURIComponent((item.title || "").replace(/ /g, "-")) + "-" + item.id.slice(0, 6));
        navigate(`/${slug}`); setSelectedMovie(item);
      }
    };
    setPendingAction(() => action); setShowDonation(true);
  };

  // ── shared styles ──
  const inp = { width: "100%", background: "#F0F0F5", border: "1.5px solid #d2d2d7", borderRadius: 10, padding: "10px 12px", fontSize: 13, fontFamily: "inherit", outline: "none", boxSizing: "border-box" };
  const cardStyle = { background: "#fff", borderRadius: 16, padding: 18, marginBottom: 14, boxShadow: "0 4px 20px rgba(0,0,0,.07)" };
  const dot = <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#0071e3", display: "inline-block", marginLeft: 8, flexShrink: 0 }} />;

  // ── early returns ──
  if (kalturaRefreshing) return (
    <div style={{ position: "fixed", inset: 0, background: "#000", zIndex: 9999, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 20 }}>
      <style>{SPIN}</style>
      <div style={{ width: 56, height: 56, border: "4px solid rgba(255,255,255,0.15)", borderTop: "4px solid #e91e63", borderRadius: "50%", animation: "spin 0.9s linear infinite" }} />
      <p style={{ color: "#fff", fontSize: 15, fontFamily: "Arial", margin: 0 }}>מכין סרטון...</p>
    </div>
  );

  if (playerMovie) return (
    <CustomVideoPlayer
      movie={playerMovie}
      startTime={resumeSeconds}
      onProgress={(pos, dur) => saveProgress(playerMovie.id, pos, dur)}
      onClose={() => setPlayerMovie(null)}
    />
  );

  if (loading) return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "100vh", background: "#fff" }}>
      <style>{SPIN}</style>
      <div style={{ textAlign: "center" }}>
        <div style={{ width: 50, height: 50, border: "5px solid #eee", borderTop: "5px solid #e50914", borderRadius: "50%", animation: "spin 1s linear infinite", margin: "0 auto 15px" }} />
        <p style={{ color: "#999", fontFamily: "Arial" }}>טוען...</p>
      </div>
    </div>
  );

  if (showAdminLogin) return (
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
          if (pinH === PIN_HASH && letH === LETTER_HASH) { setShowAdminLogin(false); setShowAdmin(true); setPinInput(""); setLetterInput(""); setLoginError(""); setShowDonation(false); }
          else setLoginError("קודים שגויים.");
        }} style={{ width: "100%", background: "#e50914", color: "#fff", border: "none", padding: 14, borderRadius: 10, fontSize: 16, fontWeight: "bold", cursor: "pointer" }}>כניסה</button>
        <button onClick={() => { setShowAdminLogin(false); setPinInput(""); setLetterInput(""); }} style={{ width: "100%", background: "none", color: "#666", border: "none", padding: 10, marginTop: 8, cursor: "pointer", fontSize: 14 }}>ביטול</button>
      </div>
    </div>
  );

  // ── donation modal ──
  const DonationModal = showDonation && !showAdmin ? (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.88)", zIndex: 9998, display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }} dir="rtl">
      <div style={{ background: "#111", borderRadius: 24, padding: 28, maxWidth: 380, width: "100%", textAlign: "center", boxShadow: "0 20px 60px rgba(0,0,0,0.6)", border: "1px solid #222" }}>
        <div style={{ fontSize: 32, marginBottom: 10 }}>🎬</div>
        <h2 style={{ fontSize: 20, fontWeight: 900, margin: "0 0 10px", color: "#fff" }}>עזרו לנו לשפר את האתר</h2>
        <p style={{ fontSize: 14, color: "#aaa", margin: "0 0 20px", lineHeight: 1.7 }}>
          ZOVEX פועל ללא מטרות רווח ובהתנדבות מלאה.<br/>
          תרומה קטנה תעזור לנו לשפר את איכות האתר,<br/>
          לשדרג את הנגנים ולהוסיף עוד תכנים כיפיים לצפייה 💙
        </p>
        <a href="https://www.bitpay.co.il/app/me/F062649F-7124-4CDF-88DD-A1FEA14185EB" target="_blank" rel="noreferrer" style={{ display: "block", background: "#0d7a5f", color: "#fff", borderRadius: 14, padding: "14px 0", fontSize: 16, fontWeight: 700, textDecoration: "none", marginBottom: 10 }}>
          💳 תרום בביט
        </a>
        <button onClick={() => { setShowDonation(false); pendingAction && pendingAction(); }} style={{ width: "100%", background: "#1e1e1e", color: "#888", border: "1px solid #333", borderRadius: 14, padding: "12px 0", fontSize: 14, cursor: "pointer", fontFamily: "inherit" }}>
          המשך לצפייה
        </button>
      </div>
    </div>
  ) : null;

  // ── admin panel ──
  if (showAdmin) return (
    <div style={{ background: "#F5F5F7", minHeight: "100vh", direction: "rtl", fontFamily: "-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif" }}>
      <style>{SPIN}</style>
      {DonationModal}
      {/* topbar */}
      <div style={{ background: "rgba(245,245,247,.94)", backdropFilter: "blur(20px)", borderBottom: "1px solid #d2d2d7", padding: "13px 18px", display: "flex", alignItems: "center", justifyContent: "space-between", position: "sticky", top: 0, zIndex: 30 }}>
        <div style={{ fontSize: 18, fontWeight: 900, letterSpacing: 2 }}>ZOVEX Admin</div>
        <button onClick={() => setShowAdmin(false)} style={{ background: "#F0F0F5", color: "#6e6e73", border: "1.5px solid #d2d2d7", borderRadius: 12, padding: "7px 14px", fontSize: 12, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>יציאה</button>
      </div>
      {/* tabs nav */}
      <div style={{ background: "rgba(245,245,247,.94)", borderBottom: "1px solid #d2d2d7", display: "flex", overflowX: "auto", position: "sticky", top: 50, zIndex: 20 }}>
        {[["browse","סרטים"],["add","הוסף"],["manage","ניהול"],["categories","קטגוריות"],["live","🔴 שידור חי"],["settings","הגדרות"]].map(([id, label]) => (
          <button key={id} onClick={() => setAdminTab(id)} style={{ flex: 1, minWidth: 58, padding: "11px 3px", fontSize: 11, fontWeight: 700, color: adminTab === id ? "#0071e3" : "#6e6e73", background: "none", border: "none", borderBottom: `2px solid ${adminTab === id ? "#0071e3" : "transparent"}`, cursor: "pointer", fontFamily: "inherit" }}>{label}</button>
        ))}
      </div>
      <div style={{ padding: 14, paddingBottom: 80 }}>

        {/* ── Browse tab ── */}
        {adminTab === "browse" && (
          <AdminBrowseTab movies={movies} seriesMap={seriesMap} existingSeriesNames={existingSeriesNames} categories={categories} onEdit={startEdit} />
        )}

        {/* ── Add/Edit tab ── */}
        {adminTab === "add" && (
          <div>
            <div style={cardStyle}>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12, display: "flex", alignItems: "center" }}>{dot}חיפוש TMDB אוטומטי</div>
              <div style={{ position: "relative" }}>
                <input value={tmdbQuery} onChange={e => setTmdbQuery(e.target.value)} placeholder={tmdbKey ? "חפש שם סרט / סדרה..." : "הכנס TMDB Key בהגדרות"} disabled={!tmdbKey} style={inp} />
                {tmdbLoading && <Loader2 size={14} style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", animation: "spin .6s linear infinite", color: "#0071e3" }} />}
              </div>
              {tmdbResults.length > 0 && (
                <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 7, maxHeight: 280, overflowY: "auto" }}>
                  {tmdbResults.map((x, i) => (
                    <div key={i} onClick={() => selectTMDB(x)} style={{ display: "flex", gap: 10, background: "#F5F5F7", borderRadius: 12, padding: 10, cursor: "pointer", border: "1.5px solid #d2d2d7", alignItems: "flex-start" }}>
                      {x.poster_path ? <img src={`https://image.tmdb.org/t/p/w92${x.poster_path}`} style={{ width: 40, height: 56, borderRadius: 7, objectFit: "cover", flexShrink: 0 }} alt="" /> : <div style={{ width: 40, height: 56, borderRadius: 7, background: "#d2d2d7", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18 }}>?</div>}
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 700 }}>{x.title || x.name}</div>
                        <div style={{ fontSize: 11, color: "#6e6e73", marginTop: 1 }}>{(x.release_date || x.first_air_date || "").slice(0, 4)} - {x.media_type === "tv" ? "סדרה" : "סרט"}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div style={cardStyle}>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 14, display: "flex", alignItems: "center" }}>{dot}{editingMovie ? "עריכת תוכן" : "פרטי התוכן"}</div>
              {/* type toggle */}
              <div style={{ marginBottom: 12 }}>
                <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>סוג תוכן</label>
                <div style={{ display: "flex", gap: 8 }}>
                  {[["movie","סרט"],["series","סדרה"]].map(([v, l]) => (
                    <button key={v} onClick={() => { setIsSeries(v === "series"); setShowExistingSeries(v === "series" && existingSeriesNames.length > 0); }} style={{ flex: 1, borderRadius: 12, padding: "10px 0", fontSize: 13, fontWeight: 700, border: "1.5px solid", cursor: "pointer", fontFamily: "inherit", borderColor: (v === "series") === isSeries ? "#0071e3" : "#d2d2d7", background: (v === "series") === isSeries ? "#0071e3" : "#F0F0F5", color: (v === "series") === isSeries ? "#fff" : "#6e6e73" }}>{l}</button>
                  ))}
                </div>
              </div>
              {/* existing series picker */}
              {isSeries && existingSeriesNames.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <button onClick={() => setShowExistingSeries(!showExistingSeries)} style={{ width: "100%", background: form.series_name && existingSeriesNames.includes(form.series_name) ? "#e8f4ff" : "#F5F5F7", border: `1.5px solid ${form.series_name && existingSeriesNames.includes(form.series_name) ? "#0071e3" : "#d2d2d7"}`, borderRadius: 12, padding: "11px 14px", fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "space-between", color: "#0071e3" }}>
                    <span>{form.series_name && existingSeriesNames.includes(form.series_name) ? form.series_name : "הוסף לסדרה קיימת"}</span>
                    {showExistingSeries ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                  </button>
                  {showExistingSeries && (
                    <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6, maxHeight: 200, overflowY: "auto", background: "#F5F5F7", borderRadius: 12, padding: 10 }}>
                      {existingSeriesNames.map(name => (
                        <div key={name} onClick={() => { const s = seriesMap[name]; setForm(p => ({ ...p, series_name: name, category: s.category || p.category, thumbnail_url: s.thumbnail_url || p.thumbnail_url })); setPosterPreview(s.thumbnail_url || ""); setShowExistingSeries(false); }} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", background: form.series_name === name ? "#e8f4ff" : "#fff", borderRadius: 10, cursor: "pointer", border: `1.5px solid ${form.series_name === name ? "#0071e3" : "#d2d2d7"}` }}>
                          {seriesMap[name]?.thumbnail_url ? <img src={seriesMap[name].thumbnail_url} style={{ width: 30, height: 42, borderRadius: 6, objectFit: "cover", flexShrink: 0 }} alt="" /> : <div style={{ width: 30, height: 42, borderRadius: 6, background: "#e0e0e0" }} />}
                          <div style={{ fontSize: 13, fontWeight: 700 }}>{name}</div>
                          {form.series_name === name && <span style={{ marginRight: "auto", fontSize: 16 }}>✓</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {/* title */}
              <div style={{ marginBottom: 12 }}>
                <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>{isSeries ? "כותרת לתצוגה (שם הפרק)" : "שם הסרט"}</label>
                <input value={form.title} onChange={e => setForm(p => ({ ...p, title: e.target.value }))} placeholder={isSeries ? "למשל: הכבוד של אשרף פרק 1" : "שם הסרט"} style={inp} />
              </div>
              {!isSeries && (
                <div style={{ marginBottom: 12 }}>
                  <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>כתובת URL לסרט (אנגלית, אופציונלי)</label>
                  <input value={form.custom_slug} onChange={e => setForm(p => ({ ...p, custom_slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "") }))} placeholder="fauda" dir="ltr" style={inp} />
                  <div style={{ fontSize: 10, color: "#0071e3", marginTop: 4, direction: "ltr", fontFamily: "monospace" }}>
                    /zovex/{form.custom_slug || "..."}
                  </div>
                </div>
              )}
              {/* series fields */}
              {isSeries && (
                <div style={{ background: "#F5F5F7", borderRadius: 12, padding: 12, marginBottom: 12 }}>
                  <div style={{ marginBottom: 10 }}>
                    <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>שם הסדרה (חייב להיות זהה בכל הפרקים!)</label>
                    <input value={form.series_name} onChange={e => setForm(p => ({ ...p, series_name: e.target.value }))} placeholder="למשל: הכבוד של אשרף" style={inp} />
                  </div>
                  <div style={{ marginBottom: 10 }}>
                    <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>כתובת URL לסדרה (אנגלית, אופציונלי)</label>
                    <input value={form.custom_slug} onChange={e => setForm(p => ({ ...p, custom_slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "") }))} placeholder="fauda" dir="ltr" style={inp} />
                    <div style={{ fontSize: 10, color: "#0071e3", marginTop: 4, direction: "ltr", fontFamily: "monospace" }}>
                      /zovex/{form.custom_slug || "..."}
                    </div>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                    <div>
                      <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>מספר עונה</label>
                      <input type="number" min="1" value={form.season_number} onChange={e => setForm(p => ({ ...p, season_number: e.target.value }))} placeholder="1" style={inp} />
                    </div>
                    <div>
                      <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>מספר פרק</label>
                      <input type="number" min="1" value={form.episode_number} onChange={e => setForm(p => ({ ...p, episode_number: e.target.value }))} placeholder="1" style={inp} />
                    </div>
                  </div>
                </div>
              )}
              {/* year + category */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 12 }}>
                <div>
                  <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>שנה</label>
                  <input type="number" value={form.year} onChange={e => setForm(p => ({ ...p, year: e.target.value }))} style={inp} />
                </div>
                <div>
                  <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>קטגוריה</label>
                  <select value={form.category} onChange={e => setForm(p => ({ ...p, category: e.target.value }))} style={inp}>
                    <option value="">בחר...</option>
                    {categories.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
              </div>
              {/* description */}
              <div style={{ marginBottom: 12 }}>
                <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>תיאור</label>
                <textarea value={form.description} onChange={e => setForm(p => ({ ...p, description: e.target.value }))} rows={3} style={{ ...inp, resize: "none", minHeight: 72 }} />
              </div>
              {/* poster */}
              <div style={{ marginBottom: 12 }}>
                <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 8, fontWeight: 700 }}>תמונת פוסטר</label>
                <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  <div style={{ width: 56, height: 78, borderRadius: 10, background: "#F0F0F5", border: "1.5px solid #d2d2d7", overflow: "hidden", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer" }} onClick={() => fileInputRef.current?.click()}>
                    {posterPreview ? <img src={posterPreview} style={{ width: "100%", height: "100%", objectFit: "cover" }} alt="" onError={() => setPosterPreview("")} /> : <Upload size={20} color="#6e6e73" />}
                  </div>
                  <button type="button" onClick={() => fileInputRef.current?.click()} disabled={uploading} style={{ flex: 1, background: "transparent", color: "#0071e3", border: "1.5px solid #0071e3", borderRadius: 12, padding: "11px 0", fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
                    {uploading ? "מעלה..." : "העלה תמונה"}
                  </button>
                </div>
                <input ref={fileInputRef} type="file" accept="image/*" style={{ display: "none" }} onChange={handleUploadPoster} />
                {isSeries && editingMovie && (
                  <div style={{ marginTop: 8, display: "flex", gap: 6 }}>
                    <button type="button" onClick={() => updateSeriesDescription(form.series_name || editingMovie.series_name, form.description)} disabled={!form.description} style={{ flex: 1, background: form.description ? "#5e5ce6" : "#ccc", color: "#fff", border: "none", borderRadius: 12, padding: "10px 0", fontSize: 12, fontWeight: 700, cursor: form.description ? "pointer" : "default", fontFamily: "inherit" }}>
                      📝 תיאור לסדרה
                    </button>
                    <button type="button" onClick={() => updateSeriesThumbnail(form.series_name || editingMovie.series_name, form.thumbnail_url)} disabled={!form.thumbnail_url} style={{ flexShrink: 0, background: form.thumbnail_url ? "#ff9500" : "#ccc", color: "#fff", border: "none", borderRadius: 12, padding: "10px 12px", fontSize: 16, cursor: form.thumbnail_url ? "pointer" : "default", fontFamily: "inherit" }}>
                      🖼️
                    </button>
                  </div>
                )}
              </div>
              {/* URL input */}
              <div style={{ marginBottom: 14 }}>
                <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>
                  קישור וידאו
                  {videoUrlInput && <span style={{ color: "#0071e3", fontWeight: 400, marginRight: 6, fontSize: 10 }}> - {extractVideoInfo(videoUrlInput).type}</span>}
                </label>
                <input value={videoUrlInput} onChange={e => {
                  let val = e.target.value;
                  if (val.includes("<iframe")) { const m = val.match(/src=["']([^"']+)['"]/); if (m) val = m[1]; }
                  setVideoUrlInput(val);
                }} placeholder="YouTube / Drive / Dailymotion / Rumble / mp4 / Kaltura iframe..." dir="ltr" style={inp} />
              </div>
              {/* save buttons */}
              <div style={{ display: "flex", gap: 8 }}>
                <button onClick={generateAI} disabled={aiLoading} style={{ flex: 1, background: "#34c759", color: "#fff", border: "none", borderRadius: 12, padding: 12, fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
                  {aiLoading ? <Loader2 size={14} style={{ animation: "spin .6s linear infinite" }} /> : "AI תיאור"}
                </button>
                <button onClick={handleSave} disabled={saving} style={{ flex: 1, background: "#0071e3", color: "#fff", border: "none", borderRadius: 12, padding: 12, fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
                  {saving ? <Loader2 size={14} style={{ animation: "spin .6s linear infinite" }} /> : editingMovie ? "עדכן" : "שמור"}
                </button>
              </div>
              {editingMovie && <button onClick={resetForm} style={{ width: "100%", marginTop: 8, background: "#F0F0F5", color: "#6e6e73", border: "1.5px solid #d2d2d7", borderRadius: 12, padding: 10, fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>ביטול עריכה</button>}
              {formStatus.message && <div style={{ marginTop: 10, borderRadius: 10, padding: "10px 12px", fontSize: 12, background: formStatus.type === "success" ? "#f0fff4" : "#fff5f5", color: formStatus.type === "success" ? "#1a7a3a" : "#ff3b30" }}>{formStatus.message}</div>}
            </div>
          </div>
        )}

        {/* ── Manage tab ── */}
        {adminTab === "manage" && (
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, background: "#F0F0F5", borderRadius: 12, padding: "9px 12px", marginBottom: 14, border: "1.5px solid #d2d2d7" }}>
              <Search size={15} color="#aaa" />
              <input value={manageQ} onChange={e => setManageQ(e.target.value)} placeholder="חפש סדרה או סרט..." style={{ background: "none", border: "none", outline: "none", flex: 1, fontSize: 13, fontFamily: "inherit" }} />
              {manageQ && <span onClick={() => setManageQ("")} style={{ cursor: "pointer", color: "#aaa", fontSize: 16 }}>✕</span>}
            </div>
            <div style={{ fontSize: 12, color: "#6e6e73", marginBottom: 10 }}>תכנים ({movies.length})</div>
            {existingSeriesNames.filter(n => n.toLowerCase().includes(manageQ.toLowerCase())).length > 0 && (
              <div style={{ marginBottom: 12, background: "#fff", borderRadius: 16, boxShadow: "0 2px 12px rgba(0,0,0,.06)", overflow: "hidden" }}>
                <div style={{ padding: "10px 16px", background: "#e8f0fe", fontSize: 13, fontWeight: 800, color: "#0071e3" }}>סדרות</div>
                {existingSeriesNames.filter(n => n.toLowerCase().includes(manageQ.toLowerCase())).map(serName => (
                  <AdminSeriesSection key={serName} serName={serName} episodes={seriesMap[serName].episodes} onEdit={startEdit} onDelete={handleDelete} onDeleteSeries={handleDeleteSeries} deleting={deleting} />
                ))}
              </div>
            )}
            {movies.filter(m => !m.series_name && (m.title || "").toLowerCase().includes(manageQ.toLowerCase())).length > 0 && (
              <AdminCategorySection catName="סרטים" items={movies.filter(m => !m.series_name && (m.title || "").toLowerCase().includes(manageQ.toLowerCase()))} onEdit={startEdit} onDelete={handleDelete} deleting={deleting} />
            )}
          </div>
        )}

        {/* ── Categories tab ── */}
        {adminTab === "categories" && (
          <div style={cardStyle}>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 14 }}>ניהול קטגוריות</div>
            <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
              <input value={newCat} onChange={e => setNewCat(e.target.value)} placeholder="קטגוריה חדשה..."
                onKeyDown={e => { if (e.key === "Enter" && newCat.trim()) { saveCats([...categories, newCat.trim()]); setNewCat(""); } }}
                style={{ ...inp, flex: 1 }} />
              <button onClick={() => { if (newCat.trim()) { saveCats([...categories, newCat.trim()]); setNewCat(""); } }} style={{ background: "#0071e3", color: "#fff", border: "none", borderRadius: 10, padding: "0 16px", fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>הוסף</button>
            </div>
            {categories.length === 0 && <p style={{ color: "#6e6e73", fontSize: 13, textAlign: "center" }}>אין קטגוריות עדיין</p>}
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {categories.map((cat, i) => (
                <div key={i} style={{ background: "#F5F5F7", borderRadius: 10, padding: "10px 14px" }}>
                  {editingCat === cat ? (
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <input value={editingCatVal} onChange={e => setEditingCatVal(e.target.value)} autoFocus onKeyDown={e => { if (e.key === "Enter") renameCat(cat, editingCatVal); if (e.key === "Escape") setEditingCat(null); }} style={{ ...inp, flex: 1, padding: "6px 10px" }} />
                      <button onClick={() => renameCat(cat, editingCatVal)} style={{ background: "#34c759", color: "#fff", border: "none", borderRadius: 8, padding: "6px 12px", cursor: "pointer", fontSize: 12, fontWeight: 700, fontFamily: "inherit" }}>שמור</button>
                      <button onClick={() => setEditingCat(null)} style={{ background: "#F0F0F5", color: "#6e6e73", border: "none", borderRadius: 8, padding: "6px 10px", cursor: "pointer", fontSize: 12, fontFamily: "inherit" }}>ביטול</button>
                    </div>
                  ) : (
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                      <span style={{ fontSize: 14, fontWeight: 600 }}>{cat}</span>
                      <div style={{ display: "flex", gap: 8 }}>
                        <button onClick={() => { setEditingCat(cat); setEditingCatVal(cat); }} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 16 }}>✏️</button>
                        <button onClick={() => saveCats(categories.filter((_, j) => j !== i))} style={{ background: "none", border: "none", color: "#ff3b30", cursor: "pointer", fontSize: 20 }}>×</button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Live tab — כמה שידורים חיים במקביל ── */}
        {adminTab === "live" && (
          <div>
            <div style={cardStyle}>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 14, display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ width: 10, height: 10, borderRadius: "50%", background: liveActive ? "#e50914" : "#ccc", display: "inline-block", animation: liveActive ? "livePulseDot 1.5s ease-in-out infinite" : "none" }} />
                {liveActive ? `${liveChannels.length} שידורים חיים פעילים` : "אין שידורים חיים פעילים"}
              </div>

              <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>שם הערוץ / מה משודר</label>
              <input
                value={liveNameInput}
                onChange={e => setLiveNameInput(e.target.value)}
                placeholder="למשל: ערוץ 12 - חדשות"
                style={{ ...inp, marginBottom: 10 }}
              />

              <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>קישור לשידור חי (m3u8 / iframe)</label>
              <input
                value={liveUrlInput}
                onChange={e => setLiveUrlInput(e.target.value)}
                placeholder="https://example.com/stream.m3u8"
                dir="ltr"
                style={{ ...inp, marginBottom: 10 }}
              />

              <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
                <button onClick={async () => {
                  if (!liveUrlInput.trim() || !liveNameInput.trim()) {
                    setFormStatus({ type: "error", message: "צריך גם שם וגם קישור" });
                    setTimeout(() => setFormStatus({ type: "", message: "" }), 2500);
                    return;
                  }
                  setLiveSaving(true);
                  try {
                    const all = await Movie.list("-created_date", 2000);
                    let updated;
                    if (editingLiveId) {
                      updated = all.map(m => m.id === editingLiveId
                        ? { ...m, title: liveNameInput.trim(), video_url: liveUrlInput.trim() }
                        : m);
                    } else {
                      const liveEntry = {
                        id: "live_" + crypto.randomUUID(),
                        is_live: true,
                        title: liveNameInput.trim(),
                        video_url: liveUrlInput.trim(),
                        category: "שידורים חיים",
                        created_date: new Date().toISOString(),
                      };
                      updated = [liveEntry, ...all];
                    }
                    await Movie.saveAll(updated);
                    setLiveNameInput(""); setLiveUrlInput(""); setEditingLiveId(null);
                    setFormStatus({ type: "success", message: editingLiveId ? "✅ עודכן!" : "✅ שידור חדש נוסף! פעיל עכשיו לכולם" });
                    await loadMovies();
                  } catch { setFormStatus({ type: "error", message: "שגיאה בשמירה — בדוק טוקן" }); }
                  setLiveSaving(false);
                  setTimeout(() => setFormStatus({ type: "", message: "" }), 3000);
                }} disabled={liveSaving} style={{ flex: 1, background: "#e50914", color: "#fff", border: "none", borderRadius: 12, padding: 12, fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", opacity: liveSaving ? .6 : 1 }}>
                  {liveSaving ? "⏳ שומר..." : editingLiveId ? "💾 עדכן שידור" : "🔴 הוסף שידור חי"}
                </button>
                {editingLiveId && (
                  <button onClick={() => { setEditingLiveId(null); setLiveNameInput(""); setLiveUrlInput(""); }} style={{ flex: 1, background: "#f5f5f7", color: "#333", border: "1.5px solid #d2d2d7", borderRadius: 12, padding: 12, fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>
                    ביטול
                  </button>
                )}
              </div>

              {formStatus.message && <div style={{ borderRadius: 10, padding: "10px 12px", fontSize: 12, background: formStatus.type === "success" ? "#f0fff4" : "#fff5f5", color: formStatus.type === "success" ? "#1a7a3a" : "#ff3b30", marginBottom: 12 }}>{formStatus.message}</div>}
            </div>

            {liveChannels.length > 0 && (
              <div style={cardStyle}>
                <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>שידורים פעילים ({liveChannels.length})</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {liveChannels.map(ch => (
                    <div key={ch.id} style={{ background: "#F5F5F7", borderRadius: 12, padding: 12 }}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#e50914", display: "inline-block", animation: "livePulseDot 1.5s ease-in-out infinite" }} />
                          <span style={{ fontSize: 13, fontWeight: 700 }}>{ch.title}</span>
                          <span style={{ fontSize: 11, fontWeight: 700, color: "#0071e3", background: "#e8f2ff", borderRadius: 8, padding: "2px 8px" }}>
                            👁️ {adminLiveViewerCounts[ch.id] ?? "…"} צופים
                          </span>
                        </div>
                        <div style={{ display: "flex", gap: 6 }}>
                          <button onClick={() => { setEditingLiveId(ch.id); setLiveNameInput(ch.title); setLiveUrlInput(ch.video_url); }} style={{ background: "none", border: "1.5px solid #d2d2d7", borderRadius: 8, padding: "4px 10px", cursor: "pointer", fontSize: 11, fontFamily: "inherit" }}>✏️ ערוך</button>
                          <button onClick={async () => {
                            if (!window.confirm(`לעצור את "${ch.title}"?`)) return;
                            setLiveSaving(true);
                            try {
                              const all = await Movie.list("-created_date", 2000);
                              await Movie.saveAll(all.filter(m => m.id !== ch.id));
                              await loadMovies();
                              setFormStatus({ type: "success", message: "⏹ שידור הופסק" });
                            } catch {}
                            setLiveSaving(false);
                            setTimeout(() => setFormStatus({ type: "", message: "" }), 2500);
                          }} style={{ background: "none", border: "1.5px solid #ffd0d0", borderRadius: 8, padding: "4px 10px", cursor: "pointer", fontSize: 11, color: "#ff3b30", fontFamily: "inherit" }}>⏹ עצור</button>
                        </div>
                      </div>
                      <div style={{ background: "#000", borderRadius: 10, overflow: "hidden" }}>
                        <HlsPlayer src={ch.video_url} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Settings tab ── */}
        {adminTab === "settings" && (
          <div>
            <div style={cardStyle}>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 14 }}>הגדרות</div>
              <div style={{ marginBottom: 12 }}>
                <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>GitHub Token</label>
                <input type="password"
                  defaultValue={(() => { try { return localStorage.getItem("github_token") || ""; } catch { return ""; } })()}
                  onChange={e => { try { localStorage.setItem("github_token", e.target.value); } catch {} }}
                  placeholder="ghp_..." dir="ltr" style={inp} />
              </div>
              <button onClick={() => { setFormStatus({ type: "success", message: "✅ טוקן נשמר!" }); setTimeout(() => setFormStatus({ type: "", message: "" }), 2000); }} style={{ width: "100%", background: "#24292e", color: "#fff", border: "none", borderRadius: 12, padding: 12, fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", marginBottom: 10 }}>🔑 שמור GitHub Token</button>
              <div style={{ marginBottom: 12 }}>
                <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>
                  TMDB API Key <span style={{ color: tmdbKey ? "#34c759" : "#ff3b30", fontWeight: 400 }}>{tmdbKey ? "מוגדר" : "לא מוגדר"}</span>
                </label>
                <input type="password" value={tmdbKey} onChange={e => setTmdbKey(e.target.value)} placeholder="32 תווים..." dir="ltr" style={inp} />
              </div>
              <button onClick={() => { lsSet("zovex_tmdb_key", tmdbKey); setFormStatus({ type: "success", message: "נשמר!" }); setTimeout(() => setFormStatus({ type: "", message: "" }), 2000); }} style={{ width: "100%", background: "#0071e3", color: "#fff", border: "none", borderRadius: 12, padding: 12, fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>שמור מפתח</button>
              {formStatus.message && <div style={{ marginTop: 10, borderRadius: 10, padding: "10px 12px", fontSize: 12, background: "#f0fff4", color: "#1a7a3a" }}>{formStatus.message}</div>}
            </div>
            <KalturaRefreshPanel movies={movies} cardStyle={cardStyle} dot={dot} MovieEntity={Movie} />
            <BulkImportPanel loadMovies={loadMovies} cardStyle={cardStyle} inp={inp} dot={dot} MovieEntity={Movie} />
            <MergeSeriesPanel movies={movies} loadMovies={loadMovies} cardStyle={cardStyle} inp={inp} dot={dot} MovieEntity={Movie} />
            <FindByTypePanel movies={movies} cardStyle={cardStyle} inp={inp} dot={dot} onEdit={startEdit} />
            <SeriesCategoryPanel movies={movies} categories={categories} saveCats={saveCats} loadMovies={loadMovies} cardStyle={cardStyle} inp={inp} dot={dot} MovieEntity={Movie} />
            <ExportContentPanel movies={movies} cardStyle={cardStyle} dot={dot} inp={inp} />
            <ApiKeysPanel cardStyle={cardStyle} inp={inp} dot={dot} />
            <AutoSlugPanel movies={movies} loadMovies={loadMovies} cardStyle={cardStyle} inp={inp} dot={dot} MovieEntity={Movie} />
          </div>
        )}
      </div>
    </div>
  );

  // ── Series page ──
  if (selectedSeries) {
    const series = seriesMap[selectedSeries];
    const episodes = series?.episodes || [];
    const seasonNums = [...new Set(episodes.map(e => e.season_number || 1))].sort((a, b) => a - b);
    const activeSeason = openSeasons._active !== undefined ? openSeasons._active : seasonNums[0];
    const activeEps = episodes.filter(e => (e.season_number || 1) === activeSeason).sort((a, b) => (a.episode_number || 0) - (b.episode_number || 0));
    return (
      <div style={{ background: "#fff", minHeight: "100vh", direction: "rtl", fontFamily: "Arial, sans-serif", color: "#111" }}>
        <style>{SPIN}</style>
        <button onClick={() => { setSelectedSeries(null); setOpenSeasons({}); window.history.replaceState(null, "", "/zovex/"); }} style={{ position: "fixed", top: 15, right: 15, zIndex: 100, background: "rgba(0,0,0,.7)", border: "none", color: "#fff", borderRadius: "50%", width: 44, height: 44, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer" }}>
          <ArrowRight size={22} />
        </button>
        <div style={{ position: "relative" }}>
          {series?.thumbnail_url && <img src={series.thumbnail_url} alt="" style={{ width: "100%", height: "55vw", maxHeight: 380, objectFit: "cover", display: "block" }} onError={e => e.target.style.display = "none"} />}
          <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 130, background: "linear-gradient(transparent,#fff)" }} />
        </div>
        <div style={{ padding: 20 }}>
          <h1 style={{ fontSize: 22, fontWeight: 900, margin: "0 0 8px", color: "#111" }}>{selectedSeries}</h1>
          <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
            {series?.category && <span style={{ background: "#e50914", color: "#fff", padding: "4px 12px", borderRadius: 20, fontSize: 12, fontWeight: "bold" }}>{series.category}</span>}
            <span style={{ background: "#f0f0f0", color: "#555", padding: "4px 12px", borderRadius: 20, fontSize: 12 }}>{episodes.length} פרקים</span>
            <span style={{ background: "#f0f0f0", color: "#555", padding: "4px 12px", borderRadius: 20, fontSize: 12 }}>{seasonNums.length} עונות</span>
          </div>
          {series?.description && <div style={{ margin: "0 0 20px" }}><div style={{ fontSize: 13, fontWeight: 700, color: "#111", marginBottom: 6 }}>תיאור הסדרה 🎬:</div><p style={{ fontSize: 14, lineHeight: 1.8, color: "#444", margin: 0 }}>{series.description}</p></div>}
          <div style={{ position: "relative", marginBottom: 18 }}>
            <button onClick={() => setShowSeasonMenu(s => !s)} style={{ display: "flex", alignItems: "center", gap: 10, background: "#111", color: "#fff", border: "none", borderRadius: 10, padding: "12px 18px", fontSize: 15, fontWeight: 900, cursor: "pointer", fontFamily: "inherit", minWidth: 160 }}>
              <span>עונה {activeSeason}</span><ChevronDown size={18} color="#fff" />
            </button>
            {showSeasonMenu && (
              <div style={{ position: "absolute", top: "calc(100% + 6px)", right: 0, background: "#fff", borderRadius: 12, boxShadow: "0 8px 30px rgba(0,0,0,.18)", zIndex: 50, minWidth: 160, overflow: "hidden", border: "1px solid #eee" }}>
                {seasonNums.map(s => (
                  <div key={s} onClick={() => { setShowSeasonMenu(false); if (s === activeSeason) return; setSeasonLoading(true); setTimeout(() => { setOpenSeasons(p => ({ ...p, _active: s })); setSeasonLoading(false); }, 600); }} style={{ padding: "14px 18px", fontSize: 15, fontWeight: s === activeSeason ? 900 : 500, color: s === activeSeason ? "#e50914" : "#111", cursor: "pointer", background: s === activeSeason ? "#fff5f5" : "#fff", borderBottom: "1px solid #f5f5f5" }}>
                    עונה {s}
                  </div>
                ))}
              </div>
            )}
          </div>
          {seasonLoading ? (
            <div style={{ display: "flex", justifyContent: "center", padding: "40px 0" }}>
              <div style={{ width: 40, height: 40, border: "4px solid #eee", borderTop: "4px solid #e50914", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
            </div>
          ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {activeEps.map((ep, i) => (
              <div key={ep.id} onClick={() => openWithKalturaRefresh(ep)} style={{ display: "flex", gap: 12, padding: "12px 0", borderBottom: "1px solid #eee", cursor: "pointer", alignItems: "center" }}>
                <div style={{ width: 42, height: 42, borderRadius: 10, background: "#e50914", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                  <Play size={18} fill="white" color="white" />
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#111" }}>פרק {ep.episode_number || i + 1}{ep.episode_title ? " - " + ep.episode_title : ""}</div>
                  <div style={{ fontSize: 12, color: "#888", marginTop: 2 }}>{ep.title}</div>
                </div>
              </div>
            ))}
          </div>
          )}
        </div>
      </div>
    );
  }

  // ── Movie page ──
  if (selectedMovie) {
    const baseName = (selectedMovie.title || "").replace(/\s*\d+$/, "").trim();
    const sequels = movies.filter(m => !m.series_name && m.id !== selectedMovie.id && (m.title || "").replace(/\s*\d+$/, "").trim() === baseName).sort((a, b) => (a.year || 0) - (b.year || 0));
    return (
      <div style={{ background: "#111", minHeight: "100vh", direction: "rtl", fontFamily: "Arial, sans-serif", color: "#fff" }}>
        <button onClick={() => { setSelectedMovie(null); window.history.replaceState(null, "", "/zovex/"); }} style={{ position: "fixed", top: 15, right: 15, zIndex: 100, background: "rgba(0,0,0,.7)", border: "none", color: "#fff", borderRadius: "50%", width: 44, height: 44, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer" }}>
          <ArrowRight size={22} />
        </button>
        <div style={{ position: "relative" }}>
          {selectedMovie.thumbnail_url && <img src={selectedMovie.thumbnail_url} alt="" style={{ width: "100%", height: "55vw", maxHeight: 380, objectFit: "cover", display: "block" }} onError={e => e.target.style.display = "none"} />}
          <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 130, background: "linear-gradient(transparent,#111)" }} />
        </div>
        <div style={{ padding: 20 }}>
          <h1 style={{ fontSize: 22, fontWeight: 900, margin: "0 0 8px", color: "#fff" }}>{selectedMovie.title}</h1>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
            {selectedMovie.category && <span style={{ background: "#e50914", color: "#fff", padding: "4px 12px", borderRadius: 20, fontSize: 12, fontWeight: "bold" }}>{selectedMovie.category}</span>}
            {selectedMovie.year && <span style={{ background: "#222", color: "#888", padding: "4px 12px", borderRadius: 20, fontSize: 12 }}>{selectedMovie.year}</span>}
          </div>
          {selectedMovie.description && <div style={{ margin: "0 0 20px" }}><div style={{ fontSize: 13, fontWeight: 700, color: "#ddd", marginBottom: 6 }}>תיאור הסרט 🎬:</div><p style={{ fontSize: 14, lineHeight: 1.8, color: "#bbb", margin: 0 }}>{selectedMovie.description}</p></div>}
          <button onClick={() => openWithKalturaRefresh(selectedMovie)} style={{ width: "100%", background: "#e50914", color: "#fff", border: "none", padding: 16, fontSize: 17, fontWeight: "bold", borderRadius: 12, display: "flex", alignItems: "center", justifyContent: "center", gap: 10, cursor: "pointer" }}>
            <Play fill="white" size={20} /> לצפייה עכשיו
          </button>
          {sequels.length > 0 && (
            <div style={{ marginTop: 24 }}>
              <div style={{ fontSize: 14, fontWeight: 900, color: "#fff", marginBottom: 12 }}>סרטי המשך</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {sequels.map(s => (
                  <div key={s.id} onClick={() => setSelectedMovie(s)} style={{ display: "flex", gap: 12, alignItems: "center", background: "#1a1a1a", borderRadius: 12, padding: 10, cursor: "pointer", border: "1px solid #2a2a2a" }}>
                    {s.thumbnail_url ? <img src={s.thumbnail_url} style={{ width: 48, height: 68, borderRadius: 8, objectFit: "cover", flexShrink: 0 }} alt="" onError={e => e.target.style.display = "none"} /> : <div style={{ width: 48, height: 68, borderRadius: 8, background: "#333", flexShrink: 0 }} />}
                    <div style={{ flex: 1 }}><div style={{ fontSize: 14, fontWeight: 700, color: "#fff" }}>{s.title}</div>{s.year && <div style={{ fontSize: 12, color: "#888", marginTop: 3 }}>{s.year}</div>}</div>
                    <Play size={18} fill="#e50914" color="#e50914" />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Home grid ──
  return (
    <>
      {DonationModal}

      {/* ── Live Player — נפתח מתוך קטגוריית "שידורים חיים", דרך אותו נגן מאוחד כמו כל שאר התוכן ── */}
      {showLivePlayer && (
        <CustomVideoPlayer
          movie={{ ...showLivePlayer, is_live: true }}
          onClose={() => setShowLivePlayer(null)}
        />
      )}

      <div style={{ background: "#fff", minHeight: "100vh", direction: "rtl", fontFamily: "Arial, sans-serif" }}>
        <style>{SPIN}</style>
        <header style={{ padding: "14px 14px 0", background: "#fff", boxShadow: "0 2px 10px rgba(0,0,0,.08)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
            <h1
              onClick={() => {
                setSelectedMovie(null);
                setSelectedSeries(null);
                setPlayerMovie(null);
                setSearchTerm("");
                setSelectedCategory("הכל");
                lsDel("zovex_movie");
                lsDel("zovex_series");
                lsDel("zovex_player");
                navigate("/");
              }}
              style={{ color: "#e50914", fontSize: 26, fontWeight: 900, margin: 0, flexShrink: 0, cursor: "pointer" }}>ZOVEX</h1>
            <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 8, background: "#f5f5f5", padding: "9px 14px", borderRadius: 50, border: "1px solid #eee" }}>
              <Search size={16} color="#aaa" />
              <input type="text" placeholder="חפש סרט או סדרה..." value={searchTerm} onChange={e => { setSearchTerm(e.target.value); setVisibleCount(40); }} style={{ background: "none", border: "none", outline: "none", width: "100%", fontSize: 15, color: "#333" }} />
              {searchTerm && <span onClick={() => setSearchTerm("")} style={{ cursor: "pointer", color: "#aaa", fontSize: 18 }}>×</span>}
            </div>
            {/* אזור משתמש */}
            <div ref={userMenuRef} style={{ position: "relative", flexShrink: 0 }}>
              {user ? (
                <img
                  src={user.picture} alt={user.name}
                  style={{ width: 34, height: 34, borderRadius: "50%", border: "2px solid #e50914", cursor: "pointer", display: "block" }}
                  onClick={() => setUserMenuOpen(o => !o)}
                  title={user.name}
                  onError={e => e.target.style.display = "none"}
                />
              ) : (
                <div
                  onClick={() => setUserMenuOpen(o => !o)}
                  title="אורח"
                  style={{
                    width: 34, height: 34, borderRadius: "50%",
                    background: "#f0f0f0", border: "2px solid #ddd",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: 11, fontWeight: 700, color: "#999", cursor: "pointer"
                  }}
                >
                  אורח
                </div>
              )}

              {userMenuOpen && (
                <div style={{
                  position: "absolute", top: 42, left: 0, background: "#fff",
                  borderRadius: 12, boxShadow: "0 6px 24px rgba(0,0,0,.18)",
                  border: "1px solid #eee", minWidth: 170, overflow: "hidden", zIndex: 50
                }}>
                  {user && (
                    <>
                      <div style={{ padding: "10px 14px", borderBottom: "1px solid #f0f0f0" }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: "#111", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{user.name}</div>
                        <div style={{ fontSize: 11, color: "#999", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{user.email}</div>
                      </div>
                      <div
                        onClick={() => { setSelectedCategory("היסטוריה"); setUserMenuOpen(false); refreshHistory(); }}
                        style={{ padding: "11px 14px", fontSize: 13, color: "#333", cursor: "pointer", fontWeight: 600 }}
                        onMouseEnter={e => e.currentTarget.style.background = "#f7f7f7"}
                        onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                      >
                        📋 היסטוריית צפייה
                      </div>
                    </>
                  )}
                  <div
                    onClick={() => { setUserMenuOpen(false); onLogout(); }}
                    style={{ padding: "11px 14px", fontSize: 13, color: "#e50914", cursor: "pointer", fontWeight: 700, borderTop: user ? "1px solid #f0f0f0" : "none" }}
                    onMouseEnter={e => e.currentTarget.style.background = "#fff0f0"}
                    onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                  >
                    {user ? "🚪 יציאה מהחשבון" : "🚪 יציאה ממצב אורח"}
                  </div>
                </div>
              )}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", paddingBottom: 11 }}>
            {allCategories.map(cat => {
              const isLiveCat = cat === "שידורים חיים";
              return (
                <span key={cat} onClick={() => { setSelectedCategory(cat); if (cat === "היסטוריה") refreshHistory(); }} style={{ cursor: "pointer", fontSize: 13, fontWeight: 700, color: selectedCategory === cat ? "#fff" : (isLiveCat ? "#e50914" : "#444"), background: selectedCategory === cat ? "#e50914" : (isLiveCat ? "#fff0f0" : "#f0f0f0"), border: selectedCategory === cat ? "none" : (isLiveCat ? "1px solid #e50914" : "1px solid #ddd"), borderRadius: 50, padding: "6px 16px", flexShrink: 0, boxShadow: selectedCategory === cat ? "0 2px 10px rgba(229,9,20,.35)" : "0 1px 4px rgba(0,0,0,.07)", display: "flex", alignItems: "center", gap: 5 }}>
                  {isLiveCat && <Eye size={13} />}
                  {cat}
                </span>
              );
            })}
          </div>
        </header>
        <main style={{ padding: "8px 0 100px", background: "#fff" }}>
          <NetflixRows
            movies={movies}
            seriesMap={seriesMap}
            liveChannels={liveChannels}
            allCategories={allCategories}
            selectedCategory={selectedCategory}
            searchTerm={searchTerm}
            isDesktop={isDesktop}
            handleItemClick={handleItemClick}
            onContinueWatchingClick={handleContinueWatchingClick}
            history={history}
            user={user}
          />
        </main>
        {/* Telegram bubble */}
        <div style={{ position: "fixed", bottom: 24, left: 16, zIndex: 1000, display: "flex", alignItems: "flex-end", gap: 10 }}>
          <div style={{ background: "#fff", borderRadius: "16px 16px 16px 4px", padding: "10px 14px", boxShadow: "0 4px 18px rgba(0,0,0,.13)", border: "1px solid #eee", maxWidth: 170, direction: "rtl" }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: "#111", marginBottom: 2 }}>רוצה להוסיף סרט? 🎬</div>
            <div style={{ fontSize: 11, color: "#666", lineHeight: 1.4 }}>יש בעיה באתר?<br/>דברו איתנו בטלגרם</div>
          </div>
          <a href="https://t.me/ZOVE8" target="_blank" rel="noreferrer" style={{ background: "#24A1DE", width: 50, height: 50, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", boxShadow: "0 4px 15px rgba(36,161,222,.5)", textDecoration: "none", flexShrink: 0 }}>
            <Send size={22} fill="white" />
          </a>
        </div>
      </div>
    </>
  );
}

// ═══════════════════════════════════════════════════════════════
// Admin sub-components
// ═══════════════════════════════════════════════════════════════

function AdminBrowseTab({ movies, seriesMap, existingSeriesNames, categories, onEdit }) {
  const [browsecat, setBrowsecat] = useState("הכל");
  const allCats = ["הכל", ...new Set([...categories, ...movies.map(m => m.category).filter(Boolean)])];
  const filteredSeries = existingSeriesNames.filter(n => browsecat === "הכל" || seriesMap[n]?.category === browsecat);
  const filteredMovies = movies.filter(m => !m.series_name && (browsecat === "הכל" || m.category === browsecat));
  return (
    <div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 14 }}>
        {allCats.map(c => <button key={c} onClick={() => setBrowsecat(c)} style={{ background: browsecat === c ? "#0071e3" : "#fff", border: "1.5px solid", borderColor: browsecat === c ? "#0071e3" : "#d2d2d7", color: browsecat === c ? "#fff" : "#6e6e73", borderRadius: 20, padding: "6px 14px", cursor: "pointer", fontSize: 12, fontWeight: 600, fontFamily: "inherit" }}>{c}</button>)}
      </div>
      {filteredSeries.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#6e6e73", marginBottom: 8, textTransform: "uppercase", letterSpacing: 1 }}>סדרות ({filteredSeries.length})</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10 }}>
            {filteredSeries.map(name => {
              const s = seriesMap[name];
              return (
                <div key={name} onClick={() => onEdit(s.episodes[0])} style={{ cursor: "pointer", borderRadius: 12, overflow: "hidden", aspectRatio: "2/3", background: "#e8e8e8", position: "relative" }}>
                  {s.thumbnail_url ? <img src={s.thumbnail_url} alt={name} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 24 }}>📺</div>}
                  <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, background: "linear-gradient(transparent,rgba(0,0,0,.85))", padding: "16px 8px 8px" }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: "#fff" }}>{name}</div>
                    <div style={{ fontSize: 9, color: "rgba(255,255,255,.7)" }}>{s.episodes.length} פרקים</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
      {filteredMovies.length > 0 && (
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#6e6e73", marginBottom: 8, textTransform: "uppercase", letterSpacing: 1 }}>סרטים ({filteredMovies.length})</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10 }}>
            {filteredMovies.map(m => (
              <div key={m.id} onClick={() => onEdit(m)} style={{ cursor: "pointer", borderRadius: 12, overflow: "hidden", aspectRatio: "2/3", background: "#e8e8e8", position: "relative" }}>
                {m.thumbnail_url ? <img src={m.thumbnail_url} alt={m.title} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 24 }}>🎬</div>}
                <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, background: "linear-gradient(transparent,rgba(0,0,0,.85))", padding: "16px 8px 8px" }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "#fff" }}>{m.title}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function AdminSeriesSection({ serName, episodes, onEdit, onDelete, onDeleteSeries, deleting }) {
  const [open, setOpen] = useState(false);
  const sortedEps = [...episodes].sort((a, b) => ((a.season_number || 1) - (b.season_number || 1)) || ((a.episode_number || 0) - (b.episode_number || 0)));
  return (
    <div style={{ borderTop: "1px solid #F5F5F7" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "11px 16px", cursor: "pointer" }} onClick={() => setOpen(o => !o)}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {episodes[0]?.thumbnail_url ? <img src={episodes[0].thumbnail_url} style={{ width: 32, height: 46, borderRadius: 6, objectFit: "cover", flexShrink: 0 }} alt="" /> : <div style={{ width: 32, height: 46, borderRadius: 6, background: "#F0F0F5", flexShrink: 0 }} />}
          <div>
            <div style={{ fontSize: 13, fontWeight: 700 }}>{serName}</div>
            <div style={{ fontSize: 10, color: "#6e6e73", marginTop: 1 }}>{episodes.length} פרקים</div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <button onClick={e => { e.stopPropagation(); onDeleteSeries && onDeleteSeries(serName, episodes); }} style={{ background: "none", border: "none", color: "#ff3b30", cursor: "pointer", fontSize: 18, padding: 4 }}>🗑️</button>
          {open ? <ChevronUp size={16} color="#6e6e73" /> : <ChevronDown size={16} color="#6e6e73" />}
        </div>
      </div>
      {open && sortedEps.map(ep => (
        <div key={ep.id} style={{ display: "flex", gap: 10, padding: "10px 16px", alignItems: "center", borderTop: "1px solid #F5F5F7", background: "#FAFAFA" }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>ע{ep.season_number || 1}פ{ep.episode_number || "?"} — {ep.title}</div>
            <div style={{ fontSize: 10, color: "#6e6e73", marginTop: 1 }}>{ep.type || "direct"}</div>
          </div>
          <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
            <button onClick={() => onEdit(ep)} style={{ background: "#F0F0F5", border: "1.5px solid #d2d2d7", borderRadius: 8, padding: "5px 8px", cursor: "pointer", fontSize: 14 }}>✏️</button>
            <button onClick={() => onDelete(ep.id)} disabled={deleting === ep.id} style={{ background: "#F0F0F5", border: "1.5px solid #d2d2d7", borderRadius: 8, padding: "5px 8px", cursor: "pointer", fontSize: 14 }}>
              {deleting === ep.id ? <Loader2 size={13} style={{ animation: "spin .6s linear infinite" }} /> : "🗑️"}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

function AdminCategorySection({ catName, items, onEdit, onDelete, deleting }) {
  const [open, setOpen] = useState(true);
  return (
    <div style={{ marginBottom: 12, background: "#fff", borderRadius: 16, boxShadow: "0 2px 12px rgba(0,0,0,.06)", overflow: "hidden" }}>
      <button onClick={() => setOpen(!open)} style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", background: "#F0F0F5", border: "none", cursor: "pointer", fontFamily: "inherit" }}>
        <span style={{ fontSize: 14, fontWeight: 700 }}>{catName} <span style={{ color: "#6e6e73", fontWeight: 400, fontSize: 12 }}>({items.length})</span></span>
        {open ? <ChevronUp size={16} color="#6e6e73" /> : <ChevronDown size={16} color="#6e6e73" />}
      </button>
      {open && items.map(item => (
        <div key={item.id} style={{ display: "flex", gap: 10, padding: 12, alignItems: "center", borderTop: "1px solid #F5F5F7" }}>
          {item.thumbnail_url ? <img src={item.thumbnail_url} style={{ width: 36, height: 52, borderRadius: 8, objectFit: "cover", flexShrink: 0 }} alt="" onError={e => e.target.style.display = "none"} /> : <div style={{ width: 36, height: 52, borderRadius: 8, background: "#F0F0F5", flexShrink: 0 }} />}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.title}</div>
            <div style={{ fontSize: 10, color: "#6e6e73", marginTop: 2 }}>{item.year || ""} {item.type || ""}</div>
          </div>
          <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
            <button onClick={() => onEdit(item)} style={{ background: "#F0F0F5", border: "1.5px solid #d2d2d7", borderRadius: 8, padding: "5px 8px", cursor: "pointer", fontSize: 14 }}>✏️</button>
            <button onClick={() => onDelete(item.id)} disabled={deleting === item.id} style={{ background: "#F0F0F5", border: "1.5px solid #d2d2d7", borderRadius: 8, padding: "5px 8px", cursor: "pointer", fontSize: 14 }}>
              {deleting === item.id ? <Loader2 size={13} style={{ animation: "spin .6s linear infinite" }} /> : "🗑️"}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

function KalturaRefreshPanel({ movies, cardStyle, dot, MovieEntity }) {
  const [refreshing, setRefreshing] = useState(false);
  const [status, setStatus] = useState("");
  const kalturaMovies = movies.filter(m => m.type === "kaltura" || (m.video_id || "").includes("kaltura"));
  const handleRefresh = async () => {
    setRefreshing(true); setStatus(`מרענן ${kalturaMovies.length} קישורים...`);
    let done = 0;
    for (const m of kalturaMovies) {
      try { await MovieEntity.update(m.id, { ...m, _refreshed: Date.now() }); done++; } catch {}
    }
    setStatus(`✅ רועננו ${done} קישורי Kaltura!`); setRefreshing(false); setTimeout(() => setStatus(""), 4000);
  };
  return (
    <div style={{ ...cardStyle, border: "2px solid #e50914" }}>
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8, display: "flex", alignItems: "center", color: "#e50914" }}>{dot} רענון קישורי Kaltura</div>
      <div style={{ fontSize: 11, color: "#6e6e73", marginBottom: 14 }}>יש כרגע <strong>{kalturaMovies.length}</strong> קישורי Kaltura.</div>
      <button onClick={handleRefresh} disabled={refreshing || !kalturaMovies.length} style={{ width: "100%", background: refreshing ? "#aaa" : "#e50914", color: "#fff", border: "none", borderRadius: 12, padding: 13, fontSize: 14, fontWeight: 700, cursor: refreshing ? "default" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
        {refreshing ? <><Loader2 size={14} style={{ animation: "spin .6s linear infinite" }} /> מרענן...</> : "🔄 רענן קישורים עכשיו"}
      </button>
      {status && <div style={{ marginTop: 10, borderRadius: 10, padding: "10px 12px", fontSize: 12, background: "#f0fff4", color: "#1a7a3a" }}>{status}</div>}
    </div>
  );
}

function BulkImportPanel({ loadMovies, cardStyle, inp, dot, MovieEntity }) {
  const [text, setText] = useState("");
  const [status, setStatus] = useState("");
  const [importing, setImporting] = useState(false);
  const handleImport = async () => {
    let rows;
    try { rows = JSON.parse(text); if (!Array.isArray(rows)) throw new Error(); } catch { setStatus("❌ JSON לא תקין — נדרש מערך"); return; }
    setImporting(true); setStatus(`מייבא ${rows.length} פריטים...`);
    let done = 0;
    for (const row of rows) {
      try { await MovieEntity.create(row); done++; } catch {}
    }
    await loadMovies(); setStatus(`✅ יובאו ${done} פריטים!`); setImporting(false); setText(""); setTimeout(() => setStatus(""), 4000);
  };
  return (
    <div style={{ ...cardStyle, border: "2px solid #ff9500" }}>
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8, display: "flex", alignItems: "center", color: "#ff9500" }}>{dot} ייבוא מרוכז (JSON)</div>
      <div style={{ fontSize: 11, color: "#6e6e73", marginBottom: 12 }}>הדבק מערך JSON של תכנים לייבוא מרוכז</div>
      <textarea value={text} onChange={e => setText(e.target.value)} rows={5} placeholder={'[{"title":"...", "category":"...", "video_url":"..."}]'} dir="ltr" style={{ ...inp, resize: "vertical", marginBottom: 10, fontFamily: "monospace", fontSize: 11 }} />
      <button onClick={handleImport} disabled={importing || !text.trim()} style={{ width: "100%", background: importing ? "#aaa" : "#ff9500", color: "#fff", border: "none", borderRadius: 12, padding: 13, fontSize: 14, fontWeight: 700, cursor: importing ? "default" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
        {importing ? <><Loader2 size={14} style={{ animation: "spin .6s linear infinite" }} /> מייבא...</> : "📥 ייבא JSON"}
      </button>
      {status && <div style={{ marginTop: 10, borderRadius: 10, padding: "10px 12px", fontSize: 12, background: status.startsWith("✅") ? "#f0fff4" : "#fff5f5", color: status.startsWith("✅") ? "#1a7a3a" : "#c0392b" }}>{status}</div>}
    </div>
  );
}

function MergeSeriesPanel({ movies, loadMovies, cardStyle, inp, dot, MovieEntity }) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [status, setStatus] = useState("");
  const [merging, setMerging] = useState(false);
  const seriesNames = [...new Set(movies.filter(m => m.series_name).map(m => m.series_name))].sort();
  const handleMerge = async () => {
    if (!from || !to || from === to) { setStatus("⚠️ בחר שתי סדרות שונות"); return; }
    if (!window.confirm(`למזג "${from}" לתוך "${to}"?`)) return;
    setMerging(true); setStatus("ממזג...");
    try {
      const all = await MovieEntity.list("-created_date", 2000);
      await MovieEntity.saveAll(all.map(m => m.series_name === from ? { ...m, series_name: to } : m));
      await loadMovies(); setStatus(`✅ מוזג!`);
    } catch { setStatus("❌ שגיאה"); }
    setMerging(false); setTimeout(() => setStatus(""), 3000);
  };
  return (
    <div style={{ ...cardStyle, border: "2px solid #af52de" }}>
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8, display: "flex", alignItems: "center", color: "#af52de" }}>{dot} מיזוג סדרות</div>
      <div style={{ fontSize: 11, color: "#6e6e73", marginBottom: 14 }}>מזג פרקים מסדרה אחת לתוך אחרת</div>
      <div style={{ marginBottom: 10 }}>
        <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>מ-סדרה (תימחק)</label>
        <select value={from} onChange={e => setFrom(e.target.value)} style={inp}><option value="">בחר...</option>{seriesNames.map(n => <option key={n} value={n}>{n}</option>)}</select>
      </div>
      <div style={{ marginBottom: 14 }}>
        <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>לתוך סדרה (תישאר)</label>
        <select value={to} onChange={e => setTo(e.target.value)} style={inp}><option value="">בחר...</option>{seriesNames.map(n => <option key={n} value={n}>{n}</option>)}</select>
      </div>
      <button onClick={handleMerge} disabled={merging} style={{ width: "100%", background: merging ? "#aaa" : "#af52de", color: "#fff", border: "none", borderRadius: 12, padding: 13, fontSize: 14, fontWeight: 700, cursor: merging ? "default" : "pointer", fontFamily: "inherit" }}>
        {merging ? "ממזג..." : "🔀 מזג סדרות"}
      </button>
      {status && <div style={{ marginTop: 10, borderRadius: 10, padding: "10px 12px", fontSize: 12, background: status.startsWith("✅") ? "#f0fff4" : "#fff5f5", color: status.startsWith("✅") ? "#1a7a3a" : "#c0392b" }}>{status}</div>}
    </div>
  );
}

function FindByTypePanel({ movies, cardStyle, inp, dot, onEdit }) {
  const [selectedType, setSelectedType] = useState("kaltura");
  const [selectedSeries, setSelectedSeries] = useState("הכל");
  const typeLabels = { kaltura: "Kaltura", youtube: "YouTube", drive: "Google Drive", dailymotion: "Dailymotion", rumble: "Rumble", archive: "Archive.org", kan: "כאן", okru: "OK.ru", direct: "קישור ישיר" };
  const seriesNames = [...new Set(movies.filter(m => m.series_name).map(m => m.series_name))].sort();
  const results = movies.filter(m => m.type === selectedType && (selectedSeries === "הכל" || m.series_name === selectedSeries)).sort((a, b) => (a.season_number || 1) - (b.season_number || 1) || (a.episode_number || 0) - (b.episode_number || 0));
  return (
    <div style={{ ...cardStyle, border: "2px solid #ff3b30" }}>
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8, display: "flex", alignItems: "center", color: "#ff3b30" }}>{dot} מצא פרקים לפי סוג קישור</div>
      <div style={{ fontSize: 11, color: "#6e6e73", marginBottom: 12 }}>מצא את כל הפרקים עם סוג קישור מסוים כדי לעדכן אותם</div>
      <div style={{ marginBottom: 10 }}>
        <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>סדרה</label>
        <select value={selectedSeries} onChange={e => setSelectedSeries(e.target.value)} style={inp}>
          <option value="הכל">כל הסדרות והסרטים</option>
          {seriesNames.map(n => <option key={n} value={n}>{n}</option>)}
        </select>
      </div>
      <div style={{ marginBottom: 14 }}>
        <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>סוג קישור ({results.length} תוצאות)</label>
        <select value={selectedType} onChange={e => setSelectedType(e.target.value)} style={inp}>
          {Object.entries(typeLabels).map(([val, label]) => <option key={val} value={val}>{label}</option>)}
        </select>
      </div>
      {results.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 200, overflowY: "auto" }}>
          {results.map(m => (
            <div key={m.id} onClick={() => onEdit(m)} style={{ display: "flex", gap: 10, padding: "8px 10px", background: "#F5F5F7", borderRadius: 10, cursor: "pointer", alignItems: "center" }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.title}</div>
                {m.series_name && <div style={{ fontSize: 10, color: "#6e6e73" }}>ע{m.season_number}פ{m.episode_number} | {m.series_name}</div>}
              </div>
              <span style={{ fontSize: 12, color: "#0071e3", flexShrink: 0 }}>✏️</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SeriesCategoryPanel({ movies, categories, saveCats, loadMovies, cardStyle, inp, dot, MovieEntity }) {
  const [bulkSeries, setBulkSeries] = useState("");
  const [bulkCat, setBulkCat] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const seriesNames = [...new Set(movies.filter(m => m.series_name).map(m => m.series_name))].sort();
  const handleAssign = async () => {
    if (!bulkSeries || !bulkCat) { setStatus("⚠️ בחר סדרה וקטגוריה"); return; }
    setLoading(true); setStatus("מעדכן...");
    try {
      const all = await MovieEntity.list("-created_date", 2000);
      await MovieEntity.saveAll(all.map(m => m.series_name === bulkSeries ? { ...m, category: bulkCat } : m));
      await loadMovies(); setStatus(`✅ קטגוריה "${bulkCat}" הוגדרה לסדרה "${bulkSeries}"`);
    } catch { setStatus("❌ שגיאה"); }
    setLoading(false); setTimeout(() => setStatus(""), 4000);
  };
  return (
    <div style={{ ...cardStyle, border: "2px solid #5e5ce6" }}>
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8, display: "flex", alignItems: "center", color: "#5e5ce6" }}>{dot} הגדר קטגוריה לסדרה שלמה</div>
      <div style={{ fontSize: 11, color: "#6e6e73", marginBottom: 14 }}>כל הפרקים יתעדכנו בבת אחת</div>
      <div style={{ marginBottom: 10 }}>
        <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>סדרה</label>
        <select value={bulkSeries} onChange={e => setBulkSeries(e.target.value)} style={inp}><option value="">בחר...</option>{seriesNames.map(n => <option key={n} value={n}>{n}</option>)}</select>
      </div>
      <div style={{ marginBottom: 14 }}>
        <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>קטגוריה</label>
        <select value={bulkCat} onChange={e => setBulkCat(e.target.value)} style={inp}><option value="">בחר...</option>{categories.map(c => <option key={c} value={c}>{c}</option>)}</select>
      </div>
      <button onClick={handleAssign} disabled={loading} style={{ width: "100%", background: loading ? "#aaa" : "#5e5ce6", color: "#fff", border: "none", borderRadius: 12, padding: 13, fontSize: 14, fontWeight: 700, cursor: loading ? "default" : "pointer", fontFamily: "inherit" }}>
        {loading ? "מעדכן..." : "🏷️ עדכן קטגוריה לסדרה"}
      </button>
      {status && <div style={{ marginTop: 10, borderRadius: 10, padding: "10px 12px", fontSize: 12, background: status.startsWith("✅") ? "#f0fff4" : "#fff5f5", color: status.startsWith("✅") ? "#1a7a3a" : "#c0392b" }}>{status}</div>}
    </div>
  );
}

function ExportContentPanel({ movies, cardStyle, dot, inp }) {
  const [filter, setFilter] = useState("הכל");
  const [status, setStatus] = useState("");
  const categories = ["הכל", ...new Set(movies.map(m => m.category).filter(Boolean))];
  const filtered = filter === "הכל" ? movies : movies.filter(m => m.category === filter);
  const exportJSON = () => {
    const b = new Blob([JSON.stringify(filtered, null, 2)], { type: "application/json" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = `zovex_${filter}_${Date.now()}.json`; a.click();
    setStatus(`✅ יוצאו ${filtered.length} תכנים`); setTimeout(() => setStatus(""), 3000);
  };
  const exportCSV = () => {
    const headers = ["id", "title", "year", "category", "type", "series_name", "season_number", "episode_number", "video_id"];
    const rows = filtered.map(m => headers.map(h => JSON.stringify(m[h] ?? "")).join(","));
    const b = new Blob([[headers.join(","), ...rows].join("\n")], { type: "text/csv;charset=utf-8;" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = `zovex_${filter}_${Date.now()}.csv`; a.click();
    setStatus(`✅ יוצאו ${filtered.length} תכנים (CSV)`); setTimeout(() => setStatus(""), 3000);
  };
  return (
    <div style={{ ...cardStyle, border: "2px solid #34c759" }}>
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8, display: "flex", alignItems: "center", color: "#34c759" }}>{dot} ייצוא תכנים</div>
      <div style={{ fontSize: 11, color: "#6e6e73", marginBottom: 14 }}>{movies.length} תכנים במאגר</div>
      <div style={{ marginBottom: 14 }}>
        <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>סנן לפי קטגוריה</label>
        <select value={filter} onChange={e => setFilter(e.target.value)} style={inp}>{categories.map(c => <option key={c} value={c}>{c}</option>)}</select>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={exportJSON} style={{ flex: 1, background: "#34c759", color: "#fff", border: "none", borderRadius: 12, padding: 12, fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>📤 JSON ({filtered.length})</button>
        <button onClick={exportCSV} style={{ flex: 1, background: "#F0F0F5", color: "#1c1c1e", border: "1.5px solid #d2d2d7", borderRadius: 12, padding: 12, fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>📊 CSV</button>
      </div>
      {status && <div style={{ marginTop: 10, borderRadius: 10, padding: "10px 12px", fontSize: 12, background: "#f0fff4", color: "#1a7a3a" }}>{status}</div>}
    </div>
  );
}

function ApiKeysPanel({ cardStyle, inp, dot }) {
  const [keys, setKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [newKeyName, setNewKeyName] = useState("");
  const [creating, setCreating] = useState(false);
  const [copiedId, setCopiedId] = useState(null);
  const [visibleKeys, setVisibleKeys] = useState({});
  const [status, setStatus] = useState({ type: "", message: "" });

  const load = async () => {
    setLoading(true);
    try { setKeys((await ApiKey.list("-created_date", 100)) || []); }
    catch { setStatus({ type: "error", message: "שגיאה בטעינת מפתחות" }); }
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const genKey = () => {
    const part = () => (crypto.randomUUID?.() || Math.random().toString(36).slice(2)).replace(/-/g, "");
    return "zx_" + part() + part();
  };

  const handleCreate = async () => {
    if (!newKeyName.trim()) { setStatus({ type: "error", message: "הכנס שם למפתח" }); return; }
    setCreating(true);
    try {
      await ApiKey.create({ key: genKey(), name: newKeyName.trim(), active: true });
      setNewKeyName("");
      setStatus({ type: "success", message: "המפתח נוצר!" });
      load();
      setTimeout(() => setStatus({ type: "", message: "" }), 3000);
    } catch { setStatus({ type: "error", message: "שגיאה ביצירת מפתח" }); }
    setCreating(false);
  };

  const handleDelete = async (id) => {
    if (!window.confirm("למחוק מפתח זה? אתרים שמשתמשים בו יאבדו גישה.")) return;
    try { await ApiKey.delete(id); load(); } catch {}
  };

  const toggleActive = async (k) => {
    try { await ApiKey.update(k.id, { active: !k.active }); load(); } catch {}
  };

  const copyKey = (k) => {
    navigator.clipboard?.writeText(k.key);
    setCopiedId(k.id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const apiUrl = `${window.location.origin}/zovex/api`;

  return (
    <div style={{ ...cardStyle, border: "2px solid #0071e3" }}>
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6, display: "flex", alignItems: "center", color: "#0071e3" }}>
        {dot} מפתחות API חיצוניים
      </div>
      <div style={{ fontSize: 11, color: "#6e6e73", marginBottom: 14, lineHeight: 1.7 }}>
        צור מפתח ושלח אותו למי שאתה סומך עליו — הוא יוכל למשוך את כל מאגר הסרטים שלך.<br/>
        <span style={{ fontFamily: "monospace", fontSize: 10, color: "#0071e3", direction: "ltr", display: "inline-block" }}>
          GET {apiUrl}?key=YOUR_KEY
        </span>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
        <input value={newKeyName} onChange={e => setNewKeyName(e.target.value)} placeholder="שם למפתח (למשל: האתר של דני)" style={{ ...inp, flex: 1 }} onKeyDown={e => e.key === "Enter" && handleCreate()} />
        <button onClick={handleCreate} disabled={creating} style={{ background: "#0071e3", color: "#fff", border: "none", borderRadius: 10, padding: "0 16px", fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
          {creating ? <Loader2 size={14} style={{ animation: "spin .6s linear infinite" }} /> : "➕"} צור
        </button>
      </div>

      {loading ? (
        <div style={{ textAlign: "center", padding: 20, color: "#aaa", fontSize: 13 }}>טוען...</div>
      ) : keys.length === 0 ? (
        <div style={{ textAlign: "center", padding: 20, color: "#aaa", fontSize: 13 }}>אין מפתחות עדיין — צור אחד כדי להתחיל</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {keys.map(k => (
            <div key={k.id} style={{ background: "#F5F5F7", borderRadius: 12, padding: 12, border: `1.5px solid ${k.active ? "#d2d2d7" : "#ffd0d0"}` }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 13, fontWeight: 700 }}>{k.name}</span>
                  <span style={{ fontSize: 10, color: k.active ? "#34c759" : "#ff3b30", fontWeight: 700, background: k.active ? "#e8f9ee" : "#fff0f0", padding: "2px 8px", borderRadius: 8 }}>{k.active ? "פעיל" : "מושבת"}</span>
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  <button onClick={() => toggleActive(k)} style={{ background: "none", border: "1.5px solid #d2d2d7", borderRadius: 8, padding: "4px 10px", cursor: "pointer", fontSize: 11, fontFamily: "inherit", color: "#6e6e73" }}>{k.active ? "השבת" : "הפעל"}</button>
                  <button onClick={() => handleDelete(k.id)} style={{ background: "none", border: "1.5px solid #d2d2d7", borderRadius: 8, padding: "4px 8px", cursor: "pointer", color: "#ff3b30" }}>🗑️</button>
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, background: "#fff", borderRadius: 8, padding: "8px 10px", border: "1px solid #e8e8e8" }}>
                <code style={{ flex: 1, fontSize: 11, fontFamily: "monospace", color: "#333", direction: "ltr", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {visibleKeys[k.id] ? k.key : "••••••••••••••••••••••••••••••"}
                </code>
                <button onClick={() => setVisibleKeys(s => ({ ...s, [k.id]: !s[k.id] }))} style={{ background: "none", border: "none", cursor: "pointer", padding: 4 }}>
                  {visibleKeys[k.id] ? "🙈" : "👁️"}
                </button>
                <button onClick={() => copyKey(k)} style={{ background: "none", border: "none", cursor: "pointer", padding: 4 }}>
                  {copiedId === k.id ? "✅" : "📋"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
      {status.message && (
        <div style={{ marginTop: 10, borderRadius: 10, padding: "10px 12px", fontSize: 12, background: status.type === "success" ? "#f0fff4" : "#fff5f5", color: status.type === "success" ? "#1a7a3a" : "#ff3b30" }}>
          {status.message}
        </div>
      )}
    </div>
  );
}

function AutoSlugPanel({ movies, loadMovies, cardStyle, inp, dot, MovieEntity }) {
  const [groqKey, setGroqKey] = useState(() => ls("zovex_groq_key", ""));
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [status, setStatus] = useState({ type: "", message: "" });
  const [log, setLog] = useState([]);

  const saveKey = () => {
    lsSet("zovex_groq_key", groqKey);
    setStatus({ type: "success", message: "מפתח נשמר!" });
    setTimeout(() => setStatus({ type: "", message: "" }), 2000);
  };

  // אוסף את כל הסדרות/סרטים שעדיין אין להם custom_slug
  const getTargets = () => {
    const seen = new Set();
    const targets = [];
    movies.forEach(m => {
      const name = m.series_name || m.title;
      if (!name || seen.has(name)) return;
      if (m.custom_slug) { seen.add(name); return; }
      seen.add(name);
      targets.push({ name, isSeries: !!m.series_name });
    });
    return targets;
  };

  const askGroq = async (hebrewName) => {
    const res = await fetch("https://api.groq.com/openai/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${groqKey}` },
      body: JSON.stringify({
        model: "llama-3.3-70b-versatile",
        messages: [{
          role: "user",
          content: `תרגם את השם העברי הבא לכתובת URL קצרה באנגלית (slug). חוקים: רק אותיות אנגליות קטנות, מספרים, ומקף (-). בלי רווחים, בלי תווים מיוחדים, בלי שנה אם אפשר. החזר רק את ה-slug, בלי הסברים, בלי מירכאות. השם: "${hebrewName}"`
        }],
        temperature: 0.3,
        max_tokens: 30,
      })
    });
    if (!res.ok) throw new Error(`Groq error ${res.status}`);
    const data = await res.json();
    let slug = data.choices?.[0]?.message?.content?.trim() || "";
    slug = slug.toLowerCase().replace(/[^a-z0-9-]/g, "").replace(/^-+|-+$/g, "");
    return slug;
  };

  const handleRun = async () => {
    if (!groqKey) { setStatus({ type: "error", message: "הכנס מפתח Groq קודם" }); return; }
    const targets = getTargets();
    if (targets.length === 0) { setStatus({ type: "success", message: "לכל התכנים יש כבר כתובת URL!" }); return; }

    setRunning(true);
    setLog([]);
    setProgress({ done: 0, total: targets.length });

    const all = await MovieEntity.list("-created_date", 2000);
    let updated = [...all];
    const usedSlugs = new Set(all.map(m => m.custom_slug).filter(Boolean));

    for (let i = 0; i < targets.length; i++) {
      const t = targets[i];
      try {
        let slug = await askGroq(t.name);
        if (!slug) slug = "item-" + Math.random().toString(36).slice(2, 8);
        // וודא ייחודיות
        let finalSlug = slug;
        let counter = 2;
        while (usedSlugs.has(finalSlug)) { finalSlug = `${slug}-${counter}`; counter++; }
        usedSlugs.add(finalSlug);

        updated = updated.map(m => {
          const name = m.series_name || m.title;
          return name === t.name ? { ...m, custom_slug: finalSlug } : m;
        });

        setLog(prev => [...prev, { name: t.name, slug: finalSlug, ok: true }]);
      } catch (e) {
        setLog(prev => [...prev, { name: t.name, slug: null, ok: false, error: e.message }]);
      }
      setProgress({ done: i + 1, total: targets.length });
      await new Promise(r => setTimeout(r, 350)); // הגנה מ-rate limit
    }

    try {
      await MovieEntity.saveAll(updated);
      setStatus({ type: "success", message: `✅ הושלם! ${targets.length} כתובות URL נוצרו ונשמרו` });
      await loadMovies();
    } catch {
      setStatus({ type: "error", message: "השמירה נכשלה — נסה שוב" });
    }
    setRunning(false);
  };

  const targetsCount = getTargets().length;

  return (
    <div style={{ ...cardStyle, border: "2px solid #ff9500" }}>
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8, display: "flex", alignItems: "center", color: "#ff9500" }}>
        {dot} תרגום אוטומטי לכתובות URL (Groq AI)
      </div>
      <div style={{ fontSize: 11, color: "#6e6e73", marginBottom: 14, lineHeight: 1.7 }}>
        ייצור אוטומטי של כתובות URL באנגלית לכל הסדרות והסרטים שעדיין אין להם.<br/>
        כרגע <strong>{targetsCount}</strong> פריטים זקוקים לכתובת URL.
      </div>

      <div style={{ marginBottom: 12 }}>
        <label style={{ display: "block", fontSize: 11, color: "#6e6e73", marginBottom: 5, fontWeight: 700 }}>Groq API Key</label>
        <input type="password" value={groqKey} onChange={e => setGroqKey(e.target.value)} placeholder="gsk_..." dir="ltr" style={inp} />
      </div>
      <button onClick={saveKey} style={{ width: "100%", background: "#F0F0F5", color: "#1c1c1e", border: "1.5px solid #d2d2d7", borderRadius: 10, padding: 10, fontSize: 12, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", marginBottom: 14 }}>
        שמור מפתח
      </button>

      <button onClick={handleRun} disabled={running || targetsCount === 0} style={{ width: "100%", background: running ? "#aaa" : "#ff9500", color: "#fff", border: "none", borderRadius: 12, padding: 13, fontSize: 14, fontWeight: 700, cursor: running ? "default" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
        {running
          ? <><Loader2 size={14} style={{ animation: "spin .6s linear infinite" }} /> מתרגם... ({progress.done}/{progress.total})</>
          : `🌐 תרגם ${targetsCount} פריטים אוטומטית`}
      </button>

      {running && (
        <div style={{ marginTop: 10, height: 6, background: "#F0F0F5", borderRadius: 4, overflow: "hidden" }}>
          <div style={{ height: "100%", background: "#ff9500", width: `${(progress.done / Math.max(progress.total, 1)) * 100}%`, transition: "width 0.3s" }} />
        </div>
      )}

      {log.length > 0 && (
        <div style={{ marginTop: 12, maxHeight: 200, overflowY: "auto", display: "flex", flexDirection: "column", gap: 4 }}>
          {log.map((l, i) => (
            <div key={i} style={{ fontSize: 11, padding: "6px 10px", borderRadius: 8, background: l.ok ? "#f0fff4" : "#fff5f5", display: "flex", justifyContent: "space-between", gap: 8 }}>
              <span style={{ color: "#333", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.name}</span>
              <span style={{ color: l.ok ? "#1a7a3a" : "#c0392b", fontFamily: "monospace", direction: "ltr", flexShrink: 0 }}>
                {l.ok ? l.slug : "שגיאה"}
              </span>
            </div>
          ))}
        </div>
      )}

      {status.message && (
        <div style={{ marginTop: 10, borderRadius: 10, padding: "10px 12px", fontSize: 12, background: status.type === "success" ? "#f0fff4" : "#fff5f5", color: status.type === "success" ? "#1a7a3a" : "#ff3b30" }}>
          {status.message}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════
// NetflixRows — שורות גלילה אופקיות (Netflix-style)
// רקע לבן, כותרת קטגוריה + carousel לכל קטגוריה
// ═══════════════════════════════════════════════════════
function NetflixCard({ item, isSer, isLive, onClick, cardW, cardH }) {
  const title = isSer ? item.name : item.title;
  return (
    <div onClick={() => onClick(item, isSer)} style={{ flexShrink: 0, width: cardW, cursor: "pointer", direction: "rtl" }}>
      <div style={{ width: cardW, height: cardH, borderRadius: 12, overflow: "hidden", background: isLive ? "#1a1a1a" : "#e8e8e8", position: "relative", border: isLive ? "2px solid #e50914" : "none", transition: "transform .18s", boxShadow: "0 2px 8px rgba(0,0,0,.10)" }}
        onMouseEnter={e => { e.currentTarget.style.transform = "scale(1.04)"; e.currentTarget.style.boxShadow = "0 8px 24px rgba(0,0,0,.18)"; }}
        onMouseLeave={e => { e.currentTarget.style.transform = "scale(1)"; e.currentTarget.style.boxShadow = "0 2px 8px rgba(0,0,0,.10)"; }}>
        {isLive ? (
          <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8, background: "linear-gradient(135deg,#1a1a1a,#2a0a0c)" }}>
            <Eye size={30} color="#e50914" strokeWidth={2} />
            <span style={{ fontSize: 10, color: "#fff", fontWeight: 700, textAlign: "center", padding: "0 8px" }}>שידור חי</span>
          </div>
        ) : item.thumbnail_url ? (
          <img src={item.thumbnail_url} alt={title} loading="lazy" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} onError={e => e.target.style.display = "none"} />
        ) : (
          <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 28, background: "#f0f0f0", color: "#aaa" }}>🎬</div>
        )}
        {isSer && !isLive && <div style={{ position: "absolute", top: 7, right: 7, background: "rgba(0,0,0,.65)", borderRadius: 7, padding: "2px 7px", fontSize: 9, color: "#fff", fontWeight: 700 }}>סדרה</div>}
        {isLive && (
          <div style={{ position: "absolute", top: 7, right: 7, background: "#e50914", borderRadius: 7, padding: "2px 7px", fontSize: 9, color: "#fff", fontWeight: 900, display: "flex", alignItems: "center", gap: 3 }}>
            <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#fff", display: "inline-block", animation: "livePulseDot 1.5s ease-in-out infinite" }} />
            LIVE
          </div>
        )}
      </div>
      <div style={{ fontSize: 12, fontWeight: 700, marginTop: 6, color: "#111", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", textAlign: "right", padding: "0 2px" }}>{title}</div>
    </div>
  );
}

function NetflixRow({ title, items, isDesktop, handleItemClick, isLiveRow }) {
  const rowRef = React.useRef(null);
  const cardW = isDesktop ? 170 : 130;
  const cardH = isDesktop ? 240 : 185;

  const scroll = (dir) => {
    if (!rowRef.current) return;
    const amount = cardW * 3 + 24;
    rowRef.current.scrollBy({ left: dir === "right" ? -amount : amount, behavior: "smooth" });
  };

  if (!items || items.length === 0) return null;

  return (
    <div style={{ marginBottom: isDesktop ? 36 : 28, direction: "rtl" }}>
      {/* כותרת שורה */}
      <div style={{ padding: "0 16px", marginBottom: 12, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {isLiveRow && <Eye size={16} color="#e50914" />}
          <h2 style={{ fontSize: isDesktop ? 18 : 16, fontWeight: 900, color: "#111", margin: 0 }}>{title}</h2>
          <span style={{ fontSize: 12, color: "#888" }}>({items.length})</span>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button onClick={() => scroll("right")} style={{ background: "#f0f0f0", border: "none", borderRadius: "50%", width: 30, height: 30, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14 }}>›</button>
          <button onClick={() => scroll("left")} style={{ background: "#f0f0f0", border: "none", borderRadius: "50%", width: 30, height: 30, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14 }}>‹</button>
        </div>
      </div>
      {/* הcarousel */}
      <div ref={rowRef} style={{ display: "flex", gap: 10, overflowX: "auto", scrollbarWidth: "none", msOverflowStyle: "none", padding: "4px 16px 8px", direction: "ltr" }}>
        {items.map((item) => {
          const isSer = !!item.episodes;
          const isLive = !!item.is_live;
          return (
            <NetflixCard
              key={isSer ? "s-" + item.name : item.id}
              item={item}
              isSer={isSer}
              isLive={isLive}
              onClick={handleItemClick}
              cardW={cardW}
              cardH={cardH}
            />
          );
        })}
      </div>
    </div>
  );
}

function NetflixRows({ movies, seriesMap, liveChannels, allCategories, selectedCategory, searchTerm, isDesktop, handleItemClick, onContinueWatchingClick, history, user }) {
  const q = searchTerm.toLowerCase();

  // בנה map: קטגוריה → פריטים
  const buildItems = (cat) => {
    const regularMovies = movies.filter(m =>
      !m.series_name &&
      (m.title || "").toLowerCase().includes(q) &&
      (cat === "הכל" || m.category === cat)
    );
    const seen = {};
    const seriesList = [];
    movies.forEach(m => {
      if (!m.series_name || seen[m.series_name]) return;
      const matchQ = m.series_name.toLowerCase().includes(q) || (m.title || "").toLowerCase().includes(q);
      const matchC = cat === "הכל" || m.category === cat;
      if (matchQ && matchC) { seen[m.series_name] = true; seriesList.push(seriesMap[m.series_name]); }
    });
    return [...seriesList, ...regularMovies];
  };

  const liveItems = liveChannels.filter(ch => ch.title.toLowerCase().includes(q)).map(ch => ({ ...ch, is_live: true }));

  // קבע אילו שורות להציג לפי selectedCategory
  let rowsToShow = [];
  if (selectedCategory === "הכל" || selectedCategory === "שידורים חיים") {
    // שורה ראשונה: לייבים (אם יש)
    if (liveItems.length > 0) {
      rowsToShow.push({ title: "👁️ שידורים חיים", items: liveItems, isLive: true });
    }
  }

  if (selectedCategory === "הכל") {
    // כל הקטגוריות כשורות נפרדות
    const cats = allCategories.filter(c => c !== "הכל" && c !== "שידורים חיים");
    cats.forEach(cat => {
      const items = buildItems(cat);
      if (items.length > 0) rowsToShow.push({ title: cat, items, isLive: false });
    });
  } else if (selectedCategory !== "שידורים חיים" && selectedCategory !== "היסטוריה") {
    // קטגוריה ספציפית — שורה אחת
    const items = buildItems(selectedCategory);
    if (items.length > 0) rowsToShow.push({ title: selectedCategory, items, isLive: false });
  }

  // שורת "המשך צפייה" — רק למחוברים עם היסטוריה
  const continueWatchingItems = user && history && history.length > 0
    ? history.slice(0, 10).map(h => {
        const found = movies.find(m => m.id === h.media_id) ||
          Object.values(seriesMap).flatMap(s => s.episodes).find(e => e.id === h.media_id);
        return found ? found : null;
      }).filter(Boolean)
    : [];

  // אם בוחרים "היסטוריה" — הצג שתי שורות: המשך צפייה, ואחריה היסטוריה מלאה
  // חשוב: הבדיקה הזו חייבת להיות *לפני* ה-early-return של "לא נמצאו תוצאות"
  // למטה — כי "היסטוריה" היא טאב וירטואלי, לא קטגוריית תוכן אמיתית, אז
  // rowsToShow תמיד ריק בשבילה ובלי הסדר הזה היינו נתקעים תמיד ב"לא נמצאו
  // תוצאות" בלי להגיע לקוד שמטפל בהיסטוריה בפועל (זה בדיוק מה שקרה).
  if (selectedCategory === "היסטוריה") {
    // דיאגנוסטיקה זמנית על המסך (בלי צורך ב-DevTools) — מראה בדיוק איפה זה נשבר:
    // אם "מהשרת" הוא 0 → הבעיה בטעינה/שמירה מהשרת. אם "מהשרת" > 0 אבל "הותאם" הוא 0 →
    // הבעיה בהתאמה בין media_id שנשמר לבין movie.id הנוכחי (למשל תוכן שנמחק/שונה).
    const debugLine = `דיאגנוסטיקה: מהשרת ${history?.length || 0} | הותאם לסרט קיים ${continueWatchingItems.length}`;
    return (
      <div style={{ paddingTop: 8 }}>
        <div style={{ fontSize: 11, color: "#e50914", textAlign: "center", padding: "6px 12px", fontFamily: "monospace", direction: "ltr" }}>
          {debugLine}
        </div>
        {continueWatchingItems.length > 0 ? (
          <>
            <NetflixRow title="▶️ המשך צפייה" items={continueWatchingItems} isDesktop={isDesktop} handleItemClick={onContinueWatchingClick} isLiveRow={false} />
            <NetflixRow title="📋 היסטוריית צפייה" items={continueWatchingItems} isDesktop={isDesktop} handleItemClick={onContinueWatchingClick} isLiveRow={false} />
          </>
        ) : (
          <div style={{ textAlign: "center", padding: "60px 20px", color: "#aaa" }}>
            <p style={{ fontSize: 18 }}>עדיין לא צפית בשום דבר</p>
            <p style={{ fontSize: 13, marginTop: 8 }}>ההיסטוריה שלך תופיע כאן</p>
          </div>
        )}
      </div>
    );
  }

  if (rowsToShow.length === 0) {
    return <div style={{ textAlign: "center", padding: "60px 20px", color: "#aaa" }}><p style={{ fontSize: 18 }}>לא נמצאו תוצאות</p></div>;
  }

  return (
    <div style={{ paddingTop: 8 }}>
      {/* שורת "המשך צפייה" מוצגת אך ורק בתוך קטגוריית "היסטוריה" (למעלה) —
          לא במסך הראשי/"הכל" ולא בשום קטגוריה אחרת */}
      {rowsToShow.map(row => (
        <NetflixRow
          key={row.title}
          title={row.title}
          items={row.items}
          isDesktop={isDesktop}
          handleItemClick={handleItemClick}
          isLiveRow={row.isLive}
        />
      ))}
    </div>
  );
}
