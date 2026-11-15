#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · בדיקת מהירות אמיתית לכל בוט. מוסיף endpoint (localhost בלבד) ומריץ.
#   sudo bash deploy_bots_bench.sh          sudo bash deploy_bots_bench.sh --rollback
# אחרי ההתקנה, להרצה חוזרת בלי restart:   python3 /tmp/bots_bench.py
# ─────────────────────────────────────────────────────────────────────────────
set -u
DIR=/opt/zovex-bot
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${REF}/vps-bot"
die(){ echo "❌ $*" >&2; exit 1; }
for f in fix_bots_bench.py bots_bench.py; do
  curl -fsSL -H 'Cache-Control: no-cache' "$RAW/$f?t=$(date +%s)" -o "/tmp/$f" || die "הורדה נכשלה: $f"
done
if [ "${1:-}" = "--rollback" ]; then
  MAIN_PY="$DIR/main.py" python3 /tmp/fix_bots_bench.py --revert || die "שחזור נכשל"
  python3 -m py_compile "$DIR/main.py" && systemctl restart zovex-bot; echo "✅ שוחזר"; exit 0
fi
if ! grep -q "fix_bots_bench" "$DIR/main.py"; then
  MAIN_PY="$DIR/main.py" python3 /tmp/fix_bots_bench.py || die "הטלאי נכשל — לא נגעתי"
  python3 -m py_compile "$DIR/main.py" || { MAIN_PY="$DIR/main.py" python3 /tmp/fix_bots_bench.py --revert; die "לא מתקמפל — שוחזר"; }
  echo "הפעלה מחדש…"; systemctl restart zovex-bot; sleep 8
  systemctl is-active --quiet zovex-bot || { MAIN_PY="$DIR/main.py" python3 /tmp/fix_bots_bench.py --revert; systemctl restart zovex-bot; die "השרת לא עלה — שוחזר"; }
  echo "ממתין 60ש שהבוטים יעלו…"; sleep 60
fi
python3 /tmp/bots_bench.py "$@"
