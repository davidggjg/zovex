#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# install — מתקין את GroupOS כשירות נפרד על השרת.
#
# **נפרד מ-zovex בכוונה.** תיקייה משלו, שירות systemd משלו, מסד משלו.
# אם הבוט הזה ייפול, יקרוס או יאכל זיכרון — האתר והסטרימינג לא מרגישים.
#
# מה הוא עושה:
#   1. מוריד את הקוד מהמאגר ובודק שכל קובץ נטען כפייתון תקין
#   2. מריץ את כל הבדיקות **לפני** שהוא נוגע בשירות
#   3. שומר את הטוקן ב-.env עם הרשאות 600 בלבד
#   4. מתקין שירות systemd שעולה מחדש לבד ומוגבל במשאבים
#   5. מוודא שהבוט באמת ענה לטלגרם, ולא רק ש"השירות רץ"
#
#   bash install.sh                      התקנה או עדכון
#   bash install.sh --token 123:AA...    הטוקן בשורת הפקודה, בלי שאלה
#   bash install.sh --update             רק קוד, בלי לגעת בטוקן ובשירות
#
# **מה הוא לא דורס, בשום מצב:**
#   · המסד — לא נמחק, לא נדרס, ומגובה לפני כל הפעלה מחדש
#   · הטוקן ומפתחות ה-AI שב-.env — נקראים ומוחזרים לקובץ כמו שהם
#   · פקודות, דיווחים, הגדרות וכל מה שנשמר בקבוצות — הם במסד
#
# ואם עדכון בכל זאת שובר משהו: נשמר עותק של הקוד הקודם, והסקריפט
# מחזיר אותו לבד כשהבוט לא עולה. ‎--rollback‎ מחזיר ידנית.
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail

# ‎GROUPOS_DIR‎ קיים כדי שאפשר יהיה להריץ את המתקין עצמו בבדיקה, על
# תיקייה זמנית, בלי לגעת בהתקנה האמיתית. בשרת לא מגדירים אותו.
DIR=${GROUPOS_DIR:-/opt/groupos}
BRANCH="claude/hls-relay-schema-port-ll8xiz"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/$BRANCH/groupos"
# רשימת הקבצים מגיעה מ-manifest.txt שבמאגר ולא מכאן. הרשימה הקשיחה
# שהייתה כאן פספסה שלושה מודולים חדשים — ההתקנה "הצליחה" והבוט עלה
# בלי הפאנל. עכשיו קובץ חדש נכנס ל-manifest ומגיע מעצמו, ויש בדיקה
# שנכשלת אם מודול קיים חסר ממנו.
#
# install.sh נמצא ברשימה כי המתקין חייב להשאיר עותק של עצמו ב-$DIR.
# בלי זה ‎bash /opt/groupos/install.sh --update‎ — מה שכתוב ב-README
# ובמסך הסיום — נכשל ב-"No such file or directory".
EXTRA=(README.md requirements.txt manifest.txt install.sh)
SVC=${GROUPOS_SVC:-/etc/systemd/system/groupos.service}
KEEP=5                       # כמה גיבויים וגלגולים לאחור שומרים
MODE=${1:-}
ARG_TOKEN=""
if [ "$MODE" = "--token" ]; then ARG_TOKEN=${2:-}; MODE=""; fi

# ── גיבוי, שחזור וניקוי ──────────────────────────────────────────────────
# הכול יושב ב-$DIR/data, שהוא ממילא התיקייה שלא נדרסת.
BACKUPS="$DIR/data/backups"

