#!/bin/bash
# מגבה את מה שקיים רק על הדיסק של השרת אל תוך המאגר.
#
# ## למה זה נדרש
#
# main.py בשרת גדול ב-193KB מהעותק שבמאגר: כל תיקון שהוחל מאז 27/08 —
# טיפול ב-ec-3, חלונות, בריכות בוטים, שני הפאצ'ים של הלוח — קיים **רק**
# על הדיסק. גם admin.html שונה (תיקון ה-409 במחיקה המונית). נפילת דיסק
# מוחקת את כולם, ואין מאיפה לשחזר.
#
# בנוסף, כמה מסקריפטי הפאץ' ב-/root מעולם לא נדחפו.
#
# ## למה fine-grained PAT ולא deploy key
#
# זו ההמלצה של GitHub ל-2026 לגישת שרת לכתיבה, כש-GitHub App הוא overkill.
# deploy key נחשב ללגסי כאן: אין לו תפוגה, ההרשאות שלו גסות, והוא נותן
# גישה ל**מאגר אחד בלבד** — ואילו כאן צריך שניים (zovex ו-zovex-android).
# טוקן אחד מכסה את שניהם, מוגבל ל-Contents בלבד, ופג לבד.
#
# ## אבטחה
#
# הטוקן נקרא מקובץ עם הרשאות 600 ו**לעולם לא מופיע** בשורת הפקודה (שגלויה
# ל-ps לכל משתמש), לא ב-.git/config, ולא בלוג. הוא מוזרם דרך credential
# helper זמני שחי רק למשך הפקודה.
#
# הסקריפט **מסרב לרוץ** אם הוא מזהה סוד בתוך קובץ שעומד להידחף. main.py
# אמור לקרוא סודות מ-.env, אבל בדיקה עדיפה על הפתעה.
#
#     bash backup_to_git.sh --check    # מראה מה יידחף וסורק סודות. לא נוגע בכלום
#     bash backup_to_git.sh            # מגבה ודוחף
set -euo pipefail

REPO="davidggjg/zovex"
BRANCH="claude/hls-relay-schema-port-ll8xiz"
TOKEN_FILE="/root/.zovex_gh_token"
WORK="/root/.zovex_backup_clone"

# מה מגבים: מקור → יעד בתוך המאגר
declare -A FILES=(
  ["/opt/zovex-bot/main.py"]="vps-bot/main.py"
  ["/opt/zovex-bot/admin.html"]="vps-bot/admin.html"
)

# תבניות שלא אמורות להופיע בקוד. אם אחת נמצאת — עוצרים.
# (מחרוזות ארוכות של hex/base64 אופייניות לטוקנים ולמפתחות)
SECRET_PATTERNS=(
  '[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}'   # טוקן בוט טלגרם
  'ghp_[A-Za-z0-9]{30,}'               # טוקן GitHub
  'github_pat_[A-Za-z0-9_]{30,}'
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'
)

CHECK=0
[[ "${1:-}" == "--check" ]] && CHECK=1

