#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# ZOVEX · החלפת ליבת טלגרם: Pyrogram 2.0.106 (נטושה מ-2023) → kurigram 2.2.27
#
#   1. גיבוי: main.py + כל קבצי ה-session (kurigram משנה את הסכמה שלהם).
#   2. סביבה נפרדת venv_k (העתק של venv + kurigram). venv המקורי לא נוגעים בו.
#   3. שכבת התאמה ב-main.py (עובדת על שתי הספריות; שומרת על עקיפת DC4).
#   4. השירות עובר ל-venv_k דרך drop-in של systemd (מחיקתו = חזרה).
#   5. בדיקה: השרת עולה, קטלוג נטען, ו-3 סרטים אמיתיים מחזירים 1MB.
#      כישלון ⇒ חזרה אוטומטית לגיבוי.
#
#   sudo bash deploy_kurigram.sh              ·   sudo bash deploy_kurigram.sh --rollback
# ═══════════════════════════════════════════════════════════════════════════
set -u
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
DIR=/opt/zovex-bot; OLD="$DIR/venv"; NEW="$DIR/venv_k"
DROP=/etc/systemd/system/zovex-bot.service.d/zz-kurigram.conf
BAKDIR=/opt/zovex-bot-core-backup
die(){ echo "❌ $*"; exit 1; }

rollback(){
  echo "↩ חוזר ל-Pyrogram…"
  systemctl stop zovex-bot
  rm -f "$DROP"; systemctl daemon-reload
  LAST=$(ls -1t $BAKDIR/sessions_*.tgz 2>/dev/null | head -1)
  [ -n "$LAST" ] && tar xzf "$LAST" -C / && echo "   קבצי session שוחזרו מ-$LAST"
  systemctl start zovex-bot
  for i in $(seq 1 30); do sleep 2; curl -fsS -m 5 -o /dev/null http://127.0.0.1:8000/app/version && { echo "✅ חזר ל-Pyrogram ועובד"; return 0; }; done
  echo "⚠ השרת לא עלה אחרי החזרה — שלח: journalctl -u zovex-bot -n 60"
}
if [ "${1:-}" = "--rollback" ]; then rollback; exit 0; fi

# ── 0. בדיקות מקדימות ─────────────────────────────────────────────────────
[ -x "$OLD/bin/python" ] || die "לא נמצא $OLD"
"$OLD/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' || die "דרוש Python 3.10+"
[ "$(df --output=avail -BM / | tail -1 | tr -dc 0-9)" -gt 2000 ] || die "פחות מ-2GB פנויים"
[ -f "$DROP" ] && die "kurigram כבר מותקן (להסרה: --rollback)"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
curl -fsSL "https://raw.githubusercontent.com/davidggjg/zovex/$REF/vps-bot/fix_kurigram_compat.py" -o $T/compat.py || die "הורדה נכשלה"

# ── 1. סביבה חדשה (השרת עדיין רץ כרגיל) ─────────────────────────────────
echo "① בונה סביבה נפרדת עם kurigram (השרת ממשיך לרוץ)…"
rm -rf "$NEW"; cp -a "$OLD" "$NEW" || die "העתקת venv נכשלה"
sed -i "s#$OLD#$NEW#g" "$NEW"/bin/activate* 2>/dev/null
"$NEW/bin/python" -m pip uninstall -y -q pyrogram >/dev/null 2>&1
"$NEW/bin/python" -m pip install -q "kurigram==2.2.27" 2>&1 | grep -v -i "warn\|notice" | tail -3
"$NEW/bin/python" -c "import pyrogram, sys; print('   ', pyrogram.__version__); sys.exit(0 if pyrogram.__version__.startswith('2.2') else 1)" || { rm -rf "$NEW"; die "התקנת kurigram נכשלה — לא נגעתי בשרת"; }
"$NEW/bin/python" -c "from pyrogram.crypto import aes" 2>&1 | grep -qi "slower" && echo "   ⚠ בלי האצת הצפנה" || echo "    האצת הצפנה: פעילה"

