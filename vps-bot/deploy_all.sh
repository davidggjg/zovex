#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZOVEX · עדכון מלא: שרת ואתר, בפקודה אחת.
#
# מה נכלל, לפי הסדר:
#
#   1. /vodinfo — ניתוב ב-nginx + browser_ok, כדי ש"החממה" וקבצי DivX
#      אחרים יעברו להמרה ויחזור להם הקול.
#   2. חסימת מייל — add_bans.py, אם עוד לא הוחל.
#   3. האתר — מהירות, עיצוב לפי האפליקציה, מצב טלוויזיה, מסך חסימה,
#      מסך מלא באייפון, ובחירת האיכות הגבוהה.
#
# כל שלב בודק את עצמו. שלב שנכשל אינו עוצר את השאר, והסיכום בסוף
# אומר מה עבר ומה לא.
#
# שלב 1 ו-2 עושים restart ל-zovex-bot. שלב 3 אינו נוגע בשרת.
#
#   sudo bash deploy_all.sh
# ─────────────────────────────────────────────────────────────────────────────
set -u
REF="${ZOVEX_REF:?צריך ZOVEX_REF=<sha>}"
B="https://raw.githubusercontent.com/davidggjg/zovex/${REF}/vps-bot"
OK=(); BAD=()
step() {  # step "שם" "פקודה"
  echo; echo "══════ $1"
  if bash -c "$2"; then OK+=("$1"); else BAD+=("$1"); echo "⚠️  $1 נכשל — ממשיכים"; fi
}

get() { curl -fsSL -H 'Cache-Control: no-cache' "$B/$1" -o "/tmp/$1" || return 1; }

get deploy_vodinfo_fix.sh && get deploy_bans.sh && get deploy_site_v2.sh \
  || { echo "❌ הורדת הסקריפטים נכשלה"; exit 1; }

step "① /vodinfo — קול לקבצי DivX" "ZOVEX_REF='$REF' bash /tmp/deploy_vodinfo_fix.sh"
step "② חסימת מייל"                "ZOVEX_REF='$REF' bash /tmp/deploy_bans.sh"
step "③ האתר"                      "ZOVEX_REF='$REF' bash /tmp/deploy_site_v2.sh"

echo
echo "═══════════════ סיכום ═══════════════"
for x in "${OK[@]:-}";  do [ -n "$x" ] && echo "  ✅ $x"; done
for x in "${BAD[@]:-}"; do [ -n "$x" ] && echo "  ❌ $x"; done
echo
echo "לחזרה, כל אחד בנפרד:"
echo "  sudo bash /tmp/deploy_vodinfo_fix.sh --rollback"
echo "  sudo bash /tmp/deploy_bans.sh --rollback"
echo "  sudo bash /tmp/deploy_site_v2.sh --rollback"
echo
echo "באתר: רענן עם Ctrl+Shift+R. בטלפון — סגור את הלשונית ופתח מחדש."
[ ${#BAD[@]} -eq 0 ]
