#!/usr/bin/env bash
# setup_chat_nginx.sh — מוסיף את /chat/ לאתר, מעל HTTPS הקיים.
#
# למה זה עדיף מפורט חשוף: אין צורך לפתוח פורט בחומת האש, מקבלים את
# תעודת ה-TLS של האתר בחינם, וזה עובד מכל רשת — כולל רשתות שחוסמות
# פורטים לא סטנדרטיים (וזה כנראה מה שהחזיר ERR_EMPTY_RESPONSE).
#
#   bash setup_chat_nginx.sh            # מוסיף
#   bash setup_chat_nginx.sh --remove   # מסיר
#
# reload של nginx הוא הדרגתי: חיבורים פתוחים ממשיכים כרגיל.
# הוא לא מנתק צופים, בניגוד ל-restart של zovex-bot.

set -euo pipefail
PORT="${IMG_PORT:-8099}"
MARK="# zovex-imagechat"
ANCHOR="root /opt/zovex-site;"

# מאתרים את קובץ ה-server block לפי העוגן הייחודי. לא מניחים שם קובץ:
# בשרת הזה כבר ראינו שההנחות לא תמיד נכונות.
CONF=$(grep -rl -- "$ANCHOR" /etc/nginx/sites-enabled /etc/nginx/conf.d 2>/dev/null | head -1)
[ -n "$CONF" ] || { echo "לא מצאתי קובץ nginx עם '$ANCHOR'"; exit 1; }
echo "קובץ: $CONF"

if [ "${1:-}" = "--remove" ]; then
  grep -q -- "$MARK" "$CONF" || { echo "לא מותקן, אין מה להסיר."; exit 0; }
  cp -a "$CONF" "$CONF.bak_chat_rm"
  python3 - "$CONF" "$MARK" <<'PY'
import re, sys
path, mark = sys.argv[1], sys.argv[2]
s = open(path, encoding="utf-8").read()
m = re.escape(mark)
# בולעים גם את שורת הריק ואת ההזחה שלפני הסימון ואחרי הסיום, אחרת
# ההסרה משאירה שאריות וההזחה של השורה הבאה נשברת. revert שלא מחזיר
# את הקובץ בדיוק כפי שהיה הוא לא revert.
s, n = re.subn(r"\n+[ \t]*" + m + r" begin\b.*?" + m + r" end[ \t]*(?=\n)",
               "", s, flags=re.S)
if n == 0:
    sys.exit("✗ לא נמצא הבלוק להסרה")
open(path, "w", encoding="utf-8").write(s)
PY
  nginx -t && systemctl reload nginx && echo "✓ הוסר ו-nginx נטען מחדש"
  exit 0
fi

if grep -q -- "$MARK" "$CONF"; then
  echo "✓ כבר מותקן. לשינוי פורט: הסר קודם עם --remove"
  exit 0
fi

# בודקים שהשירות באמת עונה לפני שמפנים אליו תעבורה
if ! curl -fsS -m 5 -o /dev/null "http://127.0.0.1:$PORT/"; then
  echo "⚠ אין תשובה מ-127.0.0.1:$PORT — imagechat.py לא רץ?"
  echo "  הפעל אותו קודם, אחרת /chat יחזיר 502."
  echo "  להמשיך בכל זאת:  FORCE=1 bash $0"
  [ "${FORCE:-}" = "1" ] || exit 1
fi

cp -a "$CONF" "$CONF.bak_chat"
echo "גיבוי: $CONF.bak_chat"

BLOCK=$(cat <<EOF

    $MARK begin
    # /chat → /chat/ : הדף משתמש בכתובות יחסיות, ובלי הסלאש הסוגר
    # הדפדפן היה פותר אותן מול שורש האתר ומקבל 404.
    location = /chat { return 301 /chat/; }
    location /chat/ {
        # הסלאש בסוף proxy_pass מסיר את הקידומת: /chat/api/gen → /api/gen
        proxy_pass http://127.0.0.1:$PORT/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        # יצירת תמונה לוקחת שניות; ברירת המחדל של 60 שניות מספיקה
        # אבל מודל איטי עם הרבה צעדים יכול לחרוג.
        proxy_read_timeout 180s;
        proxy_send_timeout 180s;
        client_max_body_size 1m;
    }
    $MARK end
EOF
)

python3 - "$CONF" "$ANCHOR" "$BLOCK" <<'PY'
import sys
path, anchor, block = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(path, encoding="utf-8").read()
n = s.count(anchor)
if n != 1:
    sys.exit(f"✗ העוגן מופיע {n} פעמים — לא נוגעים בקובץ")
s = s.replace(anchor, anchor + "\n" + block, 1)
open(path, "w", encoding="utf-8").write(s)
PY

if ! nginx -t; then
  cp -a "$CONF.bak_chat" "$CONF"
  echo "✗ בדיקת nginx נכשלה — הקובץ שוחזר, לא בוצע reload"
  exit 1
fi

systemctl reload nginx
echo
echo "✓ מוכן:  https://zovex.duckdns.org/chat/"
echo "  (reload הדרגתי — צופים פעילים לא נותקו)"
