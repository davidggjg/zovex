#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · בריאות הבוטים: ספסל לאיטיים, זיהוי חניקה, ואבחון DC.
#
# ## מה נמדד
#
# אותו קובץ, אותו רגע, 4 חיבורים לכל בוט:
#   6.78 MB/s · 1.86 · 1.44 · 0.25 · 0.25 · 0.08 · שניים ב-timeout
#
# פער של פי 85. התוכן נע בין 50MB ל-4GB; סרט 4GB בשעתיים צורך ~0.55 MB/s,
# כלומר בוט שנותן 0.08 אינו מחזיק אפילו צופה אחד — והקוד שלח אליו צופים
# כאילו הוא תקין, כי cooldown הופעל רק על שגיאה ואיטיות לא נחשבה כשל.
#
# ## שלושה טלאים, משלימים
#
# 1. flood_premium — Pyrogram 2.0.106 אינו מכיר את FLOOD_PREMIUM_WAIT
#    (אומת על השרת), ולכן היא נפלה ל-except הגנרי, נספרה ככשל רך, והקוד
#    המשיך להפציץ בוט חנוק — מה שמאריך את העונש. עכשיו: הזמן נלקח
#    מהשגיאה, קירור מיידי, בלי הסלמה.
#
# 2. slow_bench — איטיות מתמשכת שולחת בוט לספסל זמני עם חזרה אוטומטית.
#    לא מחיקה: 50 אדמינים לערוץ ו-20 בוטים לחשבון, ובוט חדש מוגבל
#    להעברות ל-20 דקות עד 24 שעות ויתאושש לבד.
#
# 3. bot_dc — מציג ב-/speedtest/bots את ה-DC של כל בוט ושל הקובץ, כדי
#    לדעת אם האיטיות היא מיקום (ואז מחליפים אותם) או זמנית (ואז הספסל
#    לבדו מספיק). חשוב לדעת לפני שנוצרים עשרות בוטים נוספים.
#
# ## רשתות ביטחון בספסל
#
# מדגם מתחת ל-1MB לא נספר (בקשת moov קטנה נותנת MB/s נמוך בגלל השהיה);
# צריך 3 מדידות איטיות ברצף; ולעולם לא יישלח בוט לספסל אם יישארו פחות
# מ-3 זמינים.
#
#   sudo bash deploy_bots_health.sh
#   sudo bash deploy_bots_health.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

SVC=zovex-bot
DIR=/opt/zovex-bot
LIVE="$DIR/main.py"
PY="$DIR/venv/bin/python"
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot"
API="http://127.0.0.1:8000"
PATCHES="patch_flood_premium patch_slow_bench patch_bot_dc"

die() { echo "❌ $*" >&2; exit 1; }
wait_up() {
  for _ in $(seq 1 80); do
    curl -fsS -m 3 "$API/ping" >/dev/null 2>&1 && return 0
    sleep 3
  done
  return 1
}

[ -f "$LIVE" ] || die "$LIVE לא קיים — זה לא שרת ZOVEX"
[ -x "$PY" ]   || PY=python3

echo "① מוריד את הטלאים"
for p in $PATCHES; do
  curl -fsSL "$RAW/$p.py" -o "/tmp/$p.py" || die "הורדת $p נכשלה"
done

if [ "${1:-}" = "--rollback" ]; then
  # בסדר הפוך לסדר ההחלה
  for p in patch_bot_dc patch_slow_bench patch_flood_premium; do
    "$PY" "/tmp/$p.py" "$LIVE" --revert || echo "   ⚠️ $p: אין מה לשחזר"
  done
  systemctl restart "$SVC" || die "restart נכשל"
  wait_up && echo "✅ שוחזר" || echo "⚠️  שוחזר, אבל /ping לא ענה"
  exit 0
fi

echo "② מחיל (כל טלאי: התאמה מדויקת, או סירוב בלי לגעת)"
for p in $PATCHES; do
  printf '   %-22s ' "$p"
  "$PY" "/tmp/$p.py" "$LIVE" >/tmp/$p.out 2>&1 \
    || { cat /tmp/$p.out; die "$p לא הוחל — שום שינוי לא נשמר בשרת החי?
        בדוק את הפלט למעלה ושלח לי אותו."; }
  head -1 /tmp/$p.out
done

echo "③ מפעיל מחדש (הבוטים עולים בהדרגה — דקות)"
systemctl restart "$SVC" || die "restart נכשל"
wait_up || die "/ping לא ענה.  לשחזור: sudo bash $0 --rollback"

echo
echo "④ מאמת ששלושתם חיים בתהליך"
curl -fsS -m 15 "$API/debug/caches" | "$PY" -c 'import json,sys
d = json.load(sys.stdin)
missing = [k for k in ("flood_premium", "benched_total", "bot_speeds") if k not in d]
if missing:
    sys.exit("   ❌ חסרים שדות: " + ", ".join(missing) + " — קוד ישן עדיין רץ")
print("   flood_premium = " + str(d["flood_premium"]))
print("   benched_total = " + str(d["benched_total"]))
print("   בוטים במעקב   = " + str(len(d["bot_speeds"])))' \
  || die "האימות נכשל.  לשחזור: sudo bash $0 --rollback"

cat <<EOF

────────────────────────────────────────────────────────────
✅ נפרס.

עכשיו תן לזה לרוץ כמה שעות עם צופים אמיתיים. הבוטים צריכים
להצטבר מדידות לפני שהספסל מתחיל לעבוד.

אחר כך — התמונה המלאה בפקודה אחת:

  curl -s $API/debug/caches | $PY -m json.tool | grep -A30 bot_speeds

  · בוטים עם מהירות מעל 0.6  → אלה שמחזיקים אותך
  · בוטים מתחת               → יושבים בספסל וחוזרים לבדיקה לבד
  · flood_premium גדול מ-0   → טלגרם חונקים; לא להוסיף מקביליות

ולשאלה אם זו בעיית DC (חשוב לפני שתיצור עוד בוטים):

  curl -s "$API/speedtest/bots?mb=4&n=10" | $PY -m json.tool | grep -E 'who|mb_per_sec|home_dc|cross_dc'

  אם כל האיטיים חולקים home_dc אחד — אל תיצור בוטים חדשים
  מאותה קידומת. זה יחסוך לך עשרות בוטים מבוזבזים.

לשחזור הכל:  sudo bash /tmp/deploy_bots_health.sh --rollback
EOF
