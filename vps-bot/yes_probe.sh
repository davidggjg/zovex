#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# בודק שלוש דרכים לגשת ל-API של yes, ומדווח מה עובד.
#
# רקע: svc.yes.co.il מוגן ב-Akamai ומחזיר 403 ל-curl רגיל, גם מ-IP ישראלי
# וגם עם ה-User-Agent שבו iptv-org משתמשים. שתי סיבות אפשריות נפוצות:
#   • עוגיות — Akamai מנפיקה עוגיות בביקור בדף, וה-API דורש אותן.
#   • טביעת TLS — Akamai מזהה את חתימת ה-handshake של curl וחוסמת אותה.
# הסקריפט בודק את שתיהן ומדווח, בלי לשנות כלום במערכת.
#     bash yes_probe.sh
# ─────────────────────────────────────────────────────────────────────────────
set -u
API="https://svc.yes.co.il/api/content/broadcast-schedule/channels?page=0&pageSize=1000"
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
JAR=$(mktemp)

show() { printf "  %-34s HTTP %s  %s בייט\n" "$1" "$2" "$3"; }

echo "── 1 · curl רגיל ──"
r=$(curl -s -o /tmp/y1 -w "%{http_code} %{size_download}" --max-time 30 \
     -H "User-Agent: $UA" -H 'accept-language: he-IL' "$API")
show "בלי עוגיות" ${r% *} ${r#* }

echo "── 2 · קודם ביקור בדף, אחר כך API (עם עוגיות) ──"
curl -s -o /dev/null --max-time 40 -c "$JAR" -H "User-Agent: $UA" \
  -H 'accept-language: he-IL' "https://www.yes.co.il/content/tv/broadcast-schedule" 2>/dev/null
n=$(grep -vc '^#' "$JAR" 2>/dev/null || echo 0)
echo "     (התקבלו $n עוגיות)"
r=$(curl -s -o /tmp/y2 -w "%{http_code} %{size_download}" --max-time 30 \
     -b "$JAR" -H "User-Agent: $UA" -H 'accept-language: he-IL' \
     -H 'Referer: https://www.yes.co.il/content/tv/broadcast-schedule' \
     -H 'Origin: https://www.yes.co.il' "$API")
show "עם עוגיות" ${r% *} ${r#* }

echo "── 3 · חיקוי טביעת TLS של דפדפן ──"
if ! python3 -c "import curl_cffi" 2>/dev/null; then
  echo "     מתקין curl_cffi..."
  pip install -q curl_cffi 2>&1 | tail -1
fi
python3 - "$API" <<'PY'
import sys
try:
    from curl_cffi import requests as cr
except Exception as e:
    print("     curl_cffi לא זמין:", e); raise SystemExit
url = sys.argv[1]
for imp in ("chrome124", "chrome120", "chrome116", "safari17_0"):
    try:
        r = cr.get(url, impersonate=imp, timeout=35,
                   headers={"accept-language": "he-IL",
                            "Referer": "https://www.yes.co.il/"})
        ok = "✅ עובד!" if r.status_code == 200 else ""
        print(f"  {imp:<34} HTTP {r.status_code}  {len(r.content)} בייט  {ok}")
        if r.status_code == 200:
            open("/tmp/yes_ok.json", "wb").write(r.content)
            print("\n     נשמר ל-/tmp/yes_ok.json")
            print("     " + r.text[:160])
            break
    except Exception as e:
        print(f"  {imp:<34} שגיאה: {type(e).__name__}")
PY

rm -f "$JAR"
echo
echo "── סיכום ──"
for f in /tmp/y1 /tmp/y2 /tmp/yes_ok.json; do
  [ -s "$f" ] && head -c 1 "$f" | grep -q '{' && echo "  ✅ $f מכיל JSON — יש לנו גישה!"
done
grep -l '{' /tmp/y1 /tmp/y2 /tmp/yes_ok.json 2>/dev/null >/dev/null || \
  echo "  ❌ כל השיטות חסומות — נעבור לתוכנית ב' (הבאת הנתונים מהדפדפן שלך)"
