#!/bin/bash
# snapwatch — שורה אחת כל כמה דקות, כדי שתהיה עקומה ולא צילום.
#
# ## למה זה קיים
#
# התסמין הוא "אחרי כמה שעות או ימים בלי ריסט מתחיל להיתקע, ומתגבר". צילום
# בודד לא יכול להוכיח דבר כזה: המדידה מ-24 שעות למעלה הראתה שרת במנוחה
# (load 0.05) ולכן שללה יפה — ffmpeg 0, 31 משימות, 11 threads, 254 FD —
# אבל לא יכלה למצוא כלום, כי באותה שנייה לא קרה כלום.
#
# טענה על **הצטברות** נבדקת רק מול ציר זמן. לכן: דגימה כל כמה דקות,
# שורה אחת לכל דגימה, כך שאפשר לפתוח את הקובץ ולראות מה טיפס בין
# הרגע השקט לרגע התקוע.
#
# ## קריאה בלבד
#
# קורא /proc ושתי נקודות דיבאג מקומיות של כמה בתים. לא מוריד וידאו, לא
# נוגע בטלגרם, לא כותב לשום דבר של המערכת. אפשר להשאיר רץ ימים.
#
#     nohup ./snapwatch.sh > /dev/null 2>&1 &
#     tail -20 /tmp/zovex_snap.log
#     pkill -f snapwatch.sh          # לעצור
#
# כל עמודה והמשמעות שלה:
#   up      כמה זמן השירות למעלה — זה הציר. בלעדיו כל מספר הוא סתם מספר.
#   rss     זיכרון במגה. החשוד היחיד שנשאר פתוח מהצילום הראשון.
#   fd/sock מצייני קבצים וסוקטים. דליפה כאן = כל משיכה מחכה לחיבור מת.
#   thr     threads.
#   ffm     תהליכי ffmpeg של ערוצים חיים שלא נסגרו.
#   task    משימות asyncio ממתינות.
#   pool    בריכות טלגרם / חיבורים בהן.
#   load    עומס. זה מה שמזהה את *רגע* התקיעה בתוך העקומה.
#   c443    חיבורים פתוחים של צופים.

OUT=${SNAP_OUT:-/tmp/zovex_snap.log}
EVERY=${SNAP_EVERY:-300}
PORT=${PORT:-8000}

field() {   # field <טקסט json> <שם שדה>
    echo "$1" | tr -d '{}"' | tr ',' '\n' | awk -F: -v k="$2" \
        '$1 ~ k {gsub(/ /,"",$2); print $2; exit}'
}

echo "snapwatch: דוגם כל ${EVERY}ש אל $OUT · לעצירה: pkill -f snapwatch.sh" >&2

while true; do
    P=$(systemctl show zovex-bot -p MainPID --value 2>/dev/null)
    [ -z "$P" -o "$P" = "0" ] && P=$(pgrep -f /opt/zovex-bot/main.py | head -1)

    if [ -z "$P" ] || [ ! -d "/proc/$P" ]; then
        # השירות לא רץ. נרשם ולא מדולג: "השירות היה למטה" הוא בדיוק סוג
        # האירוע שצריך להופיע בעקומה, ולא להיעלם ממנה.
        echo "$(date '+%F %H:%M') | השירות לא רץ" >> "$OUT"
        sleep "$EVERY"; continue
    fi

    # גיל התהליך עצמו, ולא חותמת של systemd: זה בדיוק "כמה זמן מאז הריסט",
    # הוא נכון גם כשהשירות הופעל ידנית, ואין בו נפילה שקטה לערך שגוי כש-
    # systemctl לא מחזיר כלום.
    UPS=$(ps -o etimes= -p "$P" 2>/dev/null | tr -d ' ')
    [ -z "$UPS" ] && UPS=0
    UPH=$(awk -v s="$UPS" 'BEGIN{printf "%.1f", s/3600}')

    RSS=$(awk '/VmRSS/{printf "%d", $2/1024}' "/proc/$P/status" 2>/dev/null)
    THR=$(awk '/Threads/{print $2}' "/proc/$P/status" 2>/dev/null)
    FD=$(ls "/proc/$P/fd" 2>/dev/null | wc -l)
    SOCK=$(ls -l "/proc/$P/fd" 2>/dev/null | grep -c socket)
    FFM=$(pgrep -c -P "$P" ffmpeg 2>/dev/null); [ -z "$FFM" ] && FFM=0
    LOAD=$(cut -d' ' -f1 /proc/loadavg)
    C443=$(ss -tn state established '( sport = :443 )' 2>/dev/null | tail -n +2 | wc -l)

    # סחרור הסשנים מול טלגרם, נספר על החלון שמאז הדגימה הקודמת. זו השאלה
    # הפתוחה היחידה אחרי fix_pool_thrash: מדידה של אפס התקבלה על שרת
    # שאותחל זה עתה ובשעה ריקה, ולכן היא לא יכולה להבדיל בין "התיקון
    # עובד" ל"עוד לא הספיק להצטבר". רק העמודה הזאת לאורך יממה תפריד.
    JL=$(journalctl -u zovex-bot --since "${EVERY} sec ago" --no-pager -o cat 2>/dev/null)
    CONN=$(printf '%s' "$JL" | grep -c "Connecting" )
    SKIP=$(printf '%s' "$JL" | grep -c "מדלג על הפלה")

    TJ=$(curl -s --max-time 5 "http://127.0.0.1:$PORT/debug/tasks" 2>/dev/null)
    CJ=$(curl -s --max-time 5 "http://127.0.0.1:$PORT/debug/caches" 2>/dev/null)
    TASK=$(field "$TJ" "pending_tracked")
    POOLS=$(field "$CJ" "media_sessions_pools")
    CONNS=$(field "$CJ" "media_sessions_total_conns")
    SEGMB=$(field "$CJ" "hls_seg_cache_bytes")
    [ -n "$SEGMB" ] && SEGMB=$((SEGMB / 1048576))

    printf '%s | up %5sh | rss %5s | fd %4s | sock %4s | thr %3s | ffm %2s | task %4s | pool %3s/%4s | seg %3sMB | load %5s | c443 %4s | conn %6s | skip %4s\n' \
        "$(date '+%F %H:%M')" "$UPH" "${RSS:-?}" "$FD" "$SOCK" "${THR:-?}" \
        "$FFM" "${TASK:-?}" "${POOLS:-?}" "${CONNS:-?}" "${SEGMB:-?}" \
        "$LOAD" "$C443" "$CONN" "$SKIP" >> "$OUT"

    sleep "$EVERY"
done
