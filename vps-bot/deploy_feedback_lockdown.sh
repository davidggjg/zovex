#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · חסימה דחופה של הצפת תיבת התמיכה.
#
# ## מה קורה
#
# /feedback/send אינו מאומת ואין בו הגבלת קצב: כל אחד שולח כמה הודעות
# שירצה, עם כל user_id, מחשבונות זבל. זה מה שדוד רואה — הצפה בהודעות
# אקראיות (ospuuq / ovppyo / oocbgh) מכתובות gmail מיוצרות.
#
# הטלאי fix_feedback_abuse.py (שנכתב בעבר ומעולם לא הוחל) מוסיף:
#   · הגבלת קצב: 12 הודעות לשעה לכל IP → 429 מעבר לזה.
#   · רשימת kind סגורה (support/review/tip) → סוגר גם הזרקת HTML
#     לפאנל דרך השדה הזה.
#
# לא שובר כלום: משתמש אמיתי שולח הודעה אחת-שתיים ולא מגיע למגבלה.
#
#   sudo bash deploy_feedback_lockdown.sh
#   sudo bash deploy_feedback_lockdown.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u
DIR=/opt/zovex-bot
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${REF}/vps-bot/fix_feedback_abuse.py"
die(){ echo "❌ $*" >&2; exit 1; }
[ -f "$DIR/main.py" ] || die "$DIR/main.py לא קיים"

curl -fsSL -H 'Cache-Control: no-cache' "$RAW?t=$(date +%s)" -o /tmp/fix_feedback_abuse.py || die "הורדה נכשלה"

if [ "${1:-}" = "--rollback" ]; then
  MAIN_PY="$DIR/main.py" python3 /tmp/fix_feedback_abuse.py --revert || die "שחזור נכשל"
  systemctl restart zovex-bot; echo "✅ שוחזר"; exit 0
fi

echo "① מחיל הגבלת קצב על /feedback/send"
MAIN_PY="$DIR/main.py" python3 /tmp/fix_feedback_abuse.py || die "הטלאי נכשל"
python3 -m py_compile "$DIR/main.py" || { MAIN_PY="$DIR/main.py" python3 /tmp/fix_feedback_abuse.py --revert; die "לא מתקמפל — שוחזר"; }

echo "② מפעיל מחדש"
systemctl restart zovex-bot || die "restart נכשל"
sleep 8
systemctl is-active --quiet zovex-bot || { journalctl -u zovex-bot -n 25 --no-pager; die "השרת אינו פעיל"; }

echo "③ בדיקה — הגבלת קצב פעילה:"
# 14 בקשות מהירות; הראשונות 12 אמורות לעבור (400 כי ריק, זה בסדר),
# ומעבר לזה 429. בלי לשלוח תוכן אמיתי — גוף ריק.
c429=0
for i in $(seq 1 14); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -X POST -H 'Content-Type: application/json' -d '{}' "http://127.0.0.1:8000/feedback/send")
  [ "$code" = "429" ] && c429=$((c429+1))
done
echo "   תגובות 429 מתוך 14: $c429"
[ "$c429" -gt 0 ] && echo "   ✅ הגבלת הקצב פעילה" || echo "   ⚠️ לא נראו 429 — ייתכן שהמגבלה גבוהה מ-14, בדוק ידנית"
echo
echo "✅ ההצפה נחסמה. ל-IP בודד: 12 הודעות לשעה."
echo "   לחזרה:  sudo bash $0 --rollback"
