#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · הקשחת אבטחה מלאה — פקודה אחת.
#
# סוגר את כל מה שסבב התקיפה האדום מצא ושאפשר לנצל:
#
#   ① IDOR/BOLA  (add_identity_auth.py)
#       ארבעה נתיבים מזהים משתמש לפי מה שהלקוח אומר, בלי אימות:
#       כל אחד קרא/כתב היסטוריה, מועדפים, המשך-צפייה, ו**קרא את כל
#       שיחת התמיכה** של כל משתמש לפי המייל שלו. התיקון מאמת מול
#       גוגל פעם אחת, ואז חתימה מקומית — מדורג, לא שובר אף לקוח.
#
#   ② SSRF + מיצוי זיכרון  (harden_security.py)
#       "למידת מארחים" אוטומטית לא בדקה שהמארח ציבורי → אפשר היה
#       ללמד את השרת כתובת פנימית (metadata של הענן / localhost) והוא
#       היה פונה אליה. התיקון מחיל את _host_is_public הקיים גם על
#       הלמידה, וחוסם את המילון בגודל.
#
#   ③ שכבת nginx (מודפס בסוף — להדבקה ידנית, אפס-סיכון להזרמה):
#       הגבלת גודל גוף בקשה (נגד הפלת זיכרון), כותרות אבטחה,
#       הגבלת קצב על נתיבים ציבוריים.
#
# שום דבר כאן לא נוגע ב-streaming.
#
#   sudo bash deploy_harden.sh
#   sudo bash deploy_harden.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u
DIR=/opt/zovex-bot
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${REF}/vps-bot"
die(){ echo "❌ $*" >&2; exit 1; }
[ -f "$DIR/main.py" ] || die "$DIR/main.py לא קיים"

fetch(){ curl -fsSL -H 'Cache-Control: no-cache' "$RAW/$1?t=$(date +%s)" -o "/tmp/$1" || die "הורדה נכשלה: $1"; }
fetch add_identity_auth.py
fetch harden_security.py

if [ "${1:-}" = "--rollback" ]; then
  MAIN_PY="$DIR/main.py" python3 /tmp/harden_security.py --revert || echo "⚠️ harden כבר לא מוחל"
  MAIN_PY="$DIR/main.py" python3 /tmp/add_identity_auth.py --revert || echo "⚠️ identity כבר לא מוחל"
  python3 -m py_compile "$DIR/main.py" || die "לא מתקמפל אחרי שחזור"
  systemctl restart zovex-bot; echo "✅ שוחזר"; exit 0
fi

# גיבוי מלא לפני הכל
cp -a "$DIR/main.py" "$DIR/main.py.bak_before_harden_$(date +%s)" || die "גיבוי נכשל"

echo "① סוגר IDOR (אימות זהות)"
MAIN_PY="$DIR/main.py" python3 /tmp/add_identity_auth.py || die "טלאי הזהות נכשל"

echo "② סוגר SSRF + הגנת זיכרון"
MAIN_PY="$DIR/main.py" python3 /tmp/harden_security.py || die "טלאי ההקשחה נכשל"

echo "③ אימות קומפילציה"
if ! python3 -m py_compile "$DIR/main.py"; then
  MAIN_PY="$DIR/main.py" python3 /tmp/harden_security.py --revert
  MAIN_PY="$DIR/main.py" python3 /tmp/add_identity_auth.py --revert
  die "לא מתקמפל — שוחזר"
fi

echo "④ מפעיל מחדש"
systemctl restart zovex-bot || die "restart נכשל"
sleep 8
systemctl is-active --quiet zovex-bot || { journalctl -u zovex-bot -n 30 --no-pager; die "השרת אינו פעיל — בצע --rollback"; }

echo "⑤ בדיקת בריאות"
code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "http://127.0.0.1:8000/ping")
echo "   /ping → $code"
[ "$code" = "200" ] && echo "   ✅ השרת חי" || echo "   ⚠️ /ping לא 200 — בדוק ידנית"

cat <<'NGINX'

────────────────────────────────────────────────────────────────────────────
③ שכבת nginx — להדבקה ידנית בקובץ ה-site (למשל /etc/nginx/sites-enabled/zovex)
   זה חוסם הפלת-זיכרון דרך גוף בקשה ענק, מוסיף כותרות אבטחה, ומגביל קצב —
   הכל ברמת ה-proxy, בלי שום נגיעה בהזרמת הווידאו.

# ── בראש הקובץ (מחוץ ל-server), פעם אחת: ──
limit_req_zone $binary_remote_addr zone=zovex_public:10m rate=30r/m;

# ── בתוך בלוק server: ──

  # כותרות אבטחה (always = גם על שגיאות)
  add_header X-Content-Type-Options "nosniff" always;
  add_header X-Frame-Options "DENY" always;
  add_header Referrer-Policy "no-referrer" always;
  # HSTS — רק אם האתר כולו ב-HTTPS (זה המצב):
  add_header Strict-Transport-Security "max-age=15552000" always;

  # גוף גדול מותר רק להעלאות (מאומתות); השאר קטן:
  client_max_body_size 4g;

  location /feedback/ {
    client_max_body_size 1m;
    limit_req zone=zovex_public burst=10 nodelay;
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  }

  location /api/ {
    client_max_body_size 1m;
    limit_req zone=zovex_public burst=20 nodelay;
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  }

# אחרי העריכה:  sudo nginx -t && sudo systemctl reload nginx
# אם יש לך כבר location /api/ או /feedback/ — מזג את 3 השורות (limit/body)
# פנימה במקום להוסיף בלוק כפול.
────────────────────────────────────────────────────────────────────────────
NGINX

echo
echo "✅ שתי הפרצות הקריטיות סגורות בשרת. השלם את קטע ה-nginx למעלה."
echo "   לחזרה מלאה:  sudo bash $0 --rollback"
