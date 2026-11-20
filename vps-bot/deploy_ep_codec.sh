#!/usr/bin/env bash
# ZOVEX · בוט ההעלאה: תגיות איכות/קודק (x264, DD5.1, 1080p...) לא נקראות יותר כמספר פרק.
#   sudo bash deploy_ep_codec.sh          sudo bash deploy_ep_codec.sh --rollback
set -u
DIR=/opt/zovex-bot
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${REF}/vps-bot"
die(){ echo "❌ $*" >&2; exit 1; }
curl -fsSL -H 'Cache-Control: no-cache' "$RAW/fix_ep_codec.py?t=$(date +%s)" -o /tmp/fix_ep_codec.py || die "הורדה נכשלה"
if [ "${1:-}" = "--rollback" ]; then
  MAIN_PY="$DIR/main.py" python3 /tmp/fix_ep_codec.py --revert || die "שחזור נכשל"
  python3 -m py_compile "$DIR/main.py" && systemctl restart zovex-bot; echo "✅ שוחזר"; exit 0
fi
MAIN_PY="$DIR/main.py" python3 /tmp/fix_ep_codec.py || die "הטלאי נכשל — לא נגעתי"
python3 -m py_compile "$DIR/main.py" || { MAIN_PY="$DIR/main.py" python3 /tmp/fix_ep_codec.py --revert; die "לא מתקמפל — שוחזר"; }
systemctl restart zovex-bot; sleep 8
systemctl is-active --quiet zovex-bot || { journalctl -u zovex-bot -n 25 --no-pager; MAIN_PY="$DIR/main.py" python3 /tmp/fix_ep_codec.py --revert; systemctl restart zovex-bot; die "השרת לא עלה — שוחזר"; }
echo "✅ מותקן. שלח לבוט שוב את הקובץ של הסרט — הוא יזוהה כסרט."
echo "   לחזרה: sudo bash $0 --rollback"
