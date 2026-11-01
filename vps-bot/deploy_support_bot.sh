#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · התקנת בוט התמיכה כשירות נפרד.
#
# שירות משלו ולא טלאי ל-main.py: אם התמיכה תיפול אסור שההזרמה תיפול
# איתה, ולהפך. אין תלויות חדשות ואין נגיעה ב-venv.
#
# הבוט מגשר גם על צ'אט התמיכה הקיים של האתר והאפליקציה: פנייה משם
# נכנסת לאותה קבוצה, ותשובה בקבוצה חוזרת לצ'אט של המשתמש דרך
# POST /feedback/reply — הנתיב שגם שולח לו את ההתראה לטלפון. ולכן
# הוא צריך PANEL_PASSWORD, ש-main.py כבר מחזיק באותו .env.
#
# אין שינוי ב-main.py, באתר, באפליקציה או ב-nginx.
#
# דורש ב-/opt/zovex-bot/.env:
#   SUPPORT_BOT_TOKEN=...
#   SUPPORT_GROUP_ID=-1004491660594
#
#   sudo bash deploy_support_bot.sh
#   sudo bash deploy_support_bot.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u
DIR=/opt/zovex-bot
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
# ?t= מכריח את המטמון של raw.githubusercontent להתחדש. בלעדיו הרצה
# מחדש מיד אחרי דחיפה מורידה עד חמש דקות את הקובץ הקודם, והשרת ממשיך
# להריץ קוד שאינו מכיר את התיקון שזה עתה נכתב. זה בדיוק מה שקרה.
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/support_bot.py?t=$(date +%s)"
UNIT=/etc/systemd/system/zovex-support.service
die(){ echo "❌ $*" >&2; exit 1; }

[ -d "$DIR" ] || die "$DIR לא קיים — זה לא שרת ZOVEX"

if [ "${1:-}" = "--rollback" ]; then
  systemctl disable --now zovex-support 2>/dev/null
  rm -f "$UNIT"; systemctl daemon-reload
  echo "✅ השירות הוסר. support_bot.py ו-support_state.json נשארו ב-$DIR"
  exit 0
fi

grep -q '^SUPPORT_BOT_TOKEN=.\+' "$DIR/.env" || die "SUPPORT_BOT_TOKEN חסר ב-$DIR/.env"
grep -q '^PANEL_PASSWORD=.\+' "$DIR/.env" || die "PANEL_PASSWORD חסר ב-$DIR/.env — בלעדיו אי אפשר להחזיר תשובה לצ'אט של האתר"
if ! grep -q '^SUPPORT_GROUP_ID=.\+' "$DIR/.env"; then
  echo "SUPPORT_GROUP_ID=-1004491660594" >> "$DIR/.env"
  echo "   SUPPORT_GROUP_ID נכתב"
fi
chmod 600 "$DIR/.env"

echo "① מוריד את הקוד"
curl -fsSL -H 'Cache-Control: no-cache' -H 'Pragma: no-cache' \
     "$RAW" -o "$DIR/support_bot.py.new" || die "ההורדה נכשלה"
python3 -m py_compile "$DIR/support_bot.py.new" || die "הקוד שהורד לא מתקמפל"
VER=$(grep -m1 '^VERSION = ' "$DIR/support_bot.py.new" | cut -d'"' -f2)
[ -n "$VER" ] || die "הקובץ שהתקבל אינו support_bot.py (מטמון?)"
echo "   גרסה $VER"
mv "$DIR/support_bot.py.new" "$DIR/support_bot.py"

echo "② בדיקה עצמית לפני שמחליפים שירות פעיל"
SUPPORT_STATE=/tmp/zovex_support_pre.json python3 "$DIR/support_bot.py" --selftest \
  >/tmp/zovex_support_selftest.log 2>&1 \
  || { tail -20 /tmp/zovex_support_selftest.log; die "הבדיקה העצמית נכשלה — השירות לא נוגע"; }
