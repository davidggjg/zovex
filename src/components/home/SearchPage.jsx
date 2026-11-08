import { useEffect, useMemo, useRef, useState } from "react";
import { Search, X, ArrowRight } from "lucide-react";
import { colors, radius, glass, glassFloating, depth } from "@/theme/tokens";
import { NetflixCard } from "./NetflixCard";

// ─────────────────────────────────────────────────────────────────────────────
// דף חיפוש נפרד.
//
// מה שהיה: שכבה צפה מעל דף הבית. בטלפון היא כיסתה את התוצאות, ואחרי
// שתוקנה היא עדיין השאירה את החיפוש "נדבק" על מסך שלא נועד לו — אי
// אפשר לסנן, אי אפשר לראות כמה נמצאו, ואין לאן לחזור.
//
// באפליקציה יש מסך חיפוש משלו, וזה הדבר הנכון. מה שלא נלקח משם הוא
// המראה: שם זה רשת מרובעת של כפתורים. כאן המסננים הם שבבים (chips)
// בשורה נגללת — אותה פעולה, בלי קופסאות.
//
// ## הסינון
//
// שלושה צירים, וכולם עובדים יחד: טקסט חופשי, סוג (סרטים/סדרות), ושנה.
// השנים נבנות מהקטלוג עצמו ולא מרשימה קשיחה — כך אין עשורים ריקים
// ואין שנה חסרה.
//
// פרקים של סדרה מקובצים לשורה אחת לפי שם הסדרה, אחרת חיפוש "החממה"
// מחזיר 167 כרטיסים זהים במקום סדרה אחת.
// ─────────────────────────────────────────────────────────────────────────────

const CHIP = (on) => ({
  ...glass("chip"),
  borderRadius: radius.pill, padding: "7px 14px", cursor: "pointer",
  fontFamily: "inherit", fontSize: 13, fontWeight: 700, whiteSpace: "nowrap",
  color: on ? colors.text : colors.textSecondary,
  boxShadow: on ? `inset 0 0 0 1px ${colors.glowRed}` : glass("chip").boxShadow,
});

