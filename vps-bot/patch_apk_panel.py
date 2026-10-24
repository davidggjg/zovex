#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# הפאנל קורא את הקישור מהשדה שנדרס, ולכן מוחק אותו בכל טעינה.
#
# ‎loadVersion‎ טוען את ‎v.url‎ מ-‎/app/version‎ — ושם הוא כבר נדרס לכתובת
# של השרת עצמו, כדי שהאפליקציה תוריד מהדומיין שלנו. התוצאה: תיבת הקישור
# מתמלאת ב-‎…/app/apk‎ במקום במה שכתבת, והשמירה הבאה כותבת את זה לקובץ.
# כלומר השדה מוחק את עצמו, וזה מה שדווח כ"הורס את הקישור".
#
# התיקון בצד השרת (patch_apk_source.py) מוסיף ‎source_url‎ — הערך האמיתי,
# לפני הדריסה. כאן קוראים ממנו.
#
# בנוסף: הכיתוב בשדה מתוקן. "קישור לעדכון (APK / דף שחרור)" הטעה — אסור
# לשים שם דף שחרור, כי השרת מוריד משם קובץ. חייבת להיות כתובת ישירה ל-APK.
#
#   python3 patch_apk_panel.py [נתיב ל-admin.html]
# ─────────────────────────────────────────────────────────────────────────────
import io
import sys

P = sys.argv[1] if len(sys.argv) > 1 else "/opt/zovex-bot/admin.html"
MARK = "v.source_url"

OLD_LOAD = '''    $("v_url").value=v.url||""; $("v_notes").value=v.notes||""; }catch{}'''
NEW_LOAD = '''    // source_url ולא url: ב-/app/version השדה url נדרס לכתובת של השרת
    // עצמו (כדי שהאפליקציה תוריד מהדומיין שלנו), ולכן קריאה ממנו מילאה
    // את התיבה בכתובת השרת ומחקה את מה שהמנהל כתב בשמירה הבאה.
    $("v_url").value=(v.source_url!==undefined?v.source_url:"")||"";
    $("v_notes").value=v.notes||""; }catch{}'''

OLD_PH = '''      <input id="v_url" placeholder="קישור לעדכון (APK / דף שחרור)" style="margin-top:8px">'''
NEW_PH = '''      <input id="v_url" placeholder="כתובת ישירה לקובץ ה-APK (לא דף שחרור)" style="margin-top:8px">
      <div style="font-size:12px;color:#888;margin-top:4px;line-height:1.5">
        מכאן השרת מוריד את הקובץ ומגיש אותו מהדומיין שלנו. חייבת להיות
        כתובת שמורידה APK ישירות — דף אינטרנט יישמר כקובץ פגום.<br>
        בגיטהאב: <code>…/releases/latest/download/zovex.apk</code><br>
        שמירה מפעילה הורדה מחדש ברקע; הבדיקה בכפתור "מצב APK".
      </div>'''


def main():
    try:
        s = io.open(P, encoding="utf-8").read()
    except OSError as e:
        sys.exit(f"❌ לא נפתח {P}: {e}")

    if MARK in s:
        print("✓ כבר מתוקן — מדלג")
        return

    for name, old in (("loadVersion", OLD_LOAD), ("placeholder", OLD_PH)):
        if s.count(old) != 1:
            sys.exit(f"❌ הקטע '{name}' לא נמצא בדיוק פעם אחת "
                     f"({s.count(old)}) ב-{P} — לא נגעתי בכלום.")

    bak = P + ".before_apksrc"
    io.open(bak, "w", encoding="utf-8").write(s)
    s = s.replace(OLD_LOAD, NEW_LOAD, 1).replace(OLD_PH, NEW_PH, 1)
    io.open(P, "w", encoding="utf-8").write(s)
    print(f"✓ הוחל. גיבוי: {bak}")


if __name__ == "__main__":
    main()
