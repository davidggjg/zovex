#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# update_all — כל מה שממתין, בפקודה אחת: הבוט, הפאנל והאתר.
#
# האפליקציה **אינה** כאן. ה-APK נבנה ב-GitHub Actions ולא על השרת, וזה
# מסלול נפרד — ראה בסוף.
#
# הסדר אינו שרירותי:
#   1. מוריד הכל ובודק שירד שלם
#   2. מריץ את הפאצ'ים על **עותקים**, בזה אחר זה — כי שניהם עורכים את
#      אותו main.py, ופאץ' שני חייב לראות את התוצאה של הראשון
#   3. רק אם כל הרצף עבר — מחיל באמת
#   4. מפעיל מחדש ובודק שהנקודות עונות. לא "השירות רץ" אלא "הוא עונה":
#      שירות שעלה ונפל בייבוא נראה active לרגע, וכך הופל האתר בעבר
#   5. נכשל? מחזיר את הגיבויים ומפעיל מחדש, ואומר את זה במפורש
#   6. האתר: מוחלף רק אחרי שהבוט בריא, ויש גיבוי לחזור אליו
#   7. מגבה את הקבצים החיים למאגר
#
#     bash update_all.sh --check     בדיקה יבשה בלבד, לא נוגע בכלום
#     bash update_all.sh             העדכון עצמו
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail
cd /opt/zovex-bot || { echo "❌ /opt/zovex-bot לא נמצא"; exit 1; }

BRANCH="claude/hls-relay-schema-port-ll8xiz"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/$BRANCH/vps-bot"
# איפה האתר באמת יושב — נשאל את nginx ולא נניח. פריסה לתיקייה שאיש
# אינו מגיש הייתה "מצליחה" בשקט ולא משנה כלום.
SITE_DIR=$(nginx -T 2>/dev/null | grep -E "^[[:space:]]*root[[:space:]]" \
           | awk '{print $2}' | tr -d ';' | grep -v "^/var/www/html$" \
           | head -1)
[ -n "${SITE_DIR:-}" ] || SITE_DIR="/opt/zovex-site"
DRY=0; [ "${1:-}" = "--check" ] && DRY=1

# פאצ'ים שעורכים main.py (ואחד גם את admin.html), לפי הסדר שבו הם מוחלים
PATCHES=(fix_panel_msg_read.py fix_upload_read_caption.py fix_content_cache.py fix_caption_title_cut.py fix_panel_pass_header.py)
# כלי אבחון — יורדים אבל לא מורצים
TOOLS=(who_is_watching.py vodinfo_probe.py)

echo "════════ 1/6 · מוריד ════════"
for f in "${PATCHES[@]}" "${TOOLS[@]}"; do
  if curl -fsSL -o "$f.new" "$RAW/$f" && python3 -c "import ast;ast.parse(open('$f.new',encoding='utf-8').read())"; then
    mv "$f.new" "$f"; echo "  ✓ $f"
  else
    rm -f "$f.new"; echo "  ✗ $f לא ירד או ירד פגום"; exit 1
  fi
done
if curl -fsSL -o /tmp/zovex-site.tgz "$RAW/site.tgz" && tar tzf /tmp/zovex-site.tgz >/dev/null 2>&1; then
  echo "  ✓ site.tgz ($(du -h /tmp/zovex-site.tgz | cut -f1))"
else
  echo "  ✗ site.tgz לא ירד או פגום"; exit 1
fi

echo
echo "════════ 2/6 · בדיקה יבשה על עותקים ════════"
SIM=$(mktemp -d); trap 'rm -rf "$SIM"' EXIT
cp main.py "$SIM/main.py"; cp admin.html "$SIM/admin.html"
APPLY=(); FAILED=0
for f in "${PATCHES[@]}"; do
  # מריצים בפועל על העותק, כדי שהבא בתור יראה את התוצאה של הקודם
  if out=$(MAIN_PY="$SIM/main.py" ADMIN_HTML="$SIM/admin.html" python3 "$f" 2>&1); then
    if echo "$out" | grep -q "כבר מותקן"; then echo "  ● $f — כבר מוחל"
    else echo "  ✓ $f"; APPLY+=("$f"); fi
  else
    echo "  ✗ $f — $(echo "$out" | tail -2 | head -1)"; FAILED=1
  fi
done
python3 -c "import ast;ast.parse(open('$SIM/main.py',encoding='utf-8').read())" \
  || { echo "  ✗ התוצאה המשולבת אינה עוברת קומפילציה"; FAILED=1; }
