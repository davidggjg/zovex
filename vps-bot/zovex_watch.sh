#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · מנטר רקע: רושם מה קורה, ומדווח אחר כך מה השתנה.
#
# דווח: "אחרי בערך 20 דקות הכול מתאפס ומתחיל מחדש". מונים יושבים בזיכרון,
# ולכן אי אפשר לדעת בדיעבד מה קרה — עד שמישהו רושם. זה מה שהסקריפט עושה.
#
# הוא רץ מנותק מהטרמינל (setsid + nohup), ולכן סגירת החלון או ניתוק
# ה-SSH אינם עוצרים אותו.
#
#   sudo bash zovex_watch.sh start     # מתחיל לנטר ברקע
#   sudo bash zovex_watch.sh report    # מה קרה מאז
#   sudo bash zovex_watch.sh stop
#
# הסיסמה נקראת בהקלדה ומועברת בסביבה בלבד — היא אינה נכתבת לדיסק ואינה
# מופיעה ב-ps.
# ─────────────────────────────────────────────────────────────────────────────
set -u
API="http://127.0.0.1:8000"
PY=/opt/zovex-bot/venv/bin/python
[ -x "$PY" ] || PY=python3
LOG=/var/log/zovex_watch.log
EVT=/var/log/zovex_events.log
PIDF=/run/zovex_watch.pid
INTERVAL="${WATCH_INTERVAL:-30}"

sample() {
  while true; do
    NOW=$(date '+%Y-%m-%d %H:%M:%S')
    NR=$(systemctl show zovex-bot -p NRestarts --value 2>/dev/null)
    PID=$(systemctl show zovex-bot -p MainPID --value 2>/dev/null)
    RSS=$(awk '/VmRSS/{print $2}' "/proc/$PID/status" 2>/dev/null)
    CONN=$(ss -tn state established '( sport = :443 )' 2>/dev/null | tail -n +2 | wc -l)
    LOAD=$(awk '{print $1}' /proc/loadavg)
    D=$(curl -fsS -m 8 "$API/debug/caches" 2>/dev/null | "$PY" -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception: print("- - - - -"); raise SystemExit
caps=d.get("bot_caps") or {}
print(d.get("stream_bots","-"), d.get("benched_now","-"),
      sum(1 for v in caps.values() if v is not None),
      d.get("edge_fill_dropped","-"), d.get("flood_premium","-"))' 2>/dev/null)
    [ -n "$D" ] || D="- - - - -"
    E="- -"
    if [ -n "${WPASS:-}" ]; then
      E=$(curl -fsS -m 8 -X POST "$API/panel/enrich/status" \
            -H 'Content-Type: application/json' -d "{\"password\":\"$WPASS\"}" 2>/dev/null \
          | "$PY" -c 'import json,sys
try: d=json.load(sys.stdin)
except Exception: print("- -"); raise SystemExit
print(d.get("done","-"), 1 if d.get("running") else 0)' 2>/dev/null)
      [ -n "$E" ] || E="- -"
    fi
    echo "$NOW|$NR|$RSS|$CONN|$LOAD|$D|$E" >> "$LOG"
    sleep "$INTERVAL"
  done
}

case "${1:-}" in
  start)
    if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
      echo "כבר רץ (pid $(cat "$PIDF"))"; exit 0
    fi
    read -r -s -p "סיסמת הפאנל (לא חובה — Enter לדילוג): " WPASS; echo
    export WPASS
    : > "$LOG"
    echo "# התחיל $(date)" >> "$EVT"
    # setsid מנתק מהטרמינל לגמרי: סגירת החלון או ניתוק SSH לא יעצרו
    setsid nohup bash "$0" _loop >/dev/null 2>&1 &
    echo $! > "$PIDF"
    echo "✅ מנטר ברקע (pid $(cat "$PIDF")), דגימה כל ${INTERVAL}ש'"
    echo "   אפשר לסגור את החלון. לדוח:  sudo bash $0 report"
    ;;
  _loop) sample ;;
  stop)
    [ -f "$PIDF" ] && kill "$(cat "$PIDF")" 2>/dev/null && rm -f "$PIDF" \
      && echo "✅ נעצר" || echo "לא רץ"
    ;;
  report)
    [ -s "$LOG" ] || { echo "אין נתונים — הרץ קודם: sudo bash $0 start"; exit 1; }
    "$PY" - "$LOG" <<'PYEOF'
