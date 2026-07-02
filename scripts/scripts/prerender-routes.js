// scripts/prerender-routes.js
// אחרי ה-build, יוצר תיקייה אמיתית לכל route (סרט/סדרה) עם עותק של index.html.
// כך GitHub Pages מחזיר 200 (לא 404) לכתובות כמו /zovex/avengers/,
// והאפליקציה (React Router) ממשיכה לטעון ולנתב כרגיל בצד הלקוח.
// זה מה שמאפשר לגוגל בפועל "לראות" ולאנדקס כל דף בנפרד.

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const DIST_DIR = path.join(ROOT, "dist");
const MOVIES_PATH = path.join(ROOT, "public", "movies.json");
const INDEX_HTML = path.join(DIST_DIR, "index.html");

function slugifyMovie(movie) {
  if (movie.custom_slug) return movie.custom_slug;
  const base = encodeURIComponent((movie.title || "").replace(/ /g, "-"));
  return `${base}-${(movie.id || "").slice(0, 6)}`;
}

function slugifySeries(seriesName, customSlug) {
  if (customSlug) return customSlug;
  return encodeURIComponent(seriesName.replace(/ /g, "-"));
}

function collectRoutes(movies) {
  const routes = new Set();
  const seriesSeen = new Map();

  for (const m of movies) {
    if (m.series_name) {
      if (!seriesSeen.has(m.series_name)) {
        seriesSeen.set(m.series_name, m.custom_slug || null);
      }
    } else {
      routes.add(slugifyMovie(m));
    }
  }

  for (const [name, customSlug] of seriesSeen.entries()) {
    routes.add(slugifySeries(name, customSlug));
  }

  return Array.from(routes);
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

  for (const route of routes) {
    if (!route) continue;
    const routeDir = path.join(DIST_DIR, route);
    try {
      fs.mkdirSync(routeDir, { recursive: true });
      fs.writeFileSync(path.join(routeDir, "index.html"), indexHtml, "utf-8");
      created++;
    } catch (e) {
      console.warn(`[prerender] Failed to create route "${route}":`, e.message);
    }
  }

  console.log(`[prerender] Created ${created} static route folders in dist/.`);
}

prerender();
