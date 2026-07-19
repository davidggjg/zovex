import { X, Play, Pause, Volume2, VolumeX, Maximize, Minimize, RotateCcw, RotateCw, Share2, PictureInPicture2, SkipForward } from "lucide-react";
import { useEffect, useRef, useState, useCallback } from "react";

// ──────────────────────────────────────────────────────────────
// Native bridge helpers (used when running inside the Android app)
// ──────────────────────────────────────────────────────────────
function postNative(msg) {
  try { window.ReactNativeWebView?.postMessage(JSON.stringify(msg)); } catch {}
}

function setupMediaSession(videoEl, movie) {
  if (!("mediaSession" in navigator)) return;
  const artwork = movie.poster_url
    ? [{ src: movie.poster_url, sizes: "512x512", type: "image/jpeg" }]
    : [];
  navigator.mediaSession.metadata = new MediaMetadata({
    title: movie.title || "ZOVEX",
    artist: movie.year ? String(movie.year) : "",
    artwork,
  });
  const seek = (s) => { try { videoEl.currentTime = Math.max(0, videoEl.currentTime + s); } catch {} };
  navigator.mediaSession.setActionHandler("play", () => videoEl.play().catch?.(() => {}));
  navigator.mediaSession.setActionHandler("pause", () => videoEl.pause());
  navigator.mediaSession.setActionHandler("seekbackward", (d) => seek(-(d?.seekOffset ?? 10)));
  navigator.mediaSession.setActionHandler("seekforward", (d) => seek(d?.seekOffset ?? 10));
  navigator.mediaSession.setActionHandler("stop", () => { videoEl.pause(); videoEl.currentTime = 0; });
  navigator.mediaSession.playbackState = "playing";
}

function clearMediaSession() {
  if (!("mediaSession" in navigator)) return;
  navigator.mediaSession.metadata = null;
  ["play","pause","seekbackward","seekforward","stop"].forEach(a => {
    try { navigator.mediaSession.setActionHandler(a, null); } catch {}
  });
  navigator.mediaSession.playbackState = "none";
}

const spinStyle = `
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes fadeInOut { 0%{opacity:0;transform:translateY(-50%) scale(0.7)} 25%{opacity:1;transform:translateY(-50%) scale(1.1)} 70%{opacity:1} 100%{opacity:0} }
@keyframes fadeUp { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:translateY(0)} }
@keyframes livePulseDot { 0%,100%{box-shadow:0 0 0 0 rgba(229,9,20,.6)} 50%{box-shadow:0 0 0 6px rgba(229,9,20,0)} }
`;

// שמות ערוצי טלגרם → מזהה מספרי (רק לערוצים פרטיים שדורשים בוט-פרוקסי)
// ערוצים פומביים (כמו ZOVE8) לא נמפים כאן — הם עוברים ישירות לאיפריים של טלגרם
const TG_CHANNELS = {};
const TG_PROXY = import.meta.env.VITE_TELEGRAM_PROXY || "https://telegram-bot-8528.onrender.com";

