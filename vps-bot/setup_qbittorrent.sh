#!/usr/bin/env bash
# מתקין ומגדיר qbittorrent-nox עם WebUI על השרת.
#
# ## למה זה בנוי כך
#
# על השרת הזה כבר רצים nginx (80/443), הבוט (8000) ושרת ה-Go (8099).
# לכן הסקריפט **סוקר קודם ולא נוגע בכלום**, ועוצר אם משהו מתנגש. הוא גם
# לא רץ כ-root: משתמש ייעודי בלי shell, שאין לו גישה ל-/opt/zovex-bot.
#
# ## מה נבדק לפני
#
#   • שזו אובונטו/דביאן                    • כמה מקום פנוי בדיסק
#   • איזה פורט פנוי ל-WebUI                • מצב חומת האש
#   • שאין qbittorrent שכבר מותקן ורץ
#
# ## חילוץ אוטומטי
#
# ל-qBittorrent אין מחלץ מובנה — לא unrar ולא unzip. מה שכן קיים הוא
# "הרצת תוכנית חיצונית בסיום", וזה המנגנון שדרכו אנשים מחברים unrar.
# הוא מוגדר כאן במפורש כבוי (AutoRun\enabled=false), כך שהקבצים נשארים
# בדיוק כפי שירדו.
#
# ## הדיסק
#
# 30GB זה מעט. לכן: תיקיית "בהורדה" נפרדת מ"הושלם", תור שמגביל כמה
# יורדים במקביל, יחס שיתוף שעוצר זריעה אינסופית, ושומר-דיסק שרץ כל חמש
# דקות ומשהה הכל אם נשאר פחות מ-3GB. בלי האחרון, דיסק מלא היה מפיל גם
# את האתר ואת ההעלאות — הם על אותו דיסק.
#
#     bash setup_qbittorrent.sh --check    # רק סוקר. לא משנה כלום
#     bash setup_qbittorrent.sh            # מתקין ומגדיר
#     bash setup_qbittorrent.sh --remove   # מסיר הכל
set -uo pipefail

QBT_USER=qbt
QBT_HOME=/home/qbt
DL_ROOT=/home/torrents
WANT_PORT=8080
MIN_FREE_GB=5          # פחות מזה — לא מתקינים בכלל
GUARD_FREE_GB=3        # פחות מזה — משהים את כל ההורדות
CONF="$QBT_HOME/.config/qBittorrent/qBittorrent.conf"

say()  { printf '%s\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m⚠\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31m❌ %s\033[0m\n' "$*"; exit 1; }

[[ $EUID -eq 0 ]] || die "צריך להריץ כ-root"

# ── הסרה ──────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--remove" ]]; then
  say "מסיר…"
  systemctl disable --now qbittorrent-nox.service 2>/dev/null
  systemctl disable --now qbt-diskguard.timer 2>/dev/null
  rm -f /etc/systemd/system/qbittorrent-nox.service \
        /etc/systemd/system/qbt-diskguard.{service,timer} \
        /usr/local/bin/qbt-diskguard.sh
  systemctl daemon-reload
  apt-get -y remove qbittorrent-nox >/dev/null 2>&1
  say "השירות והחבילה הוסרו."
  say "הקבצים שהורדו נשארו ב-$DL_ROOT — למחיקה ידנית אם רוצים."
  say "המשתמש $QBT_USER נשאר. למחיקה:  userdel -r $QBT_USER"
  exit 0
fi

# ── שלב 1: סקר סביבה, בלי לגעת בכלום ─────────────────────────────────────
say "── סקר סביבה ──"
. /etc/os-release 2>/dev/null || die "לא הצלחתי לזהות את מערכת ההפעלה"
say "  מערכת: $PRETTY_NAME"
[[ "$ID" =~ ^(ubuntu|debian)$ ]] || die "הסקריפט הזה לדביאן/אובונטו בלבד"

