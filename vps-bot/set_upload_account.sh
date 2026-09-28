#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# set_upload_account — קובע לאיזה חשבון טלגרם ההעלאה מהטלפון מגיעה.
#
#     bash set_upload_account.sh 123456789
#     bash set_upload_account.sh            ← מראה מה מוגדר עכשיו, לא משנה
#
# **מזהה ולא שם משתמש.** שם משתמש הוא תווית שאפשר להחליף בשתי לחיצות,
# והחלפה אחת כזאת כבר ניתקה כאן את ההעלאה בלי שאיש נגע בקוד או בהגדרות.
# המזהה אינו משתנה לעולם. את המזהה מקבלים מ-check_userbot.py (סעיף 2).
#
# ## למה זה סקריפט ולא שורת sed
#
# ההגדרה לא בהכרח יושבת ב-/opt/zovex-bot/.env. היא יכולה לשבת ב-
# Environment= של יחידת systemd, ב-EnvironmentFile אחר, או ב-drop-in —
# ומי שיערוך את הקובץ הלא נכון יראה "שיניתי ולא קרה כלום", כי המקור
# האמיתי דורס אותו. לכן **שואלים את systemd** איפה ההגדרות שלו.
#
# וחיפוש ב-grep -r על התיקייה אינו תחליף: main.py, check_userbot.py
# ו-fix_saved_userbot.py כולם מזכירים את השם, וחיפוש כזה היה "מוצא"
# אותם ועורך קוד.
#
# אם ההגדרה יושבת בשני מקומות — לא נוגע בכלום ואומר את זה. שני מקורות
# שאחד דורס את השני הם בדיוק המצב שבו תיקון עיוור מבלבל עוד יותר.
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail

SVC=${BOT_SERVICE:-zovex-bot}
ENVDEF=${BOT_ENV:-/opt/zovex-bot/.env}
ID=${1:-}

if [ -n "$ID" ] && ! printf '%s' "$ID" | grep -qE '^[0-9]{5,}$'; then
  echo "✗ '$ID' אינו מזהה. מזהה הוא מספר בן 5 ספרות ומעלה."
  echo "  להשיג אותו:  python3 /opt/zovex-bot/check_userbot.py   (סעיף 2)"
  exit 1
fi

# ── איפה systemd מחזיק את ההגדרות ────────────────────────────────────────
U=$(systemctl show "$SVC" -p FragmentPath --value 2>/dev/null)
D=$(systemctl show "$SVC" -p DropInPaths --value 2>/dev/null)
E=$(systemctl show "$SVC" -p EnvironmentFiles --value 2>/dev/null \
    | tr ' ' '\n' | sed 's/^-//' | grep '^/')
CAND=$(printf '%s\n%s\n%s\n%s\n' "$U" "$D" "$E" "$ENVDEF" \
       | tr ' ' '\n' | grep '^/' | sort -u)

M=""
for f in $CAND; do
  [ -f "$f" ] && grep -q "SAVED_UPLOAD_USER" "$f" && M="$M$f
"
done
M=$(printf '%s' "$M" | grep . || true)
N=$(printf '%s' "$M" | grep -c . || true)

echo "קבצי ההגדרה של $SVC:"
for f in $CAND; do
  [ -f "$f" ] && echo "  $f" || echo "  $f  (לא קיים)"
done
echo

# ── מה מוגדר כרגע, מהתהליך החי ──────────────────────────────────────────
PID=$(systemctl show "$SVC" -p MainPID --value 2>/dev/null)
CUR=""
# ‎[ -r ]‎ ולא רק ‎2>/dev/null‎: ההפניה ‎< file‎ נכשלת בקליפה עצמה לפני
# ש-tr רץ, ולכן ההפניה של שגיאות tr אינה משתיקה אותה.
if [ -r "/proc/$PID/environ" ]; then
  CUR=$(tr '\0' '\n' < "/proc/$PID/environ" \
        | grep '^SAVED_UPLOAD_USER=' | cut -d= -f2- || true)
fi
echo "בתהליך החי כרגע: ${CUR:-(לא מוגדר — נבחר החשבון הראשון שעלה)}"

if [ -z "$ID" ]; then
  echo
  echo "לא נמסר מזהה — לא שיניתי כלום."
  echo "לקביעה:  bash $0 <מזהה>"
  exit 0
fi

