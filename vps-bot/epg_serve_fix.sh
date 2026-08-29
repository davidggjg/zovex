#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# מוציא את לוח השידורים מתיקיית האתר, כדי שפריסות לא ימחקו אותו.
#
# מה קרה: epg_build.py כתב את epg.json לתוך /opt/zovex-site, וכל פריסת אתר
# מריצה `find /opt/zovex-site -mindepth 1 -delete` — כלומר מוחקת את הלוח.
# אחרי המחיקה nginx נופל ל-try_files ומחזיר את index.html בתשובה ל-/epg.json,
# כך שהאתר "מקבל 200" אבל בלי נתונים — וכל הלוחות נראים ריקים.
#
# התיקון: הלוח נשמר ב-/opt/zovex-bot/data (מחוץ לתיקיית האתר), ו-nginx מגיש
# אותו דרך location ייעודי. פריסות אתר כבר לא נוגעות בו.
#
# בטוח: מגבה את תצורת nginx · בודק עם nginx -t · משחזר אם הבדיקה נכשלת.
#     bash epg_serve_fix.sh
# ─────────────────────────────────────────────────────────────────────────────
set -u
CONF="/etc/nginx/sites-available/zovex"
BAK="${CONF}.bak-epg-$(date +%Y%m%d-%H%M%S)"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/claude/hls-relay-schema-port-ll8xiz/vps-bot/epg_build.py"

[ -f "$CONF" ] || { echo "❌ לא נמצא $CONF"; exit 1; }

echo "── 1/3 · מעדכן את בונה הלוח ──"
curl -fsSL "$RAW" -o /opt/zovex-bot/epg_build.py || { echo "❌ הורדה נכשלה"; exit 1; }
python3 -m py_compile /opt/zovex-bot/epg_build.py || { echo "❌ הקובץ לא תקין"; exit 1; }
echo "   ✓ תקין"

echo "── 2/3 · מגדיר ל-nginx להגיש את הלוח מהמיקום החדש ──"
if grep -q "ZOVEX-EPG-ALIAS" "$CONF"; then
  echo "   ✓ כבר מוגדר"
else
  cp "$CONF" "$BAK"
  python3 - "$CONF" <<'PY'
import re, sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
BLOCK = '''    # ZOVEX-EPG-ALIAS — הלוח יושב מחוץ לתיקיית האתר כדי לשרוד פריסות.
    location = /epg.json {
        alias /opt/zovex-bot/data/epg.json;
        add_header Cache-Control "no-cache" always;
        default_type application/json;
    }
'''
# מוסיפים לפני location / כדי שההתאמה המדויקת תקדם לו
m = re.search(r"\n(\s*)location\s+/\s*\{", s)
if not m:
    print("   ✗ לא נמצא 'location /' — לא שונה כלום"); sys.exit(2)
s = s[:m.start()] + "\n" + BLOCK + s[m.start():]
open(p, "w", encoding="utf-8").write(s)
print("   ✓ נוסף ל-nginx")
PY
  if [ $? -ne 0 ]; then cp "$BAK" "$CONF"; echo "❌ שוחזר הגיבוי"; exit 1; fi
  if nginx -t 2>&1 | grep -q successful; then
    systemctl reload nginx
  else
    cp "$BAK" "$CONF"; systemctl reload nginx 2>/dev/null
    echo "❌ בדיקת nginx נכשלה — שוחזר הגיבוי"; nginx -t; exit 1
  fi
fi

echo "── 3/3 · בונה את הלוח מחדש ──"
mkdir -p /opt/zovex-bot/data
systemctl start zovex-epg.service
sleep 3
if [ -s /opt/zovex-bot/data/epg.json ]; then
  echo "   ✓ נכתב ($(du -h /opt/zovex-bot/data/epg.json | cut -f1))"
else
  echo "   ⏳ עדיין נבנה — נסה שוב בעוד דקה"
fi

echo
echo "── בדיקה ──"
curl -s --max-time 20 "https://zovex.duckdns.org/epg.json" | head -c 60
echo
