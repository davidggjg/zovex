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

  const loadMovies = async () => {
    setLoading(true);
    // apply רץ פעמיים: פעם על המנה הראשונה (ציור מיידי) ופעם על הקטלוג המלא
    // כשהוא מגיע ברקע. בלי זה המסך היה ממתין ~4 שניות פרסור לפני שהוא מצייר.
    const apply = (all) => {
      setLiveChannels(prev => mergeLiveChannels(prev, all.filter(m => m.is_live === true)));
      setMovies(all.filter(m => !m.is_live));
    };
    try {
      const first = (await Movie.list("-created_date", 100000, apply)) || [];
      apply(first);
    } catch {}
    setLoading(false);
  };

  // רענון שידורים חיים. /content/live מחזיר רק את הערוצים (עשרות KB) במקום
  // את כל הקטלוג. הגרסה הקודמת משכה את movies.json המלא מגיטהאב עם
  // cache-buster — כלומר הורדה שלמה בכל טעינה ועוד אחת כל 5 דקות, וגם זה
  // כבר החזיר 404 כי הקובץ לא קיים שם יותר. בלי `?t=`: ה-ETag של השרת נותן
  // 304 ריק כשאין שינוי, וזה מהיר יותר מכל cache-buster.
  const LIVE_FALLBACK = import.meta.env.VITE_CONTENT_URL || "";
  const loadLiveChannels = async () => {
    for (const url of ["/content/live", LIVE_FALLBACK].filter(Boolean)) {
      try {
        const res = await fetch(url);
        if (!res.ok) continue;
        const all = await res.json();
        if (!Array.isArray(all)) continue;
        setLiveChannels(prev => mergeLiveChannels(prev, all.filter(m => m.is_live === true)));
        return;
      } catch {}
    }
  };

  useEffect(() => { loadMovies(); }, []);

  // רענון אוטומטי כשחוזרים לטאב (כמו באפליקציה) — כדי שתוכן חדש שהועלה יופיע
  // בלי צורך לרענן ידנית. מוגבל לפעם בדקה כדי לא להוריד את קובץ התוכן הגדול שוב ושוב.
  useEffect(() => {
    let last = Date.now();
    const refresh = () => {
      if (document.visibilityState && document.visibilityState !== "visible") return;
      if (Date.now() - last < 60000) return;
      last = Date.now();
      loadMovies();
    };
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener("focus", refresh);
    return () => {
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener("focus", refresh);
    };
  }, []);
  useEffect(() => {
    loadLiveChannels();
    // אם אין שידורים חיים כרגע — בדוק פעם אחת בטעינה ועצור (אין טעם לפולינג מתמשך)
    if (liveChannels.length === 0) return;
    // יש שידור חי פעיל — בדוק כל כמה דקות אם יש שינויים.
    // תיקון: זה היה כל 30 שניות - אבל הקובץ הזה כבר מכיל את כל הקטלוג
    // (4MB+ ורק גדל), אז כל "בדיקה" כזו הורידה מחדש את כל הקובץ, לא רק
    // את השידורים החיים. על מכשיר/רשת ממוצעים זה יצר עומס רשת+CPU מתמיד
    // ברקע שהאט הכל, כולל נגינת וידאו לא קשורה בכלל (כמו שידור חי
    // מ-CDN חיצוני). 5 דקות מספיק מהיר בשביל לתפוס עדכון שידור חי בזמן
    // סביר, בלי להוריד את אותו קובץ ענק שוב ושוב כל חצי דקה.
    const interval = setInterval(loadLiveChannels, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [liveChannels.length]);

  return { movies, loading, liveChannels, loadMovies };
}
