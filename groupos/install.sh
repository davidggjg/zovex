#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# install — מתקין את GroupOS כשירות נפרד על השרת.
#
# **נפרד מ-zovex בכוונה.** תיקייה משלו, שירות systemd משלו, מסד משלו.
# אם הבוט הזה ייפול, יקרוס או יאכל זיכרון — האתר והסטרימינג לא מרגישים.
#
# מה הוא עושה:
#   1. מוריד את הקוד מהמאגר ובודק שכל קובץ נטען כפייתון תקין
#   2. מריץ את 57 הבדיקות **לפני** שהוא נוגע בשירות
#   3. שומר את הטוקן ב-.env עם הרשאות 600 בלבד
#   4. מתקין שירות systemd שעולה מחדש לבד ומוגבל במשאבים
#   5. מוודא שהבוט באמת ענה לטלגרם, ולא רק ש"השירות רץ"
#
#   bash install.sh                      התקנה או עדכון
#   GROUPOS_TOKEN=... bash install.sh    עם טוקן מראש, בלי שאלה
#   bash install.sh --update             רק קוד, בלי לגעת בטוקן ובשירות
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail

DIR=/opt/groupos
BRANCH="claude/hls-relay-schema-port-ll8xiz"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/$BRANCH/groupos"
FILES=(db.py permissions.py audit.py ratelimit.py bot.py test_core.py
       README.md requirements.txt)
SVC=/etc/systemd/system/groupos.service
MODE=${1:-}

echo "════════ 1/5 · מוריד ════════"
mkdir -p "$DIR/data"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
for f in "${FILES[@]}"; do
  if ! curl -fsSL -o "$TMP/$f" "$RAW/$f"; then
    echo "  ✗ $f לא ירד"; exit 1
  fi
  # קובץ פייתון שירד חתוך ייראה תקין עד שהשירות ינסה לעלות
  case "$f" in
    *.py) python3 -c "import ast,sys;ast.parse(open(sys.argv[1],encoding='utf-8').read())" "$TMP/$f" \
            || { echo "  ✗ $f ירד פגום"; exit 1; } ;;
  esac
  echo "  ✓ $f"
done

echo
echo "════════ 2/5 · בודק לפני שנוגעים בשירות ════════"
if ! python3 -c "import aiogram" 2>/dev/null; then
  echo "  מתקין aiogram…"
  pip install -q aiogram || { echo "  ✗ התקנת aiogram נכשלה"; exit 1; }
fi
echo "  ✓ aiogram $(python3 -c 'import aiogram;print(aiogram.__version__)')"

# הבדיקות רצות על העותק שירד, על מסד זמני, בלי טוקן ובלי רשת
OUT=$(cd "$TMP" && GROUPOS_DB="$TMP/test.db" python3 test_core.py 2>&1)
echo "$OUT" | tail -1
if echo "$OUT" | grep -q "נכשלו 0"; then
  echo "  ✓ הבדיקות עברו — ממשיכים"
else
  echo "  ✗ בדיקות נכשלו. לא מתקינים."
  echo "$OUT" | grep "✗" | head -10
  exit 1
fi

# רק עכשיו, אחרי שהכול נבדק, מחליפים את הקוד החי
cp "$TMP"/*.py "$TMP"/*.md "$TMP"/requirements.txt "$DIR/"
echo "  ✓ הקוד הוחלף ב-$DIR"

if [ "$MODE" = "--update" ]; then
  systemctl restart groupos 2>/dev/null && echo "  ✓ השירות הופעל מחדש"
  exit 0
fi

echo
echo "════════ 3/5 · טוקן ════════"
ENV="$DIR/.env"
if [ -n "${GROUPOS_TOKEN:-}" ]; then
  TOK="$GROUPOS_TOKEN"
elif [ -f "$ENV" ] && grep -q '^GROUPOS_TOKEN=' "$ENV"; then
  TOK=$(grep '^GROUPOS_TOKEN=' "$ENV" | cut -d= -f2-)
  echo "  ● משתמש בטוקן הקיים"
else
  read -rp "  הדבק את הטוקן מ-BotFather: " TOK
fi
[ -n "$TOK" ] || { echo "  ✗ בלי טוקן אין מה להתקין"; exit 1; }

# 600: רק root קורא. הטוקן לעולם לא נכנס למאגר ולא ליומני מערכת.
umask 077
cat > "$ENV" <<EOF
GROUPOS_TOKEN=$TOK
GROUPOS_DB=$DIR/data/groupos.db
# שרת Bot API מקומי — מחזיר נתיב מקומי לקבצים במקום להוריד אותם.
# ריק = השרת של טלגרם.
GROUPOS_API_BASE=
EOF
chmod 600 "$ENV"
echo "  ✓ נשמר ב-$ENV (הרשאות $(stat -c%a "$ENV"))"

echo
echo "════════ 4/5 · שירות ════════"
cat > "$SVC" <<EOF
[Unit]
Description=GroupOS — Telegram group management
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$DIR
EnvironmentFile=$ENV
ExecStart=/usr/bin/python3 $DIR/bot.py
Restart=always
RestartSec=5
# תקרות: הבוט הזה חולק שרת עם הזרמת וידאו. אם הוא ידלוף זיכרון או
# יתחיל לטרוף מעבד, systemd יעצור אותו לפני שהצופים ירגישו.
MemoryMax=768M
CPUQuota=150%
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable -q groupos
systemctl restart groupos
echo "  ✓ groupos.service הותקן והופעל"

echo
echo "════════ 5/5 · מוודא שהוא באמת חי ════════"
# "active" אינו מספיק: שירות שעלה ונפל על טוקן שגוי נראה active לרגע.
# מחכים לשורה שהבוט כותב רק אחרי ש-getMe הצליח מול טלגרם.
OKAY=0
for i in $(seq 1 20); do
  sleep 1
  if journalctl -u groupos --since "-2 min" 2>/dev/null | grep -q "GroupOS עלה כ-@"; then
    OKAY=1; break
  fi
  if journalctl -u groupos --since "-2 min" 2>/dev/null | grep -qE "Unauthorized|TokenValidationError"; then
    echo "  ✗ טלגרם דחתה את הטוקן. בדוק אותו מול BotFather."
    exit 1
  fi
done

if [ "$OKAY" -eq 1 ]; then
  journalctl -u groupos --since "-2 min" | grep "GroupOS עלה" | tail -1 | sed 's/^/  ✓ /'
  echo
  echo "✅ הבוט חי."
  echo
  echo "עכשיו:"
  echo "  1. הוסף אותו לקבוצת בדיקה"
  echo "  2. תן לו הרשאות מנהל (מחיקת הודעות, חסימה, הגבלה)"
  echo "  3. שלח /health בקבוצה"
  echo
  echo "פקודות שירות:"
  echo "  journalctl -u groupos -f          יומן חי"
  echo "  systemctl restart groupos         הפעלה מחדש"
  echo "  bash install.sh --update          עדכון קוד בלבד"
else
  echo "  ✗ הבוט לא דיווח שהוא עלה תוך 20 שניות."
  echo "    היומן:"
  journalctl -u groupos --since "-2 min" --no-pager | tail -15 | sed 's/^/      /'
  exit 1
fi
