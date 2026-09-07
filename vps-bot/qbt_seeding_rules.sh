#!/usr/bin/env bash
# מכוון את כללי הזריעה לדרישות של TorrentLeech, ומשחרר את הדיסק לבד.
#
# ## מה מתקן כאן
#
# בהגדרה הראשונה שכתבתי היו שתי טעויות:
#
#   GlobalMaxSeedingMinutes = 1440   — 24 שעות. TL דורש 4 עד 10 ימים לפי
#                                      דרגת המשתמש, אז זה היה מייצר HnR
#                                      במקום למנוע אותו. בדיוק ההפך.
#
#   MaxRatioAction = 1               — תיארתי את זה כ"משהה". הערכים בפועל:
#                                      0 משהה · 1 מסיר מהרשימה ·
#                                      2 סופר-סידינג · 3 מסיר ומוחק קבצים.
#
# ## הכלל של TorrentLeech
#
# מהוויקי הרשמי: לזרוע ליחס 1:1 **או** למשך המינימום של הדרגה —
# Registered 10 ימים, Power User 8, Super User 7, Extreme 6, TL God 4,
# VIP ללא מינימום. פריליץ' אינו פטור.
#
# ## למה זה מסתדר לבד
#
# qBittorrent מפעיל את הפעולה כשמגיעים ליחס **או** לזמן — מה שקורה קודם.
# זה בדיוק אותו כלל. אז: זורע, עומד בדרישה, מוחק את עצמו, והתור מושך את
# הבא. הדיסק לא מתמלא ואין HnR.
#
#     bash qbt_seeding_rules.sh --days 10          # Registered
#     bash qbt_seeding_rules.sh --days 4           # TL God
#     bash qbt_seeding_rules.sh --days 10 --keep   # לא מוחק, רק משהה
set -uo pipefail

CONF=/home/qbt/.config/qBittorrent/qBittorrent.conf
DAYS=10
ACTION=3          # מסיר ומוחק את הקבצים
MARGIN_H=6        # שעות מרווח מעל הדרישה, ליתר ביטחון

while [[ $# -gt 0 ]]; do
  case "$1" in
    --days) DAYS="$2"; shift 2 ;;
    --keep) ACTION=0; shift ;;      # רק משהה, לא מוחק
    *) echo "לא מוכר: $1"; exit 1 ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "❌ צריך root"; exit 1; }
[[ -f "$CONF" ]] || { echo "❌ לא נמצא $CONF"; exit 1; }

MIN=$(( DAYS * 24 * 60 + MARGIN_H * 60 ))

echo "── מה משתנה ──"
echo "  זמן זריעה מינימלי:  $DAYS ימים (+$MARGIN_H שעות מרווח) = $MIN דקות"
echo "  יחס:                 1.0"
echo "  כשאחד מהם הושג:      $([[ $ACTION == 3 ]] && echo 'מסיר ומוחק את הקבצים' || echo 'משהה בלבד')"
echo

# qBittorrent כותב מחדש את הקובץ ביציאה, ולכן חייבים לעצור לפני שעורכים.
systemctl stop qbittorrent-nox
sleep 2
cp "$CONF" "$CONF.bak-seed-$(date +%Y%m%d-%H%M%S)"

set_key() {   # קובץ, מפתח, ערך — מעדכן אם קיים, מוסיף אם לא
  local k="$1" v="$2"
  if grep -q "^${k}=" "$CONF"; then
    sed -i "s|^${k}=.*|${k}=${v}|" "$CONF"
  else
    # מוסיף לתוך הסקציה [BitTorrent]
    sed -i "/^\[BitTorrent\]/a ${k}=${v}" "$CONF"
  fi
}

set_key 'Session\\GlobalMaxRatio'         '1'
set_key 'Session\\GlobalMaxSeedingMinutes' "$MIN"
set_key 'Session\\MaxRatioAction'          "$ACTION"

systemctl start qbittorrent-nox
sleep 3

echo "── מה בקובץ עכשיו ──"
grep -E 'GlobalMaxRatio|GlobalMaxSeedingMinutes|MaxRatioAction' "$CONF" | sed 's/^/  /'
echo
systemctl is-active --quiet qbittorrent-nox \
  && echo "  ✓ השירות פעיל" || echo "  ✗ השירות לא עלה"
echo
echo "מעכשיו: כל טורנט נזרע עד 1:1 או $DAYS ימים — מה שקורה קודם —"
echo "ואז $([[ $ACTION == 3 ]] && echo 'נמחק מהדיסק' || echo 'מושהה') והתור מושך את הבא."
