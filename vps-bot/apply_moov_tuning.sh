#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · מכוונן את מטמון הקצה לפי מה שנמדד, ומריץ את המחמם המתוקן.
#
# ## מה נמדד (moov_probe.py, 29 פריטים פרושים על הקטלוג)
#
#   חציון moov 1.38MB · אחוזון 90 3.46MB · מקסימום 5.46MB
#   moov בסוף הקובץ: 8/29 בלבד — ב-72% הוא בהתחלה (faststart)
#
# ## שתי מסקנות
#
# 1. הזנב הוא 12MB, וה-moov הגדול ביותר שנמדד הוא 5.46MB. 6MB מכסים כל
#    מה שנמדד, בחצי מהמשיכה.
#
# 2. הראש הוא 2MB, אבל ב-72% מהקטלוג ה-moov יושב בהתחלה ומגיע ל-5.46MB.
#    כלומר הטמנו עד היום רק *חלק* מטבלת האינדקס, והשאר נמשך קר בכל
#    הפעלה — גם בפריט ש"חומם". זה באג ולא רק בזבוז, והוא מסביר למה
#    החימום לא נתן את מה שציפינו. 6MB סוגרים אותו.
#
# ## למה drop-in ולא עריכת הקובץ הקיים
#
# systemd מחיל תיקיית drop-in אחרי יחידת השירות, ולכן ההגדרות כאן גוברות
# בלי לגעת בתצורה הקיימת. ביטול = מחיקת קובץ אחד.
#
# ## מה הסקריפט עושה
#
#   1. כותב את שתי ההגדרות כ-drop-in
#   2. מפעיל מחדש ומחכה שהשירות יענה
#   3. מפנה את מטמון הקצה (הקבצים הישנים בגודל אחר — השרת לא יקרא אותם)
#   4. מריץ את המחמם המתוקן על 20 פריטים, כדי שתראה את ההפרש
#
#   sudo bash apply_moov_tuning.sh
#   sudo bash apply_moov_tuning.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

SVC=zovex-bot
DIR=/opt/zovex-bot
CACHE="$DIR/data/edge_cache"
DROPIN_DIR="/etc/systemd/system/${SVC}.service.d"
DROPIN="$DROPIN_DIR/zovex-edge.conf"
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/warm_tails.py"
SIZE=6291456          # 6MB — מכסה את ה-moov הגדול ביותר שנמדד (5.46MB)

die() { echo "❌ $*" >&2; exit 1; }

wait_up() {
  for _ in $(seq 1 80); do
    curl -fsS -m 3 http://127.0.0.1:8000/ping >/dev/null 2>&1 && return 0
    sleep 3
  done
  return 1
}

if [ "${1:-}" = "--rollback" ]; then
  rm -f "$DROPIN"
  systemctl daemon-reload
  systemctl restart "$SVC" || die "restart נכשל"
  rm -f "$CACHE"/*.head "$CACHE"/*.tail 2>/dev/null
  wait_up && echo "✅ בוטל. הערכים חזרו לברירת המחדל (ראש 2MB, זנב 12MB)." \
          || echo "⚠️  בוטל, אבל /ping לא ענה. journalctl -u $SVC -n 50"
  exit 0
fi

[ -d "$DIR" ] || die "$DIR לא קיים — זה לא השרת הנכון"
pkill -f warm_tails.py 2>/dev/null && echo "עצרתי מחמם שרץ"

echo "① כותב את ההגדרות"
mkdir -p "$DROPIN_DIR" || die "לא נוצרה תיקיית drop-in"
cat >"$DROPIN" <<EOF
# נכתב ע"י apply_moov_tuning.sh — ראה את ההסבר שם.
# ה-moov הגדול ביותר שנמדד בקטלוג הוא 5.46MB; 6MB מכסים כל מקרה.
[Service]
Environment=STREAM_EDGE_HEAD=$SIZE
Environment=STREAM_EDGE_TAIL=$SIZE
EOF
systemctl daemon-reload || die "daemon-reload נכשל"

echo "② מפעיל מחדש (הבוטים עולים בהדרגה — זה לוקח דקות)"
systemctl restart "$SVC" || { rm -f "$DROPIN"; systemctl daemon-reload
                              systemctl restart "$SVC"; die "restart נכשל — בוטל"; }
wait_up || { rm -f "$DROPIN"; systemctl daemon-reload; systemctl restart "$SVC"
             die "/ping לא ענה תוך 4 דקות — בוטל.  journalctl -u $SVC -n 80"; }

echo "③ מפנה את המטמון הישן"
# הקבצים הישנים הם 2MB ו-12MB. השרת בודק התאמת גודל מדויקת ולכן לא
# יקרא אותם יותר — הם רק תופסים מקום עד שהפינוי יגיע אליהם.
BEFORE=$(du -sh "$CACHE" 2>/dev/null | cut -f1)
rm -f "$CACHE"/*.head "$CACHE"/*.tail 2>/dev/null
echo "   היה $BEFORE, עכשיו $(du -sh "$CACHE" 2>/dev/null | cut -f1)"

echo "④ מוריד את המחמם המתוקן"
curl -fsSL "$RAW" -o "$DIR/warm_tails.py" || die "ההורדה נכשלה"

echo "⑤ מחמם 20 פריטים, כדי שתראה את ההפרש"
echo
cd "$DIR" && WARM_LIMIT=20 python3 -u warm_tails.py

cat <<'EOF'

────────────────────────────────────────────────────────────
בסיכום למעלה יש שתי שורות חדשות: גודל ה-moov הממוצע, וכמה משיכה
נחסכה בזנבות שאיש לא היה קורא.

להריץ על כל הקטלוג ברקע:
  cd /opt/zovex-bot && nohup python3 -u warm_tails.py > /var/log/zovex-warm.log 2>&1 &

לעקוב:   tail -f /var/log/zovex-warm.log
לעצור:   pkill -f warm_tails.py
לבטל הכל: sudo bash apply_moov_tuning.sh --rollback
EOF
