import { useState, useEffect } from "react";
import { Movie } from "@/entities/Movie";

// ממזג רשימת שידורים חיים "טרייה" עם הגרסה הקודמת ב-state: אם לפריט מסוים
// חסר שדה (thumbnail_url/custom_slug) בגרסה הטרייה אבל היה קיים בגרסה
// הקודמת - שומרים את הישן. זה מונע מצב שבו raw.githubusercontent.com
// (שיש לו עיכוב הפצה משלו, בלתי-תלוי בקאש-באסטינג) מחזיר זמנית עותק
// ישן-יותר מ-movies.json ומוחק פוסטרים שכבר הוצגו נכון לרגע לפני כן.
function mergeLiveChannels(prev, fresh) {
  const prevById = new Map(prev.map(p => [p.id, p]));
  return fresh.map(f => {
    const p = prevById.get(f.id);
    if (!p) return f;
    const merged = { ...f };
    for (const key of ["thumbnail_url", "custom_slug"]) {
      if (!merged[key] && p[key]) merged[key] = p[key];
    }
    return merged;
  });
}

// טוען את מאגר הסרטים/סדרות + השידורים החיים, ומרענן שידורים חיים מ-GitHub
export function useMovieLibrary() {
  const [movies, setMovies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [liveChannels, setLiveChannels] = useState([]);

  // ── טעינת הקטלוג בשני שלבים ────────────────────────────────────────────
  //
  // נמדד מול השרת החי: דף הבית הוריד ‎/movies.json‎ — **2.6MB דחוס**,
  // 30MB לפני דחיסה, 26,006 פריטים — לפני שהופיע כרטיס אחד. הכרטיס
  // הראשון הגיע אחרי 10.2 שניות במחשב ו-11.2 בטלפון.
  //
  // ‎?t=<זמן>‎ בכתובת הפך כל טעינה להורדה מחדש: הדפדפן לא יכול לשמור
  // במטמון כתובת שמשתנה. בלעדיו השרת מחזיר 304 ריק, כי הוא כבר שולח
  // ETag ו-Cache-Control: no-cache ("שמור אבל אמת").
  //
  // והשרת כבר מגיש גרסה מהירה שהאתר לא השתמש בה:
  //
  //     /content/lite?limit=800   52KB     ← ציור ראשון
  //     /content/lite            1.86MB    ← הושלם ברקע
  //     /movies.json             2.6MB     ← מה שהיה
  //
  // הרשימה כבר מגיעה מהחדש לישן, ולכן 800 הראשונים הם 800 החדשים.
  //
  // ‎/content/lite‎ אינו כולל ‎description‎ (הוא נחסך בשרת) — התיאור
  // נמשך לפריט בודד דרך ‎/content/item/{id}‎ כשפותחים אותו.
  const CATALOG = "/content/lite";

  const fetchCatalog = async (limit) => {
    const res = await fetch(limit ? `${CATALOG}?limit=${limit}` : CATALOG);
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  };

  const apply = (arr) => {
    // reverse נשמר מההתנהגות הקודמת של Movie.list("-created_date"):
    // שינוי הסדר כאן היה משנה אילו פריטים מופיעים בכל שורה, וזה לא
    // מה שהשינוי הזה בא לעשות.
    const all = [...arr].reverse();
    setLiveChannels(prev => mergeLiveChannels(prev, all.filter(m => m.is_live === true)));
    setMovies(all.filter(m => !m.is_live));
  };

  const loadMovies = async () => {
    setLoading(true);
    try {
      apply(await fetchCatalog(800));   // ציור ראשון, 52KB
      setLoading(false);
      apply(await fetchCatalog(0));     // השלמה ברקע
    } catch {
      // נפילה חזרה למקור הישן: עדיף איטי מאשר ריק.
      try {
        const all = (await Movie.list("-created_date", 100000)) || [];
        setLiveChannels(prev => mergeLiveChannels(prev, all.filter(m => m.is_live === true)));
        setMovies(all.filter(m => !m.is_live));
      } catch {}
    }
    setLoading(false);
  };

  // קריאה מ-raw.githubusercontent.com — מתעדכן מיד אחרי שמירה בלי לחכות ל-build
  const loadLiveFromGitHub = async () => {
    try {
      // ‎/content/live‎ מחזיר רק את השידורים החיים — עשרות KB במקום
      // הקטלוג כולו. קודם זה משך את movies.json מגיטהאב בכל רענון,
      // כלומר מגה-בייטים כל חמש דקות לכל לשונית פתוחה, רק כדי לבדוק
      // אם ערוץ אחד השתנה.
      const res = await fetch("/content/live");
      if (!res.ok) return;
      const all = await res.json();
      const live = Array.isArray(all) ? all.filter(m => m.is_live === true) : [];
      if (live.length) setLiveChannels(prev => mergeLiveChannels(prev, live));
    } catch {}
  };

  useEffect(() => { loadMovies(); }, []);
  useEffect(() => {
    loadLiveFromGitHub();
    // אם אין שידורים חיים כרגע — בדוק פעם אחת בטעינה ועצור (אין טעם לפולינג מתמשך)
    if (liveChannels.length === 0) return;
    // יש שידור חי פעיל — בדוק כל כמה דקות אם יש שינויים.
    // תיקון: זה היה כל 30 שניות - אבל הקובץ הזה כבר מכיל את כל הקטלוג
    // (4MB+ ורק גדל), אז כל "בדיקה" כזו הורידה מחדש את כל הקובץ, לא רק
    // את השידורים החיים. על מכשיר/רשת ממוצעים זה יצר עומס רשת+CPU מתמיד
    // ברקע שהאט הכל, כולל נגינת וידאו לא קשורה בכלל (כמו שידור חי
    // מ-CDN חיצוני). 5 דקות מספיק מהיר בשביל לתפוס עדכון שידור חי בזמן
    // סביר, בלי להוריד את אותו קובץ ענק שוב ושוב כל חצי דקה.
    const interval = setInterval(loadLiveFromGitHub, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [liveChannels.length]);

  return { movies, loading, liveChannels, loadMovies };
}
