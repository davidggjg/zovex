#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · בחירת פרקים ידנית באזור הממתינים + "אחד את הנבחרים". admin.html בלבד.
#
#   כששתי סדרות מתפצלות יחד: סמן ✓ את הפרקים של סדרה אחת, הקלד שם, אחד.
#   אח"כ סמן את השאר לסדרה הבאה. מספור-מחדש אוטומטי ע1פ1..ע1פN.
#
#   sudo bash deploy_upload_select.sh
#   sudo bash deploy_upload_select.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u
DIR=/opt/zovex-bot
PANEL="$DIR/admin.html"
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${REF}/vps-bot/patch_upload_select.py"
die(){ echo "❌ $*" >&2; exit 1; }
[ -f "$PANEL" ] || die "$PANEL לא קיים"

curl -fsSL -H 'Cache-Control: no-cache' "$RAW?t=$(date +%s)" -o /tmp/patch_upload_select.py || die "הורדה נכשלה"

if [ "${1:-}" = "--rollback" ]; then
  PANEL="$PANEL" python3 /tmp/patch_upload_select.py --revert || die "שחזור נכשל"
  echo "✅ שוחזר (רענן את /admin)"; exit 0
fi

PANEL="$PANEL" python3 /tmp/patch_upload_select.py || die "הטלאי נכשל"
echo "✅ הותקן. רענן את /admin (Ctrl+Shift+R) → לשונית 'העלאות מהבוט' → צ'קבוקסים."
echo "   לחזרה:  sudo bash $0 --rollback"
