#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · "בלי טריילר" הופך למרכז "חסרים".
#
# הכרטיס הקיים ענה על שאלה אחת: למי אין טריילר. אבל חסרים גם תיאורים
# ופוסטרים, ולא היה שום מקום בפאנל שמראה אותם — ולכן לא היה אפשר לדעת
# כמה חסר ומה לתקן קודם.
#
# נוספה /panel/missing עם ארבעה סוגים: טריילר, פוסטר, תיאור, ו-tmdb_id.
# המזהה מקבל רשימה משלו כי הוא השורש — בלעדיו אין מאיפה למשוך תיאור,
# פוסטר או טריילר אוטומטית.
#
# התשובה כוללת תמיד ספירה של כל הארבעה, כדי שהפאנל יראה את התמונה
# המלאה גם כשמסתכלים על רשימה אחת.
#
# /panel/no-trailer נשאר כפי שהוא: פאנל ישן שפתוח בדפדפן לא נשבר.
#
#   sudo bash deploy_missing_panel.sh
#   sudo bash deploy_missing_panel.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

SVC=zovex-bot
DIR=/opt/zovex-bot
LIVE="$DIR/main.py"
PANEL="$DIR/admin.html"
PY="$DIR/venv/bin/python"
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/patch_missing_panel.py"
API="http://127.0.0.1:8000"

die() { echo "❌ $*" >&2; exit 1; }
wait_up() {
  for _ in $(seq 1 80); do
    curl -fsS -m 3 "$API/ping" >/dev/null 2>&1 && return 0
    sleep 3
  done
  return 1
}

[ -f "$LIVE" ]  || die "$LIVE לא קיים — זה לא שרת ZOVEX"
[ -f "$PANEL" ] || die "$PANEL לא קיים"
[ -x "$PY" ]    || PY=python3
curl -fsSL "$RAW" -o /tmp/patch_missing_panel.py || die "הורדת הטלאי נכשלה"

if [ "${1:-}" = "--rollback" ]; then
  "$PY" /tmp/patch_missing_panel.py "$LIVE" "$PANEL" --revert || die "השחזור נכשל"
  systemctl restart "$SVC" || die "restart נכשל"
  wait_up && echo "✅ שוחזר" || echo "⚠️  שוחזר, אבל /ping לא ענה"
  exit 0
fi

echo "① מחיל על main.py ועל admin.html"
"$PY" /tmp/patch_missing_panel.py "$LIVE" "$PANEL" || die "לא הוחל"

echo "② מפעיל מחדש (הבוטים עולים בהדרגה — דקות)"
systemctl restart "$SVC" || die "restart נכשל"
wait_up || die "/ping לא ענה.  לשחזור: sudo bash $0 --rollback"

echo
echo "③ מאמת שהשדות חוזרים מהשרת"
read -r -s -p "   סיסמת הפאנל (לא מוצגת): " PASS; echo
for K in trailer poster desc tmdb; do
  curl -fsS -m 60 "$API/panel/missing?kind=$K" -H "X-Panel-Password: $PASS" \
    | "$PY" -c 'import json,sys
d = json.load(sys.stdin)
c = d.get("counts", {}).get(sys.argv[1])
if c is None:
    sys.exit("   ❌ לא חזרו ספירות — קוד ישן עדיין רץ")
name = {"trailer":"בלי טריילר","poster":"בלי פוסטר",
        "desc":"בלי תיאור","tmdb":"בלי מזהה TMDB"}[sys.argv[1]]
print("   " + name.ljust(16) + " סרטים " + str(c["movies"]).rjust(6) +
      "   סדרות " + str(c["series"]).rjust(5))' "$K" \
    || die "האימות נכשל (סיסמה שגויה?).  לשחזור: sudo bash $0 --rollback"
done

cat <<EOF

────────────────────────────────────────────────────────────
✅ נפרס.

רענן את הפאנל עם Ctrl+Shift+R. הלשונית "🎬 בלי טריילר" נקראת
עכשיו "🧩 חסרים", ובתוכה ארבעה כפתורים:

  🎬 בלי טריילר   🖼 בלי פוסטר   📝 בלי תיאור   🔗 בלי מזהה TMDB

בראש הרשימה מוצגת ספירה של כל הארבעה יחד, גם כשמסתכלים על
אחד — כך רואים מה הכי דחוף.

התחל מ-"בלי מזהה TMDB": בלי המזהה אין מאיפה למשוך תיאור,
פוסטר או טריילר, ולכן כל השאר תלוי בו.

לשחזור:  sudo bash /tmp/deploy_missing_panel.sh --rollback
EOF
