#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · פינוי דיסק בטוח.  ברירת מחדל: מציג בלבד.  --apply: מבצע.
#
# לא נוגע לעולם ב: /home/torrents (קבצי הטורנטים), קונטיינרים/אימג'ים פעילים,
# הקטלוג, הבוטים, ‎.env‎, ‎main.py‎ החי, ‎admin.html‎ החי, ו-‎/root/.cache‎ מלבד pip.
#
# מה הוא עושה:
#  1. תקרות סבירות לשני המטמונים (היו 45GB + 20GB = 65GB מתוך דיסק של 100GB):
#     edge_cache → EDGE_GB (ברירת מחדל 6),  zovex-vh → VH_GB (ברירת מחדל 6).
#     נשמר ב-drop-in של systemd, וגוזם מיד עד התקרה (הישנים קודם).
#  2. שאריות המרות MKV ב-mkvwork (רק אם אין ffmpeg שעובד עליהן).
#  3. לוגים: syslog.1 נמחק, syslog מאופס, journald עד 200MB.
#  4. Docker: רק build cache (לא אימג'ים, לא קונטיינרים).
#  5. מטמון pip.
#  6. גיבויי טלאים/אתר: נשמרים כל מה שמ-7 הימים האחרונים (rollback של
#     הטלאים האחרונים ממשיך לעבוד) + 3 האחרונים מכל סוג.
#
#   sudo bash cleanup_disk.sh            # תצוגה
#   sudo bash cleanup_disk.sh --apply    # ביצוע (כולל restart קצר לשרת)
# ─────────────────────────────────────────────────────────────────────────────
set -u
APPLY=0; [ "${1:-}" = "--apply" ] && APPLY=1
EDGE_GB="${EDGE_GB:-6}"; VH_GB="${VH_GB:-6}"
BOT=/opt/zovex-bot; EDGE=$BOT/data/edge_cache; VH=/var/cache/zovex-vh
TOTAL=0
sz(){ du -sb "$@" 2>/dev/null | awk '{s+=$1} END{print s+0}'; }
hb(){ numfmt --to=iec --suffix=B "${1:-0}" 2>/dev/null || echo "$1"; }
step(){ printf '\n▸ %s\n' "$1"; }
say(){ TOTAL=$((TOTAL+$2)); printf '   %-52s %8s\n' "$1" "$(hb $2)"; }
run(){ [ $APPLY = 1 ] && eval "$@"; }

df -h / | tail -1 | awk '{print "דיסק לפני: "$3" תפוס מתוך "$2" ("$5")"}'
[ $APPLY = 1 ] && echo "מצב: ביצוע" || echo "מצב: תצוגה בלבד — שום דבר לא נמחק (הוסף --apply)"

# ── 1. מטמונים ────────────────────────────────────────────────────────────────
trim(){   # trim <dir> <cap-bytes> <find-pattern>   — הישנים (atime) נמחקים קודם
  local dir=$1 cap=$2 pat=$3 cur list freed=0
  [ -d "$dir" ] || { echo 0; return; }
  cur=$(find "$dir" -type f -name "$pat" -printf '%s\n' | awk '{s+=$1} END{print s+0}')
  [ "$cur" -le "$cap" ] && { echo 0; return; }
  local need=$((cur-cap))
  while IFS=' ' read -r _ size path; do
    [ $freed -ge $need ] && break
    run rm -f -- "\"$path\""
    freed=$((freed+size))
  done < <(find "$dir" -type f -name "$pat" -printf '%A@ %s %p\n' | sort -n)
  echo $freed
}
step "1. תקרות למטמונים (edge ${EDGE_GB}GB, vh ${VH_GB}GB)"
E=$(trim "$EDGE" $((EDGE_GB<<30)) '*');  say "edge_cache מעבר לתקרה" "$E"
V=$(trim "$VH"   $((VH_GB<<30))  's*.ts'); say "zovex-vh מעבר לתקרה" "$V"
if [ $APPLY = 1 ]; then
  find "$VH" -mindepth 1 -type d -empty -delete 2>/dev/null
  mkdir -p /etc/systemd/system/zovex-bot.service.d
  cat > /etc/systemd/system/zovex-bot.service.d/zz-cache-caps.conf <<EOF
