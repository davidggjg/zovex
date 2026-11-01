#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · "המשך צפייה" עובד מכל מקום, עם שאלה, ועם עונה ופרק.
#
# דווח: ההמשכה עבדה רק מתוך שורת ההיסטוריה; לחיצה על סרט ממסך הבית או
# מקטגוריה התחילה תמיד מאפס. ובשורת ההיסטוריה עצמה לא הייתה שאלה — וגם
# לא היה אפשר לדעת באיזה פרק עצרת, כי הכרטיס הציג רק את שם הפרק, שבסדרות
# רבות זהה לכל הפרקים.
#
# ## שלושה תיקונים
#
# 1. **נקודת כניסה אחת לנגן.** היו שלוש — כפתור ההפעלה בדף הסרט, לחיצה
#    על פרק בסדרה, ולחיצה מההיסטוריה — וכל אחת התנהגה אחרת. רק האחרונה
#    העבירה מיקום, ולכן ההמשכה עבדה רק משם. כולן עוברות עכשיו דרך
#    playItem.
#
# 2. **דיאלוג שאלה**, כמו באפליקציה: "המשך מ-12:34" או "התחל מההתחלה".
#    הוא מרונדר בשלושת מסכי ה-render, כי לדף הסרט ולדף הסדרה יש return
#    מוקדם משלהם ובלעדיו הוא היה מופיע רק במסך הבית.
#
# 3. **עונה ופרק על הכרטיס** בשורת ההיסטוריה. התווית נוספת כשדה נפרד
#    ואינה דורסת את title, כי ממנו נבנית הכתובת כשאין custom_slug.
#
# המיקום נלקח מההיסטוריה שכבר נטענה — אין קריאת רשת נוספת. פחות מדקה
# אינו "המשך צפייה", וסיום כמעט מלא אינו מצדיק שאלה; בשני המקרים הנגן
# נפתח ישר.
#
#   sudo bash deploy_site_resume2.sh
#   sudo bash deploy_site_resume2.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
TGZ_URL="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/site-resume3.tgz"
SITE_DIR="/opt/zovex-site"
DOMAIN="zovex.duckdns.org"
CATALOG="http://127.0.0.1:8000/content/lite"
WORK="/tmp/zovex-site-resume3.$$"
TS=$(date +%Y%m%d-%H%M%S)
BAK="/opt/zovex-site.bak_resume3_${TS}"

die() { echo "❌ $*" >&2; exit 1; }

if [ "${1:-}" = "--rollback" ]; then
  LAST=$(ls -1dt /opt/zovex-site.bak_resume3_* 2>/dev/null | head -1)
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
