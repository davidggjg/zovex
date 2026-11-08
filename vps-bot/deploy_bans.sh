#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · כפתור חסימת המייל בפאנל אינו עובד.
#
# ## מה נמדד
#
#     POST /panel/bans      → 404  {"detail":"Not Found"}   (JSON מהשרת)
#     GET  /api/access      → 404  {"detail":"Not Found"}
#     POST /feedback/read   → 422  (קיים ומנותב)
#
# ה-404 מגיע מה-API עצמו ולא מ-nginx, כלומר הניתוב תקין והנתיבים פשוט
# **אינם קיימים בשרת**: הטלאי add_bans.py מעולם לא הוחל. הפאנל אפילו
# צפה את זה ומציג "צריך להריץ add_bans.py בשרת".
#
# הסקריפט מחיל אותו, ואחריו fix_feedback_bans.py — שבלעדיו מי שנחסם
# ממשיך לכתוב לתיבת התמיכה, וזה בדיוק מה שהחסימה נועדה למנוע.
#
#   sudo bash deploy_bans.sh
#   sudo bash deploy_bans.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u
DIR=/opt/zovex-bot
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
B="https://raw.githubusercontent.com/davidggjg/zovex/${REF}/vps-bot"
T=$(date +%s)
die() { echo "❌ $*" >&2; exit 1; }
[ -f "$DIR/main.py" ] || die "$DIR/main.py לא קיים"

curl -fsSL -H 'Cache-Control: no-cache' "$B/add_bans.py?t=$T" -o /tmp/add_bans.py || die "הורדה נכשלה"
curl -fsSL -H 'Cache-Control: no-cache' "$B/fix_feedback_bans.py?t=$T" -o /tmp/fix_feedback_bans.py || die "הורדה נכשלה"

if [ "${1:-}" = "--rollback" ]; then
  python3 /tmp/fix_feedback_bans.py --undo 2>/dev/null
  python3 /tmp/add_bans.py --undo || die "השחזור נכשל"
  systemctl restart zovex-bot
  echo "✅ שוחזר"
  exit 0
fi

echo "① בודק מה המצב היום"
CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 20 "http://127.0.0.1:8000/api/access?email=t@t.com")
echo "   /api/access → $CODE"
if [ "$CODE" = "200" ]; then
  echo "✅ הנתיב כבר קיים — add_bans הוחל בעבר. לא נוגעים ב-main.py."
else
  echo "② מחיל add_bans.py"
  python3 /tmp/add_bans.py || die "add_bans נכשל"
  echo "③ מחיל fix_feedback_bans.py (חוסם כתיבה לתמיכה למי שנחסם)"
  python3 /tmp/fix_feedback_bans.py || echo "   ⚠️ לא הוחל — החסימה תעבוד, אבל נחסם עדיין יוכל לכתוב לתמיכה"
  echo "④ מפעיל מחדש"
  systemctl restart zovex-bot || die "ההפעלה מחדש נכשלה"
  sleep 8
  systemctl is-active --quiet zovex-bot || { journalctl -u zovex-bot -n 30 --no-pager; die "השרת אינו פעיל"; }
fi

echo "⑤ בדיקה"
printf '   GET  /api/access  → '
curl -s -m 20 "http://127.0.0.1:8000/api/access?email=test@test.com"; echo
printf '   POST /panel/bans  → '
curl -s -o /tmp/pb.txt -w '%{http_code}' -m 20 -X POST -H 'Content-Type: application/json' \
  -d '{"password":"__wrong__","action":"list"}' "http://127.0.0.1:8000/panel/bans"
echo "  $(head -c 90 /tmp/pb.txt)"
echo
echo "   403 עם סיסמה שגויה הוא התשובה הנכונה: הנתיב קיים ומוגן."
echo "   404 פירושו שהטלאי עדיין לא נכנס."
echo
echo "✅ נסה עכשיו את כפתור החסימה בפאנל."
echo "   לחזרה:  sudo bash $0 --rollback"
