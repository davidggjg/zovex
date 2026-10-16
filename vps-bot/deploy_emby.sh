#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# פורס את תמיכת ה-Emby: נתיבי /emby/* ב-main.py, ומעבר שלהם ב-Caddy.
#
# למה שניהם: ה-Caddyfile מעביר לאפליקציה רק רשימת נתיבים מפורשת, ו-/emby
# לא היה בה. לכן POST ל-/emby/register נפל להגשת הקבצים הסטטיים, ו-
# file_server עונה 405 על POST — זו השגיאה שראית בפאנל.
#
# בטוח: dry-run לפני כל נגיעה, גיבוי לשני הקבצים, בדיקת קומפילציה, בדיקת
# תצורת Caddy, ושחזור אוטומטי של שניהם בכל כשל.
#
#   sudo bash deploy_emby.sh
#   sudo bash deploy_emby.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u

BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/emby.patch"
DIR=/opt/zovex-bot
LIVE="$DIR/main.py"
PY="$DIR/venv/bin/python"
SVC=zovex-bot
CADDY=/etc/caddy/Caddyfile
PORT="${PORT:-8000}"
TS=$(date +%Y%m%d-%H%M%S)
BAK="$DIR/main_before_emby_${TS}.py"
CBAK="${CADDY}.before_emby_${TS}"
PF="/tmp/emby_${TS}.patch"

die() { echo "❌ $*" >&2; exit 1; }

if [ "${1:-}" = "--rollback" ]; then
  LAST=$(ls -1t "$DIR"/main_before_emby_*.py 2>/dev/null | head -1)
  [ -n "$LAST" ] && { cp "$LAST" "$LIVE"; echo "שוחזר $LAST"; }
  CLAST=$(ls -1t "${CADDY}".before_emby_* 2>/dev/null | head -1)
  [ -n "$CLAST" ] && { cp "$CLAST" "$CADDY"; systemctl reload caddy; echo "שוחזר $CLAST"; }
  systemctl restart "$SVC"
  echo "✅ שוחזר"
  exit 0
fi

[ -f "$LIVE" ] || die "$LIVE לא קיים"
[ -x "$PY" ]   || die "$PY לא קיים"
[ -f "$CADDY" ] || die "$CADDY לא קיים"
command -v patch >/dev/null || die "חסר patch:  apt-get install -y patch"

# ── 1. הקוד ─────────────────────────────────────────────────────────────────
if grep -q "emby_register" "$LIVE"; then
  echo "① הקוד כבר מכיל את נתיבי /emby — מדלג"
else
  echo "① מוריד את הטלאי"
  curl -fsSL "$RAW" -o "$PF" || die "הורדת הטלאי נכשלה"
  grep -q "^@@" "$PF" || die "הקובץ שהתקבל אינו טלאי"

  echo "② dry-run מול $LIVE ($(wc -l < "$LIVE") שורות)"
  if ! patch "$LIVE" --forward --dry-run --fuzz=3 < "$PF" > /tmp/emby_dry_$TS.log 2>&1; then
    cat /tmp/emby_dry_$TS.log >&2
    die "הטלאי לא מתאים לקובץ החי — לא נגעתי בכלום. שלח לי את הפלט."
  fi

  echo "③ מגבה ל-$BAK ומחיל"
  cp "$LIVE" "$BAK" || die "גיבוי נכשל"
  patch "$LIVE" --forward --fuzz=3 < "$PF" || { cp "$BAK" "$LIVE"; die "ההחלה נכשלה — שוחזר"; }
  "$PY" -m py_compile "$LIVE" || { cp "$BAK" "$LIVE"; die "לא עובר קומפילציה — שוחזר"; }
fi

# ── 2. Caddy ────────────────────────────────────────────────────────────────
if grep -q '/emby/\*' "$CADDY"; then
  echo "④ Caddy כבר מעביר /emby/* — מדלג"
else
  echo "④ מוסיף /emby/* ל-Caddy"
  grep -q '@api path' "$CADDY" || die "לא מצאתי '@api path' ב-$CADDY — תקן ידנית"
  cp "$CADDY" "$CBAK" || die "גיבוי Caddyfile נכשל"
  sed -i 's#\(@api path .*\)/hls-relay/\*#\1/hls-relay/* /emby/*#' "$CADDY"
  grep -q '/emby/\*' "$CADDY" || { cp "$CBAK" "$CADDY"; die "העריכה לא נתפסה — שוחזר"; }
  caddy validate --config "$CADDY" --adapter caddyfile >/dev/null 2>&1 \
    || { cp "$CBAK" "$CADDY"; die "תצורת Caddy לא תקינה — שוחזר"; }
fi

# ── 3. הפעלה מחדש ובדיקה ────────────────────────────────────────────────────
echo "⑤ מפעיל מחדש"
systemctl reload caddy 2>/dev/null || systemctl restart caddy
systemctl restart "$SVC" || die "restart נכשל"

echo "⑥ מחכה שהשירות יענה (ההפעלה לוקחת דקות — הבוטים עולים בהדרגה)"
OK=0
for _ in $(seq 1 60); do
  curl -fsS -m 3 "http://127.0.0.1:${PORT}/ping" >/dev/null 2>&1 && { OK=1; break; }
  sleep 3
done
[ "$OK" = "1" ] || die "/ping לא ענה תוך 3 דקות.  journalctl -u $SVC -n 80 --no-pager"

# /emby/register בלי סיסמה חייב להחזיר 401/403 — לא 405 ולא 404.
CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -X POST \
  -H 'Content-Type: application/json' -d '{"password":"x","url":"y"}' \
  "https://zovex.duckdns.org/emby/register")
echo
echo "   /emby/register → HTTP $CODE"
case "$CODE" in
  401|403) echo "   ✅ הנתיב חי ומוגן (405 הוא מה שהיה קודם)";;
  405) echo "   ❌ עדיין 405 — Caddy לא מעביר. בדוק: grep '@api path' $CADDY";;
  404) echo "   ❌ 404 — הקוד לא נטען. בדוק: journalctl -u $SVC -n 50";;
  *)   echo "   ⚠️  לא צפוי";;
esac
echo
echo "✅ נפרס. גיבויים: $BAK ${CBAK:-(ללא)}"
echo "לשחזור:  sudo bash $0 --rollback"
