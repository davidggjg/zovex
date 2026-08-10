#!/bin/bash
# בודק אילו מהערוצים באמת עובדים — חייב לרוץ *על השרת* (המקור חסום מבחוץ,
# והשרת הוא זה שיעביר את הזרמים בפועל).
#
# שלוש בדיקות לכל ערוץ, כי playlist תקין לבדו לא מוכיח ששידור חי:
#   1) ה-playlist נטען ומתחיל ב-#EXTM3U
#   2) יש בו סגמנטים (שורה שאינה הערה) — playlist ריק = ערוץ מת
#   3) הסגמנט האחרון באמת נטען ומחזיר וידאו אמיתי (>50KB)
# בדיקה בלבד — לא משנה שום תוכן.

BASE="https://tv.embyil.tv:86/live"
UA="Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"
OK=0; BAD=0
: > /tmp/live_ok.txt
: > /tmp/live_bad.txt

while IFS='|' read -r id name; do
  [ -z "$id" ] && continue
  url="$BASE/$id/chunks.m3u8"
  pl=$(curl -s --max-time 12 -A "$UA" "$url" 2>/dev/null)

  if ! printf '%s' "$pl" | head -1 | grep -q "#EXTM3U"; then
    echo "FAIL  $id  $name   (אין playlist)"
    echo "$id|$name|no-playlist" >> /tmp/live_bad.txt; BAD=$((BAD+1)); continue
  fi

  # שורת מדיה אחרונה (סגמנט או playlist מקונן)
  seg=$(printf '%s' "$pl" | grep -v '^#' | grep -v '^[[:space:]]*$' | tail -1 | tr -d '\r')
  if [ -z "$seg" ]; then
    echo "FAIL  $id  $name   (playlist ריק - ערוץ מת)"
    echo "$id|$name|empty" >> /tmp/live_bad.txt; BAD=$((BAD+1)); continue
  fi

  # כתובת מלאה לסגמנט (יחסית או מוחלטת)
  case "$seg" in
    http*) seg_url="$seg" ;;
    /*)    seg_url="https://tv.embyil.tv:86$seg" ;;
    *)     seg_url="$BASE/$id/$seg" ;;
  esac

  bytes=$(curl -s --max-time 20 -A "$UA" -r 0-60000 -o /dev/null -w "%{size_download}" "$seg_url" 2>/dev/null)
  if [ "${bytes:-0}" -gt 50000 ]; then
    echo "OK    $id  $name"
    echo "$id|$name" >> /tmp/live_ok.txt; OK=$((OK+1))
  else
    echo "FAIL  $id  $name   (סגמנט לא נטען: ${bytes}B)"
    echo "$id|$name|segment" >> /tmp/live_bad.txt; BAD=$((BAD+1))
  fi
done < /tmp/chans.txt

echo
echo "======================================"
echo "עובדים: $OK   |   לא עובדים: $BAD"
echo "======================================"
echo "--- לא עובדים ---"
cat /tmp/live_bad.txt 2>/dev/null
