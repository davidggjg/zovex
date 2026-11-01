#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · קריאה אחת שנכשלה מחקה 25,084 פריטים.
#
# מתוארך לשנייה לפי הגיבויים:
#   18:17  25,084 פריטים  31.6MB
#   18:18       6 פריטים   3KB
#
# והמספר 6 הוא בדיוק מספר הפרקים בסדרה שהועלתה באותו רגע: הכותב קרא את
# הקטלוג, קיבל רשימה ריקה, הוסיף את ששת הפרקים, ושמר.
#
# השורש: load_content מחזיר [] על **כל** כשל קריאה. הקורא אינו יכול
# להבחין בין "הקטלוג ריק" ל"לא הצלחתי לקרוא", והכותב הבא שומר את הריק.
#
# שתי שכבות:
#   1. load_content מנסה את שלושת הגיבויים האחרונים לפני שהוא מוותר.
#   2. save_content דוחה שמירה שמקטינה קטלוג של 100+ פריטים ביותר
#      ממחצית. זו השכבה החשובה — היא חוסמת את הנזק בלי קשר לסיבה, גם
#      מבאג עתידי וגם מסקריפט שגוי.
#
# מחיקה המונית מכוונת עדיין אפשרית: CONTENT_ALLOW_SHRINK=1
#
#   sudo bash deploy_content_guard.sh
#   sudo bash deploy_content_guard.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

SVC=zovex-bot
DIR=/opt/zovex-bot
LIVE="$DIR/main.py"
PY="$DIR/venv/bin/python"
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/patch_content_guard.py"
API="http://127.0.0.1:8000"

die() { echo "❌ $*" >&2; exit 1; }
wait_up() {
  for _ in $(seq 1 80); do
    curl -fsS -m 3 "$API/ping" >/dev/null 2>&1 && return 0
    sleep 3
  done
  return 1
}

[ -f "$LIVE" ] || die "$LIVE לא קיים — זה לא שרת ZOVEX"
[ -x "$PY" ]   || PY=python3
curl -fsSL "$RAW" -o /tmp/patch_content_guard.py || die "הורדת הטלאי נכשלה"

if [ "${1:-}" = "--rollback" ]; then
  "$PY" /tmp/patch_content_guard.py "$LIVE" --revert || die "השחזור נכשל"
  systemctl restart "$SVC" || die "restart נכשל"
  wait_up && echo "✅ שוחזר" || echo "⚠️  שוחזר, אבל /ping לא ענה"
  exit 0
fi

echo "① מסיר גרסה קודמת אם קיימת"
"$PY" /tmp/patch_content_guard.py "$LIVE" --revert >/dev/null 2>&1 \
  && echo "   הוסרה" || echo "   אין קודמת — ממשיך"

echo "② מחיל"
"$PY" /tmp/patch_content_guard.py "$LIVE" || die "לא הוחל"

echo "③ מפעיל מחדש (הבוטים עולים בהדרגה — כ-2 דקות)"
systemctl restart "$SVC" || die "restart נכשל"
wait_up || die "/ping לא ענה.  לשחזור: sudo bash $0 --rollback"

echo
echo "④ מאמת שההגנה חיה ושהקטלוג שלם"
curl -fsS -m 60 "$API/content/lite" | "$PY" -c 'import json,sys
n = len(json.load(sys.stdin))
print("   בקטלוג: " + str(n) + " פריטים")
if n < 1000:
    sys.exit("   ❌ הקטלוג קטן מדי — אל תמשיך, שחזר מגיבוי")' \
  || die "האימות נכשל.  לשחזור: sudo bash $0 --rollback"
grep -q "content_guard" "$LIVE" && echo "   ✓ ההגנה בקוד" \
  || die "ההגנה לא נמצאה בקובץ החי"

cat <<EOF

────────────────────────────────────────────────────────────
✅ נפרס.

עכשיו שלח לבוט קובץ, ובמקביל:

  journalctl -u zovex-bot -f | grep --line-buffered -i upload_bot

אמורה להופיע מיד שורה:
  upload_bot: התקבלה הודעה (מדיה) מ-<המזהה שלך>

זו השורה שלא הייתה קיימת, ובגללה שקט נראה בדיוק כמו תקלה.

מה שרץ מעכשיו ברקע:
  · פינג לבוט ההעלאה כל 5 דקות
  · שני כישלונות רצופים → נבנה מחדש מאפס, רק הוא
  · הצופים, הסטרימינג ושאר הבוטים לא מושפעים

שני כישלונות ולא אחד: פספוס בודד יכול להיות עומס רגעי בזמן הזרמה,
ובנייה מחדש על כל רעש היא תרופה גרועה מהמחלה.

לשחזור:  sudo bash /tmp/deploy_content_guard.sh --rollback
EOF
