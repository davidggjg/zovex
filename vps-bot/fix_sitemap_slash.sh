#!/bin/bash
# fix_sitemap_slash — כתובת של קובץ עם לוכסן בסוף תגיע לקובץ, לא לדף הבית.
#
# ## מה שבור
#
# Search Console מדווח "לא ניתן היה לקרוא את ה-sitemap", 0 דפים. הקובץ
# עצמו תקין לגמרי — נמדד:
#
#     /sitemap.xml      200  text/xml    258,970B   ← 1,436 כתובות
#     /sitemap.xml/     200  text/html     3,906B   ← דף הבית!
#
# הלוכסן בסוף הופך את זה לנתיב שאין לו קובץ, ואז ה-SPA fallback — אותו
# try_files שהוספנו כדי שקישורים ישירים לסרטים יעבדו — מחזיר index.html.
# גוגל מקבל HTML במקום XML ואומר שלא הצליח לקרוא. הוא כן הוריד משהו; זה
# פשוט לא היה sitemap.
#
# וזה לא נפתר בהגשה מחדש: הממשק מוסיף את הלוכסן בעצמו.
#
# ## התיקון
#
#     location ~ ^(/.*\.[A-Za-z0-9]{1,8})/$ {
#         return 301 $1$is_args$args;
#     }
#
# כל נתיב שנגמר ב-<שם>.<סיומת>/ מופנה לקובץ עצמו. גוגל עוקב אחרי 301
# ומקבל את ה-XML.
#
# כלל רגקס ולא כלל לקובץ אחד, כי אותה תקלה בדיוק חלה על robots.txt,
# על תמונות, ועל כל קובץ שמישהו ידביק עם לוכסן. וזה לא מפריע למסלולי
# האתר: מסלול רגיל כמו /coraline/watch אינו נגמר בנקודה+סיומת.
#
# ## בטיחות
#
# שגיאה בקונפיג של nginx מפילה את **כל** האתר, ולכן:
#   • גיבוי מחוץ ל-sites-enabled. גיבוי *בתוך* התיקייה נטען כשרת נוסף
#     עם אותו server_name — טעות שכבר נעשתה כאן פעם.
#   • nginx -t לפני כל reload. נכשל → משחזר ולא נוגע בשרת החי.
#   • אימות בפועל אחרי ה-reload, לא הנחה.
#
#     bash fix_sitemap_slash.sh --check
#     bash fix_sitemap_slash.sh
#     bash fix_sitemap_slash.sh --revert

set -u
CONF=${NGINX_CONF:-/etc/nginx/sites-enabled/zovex}
BAK=/root/zovex-nginx.bak_sitemap_slash    # מחוץ ל-sites-enabled, בכוונה
MARK='is_args$args;'

# העוגן: הבלוק שהוסיף fix_spa_fallback. אם הוא לא שם, גם התקלה הזאת לא
# קיימת — כי בלי fallback הכתובת הייתה מחזירה 404 ולא דף הבית.
ANCHOR='    location /zovex/ {'
NEW='    # ראה fix_sitemap_slash.sh: /sitemap.xml/ עם לוכסן נופל ל-SPA
    # fallback ומחזיר index.html, וגוגל מקבל HTML במקום XML. כל נתיב
    # שנגמר בשם+סיומת ולוכסן מופנה לקובץ עצמו.
    location ~ "^(/.*\\.[A-Za-z0-9]{1,8})/$" {
        return 301 $1$is_args$args;
    }

    location /zovex/ {'

check_urls() {
    echo "  בדיקה בפועל:"
    for u in /sitemap.xml /sitemap.xml/ /robots.txt/ /coraline/watch; do
        out=$(curl -s -o /dev/null -m 20 -w '%{http_code} %{content_type}' \
              -L "https://zovex.duckdns.org$u")
        printf "    %-22s %s\n" "$u" "$out"
    done
}

if [ "${1:-}" = "--revert" ]; then
    [ -f "$BAK" ] || { echo "❌ אין גיבוי ב-$BAK"; exit 1; }
    cp "$BAK" "$CONF"
    if nginx -t 2>/dev/null; then
        systemctl reload nginx && echo "✓ שוחזר ונטען"
    else
        echo "❌ הקונפיג המשוחזר לא תקין — לא טוען. בדוק ידנית."; exit 1
    fi
    exit 0
fi

[ -f "$CONF" ] || { echo "❌ לא נמצא $CONF"; exit 1; }

# הקובץ שנערך חייב להיות זה ש-nginx באמת משתמש בו. יש כאן יותר מקובץ
# אחד עם אותו server_name, ו-nginx לוקח את הראשון שנטען.
ACTIVE=$(nginx -T 2>/dev/null | grep -B2 "server_name zovex.duckdns.org" \
         | grep -m1 "configuration file" | sed 's/.*configuration file //;s/:$//')
if [ -n "$ACTIVE" ] && [ "$ACTIVE" != "$CONF" ]; then
    echo "⚠️  nginx משתמש בפועל ב-$ACTIVE ולא ב-$CONF."
    echo "    הרץ שוב עם:  NGINX_CONF=$ACTIVE bash $0 ${1:-}"
    exit 1
fi

if grep -qF "$MARK" "$CONF"; then
    echo "כבר מותקן. אין מה לעשות."
    check_urls
    exit 0
fi

n=$(grep -c -F "$ANCHOR" "$CONF")
if [ "$n" != "1" ]; then
    echo "❌ העוגן נמצא $n פעמים (ציפיתי 1) — הקונפיג שונה ממה שציפיתי."
    echo "   השורה שחיפשתי:"
    echo "     $ANCHOR"
    grep -n "location /zovex/" "$CONF" || echo "     (לא נמצא כלל)"
    exit 1
fi

echo "יעד:   $CONF"
echo "שינוי: נתיב של קובץ עם לוכסן בסוף → 301 לקובץ עצמו"
if [ "${1:-}" = "--check" ]; then
    echo "--check: שום דבר לא נכתב."
    check_urls
    exit 0
fi

cp "$CONF" "$BAK"
python3 - "$CONF" "$ANCHOR" "$NEW" <<'PY'
import sys
path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(path, encoding="utf-8").read()
assert s.count(old) == 1
open(path, "w", encoding="utf-8").write(s.replace(old, new, 1))
PY

if ! nginx -t 2>&1 | tail -2; then
    cp "$BAK" "$CONF"
    echo "❌ nginx -t נכשל — שוחזר, השרת לא נגעו בו."
    exit 1
fi

systemctl reload nginx || { cp "$BAK" "$CONF"; systemctl reload nginx; \
    echo "❌ ה-reload נכשל — שוחזר."; exit 1; }

echo "✓ הוחל · גיבוי: $BAK"
sleep 2
check_urls
echo
echo "  אמור להיות: שתי השורות הראשונות 200 text/xml"
echo "  (‎-L עוקב אחרי ההפניה, בדיוק כמו גוגל)"
echo "  לביטול: bash fix_sitemap_slash.sh --revert"
