#!/bin/bash
# ZOVEX · מכשיר הקלטה לתקיעות (לא משנה התנהגות). --rollback להסרה.
set -u
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
DIR=/opt/zovex-bot; PY="$DIR/venv/bin/python"; [ -x "$PY" ] || PY=python3
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
die(){ echo "❌ $*"; exit 1; }
curl -fsSL "https://raw.githubusercontent.com/davidggjg/zovex/$REF/vps-bot/fix_stall_trace.py" -o $T/f.py || die "הורדה נכשלה"
if [ "${1:-}" = "--rollback" ]; then MAIN_PY=$DIR/main.py python3 $T/f.py --revert; systemctl restart zovex-bot; exit 0; fi
cp $DIR/main.py $T/main.before
MAIN_PY=$DIR/main.py python3 $T/f.py || die "לא הוחל (לא שונה כלום)"
"$PY" -m py_compile $DIR/main.py || { cp $T/main.before $DIR/main.py; die "שגיאת תחביר — שוחזר"; }
systemctl restart zovex-bot
ok=0; for i in $(seq 1 30); do sleep 2; curl -fsS -m 5 -o /dev/null http://127.0.0.1:8000/debug/stalls && { ok=1; break; }; done
[ $ok = 1 ] || { cp $T/main.before $DIR/main.py; systemctl restart zovex-bot; die "השרת לא עלה — שוחזר"; }
cat > /usr/local/bin/zv-stalls <<'R'
#!/bin/bash
curl -s -m 10 "http://127.0.0.1:8000/debug/stalls?last=${1:-40}" | python3 -c '
import json,sys,time; d=json.load(sys.stdin); c=d["counters"]
print("הגדרות:", d["env"])
print("ניסיונות: %d | ok %d | timeout %d | שגיאת חיבור %d | flood %d" % (c["attempts"],c["ok"],c["timeout"],c["conn"],c["flood"]))
print("ניסיון חוזר על אותו חיבור: %d | המתנה בשער קצב >1ש: %d | הצלחה איטית >1ש: %d" % (c["retry_same_session"],c["gate_wait_over_1s"],c["slow_ok"]))
print("זמני קריאה לטלגרם:", c["lat"])
print("לפי DC:", d["by_dc"])
print("בוטים בעייתיים:"); [print("  ",b,v) for b,v in d["worst_bots"][:8]]
print("אירועים אחרונים:")
for e in d["recent"]: print("  %s %-10s dc%s sess%-6s try%d gate=%.1f call=%.1f %-7s alive=%s %s" % (time.strftime("%H:%M:%S",time.localtime(e["t"])),e["bot"],e["dc"],e["sess"],e["try"],e["gate"],e["call"],e["res"],e["alive"],e["err"]))'
R
chmod +x /usr/local/bin/zv-stalls
echo "✅ ההקלטה פעילה. צפה 15-20 דקות (עם קפיצות), ואז הרץ:  zv-stalls"
