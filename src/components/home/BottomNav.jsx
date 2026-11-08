import { useEffect, useRef } from "react";
import { Home, Search, Heart, User as UserIcon, X } from "lucide-react";
import { colors, radius } from "@/theme/tokens";

// ─────────────────────────────────────────────────────────────────────────────
// סרגל ניווט תחתון, כמו באפליקציה.
//
// המפרט נלקח מ-zovex-android/src/screens/HomeScreen.js (bottomNav):
// קפסולת זכוכית צפה, לא רצועה מוצמדת לתחתית — ‎left/right: 14‎,
// ‎bottom: 56‎, רדיוס 34, ריפוד 6, גבול דק בצבע glassBorder.
//
// למה החיפוש ירד לכאן: בראש הדף הוא תפס שורה שלמה לצד הלוגו, בזמן
// שבטלפון האגודל מגיע לתחתית המסך. באפליקציה הוא ממילא שם, וזה חלק
// ממה שגרם לה להרגיש נכון יותר.
//
// החיפוש אינו עובר למסך אחר: הוא נפתח כשכבה מעל, מתמקד מיד, ומשתמש
// באותו ‎searchTerm‎ שכבר קיים — כך ששום דבר במורד הזרם לא משתנה.
// ─────────────────────────────────────────────────────────────────────────────
const ITEM = {
  display: "flex", flexDirection: "column", alignItems: "center",
  justifyContent: "center", gap: 3, flex: 1, padding: "7px 4px",
  borderRadius: radius.pill, background: "none", border: "none",
  cursor: "pointer", fontFamily: "inherit", color: colors.textMuted,
  minWidth: 0,
};
const LABEL = { fontSize: 11, fontWeight: 700, whiteSpace: "nowrap" };

export default function BottomNav({
  active, onHome, onFavorites, onUser, user,
  searchOpen, setSearchOpen, searchTerm, setSearchTerm,
}) {
  const inputRef = useRef(null);
  useEffect(() => {
    if (searchOpen) inputRef.current?.focus();
  }, [searchOpen]);

  const item = (key, Icon, label, onClick) => {
    const on = active === key;
    return (
      <button onClick={onClick} style={{ ...ITEM, color: on ? colors.text : colors.textMuted,
                                         background: on ? colors.glassActive : "none" }}>
        <Icon size={19} color={on ? colors.primaryHi : colors.textMuted} strokeWidth={on ? 2.4 : 2} />
        <span style={LABEL}>{label}</span>
      </button>
    );
  };

  return (
    <>
      {searchOpen && (
        <div dir="rtl" style={{
          position: "fixed", inset: 0, zIndex: 998, background: colors.scrim,
          backdropFilter: "blur(10px)", WebkitBackdropFilter: "blur(10px)",
          padding: "18px 14px", display: "flex", flexDirection: "column", gap: 12,
        }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 9,
            background: colors.glass, border: `1px solid ${colors.glassBorder}`,
            borderRadius: radius.pill, padding: "11px 15px",
          }}>
            <Search size={17} color={colors.textMuted} />
            <input ref={inputRef} type="text" value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="חפש סרט או סדרה…"
              style={{ background: "none", border: "none", outline: "none", width: "100%",
                       fontSize: 16, color: colors.text, fontFamily: "inherit" }} />
            <button onClick={() => { setSearchTerm(""); setSearchOpen(false); }}
              style={{ background: "none", border: "none", cursor: "pointer", padding: 0,
                       display: "flex" }}>
              <X size={19} color={colors.textMuted} />
            </button>
          </div>
          <div style={{ color: colors.textMuted, fontSize: 12.5, textAlign: "center" }}>
            {searchTerm ? "התוצאות מתעדכנות מאחור — סגור כדי לראות אותן"
                        : "הקלד כדי לחפש"}
          </div>
        </div>
      )}

      <nav style={{
        position: "fixed", left: 14, right: 14, bottom: 18, zIndex: 999,
        display: "flex", alignItems: "center", justifyContent: "space-around",
        background: colors.glass,
        backdropFilter: "blur(16px) saturate(150%)",
        WebkitBackdropFilter: "blur(16px) saturate(150%)",
        border: `1px solid ${colors.glassBorder}`,
        borderRadius: 34, padding: 6,
        boxShadow: "0 10px 30px rgba(0,0,0,0.55)",
      }}>
        {item("home", Home, "בית", onHome)}
        {item("search", Search, "חיפוש", () => setSearchOpen(true))}
        {item("fav", Heart, "מועדפים", onFavorites)}
        <button onClick={onUser} style={{ ...ITEM, color: colors.textMuted }}>
          {user?.picture
            ? <img src={user.picture} alt="" style={{ width: 19, height: 19, borderRadius: "50%" }} />
            : <UserIcon size={19} color={colors.textMuted} />}
          <span style={LABEL}>שלי</span>
        </button>
      </nav>
    </>
  );
}
