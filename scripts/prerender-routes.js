// scripts/prerender-routes.js
// אחרי ה-build, יוצר תיקייה אמיתית לכל route (סרט/סדרה) עם עותק מותאם-אישית
// של index.html: כותרת, תיאור, ותמונת פוסטר (og:image) ספציפיים לאותו סרט/
// סדרה, ועוד תגית JSON-LD (schema.org). זה מה שמאפשר לגוגל בפועל "לראות"
// עמוד נפרד לכל תוכן - עם התמונה והשם הנכונים - במקום שכל דף באתר יראה
// לגוגל בדיוק אותו כותרת/תיאור גנרי בלי תמונה, שזו הסיבה שהפוסטרים לא
// הופיעו בגוגל תמונות.

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const DIST_DIR = path.join(ROOT, "dist");
const MOVIES_PATH = path.join(ROOT, "public", "movies.json");
const INDEX_HTML = path.join(DIST_DIR, "index.html");
const SITE_URL = "https://davidggjg.github.io/zovex";

function slugifyMovie(movie) {
  if (movie.custom_slug) return movie.custom_slug;
  const base = encodeURIComponent((movie.title || "").replace(/ /g, "-"));
  return `${base}-${(movie.id || "").slice(0, 6)}`;
}

function slugifySeries(seriesName, customSlug) {
  if (customSlug) return customSlug;
  return encodeURIComponent(seriesName.replace(/ /g, "-"));
}

// אוסף route -> מטא-דאטה (כותרת/תיאור/פוסטר/סוג) לכל סרט וסדרה
function collectRoutes(movies) {
  const routes = new Map();
  const seriesSeen = new Map(); // series_name -> נציג ראשון (לפוסטר/תיאור)

  for (const m of movies) {
    if (m.series_name) {
      if (!seriesSeen.has(m.series_name)) seriesSeen.set(m.series_name, m);
    } else {
      routes.set(slugifyMovie(m), {
        title: m.title,
        description: m.description,
        thumbnail_url: m.thumbnail_url,
        year: m.year,
        type: "movie",
      });
    }
  }

  for (const [name, rep] of seriesSeen.entries()) {
    routes.set(slugifySeries(name, rep.custom_slug), {
      title: name,
      description: rep.description,
      thumbnail_url: rep.thumbnail_url,
      year: rep.year,
      type: "series",
    });
  }

  return routes;
}

function escapeHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeJson(str) {
  return JSON.stringify(String(str || ""));
}

function buildPageHtml(baseHtml, route, meta) {
  const title = `${meta.title} - צפייה ישירה | ZOVEX`;
  const rawDesc = (meta.description || `צפייה ישירה ב${meta.title} - בחינם, באתר ZOVEX.`).trim();
  const description = rawDesc.length > 200 ? rawDesc.slice(0, 197) + "..." : rawDesc;
  // עם לוכסן בסוף - זו הכתובת שבאמת מחזירה 200 ישירות (GitHub Pages מפנה
  // 301 מהגרסה בלי הלוכסן, כי route כאן הוא תיקייה עם index.html בפנים)
  const url = `${SITE_URL}/${route}/`;
  const image = meta.thumbnail_url || "";
  const ogType = meta.type === "series" ? "video.tv_show" : "video.movie";
  const schemaType = meta.type === "series" ? "TVSeries" : "Movie";

  let html = baseHtml;
  html = html.replace(/<title>.*?<\/title>/s, `<title>${escapeHtml(title)}</title>`);
  html = html.replace(/<meta name="description" content=".*?" \/>/s, `<meta name="description" content="${escapeHtml(description)}" />`);
  html = html.replace(/<meta property="og:title" content=".*?" \/>/s, `<meta property="og:title" content="${escapeHtml(title)}" />`);
  html = html.replace(/<meta property="og:description" content=".*?" \/>/s, `<meta property="og:description" content="${escapeHtml(description)}" />`);
  html = html.replace(/<meta property="og:type" content=".*?" \/>/s, `<meta property="og:type" content="${ogType}" />`);

  const extraTags = [
    `<meta property="og:url" content="${escapeHtml(url)}" />`,
    image ? `<meta property="og:image" content="${escapeHtml(image)}" />` : "",
    `<meta name="twitter:card" content="summary_large_image" />`,
    `<meta name="twitter:title" content="${escapeHtml(title)}" />`,
    `<meta name="twitter:description" content="${escapeHtml(description)}" />`,
    image ? `<meta name="twitter:image" content="${escapeHtml(image)}" />` : "",
    `<link rel="canonical" href="${escapeHtml(url)}" />`,
    `<script type="application/ld+json">${JSON.stringify({
      "@context": "https://schema.org",
      "@type": schemaType,
      name: meta.title,
      description: description,
      image: image || undefined,
      dateCreated: meta.year ? String(meta.year) : undefined,
      url,
    })}</script>`,
  ].filter(Boolean).join("\n    ");

  html = html.replace("</head>", `    ${extraTags}\n  </head>`);

  // תוכן סטטי אמיתי בתוך #root — כדי שגם מי שלא מריץ JS (בוטים, תצוגות-
  // תצוגה-מקדימה ברשתות חברתיות) יראה טקסט/תמונה אמיתיים בתגובה הראשונה,
  // לא רק תגיות <head>. React (createRoot().render) מחליף את זה לגמרי
  // ברגע שהוא עולה - אין כאן hydrate, אז אין סיכון לשגיאת mismatch.
  const staticBody = `
      <h1>${escapeHtml(meta.title)}</h1>
      ${image ? `<img src="${escapeHtml(image)}" alt="${escapeHtml(meta.title)}" style="max-width:280px;border-radius:8px" />` : ""}
      <p>${escapeHtml(description)}</p>
      <p><a href="${escapeHtml(SITE_URL)}/">צפייה ישירה בחינם - ZOVEX</a></p>
    `;
  html = html.replace(
    '<div id="root"></div>',
    `<div id="root" style="background:#0a0a0a;color:#fff;font-family:Arial,sans-serif;padding:20px;direction:rtl">${staticBody}</div>`
  );
  return html;
}

function prerender() {
  if (!fs.existsSync(DIST_DIR) || !fs.existsSync(INDEX_HTML)) {
    console.warn("[prerender] dist/index.html not found — run this after `vite build`.");
    return;
  }
  if (!fs.existsSync(MOVIES_PATH)) {
    console.warn("[prerender] movies.json not found, skipping.");
    return;
  }

  const indexHtml = fs.readFileSync(INDEX_HTML, "utf-8");

  let movies;
  try {
    movies = JSON.parse(fs.readFileSync(MOVIES_PATH, "utf-8"));
  } catch (e) {
    console.error("[prerender] Failed to parse movies.json:", e.message);
    return;
  }
  if (!Array.isArray(movies)) {
    console.warn("[prerender] movies.json is not an array, skipping.");
    return;
  }

  const routes = collectRoutes(movies);
  let created = 0;

  for (const [route, meta] of routes.entries()) {
    if (!route) continue;
    const routeDir = path.join(DIST_DIR, route);
    try {
      fs.mkdirSync(routeDir, { recursive: true });
      const pageHtml = buildPageHtml(indexHtml, route, meta);
      fs.writeFileSync(path.join(routeDir, "index.html"), pageHtml, "utf-8");
      created++;
    } catch (e) {
      console.warn(`[prerender] Failed to create route "${route}":`, e.message);
    }
  }

  console.log(`[prerender] Created ${created} static route folders in dist/ with per-page SEO tags.`);
}

prerender();
