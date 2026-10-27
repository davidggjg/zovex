#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · סורק העשרה: תיאורים, פוסטרים, והצעות קטגוריה.
#
# ממלא **רק שדות ריקים** מ-TMDB. תקציר שקיים ב-TMDB בעברית נלקח כמו שהוא;
# כשיש רק אנגלית — מתורגם דרך Groq. זה הפער שדווח: "יש מלא דברים
# שהתיאורים שלהם באנגלית וזה לא מושך לי אותם".
#
# קטגוריות: הסורק רק **מציע**. נמדד על הקטלוג החי — 23,107 פריטים ב-12
# קטגוריות — ושלוש מהן אינן ז'אנר (מארוול הוא זיכיון, שידורים חיים אינם
# תוכן TMDB, וטורקיות/ישראלים הן לפי מוצא). סיווג לפי ז'אנר היה מרוקן
# אותן לתוך "סרטים". לכן הסורק נוגע רק בקטגוריות הגנריות, ומציע רק
# קטגוריות שכבר קיימות — הוא לא ממציא חדשות.
#
# הוא אינו רץ מעצמו. מפעילים אותו מפורשות.
#
#   sudo bash deploy_enrich.sh
#   sudo bash deploy_enrich.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

SVC=zovex-bot
DIR=/opt/zovex-bot
LIVE="$DIR/main.py"
PY="$DIR/venv/bin/python"
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/patch_enrich.py"
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
curl -fsSL "$RAW" -o /tmp/patch_enrich.py || die "הורדת הטלאי נכשלה"

if [ "${1:-}" = "--rollback" ]; then
  "$PY" /tmp/patch_enrich.py "$LIVE" --revert || die "השחזור נכשל"
  systemctl restart "$SVC" || die "restart נכשל"
  wait_up && echo "✅ שוחזר" || echo "⚠️  שוחזר, אבל /ping לא ענה"
  exit 0
fi

echo "① בודק שהמפתחות קיימים"
grep -q '^TMDB_API_KEY=' "$DIR/.env" && echo "   ✓ TMDB" \
  || echo "   ⚠️  אין TMDB_API_KEY ב-.env — בלעדיו הסורק לא ימשוך כלום"
grep -q '^GROQ_API_KEY=' "$DIR/.env" && echo "   ✓ Groq" \
  || echo "   ⚠️  אין GROQ_API_KEY — תקצירים באנגלית לא יתורגמו"

echo "② מחיל"
"$PY" /tmp/patch_enrich.py "$LIVE" || die "לא הוחל"

echo "③ מפעיל מחדש (הבוטים עולים בהדרגה — דקות)"
systemctl restart "$SVC" || die "restart נכשל"
wait_up || die "/ping לא ענה.  לשחזור: sudo bash $0 --rollback"

echo
echo "④ מאמת"
read -r -s -p "   סיסמת הפאנל (לא מוצגת): " PASS; echo
curl -fsS -m 15 -X POST "$API/panel/enrich/status" \
  -H 'Content-Type: application/json' -d "{\"password\":\"$PASS\"}" \
  | "$PY" -c 'import json,sys
d = json.load(sys.stdin)
print("   TMDB: " + ("יש" if d.get("tmdb") else "חסר") +
      "   Groq: " + ("יש" if d.get("groq") else "חסר") +
      "   רץ: " + ("כן" if d.get("running") else "לא"))' \
  || die "האימות נכשל (סיסמה שגויה?).  לשחזור: sudo bash $0 --rollback"

cat <<EOF

────────────────────────────────────────────────────────────
✅ נפרס. הסורק לא רץ — מפעילים אותו ידנית.

שים את הסיסמה במשתנה פעם אחת:

  read -s -p "סיסמה: " P; echo

להפעלה:
  curl -s -X POST $API/panel/enrich/start \\
    -H 'Content-Type: application/json' -d "{\"password\":\"\$P\"}"

לעקוב (אפשר לחזור על זה מתי שבא לך):
  curl -s -X POST $API/panel/enrich/status \\
    -H 'Content-Type: application/json' -d "{\"password\":\"\$P\"}" \\
    | $PY -m json.tool

לעצור באמצע:
  curl -s -X POST $API/panel/enrich/stop \\
    -H 'Content-Type: application/json' -d "{\"password\":\"\$P\"}"

~3,340 יחידות בקצב של 2 שניות ליחידה — בערך שעתיים.
תיאורים ופוסטרים נכתבים תוך כדי; קטגוריות רק נאספות.

אחרי שמסתיים — לראות את ההצעות:
  curl -s -X POST $API/panel/recat/list \\
    -H 'Content-Type: application/json' -d "{\"password\":\"\$P\"}" \\
    | $PY -m json.tool | head -60

להחיל את כולן:   /panel/recat/apply
לבטל הכול:       /panel/recat/undo

לשחזור הקוד:  sudo bash /tmp/deploy_enrich.sh --rollback
EOF
