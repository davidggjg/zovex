#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · ניקוי הקטלוג מכפילויות וקטגוריות שגויות.
#
# מוריד את catalog_fix.py לשרת ומריץ אותו. **ברירת המחדל היא הדמיה**:
# בלי --apply שום דבר לא נכתב, ורק מוצג מה היה קורה.
#
#   sudo bash deploy_catalog_fix.sh            # הדמיה
#   sudo bash deploy_catalog_fix.sh --apply    # ביצוע, אחרי גיבוי
#   sudo bash deploy_catalog_fix.sh --restore  # חזרה לגיבוי האחרון
#
# נמדד על עותק של הקטלוג החי (26,502 פריטים): 505 כפילויות ו-107
# תיקוני קטגוריה — הסרה של 1.9%.
# ─────────────────────────────────────────────────────────────────────────────
set -u
DIR=/opt/zovex-bot
BRANCH="claude/telegram-bots-video-freezing-m8rk0n"
RAW="https://raw.githubusercontent.com/davidggjg/zovex/${BRANCH}/vps-bot/catalog_fix.py?t=$(date +%s)"
die() { echo "❌ $*" >&2; exit 1; }

[ -d "$DIR" ] || die "$DIR לא קיים — זה לא שרת ZOVEX"

echo "① מוריד את הסקריפט"
curl -fsSL -H 'Cache-Control: no-cache' "$RAW" -o "$DIR/catalog_fix.py" || die "ההורדה נכשלה"
python3 -m py_compile "$DIR/catalog_fix.py" || die "הקוד לא מתקמפל"

DD=$(grep -m1 '^DATA_DIR=' "$DIR/.env" 2>/dev/null | cut -d= -f2-); DD="${DD:-$DIR/data}"
[ -f "$DD/content.json" ] || die "$DD/content.json לא נמצא"
echo "   קטלוג: $DD/content.json"

echo "② מריץ"
DATA_DIR="$DD" python3 "$DIR/catalog_fix.py" "$@" || die "הריצה נכשלה"

case " $* " in
  *" --apply "*)
    echo
    echo "③ מוודא שהשרת מגיש את הקטלוג החדש"
    sleep 2
    V=$(curl -fsS -m 20 http://127.0.0.1:8000/content/version | tr -dc '0-9')
    N=$(curl -fsS -m 120 http://127.0.0.1:8000/content/lite | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))')
    echo "   גרסת תוכן: $V · פריטים שמוגשים: $N"
    echo
    echo "✅ בוצע. הדוח המלא: $DD/catalog_fix_report.csv"
    echo "   לחזרה:  sudo bash $0 --restore"
    echo
    echo "   באפליקציה ובאתר השינוי מופיע מעצמו — מונה הגרסה קודם."
    ;;
esac