# ── 2. שכבת התאמה (לא פעילה על Pyrogram — בטוח להחיל לפני המעבר) ─────────
echo "② שכבת התאמה ב-main.py"
cp $DIR/main.py $T/main.before
MAIN_PY=$DIR/main.py python3 $T/compat.py || die "שכבת ההתאמה לא הוחלה — לא נגעתי בשרת"
"$NEW/bin/python" -m py_compile $DIR/main.py || { cp $T/main.before $DIR/main.py; die "שגיאת תחביר — שוחזר"; }
(cd $DIR && timeout 60 "$NEW/bin/python" -c "
import ast,sys; src=open('main.py').read(); tree=ast.parse(src)
for n in tree.body:
    if isinstance(n,(ast.Import,ast.ImportFrom)) and 'pyrogram' in ast.unparse(n): exec(ast.unparse(n))
print('    כל ה-imports של pyrogram נטענים ב-kurigram')") || { cp $T/main.before $DIR/main.py; rm -rf "$NEW"; die "import נכשל ב-kurigram — שוחזר, לא נגעתי בשרת"; }

# ── 3. גיבוי + מעבר ──────────────────────────────────────────────────────
TS=$(date +%Y%m%d-%H%M%S); mkdir -p $BAKDIR
echo "③ עוצר את השרת לגיבוי עקבי של קבצי ה-session…"
systemctl stop zovex-bot
tar czf $BAKDIR/sessions_$TS.tgz $DIR/data/*.session* $DIR/*.session* 2>/dev/null
cp $T/main.before $BAKDIR/main.py.before_kurigram_$TS
echo "   גיבוי: $BAKDIR/sessions_$TS.tgz ($(du -h $BAKDIR/sessions_$TS.tgz | cut -f1))"
mkdir -p "$(dirname $DROP)"
printf '[Service]\nExecStart=\nExecStart=%s/bin/python %s/main.py\n' "$NEW" "$DIR" > "$DROP"
systemctl daemon-reload; systemctl start zovex-bot

# ── 4. בדיקה אמיתית ──────────────────────────────────────────────────────
echo "④ בודק…"
up=0; for i in $(seq 1 45); do sleep 2; curl -fsS -m 5 -o /dev/null http://127.0.0.1:8000/app/version && { up=1; break; }; done
[ $up = 1 ] || { journalctl -u zovex-bot -n 40 --no-pager; rollback; die "השרת לא עלה עם kurigram — חזרתי"; }
echo "   השרת עלה. מחכה 40ש שהבוטים יתחברו…"; sleep 40
journalctl -u zovex-bot --since "-2min" --no-pager | grep -q "kurigram compat פעיל" && echo "   שכבת ההתאמה פעילה ✓" || echo "   ⚠ לא נמצאה שורת ההתאמה ביומן"
URLS=$(curl -s -m 60 http://127.0.0.1:8000/content/lite | python3 -c "import json,sys,random;d=[m['video_url'] for m in json.load(sys.stdin) if '/stream/' in (m.get('video_url') or '')];random.shuffle(d);print('\n'.join(x.replace('https://zovex.duckdns.org','http://127.0.0.1:8000') for x in d[:3]))")
[ -n "$URLS" ] || { rollback; die "הקטלוג לא נטען — חזרתי"; }
good=0
for u in $URLS; do
  r=$(curl -s -m 60 -o /dev/null -r 0-1048575 -w "%{size_download} %{time_total}" "$u")
  sz=${r%% *}; echo "   סרט: ${sz} בייטים ב-${r##* }ש"
  [ "$sz" = "1048576" ] && good=$((good+1))
done
if [ $good -lt 2 ]; then
  journalctl -u zovex-bot -n 40 --no-pager | grep -i "error\|traceback\|exception" | tail -15
  rollback; die "רק $good/3 סרטים נוגנו עם kurigram — חזרתי ל-Pyrogram. שלח לי את הפלט"
fi
echo
echo "✅ הליבה הוחלפה ל-kurigram 2.2.27 ($good/3 סרטים נוגנו)."
echo "   גיבוי: $BAKDIR   ·   חזרה: sudo bash $0 --rollback"
echo "   תן 10-15 דק׳ להתייצב, צפה, ואז zv-stalls (אם מותקן)."
