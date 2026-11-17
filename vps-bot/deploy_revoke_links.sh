#!/usr/bin/env bash
# ZOVEX · קישור של פריט שנמחק/הוחלף מפסיק לעבוד מיד + הודעת "כבר הועלה" מדויקת בבוט.
#   sudo bash deploy_revoke_links.sh          sudo bash deploy_revoke_links.sh --rollback
# כיבוי בלי להסיר: STREAM_REVOKE=0 בקובץ zz-pinned.conf
set -u
DIR=/opt/zovex-bot
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${REF}/vps-bot"
die(){ echo "❌ $*" >&2; exit 1; }
for f in fix_revoke_links.py bench_stream.py; do
  curl -fsSL -H 'Cache-Control: no-cache' "$RAW/$f?t=$(date +%s)" -o "/tmp/$f" || die "הורדה נכשלה: $f"
done
if [ "${1:-}" = "--rollback" ]; then
  MAIN_PY="$DIR/main.py" python3 /tmp/fix_revoke_links.py --revert || die "שחזור נכשל"
  python3 -m py_compile "$DIR/main.py" && systemctl restart zovex-bot; echo "✅ שוחזר"; exit 0
fi
MAIN_PY="$DIR/main.py" python3 /tmp/fix_revoke_links.py || die "הטלאי נכשל — לא נגעתי"
python3 -m py_compile "$DIR/main.py" || { MAIN_PY="$DIR/main.py" python3 /tmp/fix_revoke_links.py --revert; die "לא מתקמפל — שוחזר"; }
systemctl restart zovex-bot; sleep 8
systemctl is-active --quiet zovex-bot || { journalctl -u zovex-bot -n 25 --no-pager; MAIN_PY="$DIR/main.py" python3 /tmp/fix_revoke_links.py --revert; systemctl restart zovex-bot; die "השרת לא עלה — שוחזר"; }
echo "ממתין 60ש ובודק שסרטים שבאתר ממשיכים להתנגן…"; sleep 60
python3 /tmp/bench_stream.py --n 3
echo; echo "✅ מותקן.  לחזרה: sudo bash $0 --rollback"
