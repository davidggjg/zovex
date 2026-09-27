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
# mkvtool מנקה אחרי עצמו, ולכן מה שנשאר כאן הוא עבודה שנקטעה באמצע —
# למשל בהפעלה מחדש של השרת.
#
# **לא** "האם mkvtool רץ": הוא שירות שיושב ב-idle ומחכה לקבצים, כלומר
# הוא רץ *תמיד*, ובדיקה כזאת הייתה מדלגת על 11GB לנצח. במקום זה נבדק
# לכל תיקייה בנפרד אם מישהו מחזיק בה קובץ פתוח או יושב בה — דרך /proc,
# בלי תלות ב-lsof שאינו בטוח מותקן.
if [ -d "$MKV" ]; then
  python3 - "$MKV" "$MKV_AGE_HOURS" "$DO_IT" <<'PYMKV'
import os, shutil, sys, time
from pathlib import Path

root, age_h, do_it = Path(sys.argv[1]), float(sys.argv[2]), sys.argv[3] == "1"


def busy_paths():
    """כל מה שתהליך כלשהו מחזיק פתוח, או יושב בו כ-cwd."""
    out = set()
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        for kind in ("cwd", "fd"):
            base = "/proc/%s/%s" % (pid, kind)
            try:
                names = [base] if kind == "cwd" else \
                    ["%s/%s" % (base, fd) for fd in os.listdir(base)]
            except OSError:
                continue
            for n in names:
                try:
                    out.add(os.path.realpath(os.readlink(n)))
                except OSError:
                    continue
    return out


def h(n):
    return "%.1fGB" % (n / (1 << 30)) if n >= (1 << 30) else "%.0fMB" % (n / (1 << 20))


open_paths = busy_paths()
now = time.time()
cut = now - age_h * 3600
total_all = 0
cand, skipped = [], []
for d in sorted(root.iterdir() if root.exists() else []):
    if not d.is_dir():
        continue
    size = 0
    for f in d.rglob("*"):
        try:
            if f.is_file():
                size += f.stat().st_size
        except OSError:
            pass
    total_all += size
    try:
        mtime = d.stat().st_mtime
    except OSError:
        continue
    real = os.path.realpath(d)
    in_use = any(x == real or x.startswith(real + os.sep) for x in open_paths)
    if in_use:
        skipped.append((d.name, size, "קובץ פתוח בתוכה"))
    elif mtime > cut:
        skipped.append((d.name, size, "נגעו בה לפני %.0f דקות" % ((now - mtime) / 60)))
    else:
        cand.append((d, size, (now - mtime) / 3600))

print("  התיקייה כולה: " + h(total_all))
for name, size, why in skipped:
    print("    \u2298 %-12s %8s  \u2014 %s" % (name, h(size), why))
if not cand:
    print("    אין תיקייה שאפשר לפנות")
else:
    for d, size, hours in cand:
        print("    %-12s %8s  (נקטעה לפני %.0f שעות)" % (d.name, h(size), hours))
    print("  יפונה: %s ב-%d תיקיות" % (h(sum(s for _, s, _ in cand)), len(cand)))
    if do_it:
        gone = 0
        for d, _s, _hrs in cand:
            shutil.rmtree(d, ignore_errors=True)
            if not d.exists():
                gone += 1
        print("  \u2713 נמחקו %d תיקיות" % gone)
PYMKV
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
