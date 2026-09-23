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
#   bash install.sh --token 123:AA...    הטוקן בשורת הפקודה, בלי שאלה
#   bash install.sh --update             רק קוד, בלי לגעת בטוקן ובשירות
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail

DIR=/opt/groupos
BRANCH="claude/hls-relay-schema-port-ll8xiz"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/$BRANCH/groupos"
# רשימת הקבצים מגיעה מ-manifest.txt שבמאגר ולא מכאן. הרשימה הקשיחה
# שהייתה כאן פספסה שלושה מודולים חדשים — ההתקנה "הצליחה" והבוט עלה
# בלי הפאנל. עכשיו קובץ חדש נכנס ל-manifest ומגיע מעצמו, ויש בדיקה
# שנכשלת אם מודול קיים חסר ממנו.
EXTRA=(README.md requirements.txt manifest.txt)
SVC=/etc/systemd/system/groupos.service
MODE=${1:-}
ARG_TOKEN=""
if [ "$MODE" = "--token" ]; then ARG_TOKEN=${2:-}; MODE=""; fi

echo "════════ 1/5 · מוריד ════════"
mkdir -p "$DIR/data"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
if ! curl -fsSL -o "$TMP/manifest.txt" "$RAW/manifest.txt"; then
  echo "  ✗ manifest.txt לא ירד"; exit 1
fi
mapfile -t FILES < <(grep -E '^[A-Za-z0-9_]+\.py$' "$TMP/manifest.txt")
if [ ${#FILES[@]} -lt 5 ]; then
  echo "  ✗ manifest.txt נראה פגום (${#FILES[@]} קבצים)"; exit 1
fi
FILES+=("${EXTRA[@]}")
for f in "${FILES[@]}"; do
  [ "$f" = "manifest.txt" ] && continue
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

# כל מודול מקומי ש-bot.py מייבא חייב להיות בין הקבצים שירדו. בלי זה
# המתקין "מצליח" והשירות נופל על ImportError בהפעלה הראשונה.
MISSING=$(cd "$TMP" && python3 - <<'PYEOF'
import ast, os
need = set()
for n in ast.walk(ast.parse(open("bot.py", encoding="utf-8").read())):
    if isinstance(n, ast.Import):
        need |= {a.name.split(".")[0] for a in n.names}
    elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
        need.add(n.module.split(".")[0])
have = {f[:-3] for f in os.listdir(".") if f.endswith(".py")}
import sys
std = set(sys.stdlib_module_names) | {"aiogram"}
print(" ".join(sorted(need - have - std)))
PYEOF
)
if [ -n "$MISSING" ]; then
  echo "  ✗ חסרים מודולים ש-bot.py מייבא: $MISSING"
  echo "    (הם כנראה לא רשומים ב-manifest.txt)"
  exit 1
fi
echo "  ✓ כל מה ש-bot.py מייבא נמצא"

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
cp "$TMP"/*.py "$TMP"/*.md "$TMP"/requirements.txt "$TMP"/manifest.txt "$DIR/"
echo "  ✓ הקוד הוחלף ב-$DIR"

if [ "$MODE" = "--update" ]; then
  systemctl restart groupos 2>/dev/null && echo "  ✓ השירות הופעל מחדש"
  exit 0
fi

echo
echo "════════ 3/5 · טוקן ════════"
ENV="$DIR/.env"

# טוקן של טלגרם הוא מספר, נקודתיים, ולפחות 30 תווים. בלי הבדיקה הזאת
# משתנה סביבה ישן — או טקסט מציין-מקום שהודבק פעם — נלקח **בשקט**,
# וההתקנה נכשלת רק בשלב האחרון בלי לומר למה. זה בדיוק מה שקרה.
valid_token() { printf '%s' "$1" | grep -qE '^[0-9]{6,}:[A-Za-z0-9_-]{30,}$'; }
mask() { printf '%s' "$1" | sed -E 's/^([0-9]+:.{4}).*(.{4})$/\1…\2/'; }

TOK=""
SRC=""
if [ -n "$ARG_TOKEN" ]; then
  if valid_token "$ARG_TOKEN"; then
    TOK="$ARG_TOKEN"; SRC="מהפקודה"
  else
    echo "  ✗ הטוקן שבפקודה אינו בצורה הנכונה: 123456789:AA..."; exit 1
  fi
fi
if [ -z "$TOK" ] && [ -n "${GROUPOS_TOKEN:-}" ] && valid_token "$GROUPOS_TOKEN"; then
  TOK="$GROUPOS_TOKEN"; SRC="ממשתנה הסביבה"
elif [ -n "${GROUPOS_TOKEN:-}" ]; then
  echo "  ⚠ משתנה הסביבה GROUPOS_TOKEN אינו נראה כמו טוקן — מתעלם ממנו."
  echo "    (לנקות אותו:  unset GROUPOS_TOKEN)"
fi
if [ -z "$TOK" ] && [ -f "$ENV" ]; then
  EXIST=$(grep '^GROUPOS_TOKEN=' "$ENV" 2>/dev/null | cut -d= -f2-)
  if valid_token "$EXIST"; then
    TOK="$EXIST"; SRC="מהקובץ הקיים"
  elif [ -n "$EXIST" ]; then
    echo "  ⚠ הטוקן שב-.env אינו תקין — נחליף אותו."
  fi
fi
while [ -z "$TOK" ]; do
  # /dev/tty ולא stdin: כך השאלה עובדת גם כשהסקריפט מגיע דרך צינור
  printf "  הדבק את הטוקן מ-BotFather: " > /dev/tty
  read -r TOK < /dev/tty || { echo; echo "  ✗ אין קלט"; exit 1; }
  if ! valid_token "$TOK"; then
    echo "  ✗ זה לא נראה כמו טוקן. הצורה היא 123456789:AA..." > /dev/tty
    TOK=""
  fi
done
echo "  ✓ טוקן $(mask "$TOK") ${SRC:-שהוזן עכשיו}"

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
# 78 = EX_CONFIG. טוקן שגוי לא יתקן את עצמו בניסיון ה-12, ולולאת
# הפעלה-מחדש על שרת שמזרים וידאו שורפת מעבד לחינם. נמדד: 9.35 שניות
# מעבד ב-11 ניסיונות, לפני שהתקרה הזאת נוספה.
RestartPreventExitStatus=78
StartLimitIntervalSec=120
StartLimitBurst=5
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
  if journalctl -u groupos --since "-2 min" 2>/dev/null | grep -q "אינו בצורה של טוקן"; then
    echo "  ✗ הטוקן ב-.env אינו תקין. הרץ:"
    echo "      bash /opt/groupos/install.sh --token <הטוקן מ-BotFather>"
    exit 1
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
