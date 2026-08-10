#!/bin/bash
U="https://tv.embyil.tv:86/live/10/chunks.m3u8"
UA="Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"
echo "=== 1. שגיאה אמיתית (בלי -s) ==="
curl --max-time 15 -A "$UA" -o /dev/null "$U" 2>&1 | tail -3
echo
echo "=== 2. עם -k (התעלמות מתעודה) ==="
curl -sk --max-time 15 -A "$UA" -o /tmp/t1 -w "HTTP %{http_code} | %{size_download}B\n" "$U" 2>&1
head -2 /tmp/t1 2>/dev/null
echo
echo "=== 3. HTTP רגיל (בלי TLS) ==="
curl -s --max-time 15 -A "$UA" -o /tmp/t2 -w "HTTP %{http_code} | %{size_download}B\n" "http://tv.embyil.tv:86/live/10/chunks.m3u8" 2>&1
head -2 /tmp/t2 2>/dev/null
echo
echo "=== 4. האם הפורט בכלל פתוח ==="
timeout 8 bash -c 'cat < /dev/null > /dev/tcp/tv.embyil.tv/86' 2>&1 && echo "פורט 86 פתוח ✅" || echo "פורט 86 חסום ❌"
echo
echo "=== 5. פרטי תעודה ==="
timeout 12 openssl s_client -connect tv.embyil.tv:86 -servername tv.embyil.tv </dev/null 2>&1 | grep -iE "subject=|issuer=|verify|CN" | head -5
