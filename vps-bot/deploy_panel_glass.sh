#!/usr/bin/env bash
# ZOVEX · עיצוב "Luxe Glass" לפאנל הניהול. CSS בלבד, admin.html בלבד, אין restart.
#   sudo bash deploy_panel_glass.sh          sudo bash deploy_panel_glass.sh --rollback
set -u
DIR=/opt/zovex-bot
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${REF}/vps-bot"
die(){ echo "❌ $*" >&2; exit 1; }
mkdir -p /tmp/zvglass
for f in patch_panel_glass.py panel_glass.css; do
  curl -fsSL -H 'Cache-Control: no-cache' "$RAW/$f?t=$(date +%s)" -o "/tmp/zvglass/$f" || die "הורדה נכשלה: $f"
done
if [ "${1:-}" = "--rollback" ]; then
  PANEL="$DIR/admin.html" python3 /tmp/zvglass/patch_panel_glass.py --revert; echo "✅ העיצוב הוסר (רענן /admin)"; exit 0
fi
PANEL="$DIR/admin.html" CSS=/tmp/zvglass/panel_glass.css python3 /tmp/zvglass/patch_panel_glass.py || die "נכשל — לא נגעתי"
echo "✅ מותקן. פתח /admin ורענן (Ctrl+Shift+R).   לחזרה: sudo bash $0 --rollback"
