#!/usr/bin/env python3
"""fix_panel_pass_header — סיסמת הפאנל נכתבה בגלוי ליומן של nginx.

## הממצא

מסקירת אבטחה של המאגרים הציבוריים. הפאנל טוען את רשימת "חסרי טריילר"
כך:

    fetch("/panel/no-trailer?password=" + encodeURIComponent(PASS))

סיסמה ב-**כתובת** היא סיסמה ביומן. nginx כותב את השורה המלאה, כולל
‎?password=…, לקובץ ‎/var/log/nginx/access.log בכל פעם שהפאנל נפתח. היומן
נשמר על הדיסק ימים, מסתובב לקבצי ‎.gz, ונקרא על ידי כל כלי שקורא יומנים.
זה המקום היחיד בפאנל שעושה את זה — כל שאר הקריאות שולחות אותה בגוף
הבקשה, שלא נרשם.

## התיקון

הפאנל שולח את הסיסמה בכותרת ‎X-Panel-Password, ש-nginx לא רושם. השרת
מקבל אותה משם, ועדיין מקבל גם את הצורה הישנה — כדי שפאנל פתוח בדפדפן
עם עותק ישן לא יישבר באמצע עבודה. הדליפה נפסקת ברגע שהפאנל החדש נטען.

## מה שזה לא מתקן

שורות שכבר נכתבו ליומן נשארות שם. אחרי ההחלה, להחליף את הסיסמה (היא
גם כבר נחשפה בהיסטוריית הטרמינל) ולנקות:

    grep -l "password=" /var/log/nginx/access.log* 2>/dev/null

    python3 fix_panel_pass_header.py --check
    python3 fix_panel_pass_header.py
    python3 fix_panel_pass_header.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
HTML = os.environ.get("ADMIN_HTML", "/opt/zovex-bot/admin.html")
BAK = PATH + ".bak_panel_pass_header"
BAK_HTML = HTML + ".bak_panel_pass_header"
MARK = "fix_panel_pass_header"

PA = '''async def panel_no_trailer(request: Request, password: str = ""):
    """מה שאין לו טריילר. סדרות מקובצות לפי שם — רשימה של 424 פרקים לאותה
    סדרה אינה רשימת עבודה, היא רעש."""
    check_panel_password(request, password)
'''
PN = '''async def panel_no_trailer(request: Request, password: str = ""):
    """מה שאין לו טריילר. סדרות מקובצות לפי שם — רשימה של 424 פרקים לאותה
    סדרה אינה רשימת עבודה, היא רעש."""
    # [fix_panel_pass_header] הסיסמה מגיעה בכותרת, לא בכתובת: ‎?password=
    # נכתב בגלוי ליומן של nginx בכל פתיחת פאנל. הצורה הישנה עדיין מתקבלת
    # כדי שפאנל ישן שפתוח בדפדפן לא יישבר באמצע עבודה.
    password = request.headers.get("x-panel-password") or password
    check_panel_password(request, password)
'''

HA = '''    const r=await fetch("/panel/no-trailer?password="+encodeURIComponent(PASS));'''
HN = '''    // [fix_panel_pass_header] בכותרת ולא בכתובת — כתובת נרשמת ביומן של nginx
    const r=await fetch("/panel/no-trailer",{headers:{"X-Panel-Password":PASS}});'''


def fn_source(src, name):
    for n in ast.walk(ast.parse(src)):
        if getattr(n, "name", "") == name and isinstance(
                n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ast.get_source_segment(src, n)
    return None


def validate(s, h):
    compile(s, PATH, "exec")
    body = fn_source(s, "panel_no_trailer")
    assert body and 'request.headers.get("x-panel-password")' in body, \
        "השרת לא קורא את הכותרת"
    assert body.index("x-panel-password") < body.index("check_panel_password"), \
        "הכותרת נקראת אחרי הבדיקה"
    assert "?password=" not in h, "עדיין יש סיסמה בכתובת בפאנל"
    assert h.count('"X-Panel-Password":PASS') == 1, "הפאנל לא שולח את הכותרת"


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""

    if arg == "--revert":
        n = 0
        for src, dst in ((BAK, PATH), (BAK_HTML, HTML)):
            if os.path.exists(src):
                shutil.copyfile(src, dst)
                n += 1
        if not n:
            print("❌ אין גיבויים לשחזור")
            return 1
        print(f"✓ שוחזרו {n} קבצים. הרץ:  systemctl restart zovex-bot")
        return 0

    for p in (PATH, HTML):
        if not os.path.exists(p):
            print(f"❌ לא נמצא {p}")
            return 1
    with open(PATH, encoding="utf-8") as f:
        s = f.read()
    with open(HTML, encoding="utf-8") as f:
        h = f.read()

    if MARK in s and MARK in h:
        print("כבר מותקן. אין מה לעשות.")
        return 0

    if s.count(PA) != 1:
        print(f"❌ העוגן בשרת נמצא {s.count(PA)} פעמים (ציפיתי 1). לא נוגע.")
        return 1
    if h.count(HA) != 1:
        print(f"❌ העוגן בפאנל נמצא {h.count(HA)} פעמים (ציפיתי 1). לא נוגע.")
        return 1
    out_s = s.replace(PA, PN, 1)
    out_h = h.replace(HA, HN, 1)

    try:
        validate(out_s, out_h)
    except Exception as e:
        print(f"❌ התוצאה לא תקינה ({e}) — לא נכתב כלום.")
        return 1

    print(f"יעד:   {PATH}\n       {HTML}")
    print("שינוי: סיסמת הפאנל בכותרת במקום בכתובת (לא נרשמת ביומן)")
    if arg == "--check":
        print("--check: שום דבר לא נכתב.")
        return 0

    for src, bak in ((PATH, BAK), (HTML, BAK_HTML)):
        if not os.path.exists(bak):
            shutil.copyfile(src, bak)
    for dst, data in ((PATH, out_s), (HTML, out_h)):
        tmp = dst + ".tmp_pph"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, dst)
    print("✓ הוחל. הרץ:  systemctl restart zovex-bot  ואז Ctrl+Shift+R בפאנל")
    print("  לביטול:  python3 fix_panel_pass_header.py --revert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
