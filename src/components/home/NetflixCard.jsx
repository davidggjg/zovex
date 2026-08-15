import React from "react";
import { Eye } from "lucide-react";

// בונה את כתובת ה-URL האמיתית של הכרטיס — בדיוק אותו נוסחה כמו ב-handleItemClick
// ב-Home.jsx, כדי שיהיה קישור <a href> אמיתי וניתן-לסריקה, לא רק onClick.
// בלי href אמיתי, גוגל לא רואה שום קישור מדף הבית לדפי הסרטים/סדרות בכלל.
function buildCardHref(item, isSer, isLive) {
  if (isLive) {
    const slug = item.custom_slug || encodeURIComponent((item.title || item.name || "").replace(/ /g, "-"));
    return `/live/${slug}`;
  }
  if (isSer) {
    const slug = item.custom_slug || encodeURIComponent((item.name || "").replace(/ /g, "-"));
    return `/${slug}`;
  }
  const slug = item.custom_slug || (encodeURIComponent((item.title || "").replace(/ /g, "-")) + "-" + (item.id || "").slice(0, 6));
  return `/${slug}`;
}

// TMDB מגיש את אותה תמונה בכמה רוחבים, והקטלוג שמור כולו ב-w500 — 127KB
// לפוסטר. כרטיס הוא 130-170 פיקסלים, כלומר גם ב-DPR 2 מספיק w342, ובנייד
// w185 (~30KB). מסך מלא של 60 כרטיסים ירד מ-7.6MB ל-1.8MB, וזה בדיוק הזמן
// שבו רואים ריבועים ריקים. רק כתובות TMDB נוגעות — לכל השאר לא נוגעים.
function posterUrl(url, cardW) {
  if (!url || url.indexOf("image.tmdb.org") < 0) return url;
  const want = cardW <= 150 ? "w185" : "w342";
  return url.replace(/\/t\/p\/w\d+\//, `/t/p/${want}/`);
}

function NetflixCard({ item, isSer, isLive, onClick, cardW, cardH }) {
  const title = isSer ? item.name : item.title;
  const href = buildCardHref(item, isSer, isLive);
  const poster = posterUrl(item.thumbnail_url, cardW);
  return (
    <a
      href={href}
      onClick={e => { e.preventDefault(); onClick(item, isSer); }}
      style={{ flexShrink: 0, width: cardW, cursor: "pointer", direction: "rtl", textDecoration: "none", color: "inherit", display: "block" }}
    >
      <div style={{ width: cardW, height: cardH, borderRadius: 12, overflow: "hidden", background: isLive ? "#1a1a1a" : "#1c1c1e", position: "relative", border: isLive ? "2px solid #e50914" : "none", transition: "transform .18s", boxShadow: "0 2px 8px rgba(0,0,0,.4)" }}
        onMouseEnter={e => { e.currentTarget.style.transform = "scale(1.04)"; e.currentTarget.style.boxShadow = "0 8px 24px rgba(0,0,0,.18)"; }}
        onMouseLeave={e => { e.currentTarget.style.transform = "scale(1)"; e.currentTarget.style.boxShadow = "0 2px 8px rgba(0,0,0,.10)"; }}>
        {isLive && poster ? (
          <img src={poster} alt={title} loading="lazy" decoding="async" style={{ width: "100%", height: "100%", objectFit: "contain", padding: 10, boxSizing: "border-box", display: "block" }} onError={e => e.target.style.display = "none"} />
        ) : isLive ? (
          <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8, background: "linear-gradient(135deg,#1a1a1a,#2a0a0c)" }}>
            <Eye size={30} color="#e50914" strokeWidth={2} />
            <span style={{ fontSize: 10, color: "#fff", fontWeight: 700, textAlign: "center", padding: "0 8px" }}>שידור חי</span>
          </div>
        ) : poster ? (
          <img src={poster} alt={title} loading="lazy" decoding="async" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} onError={e => e.target.style.display = "none"} />
        ) : (
          <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 28, background: "#1c1c1e", color: "#666" }}>🎬</div>
        )}
        {isSer && !isLive && <div style={{ position: "absolute", top: 7, right: 7, background: "rgba(0,0,0,.65)", borderRadius: 7, padding: "2px 7px", fontSize: 9, color: "#fff", fontWeight: 700 }}>סדרה</div>}
        {isLive && (
          <div style={{ position: "absolute", top: 7, right: 7, background: "#e50914", borderRadius: 7, padding: "2px 7px", fontSize: 9, color: "#fff", fontWeight: 900, display: "flex", alignItems: "center", gap: 3 }}>
            <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#fff", display: "inline-block", animation: "livePulseDot 1.5s ease-in-out infinite" }} />
            LIVE
          </div>
        )}
      </div>
      <div style={{ fontSize: 12, fontWeight: 700, marginTop: 6, color: "#f2f2f2", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", textAlign: "right", padding: "0 2px" }}>{title}</div>
    </a>
  );
}

// כמה כרטיסים נטענים ל-DOM בהתחלה בכל שורה, ומספר שמתווסף בכל "טעינה נוספת".
// בלי זה, שורה עם מאות פריטים (למשל קטגוריה שלמה) יוצרת מיד מאות תגי <img>
// בפעם אחת - כבד בטעינה ראשונית גם עם loading="lazy", כי הדפדפן עדיין בונה
// את כל האלמנטים מראש. במקום זה טוענים דף ראשון קטן ומרחיבים כשמתקרבים לסוף.
const ROW_PAGE_SIZE = 20;