export default function SearchPage({ movies, seriesMap, liveChannels, onClose,
                                     handleItemClick, initialTerm = "" }) {
  const [term, setTerm] = useState(initialTerm);
  const [kind, setKind] = useState("all");      // all | movie | series | live
  const [year, setYear] = useState("");
  const inputRef = useRef(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const years = useMemo(() => {
    const set = new Set();
    for (const m of movies) if (m.year) set.add(String(m.year));
    return [...set].sort((a, b) => b.localeCompare(a));
  }, [movies]);

  const results = useMemo(() => {
    const q = term.trim().toLowerCase();
    const hit = (s) => String(s || "").toLowerCase().includes(q);

    // סדרות: שורה אחת לכל סדרה, לא כרטיס לכל פרק.
    const out = [];
    const seenSeries = new Set();
    // "הכל" חייב לכלול גם שידורים חיים: useMovieLibrary מפריד אותם
    // מ-movies, ובלי האיחוד כאן חיפוש "ספורט 4" לא החזיר כלום.
    const pool = kind === "live" ? liveChannels
               : kind === "all" ? [...movies, ...liveChannels]
               : movies;

    for (const m of pool) {
      if (kind === "movie" && m.series_name) continue;
      if (kind === "series" && !m.series_name) continue;
      if (year && String(m.year || "") !== year) continue;
      if (q && !(hit(m.title) || hit(m.series_name) || hit(m.en_title))) continue;

      if (m.series_name) {
        if (seenSeries.has(m.series_name)) continue;
        seenSeries.add(m.series_name);
        out.push(seriesMap[m.series_name] || m);
      } else {
        out.push(m);
      }
      if (out.length >= 120) break;
    }
    return out;
  }, [term, kind, year, movies, liveChannels, seriesMap]);

  const empty = !term.trim() && !year && kind === "all";

  return (
    <div dir="rtl" style={{ minHeight: "100vh", background: "transparent",
                            paddingBottom: 110 }}>
      {/* שורת החיפוש — דביקה למעלה, חומר chrome */}
      <div style={{ position: "sticky", top: 0, zIndex: 30, padding: "12px 14px 10px",
                    ...glass("chrome"), border: "none" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button onClick={onClose} aria-label="חזרה"
            style={{ ...glass("chip"), borderRadius: "50%", width: 40, height: 40,
                     display: "flex", alignItems: "center", justifyContent: "center",
                     cursor: "pointer", color: colors.text, flexShrink: 0 }}>
            <ArrowRight size={19} />
          </button>
          <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 9,
                        ...glass("panel"), borderRadius: radius.pill, padding: "11px 15px" }}>
            <Search size={17} color={colors.textMuted} />
            <input ref={inputRef} value={term} onChange={(e) => setTerm(e.target.value)}
              placeholder="חפש סרט, סדרה או ערוץ…"
              style={{ background: "none", border: "none", outline: "none", width: "100%",
                       fontSize: 16, color: colors.text, fontFamily: "inherit" }} />
            {!!term && (
              <button onClick={() => setTerm("")} aria-label="נקה"
                style={{ background: "none", border: "none", cursor: "pointer", padding: 0,
                         display: "flex" }}>
                <X size={17} color={colors.textMuted} />
              </button>
            )}
          </div>
        </div>

        {/* מסננים: שבבים בשורה נגללת, לא רשת כפתורים */}
        {/* השבב האחרון נחתך בקצה: גלילה אופקית ב-RTL אינה משאירה
            מרווח בסוף מעצמה. */}
        <div style={{ display: "flex", gap: 7, marginTop: 10, overflowX: "auto",
                      paddingBottom: 2, paddingInlineEnd: 14, scrollbarWidth: "none",
                      WebkitOverflowScrolling: "touch" }}>
          {[["all", "הכל"], ["movie", "סרטים"], ["series", "סדרות"], ["live", "שידורים חיים"]]
            .map(([k, label]) => (
              <button key={k} onClick={() => setKind(k)} style={CHIP(kind === k)}>{label}</button>
            ))}
          <span style={{ width: 1, background: colors.glassBorder, margin: "0 3px",
                         flexShrink: 0 }} />
          <button onClick={() => setYear("")} style={CHIP(!year)}>כל השנים</button>
          {years.slice(0, 40).map((y) => (
            <button key={y} onClick={() => setYear(y === year ? "" : y)}
              style={CHIP(year === y)}>{y}</button>
          ))}
        </div>
      </div>

      {/* בלי חיפוש זה דף עיון, לא דף ריק — ולכן הכיתוב אומר מה מוצג
          במקום לבקש להקליד בזמן שכבר מוצגים פריטים. */}
      <div style={{ padding: "12px 14px 0", color: colors.textMuted, fontSize: 12.5 }}>
        {empty
          ? "עיון בכל התוכן — הקלד או בחר שנה כדי לסנן"
          : `${results.length}${results.length >= 120 ? "+" : ""} תוצאות`}
      </div>

      <div style={{ display: "grid", gap: 12, padding: 14,
                    gridTemplateColumns: "repeat(auto-fill, minmax(104px, 1fr))" }}>
        {results.map((m) => {
          const isSer = !!(m.episodes || m.name);
          return (
            <NetflixCard key={m.id || m.name || m.series_name} item={m}
              isSer={isSer} isLive={!!m.is_live}
              cardW="100%" cardH={160}
              onClick={() => handleItemClick(m, isSer)} />
          );
        })}
      </div>

      {!empty && results.length === 0 && (
        <div style={{ textAlign: "center", color: colors.textMuted, fontSize: 14,
                      padding: "40px 20px", lineHeight: 1.7 }}>
          לא נמצא כלום.<br />נסה שם אחר, או הסר את מסנן השנה.
        </div>
      )}
    </div>
  );
}
