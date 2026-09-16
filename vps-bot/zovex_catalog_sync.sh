#!/usr/bin/env bash
# zovex_catalog_sync — כל צינור הקטלוג בפקודה אחת.
#
# למה זה קיים: אין לי גישת SSH לשרת (הסביבה שבה אני רצה חוסמת את זה
# במכוון), ולכן כל צעד היה פקודה שדוד מדביק ידנית. הסקריפט הזה אורז
# את כולם לריצה אחת, באותו סדר תלות, כך שהוא מריץ בדיוק את מה שהייתי
# מריצה אילו יכולתי — וההבדל היחיד הוא מי מקיש Enter.
#
# הסדר אינו שרירותי:
#   1. עקביות סדרות   — משלים tmdb_id בתוך סדרה. חינם, בלי רשת, ולכן
#                        ראשון: הוא מרחיב את הקלט של כל השאר.
#   2. סינון AI       — אם ריצת ההתאמה השאירה מיפוי (מלא או .partial),
#                        מחיל את מה שעבר סף 0.99. מדלג בשקט אם אין.
#   3. קטגוריות       — כל פריט עם מזהה, לקטגוריה שלו לפי TMDB.
#   4. העשרה          — תיאור/שנה/שם באנגלית/פוסטר למה שחסר.
#
# בטיחות: כל שלב שכותב לקטלוג מגובה בנפרד (bak_series / bak_categories
# / bak_enrich) ויש לו --revert משלו. הסקריפט עוצר על השגיאה הראשונה
# (set -e), ולא נוגע ב-tmdb_ai_match — סריקת המודל נשארת ריצה נפרדת
# ומבוקרת, כי היא היחידה שצורכת מכסת טוקנים.
#
#   bash zovex_catalog_sync.sh          # מריץ
#   bash zovex_catalog_sync.sh --check  # רק מראה, לא כותב כלום
set -euo pipefail

REPO="davidggjg/zovex"
REF="${ZOVEX_REF:-claude/hls-relay-schema-port-ll8xiz}"
RAW="https://raw.githubusercontent.com/${REPO}/${REF}/vps-bot"
CHECK="${1:-}"        # "--check" מעביר את כל השלבים ליבש

cd /opt/zovex-bot

say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

say "מוריד כלים מ-${REF}"
for f in tmdb_enrich.py tmdb_names.py tmdb_map_filter.py \
         fix_categories.py fix_series_consistency.py catalog_stats.py \
         category_overrides.json; do
  curl -fsSL -o "$f" "${RAW}/${f}" && echo "  ✓ $f"
done

say "מצב הקטלוג לפני"
python3 catalog_stats.py | sed -n '1,12p'

say "1/4 · עקביות סדרות (חינם, בלי רשת)"
python3 fix_series_consistency.py ${CHECK:+$CHECK}

# 2/4 — רק אם ריצת ההתאמה השאירה מיפוי. שני השמות האפשריים.
MAP=""
for cand in tmdb_ai_map.json tmdb_ai_map.json.partial tmdb_exact_map.json; do
  [ -f "$cand" ] && MAP="$cand" && break
done
if [ -n "$MAP" ]; then
  say "2/4 · מחיל מיפוי AI מ-${MAP} (סף 0.99)"
  # שלב אופציונלי: כשל כאן לא מפיל את הצינור. tmdb_map_filter יוצא
  # בשגיאה בשלושה מצבים תקינים-לגמרי — קובץ validate (עוד לא הרצת
  # התאמה), קובץ ריק, וסף שאף אחד לא עובר — וכולם פשוט אומרים "אין
  # מיפוי להחיל עכשיו", לא "עצור הכול". שלבים 3-4 עומדים בפני עצמם.
  if python3 tmdb_map_filter.py --src "$MAP" --min 0.99 --check; then
    if [ -z "$CHECK" ]; then
      python3 tmdb_map_filter.py --src "$MAP" --min 0.99
      NEWMAP="$(ls -t ./*_ge099.json 2>/dev/null | head -1 || true)"
      [ -n "$NEWMAP" ] && python3 tmdb_apply.py --map "$NEWMAP"
    fi
  else
    echo "  ↳ אין מיפוי בר-החלה מ-${MAP} (validate / ריק / סף גבוה) — מדלג."
  fi
else
  say "2/4 · אין קובץ מיפוי AI — מדלג (זה תקין אם עוד לא הרצת התאמה)"
fi

say "3/4 · קטגוריות לפי TMDB"
python3 fix_categories.py ${CHECK:+$CHECK}

say "4/4 · העשרה (תיאור/שנה/שם/פוסטר)"
python3 tmdb_enrich.py ${CHECK:+$CHECK}

say "מצב הקטלוג אחרי"
python3 catalog_stats.py | sed -n '1,12p'

if [ -n "$CHECK" ]; then
  printf '\n\033[1mיבש בלבד. שום דבר לא נכתב. להרצה אמיתית: bash %s\033[0m\n' \
    "$(basename "$0")"
else
  say "הושלם. כל שלב הפיך ב---revert המתאים לו."
fi