# cleanup_disk.sh — תקרות מטמון שמתאימות לדיסק משותף
[Service]
Environment=STREAM_EDGE_CACHE_MAX=$((EDGE_GB<<30))
Environment=VODFIX_CACHE_GB=$VH_GB
EOF
  echo "   ✓ תקרות נשמרו ב-zz-cache-caps.conf"
fi

# ── 2. mkvwork ────────────────────────────────────────────────────────────────
step "2. שאריות המרות MKV"
if pgrep -f "ffmpeg.*mkvwork" >/dev/null; then
  echo "   ⏭  יש המרה פעילה — מדלג"
else
  M=$(sz $BOT/mkvwork/*); say "mkvwork/*" "$M"; run 'rm -rf -- '"$BOT"'/mkvwork/*'
fi

# ── 3. לוגים ──────────────────────────────────────────────────────────────────
step "3. לוגים"
S1=$(sz /var/log/syslog.1 /var/log/syslog.*.gz); say "syslog.1 + syslog.*.gz" "$S1"
run 'rm -f /var/log/syslog.1 /var/log/syslog.*.gz'
S0=$(sz /var/log/syslog); say "syslog (מאופס, לא נמחק)" "$S0"
run 'truncate -s 0 /var/log/syslog'
J=$(journalctl --disk-usage 2>/dev/null | grep -oE '[0-9.]+[KMGT]' | head -1 | numfmt --from=iec 2>/dev/null || echo 0)
JF=$(( J > 209715200 ? J-209715200 : 0 )); say "journald מעבר ל-200MB" "$JF"
run 'journalctl --vacuum-size=200M >/dev/null 2>&1'

# ── 4. Docker build cache ─────────────────────────────────────────────────────
step "4. Docker (build cache בלבד)"
if command -v docker >/dev/null; then
  D=$(docker system df --format '{{.Type}} {{.Reclaimable}}' 2>/dev/null | awk '/Build/{print $3}' | numfmt --from=iec 2>/dev/null || echo 0)
  say "docker build cache" "${D:-0}"; run 'docker builder prune -f >/dev/null 2>&1'
fi

# ── 5. pip ────────────────────────────────────────────────────────────────────
step "5. מטמון pip"
P=$(sz /root/.cache/pip); say "/root/.cache/pip" "$P"; run 'rm -rf /root/.cache/pip'

# ── 6. גיבויים ────────────────────────────────────────────────────────────────
step "6. גיבויים ישנים (שומר 7 ימים אחרונים + 3 אחרונים מכל סוג)"
B=0
prune(){   # prune <glob...>  — רשימה ממוינת לפי זמן, שומר 3 אחרונים וכל מה שמ-7 ימים
  local f i=0
  while IFS= read -r f; do
    i=$((i+1)); [ $i -le 3 ] && continue
    [ -n "$(find "$f" -maxdepth 0 -mtime -7 2>/dev/null)" ] && continue
    B=$((B+$(sz "$f"))); run rm -rf -- "\"$f\""
  done < <(ls -1dt "$@" 2>/dev/null)
}
prune $BOT/main.py.bak* $BOT/main.py.before_* $BOT/main_before_*.py
prune $BOT/admin.html.bak*
prune /opt/zovex-site.bak*
say "גיבויים" "$B"

# ── סיכום ─────────────────────────────────────────────────────────────────────
echo; echo "סה\"כ לפינוי: $(hb $TOTAL)"
if [ $APPLY = 1 ]; then
  systemctl daemon-reload
  systemctl restart zovex-bot && sleep 6
  systemctl is-active --quiet zovex-bot && echo "✓ השרת פעיל עם התקרות החדשות" || echo "⚠️ השרת לא עלה — בדוק journalctl -u zovex-bot"
  df -h / | tail -1 | awk '{print "דיסק אחרי: "$3" תפוס ("$5")"}'
else
  echo "לביצוע:  sudo bash $0 --apply"
fi
