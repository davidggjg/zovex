#!/usr/bin/env bash
# forensic_verify.sh — מודד בפועל את ארבע הבעיות שהדוח החיצוני מצא.
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
SINCE="-${DAYS} days"
J=(journalctl -u zovex-bot --since "$SINCE" --no-pager -o cat)

hr() { printf '\n\033[1m%s\033[0m\n' "$1"; }
cnt() { grep -c -- "$1" <<<"$LOG" 2>/dev/null || echo 0; }

echo "אוסף יומן של $DAYS ימים..."
LOG="$("${J[@]}" 2>/dev/null)"
LINES=$(wc -l <<<"$LOG")
echo "נאספו $LINES שורות."

# ── P0-1: תשובה קצרה מה-Content-Length שהובטח ────────────────────────
hr "P0-1 · תשובה קצרה מהמובטח"
A=$(cnt "מוותר - התגובה תהיה קצרה מהמובטח")
B=$(cnt "מסיים את התשובה כדי שהנגן יבקש שוב")
C=$(cnt "חסרים")
D=$(cnt "Response content shorter than Content-Length")
echo "  ensure() נגמרו הנסיונות ............ $A"
echo "  חלון ויתר וסגר את התשובה .......... $B   ← זה ה-return שהדוח מצא"
echo "  stream_session_range חסרים בייטים .. $C"
echo "  RuntimeError של uvicorn בפועל ...... $D"
if [ "$B" -gt 0 ]; then
  echo "  --- דוגמאות אחרונות:"
  grep -- "מסיים את התשובה כדי שהנגן יבקש שוב" <<<"$LOG" | tail -3 | sed 's/^/      /'
fi

# ── P0-2: כשל upstream שמוחזר כ-200 ──────────────────────────────────
hr "P0-2 · segment של HLS שנכשל אבל יצא כ-200"
E=$(cnt "hls_relay")
F=$(grep -c -E "hls_relay.*(50[0-9]|40[0-9]|status)" <<<"$LOG" 2>/dev/null || echo 0)
echo "  שורות hls_relay בסך הכל ............ $E"
echo "  מהן עם קוד שגיאה של upstream ....... $F"
if [ "$F" -gt 0 ]; then
  grep -E "hls_relay.*(50[0-9]|40[0-9]|status)" <<<"$LOG" \
    | sed 's/.*hls_relay/hls_relay/' | sort | uniq -c | sort -rn | head -8 | sed 's/^/      /'
fi

# ── P0-3: כמה ערוצים באמת עוברים קידוד מחדש ──────────────────────────
hr "P0-3 · קידוד מחדש (libx264) — כמה ערוצים בפועל"
PROBE=$(grep -- "hls_codec:" <<<"$LOG" || true)
if [ -z "$PROBE" ]; then
  echo "  אין שורות hls_codec ביומן — אף ערוץ לא נבדק בתקופה הזאת."
  echo "  כלומר: אפס קידוד מחדש. הסעיף הזה לא P0 אצלנו כרגע."
else
  echo "  התפלגות קודקים של המקור (ערוץ יחיד נבדק פעם בשעה):"
  sed -n 's/.*קודק מקור \(.*\)$/\1/p' <<<"$PROBE" | sort | uniq -c | sort -rn | sed 's/^/      /'
  NH=$(sed -n 's/.*קודק מקור \(.*\)$/\1/p' <<<"$PROBE" | grep -vc -E "^(h264|לא ידוע)$" || echo 0)
  echo "  → ערוצים שדורשים libx264: $NH"
  if [ "$NH" -gt 0 ]; then
    echo "  --- אלה הערוצים:"
    grep -- "hls_codec:" <<<"$LOG" | grep -v -E "קודק מקור (h264|לא ידוע)" \
      | sed 's/.*hls_codec: //' | sort -u | head -20 | sed 's/^/      /'
  fi
fi

# ── P0-4: ffmpeg שמת ומאפס את מספור הסגמנטים ─────────────────────────
hr "P0-4 · ffmpeg מת → מספור סגמנטים מתאפס"
G=$(cnt "הנגן יראה קפיצה במספור")
echo "  מספר הפעמים שזה קרה בפועל .......... $G"
if [ "$G" -gt 0 ]; then
  echo "  --- לפי ערוץ:"
  grep -- "הנגן יראה קפיצה במספור" <<<"$LOG" \
    | sed -n 's/.*ffmpeg של \([^ ]*\) מת.*/\1/p' | sort | uniq -c | sort -rn | head -10 | sed 's/^/      /'
fi

# ── הבעיה שהדוח לא יכול היה לראות: sessions דולפים ───────────────────
hr "בקרה · דליפת sessions (מה שתיקנו) — לוודא שזה עדיין 0"
T=$(journalctl -u zovex-bot --since "-30 min" --no-pager -o cat 2>/dev/null \
    | grep -oE "[0-9]{1,3}(\.[0-9]{1,3}){3}:[0-9]+" | sort -u | wc -l)
HC=$(journalctl -u zovex-bot --since "-30 min" --no-pager -o cat 2>/dev/null \
    | grep -c "handler is closed" || echo 0)
echo "  כתובות transport שונות ב-30 דק' .... $T   (היה 90 לפני התיקון, אמור להיות 0-4)"
echo "  שורות 'handler is closed' ב-30 דק' .. $HC  (היה ~32,000)"

# ── מצב השירות ────────────────────────────────────────────────────────
hr "מצב"
systemctl show zovex-bot -p ActiveEnterTimestamp --value | sed 's/^/  רץ מאז: /'
systemctl is-active zovex-bot | sed 's/^/  מצב: /'
echo
echo "סיום. שלח לי את כל הפלט הזה."
