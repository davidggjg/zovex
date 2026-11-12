#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · אבחון מעמיק: למה השרת לא מקבל זרם ממקור מסוים.  קריאה בלבד.
# מעט בקשות, במרווח 3 שניות — לא מפעיל הגנת הצפה.  לא מנסה לעקוף שום חסימה.
#
#   sudo bash diag_upstream.sh "http://host:80/path/to/stream"
# ─────────────────────────────────────────────────────────────────────────────
set -u
URL="${1:?תן קישור}"
HOST=$(echo "$URL" | sed -E 's#^[a-z]+://([^/:]+).*#\1#')
PORT=$(echo "$URL" | sed -nE 's#^[a-z]+://[^/:]+:([0-9]+).*#\1#p'); PORT=${PORT:-80}
SAFE=$(echo "$URL" | sed -E 's#(://[^/]+/)[^/]+/[^/]+/#\1USER/PASS/#')
gap(){ sleep 3; }
hr(){ printf '\n━━ %s ━━\n' "$1"; }
probe(){  # probe <label> <curl args...>
  local label=$1; shift
  local out rc
  out=$(curl -s -o /tmp/zv_diag.bin -m 12 -w '%{http_code}|%{size_download}|%{time_connect}|%{time_starttransfer}|%{content_type}' "$@" 2>/dev/null); rc=$?
  IFS='|' read -r code size tc ttfb ct <<<"$out"
  local first=""; [ -s /tmp/zv_diag.bin ] && first=$(xxd -l1 -p /tmp/zv_diag.bin)
  printf '  %-28s exit=%-3s http=%-4s bytes=%-9s connect=%-6s firstbyte=%-6s type=%s %s\n' \
    "$label" "$rc" "${code:-000}" "${size:-0}" "${tc:-0}" "${ttfb:-0}" "${ct:--}" \
    "$([ "$first" = 47 ] && echo '← TS תקין')"
  rm -f /tmp/zv_diag.bin
}

echo "יעד: $SAFE   (מארח $HOST, פורט $PORT)"

hr "1. השרת שלנו"
MYIP=$(curl -s -m 6 https://ifconfig.me); echo "  IP: $MYIP"
curl -s -m 6 "https://ipinfo.io/$MYIP/json" 2>/dev/null | grep -E '"(country|city|org)"' | sed 's/^/  /'

hr "2. המקור"
getent hosts "$HOST" | sed 's/^/  DNS מערכת: /'
command -v dig >/dev/null && echo "  DNS 1.1.1.1: $(dig +short "$HOST" @1.1.1.1 | tr '\n' ' ')"
IP=$(getent hosts "$HOST" | awk '{print $1; exit}')
curl -s -m 6 "https://ipinfo.io/$IP/json" 2>/dev/null | grep -E '"(country|city|org)"' | sed 's/^/  /'

hr "3. חיבור TCP (בלי HTTP)"
for p in "$PORT" 443 8080 25461; do
  t0=$(date +%s%N)
  if timeout 6 bash -c "</dev/tcp/$HOST/$p" 2>/dev/null; then
    echo "  פורט $p: פתוח ($(( ($(date +%s%N)-t0)/1000000 ))ms)"
  else echo "  פורט $p: סגור/לא עונה"; fi
done

hr "4. בקשות HTTP (מרווח 3ש)"
probe "דף הבית /"            "http://$HOST:$PORT/"; gap
probe "זרם, ברירת מחדל"      "$URL"; gap
probe "זרם, UA של VLC"       -A "VLC/3.0.20 LibVLC/3.0.20" "$URL"; gap
probe "זרם, UA של דפדפן"     -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36" "$URL"; gap
probe "זרם, HTTP/1.0"        --http1.0 "$URL"; gap
probe "זרם, עם Range"        -H "Range: bytes=0-1023" "$URL"; gap
probe "HTTPS לאותו מארח"     -k "https://$HOST/"; gap

hr "5. מי שולח את הניתוק? (TTL של ה-RST מול ה-SYN-ACK)"
if command -v tcpdump >/dev/null; then
  tcpdump -n -v -i any -c 12 "host $IP and tcp port $PORT and (tcp[tcpflags] & (tcp-syn|tcp-rst) != 0)" 2>/dev/null >/tmp/zv_tcpd.txt &
  TP=$!; sleep 1
  curl -s -o /dev/null -m 8 -A "VLC/3.0.20 LibVLC/3.0.20" "$URL" 2>/dev/null
  sleep 2; kill $TP 2>/dev/null; wait $TP 2>/dev/null
  SA=$(grep -B1 "$IP.$PORT > .*Flags \[S\.\]" /tmp/zv_tcpd.txt | grep -oE 'ttl [0-9]+' | head -1)
  RS=$(grep -B1 "$IP.$PORT > .*Flags \[R" /tmp/zv_tcpd.txt | grep -oE 'ttl [0-9]+' | head -1)
  echo "  SYN-ACK מהמקור: ${SA:-לא נלכד}"
  echo "  RST:            ${RS:-לא התקבל RST}"
  if [ -n "$SA" ] && [ -n "$RS" ]; then
    a=${SA#ttl }; b=${RS#ttl }; d=$(( a>b ? a-b : b-a ))
    if [ $d -le 2 ]; then echo "  → ה-RST הגיע מאותו מקום כמו ה-SYN-ACK: השרת של הספק עצמו מנתק."
    else echo "  → הפרש TTL של $d: ה-RST הוזרק על ידי רכיב בדרך (חומת אש / ספק אינטרנט / חוות שרתים), לא על ידי הספק."; fi
  fi
  rm -f /tmp/zv_tcpd.txt
else
  echo "  tcpdump לא מותקן. להתקנה:  apt-get install -y tcpdump   ואז להריץ שוב."
fi

hr "6. מסלול"
if command -v mtr >/dev/null; then mtr -rwn -c 3 -T -P "$PORT" "$IP" 2>/dev/null | tail -8 | sed 's/^/  /'
elif command -v traceroute >/dev/null; then traceroute -n -T -p "$PORT" -w 2 -q 1 -m 20 "$IP" 2>/dev/null | tail -8 | sed 's/^/  /'
else echo "  (mtr/traceroute לא מותקנים — apt-get install -y mtr-tiny)"; fi

echo; echo "סיום. הדבק את כל הפלט."
