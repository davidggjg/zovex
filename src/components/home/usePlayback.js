import { useState, useEffect } from "react";
import { Movie } from "@/entities/Movie";
import { lsSet, lsDel, lsJson } from "./helpers";

// ── הקידומת של הכתובות ─────────────────────────────────────────────────────
//
// כאן היה כתוב "/zovex/" קשיח, וזה מה שהפך כל קישור ישיר לעמוד לבן.
// ה-router מקבל basename מ-import.meta.env.BASE_URL, ועל השרת בונים עם
// ‎--base=/ — כלומר basename "/" והמסלולים הם "/:slug" ו-"/:slug/:episode".
// כתובת כמו /zovex/coraline/watch היא שלושה מקטעים, לא תואמת לשום מסלול,
// ולכן לא מצויר כלום.
//
// בזמן גלישה זה לא התגלה, כי replaceState רק כותב לשורת הכתובת ולא מנווט.
// זה נשבר בדיוק כשפותחים את הקישור מאפס — כלומר בשיתוף, שזה כל הטעם שלו.
//
// מ-BASE_URL: על השרת "/" ובדף GitHub Pages "/zovex/" — אותו קוד, ושתי
// הכתובות תמיד תואמות ל-basename שה-router באמת מקבל.
const BASE = import.meta.env.BASE_URL.endsWith("/")
  ? import.meta.env.BASE_URL
  : import.meta.env.BASE_URL + "/";

// פתיחת נגן הווידאו — כולל שמירת היסטוריה/המשך צפייה, עדכון ה-URL, ורענון קישורי Kaltura
export function usePlayback({ user, loadProgress, saveHistory }) {
  const [playerMovie, setPlayerMovie] = useState(() => lsJson("zovex_player"));
  const [resumeSeconds, setResumeSeconds] = useState(0);
  const [kalturaRefreshing, setKalturaRefreshing] = useState(false);

  // אם הנגן שוחזר מ-localStorage (למשל ריענון דף באמצע צפייה) — טען את המיקום השמור
  useEffect(() => {
    if (playerMovie && user) {
      loadProgress(playerMovie.id).then(pos => setResumeSeconds(pos || 0));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { playerMovie ? lsSet("zovex_player", JSON.stringify(playerMovie)) : lsDel("zovex_player"); }, [playerMovie]);

  const openWithKalturaRefresh = async (movie, resumeAt = null) => {
    // שמור להיסטוריה (רק למחוברים)
    saveHistory(movie.id, movie.title, movie.thumbnail_url);
    // המשך צפייה — לא מחכים כאן ל-loadProgress (קריאת רשת לשרת הבוט): זה מה
    // שהיה גורם לעיכוב לפני שהנגן בכלל נפתח ומתחיל לטעון את הסרטון. הנגן
    // נפתח מיד עם 0/resumeAt, ואם יש מיקום שמור הוא מתעדכן ברקע ומדלג
    // אליו (ראה האפקט על startTime ב-CustomVideoPlayer) ברגע שהתשובה מגיעה.
    // יוצא דופן: youtube/vimeo מטמיעים את מיקום ההתחלה בתוך ה-src של
    // ה-iframe עצמו (buildSrc), אז שם עדיין מחכים כדי לא לגרום לאייפריים
    // להיטען פעמיים (עם קפיצה גלויה) כשה-src משתנה אחרי שהתשובה מגיעה.
    const vidForType = movie.video_id || movie.video_url || "";
    const embedsStartInUrl = ["youtube", "vimeo"].includes(movie.type) || vidForType.includes("youtube.com") || vidForType.includes("youtu.be") || vidForType.includes("vimeo.com");
    if (resumeAt !== null) {
      setResumeSeconds(resumeAt);
    } else if (embedsStartInUrl) {
      setResumeSeconds((await loadProgress(movie.id)) || 0);
    } else {
      setResumeSeconds(0);
      loadProgress(movie.id).then(pos => { if (pos) setResumeSeconds(pos); });
    }
    // עדכן URL ישירות בלי לגרום ל-re-render של React Router
    // אם יש custom_slug (כתובת אנגלית קצרה) — נשתמש בו במקום השם בעברית
    if (movie.series_name && movie.episode_number) {
      const serSlug = movie.custom_slug ? movie.custom_slug : encodeURIComponent(movie.series_name.replace(/ /g, "-"));
      const seasonNum = movie.season_number || 1;
      const epSlug = movie.custom_slug
        ? `season-${seasonNum}-episode-${movie.episode_number}`
        : encodeURIComponent(`עונה-${seasonNum}-פרק-${movie.episode_number}`);
      window.history.replaceState(null, "", `${BASE}${serSlug}/${epSlug}`);
    } else if (movie.title && !movie.series_name) {
      const movieSlug = movie.custom_slug ? movie.custom_slug : (encodeURIComponent((movie.title || "").replace(/ /g, "-")) + "-" + movie.id.slice(0, 6));
      const watchPart = movie.custom_slug ? "watch" : "watch";
      window.history.replaceState(null, "", `${BASE}${movieSlug}/${watchPart}`);
    }
    const vid = movie.video_id || "";
    const isKaltura = movie.type === "kaltura" || vid.includes("kaltura");
    if (!isKaltura) { setPlayerMovie(movie); return; }
    setKalturaRefreshing(true);
    try { await Promise.race([Movie.update(movie.id, { ...movie, _refreshed: Date.now() }), new Promise((_, r) => setTimeout(() => r(), 9000))]); } catch {}
    setKalturaRefreshing(false); setPlayerMovie(movie);
  };

  return { playerMovie, setPlayerMovie, resumeSeconds, kalturaRefreshing, openWithKalturaRefresh };
}
