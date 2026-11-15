#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · הורדות מ-DC4 דרך הכתובת הרגילה (כתובת ה-media חסומה לשרת).
#   sudo bash deploy_dc_media_addr.sh            sudo bash deploy_dc_media_addr.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u
DIR=/opt/zovex-bot; PY=$DIR/venv/bin/python
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${REF}/vps-bot"
die(){ echo "❌ $*" >&2; exit 1; }
for f in fix_dc_media_addr.py bench_stream.py; do
  curl -fsSL -H 'Cache-Control: no-cache' "$RAW/$f?t=$(date +%s)" -o "/tmp/$f" || die "הורדה נכשלה: $f"
done
if [ "${1:-}" = "--rollback" ]; then
  MAIN_PY="$DIR/main.py" python3 /tmp/fix_dc_media_addr.py --revert || die "שחזור נכשל"
  python3 -m py_compile "$DIR/main.py" && systemctl restart zovex-bot; echo "✅ שוחזר"; exit 0
fi
echo "① בודק את הספרייה בשרת"
$PY -c "from pyrogram.session.internals.data_center import DataCenter as D; assert 4 in D.PROD_MEDIA; print('   ', D(4,False,False,True), '← היום')" || die "המבנה בספרייה שונה — לא נגעתי"
echo "② מחיל"
MAIN_PY="$DIR/main.py" python3 /tmp/fix_dc_media_addr.py || die "הטלאי נכשל — לא נגעתי"
python3 -m py_compile "$DIR/main.py" || { MAIN_PY="$DIR/main.py" python3 /tmp/fix_dc_media_addr.py --revert; die "לא מתקמפל — שוחזר"; }
echo "③ הפעלה מחדש"
systemctl restart zovex-bot; sleep 8
systemctl is-active --quiet zovex-bot || { journalctl -u zovex-bot -n 25 --no-pager; MAIN_PY="$DIR/main.py" python3 /tmp/fix_dc_media_addr.py --revert; systemctl restart zovex-bot; die "השרת לא עלה — שוחזר"; }
journalctl -u zovex-bot --since "1 min ago" --no-pager | grep -E "media DCs|fix_dc_media_addr" | tail -2 | sed 's/^/   /'
echo "④ חימום (60ש)"; sleep 60
P=$(systemctl show -p MainPID --value zovex-bot)
echo "== לאן מתחבר =="; ss -tnp 2>/dev/null | grep "pid=$P," | awk '{print $1, $5}' | sed -E 's/:[0-9]+$//' | sort | uniq -c | sort -rn | head -6
if [ -n "${TEST_URL:-}" ]; then
  echo "== הסרט שלא נפתח =="
  curl -s -o /dev/null -m 40 -H "Referer: https://zovex.duckdns.org/" -H "Range: bytes=0-4194303" \
    -w "  status=%{http_code} הורדו=%{size_download} בייט · עד הבייט הראשון=%{time_starttransfer}s\n" "$TEST_URL"
fi
python3 /tmp/bench_stream.py --n 4
echo; echo "✅ מותקן.  לחזרה: sudo bash $0 --rollback"
