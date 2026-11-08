import { useEffect, useState } from "react";

// ─────────────────────────────────────────────────────────────────────────────
// משיכת התיאור לפריט בודד.
//
// ‎/content/lite‎ — שממנו נטען הקטלוג — אינו כולל ‎description‎ ו-‎cast‎:
// השרת חוסך אותם בכוונה, וזה חלק ממה שמקטין את הטעינה הראשונה מ-2.6MB
// ל-52KB. התיאור נחוץ רק במסך של פריט אחד, ולכן הוא נמשך שם ולא נגרר
// בקטלוג כולו.
//
// ‎/content/item/{id}‎ מוגש עם ‎Cache-Control: public, max-age=300‎, כך
// שחזרה לאותו פריט אינה פונה שוב לרשת.
//
// אם הפריט כבר נושא תיאור (מקור ישן, או פריט שנטען מ-/content המלא) —
// לא נשלחת בקשה בכלל.
// ─────────────────────────────────────────────────────────────────────────────
const cache = new Map();

export function useDescription(item) {
  const id = item?.id;
  const existing = item?.description;
  const [desc, setDesc] = useState(existing || (id ? cache.get(id) : "") || "");

  useEffect(() => {
    if (existing) { setDesc(existing); return; }
    if (!id) { setDesc(""); return; }
    if (cache.has(id)) { setDesc(cache.get(id)); return; }
    let alive = true;
    fetch(`/content/item/${encodeURIComponent(String(id))}`)
      .then(r => (r.ok ? r.json() : null))
      .then(d => {
        const t = (d && d.description) || "";
        cache.set(id, t);
        if (alive) setDesc(t);
      })
      .catch(() => {});   // אין תיאור — המסך פשוט לא מציג אותו
    return () => { alive = false; };
  }, [id, existing]);

  return desc;
}
