import { ArrowRight, Play } from "lucide-react";

// מסך הפרטים של סרט בודד — פוסטר, תיאור, כפתור צפייה וסרטי המשך
export default function MovieDetail({ movie, movies, onPlay, onClose, onSelectMovie }) {
  const baseName = (movie.title || "").replace(/\s*\d+$/, "").trim();
  const sequels = movies.filter(m => !m.series_name && m.id !== movie.id && (m.title || "").replace(/\s*\d+$/, "").trim() === baseName).sort((a, b) => (a.year || 0) - (b.year || 0));
  return (
    <div style={{ background: "#111", minHeight: "100vh", direction: "rtl", fontFamily: "Arial, sans-serif", color: "#fff" }}>
      <button onClick={onClose} style={{ position: "fixed", top: 15, right: 15, zIndex: 100, background: "rgba(0,0,0,.7)", border: "none", color: "#fff", borderRadius: "50%", width: 44, height: 44, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer" }}>
        <ArrowRight size={22} />
      </button>
      <div style={{ position: "relative" }}>
        {movie.thumbnail_url && <img src={movie.thumbnail_url} alt="" style={{ width: "100%", height: "55vw", maxHeight: 380, objectFit: "cover", display: "block" }} onError={e => e.target.style.display = "none"} />}
        <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 130, background: "linear-gradient(transparent,#111)" }} />
      </div>
      <div style={{ padding: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 900, margin: "0 0 8px", color: "#fff" }}>{movie.title}</h1>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
          {movie.category && <span style={{ background: "#e50914", color: "#fff", padding: "4px 12px", borderRadius: 20, fontSize: 12, fontWeight: "bold" }}>{movie.category}</span>}
          {movie.year && <span style={{ background: "#222", color: "#888", padding: "4px 12px", borderRadius: 20, fontSize: 12 }}>{movie.year}</span>}
        </div>
        {movie.description && <div style={{ margin: "0 0 20px" }}><div style={{ fontSize: 13, fontWeight: 700, color: "#ddd", marginBottom: 6 }}>תיאור הסרט 🎬:</div><p style={{ fontSize: 14, lineHeight: 1.8, color: "#bbb", margin: 0 }}>{movie.description}</p></div>}
        <button onClick={onPlay} style={{ width: "100%", background: "#e50914", color: "#fff", border: "none", padding: 16, fontSize: 17, fontWeight: "bold", borderRadius: 12, display: "flex", alignItems: "center", justifyContent: "center", gap: 10, cursor: "pointer" }}>
          <Play fill="white" size={20} /> לצפייה עכשיו
        </button>
        {sequels.length > 0 && (
          <div style={{ marginTop: 24 }}>
            <div style={{ fontSize: 14, fontWeight: 900, color: "#fff", marginBottom: 12 }}>סרטי המשך</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {sequels.map(s => (
                <div key={s.id} onClick={() => onSelectMovie(s)} style={{ display: "flex", gap: 12, alignItems: "center", background: "#1a1a1a", borderRadius: 12, padding: 10, cursor: "pointer", border: "1px solid #2a2a2a" }}>
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
