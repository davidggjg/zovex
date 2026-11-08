import { Home, Search, Heart, User as UserIcon } from "lucide-react";
import { colors, radius, glassFloating } from "@/theme/tokens";

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

export default function BottomNav({ active, onHome, onSearch, onFavorites, onUser, user }) {

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
      {/* החיפוש הוא דף משלו (SearchPage), ולא שכבה מעל דף הבית:
          שם יש מסננים, ספירת תוצאות, וכפתור "חזור" של הדפדפן שעובד. */}
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
        {item("search", Search, "חיפוש", onSearch)}
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
