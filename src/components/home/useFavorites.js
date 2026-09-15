import React from "react";
import { apiCall } from "./helpers";

// ── מועדפים ──────────────────────────────────────────────────────────────────
// נשמרים בשרת ולא בדפדפן: מועדפים ב-localStorage נעלמים בניקוי היסטוריה ולא
// עוברים בין המחשב, הטלפון והאפליקציה. אותה נקודת קצה בדיוק שהאפליקציה
// משתמשת בה (/api/favorites עם x-user-id), כדי שהלב יהיה אותו לב בשני
// המקומות.
export function useFavorites(user) {
  // Set ולא מערך: הלב נבדק בכל ציור של כל כרטיס, וזו בדיקה בזמן קבוע.
  const [favIds, setFavIds] = React.useState(() => new Set());

  React.useEffect(() => {
    if (!user?.id) { setFavIds(new Set()); return; }
    let alive = true;
    apiCall("/api/favorites", "GET", null, user.id).then(list => {
      if (alive && Array.isArray(list)) {
        setFavIds(new Set(list.map(f => String(f.media_id))));
      }
    });
    return () => { alive = false; };
  }, [user?.id]);

  const isFavorite = React.useCallback(
    id => favIds.has(String(id)), [favIds]);

  // עדכון אופטימי: הלב מתמלא מיד ומתבטל רק אם השרת נכשל. בלי זה הלב נתקע
  // עד שהרשת עונה, וזה מרגיש שבור בחיבור איטי.
  const toggleFavorite = React.useCallback(async movie => {
    const uid = user?.id;
    if (!uid || !movie?.id) return;
    const id = String(movie.id);
    const had = favIds.has(id);
    const flip = add => setFavIds(prev => {
      const next = new Set(prev);
      if (add) next.add(id); else next.delete(id);
      return next;
    });
    flip(!had);
    const res = had
      ? await apiCall(`/api/favorites/${encodeURIComponent(id)}`, "DELETE", null, uid)
      : await apiCall("/api/favorites", "POST", {
          media_id: id,
          title: movie.title || "",
          thumbnail_url: movie.thumbnail_url || "",
        }, uid);
    if (!res) flip(had);      // החזרה למצב הקודם
  }, [favIds, user?.id]);

  return { favIds, isFavorite, toggleFavorite };
}

// ── טריילר ───────────────────────────────────────────────────────────────────
// מפתח יוטיוב מהשרת. null הוא תשובה תקינה ולא כשל: לחלק גדול מהקטלוג אין
// tmdb_id, ולתוכן ישראלי לרוב אין טריילר ב-TMDB.
export function useTrailer(movie) {
  const [key, setKey] = React.useState(null);
  React.useEffect(() => {
    setKey(null);
    if (!movie?.id || movie.is_live) return;
    let alive = true;
    fetch(`/content/trailer/${encodeURIComponent(String(movie.id))}`)
      .then(r => (r.ok ? r.json() : null))
      .then(j => { if (alive && j?.key) setKey(String(j.key)); })
      .catch(() => {});
    return () => { alive = false; };
  }, [movie?.id, movie?.is_live]);
  return key;
}
