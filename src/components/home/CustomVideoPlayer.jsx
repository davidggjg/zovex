import { X, Play, Pause, Volume2, VolumeX, Maximize, RotateCcw, RotateCw } from "lucide-react";
import { useEffect, useRef, useState, useCallback } from "react";

const spinStyle = `@keyframes spin { to { transform: rotate(360deg); } }
@keyframes fadeInOut { 0%{opacity:0;transform:translateY(-50%) scale(0.7)} 25%{opacity:1;transform:translateY(-50%) scale(1.1)} 70%{opacity:1} 100%{opacity:0} }
@keyframes fadeUp { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:translateY(0)} }`;

function buildSrc(movie) {
  const vid = (movie.video_id || movie.video_url || "").trim();
  const type = movie.type || "direct";
  if (!vid) return null;

  if (vid.includes("kaltura.com")) return vid;

  // זיהוי Kaltura לפי פורמט video_id: partnerId/uiconfId/entryId
  const kalturaPattern = /^(\d+)\/(\d+)\/([a-zA-Z0-9_]+)$/;
  const kalturaMatch = vid.match(kalturaPattern);
  if (type === "kaltura" || kalturaMatch) {
    const parts = vid.split("/");
    if (parts.length >= 3) {
      const partnerId = parts[0], uiconfId = parts[1], entryId = parts[2];
      return `https://cdnapisec.kaltura.com/p/${partnerId}/embedPlaykitJs/uiconf_id/${uiconfId}?iframeembed=true&entry_id=${entryId}`;
    }
    return null;
  }

  if (type === "youtube" || vid.includes("youtube.com") || vid.includes("youtu.be")) {
    const m = vid.match(/(?:v=|youtu\.be\/)([^&/?]+)/);
    const id = m ? m[1] : vid;
    return `https://www.youtube.com/embed/${id}?autoplay=1`;
  }

  if (type === "drive" || vid.includes("drive.google.com")) {
    const m = vid.match(/\/d\/([^/?]+)/);
    const id = m ? m[1] : vid;
    return `https://drive.google.com/file/d/${id}/preview`;
  }

  if (type === "vimeo" || vid.includes("vimeo.com")) {
    const m = vid.match(/vimeo\.com\/(\d+)/);
    const id = m ? m[1] : vid;
    return `https://player.vimeo.com/video/${id}?autoplay=1`;
  }

  if (type === "dailymotion" || vid.includes("dailymotion.com") || vid.includes("dai.ly")) {
    const m = vid.match(/(?:video\/|dai\.ly\/)([a-zA-Z0-9]+)/);
    const id = m ? m[1] : vid;
    return `https://www.dailymotion.com/embed/video/${id}?autoplay=1`;
  }

  if (type === "streamable" || vid.includes("streamable.com")) {
    const m = vid.match(/streamable\.com\/([a-zA-Z0-9]+)/);
    const id = m ? m[1] : vid;
    return `https://streamable.com/e/${id}?autoplay=1`;
  }

  if (type === "rumble" || vid.includes("rumble.com")) {
    const m = vid.match(/(?:embed\/|video\/)([a-zA-Z0-9]+)/);
    const id = m ? m[1] : vid;
    return `https://rumble.com/embed/${id}/`;
  }

  if (type === "archive" || vid.includes("archive.org")) {
    const m = vid.match(/archive\.org\/(?:embed|details)\/([^/?]+)/);
    const id = m ? m[1] : vid;
    return `https://archive.org/embed/${id}`;
  }

  if (type === "kan" || vid.includes("kan.org.il")) {
    return `https://www.kan.org.il/General/Embed.aspx?id=${vid}`;
  }

  if (type === "okru" || vid.includes("ok.ru")) {
    const m = vid.match(/ok\.ru\/video\/(\d+)/);
    const id = m ? m[1] : vid;
    return `https://ok.ru/videoembed/${id}`;
  }

  if (type === "telegram" || vid.includes("t.me")) {
    const id = vid.replace(/.*t\.me\//, "");
    return `https://t.me/${id}?embed=1&mode=tme`;
  }

  if (type === "jellyfin") {
    const server = (movie.jellyfin_server || "").replace(/\/$/, "");
    const apiKey = movie.jellyfin_api_key || "";
    if (server && vid) return `${server}/web/index.html#!/video?id=${vid}&serverId=&api_key=${apiKey}`;
    return null;
  }

  if (type === "cloudinary") {
    const cloud = movie.cloudinary_cloud_name || "";
    return cloud ? `https://res.cloudinary.com/${cloud}/video/upload/${vid}` : null;
  }

  return vid.startsWith("http") ? vid : null;
}

function isHlsUrl(src) {
  if (!src) return false;
  return src.includes(".m3u8") || src.includes("Manifest.ism");
}

function isIframeUrl(src, type) {
  if (!src) return false;
  const iframeTypes = ["youtube", "drive", "vimeo", "dailymotion", "streamable",
    "rumble", "archive", "kan", "okru", "telegram", "kaltura", "jellyfin"];
  if (iframeTypes.includes(type)) return true;
  const iframeDomains = ["youtube.com", "youtu.be", "drive.google.com", "vimeo.com",
    "dailymotion.com", "streamable.com", "rumble.com", "archive.org",
    "kan.org.il", "ok.ru", "t.me", "kaltura.com"];
  return iframeDomains.some(d => src.includes(d));
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

// ─── Skip animation overlay (sides only) ───────────────────
function SkipSideOverlay({ onSkip, skipAnim }) {
  return (
    <>
      <div onDoubleClick={() => onSkip("back")}
        style={{ position: "absolute", top: 0, left: 0, width: "25%", height: "85%", zIndex: 5, background: "transparent" }} />
      <div onDoubleClick={() => onSkip("forward")}
        style={{ position: "absolute", top: 0, right: 0, width: "25%", height: "85%", zIndex: 5, background: "transparent" }} />
      {skipAnim && (
        <div style={{
          position: "absolute", top: "40%",
          [skipAnim === "forward" ? "right" : "left"]: "6%",
          transform: "translateY(-50%)", pointerEvents: "none", zIndex: 6,
          animation: "fadeInOut 0.7s ease"
        }}>
          <div style={{
            background: "rgba(0,0,0,0.6)", backdropFilter: "blur(6px)",
            borderRadius: 16, padding: "12px 20px",
            display: "flex", flexDirection: "column", alignItems: "center", gap: 4,
            border: "1px solid rgba(255,255,255,0.15)"
          }}>
            <span style={{ fontSize: 22, color: "#fff" }}>{skipAnim === "forward" ? "▶▶" : "◀◀"}</span>
            <span style={{ fontSize: 12, color: "#fff", fontWeight: "bold", fontFamily: "Arial" }}>
              {skipAnim === "forward" ? "+10" : "-10"} שניות
            </span>
          </div>
        </div>
      )}
    </>
  );
}

// ─── Custom controls bar ─────────────────────────────────────
function VideoControls({ videoRef, title, onClose, onSkip }) {
  const [playing, setPlaying] = useState(true);
  const [muted, setMuted] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [visible, setVisible] = useState(true);
  const [dragging, setDragging] = useState(false);
  const hideTimer = useRef(null);
  const progressRef = useRef(null);

  const resetTimer = useCallback(() => {
    setVisible(true);
    clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => setVisible(false), 3000);
  }, []);

  useEffect(() => {
    resetTimer();
    return () => clearTimeout(hideTimer.current);
  }, [resetTimer]);

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
    if (v.paused) v.play(); else v.pause();
    resetTimer();
  };

  const toggleMute = () => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = !v.muted;
    setMuted(v.muted);
    resetTimer();
  };

  const seek = (e) => {
    const v = videoRef.current;
    const bar = progressRef.current;
    if (!v || !bar || !duration) return;
    const rect = bar.getBoundingClientRect();
    const x = (e.clientX ?? e.touches?.[0]?.clientX) - rect.left;
    const ratio = Math.max(0, Math.min(1, x / rect.width));
    v.currentTime = ratio * duration;
    setCurrentTime(ratio * duration);
    resetTimer();
  };

  const goFullscreen = () => {
    const el = document.documentElement;
    if (document.fullscreenElement) {
      document.exitFullscreen?.();
    } else {
      el.requestFullscreen?.() || el.webkitRequestFullscreen?.();
    }
    resetTimer();
  };

  const progress = duration ? (currentTime / duration) * 100 : 0;

  return (
    <div
      onMouseMove={resetTimer}
      onTouchStart={resetTimer}
      style={{ position: "absolute", inset: 0, zIndex: 10 }}
      onClick={(e) => { if (e.target === e.currentTarget) { togglePlay(); resetTimer(); } }}
    >
      {/* top bar */}
      <div style={{
        position: "absolute", top: 0, left: 0, right: 0,
        padding: "16px 16px 30px",
        background: "linear-gradient(to bottom, rgba(0,0,0,0.7) 0%, transparent 100%)",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        transition: "opacity 0.3s", opacity: visible ? 1 : 0,
        pointerEvents: visible ? "auto" : "none",
      }}>
        <button onClick={onClose} style={{
          background: "rgba(255,255,255,0.12)", backdropFilter: "blur(8px)",
          border: "1px solid rgba(255,255,255,0.2)", color: "#fff",
          borderRadius: "50%", width: 40, height: 40,
          display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer"
        }}>
          <X size={20} />
        </button>
        <p style={{ color: "#fff", fontSize: 14, margin: 0, fontFamily: "Arial", fontWeight: 600, textShadow: "0 1px 4px rgba(0,0,0,0.8)" }}>
          {title}
        </p>
        <div style={{ width: 40 }} />
      </div>

      {/* skip overlays */}
      <SkipSideOverlay onSkip={onSkip} skipAnim={null} />

      {/* bottom controls */}
      <div style={{
        position: "absolute", bottom: 0, left: 0, right: 0,
        padding: "30px 16px 16px",
        background: "linear-gradient(to top, rgba(0,0,0,0.85) 0%, transparent 100%)",
        transition: "opacity 0.3s", opacity: visible ? 1 : 0,
        pointerEvents: visible ? "auto" : "none",
        animation: "fadeUp 0.3s ease",
      }}>
        {/* progress bar */}
        <div style={{ marginBottom: 10, position: "relative" }}>
          <div
            ref={progressRef}
            onClick={seek}
            onMouseDown={(e) => { setDragging(true); seek(e); }}
            onMouseMove={(e) => { if (dragging) seek(e); }}
            onMouseUp={() => setDragging(false)}
            onTouchStart={(e) => { setDragging(true); seek(e); }}
            onTouchMove={(e) => { if (dragging) seek(e); }}
            onTouchEnd={() => setDragging(false)}
            style={{
              width: "100%", height: 4, background: "rgba(255,255,255,0.25)",
              borderRadius: 4, cursor: "pointer", position: "relative",
              transition: "height 0.15s",
            }}
            onMouseEnter={e => e.currentTarget.style.height = "6px"}
            onMouseLeave={e => e.currentTarget.style.height = "4px"}
          >
            <div style={{
              position: "absolute", top: 0, left: 0, height: "100%",
              width: `${progress}%`, background: "#e50914", borderRadius: 4,
              transition: dragging ? "none" : "width 0.1s",
            }} />
            <div style={{
              position: "absolute", top: "50%", left: `${progress}%`,
              transform: "translate(-50%, -50%)",
              width: 14, height: 14, borderRadius: "50%",
              background: "#fff", boxShadow: "0 0 6px rgba(0,0,0,0.5)",
              transition: dragging ? "none" : "left 0.1s",
            }} />
          </div>
        </div>

        {/* buttons row */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {/* skip back */}
            <button onClick={() => { onSkip("back"); resetTimer(); }} style={btnStyle}>
              <RotateCcw size={20} />
              <span style={{ fontSize: 10, position: "absolute", bottom: 2, right: 2, fontFamily: "Arial", fontWeight: "bold" }}>10</span>
            </button>
            {/* play/pause */}
            <button onClick={togglePlay} style={{ ...btnStyle, width: 48, height: 48 }}>
              {playing ? <Pause size={22} /> : <Play size={22} fill="#fff" />}
            </button>
            {/* skip forward */}
            <button onClick={() => { onSkip("forward"); resetTimer(); }} style={btnStyle}>
              <RotateCw size={20} />
              <span style={{ fontSize: 10, position: "absolute", bottom: 2, left: 2, fontFamily: "Arial", fontWeight: "bold" }}>10</span>
            </button>
            {/* mute */}
            <button onClick={toggleMute} style={btnStyle}>
              {muted ? <VolumeX size={20} /> : <Volume2 size={20} />}
            </button>
            {/* time */}
            <span style={{ color: "rgba(255,255,255,0.8)", fontSize: 12, fontFamily: "Arial", marginLeft: 4 }}>
              {formatTime(currentTime)} / {formatTime(duration)}
            </span>
          </div>
          {/* fullscreen */}
          <button onClick={goFullscreen} style={btnStyle}>
            <Maximize size={20} />
          </button>
        </div>
      </div>
    </div>
  );
}

