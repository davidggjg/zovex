#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · הספסל נשען על מדד שאינו מודד קיבולת — וצבע כמעט כל בוט ככתום.
#
# note_bot_speed מודד בייטים שהוגשו חלקי זמן. בהזרמת וידאו הנגן קובע את
# הקצב — הוא מושך בקצב הסרט, והלחץ החוזר של ה-TCP עוצר את הגנרטור. סרט
# 2GB בשעתיים הוא 0.28 MB/s, וזה בדיוק מה שיימדד גם אם הבוט מסוגל לפי
# עשרים.
#
# נמדד בפאנל: 24 בוטים בין 0.01 ל-0.57 MB/s, ואחד על 5.94 — וההבדל היחיד
# הוא שהאחרון הגיש משיכה מהירה ולא צפייה. הרצפה (0.6) גבוהה מקצב הביט של
# רוב הקטלוג, ולכן סימנה בוטים בריאים לגמרי כאיטיים.
#
# זו טעות בתכנון שלי, לא חניקה של טלגרם ולא עומס שאנחנו יוצרים.
#
# ## התיקון
#
# מדידה פעילה: כל 90 שניות נבדק בוט אחד — נמשכים ממנו 2MB מהר ככל האפשר,
# בדיוק כמו /speedtest/bots. זו קיבולת אמיתית, והיא זו שמחליטה על ספסל
# ועל בחירת בוט. המדד הפסיבי נשאר לתצוגה בלבד ולא מעניש אף אחד.
#
# בוט אחד בכל מחזור ולא כולם: בדיקה בו-זמנית של 30 בוטים היא בדיוק העומס
# שאנחנו מנסים למנוע.
#
#   sudo bash deploy_bot_capacity.sh
#   sudo bash deploy_bot_capacity.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

SVC=zovex-bot
DIR=/opt/zovex-bot
LIVE="$DIR/main.py"
PY="$DIR/venv/bin/python"
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/patch_bot_capacity.py"
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
curl -fsSL "$RAW" -o /tmp/patch_bot_capacity.py || die "הורדת הטלאי נכשלה"

if [ "${1:-}" = "--rollback" ]; then
  "$PY" /tmp/patch_bot_capacity.py "$LIVE" --revert || die "השחזור נכשל"
  systemctl restart "$SVC" || die "restart נכשל"
  wait_up && echo "✅ שוחזר" || echo "⚠️  שוחזר, אבל /ping לא ענה"
  exit 0
fi

echo "① מסיר גרסה קודמת אם קיימת"
"$PY" /tmp/patch_bot_capacity.py "$LIVE" --revert >/dev/null 2>&1 \
  && echo "   הוסרה" || echo "   אין קודמת — ממשיך"

echo "② מחיל"
"$PY" /tmp/patch_bot_capacity.py "$LIVE" || die "לא הוחל"

echo "③ מפעיל מחדש (הבוטים עולים בהדרגה — דקות)"
systemctl restart "$SVC" || die "restart נכשל"
wait_up || die "/ping לא ענה.  לשחזור: sudo bash $0 --rollback"

echo
echo "④ מאמת"
curl -fsS -m 15 "$API/debug/caches" | "$PY" -c 'import json,sys
d = json.load(sys.stdin)
if "bot_caps" not in d:
    sys.exit("   ❌ bot_caps לא מופיע — קוד ישן עדיין רץ")
print("   bot_caps קיים, " + str(len(d["bot_caps"])) + " בוטים במעקב")
print("   (כולם None כרגע — הבדיקה הראשונה מתחילה דקה אחרי העלייה)")' \
  || die "האימות נכשל.  לשחזור: sudo bash $0 --rollback"

cat <<EOF

────────────────────────────────────────────────────────────
✅ נפרס.

הבדיקה הפעילה מתחילה דקה אחרי העלייה, ואז בוט אחד כל 90 שניות.
עם 30 בוטים — סבב מלא בערך כל 45 דקות.

אחרי שעה, הקיבולת האמיתית של כל בוט:

  curl -s $API/debug/caches | $PY -m json.tool | grep -A35 bot_caps

  · מעל 0.6   → בריא
  · מתחת      → יישלח לספסל וייבדק שוב מאוחר יותר
  · null      → עדיין לא נבדק

המספרים בפאנל ("0.06 MB/s") הם עדיין המדד הפסיבי — קצב הצריכה
של הנגן. הם לתצוגה בלבד ולא מענישים יותר אף אחד.

לשחזור:  sudo bash /tmp/deploy_bot_capacity.sh --rollback
EOF
