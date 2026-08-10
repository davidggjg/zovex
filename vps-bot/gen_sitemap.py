#!/usr/bin/env python3
# מייצר sitemap.xml + robots.txt לאתר החדש (zovex.duckdns.org) מתוך התוכן החי.
import json, sys, datetime, urllib.request
from urllib.parse import quote

SITE = "https://zovex.duckdns.org"
SITE_DIR = "/opt/zovex-site"

def enc(s):  # דומה ל-encodeURIComponent של JS
    return quote((s or "").replace(" ", "-"), safe="-_.!~*'()")

def load():
    # מקור: ראשית מנסה את ה-API המקומי; אם רץ מחוץ לשרת — קובץ מקומי
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/content", timeout=20) as r:
            return json.load(r)
    except Exception:
        with open(sys.argv[1] if len(sys.argv) > 1 else "content.json", encoding="utf-8") as f:
            return json.load(f)

def build_paths(items):
    paths = [""]  # דף הבית
    seen_series = {}
    seen = set()
    for m in items:
        if m.get("is_live") or m.get("category") == "שידורים חיים":
            slug = m.get("custom_slug") or enc(m.get("title") or m.get("name") or "")
            p = f"live/{slug}"
        elif m.get("series_name"):
            name = m["series_name"]
            if name in seen_series:
                continue
            seen_series[name] = 1
            p = m.get("custom_slug") or enc(name)
        else:
            slug = m.get("custom_slug") or (enc(m.get("title") or "") + "-" + (m.get("id") or "")[:6])
            p = slug
        if p not in seen:
            seen.add(p); paths.append(p)
    return paths

def main():
    items = load()
    paths = build_paths(items)
    today = datetime.date.today().isoformat()
    rows = []
    for p in paths:
        loc = f"{SITE}/{p}" if p else f"{SITE}/"
        pr = "1.0" if not p else "0.7"
        rows.append(f"  <url>\n    <loc>{loc}</loc>\n    <lastmod>{today}</lastmod>\n    <changefreq>daily</changefreq>\n    <priority>{pr}</priority>\n  </url>")
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(rows) + "\n</urlset>\n"
    robots = f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n"
    # בבדיקה מקומית — כותב לתיקייה הנוכחית; בשרת — ל-SITE_DIR
    out = SITE_DIR if len(sys.argv) < 2 else "."
    import os
    open(os.path.join(out, "sitemap.xml"), "w", encoding="utf-8").write(xml)
    open(os.path.join(out, "robots.txt"), "w", encoding="utf-8").write(robots)
    print(f"[sitemap] {len(paths)} URLs -> {out}/sitemap.xml")
    print("[robots] ->", os.path.join(out, "robots.txt"))

if __name__ == "__main__":
    main()
