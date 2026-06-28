import { X, Play, Pause, Volume2, VolumeX, Maximize, RotateCcw, RotateCw, Share2 } from "lucide-react";
import { useEffect, useRef, useState, useCallback } from "react";
import Plyr from "plyr";
import "plyr/dist/plyr.css";

const spinStyle = `
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes fadeInOut { 0%{opacity:0;transform:translateY(-50%) scale(0.7)} 25%{opacity:1;transform:translateY(-50%) scale(1.1)} 70%{opacity:1} 100%{opacity:0} }
@keyframes fadeUp { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:translateY(0)} }
`;

// שמות ערוצי טלגרם → מזהה מספרי (חייב להיות זהה ל-Home.jsx)
const TG_CHANNELS = { "zove8": "7282626428", "ZOVE8": "7282626428" };
const TG_PROXY = import.meta.env.VITE_TELEGRAM_PROXY || "https://telegram-bot-8528.onrender.com";

// ─── helpers ────────────────────────────────────────────────
function buildSrc(movie) {
  const vid = (movie.video_id || movie.video_url || "").trim();
  const type = movie.type || "direct";
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
    return `https://www.youtube.com/embed/${m ? m[1] : vid}?autoplay=1`;
  }
  if (type === "drive" || vid.includes("drive.google.com")) {
    const m = vid.match(/\/d\/([^/?]+)/);
    return `https://drive.google.com/file/d/${m ? m[1] : vid}/preview`;
  }
  if (type === "vimeo" || vid.includes("vimeo.com")) {
    const m = vid.match(/vimeo\.com\/(\d+)/);
    return `https://player.vimeo.com/video/${m ? m[1] : vid}?autoplay=1`;
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

function formatTime(secs) {
  if (!secs || isNaN(secs)) return "0:00";
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
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
// FIX: כפתורים מסודרים: [skip-10] [מרווח] [play/pause] [מרווח] [skip+10]
// עם מרווח גדול בין כפתורים ושורת ההתקדמות למעלה
function BottomBar({ videoRef, onSkip, visible }) {
  const [playing, setPlaying] = useState(true);
  const [muted, setMuted] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [dragging, setDragging] = useState(false);
  const progressRef = useRef(null);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const onTime = () => { if (!dragging) setCurrentTime(v.currentTime); };
    const onMeta = () => setDuration(v.duration);
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    v.addEventListener("timeupdate", onTime);
    v.addEventListener("loadedmetadata", onMeta);
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    return () => {
      v.removeEventListener("timeupdate", onTime);
      v.removeEventListener("loadedmetadata", onMeta);
      v.removeEventListener("play", onPlay);
      v.removeEventListener("pause", onPause);
    };
  }, [videoRef, dragging]);

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
    const el = document.documentElement;
    document.fullscreenElement ? document.exitFullscreen?.() : (el.requestFullscreen?.() || el.webkitRequestFullscreen?.());
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
      {/* progress bar */}
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

      {/* bottom row: mute + time + fullscreen */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <button onClick={toggleMute} style={iconBtn}>
            {muted ? <VolumeX size={19} /> : <Volume2 size={19} />}
          </button>
          <span style={{ color: "rgba(255,255,255,0.75)", fontSize: 12, fontFamily: "Arial", whiteSpace: "nowrap" }}>
            {formatTime(currentTime)} / {formatTime(duration)}
          </span>
        </div>
        <button onClick={goFullscreen} style={iconBtn}>
          <Maximize size={19} />
        </button>
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

// ─── Controls wrapper (auto-hide) ─────────────────────────────
// FIX: לחיצה על כל מקום במסך (לא רק ה-div) מפעילה/מעצירה + מציגה כפתורים
function ControlsLayer({ videoRef, title, episode, onClose, onSkip, skipAnim }) {
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
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    return () => { v.removeEventListener("play", onPlay); v.removeEventListener("pause", onPause); };
  }, [videoRef]);

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

      {/* כפתורי skip + play צפים באמצע המסך */}
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
        <button onClick={(e) => { e.stopPropagation(); onSkip("back"); }} style={centerBtn}>
          <RotateCcw size={36} color="white" strokeWidth={1.8} />
          <span style={{ position: "absolute", top: "54%", left: "50%", transform: "translate(-50%,-50%)", fontSize: 10, fontWeight: 900, fontFamily: "Arial", color: "white" }}>10</span>
        </button>
        {/* play/pause — ללא שינוי */}
        <button onClick={togglePlay} style={{ ...centerBtn, width: 58, height: 58 }}>
          {playing
            ? <svg width="28" height="28" viewBox="0 0 28 28" fill="white"><rect x="3" y="3" width="8" height="22" rx="2"/><rect x="17" y="3" width="8" height="22" rx="2"/></svg>
            : <svg width="28" height="28" viewBox="0 0 28 28" fill="white"><polygon points="5,2 26,14 5,26"/></svg>
          }
        </button>
        {/* skip +10 — אייקון Lucide תקין */}
        <button onClick={(e) => { e.stopPropagation(); onSkip("forward"); }} style={centerBtn}>
          <RotateCw size={36} color="white" strokeWidth={1.8} />
          <span style={{ position: "absolute", top: "54%", left: "50%", transform: "translate(-50%,-50%)", fontSize: 10, fontWeight: 900, fontFamily: "Arial", color: "white" }}>10</span>
        </button>
      </div>

      <BottomBar videoRef={videoRef} onSkip={onSkip} visible={visible} />
      <SkipAnim side={skipAnim} />
    </div>
  );
}

