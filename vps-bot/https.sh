#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · הפעלת HTTPS על השרת (nginx reverse-proxy + Let's Encrypt חינם).
# מיועד לדומיין zovex.duckdns.org שמצביע ל-IP של השרת. הרץ כ-root:
#     bash https.sh
# ─────────────────────────────────────────────────────────────────────────────
set -u
DOMAIN="zovex.duckdns.org"
EMAIL="david.batish1@gmail.com"     # ← לשינוי אם צריך (לצורך התראות חידוש תעודה)
echo "════════ ZOVEX · HTTPS עבור $DOMAIN ════════"

echo "── 1/5 · פותח 80/443 בחומת האש ──"
ufw allow 80/tcp  >/dev/null 2>&1
ufw allow 443/tcp >/dev/null 2>&1

echo "── 2/5 · מתקין nginx + certbot ──"
apt-get update -y >/dev/null 2>&1
apt-get install -y nginx certbot python3-certbot-nginx >/dev/null 2>&1

echo "── 3/5 · מגדיר reverse-proxy אל 127.0.0.1:8000 ──"
cat >/etc/nginx/sites-available/zovex <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    client_max_body_size 0;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        # סטרימינג: בלי buffering, timeouts ארוכים
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
EOF
ln -sf /etc/nginx/sites-available/zovex /etc/nginx/sites-enabled/zovex
rm -f /etc/nginx/sites-enabled/default
if nginx -t; then systemctl reload nginx; else echo "❌ שגיאת nginx config"; exit 1; fi

echo "── 4/5 · תעודת HTTPS (Let's Encrypt) + הפניה מ-http ──"
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect
CERT_RC=$?

echo "── 5/5 · חידוש אוטומטי ──"
systemctl enable --now certbot.timer >/dev/null 2>&1

echo ""
if [ $CERT_RC -eq 0 ]; then
  echo "════════ ✅ HTTPS פעיל ════════"
  echo "בדוק בדפדפן:  https://$DOMAIN/ping"
  echo ""
  echo "נשאר צעד אחד — הפניית כל הקישורים לדומיין (שורה אחת, בזכות %BASE%):"
  echo "  sed -i '/^STREAM_PUBLIC_BASE=/d' /opt/zovex-bot/.env"
  echo "  echo 'STREAM_PUBLIC_BASE=https://$DOMAIN' >> /opt/zovex-bot/.env"
  echo "  systemctl restart zovex-bot"
else
  echo "⚠️ הוצאת התעודה נכשלה. ודא ש-$DOMAIN מצביע ל-IP הזה ושפורט 80 פתוח,"
  echo "   ואז הרץ שוב:  certbot --nginx -d $DOMAIN --agree-tos -m $EMAIL --redirect"
fi