[ "$FAILED" -eq 1 ] && { echo; echo "❌ הרצף לא עבר. לא שונה כלום."; exit 1; }

if [ "$DRY" -eq 1 ]; then
  echo; echo "✓ הכל עבר על עותקים. לא שונה כלום (--check)."
  echo "  להחלה: ${#APPLY[@]} פאצ'ים + האתר"
  exit 0
fi

echo
echo "════════ 3/6 · מחיל על הבוט ════════"
cp main.py main.py.before_update_all
cp admin.html admin.html.before_update_all
if [ ${#APPLY[@]} -eq 0 ]; then
  echo "  אין מה להחיל — הכל כבר מוחל"
else
  for f in "${APPLY[@]}"; do
    if out=$(python3 "$f" 2>&1); then echo "  ✓ $f"
    else echo "  ✗ $f — $out"; FAILED=1; fi
  done
fi

echo
echo "════════ 4/6 · מפעיל מחדש ובודק ════════"
systemctl restart zovex-bot
UP=0
for i in $(seq 1 30); do
  sleep 2
  [ "$(curl -s -o /dev/null -m 5 -w '%{http_code}' http://127.0.0.1:8000/content/version)" = "200" ] \
    && { echo "  ✓ עונה אחרי $((i*2)) שניות"; UP=1; break; }
done
OK=$UP
chk() {  # שם  כתובת  "קוד|קוד"
  c=$(curl -s -o /dev/null -m 10 -w "%{http_code}" "$2")
  case "|$3|" in
    *"|$c|"*) echo "  ✓ $1 ($c)" ;;
    *) echo "  ✗ $1 — קיבלנו $c, ציפינו $3"; OK=0 ;;
  esac
}
if [ "$UP" -eq 1 ]; then
  chk "קטלוג"         "http://127.0.0.1:8000/content/version" 200
  chk "גרסת אפליקציה" "http://127.0.0.1:8000/app/version"     200
  # הנתיב החדש של סימון-נקרא: 422 = קיים וחסרים שדות. 404 = הפאץ' לא נכנס.
  chk "סימון הודעה כנקראה" "http://127.0.0.1:8000/feedback/read" "405|422"
else
  echo "  ✗ השירות לא ענה תוך דקה"
fi
# פאץ' שנכשל בהחלה הוא כישלון גם אם הבדיקות עברו: המצב על הדיסק כבר
# אינו מה שהבדיקה היבשה אישרה, ומשם לא ממשיכים.
[ "$FAILED" -eq 1 ] && OK=0

if [ "$OK" -ne 1 ]; then
  echo
  echo "════════ מחזיר אחורה ════════"
  cp main.py.before_update_all main.py
  cp admin.html.before_update_all admin.html
  systemctl restart zovex-bot
  sleep 6
  echo "  שוחזר. האתר **לא** נגעתי בו."
  echo "❌ העדכון בוטל. שלח לי את הפלט הזה."
  exit 1
fi

echo
echo "════════ 5/6 · מחליף את האתר ════════"
if [ -d "$SITE_DIR" ]; then
  rm -rf /opt/zovex-site.prev && cp -a "$SITE_DIR" /opt/zovex-site.prev
  echo "  גיבוי: /opt/zovex-site.prev"
fi
mkdir -p "$SITE_DIR"
find "$SITE_DIR" -mindepth 1 -delete 2>/dev/null
tar xzf /tmp/zovex-site.tgz -C "$SITE_DIR"
echo "  נפרס אל $SITE_DIR: $(find "$SITE_DIR" -type f | wc -l) קבצים"
sleep 1
# האם מה שנפרס הוא מה שמוגש? משווים את שם קובץ ה-JS שבחבילה למה שדף
# הבית החי מפנה אליו. שם הקובץ נושא גיבוב של התוכן, ולכן זו תשובה
# חד-משמעית — ולא "הדף ענה 200", שהיה עונה 200 גם מהאתר הישן.
BUNDLE=$(tar tzf /tmp/zovex-site.tgz | grep -m1 -E "^\./assets/index-.*\.js$" | sed "s#^\./##")
if [ -n "$BUNDLE" ]; then
  if curl -s -m 20 https://zovex.duckdns.org/ | grep -q "$BUNDLE"; then
    echo "  ✓ הדף החי מפנה אל $BUNDLE — זו באמת התיקייה שמוגשת"
  else
    echo "  ✗ הדף החי **לא** מפנה אל $BUNDLE."
    echo "    כלומר nginx מגיש תיקייה אחרת מ-$SITE_DIR. למצוא אותה:"
    echo "      nginx -T | grep -n \"root \""
    echo "    לא ממשיכים, והאתר הישן ממשיך לעבוד."
    exit 1
  fi
