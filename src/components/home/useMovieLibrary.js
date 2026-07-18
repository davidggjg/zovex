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
    try {
      const all = (await Movie.list("-created_date", 100000)) || [];
      setLiveChannels(prev => mergeLiveChannels(prev, all.filter(m => m.is_live === true)));
      setMovies(all.filter(m => !m.is_live));
    } catch {}
    setLoading(false);
  };

  // קריאה מ-raw.githubusercontent.com — מתעדכן מיד אחרי שמירה בלי לחכות ל-build
  const loadLiveFromGitHub = async () => {
    try {
      const res = await fetch(`https://raw.githubusercontent.com/davidggjg/zovex/main/public/movies.json?t=` + Date.now());
      if (!res.ok) return;
      const all = await res.json();
      setLiveChannels(prev => mergeLiveChannels(prev, all.filter(m => m.is_live === true)));
    } catch {}
  };

  useEffect(() => { loadMovies(); }, []);
  useEffect(() => {
    loadLiveFromGitHub();
    // אם אין שידורים חיים כרגע — בדוק פעם אחת בטעינה ועצור (אין טעם לפולינג מתמשך)
    if (liveChannels.length === 0) return;
    // יש שידור חי פעיל — בדוק כל 30 שניות אם יש שינויים
    const interval = setInterval(loadLiveFromGitHub, 30000);
    return () => clearInterval(interval);
  }, [liveChannels.length]);

  return { movies, loading, liveChannels, loadMovies };
}
