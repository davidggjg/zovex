#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · פורס את תיקון ההשהיה הגלובלית.
#
# הרקע המלא מתועד ב-patch_stagger.py. בקצרה: השורה הראשונה של המטפל בכל
# בקשת ‎/stream/‎ החזיקה מנעול גלובלי והמתינה שתי שניות מאז הבקשה הקודמת —
# גם כשהתשובה הייתה מגיעה מהמטמון בלי לגעת בטלגרם. השרת כולו הוגבל לחצי
# בקשה בשנייה.
#
# הסקריפט גם מסיר את ‎STREAM_START_STAGGER=0‎ הזמני, אם הוגדר ב-
# systemctl set-environment לצורך הניסוי. אחרי התיקון הערך הנכון אינו 0:
# ההשהיה עדיין נחוצה על פתיחת זרם אמיתי, והברירה היא 0.3.
#
#   sudo bash deploy_stagger.sh
#   sudo bash deploy_stagger.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

SVC=zovex-bot
DIR=/opt/zovex-bot
LIVE="$DIR/main.py"
PY="$DIR/venv/bin/python"
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/patch_stagger.py"
PATCHER=/tmp/patch_stagger.py

die() { echo "❌ $*" >&2; exit 1; }

wait_up() {
  for _ in $(seq 1 80); do
    curl -fsS -m 3 http://127.0.0.1:8000/ping >/dev/null 2>&1 && return 0
    sleep 3
  done
  return 1
}

[ -f "$LIVE" ] || die "$LIVE לא קיים"
[ -x "$PY" ]   || PY=python3

curl -fsSL "$RAW" -o "$PATCHER" || die "הורדת הטלאי נכשלה"

if [ "${1:-}" = "--rollback" ]; then
  "$PY" "$PATCHER" "$LIVE" --revert || die "השחזור נכשל"
  systemctl restart "$SVC" || die "restart נכשל"
  wait_up && echo "✅ שוחזר" || echo "⚠️  שוחזר, אבל /ping לא ענה"
  exit 0
fi

echo "① מחיל את הטלאי (התאמה מדויקת, או סירוב בלי לגעת)"
"$PY" "$PATCHER" "$LIVE" || die "לא הוחל — הקובץ לא שונה."

echo "② מסיר את ההגדרה הזמנית מהניסוי"
# הניסוי הגדיר 0 כדי לבטל לגמרי. אחרי התיקון זה לא הערך הנכון: ההשהיה
# עדיין נחוצה על פתיחת זרם אמיתי, ושם 0.3 הוא הברירה.
systemctl unset-environment STREAM_START_STAGGER 2>/dev/null || true

echo "③ מפעיל מחדש (הבוטים עולים בהדרגה — דקות)"
systemctl restart "$SVC" || die "restart נכשל"
wait_up || die "/ping לא ענה תוך 4 דקות.
   לשחזור:  sudo bash $0 --rollback"

echo "④ מודד — ארבע בקשות טווח רצופות"
echo
"$PY" - <<'PY'
import re, time, urllib.request
B = "http://127.0.0.1:8000"
b = urllib.request.urlopen(B + "/content/lite", timeout=300).read().decode("utf-8", "replace")
seen, it = set(), []
for c, m, q in re.findall(r"/stream/(-?\d+)/(\d+)(\?[^\"'\s<>\\]*)?", b):
    if (c, m) in seen:
        continue
    seen.add((c, m))
    it.append((c, m, q or ""))
c, m, q = it[len(it) // 2]
print(f"   פריט: {c}/{m}\n")
for i in range(4):
    r = urllib.request.Request(f"{B}/stream/{c}/{m}{q}")
    r.add_header("Range", f"bytes={i * 1048576}-{(i + 1) * 1048576 - 1}")
    t = time.time()
    try:
        with urllib.request.urlopen(r, timeout=120) as z:
            n = len(z.read())
        d = max(time.time() - t, 1e-6)
        print(f"   מגה {i + 1}: {d:5.2f}s  ({n / 1024 / d:8.0f} KB/s)")
    except Exception as e:
        print(f"   מגה {i + 1}: נכשל {type(e).__name__}")
PY

cat <<'EOF'

────────────────────────────────────────────────────────────
✅ נפרס.

  ההשהיה עברה מראש המטפל אל נקודת פתיחת הזרם — אחרי בדיקת
  המטמון. בקשה שנענית מהמטמון כבר לא ממתינה כלל.
  ברירת המחדל: 2.0 → 0.3 שניות.

אם מגה כלשהו חזר ב-0.00 שניות — זה המטמון מגיש מיידית, וזה
בדיוק מה שהיה חסום עד עכשיו.

לכוונון בלי פריסה מחדש (לא שורד אתחול):
  systemctl set-environment STREAM_START_STAGGER=0.15
  systemctl restart zovex-bot

לשחזור:  sudo bash /tmp/deploy_stagger.sh --rollback
EOF
