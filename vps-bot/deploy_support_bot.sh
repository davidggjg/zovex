#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · התקנת בוט התמיכה כשירות נפרד.
#
# שירות משלו ולא טלאי ל-main.py: אם התמיכה תיפול אסור שההזרמה תיפול
# איתה, ולהפך. אין תלויות חדשות ואין נגיעה ב-venv.
#
# הבוט מגשר גם על צ'אט התמיכה הקיים של האתר והאפליקציה: פנייה משם
# נכנסת לאותה קבוצה, ותשובה בקבוצה חוזרת לצ'אט של המשתמש דרך
# POST /feedback/reply — הנתיב שגם שולח לו את ההתראה לטלפון. ולכן
# הוא צריך PANEL_PASSWORD, ש-main.py כבר מחזיק באותו .env.
#
# אין שינוי ב-main.py, באתר, באפליקציה או ב-nginx.
#
# דורש ב-/opt/zovex-bot/.env:
#   SUPPORT_BOT_TOKEN=...
#   SUPPORT_GROUP_ID=-1004491660594
#
#   sudo bash deploy_support_bot.sh
#   sudo bash deploy_support_bot.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u
DIR=/opt/zovex-bot
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/support_bot.py"
UNIT=/etc/systemd/system/zovex-support.service
die(){ echo "❌ $*" >&2; exit 1; }

[ -d "$DIR" ] || die "$DIR לא קיים — זה לא שרת ZOVEX"

if [ "${1:-}" = "--rollback" ]; then
  systemctl disable --now zovex-support 2>/dev/null
  rm -f "$UNIT"; systemctl daemon-reload
  echo "✅ השירות הוסר. support_bot.py ו-support_state.json נשארו ב-$DIR"
  exit 0
fi

grep -q '^SUPPORT_BOT_TOKEN=.\+' "$DIR/.env" || die "SUPPORT_BOT_TOKEN חסר ב-$DIR/.env"
grep -q '^PANEL_PASSWORD=.\+' "$DIR/.env" || die "PANEL_PASSWORD חסר ב-$DIR/.env — בלעדיו אי אפשר להחזיר תשובה לצ'אט של האתר"
if ! grep -q '^SUPPORT_GROUP_ID=.\+' "$DIR/.env"; then
  echo "SUPPORT_GROUP_ID=-1004491660594" >> "$DIR/.env"
  echo "   SUPPORT_GROUP_ID נכתב"
fi
chmod 600 "$DIR/.env"

echo "① מוריד את הקוד"
curl -fsSL "$RAW" -o "$DIR/support_bot.py" || die "ההורדה נכשלה"
python3 -m py_compile "$DIR/support_bot.py" || die "הקוד לא מתקמפל"

echo "② כותב יחידת systemd"
cat > "$UNIT" <<UEOF
[Unit]
Description=ZOVEX support bridge bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$DIR
EnvironmentFile=$DIR/.env
ExecStart=/usr/bin/python3 $DIR/support_bot.py
Restart=always
RestartSec=5
# תקרה צנועה: זה בוט טקסט. אם הוא יזלוג, הוא לא ייקח את ההזרמה איתו.
MemoryMax=192M
Nice=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UEOF
systemctl daemon-reload
systemctl enable --now zovex-support || die "ההפעלה נכשלה"

echo "③ בודק"
sleep 6
systemctl is-active --quiet zovex-support || { journalctl -u zovex-support -n 30 --no-pager; die "השירות אינו פעיל"; }
curl -fsS --max-time 5 http://127.0.0.1:8107/health && echo
journalctl -u zovex-support -n 8 --no-pager
echo
echo "✅ בוט התמיכה פעיל."
echo "   בדיקה 1: כתוב /ping בקבוצה — הבוט יענה שם עם מצבו."
echo "   בדיקה 2: כתוב הודעה לבוט בטלגרם — היא תופיע בקבוצה עם כפתורים."
echo "   בדיקה 3: כתוב בצ'אט התמיכה באתר — הפנייה תופיע באותה קבוצה,"
echo "            ותגובה עליה בקבוצה תחזור לצ'אט באתר ותשלח התראה לטלפון."
echo
echo "   יומן חי:  journalctl -u zovex-support -f"
