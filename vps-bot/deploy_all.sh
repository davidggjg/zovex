#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# פריסת כל השינויים לשרת, עם החזרה אוטומטית אם משהו נשבר.
#
# הסדר אינו שרירותי: קודם בדיקה יבשה של *כל* הפאצ'ים, ורק אם כולם עוברים
# מחילים. פאץ' שנכשל באמצע היה משאיר את main.py חצי-מעודכן.
#
# אחרי ההפעלה מחדש נבדקת בריאות אמיתית — לא "השירות רץ" אלא "הנקודות
# עונות". שירות שעלה ונפל בייבוא נראה 'active' לרגע, ובדיוק ככה הופל
# האתר בעבר.
#
#   bash deploy_all.sh --check     בדיקה יבשה בלבד, לא נוגע בכלום
#   bash deploy_all.sh             פריסה מלאה
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail
cd /opt/zovex-bot || { echo "❌ /opt/zovex-bot לא נמצא"; exit 1; }

RAW="https://raw.githubusercontent.com/davidggjg/zovex/claude/hls-relay-schema-port-ll8xiz/vps-bot"
DRY=0; [ "${1:-}" = "--check" ] && DRY=1

# קריטי = כישלון שלו עוצר הכל.  רשות = מדלגים עליו בשקט אם אינו מתאים.
CRITICAL=(fix_pool_session_leak.py fix_add_favorites.py fix_add_trailers.py fix_content_lang.py)
CRITICAL+=(fix_manual_trailer.py)
OPTIONAL=(fix_panel_series_category.py fix_panel_trailer.py fix_drive_gdown.py fix_drive_progress.py)

echo "════════ 1/5 · מוריד את הסקריפטים ════════"
for f in "${CRITICAL[@]}" "${OPTIONAL[@]}"; do
  if curl -fsSL -o "$f" "$RAW/$f"; then
    python3 -c "import ast,sys;ast.parse(open('$f').read())" 2>/dev/null \
      && echo "  ✓ $f" || { echo "  ✗ $f ירד פגום"; exit 1; }
  else
    echo "  ⚠ $f לא ירד — ידולג"
  fi
done

echo
echo "════════ 2/5 · בדיקה יבשה ════════"
# הבדיקה רצה על *עותקים*, ומחילה את הפאצ'ים עליהם לפי הסדר.
# בדיקה של כל פאץ' בבידוד אינה אפשרית: פאץ' שתלוי בקודמו בודק מול הקובץ
# כמו שהוא, שבו התלות עוד לא הוחלה — ולכן הוא נכשל תמיד, גם כשהרצף תקין.
# כאן נבדק מה שבאמת יקרה: הרצף כולו, מתחילתו ועד סופו.
SIM=$(mktemp -d); cp main.py "$SIM/main.py"; cp admin.html "$SIM/admin.html"
trap 'rm -rf "$SIM"' EXIT

FAILED=0; APPLY=(); ALREADY=()
target_env() {   # איזה קובץ הפאץ' עורך
  grep -q 'ADMIN_HTML' "$1" && echo "ADMIN_HTML=$SIM/admin.html" || echo "BOT_PY=$SIM/main.py"
}
classify() {     # $1=קובץ  $2="קריטי"|"רשות"
  local f="$1" kind="$2" out ev
  ev=$(target_env "$f")
  # מריצים בפועל על העותק: כך הפאץ' הבא רואה את התוצאה של הקודם.
  if out=$(env "$ev" python3 "$f" 2>&1); then
    if echo "$out" | grep -q "כבר"; then
      echo "  ● $f — כבר מוחל, לא ניגע"; ALREADY+=("$f")
    else
      echo "  ✓ $f"; APPLY+=("$f")
    fi
  else
    if [ "$kind" = "קריטי" ]; then echo "  ✗ $f — $(echo "$out" | head -1)"; FAILED=1
    else echo "  ⊘ $f — מדולג: $(echo "$out" | head -1)"; fi
  fi
}
for f in "${CRITICAL[@]}"; do
  [ -f "$f" ] || { echo "  ✗ $f חסר (קריטי)"; FAILED=1; continue; }
  classify "$f" "קריטי"
done
for f in "${OPTIONAL[@]}"; do
  [ -f "$f" ] || continue
  classify "$f" "רשות"
done
# התוצאה הסופית חייבת לעבור קומפילציה — לא רק כל פאץ' בנפרד.
if ! python3 -c "import ast,sys;ast.parse(open('$SIM/main.py',encoding='utf-8').read())" 2>/dev/null; then
  echo "  ✗ התוצאה המשולבת אינה עוברת קומפילציה"; FAILED=1
fi
[ "$FAILED" -eq 1 ] && { echo; echo "❌ הרצף לא עבר. לא שונה כלום."; exit 1; }

