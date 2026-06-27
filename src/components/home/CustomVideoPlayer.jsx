import { X, Play, Pause, Volume2, VolumeX, Maximize, RotateCcw, RotateCw, Share2 } from "lucide-react";
import { useEffect, useRef, useState, useCallback } from "react";

const spinStyle = `
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes fadeInOut { 0%{opacity:0;transform:translateY(-50%) scale(0.7)} 25%{opacity:1;transform:translateY(-50%) scale(1.1)} 70%{opacity:1} 100%{opacity:0} }
@keyframes fadeUp { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:translateY(0)} }
`;

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
    const id = vid.replace(/.*t\.me\//, "");
    return `https://t.me/${id}?embed=1&mode=tme`;
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
  const iframeTypes = ["youtube","drive","vimeo","dailymotion","streamable","rumble","archive","kan","okru","telegram","kaltura","jellyfin"];
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
function TopBar({ title, episode, onClose }) {
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
    }}>
      {/* X button — right side (RTL) */}
      <button
        onClick={(e) => { e.stopPropagation(); onClose(); }}
        style={{
          background: "none", border: "none", color: "#fff",
          cursor: "pointer", padding: 4, lineHeight: 1,
          display: "flex", alignItems: "center", justifyContent: "center",
          WebkitTapHighlightColor: "transparent",
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
          WebkitTapHighlightColor: "transparent",
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

  // לחיצה בכל מקום על המסך — תמיד מציגה את הכפתורים
  const handleOverlayClick = useCallback((e) => {
    show();
  }, [show]);

    <div
      style={{ position: "absolute", inset: 0, zIndex: 10 }}
      onMouseMove={show}
      onTouchStart={show}
      onClick={handleOverlayClick}
      onDoubleClick={(e) => e.stopPropagation()}
    >
      {/* TopBar — תמיד גלוי, לא נעלם */}
      <TopBar title={title} episode={episode} onClose={onClose} />

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
        {/* skip -10 — ה-10 בתוך האיקון */}
        <button onClick={(e) => { e.stopPropagation(); onSkip("back"); }} style={centerBtn}>
          <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
            <path d="M16 4 A12 12 0 1 0 27 13" stroke="white" strokeWidth="2.2" strokeLinecap="round" fill="none"/>
            <polyline points="10,1 16,4 10,7" fill="white"/>
            <text x="16" y="20" textAnchor="middle" fill="white" fontSize="8" fontWeight="bold" fontFamily="Arial">10</text>
          </svg>
        </button>
        {/* play/pause */}
        <button onClick={togglePlay} style={{ ...centerBtn, width: 58, height: 58 }}>
          {playing ? <Pause size={28} fill="#fff" /> : <Play size={28} fill="#fff" />}
        </button>
        {/* skip +10 — ה-10 בתוך האיקון */}
        <button onClick={(e) => { e.stopPropagation(); onSkip("forward"); }} style={centerBtn}>
          <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
            <path d="M16 4 A12 12 0 1 1 5 13" stroke="white" strokeWidth="2.2" strokeLinecap="round" fill="none"/>
            <polyline points="22,1 16,4 22,7" fill="white"/>
            <text x="16" y="20" textAnchor="middle" fill="white" fontSize="8" fontWeight="bold" fontFamily="Arial">10</text>
          </svg>
        </button>
      </div>

      <BottomBar videoRef={videoRef} onSkip={onSkip} visible={visible} />
      <SkipAnim side={skipAnim} />
    </div>
  );
}

// ─── Direct video player ──────────────────────────────────────
function DirectVideoPlayer({ src, movie, onClose }) {
  const videoRef = useRef(null);
  const [skipAnim, setSkipAnim] = useState(null);

  const handleSkip = useCallback((side) => {
    const v = videoRef.current;
    if (v) v.currentTime = Math.max(0, v.currentTime + (side === "forward" ? 10 : -10));
    setSkipAnim(side);
    setTimeout(() => setSkipAnim(null), 700);
  }, []);

  return (
    <div style={{ flex: 1, position: "relative", background: "#000" }}>
      <video ref={videoRef} src={src} autoPlay playsInline style={{ width: "100%", height: "100%", display: "block", background: "#000" }} />
      <ControlsLayer videoRef={videoRef} title={movie.title} episode={movie.episode_title ? `פרק ${movie.episode_number} - ${movie.episode_title}` : movie.episode_number ? `פרק ${movie.episode_number}` : null} onClose={onClose} onSkip={handleSkip} skipAnim={skipAnim} />
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
    <div style={{ flex: 1, position: "relative", background: "#000" }}>
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
// FIX: iframe מוגבל לגובה שמשאיר מקום לכותרת — כתוביות לא יחתכו
function IframePlayer({ src, movie, onClose }) {
  const [loaded, setLoaded] = useState(false);
  // גובה ה-TopBar בפועל (כ-70px כולל padding)
  const TOP_BAR_HEIGHT = 70;

  return (
    <div style={{ flex: 1, position: "relative", background: "#000", display: "flex", flexDirection: "column" }}>
      {/* X + title bar — תמיד מעל */}
      <div style={{
        position: "absolute", top: 0, left: 0, right: 0, zIndex: 9999,
        height: TOP_BAR_HEIGHT,
        padding: "14px 16px",
        background: "linear-gradient(to bottom, rgba(0,0,0,0.85) 0%, transparent 100%)",
        display: "flex", alignItems: "flex-start", justifyContent: "space-between",
        direction: "rtl", pointerEvents: "none",
      }}>
        {/* X — pointer-events back on */}
        <button
          onClick={(e) => { e.stopPropagation(); onClose(); }}
          style={{
            background: "rgba(0,0,0,0.5)", backdropFilter: "blur(8px)",
            border: "1px solid rgba(255,255,255,0.25)", color: "#fff",
            borderRadius: "50%", width: 42, height: 42,
            display: "flex", alignItems: "center", justifyContent: "center",
            cursor: "pointer", pointerEvents: "auto",
            WebkitTapHighlightColor: "transparent",
            flexShrink: 0,
          }}
        >
          <X size={22} strokeWidth={2.5} />
        </button>
        {/* title */}
        <div style={{ flex: 1, textAlign: "center", paddingTop: 6, pointerEvents: "none" }}>
          <div style={{ color: "#fff", fontSize: 15, fontWeight: 700, fontFamily: "Arial", textShadow: "0 1px 6px rgba(0,0,0,0.9)" }}>
            {movie.title}
          </div>
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

      {/* FIX: iframe מתחיל מתחת ל-TopBar ולא מכסה אותו */}
      <iframe
        key={src}
        src={src}
        onLoad={() => setLoaded(true)}
        style={{
          width: "100%",
          height: `calc(100% - ${TOP_BAR_HEIGHT}px)`,
          marginTop: TOP_BAR_HEIGHT,
          border: "none",
          display: "block",
        }}
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
        <DirectVideoPlayer src={src} movie={movie} onClose={onClose} />
      )}
    </div>
  );
}
