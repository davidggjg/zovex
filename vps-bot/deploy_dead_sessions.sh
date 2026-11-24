#!/bin/bash
# ZOVEX · דילוג על חיבורי media מתים (מוריד את קפיצות ה-5.7 שניות).
#   sudo bash deploy_dead_sessions.sh   ·   --rollback להסרה   ·   STREAM_SKIP_DEAD=0 לכיבוי בלי הסרה
set -u
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
DIR=/opt/zovex-bot; PY="$DIR/venv/bin/python"; [ -x "$PY" ] || PY=python3
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
die(){ echo "❌ $*"; exit 1; }
curl -fsSL "https://raw.githubusercontent.com/davidggjg/zovex/$REF/vps-bot/fix_dead_sessions.py" -o $T/f.py || die "הורדה נכשלה"
if [ "${1:-}" = "--rollback" ]; then MAIN_PY=$DIR/main.py python3 $T/f.py --revert; systemctl restart zovex-bot; exit 0; fi
cp $DIR/main.py $T/main.before
MAIN_PY=$DIR/main.py python3 $T/f.py || die "לא הוחל (לא שונה כלום)"
"$PY" -m py_compile $DIR/main.py || { cp $T/main.before $DIR/main.py; die "שגיאת תחביר — שוחזר"; }
systemctl restart zovex-bot
ok=0; for i in $(seq 1 30); do sleep 2; curl -fsS -m 5 -o /dev/null http://127.0.0.1:8000/app/version && { ok=1; break; }; done
[ $ok = 1 ] || { cp $T/main.before $DIR/main.py; systemctl restart zovex-bot; die "השרת לא עלה — שוחזר"; }
echo "✅ פעיל. מחמם 20 שניות ובודק…"; sleep 20
O=$(curl -s -m 60 http://127.0.0.1:8000/content/lite | python3 -c "import json,sys,random;d=[m for m in json.load(sys.stdin) if '/stream/' in (m.get('video_url') or '')];print(random.choice(d)['video_url'].replace('https://zovex.duckdns.org','http://127.0.0.1:8000'))")
S=$(curl -s -m 30 -r 0-0 -D - -o /dev/null "$O" | grep -i "^content-range:" | sed "s#.*/##" | tr -d "\r ")
[ -n "$S" ] || { echo "לא הצלחתי למדוד — האתר עובד, תבדוק ידנית"; exit 0; }
for r in 1 2 3; do for p in 10 30 50 70 90; do off=$(( S*p/100 )); curl -s -m 60 -o /dev/null -r $off-$((off+4194303)) -w "  $p%%  4MB=%{time_total}s\n" "$O"; done; done