FREE_KB=$(df -Pk /home | awk 'NR==2{print $4}')
FREE_GB=$(( FREE_KB / 1024 / 1024 ))
say "  דיסק:  ${FREE_GB}GB פנויים תחת /home"
(( FREE_GB >= MIN_FREE_GB )) || die "פחות מ-${MIN_FREE_GB}GB פנויים. לא מתקינים."

say
say "  פורטים שמאזינים עכשיו:"
ss -lntp 2>/dev/null | awk 'NR>1{split($4,a,":"); print a[length(a)], $NF}' \
  | sort -un | head -20 | while read -r p who; do
    printf '    %-7s %s\n' "$p" "$who"
  done

port_busy() { ss -lnt 2>/dev/null | awk '{split($4,a,":"); print a[length(a)]}' | grep -qx "$1"; }
PORT=""
for p in "$WANT_PORT" 8081 8082 8090 9091 8181; do
  if port_busy "$p"; then warn "פורט $p תפוס"; else PORT=$p; break; fi
done
[[ -n "$PORT" ]] || die "לא נמצא פורט פנוי"
ok "פורט ל-WebUI: $PORT"

say
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "^Status: active"; then
  FW=ufw; ok "חומת אש: UFW פעילה — אפתח את $PORT"
elif command -v iptables >/dev/null && [[ $(iptables -S 2>/dev/null | wc -l) -gt 3 ]]; then
  FW=iptables; warn "iptables עם כללים. לא נוגעת בהם — ייתכן שתצטרך לפתוח $PORT ידנית"
else
  FW=none; ok "חומת אש: אין כללים חוסמים"
fi

if systemctl is-active --quiet qbittorrent-nox 2>/dev/null; then
  die "qbittorrent-nox כבר רץ. הרץ --remove קודם אם רוצים להתקין מחדש."
fi

# מה שאסור לגעת בו — רק כדי להראות שראינו אותו
say
say "  שירותים קיימים שלא נוגעים בהם:"
for s in nginx zovex-bot zovex-server-next keepalive-sport5live; do
  systemctl is-active --quiet "$s" 2>/dev/null && say "    $s (פעיל)"
done

if [[ "${1:-}" == "--check" ]]; then
  say
  say "(--check — לא שונה כלום)"
  exit 0
fi

# ── שלב 2: התקנה ─────────────────────────────────────────────────────────
say
say "── התקנה ──"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null 2>&1
apt-get install -y -qq qbittorrent-nox >/dev/null 2>&1 \
  || die "התקנת qbittorrent-nox נכשלה"
ok "qbittorrent-nox $(qbittorrent-nox --version 2>/dev/null | head -1)"

id "$QBT_USER" >/dev/null 2>&1 || {
  useradd -r -m -d "$QBT_HOME" -s /usr/sbin/nologin "$QBT_USER"
  ok "נוצר משתמש ייעודי: $QBT_USER (בלי shell)"
}
mkdir -p "$DL_ROOT"/{complete,incomplete} "$QBT_HOME/.config/qBittorrent"
chown -R "$QBT_USER:$QBT_USER" "$DL_ROOT" "$QBT_HOME"
chmod 750 "$DL_ROOT"
ok "תיקיות: $DL_ROOT/complete · $DL_ROOT/incomplete"

# ── שלב 3: סיסמה ─────────────────────────────────────────────────────────
PASS=$(python3 - <<'PY'
import secrets, string
a = string.ascii_letters + string.digits
print(''.join(secrets.choice(a) for _ in range(16)))
PY
)
HASH=$(python3 - "$PASS" <<'PY'
# הפורמט של qBittorrent: PBKDF2-HMAC-SHA512, 100,000 סיבובים, מלח 16 בייט,
# מלח והאש ב-base64 מופרדים בנקודתיים.
import base64, hashlib, os, sys
salt = os.urandom(16)
h = hashlib.pbkdf2_hmac("sha512", sys.argv[1].encode(), salt, 100_000)
print(base64.b64encode(salt).decode() + ":" + base64.b64encode(h).decode())
PY
)
[[ -n "$HASH" ]] || die "יצירת האש הסיסמה נכשלה"

