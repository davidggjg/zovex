#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# AppMod · פריסת חנות האפליקציות על ה-VPS (נפרד משרת הסרטים)
#   פורט 8001 · דומיין appmod.duckdns.org · systemd: appmod · תיקייה: /opt/appmod
# הרצה (כ-root):  bash deploy_apps.sh
# הטוקן של הבוט לא שמור ב-Git — תתבקש להזין אותו בפעם הראשונה.
# ─────────────────────────────────────────────────────────────────────────────
set -u
DOMAIN="appmod.duckdns.org"
DIR="/opt/appmod"
PORT="8001"
MOVIE_ENV="/opt/zovex-bot/.env"     # ממנו נשאב API_ID/API_HASH (אותה אפליקציית טלגרם)
RAW="https://raw.githubusercontent.com/davidggjg/zovex/claude/vps-bot-deploy/apps-store"

echo "════════ AppMod · פריסה ════════"
mkdir -p "$DIR/data"

echo "── 1/6 · מוריד קבצים ──"
for f in index.html admin.html apps_service.py; do
  curl -fsSL "$RAW/$f" -o "$DIR/$f" || { echo "❌ הורדת $f נכשלה"; exit 1; }
done

echo "── 2/6 · סביבת פייתון + תלויות ──"
if [ ! -d "$DIR/venv" ]; then python3 -m venv "$DIR/venv"; fi
"$DIR/venv/bin/pip" -q install --upgrade pip
"$DIR/venv/bin/pip" -q install fastapi "uvicorn[standard]" pyrogram tgcrypto

echo "── 3/6 · הגדרות (.env) ──"
if [ ! -f "$DIR/.env" ]; then
  # שואב API_ID/API_HASH מבוט הסרטים (אותה אפליקציית טלגרם — מותר לשתף)
  AID=$(grep -E '^API_ID=' "$MOVIE_ENV" 2>/dev/null | cut -d= -f2-)
  AHASH=$(grep -E '^API_HASH=' "$MOVIE_ENV" 2>/dev/null | cut -d= -f2-)
  [ -z "${AID:-}" ]   && read -rp "API_ID (מ-my.telegram.org): " AID
  [ -z "${AHASH:-}" ] && read -rp "API_HASH: " AHASH
  read -rp "APPS_BOT_TOKEN (הטוקן של בוט האפליקציות): " BTOK
  read -rp "APPS_CHANNEL_ID [-1004358130306]: " CHID; CHID=${CHID:--1004358130306}
  GENPW=$(head -c 12 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 14)
  read -rp "סיסמת פאנל ניהול [$GENPW]: " PPW; PPW=${PPW:-$GENPW}
  cat > "$DIR/.env" <<EOF
APPS_BOT_TOKEN=$BTOK
APPS_API_ID=$AID
APPS_API_HASH=$AHASH
APPS_CHANNEL_ID=$CHID
APPS_PANEL_PASSWORD=$PPW
APPS_PUBLIC_BASE=https://$DOMAIN
APPS_DATA_DIR=$DIR/data
APPS_PORT=$PORT
EOF
  chmod 600 "$DIR/.env"
  echo "   ✅ .env נוצר · סיסמת פאנל: $PPW"
else
  echo "   .env קיים — משאיר כמו שהוא"
fi

echo "── 4/6 · שירות systemd ──"
cat > /etc/systemd/system/appmod.service <<EOF
[Unit]
Description=AppMod apps store
After=network.target
[Service]
WorkingDirectory=$DIR
EnvironmentFile=$DIR/.env
ExecStart=$DIR/venv/bin/uvicorn apps_service:api --host 127.0.0.1 --port $PORT
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable appmod >/dev/null 2>&1
systemctl restart appmod

echo "── 5/6 · nginx + SSL ──"
cat > /etc/nginx/sites-available/appmod <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    location / { proxy_pass http://127.0.0.1:$PORT; proxy_set_header Host \$host;
                 proxy_set_header X-Real-IP \$remote_addr; client_max_body_size 0;
                 proxy_read_timeout 3600s; proxy_buffering off; }
}
EOF
ln -sf /etc/nginx/sites-available/appmod /etc/nginx/sites-enabled/appmod
nginx -t && systemctl reload nginx
# תעודת SSL (אם certbot מותקן)
if command -v certbot >/dev/null 2>&1; then
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m admin@$DOMAIN --redirect || \
    echo "⚠️ certbot נכשל — ודא ש-appmod.duckdns.org מצביע ל-IP הזה ונסה שוב"
fi

echo "── 6/6 · סיום ──"
sleep 2
curl -s "http://127.0.0.1:$PORT/ping" && echo
echo "════════ ✅ AppMod פרוס ════════"
echo "אתר:   https://$DOMAIN"
echo "פאנל:  https://$DOMAIN/apps/admin"
echo "בוט:   שלח APK לערוץ $CHID — הוא יופיע אוטומטית"
