#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · למה זה נתקע רק בשעת שיא.
#
# דווח: מהיר כל היום, ואחרי 21:00 מתחיל להיתקע תוך 9-30 דקות. דפוס כזה
# אינו תכונה של קובץ ואינו חנק מצד טלגרם — שניהם היו מופיעים גם בצהריים.
# הוא תכונה של **מקביליות**: משהו שגדל עם מספר הצופים.
#
# החשד הראשי: ‎_edge_fill‎ נוצר דרך ‎asyncio.create_task‎ בלי שום תקרה
# גלובלית. כל צפייה בקובץ שאינו במטמון מתחילה מילוי רקע, וכולם מתחרים על
# אותם חיבורים מול טלגרם — שמוגבלים ל-~2 MB/s לחיבור. בשעת שיא מילויי
# הרקע מרעיבים בדיוק את מי שצופה עכשיו.
#
# זה נשאר חשד עד שנמדד. בלי המדידה הזו אבנה תקרה למשהו שאולי אינו הגורם,
# וגרוע מזה — קריאה מקדימה בלי תקרה תוסיף תעבורה בדיוק בשעה שאין בה די.
#
# הסקריפט קורא בלבד. אינו נוגע בשירות, בקבצים ובמטמון.
#
#   sudo bash peak_probe.sh            # 5 דקות
#   MINUTES=10 sudo bash peak_probe.sh
# ─────────────────────────────────────────────────────────────────────────────
set -u

API="http://127.0.0.1:8000"
MINUTES="${MINUTES:-5}"
INTERVAL=5
N=$(( MINUTES * 60 / INTERVAL ))
PY=/opt/zovex-bot/venv/bin/python
[ -x "$PY" ] || PY=python3
OUT=/tmp/zovex_peak_$(date +%H%M).csv

curl -fsS -m 5 "$API/debug/caches" >/dev/null 2>&1 \
  || { echo "❌ $API/debug/caches לא עונה — השרת למטה?"; exit 1; }

IFACE=$(ip route show default 2>/dev/null | awk '{print $5; exit}')
rx() { cat "/sys/class/net/$IFACE/statistics/tx_bytes" 2>/dev/null || echo 0; }

echo "מודד $MINUTES דקות, דגימה כל $INTERVAL שניות."
echo "תריץ את זה כשזה *באמת* נתקע, ובמקביל תנסה לצפות במשהו."
echo
printf '%-9s %7s %7s %7s %7s %8s %7s\n' \
  "שעה" "מילויים" "צופים" "HLS" "טעינה" "יציאה" "מטמון"
echo "────────────────────────────────────────────────────────────"
echo "time,edge_filling,viewers,hls_inflight,load1,tx_mbit,seg_cache_mb" > "$OUT"

P=$(rx)
MAXF=0; MAXV=0; SUMF=0
for i in $(seq 1 "$N"); do
  sleep "$INTERVAL"
  J=$(curl -fsS -m 5 "$API/debug/caches" 2>/dev/null)
  read -r F H S <<<"$(printf '%s' "$J" | "$PY" -c 'import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    print("? ? ?"); raise SystemExit
print(d.get("edge_filling","?"), d.get("hls_segment_inflight","?"),
      round(d.get("hls_seg_cache_bytes",0)/1048576))' 2>/dev/null)"
  # צופים = חיבורים פתוחים ל-443. קירוב, אבל הוא זה שגדל בשעת שיא.
  V=$(ss -tn state established '( sport = :443 )' 2>/dev/null | tail -n +2 | wc -l)
  L=$(awk '{print $1}' /proc/loadavg)
  C=$(rx); MB=$(( (C - P) * 8 / INTERVAL / 1000000 )); P=$C

  printf '%-9s %7s %7s %7s %7s %6s Mb %5s MB\n' \
    "$(date +%H:%M:%S)" "$F" "$V" "$H" "$L" "$MB" "$S"
  echo "$(date +%H:%M:%S),$F,$V,$H,$L,$MB,$S" >> "$OUT"

  case "$F" in ''|*[!0-9]*) ;; *)
    SUMF=$((SUMF+F)); [ "$F" -gt "$MAXF" ] && MAXF=$F ;;
  esac
  [ "$V" -gt "$MAXV" ] && MAXV=$V
done

FW=$(journalctl -u zovex-bot --since "${MINUTES} min ago" --no-pager 2>/dev/null \
     | grep -ci "floodwait")

cat <<EOF

────────────────────────────────────────────────────────────
מילויי רקע:  שיא $MAXF,  ממוצע $(( SUMF / N ))
צופים:       שיא $MAXV
FloodWait:   $FW ב-$MINUTES הדקות

הקובץ המלא: $OUT
שלח לי אותו:  cat $OUT
EOF
