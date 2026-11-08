import { useEffect, useRef } from "react";
import { Home, Search, Heart, User as UserIcon, X } from "lucide-react";
import { colors, radius, glass, glassFloating } from "@/theme/tokens";

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
  // §1: המשוב הוא על הלחיצה עצמה ולא על השחרור.
  transition: "transform 100ms ease-out, background 160ms ease",
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
      {/* ── שורת חיפוש, לא מסך חיפוש ──────────────────────────────────
          מה שהיה: שכבה שמכסה את כל המסך, ומתחתיה הכיתוב "התוצאות
          מתעדכנות מאחור — סגור כדי לראות אותן". כלומר המשתמש הקליד
          וראה מסך ריק. זו הייתה רגרסיה שלי.

          מה שיש: רק השורה עצמה צפה למעלה, והתוצאות מתחתיה — אותו
          מסך, מסונן תוך כדי הקלדה. §12 של הסקיל: שכבה צפה שהתוכן
          גולל מתחתיה, לא פס שבולע את המסך. ואין scrim, כי זו אינה
          משימה חוסמת. */}
      {searchOpen && (
        <div dir="rtl" style={{
          position: "fixed", top: 0, left: 0, right: 0, zIndex: 998,
          marginInline: "auto", width: "calc(100% - 28px)", maxWidth: 560,
          marginTop: 12,
        }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 9,
            ...glassFloating("chrome", 3), borderRadius: radius.pill,
            padding: "11px 15px",
          }}>
            <Search size={17} color={colors.textMuted} />
            <input ref={inputRef} type="text" value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="חפש סרט או סדרה…"
              style={{ background: "none", border: "none", outline: "none", width: "100%",
                       fontSize: 16, color: colors.text, fontFamily: "inherit" }} />
            {!!searchTerm && (
              <button onClick={() => setSearchTerm("")}
                style={{ background: "none", border: "none", cursor: "pointer",
                         padding: 0, display: "flex", color: colors.textMuted,
                         fontSize: 18, lineHeight: 1 }}>×</button>
            )}
            <button onClick={() => setSearchOpen(false)}
              style={{ background: "none", border: "none", cursor: "pointer", padding: 0,
                       display: "flex" }}>
              <X size={19} color={colors.textMuted} />
            </button>
          </div>
        </div>
      )}

      <nav style={{
        // רוחב מוגבל וממורכז. ‎left/right: 14‎ לבדם מתחו את הקפסולה
        // על כל רוחב המסך במחשב, וארבעה פריטים נפרשו מקצה לקצה —
        // באפליקציה זה נראה נכון כי מסך טלפון רחב 400 נקודות.
        position: "fixed", left: 0, right: 0, bottom: 18, zIndex: 999,
        marginInline: "auto", width: "calc(100% - 28px)", maxWidth: 440,
        display: "flex", alignItems: "center", justifyContent: "space-around",
        // זכוכית אמיתית ולא משטח כהה: רקע שקוף, טשטוש חזק ורוויה
        // מוגברת, כך שהתוכן שעובר מתחת באמת נראה דרכו.
        ...glassFloating(34, 3),
        borderRadius: 34, padding: 6,
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
