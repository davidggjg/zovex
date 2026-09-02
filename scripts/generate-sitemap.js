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

// build:vps כבר מייצא SITE_URL, אבל איש לא קרא אותו — הערך היה
// מקודד קשיח, והדפים שנוצרו הצביעו על אתר ה-GitHub Pages שנסגר.
const SITE_URL = process.env.SITE_URL || "https://zovex.duckdns.org";
const CATALOG_URL = process.env.CATALOG_URL || "https://zovex.duckdns.org/content/lite";

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

// טעינת הקטלוג. עד עכשיו, קובץ חסר גרם ל"skipping" שקט — והבנייה הצליחה
// והפיקה dist בלי אף דף ייעודי. מכיוון שהפריסה מוחקת את כל תיקיית האתר
// לפני שהיא פורסת, בנייה כזאת מוחקת בשקט אלפי דפי נחיתה מגוגל. לכן אם
// הקובץ המקומי חסר, מושכים את הקטלוג מהאתר החי במקום לוותר.
async function loadCatalog(tag) {
  if (fs.existsSync(MOVIES_PATH)) {
    try {
      const arr = JSON.parse(fs.readFileSync(MOVIES_PATH, "utf-8"));
      if (Array.isArray(arr)) return arr;
      console.warn(`[${tag}] movies.json אינו מערך — מנסה למשוך מהאתר`);
    } catch (e) {
      console.warn(`[${tag}] movies.json פגום (${e.message}) — מנסה למשוך מהאתר`);
    }
  }
  try {
    console.log(`[${tag}] מושך קטלוג מ-${CATALOG_URL}`);
    const res = await fetch(CATALOG_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const arr = await res.json();
    if (!Array.isArray(arr)) throw new Error("התשובה אינה מערך");
    console.log(`[${tag}] התקבלו ${arr.length} פריטים`);
    return arr;
  } catch (e) {
    console.error(`[${tag}] לא ניתן לטעון קטלוג: ${e.message}`);
    return null;
  }
}

async function generateSitemap() {
  const movies = await loadCatalog("sitemap");
  if (!movies) return;

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

await generateSitemap();
