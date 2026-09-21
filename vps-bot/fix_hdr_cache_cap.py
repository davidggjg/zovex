#!/usr/bin/env python3
"""fix_hdr_cache_cap — מטמון הכותרות בזיכרון לא מתפנה לעולם. התנגשות שם.

## הבאג

‎_VF_CACHE_MAX מוגדר **פעמיים**, בשני מובנים שונים, על ידי שני פאצ'ים
שונים:

    8407:  _VF_CACHE_MAX = 40                  # מספר כותרות בזיכרון
    8416:  _VF_CACHE_MAX = 20 * 1024**3        # [fix_vh_cache] תקרת דיסק

השני דורס את הראשון. ואז, בסוף ‎_vf_header_for:

    if len(_vf_cache) >= _VF_CACHE_MAX:       # ← len מול 21,474,836,480
        for k in sorted(...)[:10]:
            _vf_cache.pop(k, None)

התנאי הזה **לא יתקיים לעולם**. מטמון הכותרות גדל בלי גבול, וההערה
בקוד אומרת "כל כותרת ~2MB". עם 16,188 פריטים בקטלוג, זה עד עשרות
ג'יגה-בייט של זיכרון תהליך.

זו כנראה גם הסיבה ל-RSS 953MB שנמדד אחרי יממה, שנשאר בלי הסבר כשחיפשנו
את בעיית התקיעות.

## התיקון

לתת לתקרת הכותרות שם משלה. שני השימושים נכונים כל אחד לעצמו — רק השם
היה משותף:

    _VF_HDR_MAX = 40            # כותרות בזיכרון
    _VF_CACHE_MAX = 20GB        # מקטעים על הדיסק

## בדיקה שהתיקון באמת נדרש

אחרי ההחלה, השווה RSS לפני ואחרי כמה שעות:

    ps -o rss= -p $(systemctl show zovex-bot -p MainPID --value)

## שים לב גם לתקרת הדיסק

    VODFIX_CACHE_GB=20   (ברירת מחדל)

עם 22.8GB פנויים בלבד, מטמון מלא ישאיר פחות מ-3GB. הפאצ' הזה לא נוגע
בזה — זה משתנה סביבה, ושינוי שלו הוא החלטה שלך:

    echo 'VODFIX_CACHE_GB=8' >> /opt/zovex-bot/.env

    python3 fix_hdr_cache_cap.py --check
    python3 fix_hdr_cache_cap.py
    python3 fix_hdr_cache_cap.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_hdr_cache_cap"
MARK = "_VF_HDR_MAX"

A1 = ("_VF_CACHE_MAX = 40            "
      "# כל כותרת ~2MB; תקרה כדי לא לנפח את הזיכרון")
N1 = ("_VF_HDR_MAX = 40              "
      "# כל כותרת ~2MB; תקרה כדי לא לנפח את הזיכרון\n"
      "# שם נפרד בכוונה: fix_vh_cache הגדיר _VF_CACHE_MAX כתקרת דיסק\n"
      "# בבתים ודרס את הערך הזה, וכך תנאי הפינוי למטה השווה אורך dict\n"
      "# מול 21,474,836,480 ולא התקיים לעולם. ראה fix_hdr_cache_cap.py.")

A2 = "    if len(_vf_cache) >= _VF_CACHE_MAX:"
N2 = "    if len(_vf_cache) >= _VF_HDR_MAX:"

EDITS = [("הגדרת התקרה", A1, N1, None),
         ("תנאי הפינוי", A2, N2, "_vf_header_for")]


def fn_source(src, name):
    for n in ast.walk(ast.parse(src)):
        if getattr(n, "name", "") == name and isinstance(
                n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ast.get_source_segment(src, n)
    return None


def validate(s):
    compile(s, PATH, "exec")
    # התקרה החדשה מוגדרת פעם אחת ובשימוש פעם אחת
    assert s.count("_VF_HDR_MAX = 40") == 1, "התקרה לא הוגדרה"
    assert s.count("_VF_HDR_MAX") == 2, "מספר האזכורים אינו כצפוי"
    # ותקרת הדיסק נשארה בדיוק כפי שהייתה — היא לא הבאג
    assert s.count('_VF_CACHE_MAX = int(float(os.environ.get('
                   '"VODFIX_CACHE_GB", "20")) * (1 << 30))') == 1, \
        "תקרת הדיסק שונתה"
    # ואין יותר שתי הגדרות לאותו שם
    assert s.count("_VF_CACHE_MAX = ") == 1, "_VF_CACHE_MAX עוד מוגדר פעמיים"
    hf = fn_source(s, "_vf_header_for")
    assert "len(_vf_cache) >= _VF_HDR_MAX" in hf, \
        "תנאי הפינוי לא עודכן בתוך _vf_header_for"


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

    if s.count("_VF_CACHE_MAX = ") != 2:
        print(f"❌ ציפיתי לשתי הגדרות של _VF_CACHE_MAX, מצאתי "
              f"{s.count('_VF_CACHE_MAX = ')}. הקוד שונה — לא נוגע.")
        return 1

    out = s
    for name, a, b, inside in EDITS:
        n = out.count(a)
        if n != 1:
            print(f"❌ העוגן '{name}' נמצא {n} פעמים (ציפיתי 1).")
            return 1
        if inside:
            body = fn_source(out, inside)
            if body is None or a not in body:
                print(f"❌ העוגן '{name}' לא נמצא בתוך {inside}.")
                return 1
        out = out.replace(a, b, 1)

    try:
        validate(out)
    except Exception as e:
        print(f"❌ התוצאה לא תקינה ({e}) — לא נכתב כלום.")
        return 1

    print(f"יעד:   {PATH}")
    print("שינוי: לתקרת הכותרות בזיכרון שם נפרד, כדי שהפינוי יעבוד")
    if arg == "--check":
        print("--check: שום דבר לא נכתב.")
        return 0

    if not os.path.exists(BAK):
        shutil.copyfile(PATH, BAK)
    tmp = PATH + ".tmp_hdrcap"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, PATH)
    print(f"✓ הוחל · גיבוי: {BAK}")
    print("  הרץ:  systemctl restart zovex-bot")
    print("  לביטול:  python3 fix_hdr_cache_cap.py --revert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
