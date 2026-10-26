#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · סוף העיוורון: זיהוי FLOOD_PREMIUM_WAIT.
#
# הרקע המלא ב-patch_flood_premium.py. בקצרה: Pyrogram 2.0.106 (דצמבר 2022)
# אינו מכיר את FLOOD_PREMIUM_WAIT (שטלגרם הוסיפו ב-2024). אומת על השרת —
# המחרוזת לא קיימת בספריית השגיאות. לכן השגיאה נפלה ל-except הגנרי,
# נספרה ככשל רך, והקוד המשיך להפציץ את אותו בוט במקום להמתין כפי שטלגרם
# ביקש.
#
# המשמעות: "אפס FloodWait ב-24 שעות" מדד שלא זיהינו אותה — לא שהיא לא
# קרתה.
#
# ## למה זה חייב להיות ראשון
#
# כל שיפור ביצועים שנעשה (512KB, יותר חיבורים, פיזור בין בוטים) מגדיל את
# הסיכוי לפגוע בתקרה של טלגרם. בלי הזיהוי הזה נראה בוטים "נכשלים" בלי
# לדעת למה, ונסיק שחוסמים אותנו.
#
# ## מה זה לא עושה
#
# לא משנה ביצועים ולא נוגע במקביליות. זו עין, לא מנוע.
#
#   sudo bash deploy_flood_premium.sh
#   sudo bash deploy_flood_premium.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

SVC=zovex-bot
DIR=/opt/zovex-bot
LIVE="$DIR/main.py"
PY="$DIR/venv/bin/python"
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/patch_flood_premium.py"
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
curl -fsSL "$RAW" -o /tmp/patch_flood_premium.py || die "הורדת הטלאי נכשלה"

if [ "${1:-}" = "--rollback" ]; then
  "$PY" /tmp/patch_flood_premium.py "$LIVE" --revert || die "השחזור נכשל"
  systemctl restart "$SVC" || die "restart נכשל"
  wait_up && echo "✅ שוחזר" || echo "⚠️  שוחזר, אבל /ping לא ענה"
  exit 0
fi

echo "① מאמת שהספרייה באמת לא מכירה את השגיאה"
if grep -rqs "FLOOD_PREMIUM_WAIT" "$DIR"/venv/lib/python3*/site-packages/pyrogram/errors/ 2>/dev/null; then
  echo "   ⚠️  הספרייה כן מכירה אותה — כלומר שודרגה מאז הבדיקה."
  echo "       התיקון עדיין בטוח (הוא רק מוסיף זיהוי ומונה), אבל ההנחה השתנתה."
else
  echo "   ✓ לא קיימת בספרייה — העיוורון מאומת"
fi

echo "② מחיל (התאמה מדויקת, או סירוב בלי לגעת)"
"$PY" /tmp/patch_flood_premium.py "$LIVE" || die "לא הוחל — הקובץ לא שונה."

echo "③ מפעיל מחדש (הבוטים עולים בהדרגה — דקות)"
systemctl restart "$SVC" || die "restart נכשל"
wait_up || die "/ping לא ענה.  לשחזור: sudo bash $0 --rollback"

echo
echo "④ מאמת שהמונה חי בתהליך"
curl -fsS -m 15 "$API/debug/caches" | "$PY" -c 'import json,sys
d = json.load(sys.stdin)
if "flood_premium" not in d:
    sys.exit("   ❌ המונה לא מופיע — הקוד הישן עדיין רץ")
print("   flood_premium = " + str(d["flood_premium"]))' \
  || die "האימות נכשל.  לשחזור: sudo bash $0 --rollback"

cat <<EOF

────────────────────────────────────────────────────────────
✅ נפרס. זה לא משנה ביצועים — זו עין.

מחר, אחרי ערב אחד של שימוש אמיתי:

  curl -s $API/debug/caches | grep -o '"flood_premium":[0-9]*'

  · גדול מ-0  → טלגרם כן חונקים אותנו, ועד היום לא ידענו.
                כל העלאת מקביליות תחמיר, וצריך קודם לפזר עומס.
  · 0         → יש מרווח אמיתי, ואפשר לטפס בביטחון ל-512KB,
                יותר חיבורים ופיזור בין בוטים.

ובלוג אפשר לראות כל פגיעה בזמן אמת:
  journalctl -u zovex-bot -f | grep FLOOD_PREMIUM

לשחזור:  sudo bash /tmp/deploy_flood_premium.sh --rollback
EOF
