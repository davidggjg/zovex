#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# reclaim — מפנה מקום בדיסק. מטמונים ושאריות בלבד.
#
#   bash reclaim.sh          מראה בדיוק מה היה מפנה, ולא מוחק כלום
#   bash reclaim.sh --yes    מפנה
#
# **מה הוא לא נוגע בו, בשום מצב:**
#   · סרטים וסדרות — /home/torrents, /var/www/downloads
#   · content.json והגיבויים האחרונים שלו
#   · המסד של הבוט, .env, הקוד, האתר
#
# הוא מפנה שלושה דברים, וכולם נבנים מעצמם מחדש:
#   1. מטמון הקצה (edge_cache) — נמשך שוב מטלגרם בפתיחה הבאה
#   2. תיקיות עבודה של mkvtool שנשארו מעבודה שנקטעה
#   3. יומני systemd מעל חצי ג'יגה
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail

DO_IT=0
[ "${1:-}" = "--yes" ] && DO_IT=1

EDGE_GB=${EDGE_GB:-3}                 # התקרה שהקוד מגדיר
MKV_AGE_HOURS=${MKV_AGE_HOURS:-6}
JOURNAL_KEEP=${JOURNAL_KEEP:-500M}

DATA=/opt/zovex-bot/data
EDGE=$DATA/edge_cache
MKV=/opt/zovex-bot/mkvwork

human() { numfmt --to=iec --suffix=B "${1:-0}" 2>/dev/null || echo "${1:-0}B"; }

if [ "$DO_IT" -eq 0 ]; then
  echo "════ הרצה יבשה — לא נמחק כלום ════"
  echo "    (להפעיל באמת:  bash reclaim.sh --yes)"
else
  echo "════ מפנה ════"
fi
echo
df -h / | tail -1 | awk '{print "דיסק לפני:  " $3 " בשימוש · " $4 " פנוי · " $5}'
echo

# ── 1. מטמון הקצה ────────────────────────────────────────────────────────────
# הקבצים האלה הם העתק של 12MB מסוף כל סרט ו-2MB מההתחלה. הם נמשכים שוב
# מטלגרם בפתיחה הבאה, ולכן מחיקתם עולה המתנה אחת לצופה אחד.
echo "──── 1. מטמון הקצה ────"
if [ -d "$EDGE" ]; then
  python3 - "$EDGE" "$EDGE_GB" "$DO_IT" <<'PY'
import os, sys
from pathlib import Path
d, cap_gb, do_it = Path(sys.argv[1]), float(sys.argv[2]), sys.argv[3] == "1"
cap = int(cap_gb * (1 << 30))
import time
files, total, stale = [], 0, []
now = time.time()
for p in d.iterdir():
    try:
        st = p.stat()
    except OSError:
        continue
    if not p.is_file():
        continue
    if p.name.endswith(".tmp") and now - st.st_mtime > 300:
        stale.append((st.st_size, p)); continue
    files.append((st.st_atime, st.st_size, p)); total += st.st_size

def h(n):
    return f"{n/(1<<30):.1f}GB" if n >= (1 << 30) else f"{n/(1<<20):.0f}MB"


print(f"  יש עכשיו:  {h(total)} ב-{len(files)} קבצים")
print(f"  התקרה:     {h(cap)}")
if stale:
    print(f"  שאריות .tmp: {len(stale)} קבצים, "
          f"{sum(s for s, _ in stale)/(1<<20):.0f}MB")

to_free, kept = [], total
for atime, size, p in sorted(files):
    if kept <= cap:
        break
    to_free.append((size, p)); kept -= size
n_free = sum(s for s, _ in to_free) + sum(s for s, _ in stale)
print(f"  יפונה:     {h(n_free)} ב-{len(to_free)+len(stale)} קבצים "
      f"(הכי לא-נגועים לאחרונה)")
if do_it:
    gone = 0
    for _s, p in to_free + stale:
        try:
            p.unlink(); gone += 1
        except OSError:
            pass
    print(f"  ✓ נמחקו {gone} קבצים")
PY
else
  echo "  אין תיקייה כזאת — מדלג"
fi
echo

