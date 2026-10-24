#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · מייצר מחדש את sitemap.xml מול הקטלוג החי.
#
# ה-prerender רץ בכל פריסה ויצר 3,374 דפים, אבל מחולל הסייטמאפ כתב
# לתיקיית הקוד ולא לתיקיית האתר, ולכן נפרס רק כתוצר לוואי של בנייה מלאה.
# התוצאה: 2,394 כתובות במפה מול 3,374 דפים קיימים — כ-980 דפי נחיתה
# שגוגל לא מקבל אליהם שום הפניה.
#
# הסייטמאפ נגזר מהקטלוג בלבד, ולכן אין כאן בנייה ואין פריסה — רק קובץ אחד.
#
#   sudo bash refresh_sitemap.sh
# ─────────────────────────────────────────────────────────────────────────────
set -u

BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/scripts/generate-sitemap.js"
SITE_DIR="/opt/zovex-site"
DOMAIN="zovex.duckdns.org"
CATALOG="http://127.0.0.1:8000/content/lite"
WORK="/tmp/zovex-sitemap.$$"

die() { echo "❌ $*" >&2; exit 1; }

[ -d "$SITE_DIR" ] || die "$SITE_DIR לא קיים"
command -v node >/dev/null 2>&1 || die "node לא מותקן"

BEFORE=$(grep -c '<loc>' "$SITE_DIR/sitemap.xml" 2>/dev/null || echo 0)
PAGES=$(find "$SITE_DIR" -mindepth 2 -maxdepth 2 -name index.html | wc -l)
echo "① לפני:  $BEFORE כתובות במפה,  $PAGES דפים בדיסק"

mkdir -p "$WORK/scripts" "$WORK/public" || die "לא נוצרה תיקיית עבודה"
trap 'rm -rf "$WORK"' EXIT
curl -fsSL "$RAW" -o "$WORK/scripts/generate-sitemap.js" || die "ההורדה נכשלה"
grep -q 'process.env.SITEMAP_PATH' "$WORK/scripts/generate-sitemap.js" \
  || die "הקובץ שהורד אינו הגרסה שתומכת ב-SITEMAP_PATH — לא נגעתי בכלום"

echo "② מייצר לקובץ זמני"
# לקובץ זמני ולא ישירות על החי: כשל באמצע הכתיבה היה משאיר XML קטוע,
# וגוגל פוסל סייטמאפ פגום כולו.
( cd "$WORK" && SITEMAP_PATH="$WORK/out.xml" SITE_URL="https://$DOMAIN" \
    CATALOG_URL="$CATALOG" node scripts/generate-sitemap.js ) \
  || die "היצירה נכשלה — לא נגעתי בקובץ החי"

[ -s "$WORK/out.xml" ] || die "הקובץ שנוצר ריק — לא נגעתי בקובץ החי"
AFTER=$(grep -c '<loc>' "$WORK/out.xml")
grep -q '</urlset>' "$WORK/out.xml" || die "ה-XML קטוע — לא נגעתי בקובץ החי"
[ "$AFTER" -ge "$BEFORE" ] \
  || die "המפה החדשה קטנה מהישנה ($AFTER < $BEFORE) — לא נגעתי בכלום. שלח לי את זה."

cp -a "$SITE_DIR/sitemap.xml" "$SITE_DIR/sitemap.xml.bak" 2>/dev/null || true
cp "$WORK/out.xml" "$SITE_DIR/sitemap.xml" || die "ההעתקה נכשלה"
chown www-data:www-data "$SITE_DIR/sitemap.xml" 2>/dev/null || true

CODE=$(curl -ks -o /dev/null -w '%{http_code}' -m 20 "https://$DOMAIN/sitemap.xml")
LIVE=$(curl -ks -m 30 "https://$DOMAIN/sitemap.xml" | grep -c '<loc>')
echo
echo "③ אחרי:  $LIVE כתובות,  HTTP $CODE"
[ "$CODE" = "200" ] || die "הסייטמאפ מחזיר $CODE"
echo "✅ $BEFORE → $LIVE"
