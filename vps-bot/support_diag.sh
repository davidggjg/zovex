#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · אבחון גשר התמיכה.
#
# "הוא לא מגיב לאתר" יכול להיות שבעה דברים שונים, ומבחוץ כולם נראים
# אותו דבר. הסקריפט בודק אותם אחד-אחד ומדפיס מה נכון עכשיו בשרת:
#
#   1. איזה תהליך רץ ואיזו גרסה
#   2. איפה main.py החי שומר את שיחות התמיכה
#   3. איפה הבוט מחפש אותן
#   4. האם הקובץ נקרא, מתי השתנה, וכמה שיחות יש בו
#   5. האם ההודעה האחרונה שנכתבה שם היא אחרי שהבוט עלה
#   6. האם הבוט כבר "ראה" אותה
#   7. האם אפשר להחזיר תשובה דרך /feedback/reply
#
# קריאה בלבד — אינו משנה דבר ואינו שולח הודעה לאף אחד.
#
#   sudo bash support_diag.sh
# ─────────────────────────────────────────────────────────────────────────────
DIR=/opt/zovex-bot
ENVF="$DIR/.env"
say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

say "① התהליך"
pgrep -af 'support_bot.py' || echo "   אין תהליך של הבוט!"
systemctl is-active zovex-support 2>/dev/null | sed 's/^/   systemd: /'
curl -fsS --max-time 5 http://127.0.0.1:8107/health 2>/dev/null | sed 's/^/   health: /' \
  || echo "   health: אין תשובה מ-8107"

say "② איפה main.py החי שומר תמיכה"
grep -n 'FEEDBACK_FILE *=' "$DIR/main.py" | sed 's/^/   /'
grep -n '^DATA_DIR *=\|DATA_DIR = Path' "$DIR/main.py" | head -2 | sed 's/^/   /'
grep -n '@api.post("/feedback/send")\|@api.post("/feedback/reply")' "$DIR/main.py" | sed 's/^/   /'
echo "   --- חתימת feedback_reply (מה שהבוט קורא לו):"
sed -n "/@api.post(\"\/feedback\/reply\")/,/^@api\./p" "$DIR/main.py" | head -25 | sed 's/^/   /'

say "③ איפה הבוט מחפש"
grep -m1 '^DATA_DIR=' "$ENVF" | sed 's/^/   .env: /' || echo "   .env: אין DATA_DIR (ברירת מחדל /opt/zovex-bot/data)"
grep -m1 '^FEEDBACK_FILE=' "$ENVF" | sed 's/^/   .env: /'
grep -q '^PANEL_PASSWORD=.\+' "$ENVF" && echo "   PANEL_PASSWORD: קיים" || echo "   PANEL_PASSWORD: ❌ חסר"
grep -m1 '^PORT=' "$ENVF" | sed 's/^/   .env: /' || echo "   .env: אין PORT (ברירת מחדל 8000)"

DD=$(grep -m1 '^DATA_DIR=' "$ENVF" | cut -d= -f2-); DD="${DD:-/opt/zovex-bot/data}"
FB="$DD/feedback.json"

say "④ הקובץ"
if [ -f "$FB" ]; then
  ls -l --time-style=+'%Y-%m-%d %H:%M:%S' "$FB" | sed 's/^/   /'
  echo "   עכשיו:               $(date +'%Y-%m-%d %H:%M:%S')"
  python3 - "$FB" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
print("   שיחות: %d" % len(d))
rows = []
for uid, th in d.items():
    ms = th.get("messages") or []
    if ms:
        rows.append((ms[-1].get("ts", ""), uid, len(ms), ms[-1].get("from"),
                     (ms[-1].get("text") or "")[:40]))
rows.sort(reverse=True)
print("   חמש השיחות שעודכנו אחרונות (זמנים ב-UTC):")
for ts, uid, n, frm, tx in rows[:5]:
    print("     %s  %-28s %2d הודעות  אחרונה מ-%-5s  %s" % (ts, uid[:28], n, frm, tx))
PY
else
  echo "   ❌ $FB אינו קיים — חפש אותו:"
  find /opt/zovex-bot -name 'feedback*.json' -printf '      %p  (%TY-%Tm-%Td %TH:%TM)\n' 2>/dev/null
fi

say "⑤ מה הבוט כבר ראה"
ST="$DIR/support_state.json"
if [ -f "$ST" ]; then
  python3 - "$ST" <<'PY'
import json, sys
s = json.load(open(sys.argv[1], encoding="utf-8"))
fb = s.get("fb") or {}
print("   שיחות שהגשר מכיר: %d" % len(fb))
for uid, rec in list(fb.items())[:8]:
    print("     %-28s seen=%s  כרטיס=%s" % (uid[:28], rec.get("seen"), rec.get("tid")))
if not fb:
    print("     ריק — או שהגשר לא רץ, או שהוא לא מצא את הקובץ,")
    print("     או שאף שיחה לא התעדכנה מאז שעלה.")
PY
else
  echo "   ❌ $ST אינו קיים — הבוט עוד לא שמר מצב"
fi

say "⑥ היומן (גשר, גרסה, שגיאות)"
journalctl -u zovex-support -n 200 --no-pager 2>/dev/null \
  | grep -E 'גרסה|גשר|privacy|PANEL_PASSWORD|⚠️|❌|שגיאה|Traceback|Error' | tail -15 | sed 's/^/   /'

say "⑦ האם אפשר להחזיר תשובה"
PW=$(grep -m1 '^PANEL_PASSWORD=' "$ENVF" | cut -d= -f2-)
MP=$(grep -m1 '^PORT=' "$ENVF" | cut -d= -f2-); MP="${MP:-8000}"
if [ -n "$PW" ]; then
  # user_id שאינו קיים: התשובה הצפויה היא 404 "לא נמצא". 403 פירושו
  # שהסיסמה נדחתה, וזו הייתה הסיבה שהתשובות לא חוזרות.
  CODE=$(curl -s -o /tmp/_fbr -w '%{http_code}' --max-time 10 \
    -X POST "http://127.0.0.1:$MP/feedback/reply" -H 'Content-Type: application/json' \
    -d "{\"password\":\"$PW\",\"user_id\":\"zzz:diag-not-real\",\"text\":\"diag\"}")
  echo "   POST /feedback/reply → $CODE  $(head -c 120 /tmp/_fbr)"
  case "$CODE" in
    404) echo "   ✅ הסיסמה התקבלה (404 = המשתמש המדומה לא קיים, כצפוי)";;
    403) echo "   ❌ הסיסמה נדחתה — PANEL_PASSWORD ב-.env אינו של הפאנל";;
    000) echo "   ❌ אין תשובה מ-main.py בפורט $MP";;
    *)   echo "   ⚠️ תשובה לא צפויה — ראה למעלה";;
  esac
  rm -f /tmp/_fbr
else
  echo "   דילוג: אין PANEL_PASSWORD"
fi
echo
