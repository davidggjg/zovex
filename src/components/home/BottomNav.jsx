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
// אייקונים בלבד, בלי תוויות. התוויות הכריחו כל פריט להיות רחב כמו
// המילה שבו ("שידורים חיים"), והסרגל נמתח. אייקון מרובע נותן פריטים
// שווים וצרים, וזה מה שמחזיק את הקפסולה קטנה גם במסך רחב.
const ITEM = {
  display: "flex", alignItems: "center", justifyContent: "center",
  width: 46, height: 46, flexShrink: 0,
  borderRadius: 16, background: "none", border: "none",
  cursor: "pointer", fontFamily: "inherit", color: colors.textMuted,
  // §1: המשוב הוא על הלחיצה עצמה ולא על השחרור.
  transition: "transform 100ms ease-out, background 180ms ease",
};

export default function BottomNav({ active, onHome, onSearch, onFavorites, onUser, user }) {

  const item = (key, Icon, label, onClick) => {
    const on = active === key;
    return (
      <button onClick={onClick} aria-label={label} title={label}
        style={{ ...ITEM,
                 // הפריט הפעיל מסומן ברקע רך ולא בצבע מותג: הצבע
                 // החזק נשאר לתגים, והסרגל נשאר שקט.
                 background: on ? "rgba(255,255,255,0.12)" : "none" }}>
        <Icon size={21} color={on ? "#fff" : colors.textSecondary}
              strokeWidth={on ? 2.3 : 1.9} />
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
        marginInline: "auto", width: "max-content", maxWidth: "calc(100% - 28px)",
        display: "flex", alignItems: "center", gap: 2,
        // זכוכית אמיתית ולא משטח כהה: רקע שקוף, טשטוש חזק ורוויה
        // מוגברת, כך שהתוכן שעובר מתחת באמת נראה דרכו.
        ...glassFloating(34, 3),
        borderRadius: 999, padding: 5,
      }}>
        {item("home", Home, "בית", onHome)}
        {item("search", Search, "חיפוש", onSearch)}
        {item("fav", Heart, "מועדפים", onFavorites)}
        <button onClick={onUser} aria-label="שלי" title="שלי" style={ITEM}>
          {user?.picture
            ? <img src={user.picture} alt="" style={{ width: 24, height: 24, borderRadius: "50%" }} />
            : <UserIcon size={21} color={colors.textSecondary} strokeWidth={1.9} />}
        </button>
      </nav>
    </>
  );
}
