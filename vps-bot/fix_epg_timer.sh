#!/bin/bash
# מתקן את הטיימר של לוח השידורים, שנתקע במצב "elapsed" ולא ירה 4 ימים.
#
# ## מה היה
#
#   [Timer]
#   OnBootSec=2min
#   OnUnitActiveSec=2h
#   Persistent=true
#
# שני זמנים **יחסיים** בלבד. `OnUnitActiveSec` מחשב את הירייה הבאה מתוך
# ההפעלה האחרונה של השירות — וברגע שנקודת הייחוס הזאת אובדת (reload של
# systemd, אתחול, או ריצה שלא הסתיימה כרגיל) אין ממה לחשב, והטיימר נכנס
# ל-`active (elapsed)` עם `Trigger: n/a`. הוא נשאר enabled וירוק ב-status,
# ופשוט לא יורה יותר לעולם. זו תקלה שקטה לחלוטין.
#
# ו-`Persistent=true` לא הציל, כי הוא משפיע רק על `OnCalendar`. עם טיימר
# מונוטוני הוא מתעלם ממנו.
#
# בפועל: הטיימר מת ב-03/09 17:17, הלוח קפא, ובאתר ובאפליקציה זה נראה כמו
# "אין לוח שידורים" — עד שחיפשנו קוד שנדרס, שלא היה קיים.
#
# ## מה במקום
#
# `OnCalendar` הוא נקודת זמן **מוחלטת**: היא תמיד מתחדשת, בלי תלות בריצה
# הקודמת ובלי נקודת ייחוס שאפשר לאבד. `Persistent=true` כאן כן עובד, ולכן
# ריצה שהוחמצה בזמן שהשרת היה כבוי מושלמת מיד עם העלייה.
#
# כל שעה ולא כל שעתיים, ובכוונה: נמדד שוואלה מתחלפת ללוח היום אי-שם בין
# 06:00 ל-06:20 בבוקר, ובנייה שנופלת בדיוק בחלון הזה מוציאה 47 ערוצים
# ריקים (נתפס בפועל ב-07/09). ריצה כל שעה מקצרת את החשיפה לחצי.
#
# RandomizedDelaySec מפזר את הירייה בתוך הדקות הראשונות, כדי שלא ניפול
# בכל פעם על אותה שנייה בדיוק מול המקורות.
#
#     bash fix_epg_timer.sh --check    # מראה ולא משנה
#     bash fix_epg_timer.sh            # מחיל, עם גיבוי
#     bash fix_epg_timer.sh --revert   # מחזיר
set -euo pipefail

UNIT=/etc/systemd/system/zovex-epg.timer
BAK="$UNIT.bak-$(date +%Y%m%d-%H%M%S)"

NEW='[Unit]
Description=Refresh ZOVEX EPG hourly

[Timer]
# נקודת זמן מוחלטת. הגרסה הקודמת השתמשה ב-OnUnitActiveSec, שמחשב מתוך
# ההפעלה האחרונה — וברגע שנקודת הייחוס אבדה הטיימר נתקע ב-elapsed ולא
# ירה יותר, בלי שום סימן ב-status.
OnCalendar=*-*-* *:07:00
# מפזר בתוך חמש דקות, כדי לא לפגוע באותה שנייה בכל פעם.
RandomizedDelaySec=5min
# משלים ריצה שהוחמצה בזמן שהשרת היה כבוי. עובד רק עם OnCalendar — בטיימר
# מונוטוני, כמו שהיה כאן, systemd מתעלם ממנו.
Persistent=true
AccuracySec=1min

[Install]
WantedBy=timers.target'

if [[ "${1:-}" == "--revert" ]]; then
  last=$(ls -1t "$UNIT".bak-* 2>/dev/null | head -1 || true)
  [[ -z "$last" ]] && { echo "❌ לא נמצא גיבוי"; exit 1; }
  cp -- "$last" "$UNIT"
  systemctl daemon-reload
  systemctl restart zovex-epg.timer
  echo "✓ שוחזר מ-$(basename "$last")"
  systemctl status zovex-epg.timer --no-pager | sed -n '1,6p'
  exit 0
fi

if [[ "${1:-}" == "--check" ]]; then
  echo "── מה שיש עכשיו ──"; cat "$UNIT"
  echo; echo "── מה שייכתב ──"; echo "$NEW"
  echo; echo "(--check — לא שונה כלום)"
  exit 0
fi

cp -- "$UNIT" "$BAK"
printf '%s\n' "$NEW" > "$UNIT"
systemctl daemon-reload
systemctl restart zovex-epg.timer

echo "✓ הוחל. גיבוי: $(basename "$BAK")"
echo
systemctl status zovex-epg.timer --no-pager | sed -n '1,6p'
echo
echo "── הירייה הבאה ──"
systemctl list-timers zovex-epg.timer --no-pager
echo
echo 'אם NEXT עדיין n/a — משהו לא נקלט, תגיד לי.'