# ── 2. תיקיות עבודה של mkvtool ───────────────────────────────────────────────
# mkvtool מנקה אחרי עצמו, ולכן מה שנשאר כאן הוא עבודה שנקטעה באמצע —
# למשל בהפעלה מחדש של השרת. תיקייה שנגעו בה בשעות האחרונות לא נוגעים בה.
echo "──── 2. תיקיות עבודה שנקטעו (mkvwork) ────"
if pgrep -f mkvtool >/dev/null 2>&1; then
  echo "  ⚠ יש עבודת mkvtool שרצה כרגע — מדלג על הכול כאן."
elif [ -d "$MKV" ]; then
  MKV_TOTAL=$(du -sb "$MKV" 2>/dev/null | cut -f1)
  echo "  התיקייה כולה: $(human "${MKV_TOTAL:-0}")"
  FOUND=0; SUM=0
  while IFS= read -r dir; do
    [ -z "$dir" ] && continue
    SZ=$(du -sb "$dir" 2>/dev/null | cut -f1)
    SUM=$((SUM + ${SZ:-0})); FOUND=$((FOUND + 1))
    printf "    %-46s %s  (נגעו לפני %s שעות)\n" \
      "$(basename "$dir")" "$(human "${SZ:-0}")" \
      "$(( ( $(date +%s) - $(stat -c %Y "$dir") ) / 3600 ))"
    [ "$DO_IT" -eq 1 ] && rm -rf -- "$dir"
  done < <(find "$MKV" -mindepth 1 -maxdepth 1 -type d \
             -mmin +$((MKV_AGE_HOURS * 60)) 2>/dev/null)
  if [ "$FOUND" -eq 0 ]; then
    echo "    אין תיקייה ישנה מ-${MKV_AGE_HOURS} שעות — אין מה לפנות"
  else
    echo "  יפונה: $(human "$SUM") ב-$FOUND תיקיות"
    [ "$DO_IT" -eq 1 ] && echo "  ✓ נמחקו"
  fi
else
  echo "  אין תיקייה כזאת — מדלג"
fi
echo

# ── 3. יומני systemd ─────────────────────────────────────────────────────────
echo "──── 3. יומני systemd ────"
journalctl --disk-usage 2>/dev/null | sed 's/^/  /'
if [ "$DO_IT" -eq 1 ]; then
  journalctl --vacuum-size="$JOURNAL_KEEP" 2>&1 | tail -2 | sed 's/^/  /'
  # תקרה קבועה, אחרת זה יחזור לגדול לאותם 4 ג'יגה
  if ! grep -q "^SystemMaxUse=" /etc/systemd/journald.conf 2>/dev/null; then
    printf '\n# [reclaim] תקרה ליומן, אחרת הוא גדל עד 4GB\nSystemMaxUse=%s\n' \
      "$JOURNAL_KEEP" >> /etc/systemd/journald.conf
    systemctl restart systemd-journald 2>/dev/null
    echo "  ✓ נקבעה תקרה קבועה: SystemMaxUse=$JOURNAL_KEEP"
  fi
else
  echo "  יפונה ל-$JOURNAL_KEEP ותיקבע תקרה קבועה"
fi
echo

# ── מה שלא נוגעים בו, רק מדווחים ────────────────────────────────────────────
echo "──── לא נוגעים בזה — זה שלך, לא מטמון ────"
for p in /home/torrents /var/www/downloads /var/cache/zovex-vh \
         /var/lib/containerd "$DATA/content_backups"; do
  [ -e "$p" ] && printf "  %-34s %s\n" "$p" "$(du -sh "$p" 2>/dev/null | cut -f1)"
done
cat <<'TXT'

  · /home/torrents ו-/var/www/downloads הם קבצי וידאו. למחוק רק מה
    שאתה מזהה, למשל:   ls -lhS /var/www/downloads | head
  · /var/cache/zovex-vh הוא מטמון המרה עם תקרה של 20GB. על דיסק של
    99GB זה הרבה — להקטין ל-8:
        echo 'VODFIX_CACHE_GB=8' >> /opt/zovex-bot/.env
        systemctl restart zovex-bot
  · /var/lib/containerd הוא תמונות דוקר. אם אינך מריץ דוקר על השרת
    הזה, זה מקום שאין לו שימוש:   docker ps -a 2>/dev/null | head
TXT
echo
df -h / | tail -1 | awk '{print "דיסק אחרי:  " $3 " בשימוש · " $4 " פנוי · " $5}'
if [ "$DO_IT" -eq 0 ]; then
  echo
  echo "זו הייתה הרצה יבשה. להפעיל:  bash reclaim.sh --yes"
fi
