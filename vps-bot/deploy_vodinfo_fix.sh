#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · תיקון זיהוי קבצים שהדפדפן אינו מפענח.
#
# דיווח: "החממה" — לא רואים טוב, ובלי סאונד.
#
# נמדד ישירות על הקבצים בשרת: כל שלוש העונות הן DivX/XviD בתוך MP4,
# 624x352, קול MP3. דפדפנים אינם מפענחים MPEG-4 Part 2, ולכן הצופה
# מקבל תמונה שבורה ובלי קול.
#
# לשרת יש המרה (/vt) והיא עובדת. מה שלא עבד הוא ה**זיהוי** — שני
# באגים נפרדים:
#
#   1. nginx אינו מעביר /vodinfo לשרת, והוא מחזיר את דף הבית.
#   2. גם אם היה מעביר: המסלול של MP4 ב-/vodinfo אינו מחזיר
#      browser_ok, והאתר בודק בדיוק אותו.
#
#   sudo bash deploy_vodinfo_fix.sh
#   sudo bash deploy_vodinfo_fix.sh --rollback
# ─────────────────────────────────────────────────────────────────────────────
set -u
DIR=/opt/zovex-bot
# ZOVEX_REF מאפשר להצמיד לקומיט מסוים. raw.githubusercontent מגיש
# מהמטמון גם כש-?t= משתנה, ושם של ענף תמיד עלול להיות ישן; מזהה
# קומיט הוא קבוע ולכן לעולם אינו מוגש מגרסה אחרת.
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
B="https://raw.githubusercontent.com/davidggjg/zovex/${REF}/vps-bot"
T=$(date +%s)
die() { echo "❌ $*" >&2; exit 1; }
[ -f "$DIR/main.py" ] || die "$DIR/main.py לא קיים"

curl -fsSL -H 'Cache-Control: no-cache' "$B/patch_vodinfo_browser_ok.py?t=$T" -o /tmp/p_vb.py || die "הורדה נכשלה"
curl -fsSL -H 'Cache-Control: no-cache' "$B/fix_nginx_vodinfo.sh?t=$T" -o /tmp/p_ng.sh || die "הורדה נכשלה"
# אימות שמה שהורד הוא אכן הגרסה המתוקנת ולא עותק ישן מהמטמון.
grep -q 'grep -RlE' /tmp/p_ng.sh \
  || die "הקובץ שהתקבל הוא גרסה ישנה (מטמון). הרץ שוב עם ZOVEX_REF=<sha>"

if [ "${1:-}" = "--rollback" ]; then
  python3 /tmp/p_vb.py "$DIR/main.py" --revert
  bash /tmp/p_ng.sh --remove
  systemctl restart zovex-bot
  echo "✅ שוחזר"
  exit 0
fi

echo "① nginx: ניתוב /vodinfo"
if ! bash /tmp/p_ng.sh; then
  echo
  echo "— אבחון, כדי שלא נישאר בלי מידע —"
  echo "קבצי nginx:"
  ls -l /etc/nginx/sites-enabled /etc/nginx/conf.d 2>/dev/null | sed 's/^/   /'
  echo "קבצים שמזכירים zovex:"
  grep -Rl zovex /etc/nginx/ 2>/dev/null | sed 's/^/   /'
  echo "שורות root ו-location:"
  for f in $(grep -Rl zovex /etc/nginx/ 2>/dev/null | head -2); do
    echo "   == $f"; grep -nE 'root|server_name|location' "$f" | sed 's/^/     /'
  done
  die "תיקון nginx נכשל — שלח לי את האבחון שלמעלה"
fi

echo "② main.py: החזרת browser_ok"
python3 /tmp/p_vb.py "$DIR/main.py" || die "הטלאי נכשל"

echo "③ מפעיל מחדש את השרת"
systemctl restart zovex-bot || die "ההפעלה מחדש נכשלה"
sleep 8
systemctl is-active --quiet zovex-bot || { journalctl -u zovex-bot -n 30 --no-pager; die "השרת אינו פעיל"; }

echo "④ בדיקה"
CT=$(curl -s -o /tmp/vi.json -w '%{content_type}' -m 90 "http://127.0.0.1:8000/vodinfo/-1003936100530/20891")
echo "   סוג התשובה: $CT"
head -c 300 /tmp/vi.json; echo
case "$CT" in
  application/json*) echo "   ✅ /vodinfo מחזיר JSON";;
  *) echo "   ⚠️ עדיין לא JSON — שלח לי את הפלט";;
esac
echo
echo "✅ בוצע. בדוק פרק של 'החממה' באתר — הוא אמור לעבור להמרה תוך שניות,"
echo "   עם קול. התמונה תישאר 624x352 כי זו איכות המקור."
echo "   לחזרה:  sudo bash $0 --rollback"
