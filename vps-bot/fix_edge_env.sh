#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · מקור אמת אחד לגודל אזורי מטמון הקצה, ובערך הנכון.
#
# ## מה התגלה
#
# שלושה מקומות הגדירו את STREAM_EDGE_HEAD, עם שלושה ערכים שונים:
#
#   /opt/zovex-bot/.env שורה 19        33554432  (32MB)  ← זה שניצח
#   drop-ins/override.conf              2097152  (2MB)
#   drop-ins/zovex-edge.conf            6291456  (6MB)
#
# הסיבה ש-.env ניצח אינה סדר הטעינה אלא כלל של systemd: EnvironmentFile=
# דורס את Environment=, תמיד. לכן אפשר לכתוב drop-in, לראות אותו ב-
# systemctl cat, ושהוא לא ישפיע בכלל — וזה בדיוק מה שקרה.
#
# ## למה 6MB
#
# נמדד על 29 פריטים פרושים על הקטלוג (moov_probe.py):
#
#   חציון moov 1.38MB · אחוזון 90 3.46MB · מקסימום 5.46MB
#   moov בהתחלה (faststart): 21/29
#
# 6MB מכסים את ה-moov הגדול ביותר שנמדד, בשני המקרים. 32MB הם פי שש
# מהצורך: כל פריט שחומם משך 32MB ראש ועוד 12MB זנב, 44MB במקום 6 עד 12.
# זה גם זמן ההתנעה שהצופה מרגיש, גם העומס על הבוטים שנחנקים, וגם כמה
# פריטים נכנסים לתקציב הדיסק.
#
# ## מה הסקריפט עושה
#
#   1. מגבה את .env, ומגדיר בו את שני הערכים ל-6MB
#   2. מוחק את zovex-edge.conf — מקור כפול מיותר אחרי התיקון
#   3. מפעיל מחדש, ומאמת מהתהליך *החי* שהערכים נקלטו
#   4. רק אם אומתו: מפנה את קבצי המטמון בגודל הישן
#
# כל כשל מחזיר את .env מהגיבוי ואינו נוגע במטמון.
#
#   sudo bash fix_edge_env.sh
#   sudo bash fix_edge_env.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

SVC=zovex-bot
DIR=/opt/zovex-bot
ENVF="$DIR/.env"
CACHE="$DIR/data/edge_cache"
DROPIN=/etc/systemd/system/${SVC}.service.d/zovex-edge.conf
SIZE=6291456
TS=$(date +%Y%m%d-%H%M%S)
BAK="${ENVF}.bak_${TS}"

die() { echo "❌ $*" >&2; exit 1; }

wait_up() {
  for _ in $(seq 1 80); do
    curl -fsS -m 3 http://127.0.0.1:8000/ping >/dev/null 2>&1 && return 0
    sleep 3
  done
  return 1
}

live_env() {
  local pid
  pid=$(systemctl show -p MainPID --value "$SVC")
  [ -n "$pid" ] && [ "$pid" != "0" ] || return 1
  tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null
}

if [ "${1:-}" = "--rollback" ]; then
  LAST=$(ls -1t "${ENVF}".bak_* 2>/dev/null | head -1)
  [ -n "$LAST" ] || die "אין גיבוי של .env"
  cp "$LAST" "$ENVF" || die "השחזור נכשל"
  systemctl daemon-reload
  systemctl restart "$SVC" || die "restart נכשל"
  wait_up && echo "✅ שוחזר מ-$LAST" || echo "⚠️  שוחזר, אבל /ping לא ענה"
  exit 0
fi

[ -f "$ENVF" ] || die "$ENVF לא קיים"
pkill -f warm_tails.py 2>/dev/null && echo "עצרתי מחמם שרץ"

echo "① מגבה ל-$BAK"
cp "$ENVF" "$BAK" || die "הגיבוי נכשל"

echo "② מגדיר ב-.env"
# מחליפים אם קיים, מוסיפים אם לא. שתי הפעולות בקובץ אחד, כדי שלא תיווצר
# שוב מציאות של כמה מקורות לאותו ערך.
for k in STREAM_EDGE_HEAD STREAM_EDGE_TAIL; do
  if grep -q "^${k}=" "$ENVF"; then
    sed -i "s|^${k}=.*|${k}=${SIZE}|" "$ENVF"
  else
    printf '%s=%s\n' "$k" "$SIZE" >> "$ENVF"
  fi
  grep -q "^${k}=${SIZE}$" "$ENVF" \
    || { cp "$BAK" "$ENVF"; die "העריכה של $k לא נתפסה — שוחזר"; }
done
grep -n "^STREAM_EDGE_" "$ENVF" | sed 's/^/   /'

echo "③ מסיר את ה-drop-in הכפול"
rm -f "$DROPIN"
systemctl daemon-reload || die "daemon-reload נכשל"

echo "④ מפעיל מחדש (הבוטים עולים בהדרגה — דקות)"
systemctl restart "$SVC" || { cp "$BAK" "$ENVF"; systemctl restart "$SVC"
                              die "restart נכשל — שוחזר"; }
wait_up || { cp "$BAK" "$ENVF"; systemctl restart "$SVC"
             die "/ping לא ענה תוך 4 דקות — שוחזר.  journalctl -u $SVC -n 80"; }

echo "⑤ מאמת מהתהליך החי"
GOT=$(live_env | grep -c "^STREAM_EDGE_\(HEAD\|TAIL\)=$SIZE$")
if [ "$GOT" != "2" ]; then
  live_env | grep "^STREAM_EDGE_" || echo "   (אין STREAM_EDGE_* בכלל)"
  cp "$BAK" "$ENVF"; systemctl restart "$SVC"
  die "לא נקלט — שוחזר, והמטמון לא נגע. שלח לי את הפלט."
fi
echo "   ✓ ראש וזנב = $((SIZE / 1024 / 1024))MB"

echo "⑥ מפנה קבצי מטמון בגודל הישן"
BEFORE=$(du -sh "$CACHE" 2>/dev/null | cut -f1)
# רק קבצים שאינם בגודל הנוכחי. השרת בודק התאמת גודל מדויקת ולכן לא יקרא
# אותם לעולם; מה שכבר בגודל הנכון נשאר ולא מחומם מחדש.
find "$CACHE" -maxdepth 1 -type f \( -name '*.head' -o -name '*.tail' \) \
     ! -size "${SIZE}c" -delete 2>/dev/null
echo "   היה $BEFORE, עכשיו $(du -sh "$CACHE" 2>/dev/null | cut -f1)"

echo "⑦ מחמם 20 פריטים לדוגמה"
echo
cd "$DIR" && STREAM_EDGE_HEAD=$SIZE STREAM_EDGE_TAIL=$SIZE \
  WARM_LIMIT=20 python3 -u warm_tails.py

cat <<EOF

────────────────────────────────────────────────────────────
להריץ על כל הקטלוג ברקע:
  cd $DIR && STREAM_EDGE_HEAD=$SIZE STREAM_EDGE_TAIL=$SIZE \\
    nohup python3 -u warm_tails.py > /var/log/zovex-warm.log 2>&1 &

לעקוב:    tail -f /var/log/zovex-warm.log
לעצור:    pkill -f warm_tails.py
לבטל הכל: sudo bash $0 --rollback
EOF
