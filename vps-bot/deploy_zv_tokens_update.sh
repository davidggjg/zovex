#!/bin/bash
# ZOVEX · עדכון מודול האימות בלבד (zv_tokens.py): חלון שעון ±15 דקות + server_time בתשובות.
#   sudo bash deploy_zv_tokens_update.sh   ·   --rollback מחזיר את הגרסה הקודמת
set -u
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
DIR=/opt/zovex-bot; PY="$DIR/venv/bin/python"; [ -x "$PY" ] || PY=python3
die(){ echo "❌ $*"; exit 1; }
if [ "${1:-}" = "--rollback" ]; then
  [ -f $DIR/zv_tokens.py.prev ] || die "אין גרסה קודמת"
  cp $DIR/zv_tokens.py.prev $DIR/zv_tokens.py; systemctl restart zovex-bot; echo "✅ שוחזר"; exit 0; fi
[ -f $DIR/zv_tokens.py ] || die "zv_tokens.py לא מותקן — קודם deploy_security.sh"
T=$(mktemp); trap 'rm -f "$T"' EXIT
curl -fsSL "https://raw.githubusercontent.com/davidggjg/zovex/$REF/vps-bot/zv_tokens.py" -o $T || die "הורדה נכשלה"
(cd $(dirname $T) && cp $T zv_tokens_check.py && "$PY" -c "import ast;ast.parse(open('zv_tokens_check.py').read())"; rm -f zv_tokens_check.py) || die "קובץ פגום"
cp $DIR/zv_tokens.py $DIR/zv_tokens.py.prev
cp $T $DIR/zv_tokens.py
systemctl restart zovex-bot
for i in $(seq 1 30); do sleep 2; R=$(curl -fsS -m 5 http://127.0.0.1:8000/api/auth/config 2>/dev/null) && break; done
[ -n "${R:-}" ] || { cp $DIR/zv_tokens.py.prev $DIR/zv_tokens.py; systemctl restart zovex-bot; die "השרת לא עלה — שוחזר"; }
echo "✅ עודכן: $R"
