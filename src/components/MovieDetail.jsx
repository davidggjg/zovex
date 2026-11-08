import { useState } from "react";
import { useDescription } from "./home/useDescription";
import { ArrowRight, Play, Heart, X, Volume2, VolumeX } from "lucide-react";
import { useTrailer } from "./home/useFavorites";
import { glass } from "@/theme/tokens";
import { t } from "../i18n";

// מזהה "שם בסיס" של סרט כדי לאתר סרטי המשך - מסיר מספר עוקב בסוף השם, כולל
// כשהוא מגיע אחרי מילת חיבור כמו "חלק"/"פרק"/"Part" (לדוגמה "המדרון 1" ו"המדרון
// חלק 2" צריכים לזהות אותו שם בסיס "המדרון", לא רק "Title N" ו-"Title N" זהים)
function baseTitle(title) {
  return (title || "").replace(/\s*(חלק|פרק|part|chapter)?\s*\d+$/i, "").trim();
}

// מסך הפרטים של סרט בודד — פוסטר, תיאור, כפתור צפייה וסרטי המשך
export default function MovieDetail({ movie, movies, onPlay, onClose, onSelectMovie,
                                     isFavorite, onToggleFavorite }) {
  // הטריילר מחליף את הפוסטר כשיש. הפוסטר נשאר ברירת המחדל ולא מוחלף עד
  // שהמפתח חוזר בפועל — פריט בלי טריילר נראה בדיוק כמו קודם, בלי הבהוב.
  const trailerKey = useTrailer(movie);
  // התיאור אינו חלק מהקטלוג המהיר — הוא נמשך לפריט הזה בלבד.
  const description = useDescription(movie);
  const [trailerOff, setTrailerOff] = useState(false);
  // מושתק בהתחלה: זה התנאי של הדפדפנים להפעלה אוטומטית.
  const [heroMuted, setHeroMuted] = useState(true);
  const baseName = baseTitle(movie.title);
  // חלק מסרטי ההמשך לא נקראים "שם 2" (למשל "ראלף ההורס" -> "ראלף שובר את
  // האינטרנט") - אז אי אפשר לזהות אותם לפי מספר בסוף השם. במקרים כאלה
  // מסמנים ידנית באדמין את אותו franchise על שני הסרטים, וכך הם מתקשרים
  // גם בלי כותרת דומה.
  const sequels = movies.filter(m => {
    if (m.series_name || m.id === movie.id) return false;
    if (movie.franchise && m.franchise) return m.franchise === movie.franchise;
    return baseTitle(m.title) === baseName;
  }).sort((a, b) => (a.year || 0) - (b.year || 0));
  return (
    <div style={{ background: "#07070C", minHeight: "100vh", direction: "rtl", fontFamily: "Arial, sans-serif", color: "#fff" }}>
      <button onClick={onClose} style={{ position: "fixed", top: 15, right: 15, zIndex: 100, background: "rgba(0,0,0,.7)", border: "none", color: "#fff", borderRadius: "50%", width: 44, height: 44, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer" }}>
        <ArrowRight size={22} />
      </button>
      {/* ── הכותר: טריילר אם יש, אחרת התמונה ────────────────────────────
          התמונה היא פוסטר לאורך, ו-objectFit: cover בתוך מלבן רחב
          ונמוך חתך ממנו פס מהאמצע — הראש והכיתוב נעלמו. זה מה
          שנראה "לחוץ".

          כשיש טריילר הוא עולה לכאן ומתנגן מיד. מושתק, כי זה התנאי
          של כל הדפדפנים להפעלה אוטומטית — וידאו עם קול אינו מורשה
          להתחיל לבד, והניסיון פשוט נדחה. יש כפתור קול, וכיבוי
          הטריילר מחזיר את התמונה.

          היחס הוא 16:9 האמיתי של הסרטון ולא גובה קבוע, אחרת נחזור
          בדיוק לחיתוך שממנו ברחנו. */}
      <div style={{ position: "relative", background: "#000" }}>
        {trailerKey && !trailerOff ? (
          <div style={{ position: "relative", width: "100%", paddingTop: "56.25%" }}>
            <iframe
              src={`https://www.youtube-nocookie.com/embed/${trailerKey}?autoplay=1&mute=${heroMuted ? 1 : 0}&playsinline=1&rel=0&modestbranding=1&controls=0&loop=1&playlist=${trailerKey}`}
              title={t("detail.trailer")}
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
              referrerPolicy="strict-origin-when-cross-origin"
              style={{ position: "absolute", inset: 0, width: "100%", height: "100%", border: "none" }}
            />
            <div style={{ position: "absolute", bottom: 10, insetInlineStart: 12,
                          display: "flex", gap: 8, zIndex: 3 }}>
              <button onClick={() => setHeroMuted(m => !m)}
                aria-label={heroMuted ? "הפעל קול" : "השתק"}
                style={{ ...glass("chip"), borderRadius: 999, width: 38, height: 38,
                         display: "flex", alignItems: "center", justifyContent: "center",
                         color: "#fff", cursor: "pointer" }}>
                {heroMuted ? <VolumeX size={17} /> : <Volume2 size={17} />}
              </button>
              <button onClick={() => setTrailerOff(true)}
                style={{ ...glass("chip"), borderRadius: 999, height: 38, padding: "0 14px",
                         color: "#fff", cursor: "pointer", fontSize: 12.5, fontWeight: 700,
                         fontFamily: "inherit" }}>
                {t("common.close")}
              </button>
            </div>
          </div>
        ) : (
          movie.thumbnail_url && (
            <div style={{ position: "relative", width: "100%", paddingTop: "56.25%",
                          overflow: "hidden" }}>
              {/* אותה תמונה פעמיים: מטושטשת ב-cover כדי למלא את
                  המסגרת, ושלמה ב-contain מלפנים — כך הפוסטר נראה
                  בשלמותו ולא נחתך. */}
              <img src={movie.thumbnail_url} alt="" aria-hidden="true"
                style={{ position: "absolute", inset: 0, width: "100%", height: "100%",
                         objectFit: "cover", filter: "blur(26px) saturate(150%)",
                         transform: "scale(1.2)" }} />
              <img src={movie.thumbnail_url} alt=""
                style={{ position: "absolute", inset: 0, width: "100%", height: "100%",
                         objectFit: "contain" }}
                onError={e => (e.target.style.display = "none")} />
            </div>
          )
        )}
        <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 120,
                      pointerEvents: "none",
                      background: "linear-gradient(transparent, #07070C)" }} />
      </div>
      <div style={{ padding: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 900, margin: "0 0 8px", color: "#fff" }}>{movie.title}</h1>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
          {movie.category && <span style={{ background: "#e50914", color: "#fff", padding: "4px 12px", borderRadius: 20, fontSize: 12, fontWeight: "bold" }}>{movie.category}</span>}
          {movie.year && <span style={{ background: "#222", color: "#888", padding: "4px 12px", borderRadius: 20, fontSize: 12 }}>{movie.year}</span>}
        </div>
        {description && <div style={{ margin: "0 0 20px" }}><div style={{ fontSize: 13, fontWeight: 700, color: "#ddd", marginBottom: 6 }}>תיאור הסרט 🎬:</div><p style={{ fontSize: 14, lineHeight: 1.8, color: "#bbb", margin: 0 }}>{description}</p></div>}
        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={onPlay} style={{ flex: 1, background: "#e50914", color: "#fff", border: "none", padding: 16, fontSize: 17, fontWeight: "bold", borderRadius: 12, display: "flex", alignItems: "center", justifyContent: "center", gap: 10, cursor: "pointer" }}>
            <Play fill="white" size={20} /> לצפייה עכשיו
          </button>
          {onToggleFavorite && (
            <button onClick={() => onToggleFavorite(movie)}
              title={isFavorite ? "הסר מהמועדפים" : "הוסף למועדפים"}
              style={{ width: 58, borderRadius: 12, cursor: "pointer",
                       border: "1px solid rgba(255,255,255,.12)",
                       background: isFavorite ? "rgba(229,9,20,.18)" : "rgba(255,255,255,.06)",
                       color: isFavorite ? "#ff4d5e" : "#e8eaed",
                       display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Heart size={22} fill={isFavorite ? "#ff4d5e" : "none"} />
            </button>
          )}
        </div>
        {/* הטריילר עבר לראש העמוד ומתנגן שם מיד. */}

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
