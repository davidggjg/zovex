#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_panel_save_errors — שהפאנל יגיד **למה** השמירה נכשלה.

## מה קרה

מילוי "גרסה אחרונה" ו"מינימלית", לחיצה על שמור — ו-‎/app/version‎
המשיך להכריז על הגרסה הישנה. בלי שום רמז למה.

הסיבה אינה בשרת. הוא עונה בדיוק מה הבעיה:

    401  {"detail":"סיסמה שגויה"}
    403  {"detail":"הפעולה הזו מותרת למנהל הראשי בלבד"}

שני מצבים שונים לחלוטין — סיסמה לא נכונה מול סיסמת **עורך** שתקפה
אבל אינה מנהל ראשי. הפאנל זרק את שניהם:

    if(!r.ok) throw new Error("שגיאה");
    ...
    catch(e){ ... 'שמירה נכשלה' }

הגוף נקרא? לא. הסטטוס הוצג? לא. מה שנשאר על המסך הוא "שמירה נכשלה"
בשורה אפורה קטנה — שאפשר גם לא להבחין בה, ובוודאי אי אפשר לפעול
לפיה. הודעת שגיאה שאינה אומרת מה לעשות שקולה לשתיקה.

## ומה שגרוע ממנה

    $("verMsg").innerHTML='<span class="ok">נשמר ✓</span>';

"נשמר" נכתב על סמך **קוד התשובה**, בלי לשאול את השרת מה הוא מכריז
עכשיו. כאן זה יצא נכון במקרה, אבל זו הכרזה על הצלחה בלי לבדוק
אותה — ועדכון כפוי הוא בדיוק המקום שבו אסור להסתמך על כך.

## מה משתנה

* הגוף נקרא, וה-‎detail‎ מהשרת מוצג יחד עם הסטטוס.
* אחרי שמירה מוצלחת הפאנל שואל את ‎/app/version‎ — אותה שאלה בדיוק
  שהאפליקציה תשאל — ומציג את מה שחזר. "נשמר" הופך לעובדה נמדדת.

    python3 fix_panel_save_errors.py --check
    python3 fix_panel_save_errors.py
    python3 fix_panel_save_errors.py --revert