fi
SC=$(curl -s -o /dev/null -m 15 -w "%{http_code}" https://zovex.duckdns.org/)
SM=$(curl -s -o /dev/null -m 15 -w "%{http_code}" -L https://zovex.duckdns.org/sitemap.xml)
echo "  דף הבית: $SC   ·   sitemap: $SM"
if [ "$SC" != "200" ] && [ -d /opt/zovex-site.prev ]; then
  find "$SITE_DIR" -mindepth 1 -delete 2>/dev/null
  cp -a /opt/zovex-site.prev/. "$SITE_DIR"/
  echo "  ✗ האתר לא ענה 200 — הוחזר הקודם."
  exit 1
fi

echo
echo "════════ 6/6 · מגבה למאגר ════════"
# הסקריפט יושב ב-/root ולא ליד main.py, ולכן מחפשים אותו ולא מניחים.
# בלי הגיבוי הזה main.py ו-admin.html החיים לא מגיעים למאגר, והפאץ' הבא
# נכתב מול קובץ ישן — זה בדיוק מה ששבר פעם את כל מסלול /vh.
# סורק הסודות של הגיבוי עודכן בסקירת האבטחה: הוא לא הכיר את מפתחות
# Gemini/Google, api_hash, מחרוזות session וסיסמת פאנל — ובדיקת המפתח הפרטי
# שבו לא עבדה מעולם (grep קרא אותה כאופציה). מתקינים את החדש לפני שמריצים,
# אחרי בדיקת תחביר, ושומרים את הקודם.
if curl -fsSL -o /tmp/backup_to_git.sh.new "$RAW/backup_to_git.sh" \
   && bash -n /tmp/backup_to_git.sh.new 2>/dev/null \
   && grep -q "AQ" /tmp/backup_to_git.sh.new; then
  [ -f /root/backup_to_git.sh ] && cp /root/backup_to_git.sh /root/backup_to_git.sh.prev
  install -m 700 /tmp/backup_to_git.sh.new /root/backup_to_git.sh
  echo "  ✓ סורק הסודות עודכן (הקודם: /root/backup_to_git.sh.prev)"
else
  echo "  ⚠ לא הצלחתי לעדכן את סורק הסודות — ממשיך עם הקיים"
fi
rm -f /tmp/backup_to_git.sh.new

BK=""
for c in ./backup_to_git.sh /root/backup_to_git.sh /opt/backup_to_git.sh; do
  [ -f "$c" ] && { BK="$c"; break; }
done
[ -n "$BK" ] || BK=$(find /root /opt -maxdepth 3 -name backup_to_git.sh 2>/dev/null | head -1)
if [ -n "$BK" ]; then
  echo "  מריץ $BK"
  bash "$BK" 2>&1 | tail -4
else
  echo "  ⚠ backup_to_git.sh לא נמצא בשום מקום — הגיבוי למאגר לא רץ."
  echo "    למצוא:  find / -name backup_to_git.sh 2>/dev/null | head -3"
fi

echo
echo "✅ הבוט, הפאנל והאתר מעודכנים."
echo
echo "מה שנשאר בחוץ — האפליקציה:"
echo "  ה-APK נבנה ב-GitHub Actions, לא כאן. תגיד לי ואני אריץ את הבנייה,"
echo "  ואז תתקין את הקובץ שייצא ותבדוק על הטלוויזיה לפני שמפרסמים."
echo
echo "לבדוק שהעדכון תפס:"
echo "  • בפאנל: Ctrl+Shift+R, לפתוח שיחה עם 'חדש' — התג והספרה נעלמים,"
echo "    ולכל הודעה יש תאריך ושעה."
echo "  • בבוט: לשלוח קובץ עם כיתוב של ערוץ ושם קובץ חסר תועלת —"
echo "    ההודעה צריכה לחפש ב-TMDB לפי השם מהכיתוב."
echo
echo "לביטול, אם משהו התגלה אחר כך:"
echo "  cd /opt/zovex-bot"
echo "  python3 fix_upload_read_caption.py --revert"
echo "  python3 fix_panel_msg_read.py --revert"
echo "  systemctl restart zovex-bot"
echo "  rm -rf /opt/zovex-site && cp -a /opt/zovex-site.prev /opt/zovex-site"