grep -c '✅' /tmp/zovex_support_selftest.log | xargs -I{} echo "   {} בדיקות עברו"
rm -f /tmp/zovex_support_pre.json

echo "③ כותב יחידת systemd"
cat > "$UNIT" <<UEOF
[Unit]
Description=ZOVEX support bridge bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$DIR
EnvironmentFile=$DIR/.env
ExecStart=/usr/bin/python3 $DIR/support_bot.py
Restart=always
RestartSec=5
# תקרה צנועה: זה בוט טקסט. אם הוא יזלוג, הוא לא ייקח את ההזרמה איתו.
MemoryMax=192M
Nice=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UEOF
systemctl daemon-reload
systemctl enable zovex-support >/dev/null 2>&1

# restart ולא enable --now: ‎--now‎ אינו עושה דבר כששירות כבר פעיל,
# ולכן כל התקנה חוזרת החליפה את הקובץ בדיסק בעוד התהליך הישן ממשיך
# לרוץ עם הקוד הקודם בזיכרון. זה בדיוק מה שקרה כאן, ולא נראה כשגיאה.
systemctl stop zovex-support 2>/dev/null
# התהליך הישן מחזיק את הפורט; בלי להמתין לשחרורו השירות החדש עולה
# בלי שרת ה-HTTP ונראה תקין.
for i in 1 2 3 4 5 6 7 8 9 10; do
  pgrep -f "$DIR/support_bot.py" >/dev/null || break
  sleep 1
done
pgrep -f "$DIR/support_bot.py" >/dev/null && { pkill -f "$DIR/support_bot.py"; sleep 2; }
systemctl start zovex-support || die "ההפעלה נכשלה"

echo "④ בודק"
sleep 6
systemctl is-active --quiet zovex-support || { journalctl -u zovex-support -n 30 --no-pager; die "השירות אינו פעיל"; }
curl -fsS --max-time 5 http://127.0.0.1:8107/health && echo
# מאמתים שהגרסה שרצה היא זו שהורדנו, ולא קוד ישן ששרד restart כלשהו.
LIVE=$(curl -fsS --max-time 5 http://127.0.0.1:8107/health | grep -o '"version": *"[^"]*"' | cut -d'"' -f4)
if [ "$LIVE" = "$VER" ]; then
  echo "   גרסה $LIVE רצה עכשיו ✓"
else
  echo "⚠️ השירות מדווח גרסה '$LIVE' ולא $VER"
  journalctl -u zovex-support -n 30 --no-pager
  die "הגרסה שרצה אינה זו שהותקנה"
fi
# הגשר שותק בשקט אם הקובץ אינו במקום שהוא מחפש בו, ולכן נבדק כאן
# ולא מתגלה רק כשמשתמש כותב באתר.
FB="$(grep -m1 '^DATA_DIR=' "$DIR/.env" | cut -d= -f2-)"; FB="${FB:-/opt/zovex-bot/data}/feedback.json"
if [ -f "$FB" ]; then
  echo "   גשר האתר: $FB ($(python3 -c "import json;print(len(json.load(open('$FB'))))" 2>/dev/null || echo '?') שיחות) ✓"
else
  echo "⚠️ $FB לא נמצא — פניות מהאתר/אפליקציה לא יגיעו לקבוצה"
fi
journalctl -u zovex-support -n 12 --no-pager
echo
echo "✅ בוט התמיכה פעיל."
echo "   בדיקה 1: כתוב /ping בקבוצה — הבוט יענה שם עם מצבו."
echo "   בדיקה 2: כתוב הודעה לבוט בטלגרם — היא תופיע בקבוצה עם כפתורים."
echo "   בדיקה 3: כתוב בצ'אט התמיכה באתר — הפנייה תופיע באותה קבוצה,"
echo "            ותגובה עליה בקבוצה תחזור לצ'אט באתר ותשלח התראה לטלפון."
echo
echo "   יומן חי:  journalctl -u zovex-support -f"
