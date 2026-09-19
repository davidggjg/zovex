#!/bin/bash
# fix_spa_fallback — קישורים ישירים לסרט/פרק מחזירים 404. שורה אחת ב-nginx.
#
# ## מה שבור
#
#   /zovex/                    200   יש index
#   /zovex/coraline            301   התיקייה קיימת (פרירנדר)
#   /zovex/coraline/watch      404   ← זה
#
# בקונפיג:
#
#     location /zovex/ { alias /opt/zovex-site/; }     ← בלי try_files
#     ...
#     location / { try_files $uri $uri/ /index.html; } ← ה-fallback כאן
#
# nginx בוחר את ה-location הספציפי ביותר, ולכן /zovex/ תופס את הבקשה ובלוק
# ה-/ לעולם לא מגיע. אין נפילה-אחורה, ולכן כל נתיב שאין לו קובץ או תיקייה
# מחזיר 404.
#
# ## למה זה נראה כאילו זה עובד
#
# האתר משנה את הכתובת ב-window.history.replaceState, שרק כותב לשורת
# הכתובת ולא מנווט. כל עוד גולשים באתר הכל תקין. זה נשבר בדיוק כשמישהו
# פותח את הקישור מאפס או מרענן — כלומר בשיתוף, שזה כל הטעם שלו.
#
# ## התיקון
#
#     location /zovex/ {
#         alias /opt/zovex-site/;
#         try_files $uri $uri/ /zovex/index.html;
#     }
#
# הפרירנדר נשמר: $uri ו-$uri/ עדיין מוגשים קודם, כך ש-/zovex/coraline
# ממשיך להגיש את העמוד שנוצר לו ל-SEO. רק מה שאין לו קובץ נופל ל-index,
# ומשם ה-router של האתר מטפל.
#
# ## בטיחות
#
# שגיאה בקונפיג של nginx מפילה את **כל** האתר, ולכן:
#   • גיבוי מחוץ ל-sites-enabled. גיבוי *בתוך* התיקייה נטען כשרת נוסף עם
#     אותו server_name — זו טעות שכבר נעשתה כאן פעם.
#   • nginx -t לפני כל reload. נכשל → משחזר ולא נוגע בשרת החי.
#   • אימות בפועל אחרי ה-reload, לא הנחה.
#
#     bash fix_spa_fallback.sh --check
#     bash fix_spa_fallback.sh
#     bash fix_spa_fallback.sh --revert

set -u
CONF=${NGINX_CONF:-/etc/nginx/sites-enabled/zovex}
BAK=/root/zovex-nginx.bak_spa          # מחוץ ל-sites-enabled, בכוונה
OLD='location /zovex/ { alias /opt/zovex-site/; }'
NEW='location /zovex/ {
        alias /opt/zovex-site/;
        # ראה fix_spa_fallback.sh: בלי זה כל קישור ישיר לסרט או לפרק
        # מחזיר 404, כי ה-location הזה תופס את הבקשה ובלוק / לא מגיע.
        # הפרירנדר נשמר — $uri ו-$uri/ עדיין קודמים.
        try_files $uri $uri/ /zovex/index.html;
    }'

check_urls() {
    echo "  בדיקה בפועל:"
    for u in / /zovex/ /zovex/coraline /zovex/coraline/watch; do
        code=$(curl -s -o /dev/null -m 15 -w '%{http_code}' "https://zovex.duckdns.org$u")
        printf "    %-26s %s\n" "$u" "$code"
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

# הקובץ שנערך חייב להיות זה ש-nginx באמת משתמש בו. יש כאן יותר מקובץ אחד
# עם אותו server_name, ו-nginx לוקח את הראשון שנטען — עריכה של השני היא
# עבודה שלא משנה כלום, וזה כבר קרה כאן.
ACTIVE=$(nginx -T 2>/dev/null | grep -B2 "server_name zovex.duckdns.org" \
         | grep -m1 "configuration file" | sed 's/.*configuration file //;s/:$//')
if [ -n "$ACTIVE" ] && [ "$ACTIVE" != "$CONF" ]; then
    echo "⚠️  nginx משתמש בפועל ב-$ACTIVE ולא ב-$CONF."
    echo "    הרץ שוב עם:  NGINX_CONF=$ACTIVE bash $0 ${1:-}"
    exit 1
fi

if grep -q "try_files .* /zovex/index.html" "$CONF"; then
    echo "כבר מותקן. אין מה לעשות."
    check_urls
    exit 0
fi

n=$(grep -c -F "$OLD" "$CONF")
if [ "$n" != "1" ]; then
    echo "❌ העוגן נמצא $n פעמים (ציפיתי 1) — הקונפיג שונה ממה שציפיתי."
    echo "   השורה שחיפשתי:"
    echo "     $OLD"
    echo "   מה שיש בקובץ:"
    grep -n "location /zovex/" "$CONF" || echo "     (לא נמצא כלל)"
    exit 1
fi

echo "יעד:   $CONF"
echo "שינוי: הוספת try_files לבלוק /zovex/ (הפרירנדר נשמר)"
if [ "${1:-}" = "--check" ]; then
    echo "--check: שום דבר לא נכתב."
    check_urls
    exit 0
fi

cp "$CONF" "$BAK"
python3 - "$CONF" "$OLD" "$NEW" <<'PY'
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
echo "  אמור להיות: / 200 · /zovex/ 200 · /zovex/coraline 301 · .../watch 200"
echo "  לביטול: bash fix_spa_fallback.sh --revert"
