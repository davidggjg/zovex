#!/bin/bash
# trace_channel — מה הדפדפן באמת מקבל לערוץ, בלי לפתוח devtools.
#
# ## למה
#
# "עובד באפליקציה ולא באתר" יכול להיות שלושה דברים שונים: השרת אינו
# מגיש, השרת מפנה למסלול ההמרה והוא נופל, או שהשרת תקין והבעיה בנגן.
# שלוש פעולות שונות לגמרי, ואי אפשר להבדיל ביניהן בלי לראות את שרשרת
# התשובות.
#
# הסקריפט שולף את הכתובת של הערוץ מהקטלוג (לא מעתיקים כתובות ביד),
# מבקש אותה עם User-Agent של דפדפן, עוקב אחרי הפניות, ומדפיס את
# השרשרת, את הגוף ואת מספר המקטעים.
#
# ההחלטה על ‎_fix‎ היא צד-שרת ואינה תלויה בלקוח, ולכן curl רואה בדיוק
# את מה שהדפדפן רואה — נבדק ב-‎_hls_autofix_wanted‎, שאינו קורא
# User-Agent בכלל.
#
#     bash trace_channel.sh "ספורט 2"
#     bash trace_channel.sh "ילדים"
#
# הפלט ממוסך: מארח ואסימונים אינם מודפסים. קריאה בלבד.
set -u
NAME="${1:-}"
[ -z "$NAME" ] && { echo 'שימוש: bash trace_channel.sh "שם הערוץ"'; exit 1; }
cd /opt/zovex-bot 2>/dev/null || true

U=$(NAME="$NAME" python3 - <<'PY'
import json, os, subprocess, sys
want = os.environ["NAME"].strip()
r = subprocess.run(["curl", "-sS", "--noproxy", "127.0.0.1", "--max-time",
                    "180", "http://127.0.0.1:8000/content"],
                   capture_output=True)
try:
    items = json.loads(r.stdout)
except Exception:
    sys.exit("")
items = items if isinstance(items, list) else items.get("movies", [])
exact = [e for e in items if (e.get("title") or "").strip() == want]
part = [e for e in items if want in (e.get("title") or "")]
hit = (exact or part)
if hit:
    print((hit[0].get("video_url") or "").strip())
PY
)

if [ -z "$U" ]; then
  echo "לא נמצא ערוץ בשם \"$NAME\". שמות קיימים:"
  curl -sS --noproxy 127.0.0.1 --max-time 180 http://127.0.0.1:8000/content \
    | python3 -c "
import json,sys
d=json.load(sys.stdin); d=d if isinstance(d,list) else d.get('movies',[])
for e in [x for x in d if x.get('is_live')][:12]: print('   ', (e.get('title') or '')[:40])"
  exit 1
fi

MASK='s#/hls-relay/(_fix/)?[^/ ]+#/hls-relay/\1<ספק>#g; s#[A-Za-z0-9]{12,}#<אסימון>#g'
echo "הכתובת מהקטלוג:"
echo "  $(echo "$U" | sed -E "$MASK")"
echo
echo "שרשרת התשובות (User-Agent של דפדפן):"
curl -sS -o /tmp/_tc_body -D /tmp/_tc_hdr -L \
  -w '  סופי: %{http_code} · %{num_redirects} הפניות · %{time_total}ש\n' \
  -A 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36' \
  --max-time 45 "$U" 2>&1 | tail -2

grep -iE '^(HTTP/|location:)' /tmp/_tc_hdr 2>/dev/null \
  | sed -E "$MASK" | sed 's/^/  /' | head -10

echo
echo "גוף התשובה:"
head -c 220 /tmp/_tc_body 2>/dev/null | sed -E "s#[A-Za-z0-9]{12,}#<אסימון>#g" | sed 's/^/  /'
echo
SEGS=$(grep -c '^#EXTINF' /tmp/_tc_body 2>/dev/null || echo 0)
FIX=$(grep -ciE 'location:.*_fix' /tmp/_tc_hdr 2>/dev/null || echo 0)
echo
echo "מקטעים: $SEGS   ·   הפניה ל-_fix: $([ "$FIX" -gt 0 ] && echo כן || echo לא)"
if [ "$SEGS" -gt 0 ]; then
  echo "⇒ ✓ השרת מגיש playlist תקין לדפדפן."
  echo "  כלומר הבעיה אינה בשרת ואינה בהפניה — היא בנגן של האתר."
  echo "  מה שצריך עכשיו הוא שורת השגיאה מה-Console."
else
  echo "⇒ ✗ השרת אינו מגיש playlist."
  echo "  זה אצלנו, והשרשרת למעלה אומרת איפה בדיוק."
fi
