#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · שלושה כלי-סדרה לפאנל הניהול. admin.html בלבד — אין restart.
#
#   ① פוסטר/תקציר/שנה/קטגוריה/טריילר מופצים אוטומטית לכל פרקי הסדרה בשמירה.
#   ② כפתור "✏️ שם" — שינוי שם לכל הפרקים במכה אחת.
#   ③ כפתור "🔗 מזג" — מיזוג סדרה שהתפצלה לתוך סדרה אחרת.
#
#   sudo bash deploy_series_tools.sh
#   sudo bash deploy_series_tools.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u
DIR=/opt/zovex-bot
PANEL="$DIR/admin.html"
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${REF}/vps-bot/patch_series_tools.py"
die(){ echo "❌ $*" >&2; exit 1; }
[ -f "$PANEL" ] || die "$PANEL לא קיים"

curl -fsSL -H 'Cache-Control: no-cache' "$RAW?t=$(date +%s)" -o /tmp/patch_series_tools.py || die "הורדה נכשלה"

if [ "${1:-}" = "--rollback" ]; then
  PANEL="$PANEL" python3 /tmp/patch_series_tools.py --revert || die "שחזור נכשל"
  echo "✅ שוחזר (רענן את /admin)"; exit 0
fi

PANEL="$PANEL" python3 /tmp/patch_series_tools.py || die "הטלאי נכשל"
echo "✅ הותקן. רענן את דף /admin (Ctrl+Shift+R) כדי לראות את הכפתורים."
echo "   לחזרה:  sudo bash $0 --rollback"
