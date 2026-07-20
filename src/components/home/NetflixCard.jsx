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

function NetflixCard({ item, isSer, isLive, onClick, cardW, cardH }) {
  const title = isSer ? item.name : item.title;
  const href = buildCardHref(item, isSer, isLive);
  return (
    <a
      href={href}
      onClick={e => { e.preventDefault(); onClick(item, isSer); }}
      style={{ flexShrink: 0, width: cardW, cursor: "pointer", direction: "rtl", textDecoration: "none", color: "inherit", display: "block" }}
    >
      <div style={{ width: cardW, height: cardH, borderRadius: 12, overflow: "hidden", background: isLive ? "#1a1a1a" : "#1c1c1e", position: "relative", border: isLive ? "2px solid #e50914" : "none", transition: "transform .18s", boxShadow: "0 2px 8px rgba(0,0,0,.4)" }}
        onMouseEnter={e => { e.currentTarget.style.transform = "scale(1.04)"; e.currentTarget.style.boxShadow = "0 8px 24px rgba(0,0,0,.18)"; }}
        onMouseLeave={e => { e.currentTarget.style.transform = "scale(1)"; e.currentTarget.style.boxShadow = "0 2px 8px rgba(0,0,0,.10)"; }}>
        {isLive && item.thumbnail_url ? (
          <img src={item.thumbnail_url} alt={title} loading="lazy" decoding="async" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} onError={e => e.target.style.display = "none"} />
        ) : isLive ? (
          <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8, background: "linear-gradient(135deg,#1a1a1a,#2a0a0c)" }}>
            <Eye size={30} color="#e50914" strokeWidth={2} />
            <span style={{ fontSize: 10, color: "#fff", fontWeight: 700, textAlign: "center", padding: "0 8px" }}>שידור חי</span>
          </div>
        ) : item.thumbnail_url ? (
          <img src={item.thumbnail_url} alt={title} loading="lazy" decoding="async" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} onError={e => e.target.style.display = "none"} />
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


export { NetflixCard, NetflixRow, buildCardHref };
