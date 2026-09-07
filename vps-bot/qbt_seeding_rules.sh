#!/usr/bin/env bash
# מכוון את qBittorrent לזריעה מקסימלית, בלי לחנוק את האתר.
#
# ## שתי טעויות שלי שמתוקנות כאן
#
#   GlobalMaxSeedingMinutes=1440  — 24 שעות. TorrentLeech דורש 240 שעות
#   (10 ימים) לדרגה Registered, ולכן ההגדרה הזאת *ייצרה* HnR במקום למנוע.
#
#   MaxActiveUploads=2            — רק שני טורנטים זורעים בו-זמנית. כיוונתי
#   את התור נגד מילוי הדיסק בזמן הורדות, ולא חשבתי על זריעה. התוצאה: גם עם
#   20 טורנטים על הדיסק, 18 מהם יושבים ולא מגישים כלום.
#
# ## מה קובע יחס
#
# העלאה קורית רק כשמישהו מוריד ממך. לכן:
#
#   • **מספר טורנטים שזורעים במקביל** הוא המנוף הישיר. אותם 40GB בדיסק
#     יכולים להיות 4 קבצים של 10GB או 20 קבצים של 2GB — פי חמישה סיכוי
#     שמישהו ירצה משהו.
#   • **חריצי העלאה** קובעים לכמה עמיתים אפשר להגיש בו-זמנית.
#   • **IgnoreSlowTorrents** — טורנט שאיש לא מושך ממנו לא נחשב "פעיל",
#     ולכן לא תופס מקום במכסה. בלעדיו עשרה טורנטים רדומים חוסמים את התור.
#
# ## ומה שאסור לשכוח
#
# אותו קו משרת את הצופים באתר. זריעה בלי תקרה תרעיב אותם. לכן יש תקרת
# העלאה שמשאירה מרווח — ברירת המחדל 12MB/s מתוך ~25 שנמדדו.
#
#     bash qbt_seeding_rules.sh --days 10
#     bash qbt_seeding_rules.sh --days 10 --up 20      # תקרה 20MB/s
#     bash qbt_seeding_rules.sh --days 10 --up 0       # בלי תקרה (זהיר!)
#     bash qbt_seeding_rules.sh --days 10 --keep       # משהה במקום למחוק
set -uo pipefail

CONF=/home/qbt/.config/qBittorrent/qBittorrent.conf
UNIT=/etc/systemd/system/qbittorrent-nox.service
DAYS=10
ACTION=3          # 0 משהה · 1 מסיר · 2 סופר-סידינג · 3 מסיר ומוחק קבצים
MARGIN_H=6
UP_MB=12          # תקרת העלאה במגה-בייט לשנייה. 0 = בלי תקרה

while [[ $# -gt 0 ]]; do
  case "$1" in
    --days) DAYS="$2"; shift 2 ;;
    --up)   UP_MB="$2"; shift 2 ;;
    --keep) ACTION=0; shift ;;
    *) echo "לא מוכר: $1"; exit 1 ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "❌ צריך root"; exit 1; }
[[ -f "$CONF" ]] || { echo "❌ לא נמצא $CONF"; exit 1; }

MIN=$(( DAYS * 24 * 60 + MARGIN_H * 60 ))
UP_KB=$(( UP_MB * 1024 ))
RAM_MB=$(free -m | awk '/^Mem:/{print $2}')

echo "── מה משתנה ──"
echo "  זריעה מינימלית:    $DAYS ימים (+$MARGIN_H שעות מרווח)"
echo "  יחס יעד:            1.0  — מה שקורה קודם"
echo "  כשהושג:             $([[ $ACTION == 3 ]] && echo 'מסיר ומוחק' || echo 'משהה')"
echo
echo "  הורדות במקביל:      2      (הגנה על הדיסק)"
echo "  זריעה במקביל:       30     (היה 2)"
echo "  חריצי העלאה:        40     (היה 8)"
echo "  חיבורים:            500    (היה 200)"
echo "  תקרת העלאה:         $([[ $UP_MB == 0 ]] && echo 'ללא' || echo "${UP_MB}MB/s")"
echo "  זיכרון בשרת:        ${RAM_MB}MB"
echo

