#!/usr/bin/env bash
# ZOVEX · פאנל v2: עיצוב Luxe Glass + העלאות חכמות מהבוט + תמיכה בסגנון וואטסאפ. admin.html בלבד, אין restart.
#   sudo bash deploy_panel_v2.sh          sudo bash deploy_panel_v2.sh --rollback
set -u
DIR=/opt/zovex-bot
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${REF}/vps-bot"
die(){ echo "❌ $*" >&2; exit 1; }
T=/tmp/zvpanel2; mkdir -p $T
for f in patch_panel_glass.py panel_glass.css patch_smart_uploads.py panel_smart_uploads.js patch_panel_support.py panel_support.js; do
  curl -fsSL -H 'Cache-Control: no-cache' "$RAW/$f?t=$(date +%s)" -o "$T/$f" || die "הורדה נכשלה: $f"
done
if [ "${1:-}" = "--rollback" ]; then
  PANEL="$DIR/admin.html" python3 $T/patch_panel_support.py --revert
  PANEL="$DIR/admin.html" python3 $T/patch_smart_uploads.py --revert
  PANEL="$DIR/admin.html" python3 $T/patch_panel_glass.py --revert
  echo "✅ הפאנל חזר למצב הקודם (רענן /admin)"; exit 0
fi
cp -a "$DIR/admin.html" "$DIR/admin.html.bak_v2_$(date +%s)"
PANEL="$DIR/admin.html" CSS=$T/panel_glass.css python3 $T/patch_panel_glass.py || die "העיצוב נכשל — לא נגעתי"
PANEL="$DIR/admin.html" JS=$T/panel_smart_uploads.js python3 $T/patch_smart_uploads.py || die "ההעלאות החכמות נכשלו (העיצוב כבר הוחל)"
PANEL="$DIR/admin.html" JS=$T/panel_support.js python3 $T/patch_panel_support.py || die "התמיכה נכשלה (השאר כבר הוחל)"
echo "✅ מותקן. פתח /admin ורענן (Ctrl+Shift+R).   לחזרה: sudo bash $0 --rollback"
