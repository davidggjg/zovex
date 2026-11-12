#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · שידור חי ממקור TS גולמי (פאנל Xtream / קישור בלי .m3u8) → HLS בשרת.
#   שרת: fix_relay_ts.py  ·  פאנל: patch_panel_ts.py  ·  ערוצים קיימים לא משתנים.
#   sudo bash deploy_relay_ts.sh            sudo bash deploy_relay_ts.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u
DIR=/opt/zovex-bot
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${REF}/vps-bot"
die(){ echo "❌ $*" >&2; exit 1; }
[ -f "$DIR/main.py" ] || die "$DIR/main.py לא קיים"
for f in fix_relay_ts.py patch_panel_ts.py; do
  curl -fsSL -H 'Cache-Control: no-cache' "$RAW/$f?t=$(date +%s)" -o "/tmp/$f" || die "הורדה נכשלה: $f"
done
if [ "${1:-}" = "--rollback" ]; then
  MAIN_PY="$DIR/main.py" python3 /tmp/fix_relay_ts.py --revert
  PANEL="$DIR/admin.html" python3 /tmp/patch_panel_ts.py --revert
  python3 -m py_compile "$DIR/main.py" || die "לא מתקמפל אחרי שחזור"
  systemctl restart zovex-bot; echo "✅ שוחזר"; exit 0
fi
echo "① שרת: מצב TS בהמרה"
MAIN_PY="$DIR/main.py" python3 /tmp/fix_relay_ts.py || die "הטלאי לשרת נכשל — לא נגעתי"
if ! python3 -m py_compile "$DIR/main.py"; then
  MAIN_PY="$DIR/main.py" python3 /tmp/fix_relay_ts.py --revert; die "לא מתקמפל — שוחזר"
fi
echo "② פאנל: זיהוי קישור TS"
PANEL="$DIR/admin.html" python3 /tmp/patch_panel_ts.py || echo "⚠️ הפאנל לא עודכן (השרת כן) — אפשר להדביק את הקישור ידנית"
echo "③ הפעלה מחדש"
systemctl restart zovex-bot || die "restart נכשל"
sleep 8
if ! systemctl is-active --quiet zovex-bot; then
  journalctl -u zovex-bot -n 25 --no-pager
  MAIN_PY="$DIR/main.py" python3 /tmp/fix_relay_ts.py --revert; systemctl restart zovex-bot
  die "השרת לא עלה — שוחזר"
fi
code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:8000/ping)
echo "   /ping → $code"
echo
echo "✅ מותקן. בפאנל: הדבק את הקישור המקורי (בלי סיומת) → 'המר לרלֵיי'."
echo "   לחזרה:  sudo bash $0 --rollback"
