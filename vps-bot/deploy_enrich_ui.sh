#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · כרטיס הסורק בפאנל — הפעלה, עצירה, התקדמות והצעות.
#
# הסריקה רצה בשרת כמשימת asyncio ולכן ממשיכה גם כשהדפדפן סגור. הכרטיס
# הוא חלון להסתכל דרכו, לא המנוע: סגירת הדפדפן עוצרת רק את הסקר.
#
# שינוי בקובץ admin.html בלבד — אין נגיעה בקוד השרת ואין restart.
#
#   sudo bash deploy_enrich_ui.sh
#   sudo bash deploy_enrich_ui.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

DIR=/opt/zovex-bot
PANEL="$DIR/admin.html"
PY="$DIR/venv/bin/python"
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/patch_enrich_ui.py"
API="http://127.0.0.1:8000"

die() { echo "❌ $*" >&2; exit 1; }

[ -f "$PANEL" ] || die "$PANEL לא קיים — זה לא שרת ZOVEX"
[ -x "$PY" ]    || PY=python3
curl -fsSL "$RAW" -o /tmp/patch_enrich_ui.py || die "הורדת הטלאי נכשלה"

if [ "${1:-}" = "--rollback" ]; then
  "$PY" /tmp/patch_enrich_ui.py "$PANEL" --revert || die "השחזור נכשל"
  echo "✅ שוחזר — רענן את הפאנל עם Ctrl+Shift+R"
  exit 0
fi

echo "① בודק שנקודות הקצה של הסורק קיימות בשרת"
curl -fsS -m 10 -o /dev/null -w '' -X POST "$API/panel/enrich/status" \
  -H 'Content-Type: application/json' -d '{"password":"x"}' 2>/dev/null
case $? in
  0|22) echo "   ✓ הנתיב קיים" ;;
  *)    die "נקודות הקצה חסרות — הרץ קודם: sudo bash /tmp/deploy_enrich.sh" ;;
esac

# הטלאי מדלג על קובץ שכבר הוחל (בדיקת סימון), ולכן הרצה חוזרת לא
# שדרגה גרסה קיימת — זה בדיוק מה שהשאיר בשרת גרסה ישנה בלי
# שאיש הבחין. הסרה לפני החלה פותרת את זה: הגיבוי קיים, והשחזור
# מחזיר בדיוק את הקובץ שלפני הטלאי.
echo "② מסיר גרסה קודמת אם קיימת"
"$PY" /tmp/patch_enrich_ui.py "$PANEL" --revert >/dev/null 2>&1 \
  && echo "   הוסרה" || echo "   אין קודמת — ממשיך"

echo "③ מחיל"
"$PY" /tmp/patch_enrich_ui.py "$PANEL" || die "לא הוחל"

cat <<EOF

────────────────────────────────────────────────────────────
✅ נפרס. אין restart — רק רענן עם Ctrl+Shift+R.

בלשונית «חסרים» יש עכשיו כרטיס «🔎 סורק השלמות»:

  ▶ הפעל סריקה   ■ עצור   📋 הצעות קטגוריה

  · פס התקדמות וזמן משוער
  · תיאורים / מתורגמים / פוסטרים / הצעות — בזמן אמת
  · «אשר הכל» מחיל את כל ההצעות
  · «בטל שינוי אחרון» מחזיר אותן

אפשר לסגור את הדפדפן באמצע — הסריקה ממשיכה בשרת.
כשתחזור ללשונית, המספרים יתעדכנו מהמקום שבו היא נמצאת.

לשחזור:  sudo bash /tmp/deploy_enrich_ui.sh --rollback
EOF