// ─── Plyr-based direct video player ──────────────────────────
// Plays any direct video URL (MP4, WebM, Telegram proxy streams, etc.)
// The `src` value is resolved from the movie record in movies.json via buildSrc().
//
// URL sources by example:
//   Direct MP4   → "https://example.com/video.mp4"
//   Telegram bot → "https://telegram-bot-8528.onrender.com/stream/{channelId}/{msgId}"
//                  (set VITE_TELEGRAM_PROXY to override the bot base URL)
function PlyrVideoPlayer({ src, movie, onClose }) {
  const containerRef = useRef(null);
  const plyrRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current || !src) return;
    let destroyed = false;

    // Dynamically create the <video> element so Plyr owns its lifecycle.
    const video = document.createElement("video");
    video.setAttribute("playsinline", "");
    // src comes from buildSrc(movie) which reads video_url / video_id from movies.json
    video.src = src;
    containerRef.current.appendChild(video);

    plyrRef.current = new Plyr(video, {
      autoplay: true,
      controls: ["play-large", "play", "rewind", "fast-forward", "progress", "current-time", "duration", "mute", "volume", "fullscreen"],
      seekTime: 10,
      invertTime: false,
    });
    plyrRef.current.on("ready", () => {
      if (!destroyed) plyrRef.current?.play().catch(() => {});
    });

    return () => {
      destroyed = true;
      plyrRef.current?.destroy();
      plyrRef.current = null;
      if (containerRef.current) containerRef.current.innerHTML = "";
    };
  }, [src]);

  return (
    <div style={{ flex: 1, position: "relative", background: "#000", minHeight: 0 }}>
      {/* Plyr theme + full-height layout overrides */}
      <style>{`
        .plyr--video { --plyr-color-main: #e91e8c; position: absolute !important; inset: 0 !important; width: 100% !important; height: 100% !important; }
        .plyr__video-wrapper { padding-bottom: 0 !important; height: 100% !important; background: #000; }
        .plyr video { object-fit: contain; width: 100% !important; height: 100% !important; }
      `}</style>

      {/* Title bar always on top of Plyr's own controls */}
      <div style={{
        position: "absolute", top: 0, left: 0, right: 0, zIndex: 30,
        padding: "14px 16px 40px",
        background: "linear-gradient(to bottom, rgba(0,0,0,0.82) 0%, transparent 100%)",
        display: "flex", alignItems: "flex-start", justifyContent: "space-between",
        direction: "rtl", pointerEvents: "none",
      }}>
        <button
          onClick={onClose}
          style={{ pointerEvents: "auto", background: "none", border: "none", color: "#fff", cursor: "pointer", padding: 4, display: "flex", alignItems: "center", WebkitTapHighlightColor: "transparent", outline: "none" }}
        >
          <X size={28} strokeWidth={2.5} />
        </button>
        <div style={{ flex: 1, textAlign: "center", paddingTop: 2 }}>
          <div style={{ color: "#fff", fontSize: 15, fontWeight: 700, fontFamily: "Arial", textShadow: "0 1px 6px rgba(0,0,0,0.9)" }}>
            {movie.title}
          </div>
          {movie.episode_number && (
            <div style={{ color: "rgba(255,255,255,0.7)", fontSize: 12, fontFamily: "Arial", marginTop: 2 }}>
              {movie.episode_title
                ? `פרק ${movie.episode_number} - ${movie.episode_title}`
                : `פרק ${movie.episode_number}`}
            </div>
          )}
        </div>
        <div style={{ width: 36, flexShrink: 0 }} />
      </div>

      {/* Plyr mounts here */}
      <div ref={containerRef} style={{ position: "absolute", inset: 0, background: "#000" }} />
    </div>
  );
}

// ─── HLS player ───────────────────────────────────────────────
function HlsPlayer({ src, movie, onClose }) {
  const containerRef = useRef(null);
  const videoElRef = useRef(null);
  const playerRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [skipAnim, setSkipAnim] = useState(null);

  useEffect(() => {
    if (!src || !containerRef.current) return;
    let destroyed = false;
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
      const vjs = window.videojs(videoEl, { controls: false, autoplay: true, fill: true });
      const shaka = new window.shaka.Player();
      await shaka.attach(videoEl);
      playerRef.current = { vjs, shaka };
      try {
        await shaka.load(src);
        if (!destroyed) { videoEl.play().catch(() => {}); setLoading(false); }
      } catch {
        if (!destroyed) { vjs.src({ src, type: "application/x-mpegURL" }); vjs.play().catch(() => {}); setLoading(false); }
      }
    };
    init();
    return () => {
      destroyed = true;
      playerRef.current?.shaka?.destroy();
      playerRef.current?.vjs?.dispose();
      playerRef.current = null; videoElRef.current = null;
    };
  }, [src]);

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
      <ControlsLayer videoRef={videoElRef} title={movie.title} episode={movie.episode_title ? `פרק ${movie.episode_number} - ${movie.episode_title}` : movie.episode_number ? `פרק ${movie.episode_number}` : null} onClose={onClose} onSkip={handleSkip} skipAnim={skipAnim} />
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
export default function CustomVideoPlayer({ movie, onClose }) {
  const src = buildSrc(movie);
  const type = movie.type || "direct";

  return (
    <div style={{ position: "fixed", inset: 0, background: "#000", zIndex: 9999, display: "flex", flexDirection: "column" }}>
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
        <HlsPlayer src={src} movie={movie} onClose={onClose} />
      ) : isIframeUrl(src, type) ? (
        <IframePlayer src={src} movie={movie} onClose={onClose} />
      ) : (
        <PlyrVideoPlayer src={src} movie={movie} onClose={onClose} />
      )}
    </div>
  );
}
