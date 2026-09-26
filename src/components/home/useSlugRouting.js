import { useEffect } from "react";

// מזהה איזה סרט/סדרה לפתוח לפי ה-slug שבכתובת (custom_slug, שם בעברית מקודד, או shortId)
export function useSlugRouting(movies, slug, episode, setSelectedSeries, setSelectedMovie, openWithKalturaRefresh) {
  useEffect(() => {
    if (!movies.length) return;
    // ‎/live/<ערוץ>‎ מטופל באפקט נפרד ב-Home.jsx, שפותח את **דף הערוץ**
    // עם לוח השידורים. בלי היציאה הזאת שני האפקטים רצים על אותה כתובת,
    // וזה מה שביטל את הלוח בפועל:
    //
    //   slug="live"  →  shortId="live"  →  movies.find(m => m.id.startsWith("live"))
    //
    // ל-25 ערוצים יש ‎id‎ שמתחיל ב-‎live_‎, ולכן שלב 4 תפס את הראשון
    // במערך — ערוץ **אחר** מזה שנלחץ — קרא ל-openWithKalturaRefresh
    // ופתח נגן לפני שהצופה ראה משהו. נמדד בדפדפן: ‎/live/Sport6‎ פתח
    // את "חי את הלילה", ואף בקשה ל-‎/epg/‎ לא נשלחה.
    if (slug === "live") return;
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
      //
      // ‎shortId‎ הוא **תמיד** שש תווים: כך נבנית הכתובת בצד השני —
      // ‎encodeURIComponent(title) + "-" + item.id.slice(0, 6)‎. בלי
      // אכיפת האורך ‎startsWith‎ מתאים לכל קידומת, וזה מה שקרה בפועל:
      //
      //   /live/Sport6  →  slug="live"  →  shortId="live"
      //   movies.find(m => m.id.startsWith("live"))
      //
      // לסרט "חי את הלילה" (Live by Night) יש ‎id = "live-by-night-…"‎,
      // ולכן לחיצה על **כל** ערוץ חי פתחה אותו. אורך שש הוא מה שמפריד
      // מזהה אמיתי ממילה שהזדמנה בסוף הכתובת.
      const parts = slug.split("-");
      const shortId = parts[parts.length - 1];
      const found = shortId.length >= 6
        ? movies.find(m => m.id.startsWith(shortId))
        : null;
      if (found) {
        setSelectedMovie(found);
        if (episode) openWithKalturaRefresh(found);
      }
    }
  }, [slug, episode, movies]);
}
