import { useState, useEffect, useMemo } from "react";
import { NetflixRow } from "./NetflixCard";
import LiveBanner from "../LiveBanner";

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
  const hasLiveRow = (selectedCategory === "הכל" || selectedCategory === "שידורים חיים") && liveItems.length > 0;

  // קבע אילו שורות להציג לפי selectedCategory
  let rowsToShow = [];
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

  if (!hasLiveRow && rowsToShow.length === 0) {
    return <div style={{ textAlign: "center", padding: "60px 20px", color: "#aaa" }}><p style={{ fontSize: 18 }}>לא נמצאו תוצאות</p></div>;
  }

  return (
    <div style={{ paddingTop: 8 }}>
      {/* שורת "המשך צפייה" מוצגת אך ורק בתוך קטגוריית "היסטוריה" (למעלה) —
          לא במסך הראשי/"הכל" ולא בשום קטגוריה אחרת */}
      {hasLiveRow && <LiveBanner liveChannels={liveItems} onPlay={handleItemClick} isDesktop={isDesktop} />}
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

// ═══════════════════════════════════════════════════════════════
// RecentlyAddedBanner — באנר "עלה עכשיו" שמתחלף כל 10 שניות
// ומציג רק תוכן שנוסף ב-24 השעות האחרונות (נעלם אוטומטית אחרי זה)
// ═══════════════════════════════════════════════════════════════
function RecentlyAddedBanner({ movies, seriesMap, handleItemClick }) {
  const items = useMemo(() => {
    const DAY_MS = 24 * 60 * 60 * 1000;
    const now = Date.now();
    const seen = {};
    const recent = [];
    for (const m of movies) {
      if (!m.created_date) continue;
      const t = new Date(m.created_date).getTime();
      if (isNaN(t) || now - t > DAY_MS) continue;
      const key = m.series_name || m.id;
      if (seen[key]) continue;
      seen[key] = true;
      recent.push(m);
      if (recent.length >= 8) break;
    }
    return recent;
  }, [movies]);

  const [index, setIndex] = useState(0);
  const [visible, setVisible] = useState(true);

  useEffect(() => { setIndex(0); }, [items.length]);

  useEffect(() => {
    if (items.length < 2) return;
    const t = setInterval(() => {
      setVisible(false);
      setTimeout(() => {
        setIndex(i => (i + 1) % items.length);
        setVisible(true);
      }, 350);
    }, 10000);
    return () => clearInterval(t);
  }, [items.length]);

  if (items.length === 0) return null;

  const movie = items[index % items.length];
  const isSer = !!movie.series_name;
  const displayItem = isSer ? (seriesMap[movie.series_name] || movie) : movie;
  const title = movie.series_name || movie.title;

  return (
    <div
      onClick={() => handleItemClick(displayItem, isSer)}
      style={{
        position: "relative", margin: "6px 14px 16px", borderRadius: 16, overflow: "hidden",
        cursor: "pointer", height: 170, background: "#111",
        opacity: visible ? 1 : 0, transition: "opacity .35s ease",
      }}
    >
      {movie.thumbnail_url && (
        <img
          src={movie.thumbnail_url} alt={title}
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }}
        />
      )}
      <div style={{ position: "absolute", inset: 0, background: "linear-gradient(to top, rgba(0,0,0,.88), rgba(0,0,0,.1) 65%)" }} />
      <div style={{ position: "absolute", top: 10, right: 10, background: "#e50914", color: "#fff", fontSize: 11, fontWeight: 800, padding: "3px 10px", borderRadius: 20 }}>
        עלה עכשיו
      </div>
      <div style={{ position: "absolute", bottom: 12, right: 14, left: 14 }}>
        <div style={{ color: "#fff", fontSize: 17, fontWeight: 800 }}>{title}</div>
        {!!movie.description && (
          <div style={{ color: "#ddd", fontSize: 12, marginTop: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {movie.description}
          </div>
        )}
      </div>
    </div>
  );
}

export { NetflixRows, RecentlyAddedBanner };
