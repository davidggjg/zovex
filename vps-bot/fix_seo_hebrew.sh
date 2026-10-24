#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · 393 דפי הסרטים והסדרות העבריים הוגשו לגוגל כדף הבית.
#
# ## מה נמדד
#
#   /opt/zovex-site:  393 תיקיות בשם מקודד (%D7%90…),  0 בעברית
#   nginx:            try_files $uri $uri/ /index.html
#
# ‎prerender-routes.js‎ יצר תיקייה בשם ‎encodeURIComponent(כותר)‎, כלומר
# ‎%D7%90%D7%95%D7%99%D7%91-aa551c‎ ממש, עם סימני אחוז בשם הקובץ. אבל כל
# שרת מפענח את הכתובת לפני שהוא פונה לדיסק, ולכן בקשה ל-‎/%D7%90…/‎ חיפשה
# ‎אויב-המדינה-aa551c‎ — שלא נוצרה מעולם. ‎try_files‎ נפל חזרה ל-
# ‎/index.html‎ והגיש את דף הבית **בקוד 200**.
#
# התוצאה לא "דפים חסרים" אלא 393 כפילויות של דף הבית, עם אותה כותרת
# ואותו canonical. זה סיגנל איכות שלילי לכל הדומיין, לא רק לאותם דפים.
#
# ## התיקון
#
# שם התיקייה מפוענח; הכתובת ב-canonical ובסייטמאפ נשארת מקודדת, כי זו
# הצורה שהסורק מבקש. ‎%2F‎ שהיה הופך לקו נטוי, ו-‎..‎ שהיה יוצא מתיקיית
# האתר, נדחים ומדווחים.
#
# ## למה בלי בנייה מחדש
#
# דפי ה-SEO נבנים מ-‎index.html‎ ומהקטלוג בלבד. ‎DIST_DIR‎ מכוון לתיקיית
# האתר החיה, ולכן ‎index.html‎ שבשימוש הוא זה שכבר מוגש — עם שמות קבצי
# ה-JS וה-hash הנכונים שלו. בנייה מחדש הייתה משנה את ה-hash וחייבת פריסה
# מלאה; כאן לא נוגעים באף קובץ בנייה.
#
# nginx אינו נוגע כאן בכלל.
#
#   sudo bash fix_seo_hebrew.sh
#   sudo bash fix_seo_hebrew.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/scripts/prerender-routes.js"
SITE_DIR="/opt/zovex-site"
DOMAIN="zovex.duckdns.org"
CATALOG="http://127.0.0.1:8000/content/lite"
WORK="/tmp/zovex-seo.$$"
BAK="/opt/zovex-site.bak_seo_$(date +%Y%m%d-%H%M%S)"

die() { echo "❌ $*" >&2; exit 1; }
restore() { rm -rf "$SITE_DIR"; cp -a "$1" "$SITE_DIR"; }

if [ "${1:-}" = "--rollback" ]; then
  LAST=$(ls -1dt /opt/zovex-site.bak_seo_* 2>/dev/null | head -1)
  [ -n "$LAST" ] || die "אין גיבוי לשחזר"
  restore "$LAST" || die "השחזור נכשל"
  chown -R www-data:www-data "$SITE_DIR" 2>/dev/null || true
  echo "✅ שוחזר מ-$LAST"
  exit 0
fi

[ -d "$SITE_DIR" ]            || die "$SITE_DIR לא קיים — זה לא השרת הנכון"
[ -f "$SITE_DIR/index.html" ] || die "$SITE_DIR/index.html חסר"
command -v node >/dev/null 2>&1 || die "node לא מותקן. להתקין:
   curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt-get install -y nodejs"

NODE_MAJOR=$(node -p 'process.versions.node.split(".")[0]')
[ "$NODE_MAJOR" -ge 18 ] 2>/dev/null \
  || die "node $NODE_MAJOR מותקן; צריך 18 ומעלה (fetch לקטלוג)"

echo "① הקטלוג מגיע מהשרת המקומי"
curl -fsS -m 120 -o /dev/null "$CATALOG" \
  || die "השרת לא מגיש את $CATALOG — בדוק: systemctl status zovex-bot"