const btnStyle = {
  background: "rgba(255,255,255,0.1)", backdropFilter: "blur(4px)",
  border: "1px solid rgba(255,255,255,0.15)", color: "#fff",
  borderRadius: "50%", width: 40, height: 40, cursor: "pointer",
  display: "flex", alignItems: "center", justifyContent: "center",
  position: "relative", flexShrink: 0,
};

// ─── Direct video player with custom controls ────────────────
function DirectVideoPlayer({ src, videoRef, title, onClose }) {
  const [skipAnim, setSkipAnim] = useState(null);

  const handleSkip = useCallback((side) => {
    const secs = side === "forward" ? 10 : -10;
    const v = videoRef.current;
    if (v) v.currentTime = Math.max(0, v.currentTime + secs);
    setSkipAnim(side);
    setTimeout(() => setSkipAnim(null), 700);
  }, [videoRef]);

  return (
    <div style={{ flex: 1, position: "relative", background: "#000" }}>
      <video
        ref={videoRef}
        src={src}
        autoPlay
        playsInline
        style={{ width: "100%", height: "100%", background: "#000", display: "block" }}
      />
      {skipAnim && (
        <div style={{
          position: "absolute", top: "40%",
          [skipAnim === "forward" ? "right" : "left"]: "6%",
          transform: "translateY(-50%)", pointerEvents: "none", zIndex: 6,
          animation: "fadeInOut 0.7s ease"
        }}>
          <div style={{
            background: "rgba(0,0,0,0.6)", backdropFilter: "blur(6px)",
            borderRadius: 16, padding: "12px 20px",
            display: "flex", flexDirection: "column", alignItems: "center", gap: 4,
            border: "1px solid rgba(255,255,255,0.15)"
          }}>
            <span style={{ fontSize: 22, color: "#fff" }}>{skipAnim === "forward" ? "▶▶" : "◀◀"}</span>
            <span style={{ fontSize: 12, color: "#fff", fontWeight: "bold", fontFamily: "Arial" }}>
              {skipAnim === "forward" ? "+10" : "-10"} שניות
            </span>
          </div>
        </div>
      )}
      <VideoControls videoRef={videoRef} title={title} onClose={onClose} onSkip={handleSkip} />
    </div>
  );
}

