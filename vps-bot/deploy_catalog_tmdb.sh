#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · השלמת פוסטרים והעברת תוכן ישראלי לקטגוריה שלו, לפי TMDB.
#
# **ברירת המחדל היא הדמיה.** בלי --apply שום דבר לא נכתב.
#
#   sudo bash deploy_catalog_tmdb.sh --posters --israeli
#   sudo bash deploy_catalog_tmdb.sh --posters --israeli --apply
#   sudo bash deploy_catalog_tmdb.sh --restore
#
# נמדד על הקטלוג החי: 1,294 פריטים בלי פוסטר, 1,271 מהם פרקים של 37
# סדרות בלבד — כ-60 קריאות ל-TMDB ולא 1,294. בדיקת המקור הישראלי
# נוגעת ב-9,109 פריטים דרך 1,873 מזהים ייחודיים.
# ─────────────────────────────────────────────────────────────────────────────
set -u
DIR=/opt/zovex-bot
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/catalog_tmdb.py?t=$(date +%s)"
die() { echo "❌ $*" >&2; exit 1; }

[ -d "$DIR" ] || die "$DIR לא קיים — זה לא שרת ZOVEX"
grep -q '^TMDB_API_KEY=.\+' "$DIR/.env" 2>/dev/null \
  || die "TMDB_API_KEY חסר ב-$DIR/.env — בלעדיו אין מה למשוך"

echo "① מוריד את הסקריפט"
curl -fsSL -H 'Cache-Control: no-cache' "$RAW" -o "$DIR/catalog_tmdb.py" || die "ההורדה נכשלה"
python3 -m py_compile "$DIR/catalog_tmdb.py" || die "הקוד לא מתקמפל"

DD=$(grep -m1 '^DATA_DIR=' "$DIR/.env" 2>/dev/null | cut -d= -f2-); DD="${DD:-$DIR/data}"
[ -f "$DD/content.json" ] || die "$DD/content.json לא נמצא"

echo "② מריץ (זה לוקח כמה דקות — יש אלפי קריאות ל-TMDB בפעם הראשונה)"
DATA_DIR="$DD" python3 "$DIR/catalog_tmdb.py" "$@" || die "הריצה נכשלה"

case " $* " in
  *" --apply "*|*" --restore "*)
    echo
    echo "③ מוודא שהשרת מגיש את הקטלוג החדש"
    sleep 2
    V=$(curl -fsS -m 20 http://127.0.0.1:8000/content/version | tr -dc '0-9')
    N=$(curl -fsS -m 120 http://127.0.0.1:8000/content/lite \
        | python3 -c 'import json,sys;a=json.load(sys.stdin);print("%d פריטים, %d בלי פוסטר"%(len(a),sum(1 for i in a if not (i.get("thumbnail_url") or "").strip())))')
    echo "   גרסת תוכן: $V · $N"
    echo
    echo "   הדוח המלא: $DD/catalog_tmdb_report.csv"
    echo "   לחזרה:  sudo bash $0 --restore"
    ;;
esac
