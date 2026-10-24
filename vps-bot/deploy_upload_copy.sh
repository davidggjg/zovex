#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · מתקן את "ההעלאה לערוץ נכשלה: 'NoneType' object has no attribute 'id'"
#
# הרקע ב-patch_upload_copy.py. בקצרה: copy_message של Pyrogram מחזיר None
# על סוגי הודעות שהוא אינו יודע להעתיק, במקום לזרוק שגיאה — והשורה הבאה
# ניגשת ל-.id ונופלת. ה-except הכללי הדפיס "ודא שהבוט אדמין בערוץ", הודעה
# שאין לה קשר, ולכן זה נראה אקראי: קובץ אחד נכשל והבא עובר.
#
#   sudo bash deploy_upload_copy.sh
#   sudo bash deploy_upload_copy.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

SVC=zovex-bot
DIR=/opt/zovex-bot
LIVE="$DIR/main.py"
PY="$DIR/venv/bin/python"
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/patch_upload_copy.py"
PATCHER=/tmp/patch_upload_copy.py

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
curl -fsSL "$RAW" -o "$PATCHER" || die "הורדת הטלאי נכשלה"

if [ "${1:-}" = "--rollback" ]; then
  "$PY" "$PATCHER" "$LIVE" --revert || die "השחזור נכשל"
  systemctl restart "$SVC" || die "restart נכשל"
  wait_up && echo "✅ שוחזר" || echo "⚠️  שוחזר, אבל /ping לא ענה"
  exit 0
fi

echo "① מחיל (התאמה מדויקת, או סירוב בלי לגעת)"
"$PY" "$PATCHER" "$LIVE" || die "לא הוחל — הקובץ לא שונה."

echo "② מפעיל מחדש (הבוטים עולים בהדרגה — דקות)"
systemctl restart "$SVC" || die "restart נכשל"
wait_up || die "/ping לא ענה.  לשחזור: sudo bash $0 --rollback"

cat <<'EOF'

────────────────────────────────────────────────────────────
✅ נפרס.

עכשיו שלח לבוט את אותו פרק שנכשל קודם.

  · אם הוא עולה — התיקון עבד.
  · אם הוא עדיין נכשל, ההודעה תהיה מדויקת הפעם ולא תאשים
    הרשאות. שלח לי את מה שהיא אומרת.

לראות מה קרה מאחורי הקלעים:
  journalctl -u zovex-bot --since "5 minutes ago" --no-pager \
    | grep -i "upload_bot"

לשחזור:  sudo bash /tmp/deploy_upload_copy.sh --rollback
EOF