# ── שלב 4: קובץ ההגדרות ──────────────────────────────────────────────────
cat > "$CONF" <<EOF
[LegalNotice]
Accepted=true

[Preferences]
WebUI\\Enabled=true
WebUI\\Address=*
WebUI\\Port=$PORT
WebUI\\Username=admin
WebUI\\Password_PBKDF2="@ByteArray($HASH)"
WebUI\\LocalHostAuth=true
WebUI\\CSRFProtection=true
WebUI\\ClickjackingProtection=true
WebUI\\HostHeaderValidation=false
WebUI\\MaxAuthenticationFailCount=5
WebUI\\BanDuration=3600

# חילוץ אוטומטי: ל-qBittorrent אין מחלץ משלו. זה ההוק שדרכו מחברים
# unrar/unzip, והוא כבוי במפורש. הקבצים נשארים כפי שירדו.
AutoRun\\enabled=false
AutoRun\\program=

Downloads\\SavePath=$DL_ROOT/complete
Downloads\\TempPathEnabled=true
Downloads\\TempPath=$DL_ROOT/incomplete
Downloads\\PreAllocation=false
Downloads\\UseIncompleteExtension=true
Downloads\\StartInPause=false

Queueing\\QueueingEnabled=true
Queueing\\MaxActiveDownloads=2
Queueing\\MaxActiveUploads=2
Queueing\\MaxActiveTorrents=4

Connection\\GlobalDLLimitAlt=0
Advanced\\DiskCache=32

[BitTorrent]
# בגרסאות 4.5 ומעלה המפתחות עברו לכאן. כתובים גם וגם — גרסה שלא מכירה
# מפתח פשוט מתעלמת ממנו, וכך שדרוג עתידי לא ישבור את ההגדרות.
Session\\DefaultSavePath=$DL_ROOT/complete
Session\\TempPath=$DL_ROOT/incomplete
Session\\TempPathEnabled=true
Session\\Preallocation=false
Session\\QueueingSystemEnabled=true
Session\\MaxActiveDownloads=2
Session\\MaxActiveUploads=2
Session\\MaxActiveTorrents=4
Session\\GlobalMaxSeedingMinutes=1440
Session\\GlobalMaxRatio=1
Session\\MaxRatioAction=1
Session\\MaxConnections=200
Session\\MaxConnectionsPerTorrent=50
Session\\MaxUploads=8
EOF
chown -R "$QBT_USER:$QBT_USER" "$QBT_HOME"
chmod 600 "$CONF"
ok "נכתב $CONF"

# ── שלב 5: השירות ────────────────────────────────────────────────────────
cat > /etc/systemd/system/qbittorrent-nox.service <<EOF
[Unit]
Description=qBittorrent-nox
Documentation=man:qbittorrent-nox(1)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$QBT_USER
Group=$QBT_USER
UMask=0002
ExecStart=/usr/bin/qbittorrent-nox --webui-port=$PORT
Restart=on-failure
RestartSec=10

# עדיפות נמוכה: על השרת הזה יושבים גם האתר וגם ההזרמה, ואסור שהורדות
# יתחרו בהם על מעבד או על דיסק.
Nice=10
IOSchedulingClass=idle
CPUWeight=20
MemoryMax=768M

# בידוד: אין גישה לשאר השרת מלבד תיקיית ההורדות והבית של המשתמש.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=false
ReadWritePaths=$DL_ROOT $QBT_HOME
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true

[Install]
WantedBy=multi-user.target
EOF
ok "נכתבה יחידת systemd"

