#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · פריסת האתר עם שינויי התצוגה.
#
# ## מה השתנה
#
# 1. שלוש בשורה בטלפון במקום שתיים. הרשת השתמשה ב-auto-fill עם רוחב קבוע
#    של 143 פיקסלים, ולכן בכל מסך מתחת ל-460 — כלומר כמעט כל טלפון —
#    נכנסו שתיים בלבד. הרוחב מחושב עכשיו מרוחב המסך: שלוש עמודות קודם,
#    והכרטיס מקבל את מה שנשאר, ביחס הקיים שלו כדי שהפוסטר לא יימתח.
#
# 2. שורה במסך הבית מוגבלת ל-30 פריטים. בלי תקרה שורה אחת נמשכה למאות
#    פריטים, ומסך הבית הגיש את כל הקטלוג למי שעוד לא בחר קטגוריה.
#
# 3. "ראה הכל" בצד השני של חיצי הניווט, ועוד אריח בסוף השורה עצמה — מי
#    שהגיע לקצה בחיצים כבר לא רואה את הכותרת, ובלי האריח היה צריך לגלול
#    חזרה. שניהם פותחים את אותה רשת קטגוריה שכבר קיימת באתר, וגוללים
#    למעלה, אחרת הרשת נפתחת באמצע ונראית כאילו לא קרה כלום.
#
# ## למה הסקריפט הזה ולא site.sh
#
# site.sh כותב מחדש את כל תצורת ה-nginx. התצורה החיה כוללת נתיבים
# (‎/vt/‎, ‎/vh/‎, ‎/emby/‎) שאינם בו, והרצתו הייתה מוחקת אותם. כאן לא
# נוגעים ב-nginx בכלל — רק בקבצי האתר.
#
# ## דפי ה-SEO
#
# הבנייה משנה את ה-hash של קובץ ה-JS, ולכן אי אפשר לפרוס אותה בלי לייצר
# מחדש את דפי הסרטים — כל אחד מהם מצביע על שם הקובץ הישן, שנמחק. לכן
# ה-prerender רץ כאן, מול 127.0.0.1:8000.
#
# זו גם הסיבה שהסקריפט מאמת בסוף דף עברי ולא רק את דף הבית: הפריסה
# הזאת נוגעת באותם 393 דפים שתוקנו זה עתה.
#
# אם אין node, הסקריפט **עוצר ולא נוגע בכלום**.
#
# ## בטיחות
#
# גיבוי מלא לפני כל נגיעה, בדיקה אחרי, ושחזור אוטומטי בכל כשל.
#
#   sudo bash deploy_site_ui.sh
#   sudo bash deploy_site_ui.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
TGZ_URL="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/site-ui.tgz"
SITE_DIR="/opt/zovex-site"
DOMAIN="zovex.duckdns.org"
CATALOG="http://127.0.0.1:8000/content/lite"
WORK="/tmp/zovex-site-ui.$$"
TS=$(date +%Y%m%d-%H%M%S)
BAK="/opt/zovex-site.bak_ui_${TS}"

die() { echo "❌ $*" >&2; exit 1; }

if [ "${1:-}" = "--rollback" ]; then
  LAST=$(ls -1dt /opt/zovex-site.bak_ui_* 2>/dev/null | head -1)
  [ -n "$LAST" ] || die "אין גיבוי לשחזר"
  rm -rf "$SITE_DIR" && cp -a "$LAST" "$SITE_DIR" || die "השחזור נכשל"
  echo "✅ שוחזר מ-$LAST"
  exit 0
fi

[ -d "$SITE_DIR" ] || die "$SITE_DIR לא קיים — זה לא השרת הנכון"

# ── 1. node ─────────────────────────────────────────────────────────────────
PRERENDER=1
[ "${SKIP_PRERENDER:-0}" = "1" ] && PRERENDER=0
if [ "$PRERENDER" = "1" ] && ! command -v node >/dev/null 2>&1; then
  echo "❌ node לא מותקן, ובלעדיו אי אפשר לייצר מחדש את דפי ה-SEO."
  echo "   לא נגעתי בכלום. שתי אפשרויות:"
  echo
  echo "   להתקין node (מומלץ, פעם אחת):"
  echo "     curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt-get install -y nodejs"
  echo
  echo "   או לפרוס בלי דפי ה-SEO, במודע:"
  echo "     SKIP_PRERENDER=1 sudo bash $0"
  exit 1
fi

