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

// פריט בלי שם **וגם** בלי custom_slug מייצר כתובת כמו ‎/-a3987a/‎ —
// המזהה בלבד, בלי שום מילה. נמדד על הקטלוג החי: 10 כאלה, וכולם היו
// בסייטמאפ. דף בלי כותר אינו דף נחיתה, והגשתו לגוגל רק שוחקת את
// תקציב הסריקה של האתר. הם מדווחים בסוף ההרצה כדי שאפשר יהיה לתקן
// אותם בפאנל.
function isIndexable(m) {
  return !!((m.custom_slug || "").trim() || (m.title || "").trim());
}

function buildUrls(movies) {
  // Map ולא Set: לכל כתובת נשמרת גם התמונה שלה, ל-image sitemap.
  const urls = new Map();
  urls.set("", null); // דף הבית

  const seriesSeen = new Map();  // series_name -> {slug, image}
  const skipped = [];

  for (const m of movies) {
    if (m.series_name) {
      if (!seriesSeen.has(m.series_name)) {
        seriesSeen.set(m.series_name, {
          slug: m.custom_slug || null,
          image: (m.thumbnail_url || "").trim() || null,
        });
      } else if (!seriesSeen.get(m.series_name).image && m.thumbnail_url) {
        // הפרק הראשון לא תמיד נושא פוסטר; לוקחים את הראשון שכן
        seriesSeen.get(m.series_name).image = m.thumbnail_url.trim();
      }
    } else if (!isIndexable(m)) {
      skipped.push((m.id || "").slice(0, 8));
    } else {
      urls.set(slugifyMovie(m), (m.thumbnail_url || "").trim() || null);
    }
  }

  for (const [name, info] of seriesSeen.entries()) {
    urls.set(slugifySeries(name, info.slug), info.image);
  }

  if (skipped.length) {
    console.warn(`[sitemap] ${skipped.length} פריטים ללא שם דולגו ` +
                 `(כתובת כמו /-xxxxxx/): ${skipped.slice(0, 10).join(", ")}`);
  }
  return urls;
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

  const urlMap = buildUrls(movies);
  const paths = Array.from(urlMap.keys());
  const today = new Date().toISOString().split("T")[0];

  // ‎&‎ ו-‎<‎ בכתובת תמונה שוברים את ה-XML, והסייטמאפ כולו נפסל אז.
  const xmlEsc = (s) =>
    String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
             .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  let withImage = 0;
  const urlEntries = paths
    .map((p) => {
      // תיקון: GitHub Pages מפנה (301) כל כתובת-תיקייה בלי לוכסן בסוף אל
      // הגרסה עם הלוכסן (כי כל route כאן הוא בפועל תיקייה עם index.html
      // בפנים) - אז רושמים כאן ישר את הכתובת עם הלוכסן, כדי שגוגל יגיע
      // ישר ל-200 בלי הפניה מיותרת באמצע.
      const loc = p ? `${SITE_URL}/${p}/` : `${SITE_URL}/`;
      const priority = p ? "0.7" : "1.0";
      // גוגל תמונות אינו סורק ‎og:image‎ כאות אינדוקס — הוא מצפה
      // ל-‎<image:image>‎ בסייטמאפ. בלעדיו הפוסטרים אינם מופיעים
      // בחיפוש תמונות, גם כשהם מוגשים בכל עמוד.
      const img = urlMap.get(p);
      let imgTag = "";
      if (img && /^https?:\/\//i.test(img)) {
        withImage++;
        imgTag = `\n    <image:image>\n      <image:loc>${xmlEsc(img)}</image:loc>\n    </image:image>`;
      }
      return `  <url>\n    <loc>${loc}</loc>\n    <lastmod>${today}</lastmod>\n    <changefreq>daily</changefreq>\n    <priority>${priority}</priority>${imgTag}\n  </url>`;
    })
    .join("\n");

  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n${urlEntries}\n</urlset>\n`;

  fs.writeFileSync(SITEMAP_PATH, xml, "utf-8");
  console.log(`[sitemap] Generated sitemap.xml with ${paths.length} URLs, ` +
              `${withImage} of them with an image.`);
}

await generateSitemap();
