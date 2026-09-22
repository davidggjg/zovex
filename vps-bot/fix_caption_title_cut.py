#!/usr/bin/env python3
"""fix_caption_title_cut — "תרגום מובנה" בסוף הכותרת הפיל את כל השורה.

## מה קרה בשטח

הועלה קובץ עם הכיתוב:

    המשטרה נפלה על הראש 1 (2001) - תרגום מובנה
    איכות: 1080P ~ FHD = גבוהה מאד
    - לולו סרטים

והבוט ענה: «לא זיהיתי אוטומטית "המשטרה נפלה על הראש 1 2001 ת מ"» —
כלומר הוא חיפש לפי **שם הקובץ**, ואת הכיתוב לא ראה בכלל. כשדוד הקליד
את השם ידנית, TMDB מצא אותו מיד.

## למה

‎_recognition_candidates עוצרת בשורה הראשונה שנראית מטא-דאטה:

    if _CAP_NOISE.search(line):
        break

ו-_CAP_NOISE כוללת את המילה **תרגום**. היא מופיעה כאן בסוף שורת
הכותרת עצמה, ולכן הבדיקה נכונה טכנית והתוצאה הפוכה: הלולאה נשברה על
השורה הראשונה, רשימת הכותרות יצאה **ריקה**, ונשאר רק שם הקובץ.

נמדד על הכיתוב הזה בדיוק, לפני התיקון:

    מועמדים: ['המשטרה נפלה על הראש 1 2001 ת מ', 'המשטרה נפלה על הראש ת מ']

"ת מ" הוא ‎_ת_מ_ מתוך שם הקובץ. אין פלא ש-TMDB לא מצא.

## התיקון

לא לזרוק את השורה אלא **לחתוך אותה** במקום שבו מתחילה המטא-דאטה, ולקחת
את מה שלפניה. זה הרי הדפוס הרגיל בערוצים: "שם הסרט (שנה) - תרגום מובנה".
אם לפני הסימון לא נשאר כלום — כמו ב-"איכות: 1080P" — עוצרים כמו קודם.

אחרי התיקון, על אותו כיתוב:

    מועמדים: ['המשטרה נפלה על הראש 1 (2001)',
              'המשטרה נפלה על הראש 1',
              'המשטרה נפלה על הראש',        ← זה מה ש-TMDB מוצא
              'המשטרה נפלה על הראש 1 2001 ת מ', ...]

המועמד העברי מפיל גם את הספרה "1" (הרגקס אוסף מילים עבריות בלבד), וזה
בדיוק השם שדוד הקליד ידנית וש-TMDB ענה עליו.

זה נוגע גם בייבוא מערוץ, שמשתמש באותה פונקציה — לטובה, מאותה סיבה.

    python3 fix_caption_title_cut.py --check
    python3 fix_caption_title_cut.py
    python3 fix_caption_title_cut.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
BAK = PATH + ".bak_caption_title_cut"
MARK = "fix_caption_title_cut"

A1 = '''    title_lines = []
    for line in caption.splitlines():
        line = line.strip()
        if not line:
            continue
        if _CAP_NOISE.search(line):
            break
        title_lines.append(line)
        if len(title_lines) >= 2:
            break
'''
N1 = '''    title_lines = []
    for line in caption.splitlines():
        line = line.strip()
        if not line:
            continue
        # [fix_caption_title_cut]
        # סימון מטא-דאטה בתוך השורה אינו אומר שכל השורה מטא-דאטה. הדפוס
        # הרגיל בערוצים הוא "שם הסרט (שנה) - תרגום מובנה", ו-"תרגום"
        # נמצאת ברשימה — ולכן הלולאה נשברה על שורת הכותרת עצמה ורשימת
        # הכותרות יצאה ריקה. נמדד על כיתוב אמיתי: נשאר רק שם הקובץ,
        # «המשטרה נפלה על הראש 1 2001 ת מ», ו-TMDB לא מצא כלום.
        #
        # לכן חותכים את השורה לפני הסימון ולוקחים את מה שנשאר. אם לא
        # נשאר כלום — כמו ב-"איכות: 1080P" — עוצרים כמו קודם.
        _n = _CAP_NOISE.search(line)
        if _n:
            _head = line[:_n.start()].strip(" -–—·|:،,")
            if len(_head) >= 2:
                title_lines.append(_head)
            break
        title_lines.append(line)
        if len(title_lines) >= 2:
            break
'''

A2 = '''    out = []
    for line in (caption or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if _CAP_NOISE.search(line):
            break
        out.append(line)
        if len(out) >= lines:
            break
'''
N2 = '''    out = []
    for line in (caption or "").splitlines():
        line = line.strip()
        if not line:
            continue
        # [fix_caption_title_cut] אותו תיקון כמו ב-_recognition_candidates:
        # "הדוב (2022) - תרגום מובנה" בשורה הראשונה היה מפיל את כל הכותרת,
        # ואיתה את זיהוי הפרק מהכיתוב.
        #
        # וכאן, בשונה משם, ממשיכים לשורה הבאה אחרי החיתוך: סימון הפרק
        # יושב לא פעם בשורה שלישית ("הדוב (2022) - תרגום מובנה" /
        # "The Bear" / "עונה 2 פרק 5"), ועצירה אחרי החיתוך הייתה מאבדת
        # אותו. עוצרים רק כששורה שלמה היא מטא-דאטה, כמו "איכות: 1080P" —
        # ומשם והלאה זה כבר התקציר, שאסור לקרוא ממנו מספרי פרק.
        _n = _CAP_NOISE.search(line)
        if _n:
            _head = line[:_n.start()].strip(" -–—·|:،,")
            if len(_head) < 2:
                break
            out.append(_head)
            if len(out) >= lines:
                break
            continue
        out.append(line)
        if len(out) >= lines:
            break
'''

EDITS = [("שורות הכותרת", A1, N1, "_recognition_candidates"),
         ("שורות הכותרת לזיהוי פרק", A2, N2, "_cap_head")]


def fn_source(src, name):
    for n in ast.walk(ast.parse(src)):
        if getattr(n, "name", "") == name and isinstance(
                n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ast.get_source_segment(src, n)
    return None


def validate(s):
    compile(s, PATH, "exec")
    rc = fn_source(s, "_recognition_candidates")
    assert rc, "_recognition_candidates נעלמה"
    assert "_n = _CAP_NOISE.search(line)" in rc, "החיתוך לא נכנס"
    assert "line[:_n.start()]" in rc, "לא נלקח מה שלפני הסימון"
    # הסימון עצמו לא שונה — רק מה שעושים איתו
    assert s.count("_CAP_NOISE = re.compile") == 1, "רשימת הסימונים שונתה"
    ch = fn_source(s, "_cap_head")
    assert ch and "line[:_n.start()]" in ch, "החיתוך לא נכנס ל-_cap_head"
    # ולא נשארה שבירה עיוורת באף אחת מהשתיים
    for name, body in (("_recognition_candidates", rc), ("_cap_head", ch)):
        assert "if _CAP_NOISE.search(line):\n            break" not in body, \
            f"השבירה הישנה עדיין ב-{name}"


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
    print("שינוי: שורת כותרת נחתכת לפני המטא-דאטה במקום להיזרק כולה")
    if arg == "--check":
        print("--check: שום דבר לא נכתב.")
        return 0

    if not os.path.exists(BAK):
        shutil.copyfile(PATH, BAK)
    tmp = PATH + ".tmp_ctcut"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, PATH)
    print(f"✓ הוחל · גיבוי: {BAK}")
    print("  הרץ:  systemctl restart zovex-bot")
    print("  לביטול:  python3 fix_caption_title_cut.py --revert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
