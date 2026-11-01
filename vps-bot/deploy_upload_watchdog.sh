#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · בוט ההעלאה מת בשקט — ואין מי שיחייה אותו.
#
# נמדד: journalctl -f פתוח, נשלחו קבצים לבוט, אפס שורות. הוא עלה בהצלחה
# ב-00:17 ומאז לא קיבל מטלגרם שום עדכון.
#
# start_upload_bot() מרים אותו פעם אחת בעליית השירות. ה-watchdog הקיים
# שומר על הלקוח הראשי ועל בריכת הסטרימינג — בוט ההעלאה אינו בשום מנגנון
# החייאה, וכשה-session שלו נופל איש אינו מבחין.
#
# זה מסביר את "פתאום עובד פתאום לא": כל קריסה של השירות תיקנה אותו
# לכמה שעות. אתמול היו תשע, והן כיסו על הבעיה; ברגע שהקריסות נעצרו הוא
# נשאר תקוע — ולכן זה החמיר דווקא כשהכול השתפר.
#
#   sudo bash deploy_upload_watchdog.sh
#   sudo bash deploy_upload_watchdog.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

SVC=zovex-bot
DIR=/opt/zovex-bot
LIVE="$DIR/main.py"
PY="$DIR/venv/bin/python"
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/patch_upload_watchdog.py"
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
curl -fsSL "$RAW" -o /tmp/patch_upload_watchdog.py || die "הורדת הטלאי נכשלה"

if [ "${1:-}" = "--rollback" ]; then
  "$PY" /tmp/patch_upload_watchdog.py "$LIVE" --revert || die "השחזור נכשל"
  systemctl restart "$SVC" || die "restart נכשל"
  wait_up && echo "✅ שוחזר" || echo "⚠️  שוחזר, אבל /ping לא ענה"
  exit 0
fi

echo "① מסיר גרסה קודמת אם קיימת"
"$PY" /tmp/patch_upload_watchdog.py "$LIVE" --revert >/dev/null 2>&1 \
  && echo "   הוסרה" || echo "   אין קודמת — ממשיך"

echo "② מחיל"
"$PY" /tmp/patch_upload_watchdog.py "$LIVE" || die "לא הוחל"

echo "③ מפעיל מחדש (הבוטים עולים בהדרגה — כ-2 דקות)"
systemctl restart "$SVC" || die "restart נכשל"
wait_up || die "/ping לא ענה.  לשחזור: sudo bash $0 --rollback"

echo
echo "④ ממתין לעליית בוט ההעלאה"
for i in $(seq 1 40); do
  sleep 5
  if journalctl -u "$SVC" --since "3 min ago" --no-pager 2>/dev/null \
     | grep -q "✅ בוט העלאה עלה"; then
    echo "   ✅ עלה"
    break
  fi
  [ "$i" = 40 ] && echo "   ⚠️  לא ראיתי אותו עולה — בדוק UPLOAD_BOT_TOKEN ב-.env"
done

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

לשחזור:  sudo bash /tmp/deploy_upload_watchdog.sh --rollback
EOF
