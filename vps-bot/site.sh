#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · פריסת האתר על השרת. zovex.duckdns.org יציג את האתר עצמו, וה-API
# (סטרימינג/תוכן/היסטוריה/פאנל) ימשיך לרוץ על אותו שרת דרך nginx. הרץ כ-root:
#     bash site.sh
# ─────────────────────────────────────────────────────────────────────────────
set -u
DOMAIN="zovex.duckdns.org"
SITE_DIR="/opt/zovex-site"
TGZ_URL="https://raw.githubusercontent.com/davidggjg/zovex/claude/vps-bot-deploy/vps-bot/site.tgz"
echo "════════ ZOVEX · פריסת אתר ════════"

echo "── 1/3 · מוריד ופורס את קבצי האתר ──"
mkdir -p "$SITE_DIR"
if ! curl -fsSL "$TGZ_URL" -o /tmp/zovex-site.tgz; then echo "❌ הורדת site.tgz נכשלה"; exit 1; fi
find "$SITE_DIR" -mindepth 1 -delete 2>/dev/null
tar xzf /tmp/zovex-site.tgz -C "$SITE_DIR"
echo "   נפרס ל-$SITE_DIR"

echo "── 2/3 · מגדיר nginx (אתר ב-/, API לבוט) ──"
cat >/etc/nginx/snippets/zovex-proxy.conf <<'EOF'
proxy_pass http://127.0.0.1:8000;
proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
EOF
cat >/etc/nginx/snippets/zovex-stream.conf <<'EOF'
proxy_pass http://127.0.0.1:8000;
proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_buffering off;
proxy_request_buffering off;
proxy_read_timeout 3600s;
proxy_send_timeout 3600s;
EOF

cat >/etc/nginx/sites-available/zovex <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    return 301 https://\$host\$request_uri;
}
server {
    listen 443 ssl;
    server_name $DOMAIN;
    ssl_certificate     /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;
    client_max_body_size 0;
    root $SITE_DIR;
    index index.html;

    # דחיסה — רק לטקסט/JSON (לא לוידאו!). מקטין את /content פי ~10 → טעינה מהירה.
    gzip on;
    gzip_proxied any;
    gzip_min_length 1024;
    gzip_comp_level 5;
    gzip_types application/json application/javascript text/css text/plain image/svg+xml application/xml;

    # ── API → הבוט (uvicorn 127.0.0.1:8000) ──
    location /stream/      { include snippets/zovex-stream.conf; }
    location /hls-relay/   { include snippets/zovex-stream.conf; }
    location /speedtest    { include snippets/zovex-stream.conf; }
    location /content      { include snippets/zovex-proxy.conf; }
    location = /movies.json { include snippets/zovex-proxy.conf; }
    location /api/         { include snippets/zovex-proxy.conf; }
    location /admin        { include snippets/zovex-proxy.conf; }
    location /panel        { include snippets/zovex-proxy.conf; }
    location /uploads/     { include snippets/zovex-proxy.conf; }
    location = /ping       { include snippets/zovex-proxy.conf; }
    location = /restart    { include snippets/zovex-proxy.conf; }
    location = /dashboard  { include snippets/zovex-proxy.conf; }

    # ── נכסים ישנים עם קידומת /zovex/ (למשל לוגו של שידור חי) ──
    location /zovex/ { alias $SITE_DIR/; }

    # ── האתר (SPA) — כל השאר ──
    location / { try_files \$uri \$uri/ /index.html; }
}
EOF
ln -sf /etc/nginx/sites-available/zovex /etc/nginx/sites-enabled/zovex
rm -f /etc/nginx/sites-enabled/default
if nginx -t; then systemctl reload nginx; else echo "❌ שגיאת nginx config"; exit 1; fi

echo "── 3/3 · סיום ──"
echo "════════ ✅ האתר פרוס ════════"
echo "פתח בדפדפן:  https://$DOMAIN     ← האתר עצמו"
echo "דשבורד הבוט:  https://$DOMAIN/dashboard"
echo "פאנל ניהול:   https://$DOMAIN/admin"
