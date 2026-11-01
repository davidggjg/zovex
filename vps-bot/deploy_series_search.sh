#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · חיפוש בבורר הסדרות בפאנל.
#
# בהוספת פרק צריך לבחור סדרה מרשימה נגללת של 348 סדרות (נמדד בקטלוג).
# מציאת אחת בתוכה היא גלילה ארוכה, ובטלפון גרועה במיוחד.
#
# הבורר נשאר אותו <select id="f_existing"> ולא הוחלף ברכיב אחר, ולכן
# pickExisting(), refreshDerived() וכל מי שקורא .value ממשיכים לעבוד
# בדיוק כמו קודם — רק רשימת האפשרויות מסוננת.
#
# שינוי ב-admin.html בלבד: אין נגיעה בקוד השרת ואין restart.
#
#   sudo bash deploy_series_search.sh
#   sudo bash deploy_series_search.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

DIR=/opt/zovex-bot
PANEL="$DIR/admin.html"
PY="$DIR/venv/bin/python"
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/patch_series_search.py"

die() { echo "❌ $*" >&2; exit 1; }

[ -f "$PANEL" ] || die "$PANEL לא קיים — זה לא שרת ZOVEX"
[ -x "$PY" ]    || PY=python3
curl -fsSL "$RAW" -o /tmp/patch_series_search.py || die "הורדת הטלאי נכשלה"

if [ "${1:-}" = "--rollback" ]; then
  "$PY" /tmp/patch_series_search.py "$PANEL" --revert || die "השחזור נכשל"
  echo "✅ שוחזר — רענן עם Ctrl+Shift+R"
  exit 0
fi

echo "① מסיר גרסה קודמת אם קיימת"
"$PY" /tmp/patch_series_search.py "$PANEL" --revert >/dev/null 2>&1 \
  && echo "   הוסרה" || echo "   אין קודמת — ממשיך"

echo "② מחיל"
"$PY" /tmp/patch_series_search.py "$PANEL" || die "לא הוחל"

cat <<EOF

────────────────────────────────────────────────────────────
✅ נפרס. אין restart — רק רענן עם Ctrl+Shift+R.

ב"הוספה" → "פרק בסדרה" יש עכשיו תיבת חיפוש מעל בורר הסדרות:

  🔎 חפש סדרה…
  [— סדרה חדשה — ▾]
  3 מתוך 348 סדרות

הסינון חי תוך כדי הקלדה, והמונה מראה כמה נשארו.

הסדרה שכבר בחרת נשארת ברשימה גם כשהיא לא תואמת לחיפוש —
אחרת הקלדה אחרי בחירה הייתה מאפסת לך את הטופס.

לשחזור:  sudo bash /tmp/deploy_series_search.sh --rollback
EOF
