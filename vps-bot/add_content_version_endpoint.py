#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מוסיף ‎GET /content/version‎ — נקודת קצה זעירה שמחזירה רק את מונה גרסת התוכן.

## הבעיה שדוד תיאר

"מחקתי משהו בפאנל ואני לא רואה אותו נמחק באפליקציה, או שזה נמחק בדיליי מטורף."

הצד של השרת תקין ונמדד: כל שמירה מהפאנל עוברת ב-‎save_content()‎, שמסיימת
ב-‎_bump_content_version()‎; ‎_fresh()‎ פוסלת כל גוף שמור שגרסתו שונה, ולכן
‎/content/lite‎ מגיש את הקטלוג החדש כבר בבקשה הבאה. אין שם עיכוב.

העיכוב כולו אצל הלקוח. באפליקציה:

    const CACHE_MS = 5 * 60 * 1000;      // מטמון בזיכרון
    useEffect(... AppState 'active' → load())

כלומר הקטלוג נמשך מחדש רק כשחוזרים לאפליקציה מהרקע, ורק אם עברו חמש דקות
מהמשיכה האחרונה. ואם האפליקציה פשוט **פתוחה על המסך** — אין AppState, אין
טיימר, ואף אחד לא מושך שוב. במצב הזה הפריט המחוק נשאר על המסך **לנצח**, לא
"בדיליי". זה מסביר בדיוק את שתי התופעות שדוד ראה.

## למה צריך נקודת קצה חדשה בשביל זה

הפתרון הוא שהאפליקציה תשאל כל דקה "השתנה משהו?" — אבל בלי להוריד קטלוג.

    /content            ~1MB   — כל הקטלוג
    /content/lite       ~1MB   — בלי description
    /content/lite?limit=800  422KB
    /content/live       עשרות KB
    /content/version    ~25 בתים   ← זה

ו-‎?limit=1‎ לא היה עוזר: הוא לא ברשימת ה-limit-ים השמורים, ולכן כל בקשה
כזאת בונה מחדש את *כל* הקטלוג (כולל חתימת ~11 אלף קישורים) רק כדי להחזיר
פריט אחד. תשאול כל דקה בדרך הזאת היה מפיל את השרת.

הנקודה הזאת קוראת קובץ טקסט אחד בן ספרות בודדות. אין בה מידע רגיש — רק מספר
מונה — ולכן היא פתוחה כמו שאר ‎/content‎.

    python3 add_content_version_endpoint.py --check    # לא נוגע בכלום
    python3 add_content_version_endpoint.py           # מחיל, עם גיבוי
    python3 add_content_version_endpoint.py --revert  # מחזיר
"""
import datetime, glob, os, pathlib, shutil, sys

TARGET = pathlib.Path("/opt/zovex-bot/main.py")

ANCHOR = '''@api.get("/content/lite")
async def content_lite(request: Request, limit: int = 0):'''

NEW = '''@api.get("/content/version")
async def content_version_only():
    """מונה גרסת התוכן בלבד — כמה עשרות בתים, בלי לגעת ב-content.json.

    נועד לתשאול תכוף מהאפליקציה: היא מחזיקה את הקטלוג בזיכרון ומרעננת אותו
    רק כשהמספר הזה משתנה. בלי זה פריט שנמחק בפאנל נשאר על המסך עד שהאפליקציה
    יוצאת לרקע וחוזרת (ואם היא נשארת פתוחה — לא נעלם בכלל).

    get_content_version() קורא קובץ טקסט אחד בן ספרות בודדות. במכוון *לא*
    מוחזר count: הוא היה מחייב load_content() — פרסור של ~11 אלף פריטים בכל
    תשאול.
    """
    return JSONResponse({"version": get_content_version()},
                        headers={"Cache-Control": "no-store"})


'''


def _fail(m):
    print(f"❌ {m}")
    sys.exit(1)


def main():
    if not TARGET.exists():
        _fail(f"{TARGET} לא נמצא")
    src = TARGET.read_text(encoding="utf-8")

    if "--revert" in sys.argv:
        baks = sorted(glob.glob(str(TARGET) + ".bak-cver-*"))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], TARGET)
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}")
        print("   צריך: systemctl restart zovex-bot")
        return

    if '@api.get("/content/version")' in src:
        print("✓ הנקודה כבר קיימת. לא שונה כלום.")
        return
    if "def get_content_version" not in src:
        _fail("get_content_version לא קיים בקובץ — הקובץ לא מה שציפינו לו.")
    if "JSONResponse" not in src:
        _fail("JSONResponse לא מיובא בקובץ.")

    n = src.count(ANCHOR)
    if n != 1:
        _fail(f"נמצאו {n} עוגנים של /content/lite, ציפינו ל-1. לא נוגעים.")

    out = src.replace(ANCHOR, NEW + ANCHOR)

    try:
        compile(out, str(TARGET), "exec")
    except SyntaxError as e:
        _fail(f"התוצאה לא עוברת קומפילציה: {e}")

    if "--check" in sys.argv:
        print("✓ העוגן מתאים והתוצאה עוברת קומפילציה. לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-cver-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print(f"✓ הוחל. גיבוי: {os.path.basename(bak)}")
    print("   צריך: systemctl restart zovex-bot")
    print()
    print("בדיקה אחרי ההפעלה מחדש:")
    print("   curl -s https://zovex.duckdns.org/content/version")
    print("   → {\"version\": 1226}   (המספר יעלה בכל שמירה בפאנל)")


if __name__ == "__main__":
    main()
