#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_feedback_xss — שדה שהרשת שולטת בו מגיע ל-DOM של הפאנל בלי בריחה.

## מה נמצא

ב-‎admin.html‎, ציור שיחת תמיכה:

    const kind = m.kind ? `<span class="badge">${KIND_HE[m.kind]||m.kind}</span> ` : "";

‎KIND_HE‎ ממפה שלושה ערכים ידועים. ערך שאינו בהם **נופל ל-‎m.kind‎
עצמו** — ונכתב ל-‎innerHTML‎ כמו שהוא.

כל שדה אחר באותה פונקציה עובר דרך ‎esc()‎: ‎t.name‎, ‎t.email‎,
‎m.text‎. רק זה לא. וזו לא אי-עקביות סגנונית — ‎kind‎ מגיע מ-
‎/feedback/send‎, שאינו דורש אימות ואינו מגביל את השדה לרשימה סגורה:

    kind: Optional[str] = "support"   # support / review / tip

ההערה מתארת שלושה ערכים. הקוד אינו אוכף אותם.

## למה זה חמור

הפאנל מחזיק את סיסמת הניהול ב-‎PASS‎, משתנה JS רגיל באותו הקשר.
קוד שרץ בדף הזה יכול לקרוא אותה ולקרוא לכל נתיב ‎/panel/*‎. כלומר
‎kind‎ שמכיל ‎<img src=x onerror=...>‎ הופך צפייה בהודעת תמיכה
להשתלטות על הפאנל — בלי שהמנהל עשה דבר חוץ מלפתוח את השיחה.

ההודעות שהתקבלו בפועל (‎SECTEST-F05‎ בתווית) הן בדיוק ההוכחה
שהשדה מגיע ל-DOM. הן לא ניצלו — הן מיפו.

## מה משתנה

‎esc()‎ על הערך שנופל מהמיפוי. המיפוי עצמו לא עובר בריחה כי הוא
קבוע בקוד ולא מגיע מבחוץ — ולכן עברית נשארת עברית.

זו שכבה אחת. השנייה, ברשימה סגורה בצד השרת, נמצאת ב-
‎fix_feedback_abuse.py‎. אף אחת מהן אינה מייתרת את השנייה: בריחה
מגינה גם על רשומות שכבר נכתבו למסד.

    python3 fix_feedback_xss.py --check
    python3 fix_feedback_xss.py
    python3 fix_feedback_xss.py --revert

אין צורך ב-restart: ‎/admin‎ קורא את הקובץ בכל בקשה.
"""
import os
import shutil
import subprocess
import sys
import tempfile

PATH = os.environ.get("ADMIN_HTML", "/opt/zovex-bot/admin.html")
BAK = PATH + ".bak_feedback_xss"
MARK = "fix_feedback_xss"

A_KIND = '''    const kind=m.kind?`<span class="badge">${KIND_HE[m.kind]||m.kind}</span> `:"";
'''

N_KIND = '''    // [fix_feedback_xss] esc על ערך שאינו במיפוי. kind מגיע מ-
    // /feedback/send, שאינו מאומת — וערך לא מוכר נפל קודם ישר
    // ל-innerHTML. המיפוי עצמו קבוע בקוד ולכן נשאר כמו שהוא.
    const kind=m.kind?`<span class="badge">${KIND_HE[m.kind]||esc(m.kind)}</span> `:"";
'''

EDITS = [("תווית סוג ההודעה", A_KIND, N_KIND, 1)]


def js_of(text: str, name: str) -> str:
    i = text.index("function " + name)
    return text[i:text.index("\n}\n", i) + 3]


def validate(out: str) -> None:
    fn = js_of(out, "openThread")
    code = "\n".join(l for l in fn.splitlines()
                     if not l.strip().startswith("//"))

    assert "KIND_HE[m.kind]||esc(m.kind)" in code, "הנפילה מהמיפוי אינה עוברת esc"
    assert "||m.kind}" not in code, "נשארה נפילה גולמית ל-m.kind"

    # ושום שדה אחר לא נשבר תוך כדי
    for field in ("esc(m.text", "esc(t.name"):
        assert field in code, f"{field} נעלם — הבריחה הקיימת נפגעה"

    # ── הבריחה עצמה, מורצת על מטען אמיתי ──────────────────────────────
    # טענה טקסטואלית לא מוכיחה ש-esc באמת מנטרל. מריצים אותה.
    i = out.index("function esc(")
    esc_src = out[i:out.index("\n", i)]
    node = shutil.which("node") or shutil.which("nodejs")
    if not node:
        print("⚠ node אינו מותקן — בדיקת ההרצה דולגה")
        return

    probe = esc_src + r"""
const KIND_HE={support:"תמיכה",review:"חוות דעת",tip:"טיפ"};
const payload = '<img src=x onerror=alert(1)>';
const out = `<span class="badge">${KIND_HE[payload]||esc(payload)}</span> `;
if (out.includes('<img')) { console.error('FAIL: התגית שרדה'); process.exit(1); }
if (!out.includes('&lt;img')) { console.error('FAIL: לא נוצרה בריחה'); process.exit(1); }
// וערך מוכר עדיין מוצג בעברית, לא כקוד
const ok = `<span class="badge">${KIND_HE['support']||esc('support')}</span> `;
if (!ok.includes('תמיכה')) { console.error('FAIL: המיפוי נשבר'); process.exit(1); }
// ומרכאות, שמאפשרות בריחה מתוך ערך תכונה
if (esc('" onmouseover=alert(1) x="').includes('"')) {
  console.error('FAIL: מרכאות אינן נמלטות'); process.exit(1);
}
console.log('OK');
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(probe)
        p = fh.name
    try:
        r = subprocess.run([node, p], capture_output=True, text=True)
        assert r.returncode == 0, \
            f"הבריחה אינה עובדת:\n{(r.stderr or r.stdout).strip()[:300]}"
    finally:
        os.unlink(p)

    # ותחביר הפונקציה כולה — שגיאה כאן מפילה את כל הפאנל
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write("function $(x){return {};}\nvar _curThread,_threads,KIND_HE={};\n"
                 "function esc(s){return s;}\nfunction tsFmt(x){return '';}\n"
                 "function markRead(x){}\n" + fn)
        p2 = fh.name
    try:
        r2 = subprocess.run([node, "--check", p2], capture_output=True, text=True)
        assert r2.returncode == 0, f"התחביר שבור:\n{r2.stderr.strip()[:300]}"
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
    print("רענון קשיח בדפדפן (Ctrl+Shift+R).")


if __name__ == "__main__":
    main()
