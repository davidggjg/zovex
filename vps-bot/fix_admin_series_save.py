#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_admin_series_save — "שמור" מחיל שדות סדרה על כל הפרקים.

## הבקשה

דוד, מול הפאנל: "יש כפתורים לעדכן סדרות... אני שם פוסטר, טריילר, תיאור,
עושה שמור וזה שומר את זה לכל הסדרה. לא צריך את הכפתורים האלה. סדרה זה
לא מחולק לכמה חלקים."

הוא צודק, וזו לא רק נוחות. פוסטר, תקציר, קטגוריה וטריילר מתארים את
**הסדרה**; אין מצב שבו לפרק 4 מגיע תקציר אחר מפרק 5. עד עכשיו השמירה
עדכנה פרק אחד, ואחריה היה צריך ללחוץ ארבעה כפתורים נפרדים. מי ששכח קיבל
סדרה שבה פרק אחד נראה אחרת מכל השאר.

## מה נעשה

השמירה מפיצה את השדות לכל פרקי הסדרה בקריאה אחת, וארבעת הכפתורים הוסרו.
מקור רשימת השדות הוא SERIES_FIELDS הקיים — אותו אובייקט שהכפתורים
השתמשו בו — כדי שלא תהיה רשימה שנייה שתיסחף ממנו.

## שתי הגנות

  • רק שדה עם ערך מתפשט. בלי זה, שמירה עם תקציר ריק הייתה מוחקת תקציר
    תקין מכל הסדרה — ההיפך מהכוונה.
  • ההודעה אומרת מה קרה ("פוסטר, תקציר הוחלו על 43 פרקים"), כי פעולה
    שנוגעת בעשרות פריטים צריכה להיות גלויה ולא הפתעה.

applyToSeries הוסרה — היא נקראה רק מארבעת הכפתורים.

    python3 fix_admin_series_save.py --check
    python3 fix_admin_series_save.py
    python3 fix_admin_series_save.py --revert
