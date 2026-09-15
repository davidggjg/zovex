#!/usr/bin/env bash
# forensic_verify.sh — מודד בפועל את ארבע הבעיות שהדוחות החיצוניים מצאו.
#
# קריאה בלבד: אין restart, אין reload, אין כתיבה לאף קובץ של המערכת.
# אפשר להריץ באמצע צפייה של מישהו בלי שיקרה כלום.
#
#   bash forensic_verify.sh          # 7 ימים אחרונים
#   bash forensic_verify.sh 2        # יומיים אחרונים
#
# המטרה: להפוך "P0 קריטי" למספר. בעיה שלא קרתה אף פעם ב-7 ימים
# אינה באותה עדיפות של בעיה שקורית 40 פעם ביום.

set -uo pipefail
DAYS="${1:-7}"

hr() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# grep -c מדפיס 0 *וגם* מחזיר קוד יציאה 1 כשאין התאמה. `|| echo 0` היה
# מוסיף אפס שני והמשתנה היה מקבל "0\n0" — כל השוואה מספרית אחר כך נשברת.
# לכן רק מסתירים את קוד היציאה ונותנים ל-grep להדפיס את המספר שלו.
cnt() { grep -c -F -- "$1" <<<"$LOG" || true; }
cnte() { grep -c -E -- "$1" <<<"$LOG" || true; }

echo "אוסף יומן של $DAYS ימים..."
LOG="$(journalctl -u zovex-bot --since "${DAYS} days ago" --no-pager -o short-iso 2>/dev/null)"
if [ -z "$LOG" ]; then
  echo "⚠ היומן ריק. אולי השירות בשם אחר, או ש-journald לא שומר כל כך אחורה."
  echo "  בדוק:  journalctl -u zovex-bot --no-pager -n 5"
  exit 1
fi
echo "נאספו $(wc -l <<<"$LOG") שורות."

# ── P0-1: תשובה קצרה מה-Content-Length שהובטח ────────────────────────
hr "P0-1 · תשובה קצרה מהמובטח"
A=$(cnt "מוותר - התגובה תהיה קצרה מהמובטח")
B=$(cnt "מסיים את התשובה כדי")
C=$(cnt "מנתק כדי שהנגן יבקש שוב")
D=$(cnt "Response content shorter than Content-Length")
echo "  ensure() נגמרו הנסיונות ............ $A"
echo "  חלון ויתר וסגר את התשובה .......... $B   ← זה ה-return שהדוח מצא"
echo "  stream_session_range חסרים בייטים .. $C"
echo "  RuntimeError של uvicorn בפועל ...... $D"
if [ "${B:-0}" -gt 0 ]; then
  echo "  --- שלוש אחרונות:"
  grep -F -- "מסיים את התשובה כדי" <<<"$LOG" | tail -3 | cut -c1-160 | sed 's/^/      /'
fi

# ── P0-2: כשל upstream שמוחזר כ-200 ──────────────────────────────────
hr "P0-2 · segment של HLS שנכשל אבל יצא כ-200"
E=$(cnt "hls_relay")
F=$(cnte "hls_relay.*(50[0-9]|40[0-9])")
echo "  שורות hls_relay בסך הכל ............ $E"
echo "  מהן עם קוד שגיאה של upstream ....... $F"
if [ "${F:-0}" -gt 0 ]; then
  grep -E -- "hls_relay.*(50[0-9]|40[0-9])" <<<"$LOG" \
    | sed 's/.*hls_relay/hls_relay/' | cut -c1-110 \
    | sort | uniq -c | sort -rn | head -8 | sed 's/^/      /'
fi

# ── P0-3: כמה ערוצים באמת עוברים קידוד מחדש ──────────────────────────
hr "P0-3 · קידוד מחדש (libx264) — כמה ערוצים בפועל"
PROBE="$(grep -F -- "hls_codec:" <<<"$LOG" || true)"
if [ -z "$PROBE" ]; then
  echo "  אין שורות hls_codec ביומן — אף ערוץ לא נבדק בתקופה הזאת."
  echo "  כלומר: אפס קידוד מחדש בפועל. הסעיף הזה אינו P0 אצלנו כרגע."
else
  echo "  התפלגות קודקים של המקור (כל ערוץ נבדק פעם בשעה):"
  sed -n 's/.*קודק מקור //p' <<<"$PROBE" | sort | uniq -c | sort -rn | sed 's/^/      /'
  NH=$(sed -n 's/.*קודק מקור //p' <<<"$PROBE" | grep -vc -E "^(h264|לא ידוע)$" || true)
  echo "  → ערוצים שדורשים libx264: ${NH:-0}"
  if [ "${NH:-0}" -gt 0 ]; then
    echo "  --- אלה הערוצים:"
    grep -F -- "hls_codec:" <<<"$LOG" | grep -v -E "קודק מקור (h264|לא ידוע)" \
      | sed 's/.*hls_codec: //' | sort -u | head -20 | sed 's/^/      /'
  fi
fi

# ── P0-4: ffmpeg שמת ומאפס את מספור הסגמנטים ─────────────────────────
hr "P0-4 · ffmpeg מת → מספור סגמנטים מתאפס"
G=$(cnt "הנגן יראה קפיצה במספור")
echo "  מספר הפעמים שזה קרה בפועל .......... $G"
if [ "${G:-0}" -gt 0 ]; then
  echo "  --- לפי ערוץ:"
  grep -F -- "הנגן יראה קפיצה במספור" <<<"$LOG" \
    | sed -n 's/.*ffmpeg של \([^ ]*\) מת.*/\1/p' \
    | sort | uniq -c | sort -rn | head -10 | sed 's/^/      /'
fi

# ── בקרה: דליפת ה-sessions שתיקנו — לוודא שזה עדיין 0 ────────────────
hr "בקרה · דליפת sessions (מה שתיקנו)"
RECENT="$(journalctl -u zovex-bot --since "30 min ago" --no-pager -o cat 2>/dev/null || true)"
T=$(grep -oE "[0-9]{1,3}(\.[0-9]{1,3}){3}:[0-9]+" <<<"$RECENT" | sort -u | wc -l)
HC=$(grep -c -F -- "handler is closed" <<<"$RECENT" || true)
echo "  כתובות transport שונות ב-30 דק' .... $T    (היה 90 לפני התיקון)"
echo "  שורות 'handler is closed' ב-30 דק' .. ${HC:-0}   (היה ~32,000)"

# ── מצב השירות ────────────────────────────────────────────────────────
hr "מצב"
echo "  רץ מאז: $(systemctl show zovex-bot -p ActiveEnterTimestamp --value)"
echo "  מצב:    $(systemctl is-active zovex-bot)"
echo
echo "סיום. שלח לי את כל הפלט הזה."
