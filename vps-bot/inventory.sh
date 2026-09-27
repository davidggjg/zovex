#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# inventory — מה יושב על השרת, מה תופס מקום, ומה מצב השירותים.
#
# **קריאה בלבד.** לא מוחק, לא מפעיל מחדש, לא נוגע בכלום.
#
#   bash /opt/zovex-bot/inventory.sh
# ──────────────────────────────────────────────────────────────────────────────
echo "════════ דיסק ════════"
df -hT / 2>/dev/null | grep -vi tmpfs
echo
echo "════════ מה תופס ב-/ ════════"
du -xh --max-depth=1 / 2>/dev/null | sort -rh | head -14
echo
echo "════════ פירוט /opt ו-/var ════════"
du -xh --max-depth=2 /opt /var/lib /var/log /var/cache 2>/dev/null | sort -rh | head -22
echo
echo "════════ הקבצים הגדולים (מעל 200MB) ════════"
find / -xdev -type f -size +200M -printf '%s\t%p\n' 2>/dev/null | sort -rn | head -15 \
  | awk -F'\t' '{printf "%7.2f GB  %s\n", $1/1073741824, $2}'
echo
echo "════════ תיקיות הנתונים ════════"
for p in /opt/groupos /opt/groupos/data /root /home /tmp /srv; do
  [ -e "$p" ] && printf "%-24s %s\n" "$p" "$(du -sh "$p" 2>/dev/null | cut -f1)"
done
echo
echo "════════ יומני מערכת ומטמונים ════════"
journalctl --disk-usage 2>/dev/null
du -sh /tmp/* 2>/dev/null | sort -rh | head -8
echo
echo "════════ שירותים ════════"
for s in zovex-bot groupos nginx; do
  printf "%-12s active=%-10s enabled=%s\n" "$s" \
    "$(systemctl is-active $s 2>&1 | head -1)" "$(systemctl is-enabled $s 2>&1 | head -1)"
done
echo
echo "════════ זיכרון ופרוצסים כבדים ════════"
free -h | head -2
ps -eo pid,pcpu,pmem,rss,etime,comm --sort=-rss | head -8
echo "ffmpeg פעילים: $(pgrep -c ffmpeg 2>/dev/null || true)"
echo "════════ דיסק ════════"
df -hT / 2>/dev/null | grep -vi tmpfs
echo
echo "════════ מה תופס ב-/ ════════"
du -xh --max-depth=1 / 2>/dev/null | sort -rh | head -14
echo
echo "════════ פירוט /opt ו-/var ════════"
du -xh --max-depth=2 /opt /var/lib /var/log /var/cache 2>/dev/null | sort -rh | head -22
echo
echo "════════ הקבצים הגדולים (מעל 200MB) ════════"
find / -xdev -type f -size +200M -printf '%s\t%p\n' 2>/dev/null | sort -rn | head -15 \
  | awk -F'\t' '{printf "%7.2f GB  %s\n", $1/1073741824, $2}'
echo
echo "════════ תיקיות הנתונים ════════"
for p in /opt/groupos /opt/groupos/data /root /home /tmp /srv; do
  [ -e "$p" ] && printf "%-24s %s\n" "$p" "$(du -sh "$p" 2>/dev/null | cut -f1)"
done
echo
echo "════════ יומני מערכת ומטמונים ════════"
journalctl --disk-usage 2>/dev/null
du -sh /tmp/* 2>/dev/null | sort -rh | head -8
echo
echo "════════ שירותים ════════"
for s in zovex-bot groupos nginx; do
  printf "%-12s active=%-10s enabled=%s\n" "$s" \
    "$(systemctl is-active $s 2>&1 | head -1)" "$(systemctl is-enabled $s 2>&1 | head -1)"
done
echo
echo "════════ זיכרון ופרוצסים כבדים ════════"
free -h | head -2
ps -eo pid,pcpu,pmem,rss,etime,comm --sort=-rss | head -8
echo "ffmpeg פעילים: $(pgrep -c ffmpeg 2>/dev/null || true)"

echo
echo "════════ תוכן ומדיה של zovex ════════"
for p in /opt/zovex-bot /opt/zovex-bot/data /opt/zovex-bot/data/content.json \
         /opt/zovex-bot/data/hls /opt/zovex-bot/data/posters \
         /var/www /usr/share/nginx/html; do
  [ -e "$p" ] && printf "%-42s %s\n" "$p" "$(du -sh "$p" 2>/dev/null | cut -f1)"
done
echo
echo "════════ 12 התיקיות הגדולות תחת /opt/zovex-bot ════════"
du -xh --max-depth=2 /opt/zovex-bot 2>/dev/null | sort -rh | head -12
echo
echo "════════ כמה קבצים בכל תיקיית נתונים ════════"
for p in /opt/zovex-bot/data /opt/zovex-bot/data/hls /opt/groupos/data/backups; do
  [ -d "$p" ] && printf "%-38s %s קבצים\n" "$p" "$(find "$p" -type f 2>/dev/null | wc -l)"
done
