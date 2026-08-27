#!/usr/bin/env bash
# ── התקנת שירות ה-EPG על השרת ────────────────────────────────────────────
# מתקין את epg_build.py, יוצר טיימר systemd שמרענן את הלוח כל שעתיים, ומריץ
# פעם אחת מיד. השירות הוא oneshot מבודד — הוא *לא* יכול להשפיע על האתר או על
# zovex-bot. הלוח מתפרסם כקובץ סטטי: https://zovex.duckdns.org/epg.json
# הרצה כ-root:  bash epg_deploy.sh
set -euo pipefail

BRANCH="claude/hls-relay-schema-port-ll8xiz"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/epg_build.py"
DEST="/opt/zovex-bot/epg_build.py"

echo "→ מוריד epg_build.py"
curl -fsSL "$RAW" -o "$DEST"
python3 -m py_compile "$DEST" && echo "  ✓ תקין"

echo "→ יוצר יחידות systemd"
cat >/etc/systemd/system/zovex-epg.service <<'UNIT'
[Unit]
Description=ZOVEX EPG builder (writes /opt/zovex-site/epg.json)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /opt/zovex-bot/epg_build.py
# מבודד: כישלון כאן לא נוגע לאתר/לבוט
Nice=10
UNIT

cat >/etc/systemd/system/zovex-epg.timer <<'UNIT'
[Unit]
Description=Refresh ZOVEX EPG every 2h

[Timer]
OnBootSec=2min
OnUnitActiveSec=2h
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now zovex-epg.timer
echo "→ ריצה ראשונה עכשיו"
systemctl start zovex-epg.service
sleep 1

echo "→ בדיקה"
if [ -f /opt/zovex-site/epg.json ]; then
  bytes=$(wc -c </opt/zovex-site/epg.json)
  gen=$(python3 -c "import json;print(len(json.load(open('/opt/zovex-site/epg.json'))['channels']))" 2>/dev/null || echo '?')
  echo "  ✓ epg.json נכתב — $gen ערוצים, $bytes בייטים"
  echo "  ✓ זמין ב:  https://zovex.duckdns.org/epg.json"
else
  echo "  ✗ epg.json לא נוצר — בדוק: journalctl -u zovex-epg.service -n 40"
  exit 1
fi
echo "→ הטיימר הבא:"; systemctl list-timers zovex-epg.timer --no-pager | sed -n '1,2p'
