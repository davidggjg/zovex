#!/bin/bash
# ZOVEX · תיקון בוט ההעלאה תחת kurigram (quote= ב-reply_text). --rollback להסרה.
set -u
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
DIR=/opt/zovex-bot; PY="$DIR/venv_k/bin/python"; [ -x "$PY" ] || PY="$DIR/venv/bin/python"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
die(){ echo "❌ $*"; exit 1; }
curl -fsSL "https://raw.githubusercontent.com/davidggjg/zovex/$REF/vps-bot/fix_kurigram_compat2.py" -o $T/f.py || die "הורדה נכשלה"
if [ "${1:-}" = "--rollback" ]; then MAIN_PY=$DIR/main.py python3 $T/f.py --revert; systemctl restart zovex-bot; exit 0; fi
cp $DIR/main.py $T/main.before
MAIN_PY=$DIR/main.py python3 $T/f.py || die "לא הוחל (לא שונה כלום)"
"$PY" -m py_compile $DIR/main.py || { cp $T/main.before $DIR/main.py; die "שגיאת תחביר — שוחזר"; }
systemctl restart zovex-bot
ok=0; for i in $(seq 1 45); do sleep 2; curl -fsS -m 5 -o /dev/null http://127.0.0.1:8000/app/version && { ok=1; break; }; done
[ $ok = 1 ] || { cp $T/main.before $DIR/main.py; systemctl restart zovex-bot; die "השרת לא עלה — שוחזר"; }
sleep 15
journalctl -u zovex-bot --since "-2min" --no-pager | grep -E "בוט העלאה" | tail -2
echo "✅ הוחל. שלח לבוט ההעלאה קובץ ובדוק שהוא עונה ⏳ מעלה לערוץ..."
