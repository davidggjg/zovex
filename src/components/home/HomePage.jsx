import { useState, useRef, useEffect } from "react";
import { Search, Send, Eye } from "lucide-react";
import { SPIN } from "./helpers";
import { NetflixRows, RecentlyAddedBanner } from "./ContentRows";

// מסך הבית — לוגו, חיפוש, תפריט משתמש, קטגוריות, ורשימות התוכן
export default function HomePage({
  user, onLogout, searchTerm, setSearchTerm, selectedCategory, setSelectedCategory,
  allCategories, refreshHistory, onLogoClick,
  movies, seriesMap, liveChannels, isDesktop, handleItemClick, handleContinueWatchingClick, history,
}) {
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef(null);

  // סגירת התפריט בלחיצה מחוץ לו
  useEffect(() => {
    if (!userMenuOpen) return;
    const onClickOutside = (e) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target)) setUserMenuOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [userMenuOpen]);

  return (
    <div style={{ background: "#0a0a0a", minHeight: "100vh", direction: "rtl", fontFamily: "Arial, sans-serif" }}>
      <style>{SPIN}</style>
      <header style={{ padding: "14px 14px 0", background: "#0a0a0a", borderBottom: "1px solid #1a1a1a" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
          <h1
            onClick={onLogoClick}
            style={{ color: "#e50914", fontSize: 26, fontWeight: 900, letterSpacing: 4, margin: 0, flexShrink: 0, cursor: "pointer" }}>ZOVEX</h1>
          <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 8, background: "rgba(255,255,255,0.06)", padding: "9px 14px", borderRadius: 50, border: "1px solid #333" }}>
            <Search size={16} color="#888" />
            <input type="text" placeholder="חפש סרט או סדרה..." value={searchTerm} onChange={e => setSearchTerm(e.target.value)} style={{ background: "none", border: "none", outline: "none", width: "100%", fontSize: 15, color: "#fff" }} />
            {searchTerm && <span onClick={() => setSearchTerm("")} style={{ cursor: "pointer", color: "#888", fontSize: 18 }}>×</span>}
          </div>
          {/* אזור משתמש */}
          <div ref={userMenuRef} style={{ position: "relative", flexShrink: 0 }}>
            {user ? (
              <img
                src={user.picture} alt={user.name}
                style={{ width: 34, height: 34, borderRadius: "50%", border: "2px solid #e50914", cursor: "pointer", display: "block" }}
                onClick={() => setUserMenuOpen(o => !o)}
                title={user.name}
                onError={e => e.target.style.display = "none"}
              />
            ) : (
              <div
                onClick={() => setUserMenuOpen(o => !o)}
                title="אורח"
                style={{
                  width: 34, height: 34, borderRadius: "50%",
                  background: "#1a1a1a", border: "2px solid #333",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 11, fontWeight: 700, color: "#ccc", cursor: "pointer"
                }}
              >
                אורח
              </div>
            )}

            {userMenuOpen && (
              <div style={{
                position: "absolute", top: 42, left: 0, background: "#1a1a1a",
                borderRadius: 12, boxShadow: "0 6px 24px rgba(0,0,0,.5)",
                border: "1px solid #333", minWidth: 170, overflow: "hidden", zIndex: 50
              }}>
                {user && (
                  <>
                    <div style={{ padding: "10px 14px", borderBottom: "1px solid #2a2a2a" }}>
                      <div style={{ fontSize: 13, fontWeight: 700, color: "#fff", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{user.name}</div>
                      <div style={{ fontSize: 11, color: "#888", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{user.email}</div>
                    </div>
                    <div
                      onClick={() => { setSelectedCategory("היסטוריה"); setUserMenuOpen(false); refreshHistory(); }}
                      style={{ padding: "11px 14px", fontSize: 13, color: "#e5e5e5", cursor: "pointer", fontWeight: 600 }}
                      onMouseEnter={e => e.currentTarget.style.background = "#262626"}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                    >
                      📋 היסטוריית צפייה
                    </div>
                  </>
                )}
                <div
                  onClick={() => { setUserMenuOpen(false); onLogout(); }}
                  style={{ padding: "11px 14px", fontSize: 13, color: "#e50914", cursor: "pointer", fontWeight: 700, borderTop: user ? "1px solid #2a2a2a" : "none" }}
                  onMouseEnter={e => e.currentTarget.style.background = "rgba(229,9,20,0.12)"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                >
                  {user ? "🚪 יציאה מהחשבון" : "🚪 יציאה ממצב אורח"}
                </div>
              </div>
            )}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", paddingBottom: 11 }}>
          {allCategories.map(cat => {
            const isLiveCat = cat === "שידורים חיים";
            return (
              <span key={cat} onClick={() => { setSelectedCategory(cat); if (cat === "היסטוריה") refreshHistory(); }} style={{ cursor: "pointer", fontSize: 13, fontWeight: 700, color: selectedCategory === cat ? "#fff" : (isLiveCat ? "#e50914" : "#ccc"), background: selectedCategory === cat ? "#e50914" : (isLiveCat ? "rgba(229,9,20,0.12)" : "#1a1a1a"), border: selectedCategory === cat ? "none" : (isLiveCat ? "1px solid #e50914" : "1px solid #333"), borderRadius: 50, padding: "6px 16px", flexShrink: 0, boxShadow: selectedCategory === cat ? "0 2px 10px rgba(229,9,20,.35)" : "none", display: "flex", alignItems: "center", gap: 5 }}>
                {isLiveCat && <Eye size={13} />}
                {cat}
              </span>
            );
          })}
        </div>
      </header>
      <main style={{ padding: "8px 0 100px", background: "#0a0a0a" }}>
        <RecentlyAddedBanner movies={movies} seriesMap={seriesMap} handleItemClick={handleItemClick} />
        <NetflixRows
          movies={movies}
          seriesMap={seriesMap}
          liveChannels={liveChannels}
          allCategories={allCategories}
          selectedCategory={selectedCategory}
          searchTerm={searchTerm}
          isDesktop={isDesktop}
          handleItemClick={handleItemClick}
          onContinueWatchingClick={handleContinueWatchingClick}
          history={history}
          user={user}
        />
      </main>
      {/* Telegram bubble */}
      <div style={{ position: "fixed", bottom: 24, left: 16, zIndex: 1000, display: "flex", alignItems: "flex-end", gap: 10 }}>
        <div style={{ background: "#1a1a1a", borderRadius: "16px 16px 16px 4px", padding: "10px 14px", boxShadow: "0 4px 18px rgba(0,0,0,.4)", border: "1px solid #333", maxWidth: 170, direction: "rtl" }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "#fff", marginBottom: 2 }}>רוצה להוסיף סרט? 🎬</div>
          <div style={{ fontSize: 11, color: "#999", lineHeight: 1.4 }}>יש בעיה באתר?<br/>דברו איתנו בטלגרם</div>
        </div>
        <a href="https://t.me/ZOVE8" target="_blank" rel="noreferrer" style={{ background: "#24A1DE", width: 50, height: 50, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", boxShadow: "0 4px 15px rgba(36,161,222,.5)", textDecoration: "none", flexShrink: 0 }}>
          <Send size={22} fill="white" />
        </a>
      </div>
    </div>
  );
}
