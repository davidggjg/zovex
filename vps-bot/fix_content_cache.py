#!/usr/bin/env python3
"""fix_content_cache — הקטלוג נקרא מהדיסק מחדש בכל פעולה, וחוסם את כל השרת.

## מה נמדד

content.json הוא 19MB. כל קריאה שלו:

    קריאה מהדיסק   250-720ms
    פרסור JSON        ~100ms
    ────────────────────────
    סה"כ            360-820ms   בכל קריאה בודדת

ו-load_content אינה שומרת כלום — היא קוראת ומפרסרת מחדש בכל קריאה.

## כמה פעמים זה קורה בהעלאה אחת

    find_upload_by_fuid    → _all_entries → load_content      (1)
    find_existing_episode  → _all_entries → load_content      (2, לפרק)
    add_movie_entry        → load_content לבדיקת ייחודיות slug (3)

כלומר שתיים עד שלוש קריאות מלאות **לכל קובץ**. בהעלאה של 30 קבצים זה
60-90 קריאות, כלומר בין 20 לדקה וחצי של עבודה שכולה מיותרת.

## ולמה זה פוגע גם בצופים

‎json.loads ו-read_text הן פעולות **חוסמות**. הן רצות על אותו לולאת
אירועים שמגישה את הווידאו, ולכן כל קריאה כזאת מקפיאה את כל השרת
לחצי שנייה — גם את הסטרימינג, גם את /vodinfo, גם את הפאנל. העלאה של
30 קבצים היא עשרות הקפאות כאלה בזו אחר זו.

## התיקון

מטמון בזיכרון לפי (זמן שינוי, גודל) של הקובץ. הקובץ לא השתנה — מחזירים
את מה שכבר מפורסר. נמדד: העתקה רדודה של הרשימה לוקחת 0.2ms במקום 360.

שמירה מבטלת את המטמון, ולכן אין מצב שמישהו קורא גרסה ישנה אחרי שינוי.

המטמון מחזיר **רשימה חדשה** עם אותם פריטים, כדי שקוד שמוסיף או מוחק
פריט לא ייגע במטמון עצמו. הקריאה והכתיבה עוברות דרך save_content
כמו קודם, וזה גם מה שמבטל.

## בדיקה שזה עבד

אחרי ההחלה, העלאה של כמה קבצים ברצף אמורה להרגיש אחרת. למדידה ישירה:

    time curl -s -o /dev/null http://127.0.0.1:8000/content/version

    python3 fix_content_cache.py --check
    python3 fix_content_cache.py
    python3 fix_content_cache.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_content_cache"
MARK = "_content_cache"

A1 = '''def load_content() -> list:
    if CONTENT_FILE.exists():
        try:
            return json.loads(CONTENT_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []
'''
N1 = '''# [fix_content_cache]
# content.json הוא 19MB, וקריאה שלו נמדדה ב-360 עד 820 מילישניות — קריאה
# מהדיסק ועוד פרסור. בהעלאה אחת הוא נקרא פעמיים-שלוש (בדיקת כפילות,
# בדיקת פרק קיים, ייחודיות slug), ובהעלאה של 30 קבצים זה 60-90 קריאות
# מלאות של אותו קובץ שלא השתנה.
#
# וזה לא רק איטי: json.loads ו-read_text חוסמות, והן רצות על אותה לולאת
# אירועים שמגישה וידאו. כל קריאה כזאת מקפיאה את השרת כולו לחצי שנייה.
#
# המטמון מפתוח ב-(זמן שינוי, גודל): הקובץ לא השתנה — אין מה לקרוא שוב.
# ההעתקה הרדודה שמוחזרת נמדדה ב-0.2ms.
_content_cache = {"key": None, "data": None}


def load_content() -> list:
    if CONTENT_FILE.exists():
        try:
            st = CONTENT_FILE.stat()
            key = (st.st_mtime_ns, st.st_size)
            if _content_cache["key"] == key and _content_cache["data"] is not None:
                # רשימה חדשה עם אותם פריטים: מי שמוסיף או מוחק פריט לא נוגע
                # במטמון. שינוי של פריט נכתב דרך save_content, וזה מבטל.
                return list(_content_cache["data"])
            data = json.loads(CONTENT_FILE.read_text(encoding="utf-8"))
            _content_cache["key"] = key
            _content_cache["data"] = data
            return list(data)
        except Exception:
            _content_cache["key"] = None
            _content_cache["data"] = None
            return []
    return []
'''

A2 = '''    _atomic_write_text(CONTENT_FILE, json.dumps(arr, ensure_ascii=False, indent=2))  # [fix_atomic_writes]
    _bump_content_version()
'''
N2 = '''    _atomic_write_text(CONTENT_FILE, json.dumps(arr, ensure_ascii=False, indent=2))  # [fix_atomic_writes]
    # [fix_content_cache] הקובץ השתנה — הקריאה הבאה תקרא אותו מחדש.
    # מבטלים ולא מעדכנים בעיוורון: _normalize_live_flag כבר שינתה את arr,
    # ומה שנכתב לדיסק הוא מקור האמת.
    _content_cache["key"] = None
    _content_cache["data"] = None
    _bump_content_version()
'''

EDITS = [("קריאת הקטלוג", A1, N1, None),
         ("ביטול בשמירה", A2, N2, "save_content")]


def fn_source(src, name):
    for n in ast.walk(ast.parse(src)):
        if getattr(n, "name", "") == name and isinstance(
                n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ast.get_source_segment(src, n)
    return None


def validate(s):
    compile(s, PATH, "exec")
    assert s.count('_content_cache = {"key": None, "data": None}') == 1, \
        "המטמון לא הוגדר פעם אחת"
    lc = fn_source(s, "load_content")
    assert lc and "_content_cache[\"key\"] == key" in lc, \
        "בדיקת המטמון לא נכנסה ל-load_content"
    assert "st_mtime_ns" in lc, "המפתח אינו לפי זמן שינוי"
    assert "return list(" in lc, "מוחזרת הרשימה עצמה ולא העתק"
    sc = fn_source(s, "save_content")
    assert sc and '_content_cache["key"] = None' in sc, \
        "השמירה אינה מבטלת את המטמון"
    # אין הגדרה כפולה של load_content, ושאר הפונקציות במקומן
    names = [n.name for n in ast.walk(ast.parse(s))
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert names.count("load_content") == 1, "load_content הוגדרה פעמיים"
    assert names.count("save_content") == 1, "save_content הוגדרה פעמיים"


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""

    if arg == "--revert":
        if not os.path.exists(BAK):
            print(f"❌ אין גיבוי ב-{BAK}")
            return 1
        shutil.copyfile(BAK, PATH)
        print("✓ שוחזר. הרץ:  systemctl restart zovex-bot")
        return 0

    if not os.path.exists(PATH):
        print(f"❌ לא נמצא {PATH}")
        return 1

    with open(PATH, encoding="utf-8") as f:
        s = f.read()

    if MARK in s:
        print("כבר מותקן. אין מה לעשות.")
        return 0

    out = s
    for name, a, b, inside in EDITS:
        n = out.count(a)
        if n != 1:
            print(f"❌ העוגן '{name}' נמצא {n} פעמים (ציפיתי 1).")
            print("   main.py שונה ממה שציפיתי — לא נוגע בכלום.")
            return 1
        if inside:
            body = fn_source(out, inside)
            if body is None or a.rstrip("\n") not in body:
                print(f"❌ העוגן '{name}' לא נמצא בתוך {inside}.")
                return 1
        out = out.replace(a, b, 1)

    try:
        validate(out)
    except Exception as e:
        print(f"❌ התוצאה לא תקינה ({e}) — לא נכתב כלום.")
        return 1

    print(f"יעד:   {PATH}")
    print("שינוי: הקטלוג נקרא מהדיסק רק כשהוא באמת השתנה")
    if arg == "--check":
        print("--check: שום דבר לא נכתב.")
        return 0

    if not os.path.exists(BAK):
        shutil.copyfile(PATH, BAK)
    tmp = PATH + ".tmp_ccache"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, PATH)
    print(f"✓ הוחל · גיבוי: {BAK}")
    print("  הרץ:  systemctl restart zovex-bot")
    print("  לביטול:  python3 fix_content_cache.py --revert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