# ── אילו סקריפטים ב-/root עדיין לא במאגר ─────────────────────────────────
extra_scripts() {
  local f base
  for f in /root/*.py; do
    [[ -e "$f" ]] || continue
    base=$(basename "$f")
    [[ -e "$WORK/vps-bot/$base" ]] || echo "$f"
  done
}

scan_secrets() {
  local f pat hit=0
  for f in "$@"; do
    for pat in "${SECRET_PATTERNS[@]}"; do
      if grep -Eq "$pat" "$f" 2>/dev/null; then
        echo "❌ נמצא מה שנראה כמו סוד ב-$f (תבנית: $pat)"
        hit=1
      fi
    done
  done
  return $hit
}

# ── הטוקן ────────────────────────────────────────────────────────────────
if [[ ! -f "$TOKEN_FILE" ]]; then
  cat <<'EOF'
❌ חסר קובץ הטוקן: /root/.zovex_gh_token

איך יוצרים אותו (פעם אחת):

 1. github.com  →  Settings  →  Developer settings
      →  Personal access tokens  →  Fine-grained tokens  →  Generate new token

 2. Repository access:  Only select repositories
      בחר:  davidggjg/zovex   ו-  davidggjg/zovex-android

 3. Permissions  →  Repository permissions  →  Contents:  Read and write
      (זו ההרשאה היחידה שצריך. אל תיתן יותר.)

 4. Expiration: 90 ימים זה סביר. אפשר ליצור חדש כשיפוג.

 5. בשרת, והטוקן לא יישאר בהיסטוריית הפקודות בזכות הרווח בהתחלה:

      printf '%s' 'הדבק-כאן-את-הטוקן' > /root/.zovex_gh_token
      chmod 600 /root/.zovex_gh_token
EOF
  exit 1
fi
chmod 600 "$TOKEN_FILE"
[[ -s "$TOKEN_FILE" ]] || { echo "❌ קובץ הטוקן ריק"; exit 1; }

command -v git >/dev/null || { echo "❌ git לא מותקן:  apt install -y git"; exit 1; }

# credential helper שקורא מהקובץ. כך הטוקן לא עובר בשורת פקודה (ps) ולא
# נשמר ב-.git/config.
HELPER='!f() { echo username=x-access-token; echo "password=$(cat '"$TOKEN_FILE"')"; }; f'

# ── שכפול טרי בכל ריצה — בלי מצב שנשאר מריצה קודמת ───────────────────────
rm -rf "$WORK"
git -c credential.helper="$HELPER" clone --depth 1 --branch "$BRANCH" \
    "https://github.com/$REPO.git" "$WORK" --quiet
# היעד מוגדר בלי הטוקן, כדי שהוא לא יישב על הדיסק בתוך .git/config
git -C "$WORK" remote set-url origin "https://github.com/$REPO.git"

# ── מה משתנה ─────────────────────────────────────────────────────────────
echo "── מה ייבדק ויידחף ──"
TO_SCAN=()
CHANGED=0
for src in "${!FILES[@]}"; do
  dst="${FILES[$src]}"
  [[ -f "$src" ]] || { echo "  ⚠ $src לא קיים — מדלגים"; continue; }
  TO_SCAN+=("$src")
  if [[ -f "$WORK/$dst" ]] && cmp -s "$src" "$WORK/$dst"; then
    echo "  =  $dst (זהה, אין מה לעדכן)"
  else
    old=$( [[ -f "$WORK/$dst" ]] && stat -c%s "$WORK/$dst" || echo 0 )
    echo "  ✎  $dst   $old → $(stat -c%s "$src") בייט"
    CHANGED=1
  fi
done

mapfile -t EXTRAS < <(extra_scripts)
if ((${#EXTRAS[@]})); then
  echo "  ── סקריפטים שעדיין לא במאגר ──"
  for f in "${EXTRAS[@]}"; do
    echo "  +  vps-bot/$(basename "$f")"
    TO_SCAN+=("$f")
    CHANGED=1
  done
fi

echo
echo "── סריקת סודות ──"
if scan_secrets "${TO_SCAN[@]}"; then
  echo "  ✓ נקי"
else
  echo
  echo "עוצר. לא דוחפים קובץ שנראה שיש בו סוד."
  rm -rf "$WORK"
  exit 1
fi

if (( ! CHANGED )); then
  echo; echo "אין שינויים. המאגר כבר מעודכן."
  rm -rf "$WORK"; exit 0
fi

if (( CHECK )); then
  echo; echo "(--check — לא נדחף כלום)"
  rm -rf "$WORK"; exit 0
fi

# ── העתקה, קומיט, דחיפה ──────────────────────────────────────────────────
for src in "${!FILES[@]}"; do
  [[ -f "$src" ]] && cp -- "$src" "$WORK/${FILES[$src]}"
done
for f in "${EXTRAS[@]:-}"; do
  [[ -n "${f:-}" ]] && cp -- "$f" "$WORK/vps-bot/$(basename "$f")"
done

cd "$WORK"
git config user.email "0555687549z@gmail.com"
git config user.name  "David"
git add -A vps-bot/
if git diff --cached --quiet; then
  echo "אין שינויים אחרי ההעתקה."; cd /; rm -rf "$WORK"; exit 0
fi

git commit -q -m "גיבוי: הקבצים החיים מהשרת אל המאגר

main.py ו-admin.html שבשרת התרחקו מהעותק שבמאגר — כל תיקון שהוחל מאז
27/08 היה קיים רק על הדיסק, בלי שום מקור לשחזור. כאן הם מסונכרנים.

נדחף מהשרת עצמו ($(hostname)) ב-$(date '+%Y-%m-%d %H:%M %Z')."

git -c credential.helper="$HELPER" push origin "$BRANCH" --quiet

echo "✓ נדחף אל $REPO / $BRANCH"
git --no-pager log --oneline -1
cd /; rm -rf "$WORK"
echo
echo "מכאן והלאה: הרץ את הסקריפט הזה אחרי כל פאץ' שמחילים על השרת."