function NetflixRow({ title, items, isDesktop, handleItemClick, isLiveRow }) {
  const rowRef = React.useRef(null);
  const cardW = isDesktop ? 170 : 130;
  const cardH = isDesktop ? 240 : 185;
  const [visibleCount, setVisibleCount] = React.useState(ROW_PAGE_SIZE);

  // הרשימה עצמה משתנה (חיפוש/קטגוריה) - איפוס לדף הראשון בכל פעם שהתוכן משתנה
  React.useEffect(() => { setVisibleCount(ROW_PAGE_SIZE); }, [items]);

  const scroll = (dir) => {
    if (!rowRef.current) return;
    const amount = cardW * 3 + 24;
    rowRef.current.scrollBy({ left: dir === "right" ? -amount : amount, behavior: "smooth" });
  };

  // השורה מוצגת ב-direction: ltr (למטה) בלי קשר לכיווניות שאר האתר, אז
  // "הקצה הרחוק" יכול להיות תחילת הגלילה או סופה בהתאם לדפדפן - בודקים את
  // שני הקצוות במקום להניח כיוון ספציפי.
  const handleScroll = () => {
    const el = rowRef.current;
    if (!el || visibleCount >= items.length) return;
    const nearEnd = el.scrollWidth - el.clientWidth - el.scrollLeft < cardW * 6;
    const nearStart = el.scrollLeft < cardW * 6;
    if (nearEnd || nearStart) setVisibleCount(v => Math.min(v + ROW_PAGE_SIZE, items.length));
  };

  if (!items || items.length === 0) return null;
  const visibleItems = items.slice(0, visibleCount);

  return (
    <div style={{ marginBottom: isDesktop ? 36 : 28, direction: "rtl" }}>
      {/* כותרת שורה */}
      <div style={{ padding: "0 16px", marginBottom: 12, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {isLiveRow && <Eye size={16} color="#e50914" />}
          <h2 style={{ fontSize: isDesktop ? 18 : 16, fontWeight: 900, color: "#fff", margin: 0 }}>{title}</h2>
          <span style={{ fontSize: 12, color: "#888" }}>({items.length})</span>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button onClick={() => scroll("right")} style={{ background: "#1a1a1a", border: "1px solid #333", color: "#fff", borderRadius: "50%", width: 30, height: 30, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14 }}>›</button>
          <button onClick={() => scroll("left")} style={{ background: "#1a1a1a", border: "1px solid #333", color: "#fff", borderRadius: "50%", width: 30, height: 30, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14 }}>‹</button>
        </div>
      </div>
      {/* הcarousel */}
      <div ref={rowRef} onScroll={handleScroll} style={{ display: "flex", gap: 10, overflowX: "auto", scrollbarWidth: "none", msOverflowStyle: "none", padding: "4px 16px 8px", direction: "ltr" }}>
        {visibleItems.map((item) => {
          const isSer = !!item.episodes;
          const isLive = !!item.is_live;
          return (
            <NetflixCard
              key={isSer ? "s-" + item.name : item.id}
              item={item}
              isSer={isSer}
              isLive={isLive}
              onClick={handleItemClick}
              cardW={cardW}
              cardH={cardH}
            />
          );
        })}
      </div>
    </div>
  );
}



// ── רשת (grid) ──────────────────────────────────────────────────────────────
// כשבוחרים קטגוריה ספציפית או מחפשים, גלגלת אופקית אחת עם מאות פריטים היא
// תצוגה גרועה: רואים ארבעה פריטים וצריך לגרור. האפליקציה מציגה במצב הזה רשת,
// וזה מה שנעשה כאן — אותו כלל בדיוק (ראה isNetflixMode ב-HomeScreen).
const GRID_PAGE_SIZE = 60;

function NetflixGrid({ title, items, isDesktop, handleItemClick, isLiveRow }) {
  const [visibleCount, setVisibleCount] = React.useState(GRID_PAGE_SIZE);
  const sentinelRef = React.useRef(null);

  React.useEffect(() => { setVisibleCount(GRID_PAGE_SIZE); }, [items]);

  // גלילה אינסופית: טוענים עוד כשמגיעים לתחתית, כדי לא לרנדר מאות כרטיסים בבת אחת
  React.useEffect(() => {
    const el = sentinelRef.current;
    if (!el || visibleCount >= items.length) return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some(e => e.isIntersecting)) {
        setVisibleCount(v => Math.min(v + GRID_PAGE_SIZE, items.length));
      }
    }, { rootMargin: "600px" });
    io.observe(el);
    return () => io.disconnect();
  }, [visibleCount, items.length]);

  if (!items || items.length === 0) return null;
  const cardW = isDesktop ? 170 : 130;
  const cardH = isDesktop ? 240 : 185;

  return (
    <div style={{ marginBottom: isDesktop ? 36 : 28, direction: "rtl" }}>
      <div style={{ padding: "0 16px", marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
        {isLiveRow && <Eye size={16} color="#e50914" />}
        <h2 style={{ fontSize: isDesktop ? 18 : 16, fontWeight: 900, color: "#fff", margin: 0 }}>{title}</h2>
        <span style={{ fontSize: 12, color: "#888" }}>({items.length})</span>
      </div>
      <div style={{
        display: "grid",
        gridTemplateColumns: `repeat(auto-fill, minmax(${cardW}px, 1fr))`,
        gap: 10,
        padding: "4px 16px 8px",
        justifyItems: "center",
      }}>
        {items.slice(0, visibleCount).map((item) => {
          const isSer = !!item.episodes;
          return (
            <NetflixCard
              key={isSer ? "s-" + item.name : item.id}
              item={item}
              isSer={isSer}
              isLive={!!item.is_live}
              onClick={handleItemClick}
              cardW={cardW}
              cardH={cardH}
            />
          );
        })}
      </div>
      <div ref={sentinelRef} style={{ height: 1 }} />
    </div>
  );
}

export { NetflixCard, NetflixRow, NetflixGrid, buildCardHref };
