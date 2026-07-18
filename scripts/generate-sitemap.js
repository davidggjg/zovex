// scripts/generate-sitemap.js
// יוצר אוטומטית public/sitemap.xml מתוך public/movies.json
// רץ בכל build (מחובר ל-package.json בתור prebuild)

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const MOVIES_PATH = path.join(ROOT, "public", "movies.json");
const SITEMAP_PATH = path.join(ROOT, "public", "sitemap.xml");

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

function buildUrls(movies) {
  const urls = new Set();
  urls.add(""); // דף הבית

  const seriesSeen = new Map(); // series_name -> custom_slug (הראשון שנמצא)

  for (const m of movies) {
    if (m.series_name) {
      if (!seriesSeen.has(m.series_name)) {
        seriesSeen.set(m.series_name, m.custom_slug || null);
      }
    } else {
      urls.add(slugifyMovie(m));
    }
  }

  for (const [name, customSlug] of seriesSeen.entries()) {
    urls.add(slugifySeries(name, customSlug));
  }

  return Array.from(urls);
}

function generateSitemap() {
  if (!fs.existsSync(MOVIES_PATH)) {
    console.warn("[sitemap] movies.json not found, skipping sitemap generation.");
    return;
  }

  const raw = fs.readFileSync(MOVIES_PATH, "utf-8");
  let movies;
  try {
    movies = JSON.parse(raw);
  } catch (e) {
    console.error("[sitemap] Failed to parse movies.json:", e.message);
    return;
  }

  if (!Array.isArray(movies)) {
    console.warn("[sitemap] movies.json is not an array, skipping.");
    return;
  }

  const paths = buildUrls(movies);
  const today = new Date().toISOString().split("T")[0];

  const urlEntries = paths
    .map((p) => {
      // תיקון: GitHub Pages מפנה (301) כל כתובת-תיקייה בלי לוכסן בסוף אל
      // הגרסה עם הלוכסן (כי כל route כאן הוא בפועל תיקייה עם index.html
      // בפנים) - אז רושמים כאן ישר את הכתובת עם הלוכסן, כדי שגוגל יגיע
      // ישר ל-200 בלי הפניה מיותרת באמצע.
      const loc = p ? `${SITE_URL}/${p}/` : `${SITE_URL}/`;
      const priority = p ? "0.7" : "1.0";
      return `  <url>\n    <loc>${loc}</loc>\n    <lastmod>${today}</lastmod>\n    <changefreq>daily</changefreq>\n    <priority>${priority}</priority>\n  </url>`;
    })
    .join("\n");

  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urlEntries}\n</urlset>\n`;

  fs.writeFileSync(SITEMAP_PATH, xml, "utf-8");
  console.log(`[sitemap] Generated sitemap.xml with ${paths.length} URLs.`);
}

generateSitemap();
