#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · פורס את תיקון התקיעות בערוצים חיים.
#
# התסמין: ערוץ מנגן, נתקע לכחצי דקה, ממשיך, נתקע שוב — ורק בערוצים
# שעוברים המרה אצלנו. אצל הספק אותו קישור רץ חלק.
#
# הסיבה והתיקון מתועדים במלואם ב-patch_live_window.py. בקצרה: חלון
# המקטעים היה 24 שניות עם מחיקה אוטומטית, והנגן יושב 3 מקטעים אחורה —
# כלומר 12 שניות מרווח בלבד.
#
# נמדד לפני הפריסה: load average 0.10 על 10 ליבות, אפס תהליכי ffmpeg.
# כלומר המעבד אינו צוואר הבקבוק, והחלון הוא הסיבה הדומיננטית. (המדידה
# נעשתה בשעה ריקה ואינה שוללת עומס בשעת שיא — אם התקיעות יחזרו דווקא
# בשעות צפייה, נחזור לכאן ונבדוק את עלות הקידוד.)
#
# אינו נוגע ב-nginx ואינו מחליף את main.py: טלאי מדויק, או סירוב.
#
#   sudo bash deploy_live_window.sh
#   sudo bash deploy_live_window.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

SVC=zovex-bot
DIR=/opt/zovex-bot
LIVE="$DIR/main.py"
PY="$DIR/venv/bin/python"
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/patch_live_window.py"
PATCHER=/tmp/patch_live_window.py

die() { echo "❌ $*" >&2; exit 1; }

wait_up() {
  for _ in $(seq 1 80); do
    curl -fsS -m 3 http://127.0.0.1:8000/ping >/dev/null 2>&1 && return 0
    sleep 3
  done
  return 1
}

[ -f "$LIVE" ] || die "$LIVE לא קיים"
[ -x "$PY" ]   || PY=python3

if [ "${1:-}" = "--rollback" ]; then
  curl -fsSL "$RAW" -o "$PATCHER" || die "הורדת הטלאי נכשלה"
  "$PY" "$PATCHER" "$LIVE" --revert || die "השחזור נכשל"
  systemctl restart "$SVC" || die "restart נכשל"
  wait_up && echo "✅ שוחזר" || echo "⚠️  שוחזר, אבל /ping לא ענה"
  exit 0
fi

echo "① מוריד את הטלאי"
curl -fsSL "$RAW" -o "$PATCHER" || die "ההורדה נכשלה"

echo "② מחיל (התאמה מדויקת, או סירוב בלי לגעת)"
"$PY" "$PATCHER" "$LIVE" || die "הטלאי לא הוחל — הקובץ לא שונה."

echo "③ מפעיל מחדש (הבוטים עולים בהדרגה — דקות)"
systemctl restart "$SVC" || die "restart נכשל"
wait_up || die "/ping לא ענה תוך 4 דקות.  journalctl -u $SVC -n 80 --no-pager
   לשחזור:  sudo bash $0 --rollback"

echo "④ מאמת שהערך החדש בתוקף"
# ffmpeg מופעל רק כשצופה נכנס לערוץ, ולכן אי אפשר לבדוק תהליך רץ עכשיו.
# מה שכן אפשר לאמת הוא שהקוד שנטען מכיל את ההגדרה — זה מה שקובע.
grep -q "HLS_FIX_LIST_SIZE" "$LIVE" && echo "   ✓ HLS_FIX_LIST_SIZE בקוד" \
  || die "ההגדרה לא בקובץ — משהו השתבש"

cat <<'EOF'

────────────────────────────────────────────────────────────
✅ נפרס.

  חלון המקטעים:  6 → 12  (24 → 48 שניות)
  מרווח לנגן:   12 → 36 שניות
  נקודות מפתח:  מיושרות ל-4 שניות גם בפרופיל הראשי

עכשיו תפתח ערוץ שנתקע לך קודם — דווקא אחד שעובר המרה — ותן לו
לרוץ כמה דקות.

אם עדיין נתקע, להרחיב עוד בלי לפרוס שוב:
  systemctl set-environment HLS_FIX_LIST_SIZE=20   # לא שורד אתחול
  או drop-in קבוע, ואז: systemctl restart zovex-bot

לשחזור:  sudo bash /tmp/deploy_live_window.sh --rollback
EOF