systemctl stop qbittorrent-nox
sleep 2
cp "$CONF" "$CONF.bak-seed-$(date +%Y%m%d-%H%M%S)"

set_key() {
  local k="$1" v="$2"
  if grep -q "^${k}=" "$CONF"; then
    sed -i "s|^${k}=.*|${k}=${v}|" "$CONF"
  else
    sed -i "/^\[BitTorrent\]/a ${k}=${v}" "$CONF"
  fi
}

# ── מתי להפסיק לזרוע ─────────────────────────────────────────────────────
set_key 'Session\\GlobalMaxRatio'          '1'
set_key 'Session\\GlobalMaxSeedingMinutes'  "$MIN"
set_key 'Session\\MaxRatioAction'           "$ACTION"

# ── כמה לזרוע במקביל ─────────────────────────────────────────────────────
set_key 'Session\\QueueingSystemEnabled'    'true'
set_key 'Session\\MaxActiveDownloads'       '2'
set_key 'Session\\MaxActiveUploads'         '30'
set_key 'Session\\MaxActiveTorrents'        '32'
# טורנט שאיש לא מושך ממנו לא ייחשב פעיל, ולכן לא יחסום את המכסה
set_key 'Session\\IgnoreSlowTorrentsInQueueing' 'true'

# ── כמה עמיתים להגיש ─────────────────────────────────────────────────────
set_key 'Session\\MaxUploads'               '40'
set_key 'Session\\MaxUploadsPerTorrent'     '8'
set_key 'Session\\MaxConnections'           '500'
set_key 'Session\\MaxConnectionsPerTorrent' '100'

# ── תקרת מהירות ──────────────────────────────────────────────────────────
# 0 = ללא הגבלה. אותו קו משרת את הצופים באתר, ולכן ברירת המחדל משאירה מרווח.
set_key 'Session\\GlobalUPSpeedLimit'       "$UP_KB"
set_key 'Session\\GlobalDLSpeedLimit'       '0'

# ── זיכרון ───────────────────────────────────────────────────────────────
# 30 טורנטים ו-500 חיבורים צורכים יותר מ-768MB שהגדרתי קודם. אם החיבורים
# יגדלו והתקרה תישאר — systemd יהרוג את התהליך באמצע זריעה.
NEW_MEM=1536
if (( RAM_MB > 0 && NEW_MEM > RAM_MB / 2 )); then
  NEW_MEM=$(( RAM_MB / 2 ))
  echo "  ⚠ מתאים תקרת זיכרון ל-${NEW_MEM}MB (חצי מה-RAM)"
fi
if [[ -f "$UNIT" ]] && grep -q "^MemoryMax=" "$UNIT"; then
  sed -i "s|^MemoryMax=.*|MemoryMax=${NEW_MEM}M|" "$UNIT"
  systemctl daemon-reload
fi

systemctl start qbittorrent-nox
sleep 3

echo "── מה בקובץ עכשיו ──"
grep -E 'GlobalMaxRatio|GlobalMaxSeedingMinutes|MaxRatioAction|MaxActive|MaxUploads|MaxConnections|UPSpeedLimit|IgnoreSlow' "$CONF" | sed 's/^/  /'
echo
systemctl is-active --quiet qbittorrent-nox \
  && echo "  ✓ השירות פעיל" || echo "  ✗ השירות לא עלה — בדוק journalctl -u qbittorrent-nox -n 30"
echo
echo "מעכשיו: עד 30 טורנטים זורעים במקביל, כל אחד עד 1:1 או $DAYS ימים,"
echo "ואז $([[ $ACTION == 3 ]] && echo 'נמחק' || echo 'מושהה') והתור מושך את הבא."
echo
echo "טיפ ליחס: קבצים קטנים עדיפים. 20 טורנטים של 2GB תופסים אותו מקום"
echo "כמו 4 של 10GB — ונותנים פי חמישה סיכוי שמישהו ירצה משהו."
