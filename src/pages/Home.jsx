import { useState, useEffect, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import CustomVideoPlayer from "@/components/home/CustomVideoPlayer.jsx";
import AdminPanel from "@/components/AdminPanel.jsx";
import MovieDetail from "@/components/MovieDetail.jsx";
import SeriesView from "@/components/SeriesView.jsx";
import { useGoogleAuth, LandingScreen } from "@/components/home/Auth.jsx";
import HomePage from "@/components/home/HomePage.jsx";
import AdminLoginScreen from "@/components/home/AdminLoginScreen.jsx";
import DonationModalView from "@/components/home/DonationModalView.jsx";
import { useWatchHistory } from "@/components/home/useWatchHistory";
import { useApiKeyEndpoint } from "@/components/home/useApiKeyEndpoint";
import { useSlugRouting } from "@/components/home/useSlugRouting";
import { usePlayback } from "@/components/home/usePlayback";
import { useMovieLibrary } from "@/components/home/useMovieLibrary";
import { useCategories } from "@/components/home/useCategories";
import { useIsDesktop } from "@/components/home/useIsDesktop";
import { ls, lsSet, lsDel, lsJson, SPIN } from "@/components/home/helpers";

const SECRET_TRIGGER = "ZovexAdmin2026";

export default function Home() {
  const { user, skipped, loginWithGoogle, logout, skip } = useGoogleAuth();

  // מסך כניסה — הצג אם לא מחובר ולא דילג
  if (!user && !skipped) {
    return <LandingScreen onLogin={loginWithGoogle} onSkip={skip} />;
  }
  return <HomeMain user={user} onLogout={logout} isGuest={!user && skipped} />;
}

function HomeMain({ user, onLogout, isGuest }) {
  const { slug, episode } = useParams();
  const navigate = useNavigate();

  const { history, saveProgress, loadProgress, saveHistory, refreshHistory } = useWatchHistory(user);

  // ── API endpoint: /zovex/api?key=XXX ──
  const apiMode = slug === "api";
  const apiResult = useApiKeyEndpoint(slug);
  if (apiMode) {
    return (
      <pre style={{ direction: "ltr", fontFamily: "monospace", padding: 20, whiteSpace: "pre-wrap", wordBreak: "break-all", margin: 0 }}>
        {apiResult === null ? "" : JSON.stringify(apiResult)}
      </pre>
    );
  }

  // ── state ──
  const { movies, loading, liveChannels, loadMovies } = useMovieLibrary();
  const [categories, saveCats] = useCategories(movies);
  const isDesktop = useIsDesktop();
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("הכל");
  const [selectedMovie, setSelectedMovie] = useState(() => lsJson("zovex_movie"));
  const [selectedSeries, setSelectedSeries] = useState(() => ls("zovex_series"));
  const [showDonation, setShowDonation] = useState(false);
  const [pendingAction, setPendingAction] = useState(null);

  // admin
  const [showAdminLogin, setShowAdminLogin] = useState(false);
  const [showAdmin, setShowAdmin] = useState(false);

  // live streams — מערך של כמה שידורים חיים במקביל, כל אחד עם שם וקישור
  // נשמרים ב-movies.json כתכנים עם category: "שידורים חיים" ו-is_live: true
  const [showLivePlayer, setShowLivePlayer] = useState(null); // האובייקט של הלייב שנפתח, או null
  const liveActive = liveChannels.length > 0;

  const { playerMovie, setPlayerMovie, resumeSeconds, kalturaRefreshing, openWithKalturaRefresh } =
    usePlayback({ user, loadProgress, saveHistory });

  // ── effects ──
  // נקה state כשנכנסים ישירות למסך הבית (ללא slug)
  useEffect(() => {
    if (!slug) {
      setSelectedMovie(null);
      setSelectedSeries(null);
      setPlayerMovie(null);
      lsDel("zovex_movie");
      lsDel("zovex_series");
      lsDel("zovex_player");
    }
  }, []);

  useEffect(() => {
    const onPop = () => {
      if (playerMovie) { setPlayerMovie(null); window.history.pushState(null, "", window.location.href); return; }
      if (selectedSeries) { setSelectedSeries(null); window.history.pushState(null, "", window.location.href); return; }
      if (selectedMovie) { setSelectedMovie(null); window.history.pushState(null, "", window.location.href); return; }
    };
    window.history.pushState(null, "", window.location.href);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [playerMovie, selectedSeries, selectedMovie]);

  useEffect(() => {
    if (selectedMovie) document.title = `${selectedMovie.title} | ZOVEX`;
    else if (selectedSeries) document.title = `${selectedSeries} | ZOVEX`;
    else document.title = "ZOVEX - סדרות וסרטים לצפייה ישירה";
  }, [selectedMovie, selectedSeries]);

  useEffect(() => { selectedMovie ? lsSet("zovex_movie", JSON.stringify(selectedMovie)) : lsDel("zovex_movie"); }, [selectedMovie]);
  useEffect(() => { selectedSeries ? lsSet("zovex_series", selectedSeries) : lsDel("zovex_series"); }, [selectedSeries]);

  useEffect(() => {
    if (searchTerm === SECRET_TRIGGER) { setSearchTerm(""); setShowAdminLogin(true); }
  }, [searchTerm]);

  // ── derived ──
  const seriesMap = useMemo(() => {
    const map = {};
    movies.forEach(m => {
      if (!m.series_name) return;
      if (!map[m.series_name]) map[m.series_name] = { name: m.series_name, thumbnail_url: m.thumbnail_url, description: m.description, category: m.category, custom_slug: m.custom_slug, episodes: [] };
      map[m.series_name].episodes.push(m);
    });
    return map;
  }, [movies]);

  // הפרק הבא בסדרה, אחרי הפרק שמנגן כרגע (null אם זה סרט בודד או שאין פרק אחרי)
  const nextEpisode = useMemo(() => {
    if (!playerMovie?.series_name) return null;
    const series = seriesMap[playerMovie.series_name];
    if (!series) return null;
    const sorted = [...series.episodes].sort((a, b) => (a.season_number || 1) - (b.season_number || 1) || (a.episode_number || 0) - (b.episode_number || 0));
    const idx = sorted.findIndex(e => e.id === playerMovie.id);
    if (idx === -1 || idx === sorted.length - 1) return null;
    return sorted[idx + 1];
  }, [playerMovie, seriesMap]);

  const allCategories = useMemo(() => {
    const from = movies.map(m => m.category).filter(Boolean);
    // "שידורים חיים" מסוננת מכאן כי היא נוספת בנפרד למטה — כדי למנוע כפילות
    const base = ["הכל", ...new Set([...categories, ...from])].filter(c => c !== "שידורים חיים");
    let result = liveActive ? [...base, "שידורים חיים"] : base;
    // "היסטוריה" מוצגת רק למשתמשים מחוברים
    if (user) result = [...result, "היסטוריה"];
    return result;
  }, [movies, categories, liveActive, user]);

  // ── handlers ──
  // המשך צפייה / היסטוריה — קליק פותח את הנגן ישירות בדיוק בשנייה שנשמרה,
  // בלי לעבור קודם דרך מסך הפרטים ולחצן "המשך לצפייה" נוסף
  const handleContinueWatchingClick = (item) => {
    const action = () => {
      if (item.series_name) setSelectedSeries(item.series_name);
      else setSelectedMovie(item);
      openWithKalturaRefresh(item);
    };
    setPendingAction(() => action); setShowDonation(true);
  };

  const handleItemClick = (item, isSer) => {
    const action = () => {
      if (item.is_live) {
        setShowLivePlayer(item);
        return;
      }
      if (isSer) {
        const slug = item.custom_slug || encodeURIComponent(item.name.replace(/ /g, "-"));
        navigate(`/${slug}`); setSelectedSeries(item.name);
      } else {
        const slug = item.custom_slug || (encodeURIComponent((item.title || "").replace(/ /g, "-")) + "-" + item.id.slice(0, 6));
        navigate(`/${slug}`); setSelectedMovie(item);
      }
    };
    setPendingAction(() => action); setShowDonation(true);
  };

  const onLogoClick = () => {
    setSelectedMovie(null);
    setSelectedSeries(null);
    setPlayerMovie(null);
    setSearchTerm("");
    setSelectedCategory("הכל");
    lsDel("zovex_movie");
    lsDel("zovex_series");
    lsDel("zovex_player");
    navigate("/");
  };

  // מזהה איזה סרט/סדרה לפתוח לפי ה-slug שבכתובת
  useSlugRouting(movies, slug, episode, setSelectedSeries, setSelectedMovie, openWithKalturaRefresh);

  // ── early returns ──
  if (kalturaRefreshing) return (
    <div style={{ position: "fixed", inset: 0, background: "#000", zIndex: 9999, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 20 }}>
      <style>{SPIN}</style>
      <div style={{ width: 56, height: 56, border: "4px solid rgba(255,255,255,0.15)", borderTop: "4px solid #e91e63", borderRadius: "50%", animation: "spin 0.9s linear infinite" }} />
      <p style={{ color: "#fff", fontSize: 15, fontFamily: "Arial", margin: 0 }}>מכין סרטון...</p>
    </div>
  );

  if (playerMovie) return (
    <CustomVideoPlayer
      movie={playerMovie}
      startTime={resumeSeconds}
      onProgress={(pos, dur) => saveProgress(playerMovie.id, pos, dur)}
      onClose={() => setPlayerMovie(null)}
      onNextEpisode={nextEpisode ? () => openWithKalturaRefresh(nextEpisode) : undefined}
      nextEpisodeLabel={nextEpisode ? (nextEpisode.episode_title || `פרק ${nextEpisode.episode_number}`) : undefined}
    />
  );

  if (loading) return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "100vh", background: "#0a0a0a" }}>
      <style>{SPIN}</style>
      <div style={{ textAlign: "center" }}>
        <div style={{ width: 50, height: 50, border: "5px solid #222", borderTop: "5px solid #e50914", borderRadius: "50%", animation: "spin 1s linear infinite", margin: "0 auto 15px" }} />
        <p style={{ color: "#aaa", fontFamily: "Arial" }}>טוען...</p>
      </div>
    </div>
  );

  if (showAdminLogin) return (
    <AdminLoginScreen
      onSuccess={() => { setShowAdminLogin(false); setShowAdmin(true); setShowDonation(false); }}
      onCancel={() => setShowAdminLogin(false)}
    />
  );

  // ── donation modal ──
  const donationModal = showDonation && !showAdmin
    ? <DonationModalView onContinue={() => { setShowDonation(false); pendingAction && pendingAction(); }} />
    : null;

  // ── admin panel ──
  if (showAdmin) return (
    <AdminPanel
      movies={movies}
      seriesMap={seriesMap}
      liveChannels={liveChannels}
      categories={categories}
      saveCats={saveCats}
      loadMovies={loadMovies}
      onClose={() => setShowAdmin(false)}
    />
  );

  // ── Series page ──
  if (selectedSeries) return (
    <SeriesView
      seriesName={selectedSeries}
      seriesMap={seriesMap}
      onEpisodePlay={openWithKalturaRefresh}
      onClose={() => { setSelectedSeries(null); window.history.replaceState(null, "", "/zovex/"); }}
    />
  );

  // ── Movie page ──
  if (selectedMovie) return (
    <MovieDetail
      movie={selectedMovie}
      movies={movies}
      onPlay={() => openWithKalturaRefresh(selectedMovie)}
      onClose={() => { setSelectedMovie(null); window.history.replaceState(null, "", "/zovex/"); }}
      onSelectMovie={setSelectedMovie}
    />
  );

  // ── Home grid ──
  return (
    <>
      {donationModal}

      {/* ── Live Player — נפתח מתוך קטגוריית "שידורים חיים", דרך אותו נגן מאוחד כמו כל שאר התוכן ── */}
      {showLivePlayer && (
        <CustomVideoPlayer
          movie={{ ...showLivePlayer, is_live: true }}
          onClose={() => setShowLivePlayer(null)}
        />
      )}

      <HomePage
        user={user}
        onLogout={onLogout}
        searchTerm={searchTerm}
        setSearchTerm={setSearchTerm}
        selectedCategory={selectedCategory}
        setSelectedCategory={setSelectedCategory}
        allCategories={allCategories}
        refreshHistory={refreshHistory}
        onLogoClick={onLogoClick}
        movies={movies}
        seriesMap={seriesMap}
        liveChannels={liveChannels}
        isDesktop={isDesktop}
        handleItemClick={handleItemClick}
        handleContinueWatchingClick={handleContinueWatchingClick}
        history={history}
      />
    </>
  );
}
