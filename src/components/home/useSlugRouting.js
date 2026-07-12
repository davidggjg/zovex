import { useEffect } from "react";

// מזהה איזה סרט/סדרה לפתוח לפי ה-slug שבכתובת (custom_slug, שם בעברית מקודד, או shortId)
export function useSlugRouting(movies, slug, episode, setSelectedSeries, setSelectedMovie, openWithKalturaRefresh) {
  useEffect(() => {
    if (!movies.length) return;
    if (slug) {
      // שלב 1: בדוק אם ה-slug תואם custom_slug (כתובת אנגלית קצרה) — לסדרה
      const bySlugSeries = movies.find(m => m.series_name && m.custom_slug === slug);
      if (bySlugSeries) {
        setSelectedSeries(bySlugSeries.series_name);
        if (episode) {
          // תמיכה בפורמט: season-2-episode-5 או episode-5 (עונה 1 כברירת מחדל)
          const seasonMatch = episode.match(/season[^0-9]*(\d+)/i);
          const epMatch = episode.match(/episode[^0-9]*(\d+)/i) || episode.match(/(\d+)$/);
          const seasonNum = seasonMatch ? parseInt(seasonMatch[1]) : 1;
          const epNum = epMatch ? parseInt(epMatch[1]) : 1;
          const ep = movies.find(m =>
            m.series_name === bySlugSeries.series_name &&
            (m.season_number || 1) === seasonNum &&
            (m.episode_number === epNum || String(m.episode_number) === String(epNum))
          );
          if (ep) openWithKalturaRefresh(ep);
        }
        return;
      }
      // שלב 2: בדוק אם ה-slug תואם custom_slug — לסרט
      const bySlugMovie = movies.find(m => !m.series_name && m.custom_slug === slug);
      if (bySlugMovie) {
        setSelectedMovie(bySlugMovie);
        if (episode) openWithKalturaRefresh(bySlugMovie);
        return;
      }
      // שלב 3: fallback - שם בעברית מקודד (כתובת ישנה)
      const decoded = decodeURIComponent(slug).replace(/-/g, " ");
      if (movies.some(m => m.series_name === decoded)) {
        setSelectedSeries(decoded);
        if (episode) {
          const epDecoded = decodeURIComponent(episode).replace(/-/g, " ");
          const seasonMatch = epDecoded.match(/עונה[^0-9]*(\d+)/);
          const epMatch = epDecoded.match(/פרק[^0-9]*(\d+)/) || epDecoded.match(/(\d+)$/);
          const seasonNum = seasonMatch ? parseInt(seasonMatch[1]) : 1;
          const epNum = epMatch ? parseInt(epMatch[1]) : 1;
          const ep = movies.find(m =>
            m.series_name === decoded &&
            (m.season_number || 1) === seasonNum &&
            (m.episode_number === epNum || String(m.episode_number) === String(epNum))
          );
          if (ep) openWithKalturaRefresh(ep);
        }
        return;
      }
      // שלב 4: בדוק אם זה סרט לפי shortId (כתובת ישנה)
      const parts = slug.split("-");
      const shortId = parts[parts.length - 1];
      const found = movies.find(m => m.id.startsWith(shortId));
      if (found) {
        setSelectedMovie(found);
        if (episode) openWithKalturaRefresh(found);
      }
    }
  }, [slug, episode, movies]);
}