אין צורך ב-restart: ‎/admin‎ קורא את הקובץ בכל בקשה.
"""
import os
import shutil
import subprocess
import sys
import tempfile

PATH = os.environ.get("ADMIN_HTML", "/opt/zovex-bot/admin.html")
BAK = PATH + ".bak_panel_save_errors"
MARK = "fix_panel_save_errors"

A_SAVE = '''async function saveVersion(){
  $("verMsg").textContent="שומר...";
  try{
    const r=await fetch("/app/version/set",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({password:PASS,latest:$("v_latest").value,min:$("v_min").value,
        url:$("v_url").value,notes:$("v_notes").value})});
    if(!r.ok) throw new Error("שגיאה");
    $("verMsg").innerHTML='<span class="ok">נשמר ✓</span>';
  }catch(e){ $("verMsg").innerHTML='<span class="err">שמירה נכשלה</span>'; }
}
'''

N_SAVE = r'''async function saveVersion(){
  $("verMsg").textContent="שומר...";
  try{
    const r=await fetch("/app/version/set",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({password:PASS,latest:$("v_latest").value,min:$("v_min").value,
        url:$("v_url").value,notes:$("v_notes").value})});
    // [fix_panel_save_errors] הסיבה, ולא "שגיאה". השרת מבדיל בין 401
    // (סיסמה שגויה) ל-403 (סיסמת עורך תקפה שאינה מנהל ראשי) — שני
    // מצבים עם פתרונות שונים לגמרי, שהוצגו קודם בדיוק אותו דבר.
    let d={}; try{ d=await r.json(); }catch(_){}
    if(!r.ok) throw new Error((d.detail||"שגיאה")+" ["+r.status+"]");
    // ולא מכריזים "נשמר" על סמך קוד התשובה. שואלים את /app/version —
    // אותה שאלה בדיוק שהאפליקציה שואלת בהפעלה — ומציגים מה שחזר.
    const g=await (await fetch("/app/version",{cache:"no-store"})).json();
    $("verMsg").innerHTML='<span class="ok">נשמר ✓ — השרת מכריז: אחרונה '+
      (g.latest||"?")+' · מינימלית '+(g.min||"?")+'</span>';
  }catch(e){ $("verMsg").innerHTML='<span class="err">שמירה נכשלה: '+e.message+'</span>'; }
}
'''

EDITS = [("שמירת גרסה", A_SAVE, N_SAVE, 1)]


def js_of(text: str, name: str) -> str:
    """גוף הפונקציה מתוך ה-HTML, מתחילתה ועד הסוגר בעמודה 0."""
    i = text.index("async function " + name)
    j = text.index("\n}\n", i) + 3
    return text[i:j]


def validate(out: str) -> None:
    fn = js_of(out, "saveVersion")

    # ההערות מוסרות לפני הבדיקה. בלי זה הטענה "קוראים את /app/version"
    # עברה **בזכות הערה שמזכירה את הנתיב**, גם כשהקריאה עצמה נמחקה —
    # כלומר שומר שמאשר את עצמו. נתפס במוטציה.
    code = "\n".join(l for l in fn.splitlines()
                     if not l.strip().startswith("//"))

    assert 'throw new Error("שגיאה")' not in code, "השגיאה הגנרית נשארה"
    assert "d.detail" in code, "ה-detail מהשרת אינו מוצג"
    assert "r.status" in code, "הסטטוס אינו מוצג"
    assert 'fetch("/app/version"' in code, "אין אימות מול השרת אחרי השמירה"
    assert code.index('fetch("/app/version"') > code.index("if(!r.ok)"), \
        "האימות קודם לבדיקת הכישלון"
    assert out.count("async function saveVersion") == 1, "הפונקציה שוכפלה"

    # ── והתחביר, מורץ ───────────────────────────────────────────────────
    # הפאנל הוא קובץ אחד גדול: שגיאת תחביר באחת מהפונקציות מפילה את כל
    # ה-script, וכל הכפתורים בדף מפסיקים להגיב בבת אחת. זה כבר קרה כאן
    # פעם, בדף העלאת ה-APK, ועלה שעה.
    node = shutil.which("node") or shutil.which("nodejs")
    if not node:
        print("⚠ node אינו מותקן — בדיקת התחביר דולגה")
        return
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write("function $(x){return {};}\nvar PASS='';\n" + fn)
        p = fh.name
    try:
        r = subprocess.run([node, "--check", p], capture_output=True, text=True)
        assert r.returncode == 0, f"התחביר שבור:\n{r.stderr.strip()[:400]}"
    finally:
        os.unlink(p)

    # ומוטציה: גרש לא סגור חייב להיתפס, אחרת הבדיקה חסרת ערך
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write("var x='לא נסגר\n")
        p2 = fh.name
    try:
        r2 = subprocess.run([node, "--check", p2], capture_output=True, text=True)
        assert r2.returncode != 0, "node --check אינו תופס שגיאות — אין טעם"
    finally:
        os.unlink(p2)


def main() -> None:
    if not os.path.exists(PATH):
        sys.exit(f"אין קובץ ב-{PATH} (אפשר ADMIN_HTML=...)")
    with open(PATH, encoding="utf-8") as fh:
        src = fh.read()

    if "--revert" in sys.argv:
        if not os.path.exists(BAK):
            sys.exit(f"אין גיבוי ב-{BAK}")
        shutil.copy2(BAK, PATH)
        print(f"✓ שוחזר מ-{BAK}")
        return

    if MARK in src:
        print("כבר מותקן.")
        return

    out = src
    for label, a, n, want in EDITS:
        got = out.count(a)
        if got != want:
            sys.exit(f"✗ העוגן '{label}' נמצא {got} פעמים (צפוי {want}) — "
                     "לא נוגע בכלום.")
        out = out.replace(a, n)

    validate(out)
    print("✓ כל הבדיקות עברו")
    if "--check" in sys.argv:
        print("--check: שום דבר לא נכתב.")
        return

    shutil.copy2(PATH, BAK)
    with open(PATH, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(f"✓ הוחל. גיבוי: {BAK}")
    print()
    print("אין צורך ב-restart — /admin קורא את הקובץ בכל בקשה.")
    print("רענון קשיח בדפדפן (Ctrl+Shift+R) ואז נסה לשמור שוב.")


if __name__ == "__main__":
    main()
