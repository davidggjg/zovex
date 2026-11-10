#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · יישור הצ'קבוקס בבחירת הממתינים (תיקון ל-patch_upload_select). admin.html בלבד.
#
#   sudo bash deploy_upload_select_fix.sh
#   sudo bash deploy_upload_select_fix.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u
DIR=/opt/zovex-bot
PANEL="$DIR/admin.html"
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${REF}/vps-bot/patch_upload_select_fix.py"
die(){ echo "❌ $*" >&2; exit 1; }
[ -f "$PANEL" ] || die "$PANEL לא קיים"

curl -fsSL -H 'Cache-Control: no-cache' "$RAW?t=$(date +%s)" -o /tmp/patch_upload_select_fix.py || die "הורדה נכשלה"

if [ "${1:-}" = "--rollback" ]; then
  PANEL="$PANEL" python3 /tmp/patch_upload_select_fix.py --revert || die "שחזור נכשל"
  echo "✅ שוחזר (רענן את /admin)"; exit 0
fi

PANEL="$PANEL" python3 /tmp/patch_upload_select_fix.py || die "הטלאי נכשל"
echo "✅ הצ'קבוקס מיושר. רענן את /admin (Ctrl+Shift+R)."
echo "   לחזרה:  sudo bash $0 --rollback"
