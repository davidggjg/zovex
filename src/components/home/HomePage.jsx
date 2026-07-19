import { useState, useRef, useEffect } from "react";
import { Search, Send, Eye, ChevronDown, X } from "lucide-react";
import { SPIN, ls, lsSet } from "./helpers";
import { NetflixRows, RecentlyAddedBanner } from "./ContentRows";

// מסך הבית — לוגו, חיפוש, תפריט משתמש, קטגוריות, ורשימות התוכן
export default function HomePage({
  user, onLogout, searchTerm, setSearchTerm, selectedCategory, setSelectedCategory,
  allCategories, refreshHistory, onLogoClick,
  movies, seriesMap, liveChannels, isDesktop, handleItemClick, handleContinueWatchingClick, history,
}) {
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [showCatModal, setShowCatModal] = useState(false);
  const [showTelegramTip, setShowTelegramTip] = useState(() => !ls("zovex_hide_telegram_tip"));
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
        <div style={{ paddingBottom: 11 }}>
          <button
            onClick={() => setShowCatModal(true)}
            style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, width: "100%", background: "#1a1a1a", border: "1px solid #333", borderRadius: 14, padding: "13px 16px", cursor: "pointer", fontFamily: "inherit" }}
          >
            <span style={{ fontSize: 14, fontWeight: 800, color: "#fff", display: "flex", alignItems: "center", gap: 6 }}>
              {selectedCategory === "שידורים חיים" && <Eye size={14} color="#e50914" />}
              קטגוריות: {selectedCategory}
            </span>
            <ChevronDown size={20} color="#e50914" />
          </button>
        </div>
      </header>

      {/* תפריט קטגוריות במסך מלא — נפתח מהכפתור למעלה */}
      {showCatModal && (
        <div
          onClick={() => setShowCatModal(false)}
          style={{ position: "fixed", inset: 0, zIndex: 300, background: "rgba(0,0,0,0.92)", display: "flex", flexDirection: "column", alignItems: "center", overflowY: "auto", padding: "60px 20px 130px" }}
        >
          {allCategories.map(cat => {
            const isActive = cat === selectedCategory;
            const isLiveCat = cat === "שידורים חיים";
            return (
              <div
                key={cat}
                onClick={(e) => { e.stopPropagation(); setSelectedCategory(cat); if (cat === "היסטוריה") refreshHistory(); setShowCatModal(false); }}
                style={{ padding: "14px 20px", width: "100%", maxWidth: 480, textAlign: "center", cursor: "pointer", fontSize: isActive ? 26 : 21, fontWeight: isActive ? 900 : 400, color: isActive ? "#fff" : (isLiveCat ? "#e50914" : "rgba(255,255,255,0.45)"), display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}
              >
                {isLiveCat && <Eye size={isActive ? 22 : 18} />}
                {cat}
              </div>
            );
          })}
          <button
            onClick={() => setShowCatModal(false)}
            style={{ position: "fixed", bottom: 36, left: "50%", transform: "translateX(-50%)", width: 58, height: 58, borderRadius: 29, background: "#fff", border: "none", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", boxShadow: "0 4px 18px rgba(0,0,0,.5)" }}
          >
            <X size={24} color="#000" />
          </button>
        </div>
      )}
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
      <div style={{ position: "fixed", bottom: 20, left: 14, zIndex: 1000, display: "flex", alignItems: "flex-end", gap: 8 }}>
        {showTelegramTip && (
          <div style={{ position: "relative", background: "rgba(26,26,26,0.92)", backdropFilter: "blur(6px)", borderRadius: "14px 14px 14px 4px", padding: "8px 24px 8px 10px", boxShadow: "0 2px 10px rgba(0,0,0,.3)", border: "1px solid #2a2a2a", maxWidth: 150, direction: "rtl" }}>
            <button
              onClick={() => { setShowTelegramTip(false); lsSet("zovex_hide_telegram_tip", "1"); }}
              style={{ position: "absolute", top: 2, left: 2, background: "none", border: "none", color: "#777", cursor: "pointer", padding: 4, display: "flex" }}
              aria-label="סגור"
            >
              <X size={12} />
            </button>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#eee", marginBottom: 1 }}>לחצו כאן לתמיכה 💬</div>
            <div style={{ fontSize: 10, color: "#888", lineHeight: 1.3 }}>או להוספת סרט חדש</div>
          </div>
        )}
        <a href="https://t.me/ZOVE8" target="_blank" rel="noreferrer" style={{ background: "#229ED9", height: 42, padding: "0 14px", borderRadius: 21, display: "flex", alignItems: "center", justifyContent: "center", gap: 6, color: "#fff", boxShadow: "0 2px 10px rgba(34,158,217,.35)", textDecoration: "none", flexShrink: 0, whiteSpace: "nowrap" }}>
          <Send size={16} fill="white" />
          <span style={{ fontSize: 12, fontWeight: 700 }}>תמיכה</span>
        </a>
      </div>
    </div>
  );
}
