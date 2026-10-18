#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · פריסת האתר עם תיקון הביצועים (AmbientGlow).
#
# ## מה זה מתקן
#
# שכבת הזוהר שמאחורי התוכן ציירה שלושה עיגולים עם filter: blur(72px),
# באנימציה אינסופית ששינתה להם קנה מידה. המידה היא vmax, ולכן במסך 1920
# כל עיגול הוא 1574 פיקסלים מול 692 בטלפון — פי חמישה שטח, כפול שלושה,
# ומטושטש מחדש בכל פריים. זה נגבה כל הזמן, גם כשאיש לא נוגע בכלום, וזה
# מה שהפך את האתר לתקוע דווקא במחשב: גלילה נתקעת, לחיצות בדיליי,
# ושידורים מגמגמים כי הווידאו מתחרה על אותו GPU.
#
# ## למה הסקריפט הזה ולא site.sh
#
# site.sh כותב מחדש את כל תצורת ה-nginx. התצורה החיה כוללת נתיבים
# (‎/vt/‎, ‎/vh/‎, ‎/emby/‎) שאינם בו, והרצתו הייתה מוחקת אותם. כאן לא
# נוגעים ב-nginx בכלל — רק בקבצי האתר.
#
# ## דפי ה-SEO
#
# לכל סרט וסדרה יש תיקייה עם index.html משלה, שמצביעה על שם קובץ ה-JS
# עם ה-hash. build חדש משנה את ה-hash, ולכן פריסה בלי יצירה מחדש הייתה
# משאירה אלפי דפים שמצביעים על קובץ מחוק. הסקריפט מריץ את ה-prerender
# כאן, מול 127.0.0.1:8000 — השרת מגיע לעצמו גם כשהאתר חסום מבחוץ.
#
# אם אין node, הסקריפט **עוצר ולא נוגע בכלום** ואומר איך להתקין. הוא לא
# יפרוס אתר בלי דפי ה-SEO בלי שתחליט על זה.
#
# ## בטיחות
#
# גיבוי מלא לפני כל נגיעה, בדיקה שהאתר עונה 200 אחרי, ושחזור אוטומטי
# בכל כשל.
#
#   sudo bash deploy_site_perf.sh
#   sudo bash deploy_site_perf.sh --rollback
#   SKIP_PRERENDER=1 sudo bash deploy_site_perf.sh    # בלי דפי SEO, במודע
# ─────────────────────────────────────────────────────────────────────────────
set -u

BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
TGZ_URL="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/site-perf.tgz"
SITE_DIR="/opt/zovex-site"
DOMAIN="zovex.duckdns.org"
CATALOG="http://127.0.0.1:8000/content/lite"
WORK="/tmp/zovex-site-deploy.$$"
TS=$(date +%Y%m%d-%H%M%S)
BAK="/opt/zovex-site.bak_${TS}"

die() { echo "❌ $*" >&2; exit 1; }

if [ "${1:-}" = "--rollback" ]; then
  LAST=$(ls -1dt /opt/zovex-site.bak_* 2>/dev/null | head -1)
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

echo
echo "✅ נפרס. האתר עונה 200."
echo "   גיבוי: $BAK"
echo "   לשחזור:  sudo bash $0 --rollback"
echo
echo "עכשיו רענן את האתר במחשב עם Ctrl+Shift+R (רענון שעוקף מטמון)."