// ─── HLS player ──────────────────────────────────────────────
function HlsPlayer({ src, title, onClose }) {
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
      videoEl.className = "video-js vjs-default-skin vjs-big-play-centered";
      videoEl.setAttribute("playsinline", "");
      videoEl.setAttribute("autoplay", "");
      videoEl.style.width = "100%";
      videoEl.style.height = "100%";
      videoEl.style.position = "absolute";
      videoEl.style.inset = "0";
      containerRef.current.appendChild(videoEl);
      videoElRef.current = videoEl;

      const vjs = window.videojs(videoEl, {
        controls: false,
        autoplay: true,
        fill: true,
        techOrder: ["html5"],
        html5: { nativeAudioTracks: false, nativeVideoTracks: false },
      });

      const shaka = new window.shaka.Player();
      await shaka.attach(videoEl);
      shaka.configure({
        preferredAudioChannelCount: 2,
        streaming: { bufferingGoal: 30, rebufferingGoal: 2 },
      });

      playerRef.current = { vjs, shaka };

      try {
        await shaka.load(src);
        if (!destroyed) { videoEl.play().catch(() => {}); setLoading(false); }
      } catch {
        if (!destroyed) {
          vjs.src({ src, type: "application/x-mpegURL" });
          vjs.play().catch(() => {});
          setLoading(false);
        }
      }
    };

    init();

    return () => {
      destroyed = true;
      playerRef.current?.shaka?.destroy();
      playerRef.current?.vjs?.dispose();
      playerRef.current = null;
      videoElRef.current = null;
    };
  }, [src]);

  const handleSkip = useCallback((side) => {
    const secs = side === "forward" ? 10 : -10;
    const v = videoElRef.current;
    if (v) v.currentTime = Math.max(0, v.currentTime + secs);
    setSkipAnim(side);
    setTimeout(() => setSkipAnim(null), 700);
  }, []);

  return (
    <div style={{ flex: 1, width: "100%", background: "#000", position: "relative" }}>
      {loading && (
        <div style={{ position: "absolute", inset: 0, zIndex: 5, display: "flex", alignItems: "center", justifyContent: "center", background: "#000" }}>
          <div style={{ width: 44, height: 44, border: "4px solid rgba(255,255,255,0.2)", borderTop: "4px solid #e50914", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
        </div>
      )}
      <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />
      {skipAnim && (
        <div style={{
          position: "absolute", top: "40%",
          [skipAnim === "forward" ? "right" : "left"]: "6%",
          transform: "translateY(-50%)", pointerEvents: "none", zIndex: 20,
          animation: "fadeInOut 0.7s ease"
        }}>
          <div style={{
            background: "rgba(0,0,0,0.6)", backdropFilter: "blur(6px)",
            borderRadius: 16, padding: "12px 20px",
            display: "flex", flexDirection: "column", alignItems: "center", gap: 4,
            border: "1px solid rgba(255,255,255,0.15)"
          }}>
            <span style={{ fontSize: 22, color: "#fff" }}>{skipAnim === "forward" ? "▶▶" : "◀◀"}</span>
            <span style={{ fontSize: 12, color: "#fff", fontWeight: "bold", fontFamily: "Arial" }}>
              {skipAnim === "forward" ? "+10" : "-10"} שניות
            </span>
          </div>
        </div>
      )}
      <VideoControls videoRef={videoElRef} title={title} onClose={onClose} onSkip={handleSkip} />
    </div>
  );
}

// ─── Main export ─────────────────────────────────────────────
export default function CustomVideoPlayer({ movie, onClose }) {
  const src = buildSrc(movie);
  const type = movie.type || "direct";
  const hlsVideo = isHlsUrl(src);
  const useIframe = !hlsVideo && isIframeUrl(src, type);
  const directVideoRef = useRef(null);
  const [iframeLoaded, setIframeLoaded] = useState(false);

  useEffect(() => { setIframeLoaded(false); }, [src]);

  return (
    <div style={{ position: "fixed", inset: 0, background: "#000", zIndex: 9999, display: "flex", flexDirection: "column" }}>
      <style>{spinStyle}</style>

      {!src ? (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "#555", fontSize: 15, fontFamily: "Arial" }}>
          אין קישור וידאו זמין
        </div>
      ) : hlsVideo ? (
        <HlsPlayer src={src} title={movie.title} onClose={onClose} />
      ) : useIframe ? (
        <div style={{ flex: 1, position: "relative" }}>
          {/* top close bar for iframes */}
          <div style={{
            position: "absolute", top: 0, left: 0, right: 0, zIndex: 20,
            padding: "12px 16px",
            background: "linear-gradient(to bottom, rgba(0,0,0,0.7), transparent)",
            display: "flex", alignItems: "center", justifyContent: "space-between",
          }}>
            <button onClick={onClose} style={{
              background: "rgba(255,255,255,0.12)", backdropFilter: "blur(8px)",
              border: "1px solid rgba(255,255,255,0.2)", color: "#fff",
              borderRadius: "50%", width: 40, height: 40,
              display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer"
            }}>
              <X size={20} />
            </button>
            <p style={{ color: "#fff", fontSize: 14, margin: 0, fontFamily: "Arial", fontWeight: 600 }}>
              {movie.title}
            </p>
            <div style={{ width: 40 }} />
          </div>
          {!iframeLoaded && (
            <div style={{
              position: "absolute", inset: 0, zIndex: 10,
              background: "#000",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <div style={{ width: 48, height: 48, border: "4px solid rgba(255,255,255,0.3)", borderTop: "4px solid #fff", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
            </div>
          )}
          <iframe
            key={src}
            src={src}
            onLoad={() => setIframeLoaded(true)}
            style={{ width: "100%", height: "100%", border: "none", display: "block" }}
            allowFullScreen
            allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
          />
        </div>
      ) : (
        <DirectVideoPlayer src={src} videoRef={directVideoRef} title={movie.title} onClose={onClose} />
      )}
    </div>
  );
}
