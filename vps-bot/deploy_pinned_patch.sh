#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# מחיל את תיקוני ההזרמה על /opt/zovex-bot/main.py — כטלאי, לא כהחלפת קובץ.
#
# 11 hunks, בנויים מול השושלת הנכונה (claude/hls-relay-schema-port, 11,243
# שורות) — אותה שושלת שרצה על השרת. כל השאר בקובץ החי נשאר כפי שהוא.
#
# בטוח: בדיקת שושלת -> גיבוי -> dry-run -> החלה -> קומפילציה -> restart ->
# בדיקת בריאות, ושחזור אוטומטי בכל כשל. אם hunk אחד לא מתאים — לא מוחל כלום.
#
# הרצה:  sudo bash deploy_pinned_patch.sh
# חזרה:  sudo bash deploy_pinned_patch.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
PATCH_URL="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/pinned_stream.patch"
DIR=/opt/zovex-bot
LIVE="$DIR/main.py"
PY="$DIR/venv/bin/python"
SVC=zovex-bot
PORT="${PORT:-8000}"
MIN_LINES=10000          # השושלת הנכונה היא ~11,600 שורות
TS=$(date +%Y%m%d-%H%M%S)
BAK="$DIR/main_before_pinned_${TS}.py"
PATCHFILE="/tmp/pinned_stream_${TS}.patch"

die() { echo "❌ $*" >&2; exit 1; }
restore() { cp "$BAK" "$LIVE" 2>/dev/null && systemctl restart "$SVC" 2>/dev/null; }

# ── שחזור: בוחר את הגיבוי הנקי החדש ביותר, לא סתם את החדש ביותר ─────────────
# גיבוי שנלקח מקובץ שכבר הוחלף אינו גיבוי. הלולאה מדלגת על כאלה.
if [ "${1:-}" = "--rollback" ]; then
  ORIG=""
  for f in $(ls -1t "$DIR"/main_before_*.py 2>/dev/null); do
    grep -q "_pinned_stream" "$f" || { ORIG="$f"; break; }
  done
  [ -n "$ORIG" ] || die "לא נמצא גיבוי נקי ב-$DIR — עצור ואל תמשיך לבד"
  echo "משחזר מ-$ORIG"
  cp "$ORIG" "$LIVE" || die "השחזור נכשל"
  systemctl restart "$SVC" || die "restart נכשל"
  echo "✅ שוחזר ($(wc -l < "$LIVE") שורות). בדוק את הפאנל."
  exit 0
fi

[ -d "$DIR" ]  || die "$DIR לא קיים — זה לא שרת ה-zovex?"
[ -x "$PY" ]   || die "$PY לא קיים — ה-venv חסר"
[ -f "$LIVE" ] || die "$LIVE לא קיים"
command -v patch >/dev/null || die "הפקודה patch חסרה:  apt-get install -y patch"

# ── כבר מוחל? (OR, כדי לתפוס גם החלה חלקית) ─────────────────────────────────
if grep -q "_pinned_stream" "$LIVE" || grep -q "def stream_meta" "$LIVE"; then
  die "ב-$LIVE כבר יש חלק מהשינויים — לא מחיל שוב.
   אם זו הגרסה השבורה הקודמת, שחזר קודם:  sudo bash $0 --rollback"
fi

# ── בדיקת שושלת: שלא נחיל על הקובץ הלא-נכון ─────────────────────────────────
LINES=$(wc -l < "$LIVE")
if [ "$LINES" -lt "$MIN_LINES" ]; then
  die "ב-$LIVE יש רק $LINES שורות — פחות מ-$MIN_LINES.
   זו כנראה הגרסה השגויה מהריפו ולא הקוד האמיתי שלך.
   שחזר קודם:  sudo bash $0 --rollback"
fi
grep -q "_media_bands_fetch" "$LIVE" || die "$LIVE לא נראה כמו שרת ההזרמה — עוצר"

echo "① מוריד את הטלאי"
curl -fsSL "$PATCH_URL" -o "$PATCHFILE" || die "הורדת הטלאי נכשלה"
grep -q "^@@" "$PATCHFILE" || die "הקובץ שהתקבל אינו טלאי"

echo "② dry-run מול הקובץ החי ($LINES שורות)"
if ! patch "$LIVE" --forward --dry-run --fuzz=3 < "$PATCHFILE" >/tmp/dryrun_$TS.log 2>&1; then
  echo "──────────────────────────────────────────────" >&2
  cat /tmp/dryrun_$TS.log >&2
  echo "──────────────────────────────────────────────" >&2
  die "הטלאי לא מתאים — לא נגעתי בכלום. שלח לי את הפלט שלמעלה."
fi

echo "③ מגבה ל-$BAK"
cp "$LIVE" "$BAK" || die "הגיבוי נכשל"

echo "④ מחיל"
patch "$LIVE" --forward --fuzz=3 < "$PATCHFILE" || { restore; die "ההחלה נכשלה — שוחזר"; }

echo "⑤ בודק קומפילציה"
"$PY" -m py_compile "$LIVE" || { restore; die "לא עובר קומפילציה — שוחזר"; }

echo "⑥ מפעיל מחדש"
systemctl restart "$SVC" || { restore; die "ה-restart נכשל — שוחזר"; }

echo "⑦ מחכה שהשירות יענה"
OK=0
for _ in $(seq 1 45); do
  curl -fsS -m 3 "http://127.0.0.1:${PORT}/ping" >/dev/null 2>&1 && { OK=1; break; }
  sleep 2
done
[ "$OK" = "1" ] || { restore; die "/ping לא ענה תוך 90ש' — שוחזר.
   ללוג:  journalctl -u $SVC -n 100 --no-pager"; }

echo
echo "✅ הוחל. הגיבוי: $BAK  ($(wc -l < "$LIVE") שורות)"
echo
echo "בדוק את הפאנל:     https://zovex.duckdns.org/admin"
echo "לוג:               journalctl -u $SVC -f | grep -E 'pinned|pool'"
echo "לכבות רק הזרמה:    systemctl set-environment STREAM_PINNED=0 && systemctl restart $SVC"
echo "לשחזר:             sudo bash $0 --rollback"