if [ "$N" -gt 1 ]; then
  echo
  echo "⚠️ ההגדרה יושבת ביותר ממקום אחד, ואחד דורס את השני:"
  printf '  %s\n' $M
  echo "לא נגעתי בכלום. תמחק ידנית מכל המקומות חוץ מאחד, והרץ שוב."
  exit 1
fi

if [ "$N" -eq 1 ]; then
  F="$M"
  cp "$F" "$F.bak_saveduser"
  # ההחלפה אינה תלויה בצורה שבה השורה נכתבה, כי systemd מקבל את כולן:
  #
  #     Environment="SAVED_UPLOAD_USER=x"     גרשיים מסביב לזוג כולו
  #     Environment=SAVED_UPLOAD_USER=x       בלי גרשיים  ← זו שנכשלה
  #     SAVED_UPLOAD_USER=x                   קובץ סביבה
  #     SAVED_UPLOAD_USER="x"                 קובץ סביבה, ערך בגרשיים
  #
  # הגרסה הקודמת דרשה גרשיים מיד אחרי ‎Environment=‎, או שורה שמתחילה
  # במפתח. הצורה השנייה אינה אף אחת מהן, sed לא התאים כלום ויצא 0 —
  # והסקריפט הדפיס "✓ עודכן" על קובץ שלא נגע בו.
  #
  # שני כללים לפי הסדר: ערך שעטוף בגרשיים משלו, ואז ערך חשוף שנעצר
  # בגרש, ברווח או בסוף שורה.
  sed -i -E -e "s#(SAVED_UPLOAD_USER=)([\"'])[^\"']*\2#\1$ID#g" \
            -e "s#(SAVED_UPLOAD_USER=)[^\"'[:space:]]*#\1$ID#g" "$F"
  # sed יוצא 0 גם כשלא התאים כלום, ולכן "עודכן" נאמר רק אם הקובץ
  # באמת השתנה. דיווח הצלחה על שינוי שלא קרה גרוע מכישלון.
  if cmp -s "$F" "$F.bak_saveduser"; then
    # "לא השתנה" הוא גם מה שקורה כשהערך כבר נכון — וזו הצלחה, לא
    # כישלון. מבדילים לפי מה שכתוב בקובץ בפועל.
    if grep -qE "SAVED_UPLOAD_USER=[\"']?$ID([\"']|\$|[[:space:]])" "$F"; then
      echo
      echo "✓ כבר מוגדר נכון ב-$F"
      rm -f "$F.bak_saveduser"
    else
      echo
      echo "✗ הקובץ לא השתנה — לא זיהיתי את צורת השורה:"
      grep -n "SAVED_UPLOAD_USER" "$F" | sed 's/^/    /'
      echo "  לא נגעתי בכלום. שלח לי את השורה הזאת."
      rm -f "$F.bak_saveduser"
      exit 1
    fi
  else
    echo
    echo "✓ עודכן: $F"
    grep -n "SAVED_UPLOAD_USER" "$F" | sed 's/^/    /'
    echo "  גיבוי: $F.bak_saveduser"
  fi
  case "$F" in *.service|*.conf) systemctl daemon-reload ;; esac
else
  F="$ENVDEF"
  printf 'SAVED_UPLOAD_USER=%s\n' "$ID" >> "$F"
  echo
  echo "✓ לא היה מוגדר בשום מקום — נוסף ל-$F"
fi

echo
echo "מפעיל מחדש…"
systemctl restart "$SVC"
sleep 8

# ── ואימות מהתהליך, ולא מהקובץ: הקובץ הוא מה שביקשנו, התהליך הוא מה שיש
PID=$(systemctl show "$SVC" -p MainPID --value 2>/dev/null)
NEW=""
if [ -r "/proc/$PID/environ" ]; then
  NEW=$(tr '\0' '\n' < "/proc/$PID/environ" \
        | grep '^SAVED_UPLOAD_USER=' | cut -d= -f2- || true)
fi
if [ "$NEW" = "$ID" ]; then
  echo "✓ התהליך החי קיבל: SAVED_UPLOAD_USER=$NEW"
  echo
  echo "נסה להעלות מהטלפון. ההודעה האדומה צריכה להיעלם."
else
  echo "✗ התהליך קיבל '${NEW:-כלום}' ולא '$ID'."
  echo "  כלומר ההגדרה מגיעה ממקום שלא זוהה כאן. שלח לי את הפלט הזה."
  exit 1
fi
