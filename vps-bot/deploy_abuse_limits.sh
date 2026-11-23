#!/bin/bash
# התקנת fix_abuse_limits עם בדיקה ושחזור אוטומטי. --rollback להסרה.
set -e
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
DIR=/opt/zovex-bot; T=$(mktemp -d)
curl -fsSL "https://raw.githubusercontent.com/davidggjg/zovex/$REF/vps-bot/fix_abuse_limits.py" -o $T/f.py
if [ "$1" = "--rollback" ]; then MAIN_PY=$DIR/main.py python3 $T/f.py --revert; systemctl restart zovex-bot; echo "✓ הוסר"; exit 0; fi
cp $DIR/main.py $T/main.py.before
MAIN_PY=$DIR/main.py python3 $T/f.py
python3 -m py_compile $DIR/main.py || { cp $T/main.py.before $DIR/main.py; echo "✗ שגיאה — שוחזר"; exit 1; }
systemctl restart zovex-bot; sleep 6
if curl -fsS -m 10 -o /dev/null http://127.0.0.1:8000/content/lite 2>/dev/null || systemctl is-active -q zovex-bot; then
  echo "✓ הוגנות מספאם פעילות"
else
  cp $T/main.py.before $DIR/main.py; systemctl restart zovex-bot; echo "✗ השרת לא עלה — שוחזר"; exit 1
fi
