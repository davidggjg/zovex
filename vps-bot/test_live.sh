#!/bin/bash
# בודק אילו מהערוצים החדשים באמת עובדים — חייב לרוץ *על השרת*, כי הוא זה
# שיעביר את הזרמים בפועל (relay), והמקור עשוי להיות חסום גיאוגרפית.
# לכל ערוץ: מושכים את ה-playlist, ומוודאים שהוא באמת HLS (#EXTM3U) ולא דף שגיאה.
# פלט: OK / FAIL לכל ערוץ, וסיכום בסוף. אין שינוי בתוכן — בדיקה בלבד.

BASE="https://tv.embyil.tv:86/live"
UA="Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"
OK=0; BAD=0
: > /tmp/live_ok.txt
: > /tmp/live_bad.txt

while IFS='|' read -r id name; do
  [ -z "$id" ] && continue
  body=$(curl -s --max-time 12 -A "$UA" "$BASE/$id/chunks.m3u8" 2>/dev/null)
  code=$(curl -s --max-time 12 -A "$UA" -o /dev/null -w "%{http_code}" "$BASE/$id/chunks.m3u8" 2>/dev/null)
  if [ "$code" = "200" ] && printf '%s' "$body" | head -1 | grep -q "#EXTM3U"; then
    echo "OK    $id  $name"
    echo "$id|$name" >> /tmp/live_ok.txt
    OK=$((OK+1))
  else
    echo "FAIL  $id  $name   (HTTP $code)"
    echo "$id|$name|$code" >> /tmp/live_bad.txt
    BAD=$((BAD+1))
  fi
done < /tmp/chans.txt

echo
echo "======================================"
echo "עובדים: $OK   |   לא עובדים: $BAD"
echo "רשימת העובדים נשמרה ב: /tmp/live_ok.txt"
echo "======================================"
