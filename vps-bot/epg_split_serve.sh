#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# מגיש את קובצי הלוח הקטנים (אחד לכל ערוץ) דרך /epg/.
#
# למה: דף ערוץ צריך ~19KB ומשך 1.77MB — פי 95 — כי כל 95 הערוצים ישבו בקובץ
# אחד. בסלולר איטי זה כעשר שניות שבהן הלוח פשוט לא מוצג. epg_build.py כבר
# כותב את הקבצים הקטנים ל-/opt/zovex-bot/data/epg; חסרה רק השורה ב-nginx.
#
# הקובץ המלא /epg.json נשאר בדיוק כפי שהוא — לקוחות ישנים ממשיכים לעבוד.
#
# בטוח: מגבה את התצורה · בודק עם nginx -t · משחזר אוטומטית אם הבדיקה נכשלת.
#     bash epg_split_serve.sh
# ─────────────────────────────────────────────────────────────────────────────
set -u
CONF="/etc/nginx/sites-available/zovex"
DIR="/opt/zovex-bot/data/epg"
BAK="${CONF}.bak-epgdir-$(date +%Y%m%d-%H%M%S)"

[ -f "$CONF" ] || { echo "❌ לא נמצא $CONF"; exit 1; }

if grep -q "ZOVEX-EPG-DIR" "$CONF"; then
  echo "✓ כבר מוגדר"
else
  if [ ! -d "$DIR" ]; then
    echo "❌ $DIR לא קיים — הרץ קודם:  python3 /opt/zovex-bot/epg_build.py"
    exit 1
  fi
  cp "$CONF" "$BAK"
  python3 - "$CONF" <<'PY'
import re, sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
BLOCK = '''    # ZOVEX-EPG-DIR — לוח לכל ערוץ בנפרד. דף ערוץ מוריד ~19KB במקום 1.77MB.
    location /epg/ {
        alias /opt/zovex-bot/data/epg/;
        add_header Cache-Control "public, max-age=300" always;
        default_type application/json;
    }
'''
m = re.search(r"\n(\s*)location\s+=\s+/epg\.json\s*\{", s) or re.search(r"\n(\s*)location\s+/\s*\{", s)
if not m:
    print("   ✗ לא נמצא מקום להוסיף — לא שונה כלום"); sys.exit(2)
s = s[:m.start()] + "\n" + BLOCK + s[m.start():]
open(p, "w", encoding="utf-8").write(s)
print("   ✓ נוסף ל-nginx")
PY
  if [ $? -ne 0 ]; then cp "$BAK" "$CONF"; echo "❌ שוחזר הגיבוי"; exit 1; fi
  if nginx -t 2>&1 | grep -q successful; then
    systemctl reload nginx
    echo "   ✓ nginx נטען מחדש"
  else
    cp "$BAK" "$CONF"; systemctl reload nginx 2>/dev/null
    echo "❌ בדיקת nginx נכשלה — שוחזר הגיבוי"; nginx -t; exit 1
  fi
fi

echo
echo "── בדיקה ──"
n=$(ls "$DIR" 2>/dev/null | wc -l)
echo "   קבצים בתיקייה: $n"
for slug in mako12 Dramottorki Hotcinema; do
  printf "   /epg/%-14s " "$slug.json"
  curl -s -o /dev/null -w "%{http_code}  %{size_download} בייט\n" -m 20 \
    "https://zovex.duckdns.org/epg/$slug.json"
done
printf "   /epg.json (מלא)      "
curl -s -o /dev/null -w "%{http_code}  %{size_download} בייט\n" -m 40 \
  "https://zovex.duckdns.org/epg.json"