echo "② מוריד את הסקריפט המתוקן"
mkdir -p "$WORK/scripts" || die "לא נוצרה תיקיית עבודה"
trap 'rm -rf "$WORK"' EXIT
curl -fsSL "$RAW" -o "$WORK/scripts/prerender-routes.js" || die "ההורדה נכשלה"
grep -q 'fix_encoded_dirs' "$WORK/scripts/prerender-routes.js" \
  || die "הקובץ שהורד אינו הגרסה המתוקנת — לא נגעתי בכלום"

BEFORE_ENC=$(ls "$SITE_DIR" | grep -c '^%')
BEFORE_HEB=$(ls "$SITE_DIR" | grep -c '^[^ -~]')
echo "   לפני:  מקודדות=$BEFORE_ENC  עבריות=$BEFORE_HEB"

echo "③ מגבה ל-$BAK"
cp -a "$SITE_DIR" "$BAK" || die "הגיבוי נכשל"

echo "④ מייצר מחדש את דפי ה-SEO בתוך תיקיית האתר"
( cd "$WORK" && DIST_DIR="$SITE_DIR" SITE_URL="https://$DOMAIN" \
    CATALOG_URL="$CATALOG" node scripts/prerender-routes.js ) \
  || { restore "$BAK"; die "ה-prerender נכשל — שוחזר"; }

AFTER_HEB=$(ls "$SITE_DIR" | grep -c '^[^ -~]')
echo "   עבריות אחרי: $AFTER_HEB"
[ "$AFTER_HEB" -gt 0 ] || { restore "$BAK"; die "לא נוצרה אף תיקייה עברית — שוחזר"; }

echo "⑤ מוחק את $BEFORE_ENC התיקיות בשם המקודד"
# אחרי היצירה, לא לפניה: כך כשל בשלב ④ משאיר את האתר בדיוק כפי שהיה.
# אלה התיקיות שאף כתובת לא הגיעה אליהן מעולם; הגיבוי מחזיק אותן.
find "$SITE_DIR" -maxdepth 1 -mindepth 1 -type d -name '%*' -exec rm -rf {} + 2>/dev/null
chown -R www-data:www-data "$SITE_DIR" 2>/dev/null || true

echo
echo "⑥ האימות — מה שגוגל יקבל עכשיו על כתובת עברית"
HOME_TITLE=$(curl -ks -m 20 "https://$DOMAIN/" | grep -o '<title>[^<]*</title>' | head -1)
OK=0; BAD=0
for N in $(ls "$SITE_DIR" | grep '^[^ -~]' | shuf -n 5); do
  ENC=$(node -e 'process.stdout.write(encodeURIComponent(process.argv[1]))' "$N")
  T=$(curl -ks -m 20 "https://$DOMAIN/$ENC/" | grep -o '<title>[^<]*</title>' | head -1)
  if [ -n "$T" ] && [ "$T" != "$HOME_TITLE" ]; then
    OK=$((OK+1)); printf '   ✅ %s\n' "$T"
  else
    BAD=$((BAD+1)); printf '   ❌ %s  ->  %s\n' "$N" "${T:-ריק}"
  fi
done

CODE=$(curl -ks -o /dev/null -w '%{http_code}' -m 20 "https://$DOMAIN/")
if [ "$CODE" != "200" ] || [ "$OK" -eq 0 ]; then
  restore "$BAK"; chown -R www-data:www-data "$SITE_DIR" 2>/dev/null || true
  die "דף הבית=$CODE, הצלחות=$OK — שוחזר הגיבוי. שלח לי את הפלט."
fi

cat <<EOF

────────────────────────────────────────────────────────────
✅ נפרס.  $OK מתוך 5 דגימות מגישות את הדף הנכון${BAD:+  (נכשלו: $BAD)}
   עבריות: $BEFORE_HEB → $AFTER_HEB    מקודדות: $BEFORE_ENC → 0

גיבוי:   $BAK
לשחזור:  sudo bash $0 --rollback

עכשיו בגוגל — זה לא קורה מעצמו מהר:
  1. Search Console → Sitemaps → לשלוח מחדש את sitemap.xml
  2. URL Inspection → להדביק 2-3 כתובות של סרטים → Request indexing
  3. Search Console → Pages → לשלוח לי מה כתוב שם
EOF
