#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · הפאנל מציג את ה-@ של כל בוט, את המזהה ואת המהירות.
#
# הרקע ב-patch_pool_panel.py. בקצרה: בערוץ הבוטים מופיעים לפי ה-@ שלהם,
# ובפאנל הם הופיעו כ-bot_0/bot_1 — שם פנימי שנגזר מהסדר בקובץ הטוקנים.
# לכן אי אפשר היה להצליב בין מי שרשום כאדמין בערוץ למי שיש לנו טוקן
# עבורו, ולא ניתן היה לנקות בוטים זרים מרשימת האדמינים.
#
# המידע כבר הוחזר מ-/pool/list (who, uid); רק התצוגה חסרה. נוספה גם
# המהירות הנמדדת, כי בלעדיה אפשר לזהות בוט אבל לא לדעת אם הוא שווה את
# מקומו — ונמדד פער של פי 85 בין הבוטים.
#
#   sudo bash deploy_pool_panel.sh
#   sudo bash deploy_pool_panel.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

SVC=zovex-bot
DIR=/opt/zovex-bot
LIVE="$DIR/main.py"
PANEL="$DIR/admin.html"
PY="$DIR/venv/bin/python"
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/patch_pool_panel.py"
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
curl -fsSL "$RAW" -o /tmp/patch_pool_panel.py || die "הורדת הטלאי נכשלה"

if [ "${1:-}" = "--rollback" ]; then
  "$PY" /tmp/patch_pool_panel.py "$LIVE" "$PANEL" --revert || die "השחזור נכשל"
  systemctl restart "$SVC" || die "restart נכשל"
  wait_up && echo "✅ שוחזר" || echo "⚠️  שוחזר, אבל /ping לא ענה"
  exit 0
fi

echo "① מחיל על main.py ועל admin.html"
"$PY" /tmp/patch_pool_panel.py "$LIVE" "$PANEL" || die "לא הוחל"

echo "② מפעיל מחדש (הבוטים עולים בהדרגה — דקות)"
systemctl restart "$SVC" || die "restart נכשל"
wait_up || die "/ping לא ענה.  לשחזור: sudo bash $0 --rollback"

echo
echo "③ מאמת שהשדות חוזרים מהשרת"
read -r -s -p "   סיסמת הפאנל (לא מוצגת): " PASS; echo
curl -fsS -m 15 -X POST "$API/pool/list" \
  -H 'Content-Type: application/json' -d "{\"password\":\"$PASS\"}" \
  | "$PY" -c 'import json,sys
d = json.load(sys.stdin)
bots = d.get("bots") or []
if not bots:
    sys.exit("   ⚠️ הבריכה ריקה — ייתכן שהבוטים עדיין עולים")
if "speed" not in bots[0]:
    sys.exit("   ❌ השדה speed לא חזר — קוד ישן עדיין רץ")
named = sum(1 for b in bots if b.get("who"))
print("   בוטים: " + str(len(bots)) + ",  עם @: " + str(named))
for b in bots[:5]:
    sp = b.get("speed")
    print("     " + str(b.get("who") or "— אין @ —") + "  " +
          (str(sp) + " MB/s" if sp is not None else "טרם נמדד"))' \
  || die "האימות נכשל (סיסמה שגויה?).  לשחזור: sudo bash $0 --rollback"

cat <<EOF

────────────────────────────────────────────────────────────
✅ נפרס.

רענן את הפאנל עם Ctrl+Shift+R (עוקף מטמון), ובכרטיס הבריכה
כל בוט יציג עכשיו:

  🤖 @שם_הבוט            [פעיל]
     bot_0 · מזהה 123456789 · 0.25 MB/s · …fJU_Ck

  · ה-@ והמזהה נבחרים בלחיצה אחת — נוח להעתקה
  · מהירות בכתום = מתחת ל-0.6 MB/s, לא מחזיק אפילו צופה אחד
  · "לא מזהה ערוץ" באדום = הבוט חסר תועלת גם אם הוא "פעיל"

עכשיו אפשר להצליב מול רשימת האדמינים בערוץ ולהסיר את מי
שאין לך טוקן עבורו.

לשחזור:  sudo bash /tmp/deploy_pool_panel.sh --rollback
EOF
