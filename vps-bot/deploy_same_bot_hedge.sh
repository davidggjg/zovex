#!/bin/bash
# ZOVEX · גידור בלוקים בתוך אותו בוט. --rollback להסרה · STREAM_SAME_HEDGE_DELAY=0 לכיבוי.
set -u
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
DIR=/opt/zovex-bot; PY="$DIR/venv/bin/python"; [ -x "$PY" ] || PY=python3
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
die(){ echo "❌ $*"; exit 1; }
curl -fsSL "https://raw.githubusercontent.com/davidggjg/zovex/$REF/vps-bot/fix_same_bot_hedge.py" -o $T/f.py || die "הורדה נכשלה"
if [ "${1:-}" = "--rollback" ]; then MAIN_PY=$DIR/main.py python3 $T/f.py --revert; systemctl restart zovex-bot; exit 0; fi
cp $DIR/main.py $T/main.before
MAIN_PY=$DIR/main.py python3 $T/f.py || die "לא הוחל (לא שונה כלום)"
"$PY" -m py_compile $DIR/main.py || { cp $T/main.before $DIR/main.py; die "שגיאת תחביר — שוחזר"; }
systemctl restart zovex-bot
ok=0; for i in $(seq 1 30); do sleep 2; curl -fsS -m 5 -o /dev/null http://127.0.0.1:8000/app/version && { ok=1; break; }; done
[ $ok = 1 ] || { cp $T/main.before $DIR/main.py; systemctl restart zovex-bot; die "השרת לא עלה — שוחזר"; }
if [ -f /usr/local/bin/zv-stalls ] && ! grep -q hedge_ /usr/local/bin/zv-stalls; then
  sed -i 's|print("זמני קריאה לטלגרם:", c\["lat"\])|print("זמני קריאה לטלגרם:", c["lat"]); print("גידור: הופעל %d · ניצח %d · הראשי ניצח %d · אין חלופי %d · מעבר לתקציב %d" % (c.get("hedge_launched",0),c.get("hedge_won",0),c.get("hedge_lost",0),c.get("hedge_no_alt",0),c.get("hedge_over_budget",0)))|' /usr/local/bin/zv-stalls
fi
echo "✅ הגידור פעיל. תן 10 דק׳ להתייצב + 20 דק׳ צפייה, ואז: zv-stalls"
