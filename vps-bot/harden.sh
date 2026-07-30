#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · הקשחת אבטחה לשרת (Ubuntu). הרץ כ-root:
#     bash harden.sh
# בטוח: פותח SSH ראשון לפני הפעלת חומת האש, כדי לא לנעול אותך בחוץ.
# ─────────────────────────────────────────────────────────────────────────────
set -u
echo "════════ ZOVEX hardening ════════"

echo "── 1/4 · חומת אש (ufw): SSH + 8000 בלבד ──"
apt-get update -y >/dev/null 2>&1 || true
apt-get install -y ufw fail2ban unattended-upgrades >/dev/null 2>&1 || true
ufw allow 22/tcp        >/dev/null 2>&1   # SSH — קודם כל, שלא תינעל
ufw allow OpenSSH       >/dev/null 2>&1 || true
ufw allow 8000/tcp      >/dev/null 2>&1   # השרת של zovex
ufw default deny incoming  >/dev/null 2>&1
ufw default allow outgoing >/dev/null 2>&1
yes | ufw enable        >/dev/null 2>&1
echo "   חומת אש פעילה:"; ufw status | sed 's/^/     /'

echo "── 2/4 · fail2ban (חוסם ניחוש סיסמת SSH) ──"
cat >/etc/fail2ban/jail.d/zovex.conf <<'EOF'
[sshd]
enabled  = true
maxretry = 5
findtime = 10m
bantime  = 1h
EOF
systemctl enable --now fail2ban >/dev/null 2>&1
systemctl restart fail2ban       >/dev/null 2>&1
echo "   fail2ban פעיל."

echo "── 3/4 · עדכוני אבטחה אוטומטיים ──"
echo 'Unattended-Upgrade::Automatic-Reboot "false";' >/etc/apt/apt.conf.d/51zovex-noreboot 2>/dev/null || true
dpkg-reconfigure -f noninteractive unattended-upgrades >/dev/null 2>&1 || true
echo "   מופעל."

echo "── 4/4 · סיסמת פאנל חזקה (PANEL_PASSWORD) ──"
NEWPASS="$(openssl rand -base64 15 2>/dev/null || head -c 12 /dev/urandom | base64)"
if [ -f /opt/zovex-bot/.env ]; then
  sed -i '/^PANEL_PASSWORD=/d' /opt/zovex-bot/.env
  echo "PANEL_PASSWORD=$NEWPASS" >> /opt/zovex-bot/.env
  echo ""
  echo "   ★★★ סיסמת הפאנל החדשה (רשום אותה עכשיו!) ★★★"
  echo "   ┌───────────────────────────────────────────┐"
  echo "     $NEWPASS"
  echo "   └───────────────────────────────────────────┘"
  systemctl restart zovex-bot >/dev/null 2>&1 || true
  echo "   השרת הופעל מחדש עם הסיסמה החדשה."
else
  echo "   ⚠️ לא נמצא /opt/zovex-bot/.env — דלגתי על שינוי הסיסמה."
fi

echo ""
echo "════════ סיום ════════"
echo "נשאר לך לעשות ידנית (חשוב):"
echo "  1) שנה את סיסמת root:   passwd"
echo "  2) הפעל 2FA בפאנל FutureIL."
echo "  3) שקול להפעיל הגנת hotlink: הוסף ל-.env שורה"
echo "       HOTLINK_REFERERS=davidggjg.github.io,zovex1.netlify.app,213.139.78.39"
echo "     ואז: systemctl restart zovex-bot"