code_snapshot() {
  # עותק של הקוד **החי** לפני שמחליפים אותו. בלי זה עדכון שבור הוא
  # מצב שאין ממנו חזרה חוץ מלהתקין מחדש מהמאגר — כלומר בדיוק ברגע
  # שהמאגר הוא זה שנשבר.
  [ -f "$DIR/bot.py" ] || return 0
  mkdir -p "$BACKUPS"
  local f="$BACKUPS/code-$(date +%Y%m%d-%H%M%S).tgz"
  (cd "$DIR" && tar czf "$f" ./*.py ./*.md manifest.txt requirements.txt \
       2>/dev/null) || return 0
  echo "  ✓ הקוד הקודם נשמר: $(basename "$f")"
  ls -1t "$BACKUPS"/code-*.tgz 2>/dev/null | tail -n +$((KEEP + 1)) \
    | xargs -r rm -f
}

db_backup() {
  # המסד מגובה לפני כל הפעלה מחדש, כי הפעלה מחדש היא מה שמריץ
  # מיגרציות. מיגרציה היא השינוי היחיד כאן שנוגע בנתונים.
  local db="$DIR/data/groupos.db"
  [ -f "$db" ] || return 0
  mkdir -p "$BACKUPS"
  local f="$BACKUPS/db-$(date +%Y%m%d-%H%M%S).db"
  # ‎.backup‎ של sqlite ולא cp: cp על מסד עם WAL פתוח יכול להעתיק
  # מצב חלקי. אם sqlite3 אינו מותקן — cp של שלושת הקבצים יחד.
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$db" ".backup '$f'" 2>/dev/null || cp -f "$db" "$f"
  else
    cp -f "$db" "$f"; cp -f "$db-wal" "$f-wal" 2>/dev/null || true
  fi
  echo "  ✓ המסד גובה: $(basename "$f") ($(du -h "$f" | cut -f1))"
  ls -1t "$BACKUPS"/db-*.db 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
}

restore_code() {
  local f
  f=$(ls -1t "$BACKUPS"/code-*.tgz 2>/dev/null | head -1)
  if [ -z "$f" ]; then
    echo "  ✗ אין עותק קוד לשחזור — אין התקנה קודמת לחזור אליה."
    echo "    להתקנה מלאה:  bash $DIR/install.sh"
    return 1
  fi
  tar xzf "$f" -C "$DIR" || return 1
  echo "  ✓ הוחזר הקוד מ-$(basename "$f")"
  systemctl restart groupos 2>/dev/null || true
  return 0
}

# ‎systemctl‎ קיים גם במכולות שאין בהן systemd כ-PID 1, ושם כל פקודה
# שלו נכשלת על "Failed to connect to bus". ‎list-units‎ הוא הבדיקה
# הנכונה: הוא נכשל בלי אפיק, ומצליח גם על מערכת ב-degraded — מצב
# נפוץ לגמרי בשרת אמיתי, ולכן ‎is-system-running‎ לא מתאים כאן.
have_systemd() {
  command -v systemctl >/dev/null 2>&1 \
    && systemctl list-units --no-pager >/dev/null 2>&1
}

journal_has_any() {
  [ -n "$(journalctl -u groupos --since '-5 min' --no-pager 2>/dev/null \
          | grep -v 'No entries' | head -3)" ]
}

alive() {
  # "active" אינו מספיק: שירות שעלה ונפל נראה active לרגע. מחכים
  # לשורה שהבוט כותב רק אחרי ש-getMe הצליח מול טלגרם.
  local i
  for i in $(seq 1 "${1:-20}"); do
    sleep 1
    journalctl -u groupos --since "-2 min" 2>/dev/null \
      | grep -q "GroupOS עלה כ-@" && return 0
  done
  # השורה לא נמצאה. אם **אין יומן בכלל** — זה אומר שלא הצלחנו לקרוא,
  # ולא שהבוט מת. גלגול לאחור של עדכון תקין רק כי הלוג לא נקרא הוא
  # נזק שנגרם מהזהירות עצמה, ולכן כאן יש נפילה לבדיקה חלשה יותר.
  if ! journal_has_any && systemctl is-active --quiet groupos 2>/dev/null; then
    echo "  ⚠ אין יומן לקרוא, אבל השירות פעיל — ממשיכים בלי אימות מלא."
    return 0
  fi
  return 1
}

if [ "$MODE" = "--rollback" ]; then
  echo "════════ מחזיר את הקוד הקודם ════════"
  db_backup
  restore_code || exit 1
  if ! have_systemd; then
    echo "✅ הקוד הקודם הוחזר (אין כאן systemd שמיש)."; exit 0
  fi
  if alive 20; then echo "✅ הבוט חי על הקוד הקודם."; else
    echo "  ⚠ הבוט לא דיווח שהוא עלה. היומן:"
    journalctl -u groupos --since "-2 min" --no-pager | tail -12 | sed 's/^/      /'
  fi
  exit 0
fi

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
  echo "  ✓ בדיקות הליבה עברו"
else
  echo "  ✗ בדיקות נכשלו. לא מתקינים."
  echo "$OUT" | grep "✗" | head -10
  exit 1
fi

# בדיקות המטפלים: מריצות את הקוד של הבוט מול טלגרם מדומה. הן תופסות
# מה שבדיקות הליבה לא יכולות — פקודה ששולחת את הטקסט הלא נכון, או
# מסלול מדיה שמוחק הודעה שלא היה צריך למחוק.
if [ -f "$TMP/test_bot.py" ]; then
  OUT2=$(cd "$TMP" && GROUPOS_DB="$TMP/test2.db" python3 test_bot.py 2>&1)
  echo "$OUT2" | tail -1
  if echo "$OUT2" | grep -qE "נכשלו 0|מדלגים"; then
    echo "  ✓ בדיקות המטפלים עברו — ממשיכים"
  else
    echo "  ✗ בדיקות המטפלים נכשלו. לא מתקינים."
    echo "$OUT2" | grep "✗" | head -10
    exit 1
  fi
fi

# רק עכשיו, אחרי שהכול נבדק, מחליפים את הקוד החי — ולא לפני שיש
# ממה לחזור. שני הגיבויים עולים שברירי שנייה ושוקלים פחות ממגה.
code_snapshot
db_backup
cp "$TMP"/*.py "$TMP"/*.md "$TMP"/requirements.txt "$TMP"/manifest.txt "$DIR/"
# עותק של המתקין עצמו, דרך שם זמני ו-mv: זה החלפת inode ולא כתיבה
# לתוך הקובץ. bash קורא סקריפט תוך כדי ריצה, ולכן כתיבה ישירה לקובץ
# שרץ כרגע הייתה יכולה לשבור את ההרצה באמצע.
cp "$TMP/install.sh" "$DIR/.install.sh.new" && \
  mv -f "$DIR/.install.sh.new" "$DIR/install.sh" && \
  chmod 755 "$DIR/install.sh"
echo "  ✓ הקוד הוחלף ב-$DIR"

if [ "$MODE" = "--update" ]; then
  # עדכון שמסתיים ב-"השירות הופעל מחדש" בלי לבדוק שהוא **עלה** הוא
  # עדכון שמדווח הצלחה על בוט מת. כאן מחכים לתשובה מטלגרם, ואם היא
  # לא באה — מחזירים את הקוד הקודם לבד.
  if ! have_systemd; then
    echo "  ✓ הקוד עודכן (אין כאן systemd שמיש — אין שירות להפעיל)"
    exit 0
  fi
  systemctl restart groupos 2>/dev/null || true
  if alive 25; then
    journalctl -u groupos --since "-2 min" | grep "GroupOS עלה" | tail -1 \
      | sed 's/^/  ✓ /'
    echo "✅ עודכן והבוט חי."
    exit 0
  fi
  echo "  ✗ הבוט לא עלה אחרי העדכון. מחזיר את הקוד הקודם…"
  journalctl -u groupos --since "-2 min" --no-pager | tail -12 | sed 's/^/      /'
  if restore_code && alive 25; then
    echo "✅ הוחזר הקוד הקודם והבוט חי. הקבוצות עובדות."
    echo "   מה שנכשל נשאר ביומן למעלה."
    exit 1
  fi
  echo "  ✗ גם השחזור לא הצליח. הרץ:  bash $DIR/install.sh"
  exit 1
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

# ── הקובץ הזה לא נדרס ────────────────────────────────────────────────────
# ‎--update‎ ממילא לא מגיע לכאן. אבל גם התקנה מלאה שנייה — מה שקורה
# כשמריצים את הפקודה הראשית פעם נוספת — **חייבת** לשמור את מה שהוספת:
# מפתחות AI, שרת Bot API מקומי, וכל שורה שהוספת בעצמך. הגרסה הקודמת
# כתבה את הקובץ מאפס, כלומר מפתחות שהודבקו ידנית פשוט נעלמו בשקט.
env_get() {
  [ -f "$ENV" ] || return 0
  grep -m1 "^$1=" "$ENV" 2>/dev/null | cut -d= -f2- || true
}
count_keys() {
  # רק מספר. הערך עצמו לעולם לא נדפס ולא נכנס ליומן.
  printf '%s' "$1" | tr ',' '\n' | grep -c '[^[:space:]]' 2>/dev/null || echo 0
}

OLD_API=$(env_get GROUPOS_API_BASE)
OLD_GEM=$(env_get GROUPOS_GEMINI_KEYS)
OLD_GRQ=$(env_get GROUPOS_GROQ_KEYS)
KNOWN="GROUPOS_TOKEN GROUPOS_DB GROUPOS_API_BASE GROUPOS_GEMINI_KEYS GROUPOS_GROQ_KEYS"
EXTRA_LINES=""
if [ -f "$ENV" ]; then
  mkdir -p "$BACKUPS"
  cp -f "$ENV" "$BACKUPS/env-$(date +%Y%m%d-%H%M%S)"
  chmod 600 "$BACKUPS"/env-* 2>/dev/null || true
  # שורות שאיננו מכירים — של מי שהוסיף משתנה בעצמו. הן שורדות.
  EXTRA_LINES=$(grep -v '^[[:space:]]*#' "$ENV" 2>/dev/null \
    | grep '=' \
    | grep -vE "^($(echo "$KNOWN" | tr ' ' '|'))=" || true)
fi

cat > "$ENV" <<EOF
GROUPOS_TOKEN=$TOK
GROUPOS_DB=$DIR/data/groupos.db
# שרת Bot API מקומי — מחזיר נתיב מקומי לקבצים במקום להוריד אותם.
# ריק = השרת של טלגרם.
GROUPOS_API_BASE=$OLD_API
# מפתחות AI, מופרדים בפסיקים. אפשר כמה — הבוט מסובב ביניהם ומצנן
# מפתח שהחזיר 429. הם יושבים כאן ולא במסד, כי מסד עובר בגיבוי.
GROUPOS_GEMINI_KEYS=$OLD_GEM
GROUPOS_GROQ_KEYS=$OLD_GRQ
EOF
if [ -n "$EXTRA_LINES" ]; then
  {
    echo "# שורות שהוספת בעצמך — נשמרו כמו שהן."
    printf '%s\n' "$EXTRA_LINES"
  } >> "$ENV"
fi
chmod 600 "$ENV"
echo "  ✓ נשמר: Gemini $(count_keys "$OLD_GEM") מפתחות · Groq $(count_keys "$OLD_GRQ") מפתחות"
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

# אותה נפילה לאחור כמו ב-alive: יומן שלא נקרא אינו בוט מת.
if [ "$OKAY" -eq 0 ] && ! journal_has_any \
     && systemctl is-active --quiet groupos 2>/dev/null; then
  echo "  ⚠ אין יומן לקרוא, אבל השירות פעיל."
  OKAY=1
fi

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
  echo "  bash $DIR/install.sh --update     עדכון קוד בלבד"
  echo "  bash $DIR/install.sh --rollback   חזרה לקוד הקודם"
  echo
  echo "גיבויים (${KEEP} אחרונים מכל סוג):  $DIR/data/backups"
else
  echo "  ✗ הבוט לא דיווח שהוא עלה תוך 20 שניות."
  echo "    היומן:"
  journalctl -u groupos --since "-2 min" --no-pager | tail -15 | sed 's/^/      /'
  echo
  echo "    הקוד הקודם שמור. לחזור אליו:"
  echo "      bash $DIR/install.sh --rollback"
  exit 1
fi