# ── שלב 6: שומר הדיסק ────────────────────────────────────────────────────
cat > /usr/local/bin/qbt-diskguard.sh <<EOF
#!/usr/bin/env bash
# משהה את כל ההורדות כשנגמר המקום. הדיסק משותף עם האתר, עם ההזרמה ועם
# ההעלאות — דיסק מלא מפיל את כולם, לא רק את ההורדות.
set -u
FREE_GB=\$(( \$(df -Pk "$DL_ROOT" | awk 'NR==2{print \$4}') / 1024 / 1024 ))
(( FREE_GB >= $GUARD_FREE_GB )) && exit 0
CK=\$(mktemp)
curl -s -c "\$CK" -d "username=admin&password=\$(cat /etc/qbt-webui.pass)" \\
     "http://127.0.0.1:$PORT/api/v2/auth/login" >/dev/null
curl -s -b "\$CK" "http://127.0.0.1:$PORT/api/v2/torrents/pause?hashes=all" >/dev/null
rm -f "\$CK"
logger -t qbt-diskguard "נשארו \${FREE_GB}GB — כל ההורדות הושהו"
EOF
chmod 700 /usr/local/bin/qbt-diskguard.sh
printf '%s' "$PASS" > /etc/qbt-webui.pass
chmod 600 /etc/qbt-webui.pass

cat > /etc/systemd/system/qbt-diskguard.service <<'EOF'
[Unit]
Description=qBittorrent disk guard
[Service]
Type=oneshot
ExecStart=/usr/local/bin/qbt-diskguard.sh
EOF
cat > /etc/systemd/system/qbt-diskguard.timer <<'EOF'
[Unit]
Description=Run qBittorrent disk guard every 5 minutes
[Timer]
OnBootSec=5min
OnCalendar=*:0/5
Persistent=true
[Install]
WantedBy=timers.target
EOF
ok "שומר דיסק: משהה הכל מתחת ל-${GUARD_FREE_GB}GB"

# ── שלב 7: הפעלה ─────────────────────────────────────────────────────────
systemctl daemon-reload
systemctl enable --now qbittorrent-nox.service >/dev/null 2>&1
systemctl enable --now qbt-diskguard.timer >/dev/null 2>&1

[[ "$FW" == "ufw" ]] && { ufw allow "$PORT"/tcp >/dev/null 2>&1 && ok "UFW: נפתח $PORT/tcp"; }

# ── שלב 8: אימות ─────────────────────────────────────────────────────────
say
say "── אימות ──"
for i in $(seq 1 15); do
  ss -lnt 2>/dev/null | grep -q ":$PORT " && break
  sleep 1
done
systemctl is-active --quiet qbittorrent-nox && ok "השירות פעיל" || bad "השירות לא פעיל"
ss -lnt 2>/dev/null | grep -q ":$PORT " && ok "מאזין על $PORT" || bad "לא מאזין על $PORT"
CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$PORT/")
[[ "$CODE" == "200" ]] && ok "ה-WebUI מגיב (HTTP $CODE)" || bad "ה-WebUI החזיר $CODE"
grep -q 'AutoRun\\enabled=false' "$CONF" && ok "חילוץ אוטומטי: כבוי"

IP=$(hostname -I | awk '{print $1}')
say
say "════════════════════════════════════════════"
say "  http://$IP:$PORT"
say
say "  משתמש:  admin"
say "  סיסמה:  $PASS"
say "════════════════════════════════════════════"
say
say "  הורדות:  $DL_ROOT/complete"
say "  בהורדה:  $DL_ROOT/incomplete"
say "  הסיסמה שמורה גם ב-/etc/qbt-webui.pass (הרשאות 600)"
say
warn "ה-WebUI חשוף לאינטרנט על פורט $PORT. יש הגבלת ניסיונות כניסה"
warn "(5 כשלונות → חסימה לשעה), אבל אין HTTPS — הסיסמה עוברת בטקסט גלוי."
warn "אם תרצה, אפשר להעביר אותו מאחורי nginx עם התעודה הקיימת."