בלי restart — admin.html נקרא בכל בקשה.
"""
import argparse, os, shutil, sys
from pathlib import Path

TARGET = Path(os.environ.get("ZOVEX_ADMIN", "/opt/zovex-bot/admin.html"))
BAK = TARGET.with_name(TARGET.name + ".bak_seriessave")
MARK = "_seriesNote"

ANCHORS = [
    ("ראש saveItem", 'async function saveItem(){\n  const e=buildEntry();', 'async function saveItem(){\n  let _seriesNote="";   // מה הופץ לסדרה — נוסף להודעת ההצלחה\n  const e=buildEntry();'),
    ("הפצה בשמירה", 'if(await mutate({upsert:[item]})){', 'const _ups=[item];\n  // שדות ברמת הסדרה מתפשטים לכל הפרקים בשמירה עצמה.\n  //\n  // דוד: "סדרה זה לא מחולק לכמה חלקים" — והוא צודק. פוסטר, תקציר,\n  // קטגוריה וטריילר מתארים את הסדרה ולא את הפרק, ואין מצב שבו לפרק 4\n  // מגיע תקציר אחר מפרק 5. קודם זה דרש ארבעה כפתורים נפרדים אחרי כל\n  // שמירה, ומי ששכח קיבל סדרה שבה פרק אחד נראה אחרת מכולם.\n  //\n  // SERIES_FIELDS הוא אותו מקור שהכפתורים השתמשו בו — לא נוצרה רשימה\n  // שנייה שתיסחף ממנו כששדה יתווסף.\n  if(e.series_name){\n    const _spread={};\n    for(const _k in SERIES_FIELDS){\n      const _v=SERIES_FIELDS[_k].get();\n      if(_v) _spread[_k]=_v;   // ריק לא מתפשט — אחרת שמירה מוחקת תקציר תקין\n    }\n    const _keys=Object.keys(_spread);\n    if(_keys.length){\n      for(const _m of movies){\n        if(_m.series_name===e.series_name && _m.id!==item.id)\n          _ups.push({id:_m.id,..._spread});\n      }\n      if(_ups.length>1){\n        const _lbl=_keys.map(k=>SERIES_FIELDS[k].label).join(", ");\n        _seriesNote=\' \\u00b7 \'+_lbl+\' \\u05d4\\u05d5\\u05d7\\u05dc\\u05d5 \\u05e2\\u05dc \'+_ups.length+\' \\u05e4\\u05e8\\u05e7\\u05d9\\u05dd\';\n      }\n    }\n  }\n  if(await mutate({upsert:_ups})){'),
    ("הודעת הצלחה", '$("addMsg").innerHTML=\'<span class="ok">נשמר ✓</span>\';', '$("addMsg").innerHTML=\'<span class="ok">נשמר ✓</span>\'+_seriesNote;'),
    ("כפתורי לכל הסדרה", '<div id="applyAll" class="row hidden" style="margin-bottom:8px">\n        <button class="mini" style="background:#5e5ce6" onclick="applyToSeries(\'thumbnail_url\')">עדכן פוסטר לכל הסדרה</button>\n        <button class="mini orange" onclick="applyToSeries(\'description\')">עדכן תקציר לכל הסדרה</button>\n        <button class="mini" style="background:#0a8f5a" onclick="applyToSeries(\'category\')">קבע קטגוריה לכל הסדרה</button>\n        <button class="mini" style="background:#b4532a" onclick="applyToSeries(\'trailer_url\')">עדכן טריילר לכל הסדרה</button>\n      </div>', ""),
    ("applyToSeries", 'async function applyToSeries(field){\n  const n=$("f_series").value.trim(); if(!n) return;\n  const f=SERIES_FIELDS[field]; if(!f) return;\n  const val=f.get();\n  if(field==="category" && !val){ alert("לא נבחרה קטגוריה"); return; }\n  const ups=movies.filter(m=>m.series_name===n).map(m=>({id:m.id,[field]:val}));\n  if(!ups.length){ alert(`לא נמצאו פרקים לסדרה «${n}»`); return; }\n  // מציגים את מספר הפרקים לפני האישור: פעולה שנוגעת ב-70 פריטים צריכה\n  // להראות את זה מראש, לא אחרי.\n  if(!confirm(`לעדכן ${f.label} ל-${ups.length} הפרקים של «${n}»?\\n\\nערך חדש: ${val||"(ריק)"}`)) return;\n  if(await mutate({upsert:ups})){\n    $("addMsg").innerHTML=`<span class="ok">${f.label} עודכן ל-${ups.length} פרקים ✓</span>`;\n  }\n}', ""),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    if not TARGET.exists():
        sys.exit("לא נמצא %s" % TARGET)
    src = TARGET.read_text(encoding="utf-8")

    if a.revert:
        if not BAK.exists():
            sys.exit("אין גיבוי ב-%s" % BAK)
        shutil.copy2(BAK, TARGET)
        print("✓ שוחזר מ-%s" % BAK)
        return

    if MARK in src:
        print("כבר מותקן. אין מה לעשות.")
        return

    for label, old, _new in ANCHORS:
        n = src.count(old)
        if n != 1:
            sys.exit("עוגן '%s' נמצא %d פעמים (ציפיתי 1) — לא כותב." % (label, n))

    out = src
    for _label, old, new in ANCHORS:
        out = out.replace(old, new, 1)

    # שלוש הזרקות: הצהרה, הפצה, הודעה
    if out.count(MARK) != 3:
        sys.exit("ההוספה לא נתפסה במלואה (%d מתוך 3) — לא כותב." % out.count(MARK))
    if "SERIES_FIELDS" not in out:
        sys.exit("אימות נכשל: SERIES_FIELDS נעלם, והקוד החדש תלוי בו — לא כותב.")
    if 'id="applyAll"' in out or "applyToSeries" in out:
        sys.exit("אימות נכשל: נשאר שריד של הכפתורים — לא כותב.")

    print("שמירה: מפיצה פוסטר/תקציר/קטגוריה/טריילר לכל פרקי הסדרה")
    print("הוסרו: 4 כפתורי 'לכל הסדרה' + applyToSeries")
    print("SERIES_FIELDS נשמר — הוא מקור האמת לשדות")
    if a.check:
        print("--check: שום דבר לא נכתב. היעד: %s" % TARGET)
        return

    shutil.copy2(TARGET, BAK)
    TARGET.write_text(out, encoding="utf-8")
    print("✓ הוחל · גיבוי: %s" % BAK)
    print("  בלי restart. רענן את /admin.")
    print("  לביטול: python3 fix_admin_series_save.py --revert")


if __name__ == "__main__":
    main()
