#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · תקרת חיבורים לכל DC של טלגרם + פסק זמן לפתיחת חיבור.
# מתקן: סרטים ב-DC4 שלא נפתחים, ולולאת "Connection failed" (42 אלף בשעה).
#   sudo bash deploy_media_dc_cap.sh            sudo bash deploy_media_dc_cap.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u
DIR=/opt/zovex-bot
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${REF}/vps-bot"
die(){ echo "❌ $*" >&2; exit 1; }
for f in fix_media_dc_cap.py bench_stream.py; do
  curl -fsSL -H 'Cache-Control: no-cache' "$RAW/$f?t=$(date +%s)" -o "/tmp/$f" || die "הורדה נכשלה: $f"
done
if [ "${1:-}" = "--rollback" ]; then
  MAIN_PY="$DIR/main.py" python3 /tmp/fix_media_dc_cap.py --revert || die "שחזור נכשל"
  python3 -m py_compile "$DIR/main.py" || die "לא מתקמפל"
  systemctl restart zovex-bot; echo "✅ שוחזר"; exit 0
fi
echo "① מחיל"
MAIN_PY="$DIR/main.py" python3 /tmp/fix_media_dc_cap.py || die "הטלאי נכשל — לא נגעתי"
python3 -m py_compile "$DIR/main.py" || { MAIN_PY="$DIR/main.py" python3 /tmp/fix_media_dc_cap.py --revert; die "לא מתקמפל — שוחזר"; }
echo "② הפעלה מחדש"
systemctl restart zovex-bot; sleep 8
systemctl is-active --quiet zovex-bot || { journalctl -u zovex-bot -n 25 --no-pager; MAIN_PY="$DIR/main.py" python3 /tmp/fix_media_dc_cap.py --revert; systemctl restart zovex-bot; die "השרת לא עלה — שוחזר"; }
echo "③ חימום (90ש)"; sleep 90
P=$(systemctl show -p MainPID --value zovex-bot)
echo "== חיבורים לטלגרם =="; ss -tnp 2>/dev/null | grep "pid=$P," | awk '{print $1}' | sort | uniq -c | sed 's/^/  /'
echo "== לכל DC מול התקרה =="; curl -s -m 5 http://127.0.0.1:8000/stream/media-caps; echo
echo "== 'Connection failed' בדקה וחצי האחרונות =="; journalctl -u zovex-bot --since "2 min ago" --no-pager | grep -c "Connection failed" | sed 's/^/  /'
if [ -n "${TEST_URL:-}" ]; then
  echo "== הסרט שלא נפתח =="
  curl -s -o /dev/null -m 40 -H "Referer: https://zovex.duckdns.org/" -H "Range: bytes=0-4194303" \
    -w "  status=%{http_code} הורדו=%{size_download} בייט · עד הבייט הראשון=%{time_starttransfer}s · סה\"כ=%{time_total}s\n" "$TEST_URL"
fi
echo "== מדידת מהירות =="; python3 /tmp/bench_stream.py
echo; echo "✅ מותקן.  לחזרה: sudo bash $0 --rollback"
