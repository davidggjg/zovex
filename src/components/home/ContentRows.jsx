import { colors, radius, depth, lift } from "@/theme/tokens";
import { catName } from "../../i18n";
import { useState, useEffect, useMemo } from "react";
import { NetflixRow, buildCardHref } from "./NetflixCard";
import LiveBanner from "../LiveBanner";
import { NetflixCard } from "./NetflixCard";
import { groupLiveByGenre } from "./liveGenres";

// ── רשת פריטים ─────────────────────────────────────────────────────────
// קטגוריה ספציפית הוצגה עד עכשיו כשורה אופקית אחת, ו-NetflixRow טוען רק
// 20 פריטים בכל פעם. כלומר בקטגוריה עם מאות פריטים ראו עשרים, וכדי לראות
// עוד היה צריך לגלול הצידה שוב ושוב — זה מה שנראה כמו "לא מוצג הכל".
// רשת מציגה שורות רבות בבת אחת, וכפתור מפורש מוסיף עוד. כפתור ולא גלילה
// אינסופית, כי בשלט של הטלוויזיה אפשר להגיע לכפתור אבל אי אפשר "לגלול עוד".
const GRID_PAGE = 60;

function CardGrid({ title, items, isDesktop, handleItemClick }) {
  const [shown, setShown] = useState(GRID_PAGE);
  useEffect(() => { setShown(GRID_PAGE); }, [items]);

  // ── שלוש בשורה בטלפון ──────────────────────────────────────────────
  //
  // ‎auto-fill‎ עם רוחב קבוע של 143 נתן שתיים בשורה בכל טלפון מתחת ל-460
  // פיקסלים, כלומר כמעט בכולם: 143×2 + מרווח נכנס, 143×3 לא. התוצאה היא
  // שליש מהתוכן על המסך לעומת האפליקציה, שמציגה שלוש.
  //
  // הפתרון הוא לחשב את הרוחב מרוחב המסך במקום לקוות שהוא יתאים: שלוש
  // עמודות קודם, והכרטיס מקבל את מה שנשאר. היחס 1.41 הוא זה של הכרטיס
  // הקיים (143×202) ולכן הפוסטרים לא נמתחים.
  const [vw, setVw] = useState(() => { try { return window.innerWidth; } catch { return 390; } });
  useEffect(() => {
    const onResize = () => setVw(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const PAD = 16;
  const gap = isDesktop ? 18 : 10;
  const cardW = isDesktop ? 184 : Math.max(96, Math.floor((vw - PAD * 2 - gap * 2) / 3));
  const cardH = isDesktop ? 260 : Math.round(cardW * 1.41);
  const visible = items.slice(0, shown);

  return (
    <div style={{ padding: "0 16px 30px", direction: "rtl" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
        <h2 style={{ fontSize: isDesktop ? 21 : 18, fontWeight: 900, color: "#fff", margin: 0, letterSpacing: "-0.3px" }}>{title}</h2>
        <span style={{ fontSize: 12, color: "#888" }}>({items.length})</span>
      </div>
      <div style={{
        display: "grid",
        gridTemplateColumns: isDesktop
          ? `repeat(auto-fill, minmax(${cardW}px, 1fr))`
          : `repeat(3, ${cardW}px)`,
        gap,
        justifyContent: "center",
        justifyItems: "center",
      }}>
        {visible.map(item => {
          const isSer = !!item.episodes;
          return (
            <NetflixCard
              key={isSer ? "s-" + item.name : item.id}
              item={item}
              isSer={isSer}
              isLive={!!item.is_live}
              onClick={handleItemClick}
              cardW={cardW}
              cardH={cardH}
            />
          );
        })}
      </div>
      {shown < items.length && (
        <button
          onClick={() => setShown(v => v + GRID_PAGE)}
          style={{
            display: "block", margin: "22px auto 0", padding: "12px 28px",
            borderRadius: 26, cursor: "pointer", fontFamily: "inherit",
            fontSize: 14, fontWeight: 800, color: "#fff",
            background: "rgba(255,255,255,0.055)",
            backdropFilter: "blur(14px) saturate(150%)",
            WebkitBackdropFilter: "blur(14px) saturate(150%)",
            border: "1px solid rgba(255,255,255,0.11)",
          }}
        >
          הצג עוד ({items.length - shown})
        </button>
      )}
    </div>
  );
}

function NetflixRows({ movies, seriesMap, liveChannels, allCategories, selectedCategory, setSelectedCategory, searchTerm, isDesktop, handleItemClick, onContinueWatchingClick, history, user, favIds }) {
  const q = searchTerm.toLowerCase();

  // בנה map: קטגוריה → פריטים
  const buildItems = (cat) => {
    const regularMovies = movies.filter(m =>
      !m.series_name &&
      (m.title || "").toLowerCase().includes(q) &&
      (cat === "הכל" || m.category === cat)
    );
    const seen = {};
    const seriesList = [];
    movies.forEach(m => {
      if (!m.series_name || seen[m.series_name]) return;
      const matchQ = m.series_name.toLowerCase().includes(q) || (m.title || "").toLowerCase().includes(q);
      const matchC = cat === "הכל" || m.category === cat;
      if (matchQ && matchC) { seen[m.series_name] = true; seriesList.push(seriesMap[m.series_name]); }
    });
    return [...seriesList, ...regularMovies];
  };

  const liveItems = liveChannels.filter(ch => ch.title.toLowerCase().includes(q)).map(ch => ({ ...ch, is_live: true }));
  const hasLiveRow = (selectedCategory === "הכל" || selectedCategory === "שידורים חיים") && liveItems.length > 0;

  // קבע אילו שורות להציג לפי selectedCategory
  let rowsToShow = [];
  if (selectedCategory === "הכל") {
    // כל הקטגוריות כשורות נפרדות
    const cats = allCategories.filter(c => c !== "הכל" && c !== "שידורים חיים");
    cats.forEach(cat => {
      const items = buildItems(cat);
      if (items.length > 0) rowsToShow.push({ title: cat, cat, items, isLive: false });
    });
  }
  // קטגוריה ספציפית ושידורים חיים מטופלים למטה כרשת/כשורות ז'אנר, לא כאן.

  // שורת "המשך צפייה" — רק למחוברים עם היסטוריה
  const continueWatchingItems = user && history && history.length > 0
    ? history.slice(0, 10).map(h => {
        const found = movies.find(m => m.id === h.media_id) ||
          Object.values(seriesMap).flatMap(s => s.episodes).find(e => e.id === h.media_id);
        // [resume] המיקום נוסע יחד עם הפריט.
        //
        // ‎found‎ הוא הפריט מהקטלוג, ולפריט קטלוג אין ‎position‎ — זה נתון
        // היסטוריה. בלי השורה הזו ‎handleContinueWatchingClick‎ קיבל פריט
        // בלי מיקום, ‎Number.isFinite(item.position)‎ החזיר false, והנגן
        // נפתח על 0. כל שאר שרשרת ההמשכה הייתה תקינה — המיקום פשוט אבד
        // כאן, לפני שהגיע אליה.
        if (!found) return null;
        // [hist_label] עונה ופרק על הכרטיס.
        //
        // הכרטיס הציג את ‎title‎ של הפרק בלבד, ובסדרות רבות הוא זהה לכל
        // הפרקים — ולכן אי אפשר היה לדעת איפה עצרת. התווית נוספת כשדה
        // נפרד ולא דורסת את ‎title‎, שממנו נבנית הכתובת.
        const se = (found.season_number && found.episode_number)
          ? `${found.series_name || found.title} · ע׳${found.season_number} פ׳${found.episode_number}`
          : null;
        return {...found, position: h.position, duration: h.duration,
                ...(se ? {_label: se} : {})};
      }).filter(Boolean)
    : [];

  // אם בוחרים "היסטוריה" — הצג שתי שורות: המשך צפייה, ואחריה היסטוריה מלאה
  // חשוב: הבדיקה הזו חייבת להיות *לפני* ה-early-return של "לא נמצאו תוצאות"
  // למטה — כי "היסטוריה" היא טאב וירטואלי, לא קטגוריית תוכן אמיתית, אז
  // rowsToShow תמיד ריק בשבילה ובלי הסדר הזה היינו נתקעים תמיד ב"לא נמצאו
  // תוצאות" בלי להגיע לקוד שמטפל בהיסטוריה בפועל (זה בדיוק מה שקרה).
  // "מועדפים" הוא טאב וירטואלי כמו "היסטוריה" — הבדיקה חייבת להיות לפני
  // ה-early-return של "לא נמצאו תוצאות", אחרת rowsToShow הריק היה תופס.
  if (selectedCategory === "מועדפים") {
    const favItems = (movies || []).filter(m => favIds && favIds.has(String(m.id)));
    return (
      <div style={{ paddingTop: 8 }}>
        {favItems.length > 0 ? (
          <NetflixRow title="❤️ המועדפים שלי" items={favItems} isDesktop={isDesktop}
                      handleItemClick={handleItemClick} isLiveRow={false} />
        ) : (
          <div style={{ textAlign: "center", padding: "60px 20px", color: "#aaa" }}>
            <p style={{ fontSize: 18 }}>אין עדיין מועדפים</p>
            <p style={{ fontSize: 13, marginTop: 8 }}>
              פתחו סרט ולחצו על הלב — הוא יופיע כאן, וגם באפליקציה
            </p>
          </div>
        )}
      </div>
    );
  }

  if (selectedCategory === "היסטוריה") {
    return (
      <div style={{ paddingTop: 8 }}>
        {continueWatchingItems.length > 0 ? (
          <>
            <NetflixRow title="▶️ המשך צפייה" items={continueWatchingItems} isDesktop={isDesktop} handleItemClick={onContinueWatchingClick} isLiveRow={false} />
            <NetflixRow title="📋 היסטוריית צפייה" items={continueWatchingItems} isDesktop={isDesktop} handleItemClick={onContinueWatchingClick} isLiveRow={false} />
          </>
        ) : (
          <div style={{ textAlign: "center", padding: "60px 20px", color: "#aaa" }}>
            <p style={{ fontSize: 18 }}>עדיין לא צפית בשום דבר</p>
            <p style={{ fontSize: 13, marginTop: 8 }}>ההיסטוריה שלך תופיע כאן</p>
          </div>
        )}
      </div>
    );
  }

  const empty = (
    <div style={{ textAlign: "center", padding: "60px 20px", color: "#aaa" }}>
      <p style={{ fontSize: 18 }}>לא נמצאו תוצאות</p>
    </div>
  );

  // ── שידורים חיים: שורה לכל ז'אנר ─────────────────────────────────────
  // עד עכשיו כל 102 הערוצים נדחסו לשורה אופקית אחת שטוענת 20 בכל פעם, ולכן
  // רובם היו בלתי נגישים בפועל. אין שדה ז'אנר בנתונים, אז הוא נגזר מהשם
  // (ראה liveGenres.js) — כל 102 הערוצים מסווגים.
  if (selectedCategory === "שידורים חיים") {
    const groups = groupLiveByGenre(liveItems);
    if (groups.length === 0) return empty;
    return (
      <div style={{ paddingTop: 8 }}>
        {groups.map(g => (
          <NetflixRow
            key={g.title}
            title={g.title}
            items={g.items}
            isDesktop={isDesktop}
            handleItemClick={handleItemClick}
            isLiveRow
          />
        ))}
      </div>
    );
  }

  // ── קטגוריה ספציפית: רשת ולא רצועה אופקית ────────────────────────────
  if (selectedCategory !== "הכל") {
    const items = buildItems(selectedCategory);
    if (items.length === 0) return empty;
    return (
      <div style={{ paddingTop: 8 }}>
        <CardGrid title={catName(selectedCategory)} items={items} isDesktop={isDesktop} handleItemClick={handleItemClick} />
      </div>
    );
  }

  if (!hasLiveRow && rowsToShow.length === 0) {
    return <div style={{ textAlign: "center", padding: "60px 20px", color: "#aaa" }}><p style={{ fontSize: 18 }}>לא נמצאו תוצאות</p></div>;
  }

  return (
    <div style={{ paddingTop: 8 }}>
      {/* שורת "המשך צפייה" מוצגת אך ורק בתוך קטגוריית "היסטוריה" (למעלה) —
          לא במסך הראשי/"הכל" ולא בשום קטגוריה אחרת */}
      {hasLiveRow && <LiveBanner liveChannels={liveItems} onPlay={handleItemClick} isDesktop={isDesktop} />}
      {rowsToShow.map(row => (
        <NetflixRow
          key={row.title}
          title={row.title}
          items={row.items}
          isDesktop={isDesktop}
          handleItemClick={handleItemClick}
          isLiveRow={row.isLive}
          // בחירת הקטגוריה היא בדיוק מה שמחליף את מסך הבית ברשת של אותה
          // קטגוריה (ראה ה-return של selectedCategory !== "הכל" למטה), אז
          // "ראה הכל" אינו מסך חדש — הוא אותו מסך שכבר קיים.
          // הגלילה למעלה חיונית: בלעדיה הרשת החדשה נפתחת באמצע, בדיוק
          // בגובה שבו השורה ישבה, ונראית כאילו לא קרה כלום.
          onSeeAll={setSelectedCategory ? () => {
            setSelectedCategory(row.cat);
            try { window.scrollTo({ top: 0, behavior: "smooth" }); } catch { window.scrollTo(0, 0); }
          } : undefined}
        />
      ))}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// RecentlyAddedBanner — באנר "עלה עכשיו" שמתחלף כל 10 שניות
// ומציג רק תוכן שנוסף ב-24 השעות האחרונות (נעלם אוטומטית אחרי זה)
// ═══════════════════════════════════════════════════════════════
function RecentlyAddedBanner({ movies, seriesMap, handleItemClick }) {
  const items = useMemo(() => {
    const DAY_MS = 24 * 60 * 60 * 1000;
    const now = Date.now();
    // ── למה יש כאן מיון ───────────────────────────────────────────────
    //
    // דווח: "הבאנר לא מתעדכן". הוא אכן לא — הלולאה כאן רצה על הקטלוג
    // **לפי סדר המערך** ועצרה אחרי שמונה, בלי אף פעם למיין לפי תאריך.
    // כלומר "שמונה הראשונים שנתקלתי בהם שנוספו ביממה", ולא "שמונה
    // החדשים ביותר". כל עוד המערך במקרה מסודר מהחדש לישן זה נראה תקין,
    // ובכל סידור אחר הבאנר מפספס בדיוק את מה שהוא קיים בשבילו.
    //
    // נמדד על הקטלוג החי: 335 פריטים נוספו ביממה, והלולאה הישנה בחרה
    // "קופה ראשית" מלפני 23.3 שעות ו"שתולים" מלפני 20.9 — ודילגה על
    // "השוטרים" מלפני 4.9 שעות, שפשוט יושב עמוק יותר במערך.
    //
    // ועוד פרט: לסדרה, התאריך הקובע הוא של הפרק **החדש ביותר** שלה.
    // בלי זה פרק ישן יותר של אותה סדרה היה קובע את מקומה בתור.
    const best = new Map();
    for (const m of movies) {
      if (!m.created_date) continue;
      const t = new Date(m.created_date).getTime();
      if (isNaN(t) || now - t > DAY_MS) continue;
      const key = m.series_name || m.id;
      const cur = best.get(key);
      if (!cur || t > cur.t) best.set(key, {t, m});
    }
    return [...best.values()].sort((a, b) => b.t - a.t).slice(0, 8).map(x => x.m);
  }, [movies]);

  const [index, setIndex] = useState(0);
  const [visible, setVisible] = useState(true);

  useEffect(() => { setIndex(0); }, [items.length]);

  useEffect(() => {
    if (items.length < 2) return;
    const t = setInterval(() => {
      setVisible(false);
      setTimeout(() => {
        setIndex(i => (i + 1) % items.length);
        setVisible(true);
      }, 350);
    }, 10000);
    return () => clearInterval(t);
  }, [items.length]);

  if (items.length === 0) return null;

  const movie = items[index % items.length];
  const isSer = !!movie.series_name;
  const displayItem = isSer ? (seriesMap[movie.series_name] || movie) : movie;
  const title = movie.series_name || movie.title;

  const year = movie.year || displayItem.year;

  // ── באנר הגיבור, במבנה של האפליקציה ────────────────────────────────
  //
  // מה שהיה: פוסטר צר בצד אחד וטקסט בצד השני. זה מה שנראה "שטוח
  // כמו מדבקה" — שני מלבנים זה לצד זה, בלי שום עומק.
  //
  // מה שהאפליקציה עושה (HomeScreen.js, HeroBanner): תמונה ממלאת את
  // כל הכרטיס, מסך כהה שמתחזק כלפי מטה, והכותרת יושבת **על** התמונה
  // בתחתית. זה המבנה כאן.
  //
  // ל-0 מתוך 26,006 הפריטים בקטלוג אין backdrop_url — התמונה
  // הרוחבית שהאפליקציה מעדיפה. לכן זהו בדיוק מסלול הנפילה שלה:
  // אותה תמונה פעמיים, מטושטשת ב-cover מאחור כדי למלא את המסגרת,
  // ושלמה ב-contain מלפנים. בלי שתיהן פוסטר צר או נמתח או מרחף
  // קטן במרכז.
  const bg = movie.backdrop_url || movie.thumbnail_url;

  return (
    <a
      href={buildCardHref(displayItem, isSer, false)}
      onClick={e => { e.preventDefault(); handleItemClick(displayItem, isSer); }}
      style={{
        position: "relative", display: "block", textDecoration: "none",
        color: "inherit", margin: "8px 14px 18px", height: 228,
        borderRadius: radius.hero, overflow: "hidden",
        background: colors.surface, cursor: "pointer",
        // §12: משטח גדול נקרא עבה — צל עמוק. הזוהר האדום העדין
        // מתחתיו הוא אותו פרט שיש ל-hero באפליקציה (shadowColor:
        // auroraRed).
        boxShadow: `${depth(3).boxShadow}, 0 18px 46px -24px ${colors.glowRed}`,
        border: `1px solid ${colors.glassBorder}`,
        opacity: visible ? 1 : 0,
        transition: "opacity .35s ease, transform 220ms cubic-bezier(0.22,1,0.36,1)",
      }}
      onMouseEnter={e => { e.currentTarget.style.transform = "translateY(-3px)"; }}
      onMouseLeave={e => { e.currentTarget.style.transform = "none"; }}
    >
      {bg && (
        <>
          <img src={bg} alt="" aria-hidden="true"
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%",
                     objectFit: "cover", filter: "blur(28px) saturate(160%)",
                     transform: "scale(1.25)" }} />
          <img src={bg} alt=""  aria-hidden="true"
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%",
                     objectFit: movie.backdrop_url ? "cover" : "contain" }} />
        </>
      )}

      {/* מסך כהה מלמטה — אותה צורה כמו DarkGradient באפליקציה
          (0.86·t²), כאן בשורת CSS אחת. בלעדיו הכותרת יושבת על תמונה
          בהירה ונעלמת. */}
      <div style={{ position: "absolute", inset: 0, background:
        `linear-gradient(to top, rgba(7,7,12,0.96) 0%, rgba(7,7,12,0.82) 22%, rgba(7,7,12,0.34) 55%, rgba(7,7,12,0.04) 100%)` }} />

      <div style={{ position: "absolute", insetInlineStart: 0, insetInlineEnd: 0, bottom: 0,
                    padding: "16px 18px 18px", textAlign: "right" }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 5,
                       background: colors.focusTint, color: "#fff",
                       border: `1px solid ${colors.glowRed}`,
                       backdropFilter: "blur(10px)", WebkitBackdropFilter: "blur(10px)",
                       fontSize: 11, fontWeight: 800, padding: "4px 11px",
                       borderRadius: radius.pill, marginBottom: 8 }}>
          <span style={{ width: 5, height: 5, borderRadius: 3,
                         background: colors.primaryHi, display: "inline-block" }} />
          עלה עכשיו
        </span>
        {!!year && (
          <div style={{ color: "rgba(255,255,255,0.75)", fontSize: 13, fontWeight: 700,
                        marginBottom: 3, textShadow: "0 1px 4px rgba(0,0,0,0.7)" }}>{year}</div>
        )}
        {/* §15: טקסט גדול מקבל tracking שלילי ו-leading צמוד. */}
        <div style={{ color: "#fff", fontSize: 25, fontWeight: 900, lineHeight: 1.1,
                      letterSpacing: "-0.02em", textShadow: "0 2px 10px rgba(0,0,0,0.85)",
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {title}
        </div>
      </div>
    </a>
  );
}

export { NetflixRows, RecentlyAddedBanner };