echo
echo "  להחלה עכשיו: ${#APPLY[@]}   ·   כבר מוחלים: ${#ALREADY[@]}"
[ "$DRY" -eq 1 ] && { echo; echo "✓ הרצף כולו עבר על עותקים. לא שונה כלום (--check)."; exit 0; }
if [ ${#APPLY[@]} -eq 0 ]; then
  echo; echo "✓ הכל כבר מוחל. אין מה לעשות."; exit 0
fi

echo
echo "════════ 3/5 · מחיל ════════"
for f in "${APPLY[@]}"; do
  if out=$(python3 "$f" 2>&1); then echo "  ✓ $f"; else echo "  ✗ $f — $out"; fi
done

echo
echo "════════ 4/5 · מפעיל מחדש ════════"
systemctl restart zovex-bot
for i in $(seq 1 30); do
  sleep 2
  code=$(curl -s -o /dev/null -m 5 -w "%{http_code}" http://127.0.0.1:8000/content/version)
  [ "$code" = "200" ] && { echo "  ✓ השירות עונה אחרי $((i*2)) שניות"; break; }
done

echo
echo "════════ 5/5 · אימות ════════"
OK=1
# הארגומנט השלישי יכול להיות כמה קודים מקובלים, מופרדים ב-|.
# קיבוע קוד יחיד הפיל פריסה תקינה: נקודה מוגנת החזירה 401 ("סיסמה שגויה")
# במקום 403, כי בדיקת הסיסמה נכשלת לפני בדיקת התפקיד. מה שהבדיקה באמת
# אמורה לוודא הוא שהנתיב *קיים* — וכל תשובה שאינה 404 מוכיחה את זה.
chk() { # שם  כתובת  "קוד|קוד|…"
  c=$(curl -s -o /dev/null -m 10 -w "%{http_code}" "$2")
  case "|$3|" in
    *"|$c|"*) echo "  ✓ $1 ($c)" ;;
    *) echo "  ✗ $1 — קיבלנו $c, ציפינו לאחד מ-$3"; OK=0 ;;
  esac
}
chk "קטלוג"          "http://127.0.0.1:8000/content/version"  200
chk "גרסת אפליקציה"  "http://127.0.0.1:8000/app/version"      200
chk "קטלוג מקוצר"    "http://127.0.0.1:8000/content/lite?limit=5" 200
# 422 ולא 404: הנתיב קיים ורק חסרה כותרת המשתמש. 404 = הפאץ' לא נכנס.
chk "מועדפים"        "http://127.0.0.1:8000/api/favorites"    422
chk "רשימת חסרי טריילר" "http://127.0.0.1:8000/panel/no-trailer" "401|403"
ITEM=$(curl -s -m 15 "http://127.0.0.1:8000/content/lite?limit=1" | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['id'])" 2>/dev/null)
[ -n "$ITEM" ] && chk "טריילר" "http://127.0.0.1:8000/content/trailer/$ITEM" 200
[ -n "$ITEM" ] && chk "פריט באנגלית" "http://127.0.0.1:8000/content/item/$ITEM?lang=en" 200
if grep -q "קבע קטגוריה לכל הסדרה" admin.html 2>/dev/null; then
  echo "  ✓ כפתור הקטגוריה בפאנל"
else
  echo "  ⊘ כפתור הקטגוריה לא נמצא (ייתכן שהפאץ' דולג)"
fi

echo
if [ "$OK" -eq 1 ]; then
  echo "════════════════════════════════════════"
  echo "✅ הפריסה הצליחה. כל הבדיקות עברו."
  echo "   רענן את הפאנל ב-Ctrl+Shift+R."
  echo "════════════════════════════════════════"
  echo
  echo "── דליפת ה-sessions (היו 90 יתומים) ──"
  sleep 20
  n=$(journalctl -u zovex-bot --since "-1 min" --no-pager | grep -ao "0x[0-9a-f]\{10,\}" | sort -u | wc -l)
  echo "   כתובות transport בדקה האחרונה: $n   (0-3 = נוקה)"
else
  echo "════════════════════════════════════════"
  echo "🔴 האימות נכשל — מחזיר הכל אחורה"
  echo "════════════════════════════════════════"
  if [ ${#APPLY[@]} -eq 0 ]; then
    echo "לא הוחל דבר בהרצה הזו — אין מה להחזיר. הכישלון קדם לפריסה."
  else
    # רק מה שהוחל *כאן*. ALREADY לא נוגעים בו: החזרה שלו הייתה מוחקת
    # פריסות קודמות שלא קשורות לכישלון הנוכחי.
    for ((i=${#APPLY[@]}-1; i>=0; i--)); do
      python3 "${APPLY[$i]}" --revert 2>&1 | head -1
    done
  fi
  systemctl restart zovex-bot
  sleep 10
  c=$(curl -s -o /dev/null -m 10 -w "%{http_code}" http://127.0.0.1:8000/content/version)
  echo "אחרי ההחזרה: $c   (200 = השרת חזר לקדמותו)"
  exit 1
fi