import sys, io
rows = []
for line in io.open(sys.argv[1], encoding="utf-8"):
    p = line.strip().split("|")
    if len(p) < 7:
        continue
    t, nr, rss, conn, load = p[0], p[1], p[2], p[3], p[4]
    d = p[5].split()
    e = p[6].split()
    rows.append(dict(t=t, nr=nr, rss=rss, conn=conn, load=load,
                     bots=d[0] if len(d) > 0 else "-",
                     bench=d[1] if len(d) > 1 else "-",
                     caps=d[2] if len(d) > 2 else "-",
                     drop=d[3] if len(d) > 3 else "-",
                     flood=d[4] if len(d) > 4 else "-",
                     done=e[0] if len(e) > 0 else "-",
                     run=e[1] if len(e) > 1 else "-"))
if not rows:
    print("אין דגימות תקינות עדיין."); raise SystemExit
a, b = rows[0], rows[-1]
print(f"טווח: {a['t']}  →  {b['t']}   ({len(rows)} דגימות)\n")

def num(x):
    try: return int(x)
    except Exception: return None

ev = []
for i in range(1, len(rows)):
    p, c = rows[i-1], rows[i]
    if num(c["nr"]) is not None and num(p["nr"]) is not None and num(c["nr"]) > num(p["nr"]):
        ev.append((c["t"], "🔴 השירות עלה מחדש"))
    if num(c["done"]) is not None and num(p["done"]) is not None and num(c["done"]) < num(p["done"]):
        ev.append((c["t"], f"🟠 סורק ההעשרה התאפס ({p['done']} → {c['done']})"))
    if num(c["bots"]) is not None and num(p["bots"]) is not None and num(c["bots"]) < num(p["bots"]):
        ev.append((c["t"], f"🟠 בריכת הבוטים קטנה ({p['bots']} → {c['bots']})"))
    if num(c["flood"]) is not None and num(p["flood"]) is not None and num(c["flood"]) > num(p["flood"]):
        ev.append((c["t"], f"🟡 FLOOD_PREMIUM_WAIT (+{num(c['flood'])-num(p['flood'])})"))
    if num(c["bench"]) is not None and num(p["bench"]) is not None and num(c["bench"]) > num(p["bench"]):
        ev.append((c["t"], f"🪑 בוטים בספסל {p['bench']} → {c['bench']}"))

if ev:
    print("אירועים:")
    for t, m in ev[-40:]:
        print(f"  {t}  {m}")
else:
    print("אירועים: אין. שום דבר לא התאפס ולא קרס בטווח הזה.")

print("\nמצב עכשיו:")
print(f"  בוטים {b['bots']} · בספסל {b['bench']} · קיבולת נמדדה ל-{b['caps']}")
print(f"  חיבורים 443: {b['conn']} · עומס {b['load']} · זיכרון {b['rss']} KB")
print(f"  סורק: done={b['done']} running={b['run']}")
print(f"  מילויים שנזרקו {b['drop']} · FLOOD_PREMIUM {b['flood']}")

rs = [num(r["rss"]) for r in rows if num(r["rss"])]
if len(rs) > 2:
    print(f"\nזיכרון: {min(rs)} → {max(rs)} KB"
          + ("   ⚠️ גדל ביותר מ-50%" if max(rs) > min(rs)*1.5 else "   (יציב)"))
PYEOF
    ;;
  *)
    echo "שימוש:  sudo bash $0 start | report | stop"; exit 1 ;;
esac