# ── 2. הורדה ─────────────────────────────────────────────────────────────────
mkdir -p "$WORK" || die "לא נוצרה תיקיית עבודה"
trap 'rm -rf "$WORK"' EXIT
echo "① מוריד את האתר הבנוי"
curl -fsSL "$TGZ_URL" -o "$WORK/site.tgz" || die "ההורדה נכשלה"
tar xzf "$WORK/site.tgz" -C "$WORK" || die "הפריסה מהארכיון נכשלה"
[ -f "$WORK/dist/index.html" ] || die "הארכיון לא מכיל dist/index.html"

# ── 3. prerender ─────────────────────────────────────────────────────────────
if [ "$PRERENDER" = "1" ]; then
  echo "② מייצר דפי SEO מהקטלוג המקומי"
  curl -fsS -m 120 -o /dev/null "$CATALOG" \
    || die "השרת לא מגיש את $CATALOG — בדוק: systemctl status zovex-bot"
  ( cd "$WORK" && SITE_URL="https://$DOMAIN" CATALOG_URL="$CATALOG" \
      node scripts/prerender-routes.js ) || die "ה-prerender נכשל — לא נגעתי באתר"
  PAGES=$(find "$WORK/dist" -mindepth 2 -name index.html 2>/dev/null | wc -l)
  echo "   נוצרו $PAGES דפים"
  [ "$PAGES" -gt 0 ] || die "לא נוצר אף דף SEO — לא נגעתי באתר"
else
  echo "② מדלג על דפי SEO (SKIP_PRERENDER=1)"
fi

# ── 4. החלפה ─────────────────────────────────────────────────────────────────
echo "③ מגבה ל-$BAK"
cp -a "$SITE_DIR" "$BAK" || die "הגיבוי נכשל"
echo "④ מחליף את קבצי האתר"
rm -rf "${SITE_DIR:?}"/* || { rm -rf "$SITE_DIR"; cp -a "$BAK" "$SITE_DIR"; die "הניקוי נכשל — שוחזר"; }
cp -a "$WORK/dist/." "$SITE_DIR/" || { rm -rf "$SITE_DIR"; cp -a "$BAK" "$SITE_DIR"; die "ההעתקה נכשלה — שוחזר"; }
chown -R www-data:www-data "$SITE_DIR" 2>/dev/null || true

# ── 5. בדיקה ─────────────────────────────────────────────────────────────────
echo "⑤ בודק שהאתר עונה"
CODE=$(curl -ks -o /dev/null -w '%{http_code}' -m 20 "https://$DOMAIN/")
if [ "$CODE" != "200" ]; then
  rm -rf "$SITE_DIR"; cp -a "$BAK" "$SITE_DIR"
  die "האתר החזיר $CODE — שוחזר הגיבוי. שלח לי את הפלט."
fi

# דף הבית מוגש גם כשכל דפי הסרטים שבורים — זה בדיוק מה שקרה כאן קודם,
# ולכן בדיקה שלו בלבד אינה בדיקה. אותן דגימות כמו בתיקון ה-SEO.
echo "   בודק דף סרט עברי"
HOME_TITLE=$(curl -ks -m 20 "https://$DOMAIN/" | grep -o '<title>[^<]*</title>' | head -1)
SEO_OK=0
for N in $(ls "$SITE_DIR" | grep '^[^ -~]' | shuf -n 3); do
  ENC=$(node -e 'process.stdout.write(encodeURIComponent(process.argv[1]))' "$N")
  T=$(curl -ks -m 20 "https://$DOMAIN/$ENC/" | grep -o '<title>[^<]*</title>' | head -1)
  if [ -n "$T" ] && [ "$T" != "$HOME_TITLE" ]; then
    SEO_OK=$((SEO_OK+1)); printf '   ✅ %s\n' "$T"
  else
    printf '   ❌ %s  ->  %s\n' "$N" "${T:-ריק}"
  fi
done
if [ "$SEO_OK" -eq 0 ]; then
  rm -rf "$SITE_DIR"; cp -a "$BAK" "$SITE_DIR"
  chown -R www-data:www-data "$SITE_DIR" 2>/dev/null || true
  die "אף דף סרט לא נענה נכון — שוחזר הגיבוי. שלח לי את הפלט."
fi

echo
echo "✅ נפרס. האתר עונה 200."
echo "   גיבוי: $BAK"
echo "   לשחזור:  sudo bash $0 --rollback"
echo
echo "מה לבדוק:"
echo "  · בטלפון, בתוך קטגוריה — שלושה כרטיסים בשורה"
echo "  · במסך הבית — ליד החיצים יש \"ראה הכל\", ובסוף כל שורה אריח כזה"
echo "  · לחיצה עליו פותחת את הקטגוריה וגוללת למעלה"
echo
echo "רענן עם Ctrl+Shift+R (עוקף מטמון). בטלפון — סגור את הלשונית ופתח מחדש."
