#!/usr/bin/env node
// scripts/scan.js
// Run with: npm run scan
// Scans public/movies.json and public/live.json, reports issues and stats.

import { readFileSync, writeFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dir = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dir, "..");

const PROXY_BASE = process.env.VITE_TELEGRAM_PROXY || "https://telegram-bot-8528.onrender.com";

// ─── helpers ────────────────────────────────────────────────────────────────
function load(file) {
  try {
    return JSON.parse(readFileSync(resolve(ROOT, "public", file), "utf8"));
  } catch {
    console.error(`  ✗ לא ניתן לקרוא ${file}`);
    return null;
  }
}

function save(file, data) {
  writeFileSync(resolve(ROOT, "public", file), JSON.stringify(data, null, 2), "utf8");
}

function classify(movie) {
  const vid = (movie.video_id || movie.video_url || "").trim();
  const type = movie.type || "direct";
  if (!vid) return "empty";
  if (vid.startsWith("ttps://") || vid.startsWith("htps://")) return "broken-url";
  if (vid.includes("t.me")) return "telegram-embed";
  if (vid.includes(PROXY_BASE) || vid.includes("onrender.com/stream")) return "telegram-proxy";
  if (vid.includes(".m3u8") || vid.includes("Manifest.ism")) return "hls";
  if (type === "kaltura" || vid.match(/^\d+\/\d+\/[a-zA-Z0-9_]+$/)) return "kaltura";
  if (type === "youtube" || vid.includes("youtube.com") || vid.includes("youtu.be")) return "youtube";
  if (type === "drive" || vid.includes("drive.google.com")) return "drive";
  if (type === "dailymotion" || vid.includes("dailymotion.com")) return "dailymotion";
  if (type === "vimeo" || vid.includes("vimeo.com")) return "vimeo";
  if (type === "streamable" || vid.includes("streamable.com")) return "streamable";
  if (type === "rumble" || vid.includes("rumble.com")) return "rumble";
  if (type === "archive" || vid.includes("archive.org")) return "archive";
  if (type === "okru" || vid.includes("ok.ru")) return "okru";
  if (type === "kan" || vid.includes("kan.org.il")) return "kan";
  if (type === "jellyfin") return "jellyfin";
  if (vid.startsWith("http")) return "direct";
  return "unknown";
}

// ─── scan ────────────────────────────────────────────────────────────────────
function scanMovies(movies, fix = false) {
  const stats = {};
  const issues = [];
  const fixed = [];

  for (const m of movies) {
    const kind = classify(m);
    stats[kind] = (stats[kind] || 0) + 1;

    if (kind === "empty") {
      issues.push(`[ריק]     "${m.title}" (id: ${m.id}) — אין קישור וידאו`);
    }

    if (kind === "unknown") {
      issues.push(`[לא ידוע] "${m.title}" — video_url: ${m.video_url}`);
    }

    if (kind === "broken-url") {
      issues.push(`[קישור שבור] "${m.title}" — חסרה ה: ${m.video_url}`);
      if (fix) {
        const fixedUrl = (m.video_url || "").replace(/^ttps:\/\//, "https://").replace(/^htps:\/\//, "https://");
        m.video_url = fixedUrl;
        if (m.video_id) m.video_id = fixedUrl;
        fixed.push(`  ✔ "${m.title}" URL תוקן → ${fixedUrl}`);
      }
    }

    // Auto-fix: old t.me/NUMERIC/msgid → proxy URL
    if (fix && kind === "telegram-embed") {
      const vid = (m.video_id || m.video_url || "").trim();
      const tgId = vid.replace(/.*t\.me\//, "");
      const [chan, msg] = tgId.split("/");
      if (msg && /^\d+$/.test(chan)) {
        const newUrl = `${PROXY_BASE}/stream/${chan}/${msg}`;
        m.video_url = newUrl;
        m.video_id = newUrl;
        m.type = "direct";
        fixed.push(`  ✔ "${m.title}" → ${newUrl}`);
      }
    }
  }

  return { stats, issues, fixed };
}

// ─── main ────────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
const doFix = args.includes("--fix");

console.log("\n═══════════════════════════════════");
console.log("  ZOVEX — סריקת קבצי מדיה");
console.log("═══════════════════════════════════\n");

// movies.json
const movies = load("movies.json");
if (movies) {
  const { stats, issues, fixed } = scanMovies(movies, doFix);

  console.log(`📁 movies.json — סה"כ: ${movies.length} רשומות\n`);
  console.log("  סוגי וידאו:");
  for (const [kind, count] of Object.entries(stats).sort((a, b) => b[1] - a[1])) {
    const bar = "█".repeat(Math.min(count, 40));
    console.log(`    ${kind.padEnd(18)} ${String(count).padStart(5)}  ${bar}`);
  }

  if (issues.length) {
    console.log(`\n  ⚠️  בעיות שנמצאו (${issues.length}):`);
    issues.forEach(i => console.log("    " + i));
  } else {
    console.log("\n  ✅ לא נמצאו בעיות");
  }

  if (doFix) {
    if (fixed.length) {
      console.log(`\n  🔧 תוקנו ${fixed.length} רשומות טלגרם:`);
      fixed.forEach(f => console.log(f));
      save("movies.json", movies);
      console.log("\n  💾 movies.json נשמר");
    } else {
      console.log("\n  ℹ️  אין מה לתקן");
    }
  } else if ((stats["telegram-embed"] || 0) > 0) {
    console.log(`\n  💡 נמצאו ${stats["telegram-embed"]} קישורי t.me ישנים.`);
    console.log("     הרץ: npm run scan -- --fix  כדי להמיר אותם אוטומטית לפרוקסי");
  }
}

// live.json
const live = load("live.json");
if (live) {
  const liveList = Array.isArray(live) ? live : [live];
  console.log(`\n📡 live.json — ${liveList.length} ערוצים`);
  for (const ch of liveList) {
    if (ch.url || ch.video_url) {
      const url = ch.url || ch.video_url;
      const kind = url.includes(".m3u8") ? "HLS" : "iframe";
      console.log(`   ${kind.padEnd(6)} "${ch.title || "ללא שם"}" — ${url.slice(0, 60)}…`);
    }
  }
}

console.log("\n═══════════════════════════════════\n");
