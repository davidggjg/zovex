import { useState, useEffect, useMemo } from "react";
import { NetflixRow, buildCardHref } from "./NetflixCard";
import LiveBanner from "../LiveBanner";

function NetflixRows({ movies, seriesMap, liveChannels, allCategories, selectedCategory, searchTerm, isDesktop, handleItemClick, onContinueWatchingClick, history, user }) {
  // נרמול לחיפוש: מסיר ניקוד עברי + גרשיים, אותיות קטנות, רווחים כפולים — כך
  // "אס" מוצא גם "אָס". תמיכה בכמה מילים (כל מילה חייבת להימצא) וגם בשם האנגלי.
  const norm = (s) => (s || "").toLowerCase()
    .replace(/[֑-ׇ]/g, "").replace(/["'`׳״’‘“”]/g, "")
    .replace(/\s+/g, " ").trim();
  const qTokens = norm(searchTerm).split(" ").filter(Boolean);
  const matchQ = (...fields) => {
    if (!qTokens.length) return true;
    const hay = fields.map(norm).join(" ");
    return qTokens.every(t => hay.includes(t));
  };

  // בנה map: קטגוריה → פריטים
  const buildItems = (cat) => {
    const regularMovies = movies.filter(m =>
      !m.series_name &&
      matchQ(m.title, m.en_title, m.original_title) &&
      (cat === "הכל" || m.category === cat)
    );
    const seen = {};
    const seriesList = [];
    movies.forEach(m => {
      if (!m.series_name || seen[m.series_name]) return;
      const matchC = cat === "הכל" || m.category === cat;
      if (matchQ(m.series_name, m.title, m.en_title) && matchC) { seen[m.series_name] = true; seriesList.push(seriesMap[m.series_name]); }
    });
    return [...seriesList, ...regularMovies];
  };

  const liveItems = liveChannels.filter(ch => matchQ(ch.title, ch.name)).map(ch => ({ ...ch, is_live: true }));
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
    return (
      <div style={{ paddingTop: 8 }}>
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
    // תאריך לפי כל שדה זמין (תוכן מיובא נשמר עם added_at, לא created_date)
    const getT = (m) => {
      const v = m.created_date || m.added_at || m.created_at;
      const t = v ? new Date(v).getTime() : NaN;
      return isNaN(t) ? 0 : t;
    };
    const seen = {};
    const sorted = movies
      .map(m => ({ m, t: getT(m) }))
      .filter(x => x.t > 0)
      .sort((a, b) => b.t - a.t);
    const recent = [];
    for (const { m, t } of sorted) {
      const key = m.series_name || m.id;
      if (seen[key]) continue;
      seen[key] = true;
      recent.push({ m, fresh: now - t <= 3 * DAY_MS });   // "עלה עכשיו" = 3 ימים אחרונים
      if (recent.length >= 12) break;
    }
    // מעדיפים תוכן טרי (3 ימים); אם אין — מציגים בכל זאת את ה-8 החדשים ביותר
    const fresh = recent.filter(r => r.fresh).map(r => r.m);
    return (fresh.length ? fresh : recent.slice(0, 8).map(r => r.m)).slice(0, 12);
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
    <a
      href={buildCardHref(displayItem, isSer, false)}
      onClick={e => { e.preventDefault(); handleItemClick(displayItem, isSer); }}
      style={{
        position: "relative", margin: "6px 14px 16px", borderRadius: 16, overflow: "hidden",
        cursor: "pointer", height: 200, background: "#111",
        opacity: visible ? 1 : 0, transition: "opacity .35s ease",
        display: "block", textDecoration: "none", color: "inherit",
      }}
    >
      {movie.thumbnail_url && (
        <>
          {/* רקע מטושטש שממלא את הבאנר יפה גם לפוסטר אנכי */}
          <img src={movie.thumbnail_url} alt="" aria-hidden="true"
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", filter: "blur(20px) brightness(.45)", transform: "scale(1.15)" }} />
          {/* הפוסטר המלא — contain כדי לא לחתוך */}
          <img src={movie.thumbnail_url} alt={title}
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "contain" }} />
        </>
      )}
      <div style={{ position: "absolute", inset: 0, background: "linear-gradient(to top, rgba(0,0,0,.9), rgba(0,0,0,.05) 70%)" }} />
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
    </a>
  );
}

export { NetflixRows, RecentlyAddedBanner };
