#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · תקרה למילויי רקע מקבילים — התיקון לתקיעות שאחרי 21:00.
#
# הרקע המלא ב-patch_edge_cap.py. בקצרה: _edge_fill נוצר ב-create_task בלי
# שום תקרה, ולכן כל צופה שפתח קובץ שאינו במטמון התחיל משיכת רקע של 6MB.
# בשעת שיא עשרות כאלה מתחרים על אותם חיבורים, השהיית הבקשות גדלה, והקצב
# לצופה יורד מתחת לקצב הווידאו.
#
# ## למה זה בטוח גם בלי למדוד קודם
#
# הגבלת עבודת רקע יכולה רק להוריד תחרות על החיבורים, לא להוסיף. אף אחד
# לא ממתין למילוי רקע — צופה כן. הגרוע ביותר שיכול לקרות הוא שהמטמון
# יתמלא לאט יותר בשעת שיא, וזה ממילא מה שהמחמם עושה בשעות השקטות.
#
# ## המדידה מגיעה בחינם
#
# /debug/caches חושף עכשיו edge_fill_dropped. אם הוא גדל בשעת שיא, זו
# הוכחה שהמילויים באמת התחרו עם הצופים. אם הוא נשאר 0 — הסיבה אחרת,
# ונחפש במקום אחר במקום לנחש.
#
#   sudo bash deploy_edge_cap.sh
#   sudo bash deploy_edge_cap.sh --rollback
#   EDGE_FILL_MAX=2 sudo bash deploy_edge_cap.sh   # תקרה הדוקה יותר
# ─────────────────────────────────────────────────────────────────────────────
set -u

SVC=zovex-bot
DIR=/opt/zovex-bot
LIVE="$DIR/main.py"
ENVF="$DIR/.env"
PY="$DIR/venv/bin/python"
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/patch_edge_cap.py"
API="http://127.0.0.1:8000"

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
curl -fsSL "$RAW" -o /tmp/patch_edge_cap.py || die "הורדת הטלאי נכשלה"

if [ "${1:-}" = "--rollback" ]; then
  "$PY" /tmp/patch_edge_cap.py "$LIVE" --revert || die "השחזור נכשל"
  sed -i '/^EDGE_FILL_MAX=/d' "$ENVF" 2>/dev/null || true
  systemctl restart "$SVC" || die "restart נכשל"
  wait_up && echo "✅ שוחזר" || echo "⚠️  שוחזר, אבל /ping לא ענה"
  exit 0
fi

echo "① מחיל (התאמה מדויקת, או סירוב בלי לגעת)"
"$PY" /tmp/patch_edge_cap.py "$LIVE" || die "לא הוחל — הקובץ לא שונה."

# ב-.env ולא ב-drop-in של systemd: EnvironmentFile דורס את Environment
# ללא קשר לסדר הטעינה, וזו בדיוק המלכודת שגרמה ל-STREAM_EDGE_HEAD להישאר
# 32MB אחרי ששונה — שעה של חיפוש על לא כלום.
if [ -n "${EDGE_FILL_MAX:-}" ]; then
  echo "② כותב EDGE_FILL_MAX=$EDGE_FILL_MAX ל-.env"
  sed -i '/^EDGE_FILL_MAX=/d' "$ENVF" 2>/dev/null || true
  echo "EDGE_FILL_MAX=$EDGE_FILL_MAX" >> "$ENVF"
else
  echo "② ברירת מחדל (3) — בלי נגיעה ב-.env"
fi

echo "③ מפעיל מחדש (הבוטים עולים בהדרגה — דקות)"
systemctl restart "$SVC" || die "restart נכשל"
wait_up || die "/ping לא ענה.  לשחזור: sudo bash $0 --rollback"

echo
echo "④ מאמת שהתקרה באמת פעילה בתהליך החי"
curl -fsS -m 15 "$API/debug/caches" | "$PY" -c 'import json,sys
d = json.load(sys.stdin)
if "edge_fill_max" not in d:
    sys.exit("   ❌ השדות החדשים לא מופיעים — הקוד הישן עדיין רץ")
print("   תקרה:   " + str(d["edge_fill_max"]))
print("   פעילים: " + str(d["edge_fill_active"]))
print("   נזרקו:  " + str(d["edge_fill_dropped"]))' \
  || die "האימות נכשל.  לשחזור: sudo bash $0 --rollback"

cat <<EOF

────────────────────────────────────────────────────────────
✅ נפרס.

הערב, כשהיה נתקע — פקודה אחת, שתי שניות:

  curl -s $API/debug/caches | grep -o '"edge_fill_dropped":[0-9]*'

  · המספר גדל  → זה היה הגורם. התקיעות אמורות להיעלם.
  · המספר 0    → הסיבה אחרת. שלח לי ונחפש במקום הנכון,
                 בלי לנחש עוד פעם.

לשחזור:  sudo bash /tmp/deploy_edge_cap.sh --rollback
EOF
