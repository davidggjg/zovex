#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · גידור בלוקים בהזרמה (Hedged Requests): בלוק שמתעכב >2.5ש נשלח גם
# לבוט אחר, והראשון מנצח. אחרי ההתקנה מריץ את bench_stream ומציג מונים.
#   sudo bash deploy_pinned_hedge.sh            sudo bash deploy_pinned_hedge.sh --rollback
# כיבוי בלי להסיר:  STREAM_PIN_HEDGE_DELAY=0 בקובץ zz-pinned.conf
# ─────────────────────────────────────────────────────────────────────────────
set -u
DIR=/opt/zovex-bot
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${REF}/vps-bot"
die(){ echo "❌ $*" >&2; exit 1; }
for f in fix_pinned_hedge.py bench_stream.py; do
  curl -fsSL -H 'Cache-Control: no-cache' "$RAW/$f?t=$(date +%s)" -o "/tmp/$f" || die "הורדה נכשלה: $f"
done
if [ "${1:-}" = "--rollback" ]; then
  MAIN_PY="$DIR/main.py" python3 /tmp/fix_pinned_hedge.py --revert || die "שחזור נכשל"
  python3 -m py_compile "$DIR/main.py" || die "לא מתקמפל"
  systemctl restart zovex-bot; echo "✅ שוחזר"; exit 0
fi
echo "① מחיל את הגידור"
MAIN_PY="$DIR/main.py" python3 /tmp/fix_pinned_hedge.py || die "הטלאי נכשל — לא נגעתי"
python3 -m py_compile "$DIR/main.py" || { MAIN_PY="$DIR/main.py" python3 /tmp/fix_pinned_hedge.py --revert; die "לא מתקמפל — שוחזר"; }
echo "② הפעלה מחדש"
systemctl restart zovex-bot; sleep 8
systemctl is-active --quiet zovex-bot || { journalctl -u zovex-bot -n 25 --no-pager; MAIN_PY="$DIR/main.py" python3 /tmp/fix_pinned_hedge.py --revert; systemctl restart zovex-bot; die "השרת לא עלה — שוחזר"; }
echo "③ חימום (90ש) ומדידה"; sleep 90
python3 /tmp/bench_stream.py
echo; echo "== מונה הגידור =="; curl -s -m 5 http://127.0.0.1:8000/stream/hedge-stats; echo
echo; echo "✅ מותקן.  לחזרה: sudo bash $0 --rollback"
