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
FAILED=0; APPLY=()
for f in "${CRITICAL[@]}"; do
  [ -f "$f" ] || { echo "  ✗ $f חסר (קריטי)"; FAILED=1; continue; }
  if out=$(python3 "$f" --check 2>&1); then
    echo "  ✓ $f"; APPLY+=("$f")
  else
    echo "  ✗ $f — $out"; FAILED=1
  fi
done
for f in "${OPTIONAL[@]}"; do
  [ -f "$f" ] || continue
  if out=$(python3 "$f" --check 2>&1); then
    echo "  ✓ $f (רשות)"; APPLY+=("$f")
  else
    echo "  ⊘ $f — מדולג: $(echo "$out" | head -1)"
  fi
done
[ "$FAILED" -eq 1 ] && { echo; echo "❌ פאץ' קריטי לא עבר. לא שונה כלום."; exit 1; }
[ "$DRY" -eq 1 ] && { echo; echo "✓ הכל עבר בדיקה יבשה. לא שונה כלום (--check)."; exit 0; }

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
chk() { # שם  כתובת  קוד-צפוי
  c=$(curl -s -o /dev/null -m 10 -w "%{http_code}" "$2")
  if [ "$c" = "$3" ]; then echo "  ✓ $1 ($c)"; else echo "  ✗ $1 — קיבלנו $c, ציפינו ל-$3"; OK=0; fi
}
chk "קטלוג"          "http://127.0.0.1:8000/content/version"  200
chk "גרסת אפליקציה"  "http://127.0.0.1:8000/app/version"      200
chk "קטלוג מקוצר"    "http://127.0.0.1:8000/content/lite?limit=5" 200
# 422 ולא 404: הנתיב קיים ורק חסרה כותרת המשתמש. 404 = הפאץ' לא נכנס.
chk "מועדפים"        "http://127.0.0.1:8000/api/favorites"    422
chk "רשימת חסרי טריילר" "http://127.0.0.1:8000/panel/no-trailer" 403
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
  for ((i=${#APPLY[@]}-1; i>=0; i--)); do
    python3 "${APPLY[$i]}" --revert 2>&1 | head -1
  done
  systemctl restart zovex-bot
  sleep 10
  c=$(curl -s -o /dev/null -m 10 -w "%{http_code}" http://127.0.0.1:8000/content/version)
  echo "אחרי ההחזרה: $c   (200 = השרת חזר לקדמותו)"
  exit 1
fi
