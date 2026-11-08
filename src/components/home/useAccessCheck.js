import { useEffect, useState } from "react";

// ─────────────────────────────────────────────────────────────────────────────
// בדיקת חסימה לפי כתובת מייל.
//
// נמדד: הנתיב ‎/api/access‎ לא היה קיים בשרת כלל (add_bans.py לא הוחל),
// **וגם אחרי שהוחל — אף לקוח לא שאל אותו.** לא האתר ולא האפליקציה.
// כלומר כפתור החסימה בפאנל כתב שורה לקובץ ושום דבר לא קרה: הנחסם
// המשיך לצפות כרגיל.
//
// החסימה חלה על מי שמחובר עם חשבון גוגל, לפי המייל — המזהה היחיד
// שזהה באתר ובאפליקציה. אורח אינו נחסם, וזו החלטה מודעת: בלי מייל
// אין את מי לחסום.
//
// כשל רשת אינו חוסם. השרת הוא מקור האמת, ואם לא הגיעה תשובה עדיף
// לתת גישה מאשר לנעול משתמש תקין בגלל שנייה של רשת.
// ─────────────────────────────────────────────────────────────────────────────
export function useAccessCheck(email) {
  const [blocked, setBlocked] = useState(null);   // null = עוד לא נבדק
  const [message, setMessage] = useState("");

  useEffect(() => {
    const e = (email || "").trim();
    if (!e) { setBlocked(false); setMessage(""); return; }
    let alive = true;
    fetch(`/api/access?email=${encodeURIComponent(e)}`)
      .then(r => (r.ok ? r.json() : null))
      .then(d => {
        if (!alive || !d) return;
        setBlocked(!!d.blocked);
        setMessage(d.message || "");
      })
      .catch(() => {});
    return () => { alive = false; };
  }, [email]);

  return { blocked: blocked === true, message };
}
