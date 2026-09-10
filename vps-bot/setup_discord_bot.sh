#!/usr/bin/env bash
# מתקין ומריץ את בוט הברוך-הבא של דיסקורד כשירות systemd.
#
# לפני שמריצים — צריך ליצור בוט בדיסקורד ולקבל טוקן:
#   1. https://discord.com/developers/applications → New Application → קרא לו ZOVEX.
#   2. לשונית "Bot" → Reset Token → העתק את הטוקן.
#   3. באותו מסך, גלול ל-"Privileged Gateway Intents" והדלק את
#      "SERVER MEMBERS INTENT" (בלעדיו הבוט לא יראה כניסות — קריטי).
#   4. לשונית "OAuth2" → URL Generator → סמן scope "bot" והרשאה
#      "Send Messages" → העתק את הקישור, פתח אותו, והזמן את הבוט לשרת שלך.
#
# ואז מריצים על השרת:
#   sudo DISCORD_TOKEN='<הטוקן שהעתקת>' bash setup_discord_bot.sh
#   (אפשר גם להוסיף DISCORD_WELCOME_CHANNEL='welcome' אם רוצים ערוץ מסוים)
set -euo pipefail

APP_DIR=/opt/zovex-discord
ENV_FILE=/etc/zovex-discord.env
UNIT=/etc/systemd/system/zovex-discord.service
SRC="$(cd "$(dirname "$0")" && pwd)/discord_welcome.py"

[[ $EUID -eq 0 ]] || { echo "❌ צריך root (sudo)"; exit 1; }
[[ -f "$SRC" ]] || { echo "❌ discord_welcome.py לא נמצא ליד הסקריפט"; exit 1; }

# הטוקן: מהסביבה, או משאירים את מה שכבר בקובץ ה-env אם קיים
TOKEN="${DISCORD_TOKEN:-}"
if [[ -z "$TOKEN" && -f "$ENV_FILE" ]] && grep -q '^DISCORD_TOKEN=' "$ENV_FILE"; then
  echo "משתמש בטוקן הקיים ב-$ENV_FILE"
else
  [[ -n "$TOKEN" ]] || { echo "❌ הגדר DISCORD_TOKEN='...' לפני ההרצה"; exit 1; }
fi

mkdir -p "$APP_DIR"
cp "$SRC" "$APP_DIR/discord_welcome.py"

# venv + discord.py (מבודד, לא נוגע ב-python של המערכת)
if [[ ! -d "$APP_DIR/venv" ]]; then
  python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install -q -U pip discord.py

# קובץ סביבה עם הטוקן (הרשאות 600 — רק root קורא)
if [[ -n "$TOKEN" ]]; then
  {
    echo "DISCORD_TOKEN=$TOKEN"
    [[ -n "${DISCORD_WELCOME_CHANNEL:-}" ]] && echo "DISCORD_WELCOME_CHANNEL=$DISCORD_WELCOME_CHANNEL"
    [[ -n "${DISCORD_WELCOME_TEXT:-}" ]] && echo "DISCORD_WELCOME_TEXT=$DISCORD_WELCOME_TEXT"
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

cat > "$UNIT" <<EOF
[Unit]
Description=ZOVEX Discord welcome bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/discord_welcome.py
Restart=always
RestartSec=10
# הקשחה קלה
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_DIR

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now zovex-discord.service
sleep 3
echo "── סטטוס ──"
systemctl is-active --quiet zovex-discord && echo "✓ הבוט רץ" || echo "✗ לא עלה"
echo "לוג:  journalctl -u zovex-discord -n 20 --no-pager"
journalctl -u zovex-discord -n 8 --no-pager 2>/dev/null || true
