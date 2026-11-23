#!/bin/bash
# ZOVEX · אימות אפליקציות (MSL-style) + הגבלות ספאם + טאב 🛡 אבטחה בפאנל.
# מתחיל במצב "מעקב בלבד" — לא חוסם אף אחד. אכיפה מופעלת מהפאנל.
#   sudo bash deploy_security.sh            ·   sudo bash deploy_security.sh --rollback
set -u
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
DIR=/opt/zovex-bot; PY="$DIR/venv/bin/python"; [ -x "$PY" ] || PY=python3
RAW="https://raw.githubusercontent.com/davidggjg/zovex/$REF/vps-bot"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
die(){ echo "❌ $*"; exit 1; }
for f in zv_tokens.py fix_app_tokens.py fix_abuse_limits.py patch_panel_tokens.py panel_tokens.js zv-auth.js; do
  curl -fsSL "$RAW/$f" -o "$T/$f" || die "הורדת $f נכשלה"; done
if [ "${1:-}" = "--rollback" ]; then
  MAIN_PY=$DIR/main.py python3 $T/fix_app_tokens.py --revert
  MAIN_PY=$DIR/main.py python3 $T/fix_abuse_limits.py --revert
  PANEL=$DIR/admin.html python3 $T/patch_panel_tokens.py --revert
  systemctl restart zovex-bot; echo "✅ הוסר (הקובץ zv_tokens.py נשאר בצד ולא נטען)"; exit 0
fi
echo "① ספריית הצפנה"
"$PY" -c "import cryptography" 2>/dev/null || "$PY" -m pip install -q cryptography || die "התקנת cryptography נכשלה"
cp $DIR/main.py $T/main.before; cp $DIR/admin.html $T/admin.before
echo "② מודול האימות"
cp $T/zv_tokens.py $DIR/zv_tokens.py
(cd $DIR && "$PY" -c "import zv_tokens") || die "המודול לא נטען — לא נגעתי ב-main.py"
echo "③ חיבור לשרת + הגבלות ספאם"
MAIN_PY=$DIR/main.py python3 $T/fix_abuse_limits.py || die "fix_abuse_limits נכשל"
MAIN_PY=$DIR/main.py python3 $T/fix_app_tokens.py || { cp $T/main.before $DIR/main.py; die "fix_app_tokens נכשל — שוחזר"; }
"$PY" -m py_compile $DIR/main.py || { cp $T/main.before $DIR/main.py; die "שגיאת תחביר — שוחזר"; }
echo "④ טאב אבטחה בפאנל"
PANEL=$DIR/admin.html JS=$T/panel_tokens.js AUTH_JS=$T/zv-auth.js python3 $T/patch_panel_tokens.py || echo "⚠ הפאנל לא עודכן (השרת כן)"
echo "⑤ הפעלה מחדש"
systemctl restart zovex-bot
ok=0; for i in $(seq 1 20); do sleep 2; curl -fsS -m 5 http://127.0.0.1:8000/api/auth/config >/dev/null 2>&1 && { ok=1; break; }; done
if [ $ok != 1 ]; then
  cp $T/main.before $DIR/main.py; cp $T/admin.before $DIR/admin.html; systemctl restart zovex-bot
  journalctl -u zovex-bot -n 20 --no-pager; die "השרת לא עלה עם האימות — שוחזר הכל"
fi
echo "✅ פעיל במצב מעקב: $(curl -s http://127.0.0.1:8000/api/auth/config)"
echo "   פאנל → 🛡 אבטחה. לא להפעיל אכיפה לפני שהאפליקציות מעודכנות."
