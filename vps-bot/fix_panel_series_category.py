#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מוסיף לפאנל כפתור «קבע קטגוריה לכל הסדרה».

הבעיה: סדרה בת 70 פרקים שצריכה לעבור קטגוריה דורשת היום לפתוח כל פרק
בנפרד. עם 8,479 פרקים ב-118 סדרות זו עבודה שאין שום סיבה לעשות ידנית.

הפתרון קטן במכוון: בפאנל כבר קיימת applyToSeries שמחילה פוסטר או תקציר
על כל פרקי הסדרה, ועוברת דרך נתיב השמירה הרגיל — כולל הגיבוי ונעילת
הגרסה שמונעת דריסה בין שני עורכים. הפאץ' רק מכליל אותה כדי שתתמוך גם
בקטגוריה, ומוסיף כפתור. אין נקודת קצה חדשה בשרת ואין נתיב כתיבה חדש.

הקובץ נערך *במקום* ולא מוחלף: עותק admin.html שבמאגר ישן ואינו כולל
תוספות שהוחלו ישירות על השרת (למשל כרטיס בוט הדרייב), והחלפה מלאה
הייתה מוחקת אותן.

    python3 fix_panel_series_category.py --check
    python3 fix_panel_series_category.py
    python3 fix_panel_series_category.py --revert
"""
import argparse, datetime, glob, os, pathlib, shutil, sys

TARGET = pathlib.Path(os.environ.get("ADMIN_HTML", "/opt/zovex-bot/admin.html"))
MARK = "SERIES_FIELDS"

A_FN = '''async function applyToSeries(field){
  const n=$("f_series").value.trim(); if(!n) return;
  const val = field==="thumbnail_url"?$("f_thumb").value.trim():$("f_desc").value.trim();
  if(!confirm(`לעדכן ${field==="thumbnail_url"?"פוסטר":"תקציר"} לכל הפרקים של «${n}»?`)) return;
  const ups=movies.filter(m=>m.series_name===n).map(m=>({id:m.id,[field]:val}));
  if(await mutate({upsert:ups})){ $("addMsg").innerHTML='<span class="ok">עודכן לכל הסדרה ✓</span>'; }
}'''

B_FN = '''// שדות שאפשר להחיל על כל פרקי הסדרה בלחיצה אחת. הוספת שדה = שורה כאן.
const SERIES_FIELDS = {
  thumbnail_url: {label:"פוסטר",   get:()=>$("f_thumb").value.trim()},
  description:   {label:"תקציר",   get:()=>$("f_desc").value.trim()},
  category:      {label:"קטגוריה", get:()=>$("f_category").value.trim()},
};
async function applyToSeries(field){
  const n=$("f_series").value.trim(); if(!n) return;
  const f=SERIES_FIELDS[field]; if(!f) return;
  const val=f.get();
  if(field==="category" && !val){ alert("לא נבחרה קטגוריה"); return; }
  const ups=movies.filter(m=>m.series_name===n).map(m=>({id:m.id,[field]:val}));
  if(!ups.length){ alert(`לא נמצאו פרקים לסדרה «${n}»`); return; }
  // מציגים את מספר הפרקים לפני האישור: פעולה שנוגעת ב-70 פריטים צריכה
  // להראות את זה מראש, לא אחרי.
  if(!confirm(`לעדכן ${f.label} ל-${ups.length} הפרקים של «${n}»?\\n\\nערך חדש: ${val||"(ריק)"}`)) return;
  if(await mutate({upsert:ups})){
    $("addMsg").innerHTML=`<span class="ok">${f.label} עודכן ל-${ups.length} פרקים ✓</span>`;
  }
}'''

A_BTN = '''<button class="mini orange" onclick="applyToSeries('description')">עדכן תקציר לכל הסדרה</button>'''
B_BTN = ('''<button class="mini orange" onclick="applyToSeries('description')">עדכן תקציר לכל הסדרה</button>\n'''
         '''        <button class="mini" style="background:#0a8f5a" onclick="applyToSeries('category')">קבע קטגוריה לכל הסדרה</button>''')


def _fail(m):
    print(f"❌ {m}"); sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    if not TARGET.exists():
        _fail(f"{TARGET} לא נמצא")

    if a.revert:
        baks = sorted(glob.glob(str(TARGET) + ".bak-seriescat-*"))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], TARGET)
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}")
        print("   admin.html נטען בכל רענון — אין צורך בריסטארט.")
        return

    src = TARGET.read_text(encoding="utf-8")
    if MARK in src:
        print("✓ הכפתור כבר קיים. לא שונה כלום.")
        return
    for name, anc in (("הפונקציה", A_FN), ("שורת הכפתורים", A_BTN)):
        if src.count(anc) != 1:
            _fail(f"{name}: נמצאו {src.count(anc)} עוגנים, ציפינו ל-1. "
                  "ייתכן שהקובץ בשרת שונה ממה שציפינו — לא נוגעים.")

    out = src.replace(A_FN, B_FN).replace(A_BTN, B_BTN)
    if "f_category" not in out:
        _fail("שדה f_category לא קיים בקובץ — הכפתור לא יעבוד.")

    if a.check:
        print("✓ שני העוגנים מתאימים ושדה הקטגוריה קיים. לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-seriescat-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print(f"✓ הוחל. גיבוי: {os.path.basename(bak)}")
    print("   admin.html נטען בכל רענון — רק לרענן את הפאנל (Ctrl+Shift+R).")


if __name__ == "__main__":
    main()