// ─── helpers ────────────────────────────────────────────────
function buildSrc(movie, startTime = 0) {
  const vid = (movie.video_id || movie.video_url || "").trim();
  const type = movie.type || "direct";
  const t = Math.max(0, Math.floor(startTime || 0));
  if (!vid) return null;
  if (vid.includes("kaltura.com")) return vid;
  const kalturaMatch = vid.match(/^(\d+)\/(\d+)\/([a-zA-Z0-9_]+)$/);
  if (type === "kaltura" || kalturaMatch) {
    const parts = vid.split("/");
    if (parts.length >= 3)
      return `https://cdnapisec.kaltura.com/p/${parts[0]}/embedPlaykitJs/uiconf_id/${parts[1]}?iframeembed=true&entry_id=${parts[2]}`;
    return null;
  }
  if (type === "youtube" || vid.includes("youtube.com") || vid.includes("youtu.be")) {
    const m = vid.match(/(?:v=|youtu\.be\/)([^&/?]+)/);
    const base = `https://www.youtube.com/embed/${m ? m[1] : vid}?autoplay=1`;
    return t > 0 ? `${base}&start=${t}` : base;
  }
  if (type === "drive" || vid.includes("drive.google.com")) {
    const m = vid.match(/\/d\/([^/?]+)/);
    return `https://drive.google.com/file/d/${m ? m[1] : vid}/preview`;
  }
  if (type === "vimeo" || vid.includes("vimeo.com")) {
    const m = vid.match(/vimeo\.com\/(\d+)/);
    const base = `https://player.vimeo.com/video/${m ? m[1] : vid}?autoplay=1`;
    return t > 0 ? `${base}#t=${t}s` : base;
  }
  if (type === "dailymotion" || vid.includes("dailymotion.com")) {
    const m = vid.match(/(?:video\/|dai\.ly\/)([a-zA-Z0-9]+)/);
    return `https://www.dailymotion.com/embed/video/${m ? m[1] : vid}?autoplay=1`;
  }
  if (type === "streamable" || vid.includes("streamable.com")) {
    const m = vid.match(/streamable\.com\/([a-zA-Z0-9]+)/);
    return `https://streamable.com/e/${m ? m[1] : vid}?autoplay=1`;
  }
  if (type === "rumble" || vid.includes("rumble.com")) {
    const m = vid.match(/(?:embed\/|video\/)([a-zA-Z0-9]+)/);
    return `https://rumble.com/embed/${m ? m[1] : vid}/`;
  }
  if (type === "archive" || vid.includes("archive.org")) {
    const m = vid.match(/archive\.org\/(?:embed|details)\/([^/?]+)/);
    return `https://archive.org/embed/${m ? m[1] : vid}`;
  }
  if (type === "kan" || vid.includes("kan.org.il"))
    return `https://www.kan.org.il/General/Embed.aspx?id=${vid}`;
  if (type === "okru" || vid.includes("ok.ru")) {
    const m = vid.match(/ok\.ru\/video\/(\d+)/);
    return `https://ok.ru/videoembed/${m ? m[1] : vid}`;
  }
  if (type === "telegram" || vid.includes("t.me")) {
    // כתובת פרוקסי מוכנה כבר — נגן ישירות
    if (vid.startsWith("http") && !vid.includes("t.me")) return vid;
    // נרמול: הסרת https://t.me/ אם קיים
    const tgId = vid.replace(/^https?:\/\/t\.me\//, "");
    // חילוץ שם ערוץ + מזהה הודעה (תומך ב-CHANNEL/MSG ו-CHANNEL/TOPIC/MSG)
    const parts = tgId.split("/").filter(Boolean);
    const chanRaw = parts[0] || "";
    const msgId   = parts[parts.length - 1]; // המספר האחרון הוא תמיד מזהה ההודעה
    // ערוץ מספרי ישירות (t.me/1234567/99)
    if (/^\d+$/.test(chanRaw) && msgId) {
      return `${TG_PROXY}/stream/${chanRaw}/${msgId}`;
    }
    // שם ערוץ → חיפוש במיפוי
    const numericId = TG_CHANNELS[chanRaw] || TG_CHANNELS[chanRaw.toLowerCase()];
    if (numericId && msgId) {
      return `${TG_PROXY}/stream/${numericId}/${msgId}`;
    }
    // אין מיפוי — iframe כ-fallback
    return `https://t.me/${tgId}?embed=1&mode=tme`;
  }
  if (type === "jellyfin") {
    const server = (movie.jellyfin_server || "").replace(/\/$/, "");
    const apiKey = movie.jellyfin_api_key || "";
    return server && vid ? `${server}/web/index.html#!/video?id=${vid}&api_key=${apiKey}` : null;
  }
  return vid.startsWith("http") ? vid : null;
}

function isHlsUrl(src) {
  return src?.includes(".m3u8") || src?.includes("Manifest.ism");
}

function isIframeUrl(src, type) {
  if (!src) return false;
  // "telegram" is intentionally absent: buildSrc routes telegram URLs to either
  // the proxy bot (→ native <video>) or a t.me embed widget (→ iframe via domain check).
  const iframeTypes = ["youtube","drive","vimeo","dailymotion","streamable","rumble","archive","kan","okru","kaltura","jellyfin"];
  if (iframeTypes.includes(type)) return true;
  return ["youtube.com","youtu.be","drive.google.com","vimeo.com","dailymotion.com","streamable.com","rumble.com","archive.org","kan.org.il","ok.ru","t.me","kaltura.com"].some(d => src.includes(d));
}

// ─── "סיום צפייה" ────────────────────────────────────────────
// אם נשארה פחות מדקה עד הסוף (או שנצפו 95%+), נחשב כמי שסיים לצפות —
// גם אם יצא רגע לפני הסוף (כותרות סיום וכו'). במקרה כזה משמרים מיקום 0
// (בלי "המשך צפייה") כדי שהפריט ייחשב כצפייה שהושלמה, לא כצפייה באמצע.
const NEAR_END_SECONDS = 60;
const NEAR_END_RATIO = 0.95;
function reportProgress(onProgressRef, currentTime, duration) {
  if (!duration || !Number.isFinite(duration)) return;
  const finished = (duration - currentTime) <= NEAR_END_SECONDS || (currentTime / duration) >= NEAR_END_RATIO;
  onProgressRef.current?.(finished ? 0 : currentTime, duration);
}

const STREAM_BACKEND_URL = "https://maco11.onrender.com";

function formatTime(secs) {
  if (!secs || isNaN(secs) || !isFinite(secs)) return "0:00";
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

// כשהשרת המקור (למשל פרוקסי טלגרם) לא שולח Content-Length תקין, הדפדפן
// מדווח duration=Infinity ולא NaN/0 — ואז שורת ההתקדמות "תקועה" על 0/0
// ולא נשמרת התקדמות בכלל. הפונקציה הזו מנסה למצוא משך זמן שמיש גם במקרה כזה,
// דרך טווח ה-seekable שכן מתעדכן תוך כדי הזרמה.
function getUsableDuration(v) {
  if (!v) return 0;
  if (Number.isFinite(v.duration) && v.duration > 0) return v.duration;
  try {
    if (v.seekable && v.seekable.length > 0) {
      const end = v.seekable.end(v.seekable.length - 1);
      if (Number.isFinite(end) && end > 0) return end;
    }
  } catch {}
  return 0;
}

function loadScripts(urls) {
  return Promise.all(urls.map(url => new Promise(resolve => {
    if (document.querySelector(`script[src="${url}"]`)) { resolve(); return; }
    const s = document.createElement("script");
    s.src = url; s.onload = resolve;
    document.head.appendChild(s);
  })));
}

function loadStyles(urls) {
  urls.forEach(url => {
    if (!document.querySelector(`link[href="${url}"]`)) {
      const l = document.createElement("link");
      l.rel = "stylesheet"; l.href = url;
      document.head.appendChild(l);
    }
  });
}

// ─── Skip animation ───────────────────────────────────────────
function SkipAnim({ side }) {
  if (!side) return null;
  return (
    <div style={{
      position: "absolute", top: "40%",
      [side === "forward" ? "right" : "left"]: "6%",
      transform: "translateY(-50%)", pointerEvents: "none", zIndex: 20,
      animation: "fadeInOut 0.7s ease forwards"
    }}>
      <div style={{
        background: "rgba(0,0,0,0.55)", backdropFilter: "blur(8px)",
        borderRadius: 18, padding: "14px 22px",
        display: "flex", flexDirection: "column", alignItems: "center", gap: 4,
        border: "1px solid rgba(255,255,255,0.18)"
      }}>
        <span style={{ fontSize: 26, color: "#fff" }}>{side === "forward" ? "▶▶" : "◀◀"}</span>
        <span style={{ fontSize: 13, color: "#fff", fontWeight: 700, fontFamily: "Arial" }}>
          {side === "forward" ? "+10" : "-10"} שניות
        </span>
      </div>
    </div>
  );
}

// ─── Top bar (X + title + share) ─────────────────────────────
function TopBar({ title, episode, onClose, visible }) {
  const handleShare = () => {
    try { navigator.share?.({ title, url: window.location.href }); } catch {}
  };
  return (
    <div style={{
      position: "absolute", top: 0, left: 0, right: 0, zIndex: 30,
      padding: "14px 16px 40px",
      background: "linear-gradient(to bottom, rgba(0,0,0,0.82) 0%, transparent 100%)",
      display: "flex", alignItems: "flex-start", justifyContent: "space-between",
      direction: "rtl",
      opacity: visible ? 1 : 0,
      transition: "opacity 0.3s",
      pointerEvents: visible ? "auto" : "none",
    }}>
      {/* X button — right side (RTL) */}
      <button
        onClick={(e) => { e.stopPropagation(); onClose(); }}
        style={{
          background: "none", border: "none", color: "#fff",
          cursor: "pointer", padding: 4, lineHeight: 1,
          display: "flex", alignItems: "center", justifyContent: "center",
          WebkitTapHighlightColor: "transparent", outline: "none",
        }}
      >
        <X size={28} strokeWidth={2.5} />
      </button>

      {/* title — center */}
      <div style={{ flex: 1, textAlign: "center", paddingTop: 2 }}>
        <div style={{ color: "#fff", fontSize: 15, fontWeight: 700, fontFamily: "Arial", textShadow: "0 1px 6px rgba(0,0,0,0.9)" }}>
          {title}
        </div>
        {episode && (
          <div style={{ color: "rgba(255,255,255,0.7)", fontSize: 12, fontFamily: "Arial", marginTop: 2 }}>
            {episode}
          </div>
        )}
      </div>

      {/* share — left side */}
      <button
        onClick={handleShare}
        style={{
          background: "none", border: "none", color: "#fff",
          cursor: "pointer", padding: 4, lineHeight: 1,
          display: "flex", alignItems: "center", justifyContent: "center",
          WebkitTapHighlightColor: "transparent", outline: "none",
        }}
      >
        <Share2 size={22} strokeWidth={2} />
      </button>
    </div>
  );
}

// ─── Bottom controls bar ──────────────────────────────────────
function BottomBar({ videoRef, onSkip, visible, isLive = false, videoReady }) {
  const [playing, setPlaying] = useState(true);
  const [muted, setMuted] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [pipSupported, setPipSupported] = useState(false);
  const progressRef = useRef(null);

  useEffect(() => {
    setPipSupported(!!(document.pictureInPictureEnabled || document.webkitSupportsPresentationMode));
    const onFs = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", onFs);
    document.addEventListener("webkitfullscreenchange", onFs);
    return () => {
      document.removeEventListener("fullscreenchange", onFs);
      document.removeEventListener("webkitfullscreenchange", onFs);
    };
  }, []);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    // סנכרון מיידי — אם המטא-דאטה כבר נטענה עד שהגענו לכאן (למשל וידאו שנטען
    // מהר), נקבל את הערכים הנוכחיים במקום לחכות לאירוע שכבר לא יקרה שוב
    const syncDuration = () => { const d = getUsableDuration(v); if (d > 0) setDuration(d); };
    syncDuration();
    if (v.currentTime) setCurrentTime(v.currentTime);
    setPlaying(!v.paused);
    const onTime = () => { if (!dragging) setCurrentTime(v.currentTime); syncDuration(); };
    const onMeta = () => syncDuration();
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    v.addEventListener("timeupdate", onTime);
    v.addEventListener("loadedmetadata", onMeta);
    v.addEventListener("durationchange", onMeta);
    v.addEventListener("progress", onMeta);
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    // גיבוי: כמה שרתי הזרמה (למשל פרוקסי טלגרם) לא שולחים Content-Length
    // ולכן loadedmetadata/durationchange לא תמיד מגיעים בזמן — פולינג קצר
    // כרשת ביטחון עד שיש משך זמן שמיש.
    const poll = duration > 0 ? null : setInterval(syncDuration, 500);
    return () => {
      v.removeEventListener("timeupdate", onTime);
      v.removeEventListener("loadedmetadata", onMeta);
      v.removeEventListener("durationchange", onMeta);
      v.removeEventListener("progress", onMeta);
      v.removeEventListener("play", onPlay);
      v.removeEventListener("pause", onPause);
      if (poll) clearInterval(poll);
    };
    // videoReady משמש כטריגר: הוא הופך ל-true בדיוק כשה-<video> האמיתי נוצר
    // ונשמר ב-ref — כך שהאפקט הזה רץ שוב ברגע שיש בפועל מה להאזין לו, ולא
    // "מפספס" את האירועים כי הוא רץ מוקדם מדי (לפני שהאלמנט קיים).
  }, [videoRef, dragging, videoReady, duration]);

  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    v.paused ? v.play() : v.pause();
  };

  const toggleMute = () => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = !v.muted;
    setMuted(v.muted);
  };

  const seek = useCallback((e) => {
    const v = videoRef.current;
    const bar = progressRef.current;
    if (!v || !bar || !duration) return;
    const rect = bar.getBoundingClientRect();
    const x = (e.clientX ?? e.touches?.[0]?.clientX) - rect.left;
    const ratio = Math.max(0, Math.min(1, x / rect.width));
    v.currentTime = ratio * duration;
    setCurrentTime(ratio * duration);
  }, [videoRef, duration]);

  const goFullscreen = () => {
    const v = videoRef.current;
    const inApp = !!window.ReactNativeWebView;
    const nativeFs = !!(document.fullscreenElement || document.webkitFullscreenElement);
    const currentlyFs = nativeFs || (inApp && isFullscreen);

    if (currentlyFs) {
      if (nativeFs) (document.exitFullscreen || document.webkitExitFullscreen)?.call(document);
      setIsFullscreen(false);
      postNative({ type: "fullscreen", enter: false });
    } else {
      postNative({ type: "fullscreen", enter: true });
      if (inApp) {
        setIsFullscreen(true);
      } else {
        // Fullscreen our specific container — keeps custom controls visible.
        // Using documentElement or the video element directly can cause the
        // browser to show its native player instead of our custom overlay.
        const el = videoRef.current?.closest("[data-cvp]") || document.documentElement;
        (el.requestFullscreen || el.webkitRequestFullscreen)?.call(el);
      }
    }
  };

  const goPip = async () => {
    const v = videoRef.current;
    if (!v) return;
    try {
      if (document.pictureInPictureElement) {
        await document.exitPictureInPicture();
      } else {
        await v.requestPictureInPicture();
      }
    } catch {}
  };

  const progress = duration ? (currentTime / duration) * 100 : 0;

  return (
    <div style={{
      position: "absolute", bottom: 0, left: 0, right: 0, zIndex: 30,
      padding: "40px 20px 20px",
      background: "linear-gradient(to top, rgba(0,0,0,0.55) 0%, transparent 100%)",
      transition: "opacity 0.3s",
      opacity: visible ? 1 : 0,
      pointerEvents: visible ? "auto" : "none",
      direction: "ltr",
    }}>
      {/* progress bar — לא רלוונטי בשידור חי */}
      {!isLive && (
        <div style={{ marginBottom: 16, padding: "8px 0", cursor: "pointer" }}
          ref={progressRef}
          onClick={seek}
          onMouseDown={(e) => { setDragging(true); seek(e); }}
          onMouseMove={(e) => { if (dragging) seek(e); }}
          onMouseUp={() => setDragging(false)}
          onTouchStart={(e) => { setDragging(true); seek(e); }}
          onTouchMove={(e) => { if (dragging) seek(e); }}
          onTouchEnd={() => setDragging(false)}
        >
          <div style={{ width: "100%", height: 3, background: "rgba(255,255,255,0.25)", borderRadius: 3, position: "relative" }}>
            <div style={{ position: "absolute", top: 0, left: 0, height: "100%", width: `${progress}%`, background: "#e91e8c", borderRadius: 3 }} />
            <div style={{ position: "absolute", top: "50%", left: `${progress}%`, transform: "translate(-50%,-50%)", width: 13, height: 13, borderRadius: "50%", background: "#e91e8c", boxShadow: "0 0 6px rgba(233,30,140,0.7)" }} />
          </div>
        </div>
      )}

      {/* bottom row: mute + time/LIVE + fullscreen */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <button onClick={toggleMute} style={iconBtn}>
            {muted ? <VolumeX size={19} /> : <Volume2 size={19} />}
          </button>
          {isLive ? (
            <span style={{ display: "flex", alignItems: "center", gap: 6, color: "#fff", fontSize: 12, fontWeight: 900, fontFamily: "Arial" }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#e50914", display: "inline-block", animation: "livePulseDot 1.5s ease-in-out infinite" }} />
              LIVE
            </span>
          ) : (
            <span style={{ color: "rgba(255,255,255,0.75)", fontSize: 12, fontFamily: "Arial", whiteSpace: "nowrap" }}>
              {formatTime(currentTime)} / {formatTime(duration)}
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {pipSupported && (
            <button onClick={goPip} style={iconBtn} title="Picture in Picture">
              <PictureInPicture2 size={19} />
            </button>
          )}
          <button onClick={goFullscreen} style={iconBtn}>
            {isFullscreen ? <Minimize size={19} /> : <Maximize size={19} />}
          </button>
        </div>
      </div>
    </div>
  );
}

const iconBtn = {
  background: "none", border: "none", color: "#fff",
  width: 42, height: 42, borderRadius: "50%", cursor: "pointer",
  display: "flex", alignItems: "center", justifyContent: "center",
  position: "relative", flexShrink: 0,
  WebkitTapHighlightColor: "transparent",
};

const centerBtn = {
  background: "none", border: "none", color: "#fff",
  width: 48, height: 48, borderRadius: "50%", cursor: "pointer",
  display: "flex", alignItems: "center", justifyContent: "center",
  position: "relative", flexShrink: 0,
  WebkitTapHighlightColor: "transparent",
  outline: "none",
};

// ─── כפתור "הפרק הבא" ──────────────────────────────────────────
// מופיע כש-5 דקות או פחות נשארו לסוף הפרק, ונעלם אם חוזרים אחורה מעבר לזה.
// לא עובר אוטומטית - רק מציג כפתור, הצפייה בפרק הבא היא בחירה של הצופה.
const NEXT_EPISODE_THRESHOLD_SECS = 300;
function NextEpisodeButton({ videoRef, onNext, label, videoReady }) {
  const [show, setShow] = useState(false);

  useEffect(() => {
    const v = videoRef.current;
    if (!v || !onNext) return;
    const check = () => {
      const dur = getUsableDuration(v);
      const remaining = dur - v.currentTime;
      setShow(dur > 0 && remaining > 0 && remaining <= NEXT_EPISODE_THRESHOLD_SECS);
    };
    check();
    v.addEventListener("timeupdate", check);
    return () => v.removeEventListener("timeupdate", check);
    // videoReady משמש כטריגר: הופך ל-true בדיוק כשה-<video> האמיתי נוצר ונשמר
    // ב-ref, כך שהאפקט הזה לא "מפספס" לרוץ לפני שיש בכלל למה להאזין (אותה
    // בעיה שכבר נפתרה ב-BottomBar/ControlsLayer עם אותו pattern בדיוק).
  }, [videoRef, onNext, videoReady]);

  if (!onNext || !show) return null;

  return (
    <button
      onClick={(e) => { e.stopPropagation(); onNext(); }}
      style={{
        position: "absolute", bottom: 96, right: 16, zIndex: 30,
        background: "rgba(20,20,20,0.88)", color: "#fff", border: "1px solid rgba(255,255,255,0.25)",
        borderRadius: 12, padding: "12px 18px", fontSize: 14, fontWeight: 700,
        cursor: "pointer", display: "flex", alignItems: "center", gap: 8,
        backdropFilter: "blur(6px)", fontFamily: "Arial, sans-serif",
      }}
    >
      <SkipForward size={18} fill="white" />
      {label ? `הפרק הבא: ${label}` : "הפרק הבא"}
    </button>
  );
}

// ─── Controls wrapper (auto-hide) ─────────────────────────────
// FIX: לחיצה על כל מקום במסך (לא רק ה-div) מפעילה/מעצירה + מציגה כפתורים
function ControlsLayer({ videoRef, title, episode, onClose, onSkip, skipAnim, isLive = false, videoReady, onNextEpisode, nextEpisodeLabel }) {
  const [visible, setVisible] = useState(true);
  const timer = useRef(null);

  const show = useCallback(() => {
    setVisible(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setVisible(false), 3500);
  }, []);

  useEffect(() => { show(); return () => clearTimeout(timer.current); }, [show]);

  const [playing, setPlaying] = useState(true);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    setPlaying(!v.paused);
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    return () => { v.removeEventListener("play", onPlay); v.removeEventListener("pause", onPause); };
  }, [videoRef, videoReady]);

  const togglePlay = useCallback((e) => {
    e.stopPropagation();
    const v = videoRef.current;
    if (v) v.paused ? v.play() : v.pause();
  }, [videoRef]);

  // לחיצה בכל מקום על המסך — Toggle: אם מוצג מסתיר, אם מוסתר מציג
  const handleOverlayClick = useCallback((e) => {
    if (visible) {
      clearTimeout(timer.current);
      setVisible(false);
    } else {
      show();
    }
  }, [visible, show]);

  return (
    <div
      style={{ position: "absolute", inset: 0, zIndex: 10 }}
      onClick={handleOverlayClick}
      onDoubleClick={(e) => e.stopPropagation()}
    >
      {/* TopBar — נעלם/מופיע עם הכפתורים */}
      <TopBar title={title} episode={episode} onClose={onClose} visible={visible} />

      {/* כפתורי skip + play צפים באמצע המסך (skip מוסתר בשידור חי) */}
      <div style={{
        position: "absolute", top: "50%", left: "50%",
        transform: "translate(-50%, -50%)",
        display: "flex", alignItems: "center", gap: 32,
        opacity: visible ? 1 : 0,
        transition: "opacity 0.3s",
        pointerEvents: visible ? "auto" : "none",
        zIndex: 20,
      }}>
        {/* skip -10 — אייקון Lucide תקין */}
        {!isLive && (
          <button onClick={(e) => { e.stopPropagation(); onSkip("back"); }} style={centerBtn}>
            <RotateCcw size={36} color="white" strokeWidth={1.8} />
            <span style={{ position: "absolute", top: "54%", left: "50%", transform: "translate(-50%,-50%)", fontSize: 10, fontWeight: 900, fontFamily: "Arial", color: "white" }}>10</span>
          </button>
        )}
        {/* play/pause — ללא שינוי */}
        <button onClick={togglePlay} style={{ ...centerBtn, width: 58, height: 58 }}>
          {playing
            ? <svg width="28" height="28" viewBox="0 0 28 28" fill="white"><rect x="3" y="3" width="8" height="22" rx="2"/><rect x="17" y="3" width="8" height="22" rx="2"/></svg>
            : <svg width="28" height="28" viewBox="0 0 28 28" fill="white"><polygon points="5,2 26,14 5,26"/></svg>
          }
        </button>
        {/* skip +10 — אייקון Lucide תקין */}
        {!isLive && (
          <button onClick={(e) => { e.stopPropagation(); onSkip("forward"); }} style={centerBtn}>
            <RotateCw size={36} color="white" strokeWidth={1.8} />
            <span style={{ position: "absolute", top: "54%", left: "50%", transform: "translate(-50%,-50%)", fontSize: 10, fontWeight: 900, fontFamily: "Arial", color: "white" }}>10</span>
          </button>
        )}
      </div>

      <BottomBar videoRef={videoRef} onSkip={onSkip} visible={visible} isLive={isLive} videoReady={videoReady} />
      {!isLive && <NextEpisodeButton videoRef={videoRef} onNext={onNextEpisode} label={nextEpisodeLabel} videoReady={videoReady} />}
      <SkipAnim side={skipAnim} />
    </div>
  );
}

// ─── Direct video player ────────────────────────────────────────
// Plays any direct video URL (MP4, WebM, Telegram proxy streams, etc.)
// Uses the exact same TopBar/ControlsLayer/BottomBar as HlsPlayer —
// this is what keeps the design 100% identical across every link type.
// The `src` value is resolved from the movie record in movies.json via buildSrc().
//
// URL sources by example:
//   Direct MP4   → "https://example.com/video.mp4"
//   Telegram bot → "https://telegram-bot-8528.onrender.com/stream/{channelId}/{msgId}"
//                  (set VITE_TELEGRAM_PROXY to override the bot base URL)
function DirectVideoPlayer({ src, movie, onClose, startTime = 0, onProgress, onNextEpisode, nextEpisodeLabel }) {
  const containerRef = useRef(null);
  const videoElRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [skipAnim, setSkipAnim] = useState(null);
  // videoReady: הופך ל-true ברגע שהאלמנט <video> האמיתי נוצר ונשמר ב-ref —
  // זה מה שמאפשר ל-ControlsLayer/BottomBar (שרוצים להאזין לאירועים שלו:
  // duration, timeupdate וכו') לדעת מתי בדיוק יש למה להאזין, במקום להחמיץ
  // את האירועים כי הם ניסו להאזין לפני שהאלמנט בכלל היה קיים.
  const [videoReady, setVideoReady] = useState(false);
  // ref כדי שה-interval/cleanup תמיד יקראו את ה-callback העדכני בלי לגרום ל-re-init של הנגן
  const onProgressRef = useRef(onProgress);
  onProgressRef.current = onProgress;

  useEffect(() => {
    if (!containerRef.current || !src) return;
    let destroyed = false;
    setVideoReady(false);

    const video = document.createElement("video");
    video.setAttribute("playsinline", "");
    video.setAttribute("autoplay", "");
    video.style.cssText = "width:100%;height:100%;position:absolute;inset:0;background:#000;object-fit:contain;";
    // src comes from buildSrc(movie) which reads video_url / video_id from movies.json
    video.src = src;
    containerRef.current.appendChild(video);
    videoElRef.current = video;
    setVideoReady(true);

    const onLoaded = () => {
      if (destroyed) return;
      if (startTime > 1) { try { video.currentTime = startTime; } catch {} }
      video.play().catch(() => {});
      setLoading(false);
    };
    const onWaiting = () => setLoading(true);
    const onPlaying = () => {
      setLoading(false);
      setupMediaSession(video, movie);
      postNative({ type: "video_playing", value: true });
    };
    const onPause = () => postNative({ type: "video_playing", value: false });
    const onEnded = () => postNative({ type: "video_playing", value: false });
    video.addEventListener("loadedmetadata", onLoaded);
    video.addEventListener("waiting", onWaiting);
    video.addEventListener("playing", onPlaying);
    video.addEventListener("pause", onPause);
    video.addEventListener("ended", onEnded);

    // שמירת התקדמות תקופתית (כל 5 שניות בזמן צפייה)
    const reportInterval = setInterval(() => {
      if (!video.paused && !video.ended) {
        const dur = getUsableDuration(video);
        if (dur > 0) reportProgress(onProgressRef, video.currentTime, dur);
      }
    }, 5000);

    return () => {
      destroyed = true;
      clearInterval(reportInterval);
      { const dur = getUsableDuration(video); if (dur > 0) reportProgress(onProgressRef, video.currentTime, dur); }
      video.removeEventListener("loadedmetadata", onLoaded);
      video.removeEventListener("waiting", onWaiting);
      video.removeEventListener("playing", onPlaying);
      video.removeEventListener("pause", onPause);
      video.removeEventListener("ended", onEnded);
      clearMediaSession();
      postNative({ type: "video_playing", value: false });
      video.pause();
      video.src = "";
      videoElRef.current = null;
      setVideoReady(false);
      if (containerRef.current) containerRef.current.innerHTML = "";
    };
  }, [src]);

  // אם המיקום השמור ("המשך צפייה") מגיע רק אחרי שהנגן כבר נפתח והתחיל לטעון
  // (כי אנחנו כבר לא מחכים לו לפני הפתיחה - ראה usePlayback.js), נדלג אליו
  // כאן ברגע שהוא מגיע. הבדיקה על currentTime<2 מונעת "קפיצה" מפתיעה אם
  // המשתמש כבר הספיק לצפות רגע לפני שהתשובה חזרה מהשרת.
  useEffect(() => {
    const v = videoElRef.current;
    if (!v || startTime <= 1) return;
    if (v.currentTime < 2) { try { v.currentTime = startTime; } catch {} }
  }, [startTime]);

  const handleSkip = useCallback((side) => {
    const v = videoElRef.current;
    if (v) v.currentTime = Math.max(0, v.currentTime + (side === "forward" ? 10 : -10));
    setSkipAnim(side);
    setTimeout(() => setSkipAnim(null), 700);
  }, []);

  return (
    <div style={{ flex: 1, position: "relative", background: "#000", minHeight: 0 }}>
      {loading && (
        <div style={{ position: "absolute", inset: 0, zIndex: 5, display: "flex", alignItems: "center", justifyContent: "center", background: "#000" }}>
          <div style={{ width: 44, height: 44, border: "4px solid rgba(255,255,255,0.2)", borderTop: "4px solid #e91e8c", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
        </div>
      )}
      <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />
      <ControlsLayer videoRef={videoElRef} title={movie.title} episode={movie.episode_title ? `פרק ${movie.episode_number} - ${movie.episode_title}` : movie.episode_number ? `פרק ${movie.episode_number}` : null} onClose={onClose} onSkip={handleSkip} skipAnim={skipAnim} videoReady={videoReady} onNextEpisode={onNextEpisode} nextEpisodeLabel={nextEpisodeLabel} />
    </div>
  );
}

// ─── HLS player ───────────────────────────────────────────────
function HlsPlayer({ src, movie, onClose, startTime = 0, onProgress, isLive = false, onNextEpisode, nextEpisodeLabel }) {
  const containerRef = useRef(null);
  const videoElRef = useRef(null);
  const playerRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [skipAnim, setSkipAnim] = useState(null);
  const [videoReady, setVideoReady] = useState(false);
  const onProgressRef = useRef(onProgress);
  onProgressRef.current = onProgress;

  // ─── Auto-refresh: שומר את ה-src הנוכחי ומרענן כל 25 דקות ───
  const currentSrcRef = useRef(src);
  const refreshTimerRef = useRef(null);

  // פונקציה שמושכת src חדש מהשרת ומטעינה מחדש
  const refreshStream = useCallback(async () => {
    try {
      const res = await fetch(`${STREAM_BACKEND_URL}/api/refresh-stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_src: currentSrcRef.current }),
      });
      if (!res.ok) return;
      const data = await res.json();
      const newSrc = data.hls_url || data.url;
      if (!newSrc || newSrc === currentSrcRef.current) return;
      currentSrcRef.current = newSrc;
      // טעינה מחדש בלי רענון דף
      const shaka = playerRef.current?.shaka;
      if (shaka) {
        try { await shaka.load(newSrc); } catch {}
      }
    } catch {}
  }, []);

  // הפעלת טיימר של 25 דקות לרענון אוטומטי
  const startRefreshTimer = useCallback(() => {
    if (refreshTimerRef.current) clearInterval(refreshTimerRef.current);
    refreshTimerRef.current = setInterval(() => {
      refreshStream();
    }, 25 * 60 * 1000); // 25 דקות
  }, [refreshStream]);

  useEffect(() => {
    if (!src || !containerRef.current) return;
    let destroyed = false;
    setVideoReady(false);
    currentSrcRef.current = src;
    const init = async () => {
      loadStyles(["https://unpkg.com/video.js@8.21.0/dist/video-js.min.css"]);
      await loadScripts([
        "https://unpkg.com/video.js@8.21.0/dist/video.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/shaka-player/4.7.11/shaka-player.compiled.js",
      ]);
      if (destroyed) return;
      window.shaka.polyfill.installAll();
      const videoEl = document.createElement("video");
      videoEl.setAttribute("playsinline", "");
      videoEl.setAttribute("autoplay", "");
      videoEl.style.cssText = "width:100%;height:100%;position:absolute;inset:0;background:#000;";
      containerRef.current.appendChild(videoEl);
      videoElRef.current = videoEl;
      setVideoReady(true);
      const vjs = window.videojs(videoEl, { controls: false, autoplay: true, fill: true });
      const shaka = new window.shaka.Player();
      // תיקון: שידורים חיים מ-CDN חיצוני (כמו כאן 11) נראו "נתקעים וקופצים
      // אחורה" אצלנו כל כמה שניות, בזמן שאותו שידור בדיוק חלק לגמרי באתר
      // המקור - כלומר זו לא בעיה בשידור עצמו, זו הגדרת ה-buffering ברירת
      // המחדל של Shaka (מכוונת ל-VOD, לא לשידור חי מ-CDN שיכול להיות קצת
      // פחות יציב). מגדילים את חלון ה-buffer רק לשידורים חיים - זה עולה
      // בכמה שניות עיכוב מול "הקצה החי", אבל נותן הרבה יותר כרית נגד
      // קפיצות ברשת לפני שהנגן צריך לעצור ולהמתין.
      if (isLive) {
        shaka.configure({
          streaming: {
            bufferingGoal: 30,
            rebufferingGoal: 4,
            retryParameters: { maxAttempts: 5, baseDelay: 500, backoffFactor: 2, timeout: 15000 },
          },
        });
      }
      await shaka.attach(videoEl);
      playerRef.current = { vjs, shaka };
      try {
        await shaka.load(src);
        if (!destroyed) {
          if (!isLive && startTime > 1) { try { videoEl.currentTime = startTime; } catch {} }
          videoEl.play().catch(() => {});
          setLoading(false);
          setupMediaSession(videoEl, movie);
          postNative({ type: "video_playing", value: true });
          startRefreshTimer(); // ← רענון אוטומטי כל 25 דקות
        }
      } catch {
        if (!destroyed) {
          vjs.src({ src, type: "application/x-mpegURL" });
          if (!isLive && startTime > 1) { try { vjs.currentTime(startTime); } catch {} }
          vjs.play().catch(() => {});
          setLoading(false);
          setupMediaSession(videoEl, movie);
          postNative({ type: "video_playing", value: true });
          startRefreshTimer(); // ← רענון אוטומטי כל 25 דקות (fallback)
        }
      }
    };
    init();
    const reportInterval = !isLive ? setInterval(() => {
      const v = videoElRef.current;
      if (v && !v.paused && !v.ended) {
        const dur = getUsableDuration(v);
        if (dur > 0) reportProgress(onProgressRef, v.currentTime, dur);
      }
    }, 5000) : null;
    return () => {
      destroyed = true;
      if (reportInterval) clearInterval(reportInterval);
      if (refreshTimerRef.current) clearInterval(refreshTimerRef.current); // ← ניקוי טיימר רענון
      const v = videoElRef.current;
      if (!isLive && v) { const dur = getUsableDuration(v); if (dur > 0) reportProgress(onProgressRef, v.currentTime, dur); }
      clearMediaSession();
      postNative({ type: "video_playing", value: false });
      playerRef.current?.shaka?.destroy();
      playerRef.current?.vjs?.dispose();
      playerRef.current = null; videoElRef.current = null;
      setVideoReady(false);
    };
  }, [src]);

  // ראו הערה מקבילה ב-DirectVideoPlayer: מדלגים למיקום השמור גם אם הוא
  // מגיע רק אחרי שהנגן כבר התחיל לטעון, כל עוד המשתמש עדיין ממש בהתחלה.
  useEffect(() => {
    const v = videoElRef.current;
    if (isLive || !v || startTime <= 1) return;
    if (v.currentTime < 2) { try { v.currentTime = startTime; } catch {} }
  }, [startTime, isLive]);

  const handleSkip = useCallback((side) => {
    const v = videoElRef.current;
    if (v) v.currentTime = Math.max(0, v.currentTime + (side === "forward" ? 10 : -10));
    setSkipAnim(side);
    setTimeout(() => setSkipAnim(null), 700);
  }, []);

  return (
    <div style={{ flex: 1, position: "relative", background: "#000", minHeight: 0 }}>
      {loading && (
        <div style={{ position: "absolute", inset: 0, zIndex: 5, display: "flex", alignItems: "center", justifyContent: "center", background: "#000" }}>
          <div style={{ width: 44, height: 44, border: "4px solid rgba(255,255,255,0.2)", borderTop: "4px solid #e91e8c", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
        </div>
      )}
      <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />
      <ControlsLayer videoRef={videoElRef} title={movie.title} episode={movie.episode_title ? `פרק ${movie.episode_number} - ${movie.episode_title}` : movie.episode_number ? `פרק ${movie.episode_number}` : null} onClose={onClose} onSkip={handleSkip} skipAnim={skipAnim} isLive={isLive} videoReady={videoReady} onNextEpisode={onNextEpisode} nextEpisodeLabel={nextEpisodeLabel} />
    </div>
  );
}

// ─── Iframe player with X always on top ──────────────────────
function IframePlayer({ src, movie, onClose }) {
  const [loaded, setLoaded] = useState(false);
  const TOP_BAR_HEIGHT = 64;

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", background: "#000", overflow: "hidden" }}>
      {/* X + title bar */}
      <div style={{
        height: TOP_BAR_HEIGHT, flexShrink: 0,
        padding: "12px 16px",
        background: "rgba(0,0,0,0.85)",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        direction: "rtl",
      }}>
        <button
          onClick={onClose}
          style={{
            background: "none", border: "none", color: "#fff",
            borderRadius: "50%", width: 42, height: 42,
            display: "flex", alignItems: "center", justifyContent: "center",
            cursor: "pointer", WebkitTapHighlightColor: "transparent", outline: "none", flexShrink: 0,
          }}
        >
          <X size={24} strokeWidth={2.5} />
        </button>
        <div style={{ flex: 1, textAlign: "center" }}>
          <div style={{ color: "#fff", fontSize: 15, fontWeight: 700, fontFamily: "Arial" }}>{movie.title}</div>
          {movie.episode_number && (
            <div style={{ color: "rgba(255,255,255,0.65)", fontSize: 12, fontFamily: "Arial", marginTop: 2 }}>
              פרק {movie.episode_number}{movie.episode_title ? ` - ${movie.episode_title}` : ""}
            </div>
          )}
        </div>
        <div style={{ width: 42, flexShrink: 0 }} />
      </div>

      {/* loading spinner */}
      {!loaded && (
        <div style={{ position: "absolute", inset: 0, zIndex: 10, background: "#000", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ width: 48, height: 48, border: "4px solid rgba(255,255,255,0.2)", borderTop: "4px solid #e91e8c", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
        </div>
      )}

      {/* iframe תופס את כל השטח שנשאר מתחת לכותרת */}
      <iframe
        key={src}
        src={src}
        onLoad={() => setLoaded(true)}
        style={{ flex: 1, width: "100%", border: "none", display: "block", minHeight: 0 }}
        allowFullScreen
        allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
      />
    </div>
  );
}

// ─── Main export ──────────────────────────────────────────────
export default function CustomVideoPlayer({ movie, onClose, startTime = 0, onProgress, onNextEpisode, nextEpisodeLabel }) {
  const isLive = !!movie.is_live;
  const src = buildSrc(movie, isLive ? 0 : startTime);
  const type = movie.type || "direct";

  useEffect(() => {
    postNative({ type: "player_open", value: true });
    return () => postNative({ type: "player_open", value: false });
  }, []);

  return (
    <div data-cvp style={{ position: "fixed", inset: 0, background: "#000", zIndex: 9999, display: "flex", flexDirection: "column" }}>
      <style>{spinStyle}</style>
      {!src ? (
        <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 16 }}>
          <button onClick={onClose} style={{ position: "absolute", top: 16, right: 16, background: "rgba(255,255,255,0.1)", border: "none", color: "#fff", borderRadius: "50%", width: 42, height: 42, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <X size={22} />
          </button>
          <span style={{ fontSize: 40 }}>🎬</span>
          <p style={{ color: "#888", fontSize: 15, fontFamily: "Arial" }}>אין קישור וידאו זמין</p>
        </div>
      ) : isHlsUrl(src) ? (
        <HlsPlayer src={src} movie={movie} onClose={onClose} startTime={startTime} onProgress={onProgress} isLive={isLive} onNextEpisode={onNextEpisode} nextEpisodeLabel={nextEpisodeLabel} />
      ) : isIframeUrl(src, type) ? (
        <IframePlayer src={src} movie={movie} onClose={onClose} />
      ) : (
        <DirectVideoPlayer src={src} movie={movie} onClose={onClose} startTime={startTime} onProgress={onProgress} onNextEpisode={onNextEpisode} nextEpisodeLabel={nextEpisodeLabel} />
      )}
    </div>
  );
}
