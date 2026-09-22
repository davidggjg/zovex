#!/bin/bash
# fix_bind_localhost — האפליקציה (8000) ו-qBittorrent (8080) יאזינו רק מקומית.
#
# נמדד ב-ss:  8000 על 0.0.0.0, 8080 על *, 8099 על 127.0.0.1.
# nginx כבר מעביר אל שניהם דרך 127.0.0.1, ולכן גישה מבחוץ לא נפגעת.
# לא נוגע ב-SSH, בחומת אש או ב-sshd — רק בכתובת ההאזנה של שני השירותים.
#
#   bash fix_bind_localhost.sh --check    מראה מה ישתנה, לא נוגע בכלום
#   bash fix_bind_localhost.sh            מחיל, בודק, ומחזיר לבד אם משהו נכשל
#   bash fix_bind_localhost.sh --revert   מחזיר את שלושת הקבצים
set -uo pipefail

MAIN=/opt/zovex-bot/main.py
ENV=/opt/zovex-bot/.env
QCONF=/home/qbt/.config/qBittorrent/qBittorrent.conf
PUBLIC=https://zovex.duckdns.org
SUF=.bak_bind_localhost
MODE=${1:-}

ports() { ss -tlnp 2>/dev/null | grep -E ':(8000|8080) ' | awk '{print "    " $4}'; }

revert() {
  for f in "$MAIN" "$ENV" "$QCONF"; do
    [ -f "$f$SUF" ] && cp -p "$f$SUF" "$f" && echo "  שוחזר: $f"
  done
  systemctl stop qbittorrent-nox 2>/dev/null
  [ -f "$QCONF$SUF" ] && cp -p "$QCONF$SUF" "$QCONF"
  systemctl start qbittorrent-nox 2>/dev/null
  systemctl restart zovex-bot
}

if [ "$MODE" = "--revert" ]; then
  revert; sleep 5; echo "פורטים עכשיו:"; ports; exit 0
fi

# ── מה צריך לשנות ──────────────────────────────────────────────────────
echo "פורטים עכשיו:"; ports; echo

DO_MAIN=0; DO_ENV=0; DO_Q=0
if grep -q 'uvicorn.run("main:api", host="0.0.0.0", port=PORT' "$MAIN"; then
  DO_MAIN=1; echo "  • main.py: האזנה ל-127.0.0.1 במקום 0.0.0.0"
elif grep -q 'BIND_HOST' "$MAIN"; then
  echo "  ● main.py כבר מעודכן"
else
  echo "  ✗ לא מצאתי את שורת ההאזנה ב-main.py — לא נוגע בו"
fi

# השירות צריך להריץ את main.py עצמו; אם הוא מריץ uvicorn עם --host, השינוי
# ב-main.py לא ישפיע, ועדיף לדעת את זה לפני שמתחילים.
if systemctl cat zovex-bot 2>/dev/null | grep -E '^ExecStart=' | grep -q -- '--host'; then
  echo "  ✗ השירות מעביר --host בעצמו — שינוי ב-main.py לא ישפיע. עוצר."
  exit 1
fi

if grep -qE '^BASE_URL=http://[0-9.]+:8000/?$' "$ENV"; then
  DO_ENV=1; echo "  • .env: BASE_URL יצביע על $PUBLIC (הקישורים של הבוט הפרטי)"
fi

if [ -f "$QCONF" ] && grep -qE '^WebUI\\Address=\*$' "$QCONF"; then
  DO_Q=1; echo "  • qBittorrent: האזנה ל-127.0.0.1 במקום *"
elif [ -f "$QCONF" ] && grep -qE '^WebUI\\Address=127\.0\.0\.1$' "$QCONF"; then
  echo "  ● qBittorrent כבר מעודכן"
else
  echo "  ⚠ לא מצאתי את הגדרת הכתובת של qBittorrent — מדלג עליו"
fi

if [ $((DO_MAIN + DO_ENV + DO_Q)) -eq 0 ]; then echo; echo "אין מה לשנות."; exit 0; fi
[ "$MODE" = "--check" ] && { echo; echo "--check: לא שונה כלום."; exit 0; }

# ── גיבויים ────────────────────────────────────────────────────────────
for f in "$MAIN" "$ENV" "$QCONF"; do
  [ -f "$f" ] && [ ! -f "$f$SUF" ] && cp -p "$f" "$f$SUF"
done
chmod 600 "$ENV$SUF" 2>/dev/null

# ── החלה ───────────────────────────────────────────────────────────────
if [ $DO_MAIN -eq 1 ]; then
  python3 - "$MAIN" <<'PY' || { echo "✗ עריכת main.py נכשלה"; revert; exit 1; }
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
a = 'uvicorn.run("main:api", host="0.0.0.0", port=PORT'
b = ('uvicorn.run("main:api", '
     'host=os.environ.get("BIND_HOST", "127.0.0.1"), port=PORT')
assert s.count(a) == 1
s = s.replace(a, b, 1)
compile(s, p, "exec")
open(p + ".tmp_bind", "w", encoding="utf-8").write(s)
import os
os.replace(p + ".tmp_bind", p)
PY
  echo "  ✓ main.py"
fi

if [ $DO_ENV -eq 1 ]; then
  sed -i -E "s#^BASE_URL=http://[0-9.]+:8000/?\$#BASE_URL=$PUBLIC#" "$ENV"
  echo "  ✓ .env"
fi

systemctl restart zovex-bot
UP=0
for i in $(seq 1 30); do
  sleep 2
  [ "$(curl -s -o /dev/null -m 5 -w '%{http_code}' http://127.0.0.1:8000/content/version)" = "200" ] \
    && { UP=1; break; }
done

if [ $DO_Q -eq 1 ]; then
  # qBittorrent כותב את קובץ ההגדרות בזמן יציאה, ולכן עוצרים לפני העריכה
  systemctl stop qbittorrent-nox
  sed -i -E 's/^WebUI\\Address=\*$/WebUI\\Address=127.0.0.1/' "$QCONF"
  chown qbt:qbt "$QCONF" 2>/dev/null
  systemctl start qbittorrent-nox
  sleep 4
  echo "  ✓ qBittorrent"
fi

# ── בדיקה ──────────────────────────────────────────────────────────────
OK=$UP
SITE=$(curl -s -o /dev/null -m 15 -w '%{http_code}' "$PUBLIC/")
API=$(curl -s -o /dev/null -m 15 -w '%{http_code}' "$PUBLIC/content/version")
QBT=$(curl -s -o /dev/null -m 15 -w '%{http_code}' "$PUBLIC/qbt-api/api/v2/app/version")
echo
echo "  בוט מקומי:        $([ $UP -eq 1 ] && echo 200 || echo 'לא עונה')"
echo "  אתר דרך nginx:     $SITE"
echo "  API דרך nginx:     $API"
echo "  טורנטים דרך nginx: $QBT   (403 תקין — פירושו שהגענו ונדרשת התחברות)"
[ "$SITE" = "200" ] || OK=0
[ "$API" = "200" ] || OK=0
case "$QBT" in 502|504|000) OK=0 ;; esac

if [ $OK -ne 1 ]; then
  echo; echo "✗ משהו לא עונה — מחזיר הכל אחורה."
  revert; sleep 6; echo "פורטים אחרי ההחזרה:"; ports; exit 1
fi

echo; echo "פורטים עכשיו:"; ports
echo; echo "✓ שני הפורטים מאזינים רק מקומית. לביטול:  bash fix_bind_localhost.sh --revert"
