#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · מתקן את שדה "קישור לעדכון" בפאנל, ומאמת שהעדכון באמת יעדכן.
#
# הרקע המלא ב-patch_apk_source.py. בקצרה: השדה נדרס בכל טעינה של הפאנל,
# ובכל מקרה אף אחד לא קרא אותו — ה-APK נמשך ממשתנה סביבה. אחרי התיקון
# השדה הוא מקור האמת, ושמירה בו מפעילה הורדה מחדש.
#
# ## האימות הוא העיקר כאן
#
# "לשחרר עדכון שלא באמת מעדכן" הוא התרחיש הגרוע: חוסמים 100% מהמשתמשים
# ואז מגישים להם את ה-APK הישן. לכן הסקריפט לא מסתפק ב"נפרס בהצלחה" אלא
# משווה את הקובץ שהשרת מגיש לקובץ שפורסם בגיטהאב — לפי גודל מדויק.
#
#   sudo bash deploy_apk_source.sh
#   sudo bash deploy_apk_source.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

SVC=zovex-bot
DIR=/opt/zovex-bot
LIVE="$DIR/main.py"
PANEL="$DIR/admin.html"
PY="$DIR/venv/bin/python"
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot"
BASE="https://zovex.duckdns.org"
GH_APK="https://github.com/davidggjg/zovex-android/releases/latest/download/zovex.apk"

die() { echo "❌ $*" >&2; exit 1; }
wait_up() {
  for _ in $(seq 1 80); do
    curl -fsS -m 3 http://127.0.0.1:8000/ping >/dev/null 2>&1 && return 0
    sleep 3
  done
  return 1
}

[ -f "$LIVE" ]  || die "$LIVE לא קיים"
[ -f "$PANEL" ] || die "$PANEL לא קיים"
[ -x "$PY" ]    || PY=python3

curl -fsSL "$RAW/patch_apk_source.py" -o /tmp/patch_apk_source.py || die "הורדה נכשלה"
curl -fsSL "$RAW/patch_apk_panel.py"  -o /tmp/patch_apk_panel.py  || die "הורדה נכשלה"

if [ "${1:-}" = "--rollback" ]; then
  "$PY" /tmp/patch_apk_source.py "$LIVE" --revert || die "שחזור main.py נכשל"
  [ -f "$PANEL.before_apksrc" ] && cp "$PANEL.before_apksrc" "$PANEL"
  systemctl restart "$SVC" || die "restart נכשל"
  wait_up && echo "✅ שוחזר" || echo "⚠️  שוחזר, אבל /ping לא ענה"
  exit 0
fi

echo "① מחיל על main.py"
"$PY" /tmp/patch_apk_source.py "$LIVE" || die "לא הוחל"
echo "② מחיל על admin.html"
"$PY" /tmp/patch_apk_panel.py "$PANEL" || die "לא הוחל"

echo "③ מפעיל מחדש (הבוטים עולים בהדרגה — דקות)"
systemctl restart "$SVC" || die "restart נכשל"
wait_up || die "/ping לא ענה.  לשחזור: sudo bash $0 --rollback"

echo
echo "④ בודק שהשדה כבר לא נדרס"
# בלי f-strings: גרסאות פייתון עד 3.11 אוסרות קו נטוי בתוך ביטוי
# של f-string, וזה מה שהפיל את השלב הזה בריצה הראשונה.
curl -fsS -m 15 "$BASE/app/version" \
  | "$PY" -c 'import json,sys
v = json.load(sys.stdin)
print("   latest=" + str(v.get("latest")) + "  min=" + str(v.get("min")))
print("   מקור ההורדה (source_url): " + (v.get("source_url") or "(ריק — ברירת מחדל)"))
print("   מה שהאפליקציה מקבלת (url): " + str(v.get("url")))' \
  || echo "   ⚠️ לא הצלחתי לקרוא /app/version"

echo
echo "⑤ אימות שהקובץ שהשרת מגיש הוא זה שפורסם"
read -r -s -p "   סיסמת הפאנל (לא מוצגת): " PASS; echo
echo "   מרענן את המטמון..."
curl -fsS -m 30 -X POST "$BASE/app/apk/refresh" \
  -H 'Content-Type: application/json' -d "{\"password\":\"$PASS\"}" >/dev/null \
  || die "רענון נכשל — סיסמה שגויה?"

echo "   ממתין להורדה"
for i in $(seq 1 30); do
  sleep 5
  SZ=$(curl -fsS -m 15 -X POST "$BASE/app/apk/status" \
       -H 'Content-Type: application/json' -d "{\"password\":\"$PASS\"}" \
       | "$PY" -c 'import json,sys;print(json.load(sys.stdin).get("size",0))' 2>/dev/null)
  [ -n "${SZ:-}" ] && [ "$SZ" -gt 1000000 ] 2>/dev/null && break
done

GH_SZ=$(curl -fsSL -o /dev/null -w '%{size_download}' -r 0-0 "$GH_APK" >/dev/null 2>&1; \
        curl -fsSLI "$GH_APK" 2>/dev/null | awk 'BEGIN{IGNORECASE=1}/^content-length:/{v=$2}END{gsub(/\r/,"",v);print v}')

echo
echo "   בשרת:   ${SZ:-?} בתים"
echo "   בגיטהאב: ${GH_SZ:-?} בתים"
if [ -n "${SZ:-}" ] && [ "${SZ:-0}" = "${GH_SZ:-x}" ]; then
  echo "   ✅ זהים — המשתמשים יקבלו בדיוק את מה שפורסם."
else
  echo "   ⚠️  לא זהים. אל תפעיל חסימת עדכון לפני שזה מסתדר:"
  echo "       · פורסמה בנייה ל-latest הציבורי? (publish=true)"
  echo "       · הקישור בפאנל מצביע ישירות ל-APK ולא לדף?"
fi

cat <<'EOF'

────────────────────────────────────────────────────────────
בפאנל, בכרטיס "גרסת אפליקציה":

  קישור לעדכון:
    https://github.com/davidggjg/zovex-android/releases/latest/download/zovex.apk

  שמור — זה גם מפעיל הורדה מחדש ברקע.
  ואז רענן את הדף: הקישור צריך להישאר כפי שכתבת ולא להתחלף.

רק אחרי שסעיף ⑤ הראה "זהים" — למלא גרסה אחרונה ומינימלית.

לשחזור:  sudo bash /tmp/deploy_apk_source.sh --rollback
EOF
