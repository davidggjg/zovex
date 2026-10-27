#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · "לא ניתן לנגן מיקום זה" — Range: bytes=-N הוחזר הפוך.
#
# הרקע המלא ב-patch_suffix_range.py. בקצרה: ‎bytes=-65536‎ פירושו לפי
# RFC 7233 "65536 הבייטים האחרונים", והקוד החזיר את ה**ראשונים**.
#
# נמדד על קובץ חי (הודעה 20213): המבנה הוא ftyp → free → mdat, בלי moov
# בהתחלה — כלומר טבלת האינדקס בסוף הקובץ. הנגן ביקש את הזנב כדי לקרוא
# אותה, קיבל את ההתחלה, ולכן הכריז שהקובץ אינו נגיש.
#
# זה פגע בכל נגן חיצוני: VLC, כרום, ספארי, ExoPlayer, והסורק של גוגל.
# קבצים שבהם moov בהתחלה עבדו — ולכן זה נראה אקראי.
#
#   sudo bash deploy_suffix_range.sh
#   sudo bash deploy_suffix_range.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

SVC=zovex-bot
DIR=/opt/zovex-bot
LIVE="$DIR/main.py"
PY="$DIR/venv/bin/python"
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/patch_suffix_range.py"
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
curl -fsSL "$RAW" -o /tmp/patch_suffix_range.py || die "הורדת הטלאי נכשלה"

if [ "${1:-}" = "--rollback" ]; then
  "$PY" /tmp/patch_suffix_range.py "$LIVE" --revert || die "השחזור נכשל"
  systemctl restart "$SVC" || die "restart נכשל"
  wait_up && echo "✅ שוחזר" || echo "⚠️  שוחזר, אבל /ping לא ענה"
  exit 0
fi

# פריט אמיתי מהקטלוג, לאימות מקצה לקצה אחרי הפריסה
read -r CHAT MSG <<<"$(curl -fsS -m 60 "$API/content/lite" | "$PY" -c 'import json,sys,re
for e in json.load(sys.stdin):
    m = re.search(r"/stream/(-?\d+)/(\d+)", str(e.get("video_url") or ""))
    if m:
        print(m.group(1), m.group(2)); break')"
[ -n "${MSG:-}" ] || die "לא נמצא פריט בקטלוג לאימות"

echo "① מחיל (התאמה מדויקת, או סירוב בלי לגעת)"
"$PY" /tmp/patch_suffix_range.py "$LIVE" || die "לא הוחל"

echo "② מפעיל מחדש (הבוטים עולים בהדרגה — דקות)"
systemctl restart "$SVC" || die "restart נכשל"
wait_up || die "/ping לא ענה.  לשחזור: sudo bash $0 --rollback"

echo
echo "③ האימות: מבקש את הזנב ובודק שחוזר ממנו moov"
URL=$(curl -fsS -m 30 "$API/content/lite" | "$PY" -c 'import json,sys,re
want = sys.argv[1]
for e in json.load(sys.stdin):
    u = str(e.get("video_url") or "")
    if "/" + want in u:
        print(u); break' "$MSG")
[ -n "$URL" ] || die "לא הופק קישור חתום"

curl -fsS -m 60 -r -262144 "$URL" -o /tmp/tail.bin 2>/dev/null \
  || die "בקשת הזנב נכשלה"
SZ=$(stat -c %s /tmp/tail.bin 2>/dev/null || echo 0)
echo "   התקבלו $SZ בייטים מהזנב"

if head -c 64 /tmp/tail.bin | grep -q "ftyp"; then
  rm -f /tmp/tail.bin
  die "עדיין חוזרת תחילת הקובץ (ftyp) — התיקון לא נכנס לתוקף.
       לשחזור: sudo bash $0 --rollback"
fi
if strings /tmp/tail.bin 2>/dev/null | grep -qE '^moov$|moov'; then
  echo "   ✅ נמצא moov בזנב — נגנים חיצוניים יוכלו לנגן"
else
  echo "   ⚠️  לא נמצא moov בזנב של הפריט הזה."
  echo "       ייתכן שדווקא בקובץ הזה moov בהתחלה (faststart), וזה תקין."
  echo "       העיקר: לא חזרה תחילת הקובץ, כלומר הטווח כובד."
fi
rm -f /tmp/tail.bin

cat <<EOF

────────────────────────────────────────────────────────────
✅ נפרס.

עכשיו תנסה שוב את אותו קישור ב-VLC ובדפדפן. אמור לעבוד.

מה זה תיקן מעבר ל-VLC:
  · כרום, ספארי, ExoPlayer — כולם מבקשים את הזנב
  · הסורק של גוגל, שמושך וידאו באותה דרך
  · כל קובץ שבו moov בסוף (נמדד: כ-28% מהקטלוג)

לשחזור:  sudo bash /tmp/deploy_suffix_range.sh --rollback
EOF
