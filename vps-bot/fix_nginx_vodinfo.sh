#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · nginx אינו מעביר את /vodinfo לשרת.
#
# ## מה נמדד מול השרת החי
#
#     /stream/…                206  video/mp4                 ✔ מנותב
#     /vt/…/index.m3u8         200  application/vnd.apple…    ✔ מנותב
#     /vh/…                    404  application/json          ✔ מנותב
#     /vodinfo/…               206  text/html                 ✘ דף הבית
#
# כלומר ‎/vodinfo‎ נופל ל-try_files ומחזיר את ה-SPA. הנגן קורא לו,
# מקבל HTML, ‎r.json()‎ נכשל, ה-catch בולע — והזיהוי המהיר של קובץ
# שהדפדפן לא יכול לפענח פשוט לא קיים. נשארת רק רשת הביטחון של 25
# שניות.
#
# זה בדיוק מה שהצופה רואה ב"החממה": כל שלוש העונות הן DivX/XviD
# בתוך MP4, 624x352 — פורמט שדפדפנים אינם מפענחים.
#
# reload של nginx הדרגתי ואינו מנתק צופים.
#
#   sudo bash fix_nginx_vodinfo.sh
#   sudo bash fix_nginx_vodinfo.sh --remove
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
PORT="${API_PORT:-8000}"
MARK="# zovex-vodinfo"
ANCHOR="root /opt/zovex-site;"

CONF=$(grep -rl -- "$ANCHOR" /etc/nginx/sites-enabled /etc/nginx/conf.d 2>/dev/null | head -1)
[ -n "$CONF" ] || { echo "לא מצאתי קובץ nginx עם '$ANCHOR'"; exit 1; }
echo "קובץ: $CONF"

if [ "${1:-}" = "--remove" ]; then
  grep -q -- "$MARK" "$CONF" || { echo "לא מותקן."; exit 0; }
  cp -a "$CONF" "$CONF.bak_vodinfo_rm"
  python3 - "$CONF" "$MARK" <<'PY'
import re, sys
path, mark = sys.argv[1], sys.argv[2]
s = open(path, encoding="utf-8").read()
s, n = re.subn(r"\n+[ \t]*" + re.escape(mark) + r" begin\b.*?"
               + re.escape(mark) + r" end[ \t]*(?=\n)", "", s, flags=re.S)
if n == 0:
    sys.exit("✗ לא נמצא הבלוק להסרה")
open(path, "w", encoding="utf-8").write(s)
PY
  nginx -t && systemctl reload nginx && echo "✓ הוסר"
  exit 0
fi

grep -q -- "$MARK" "$CONF" && { echo "✓ כבר מותקן."; exit 0; }

cp -a "$CONF" "$CONF.bak_vodinfo"
echo "גיבוי: $CONF.bak_vodinfo"

BLOCK=$(printf '%s\n' \
"" \
"    $MARK begin" \
"    # בלי זה /vodinfo נופל ל-try_files ומחזיר את דף הבית, והנגן" \
"    # מקבל HTML במקום תשובה — כלומר הזיהוי של קובץ שהדפדפן אינו" \
"    # מפענח אינו עובד כלל." \
"    location ~ ^/vodinfo/ {" \
"        proxy_pass http://127.0.0.1:$PORT;" \
"        proxy_set_header Host \$host;" \
"        proxy_set_header X-Real-IP \$remote_addr;" \
"        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;" \
"        proxy_set_header X-Forwarded-Proto \$scheme;" \
"        # התשובה הראשונה לפריט דורשת משיכה מטלגרם." \
"        proxy_read_timeout 120s;" \
"    }" \
"    $MARK end")

python3 - "$CONF" "$ANCHOR" "$BLOCK" <<'PY'
import sys
path, anchor, block = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(path, encoding="utf-8").read()
if s.count(anchor) != 1:
    sys.exit("✗ העוגן מופיע %d פעמים — לא נוגעים בקובץ" % s.count(anchor))
open(path, "w", encoding="utf-8").write(s.replace(anchor, anchor + "\n" + block, 1))
PY

if ! nginx -t; then
  cp -a "$CONF.bak_vodinfo" "$CONF"
  echo "✗ בדיקת nginx נכשלה — הקובץ שוחזר"
  exit 1
fi
systemctl reload nginx
echo "✓ /vodinfo מנותב. בדיקה:"
echo "  curl -s -o /dev/null -w '%{content_type}\\n' \"https://zovex.duckdns.org/vodinfo/-1003936100530/20891?exp=...&sig=...\""
echo "  אמור להחזיר application/json ולא text/html"
