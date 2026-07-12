import { useState } from "react";
import { ArrowRight, ChevronDown, Play } from "lucide-react";
import { SPIN } from "./home/helpers";

// תצוגת עונות ופרקים של סדרה
export default function SeriesView({ seriesName, seriesMap, onEpisodePlay, onClose }) {
  const [openSeasons, setOpenSeasons] = useState({});
  const [seasonLoading, setSeasonLoading] = useState(false);
  const [showSeasonMenu, setShowSeasonMenu] = useState(false);

  const series = seriesMap[seriesName];
  const episodes = series?.episodes || [];
  const seasonNums = [...new Set(episodes.map(e => e.season_number || 1))].sort((a, b) => a - b);
  const activeSeason = openSeasons._active !== undefined ? openSeasons._active : seasonNums[0];
  const activeEps = episodes.filter(e => (e.season_number || 1) === activeSeason).sort((a, b) => (a.episode_number || 0) - (b.episode_number || 0));
  return (
    <div style={{ background: "#0a0a0a", minHeight: "100vh", direction: "rtl", fontFamily: "Arial, sans-serif", color: "#fff" }}>
      <style>{SPIN}</style>
      <button onClick={onClose} style={{ position: "fixed", top: 15, right: 15, zIndex: 100, background: "rgba(0,0,0,.7)", border: "none", color: "#fff", borderRadius: "50%", width: 44, height: 44, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer" }}>
        <ArrowRight size={22} />
      </button>
      <div style={{ position: "relative" }}>
        {series?.thumbnail_url && <img src={series.thumbnail_url} alt="" style={{ width: "100%", height: "55vw", maxHeight: 380, objectFit: "cover", display: "block" }} onError={e => e.target.style.display = "none"} />}
        <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 130, background: "linear-gradient(transparent,#0a0a0a)" }} />
      </div>
      <div style={{ padding: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 900, margin: "0 0 8px", color: "#fff" }}>{seriesName}</h1>
        <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
          {series?.category && <span style={{ background: "#e50914", color: "#fff", padding: "4px 12px", borderRadius: 20, fontSize: 12, fontWeight: "bold" }}>{series.category}</span>}
          <span style={{ background: "#1a1a1a", color: "#ccc", border: "1px solid #333", padding: "4px 12px", borderRadius: 20, fontSize: 12 }}>{episodes.length} פרקים</span>
          <span style={{ background: "#1a1a1a", color: "#ccc", border: "1px solid #333", padding: "4px 12px", borderRadius: 20, fontSize: 12 }}>{seasonNums.length} עונות</span>
        </div>
        {series?.description && <div style={{ margin: "0 0 20px" }}><div style={{ fontSize: 13, fontWeight: 700, color: "#ddd", marginBottom: 6 }}>תיאור הסדרה 🎬:</div><p style={{ fontSize: 14, lineHeight: 1.8, color: "#aaa", margin: 0 }}>{series.description}</p></div>}
        <div style={{ position: "relative", marginBottom: 18 }}>
          <button onClick={() => setShowSeasonMenu(s => !s)} style={{ display: "flex", alignItems: "center", gap: 10, background: "#1a1a1a", border: "1px solid #333", color: "#fff", borderRadius: 10, padding: "12px 18px", fontSize: 15, fontWeight: 900, cursor: "pointer", fontFamily: "inherit", minWidth: 160 }}>
            <span>עונה {activeSeason}</span><ChevronDown size={18} color="#fff" />
          </button>
          {showSeasonMenu && (
            <div style={{ position: "absolute", top: "calc(100% + 6px)", right: 0, background: "#1a1a1a", borderRadius: 12, boxShadow: "0 8px 30px rgba(0,0,0,.5)", zIndex: 50, minWidth: 160, overflow: "hidden", border: "1px solid #333" }}>
              {seasonNums.map(s => (
                <div key={s} onClick={() => { setShowSeasonMenu(false); if (s === activeSeason) return; setSeasonLoading(true); setTimeout(() => { setOpenSeasons(p => ({ ...p, _active: s })); setSeasonLoading(false); }, 600); }} style={{ padding: "14px 18px", fontSize: 15, fontWeight: s === activeSeason ? 900 : 500, color: s === activeSeason ? "#e50914" : "#fff", cursor: "pointer", background: s === activeSeason ? "rgba(229,9,20,0.12)" : "#1a1a1a", borderBottom: "1px solid #262626" }}>
                  עונה {s}
                </div>
              ))}
            </div>
          )}
        </div>
        {seasonLoading ? (
          <div style={{ display: "flex", justifyContent: "center", padding: "40px 0" }}>
            <div style={{ width: 40, height: 40, border: "4px solid #222", borderTop: "4px solid #e50914", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
          </div>
        ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {activeEps.map((ep, i) => (
            <div key={ep.id} onClick={() => onEpisodePlay(ep)} style={{ display: "flex", gap: 12, padding: "12px 0", borderBottom: "1px solid #222", cursor: "pointer", alignItems: "center" }}>
              <div style={{ width: 42, height: 42, borderRadius: 10, background: "#e50914", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                <Play size={18} fill="white" color="white" />
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: "#fff" }}>פרק {ep.episode_number || i + 1}{ep.episode_title ? " - " + ep.episode_title : ""}</div>
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
