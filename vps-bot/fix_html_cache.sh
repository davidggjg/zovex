#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# מתקן מחלקת תקלות שחוזרת בכל פריסת אתר: "מסך לבן שאי אפשר לעבור".
#
# מה קורה: ל-vite יש שם קובץ ייחודי לכל בנייה (index-<hash>.js), וכל פריסה
# מוחקת את הישן. index.html מוגש בלי Cache-Control, ולכן הדפדפן שומר אותו
# לפי היוריסטיקה שלו — ואחרי פריסה הוא מבקש נכס שכבר נמחק, מקבל 404, ונתקע
# על מסך לבן. רענון רגיל לא עוזר, כי ה-HTML הישן עצמו עדיין במטמון.
#
# התיקון: HTML (2KB בסך הכל) יאומת מול השרת בכל טעינה. הנכסים עצמם לא
# מושפעים — שמם מכיל hash שמשתנה בכל בנייה, ולכן הם ממילא בטוחים למטמון.
#
# בטוח: מגבה · בודק עם nginx -t · משחזר אוטומטית אם הבדיקה נכשלת.
#     bash fix_html_cache.sh
# ─────────────────────────────────────────────────────────────────────────────
set -u
CONF="/etc/nginx/sites-available/zovex"
BAK="${CONF}.bak-cache-$(date +%Y%m%d-%H%M%S)"

[ -f "$CONF" ] || { echo "❌ לא נמצא $CONF"; exit 1; }

if grep -q "ZOVEX-HTML-NOCACHE" "$CONF"; then
  echo "✓ כבר מוחל — לא שונה כלום"
  exit 0
fi

cp "$CONF" "$BAK"
echo "גיבוי: $(basename "$BAK")"

python3 - "$CONF" <<'PY'
import re, sys
path = sys.argv[1]
s = open(path, encoding="utf-8").read()

NEW = '''location / {
        try_files $uri $uri/ /index.html;
        # ZOVEX-HTML-NOCACHE — בלי זה פריסה חדשה משאירה דפדפנים עם HTML ישן
        # שמפנה לנכס שנמחק: 404 ומסך לבן שרענון לא מתקן.
        add_header Cache-Control "no-cache, must-revalidate" always;
    }'''

pat = re.compile(r"location\s+/\s*\{\s*try_files\s+\$uri\s+\$uri/\s+/index\.html;\s*\}")
if not pat.search(s):
    print("  ✗ לא נמצא הבלוק 'location /' הצפוי — לא שונה כלום")
    sys.exit(2)

s = pat.sub(NEW, s, count=1)
open(path, "w", encoding="utf-8").write(s)
print("  התצורה עודכנה")
PY

if [ $? -ne 0 ]; then
  cp "$BAK" "$CONF"
  echo "❌ לא הוחל — הגיבוי שוחזר"
  exit 1
fi

if nginx -t 2>&1 | grep -q "successful"; then
  systemctl reload nginx
  echo "✓ nginx נטען מחדש"
  echo
  echo "── בדיקה ──"
  curl -sI https://zovex.duckdns.org/ | grep -i "cache-control" || echo "  (עדיין לא מופיע)"
else
  cp "$BAK" "$CONF"
  systemctl reload nginx 2>/dev/null
  echo "❌ בדיקת nginx נכשלה — הגיבוי שוחזר, לא שונה כלום"
  nginx -t
  exit 1
fi
