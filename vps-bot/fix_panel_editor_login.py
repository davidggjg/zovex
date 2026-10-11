#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_panel_editor_login — כניסה כעורך לפאנל תמיד נכשלת עם "שגיאת שרת".

## מה נמצא

‎add_identity_auth‎-אדיוי... לא, זה ‎PANEL_PASSWORD‎/‎EDITOR_PASSWORD‎: השרת
כבר תומך בשתי רמות גישה (‎panel_role()‎, ‎/panel/role‎, מגבלות עורך ב-
‎/content/save‎ ו-‎/content/mutate‎) — אבל ‎doLogin()‎ ב-‎admin.html‎ עדיין
קוראת ל-‎/panel/api‎ עם ‎action:"list"‎, שעובר דרך ‎check_panel_password‎:

    def check_panel_password(request: Request, password: str):
        \"\"\"גישת אדמין בלבד ... עורך שינסה להגיע לשם יקבל 403\"\"\"
        if panel_role(request, password) != "admin":
            raise HTTPException(status_code=403, ...)

כלומר סיסמת עורך תקפה **תמיד** מקבלת 403 בכניסה עצמה — לפני שהעורך
הגיע לכל מסך. ‎doLogin()‎ מטפל רק ב-401 במפורש; כל קוד אחר (403, וגם
429 מהגנת ה-brute-force) נופל ל"שגיאת שרת" הגנרית. זה נראה כמו תקלת
שרת; זאת תקלת חיווט בלקוח.

ה-endpoint הנכון כבר קיים ולא נקרא מעולם מהכניסה:

    @api.post("/panel/role")
    async def panel_role_get(req: PanelRoleReq, request: Request):
        \"\"\"...הפאנל קורא לזה בכניסה כדי לדעת מה להציג...\"\"\"
        role = panel_role(request, req.password)
        return {"role": role, "max_delete": EDITOR_MAX_DELETE if role=="editor" else None}

## מה משתנה

‎doLogin()‎ קוראת ל-‎/panel/role‎ במקום ל-‎/panel/api‎. הצלחה (admin
**או** editor) נכנסת לפאנל; 401 מציג "סיסמה שגויה"; 429 (ממגבלת
הניסיונות) מציג הודעה מפורשת במקום "שגיאת שרת" גנרי. ‎loadContent()‎,
שרצה מיד אחרי, כבר קוראת ל-‎/content‎ — נתיב ציבורי בלי סיסמה בכלל —
ולכן היא עובדת לשני התפקידים בלי שינוי.

‎ROLE‎ ו-‎EDITOR_MAX_DELETE‎ נשמרים כמשתנים גלובליים לשימוש עתידי (למשל
הסתרת כפתורים שאסורים לעורך) — **לא** ממומש כאן. זה בכוונה: ההגבלות
האמיתיות כבר נאכפות בשרת בכל פעולה (‎/content/save‎, ‎/content/mutate‎
מחזירים 403 ברור לעורך שמנסה לגעת בשידור חי או לחרוג ממכסת המחיקה) —
הסתרת הכפתורים עצמה היא שיפור חוויה, לא תיקון אבטחה, ולכן לא נדרשת
כדי לפתור את "אני לא מצליח להיכנס בכלל".

## למה זה לא יכול לשבור את כניסת המנהל

‎panel_role()‎ מחזירה "admin" כשסיסמת ‎PANEL_PASSWORD‎ נכונה, בדיוק כמו
קודם — רק שעכשיו גם "editor" מצליח, לא רק "admin". מנהל קיים ממשיך
לעבוד זהה לגמרי.

    python3 fix_panel_editor_login.py --check
    python3 fix_panel_editor_login.py
    python3 fix_panel_editor_login.py --revert

אין צורך ב-restart — /admin קורא את הקובץ בכל בקשה. רענון קשיח
בדפדפן (Ctrl+Shift+R) אחרי ההחלה.
"""
import os
import shutil
import subprocess
import sys
import tempfile

PATH = os.environ.get("ADMIN_HTML", "/opt/zovex-bot/admin.html")
BAK = PATH + ".bak_panel_editor_login"
MARK = "fix_panel_editor_login"

A_DECL = '''let PASS="", movies=[], editingId=null, liveEditId=null, _fromUploadCmid=null;
'''

N_DECL = '''let PASS="", movies=[], editingId=null, liveEditId=null, _fromUploadCmid=null;
// [fix_panel_editor_login] תפקיד הכניסה הנוכחית. admin|editor|null.
// נשמר לשימוש עתידי (הסתרת כפתורים אסורים לעורך) — עדיין לא בשימוש כאן;
// ההגבלות עצמן כבר נאכפות בשרת בכל פעולה, לא תלויות במה שמוסתר כאן.
let ROLE=null, EDITOR_MAX_DELETE=null;
'''

A_LOGIN = '''async function doLogin(){
  const p=$("pass").value;
  try{
    const r=await fetch("/panel/api",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({password:p,action:"list"})});
    if(r.status===401){ $("loginErr").textContent="סיסמה שגויה"; return; }
    if(!r.ok){ $("loginErr").textContent="שגיאת שרת"; return; }
    PASS=p; $("login").classList.add("hidden"); $("app").classList.remove("hidden");
    await loadContent();
    loadSupport();   // מעדכן את מונה ההודעות שלא נקראו על הטאב
  }catch(e){ $("loginErr").textContent="אין חיבור לשרת"; }
}
'''

N_LOGIN = '''async function doLogin(){
  const p=$("pass").value;
  try{
    // [fix_panel_editor_login] היה /panel/api עם action:"list", שעובר דרך
    // check_panel_password — admin-בלבד, ולכן סיסמת עורך תקפה קיבלה 403
    // כבר בכניסה. /panel/role בודק את שתי הרמות ומחזיר את התפקיד בפועל.
    const r=await fetch("/panel/role",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({password:p})});
    if(r.status===401){ $("loginErr").textContent="סיסמה שגויה"; return; }
    if(r.status===429){ $("loginErr").textContent="יותר מדי ניסיונות — נסה שוב בעוד כמה דקות"; return; }
    if(!r.ok){ $("loginErr").textContent="שגיאת שרת"; return; }
    const info=await r.json();
    ROLE=info.role; EDITOR_MAX_DELETE=info.max_delete;
    PASS=p; $("login").classList.add("hidden"); $("app").classList.remove("hidden");
    await loadContent();
    loadSupport();   // מעדכן את מונה ההודעות שלא נקראו על הטאב
  }catch(e){ $("loginErr").textContent="אין חיבור לשרת"; }
}
'''

EDITS = [("הצהרת ROLE", A_DECL, N_DECL, 1), ("doLogin", A_LOGIN, N_LOGIN, 1)]


def js_fn(text: str, name: str) -> str:
    i = text.index("function " + name)
    if text[max(0, i - 6):i] == "async ":
        i -= 6
    return text[i:text.index("\n}\n", i) + 3]


def validate(out: str) -> None:
    assert "let ROLE=null, EDITOR_MAX_DELETE=null;" in out, "הצהרת ROLE חסרה"
    fn = js_fn(out, "doLogin")
    code = "\n".join(l for l in fn.splitlines() if not l.strip().startswith("//"))

    assert '"/panel/role"' in code, "עדיין לא קוראים ל-/panel/role"
    assert '"/panel/api"' not in code, "עדיין קוראים ל-/panel/api (admin-בלבד)"
    assert 'action:"list"' not in code, "נשאר payload הישן"
    assert "r.status===429" in code, "429 לא מטופל בנפרד"
    assert code.index("r.status===401") < code.index("r.status===429") < code.index("!r.ok"), \
        "סדר הבדיקות שגוי — קוד ספציפי חייב לקדום לבדיקה הגנרית"
    assert "ROLE=info.role" in code and "EDITOR_MAX_DELETE=info.max_delete" in code, \
        "התפקיד לא נשמר"
    assert "PASS=p;" in code and "await loadContent();" in code and "loadSupport();" in code, \
        "זרימת ההצלחה הקיימת נשברה"

    node = shutil.which("node") or shutil.which("nodejs")
    if not node:
        print("⚠ node אינו מותקן — בדיקת ריצה דולגה")
        return

    # מדמים fetch עם תגובות שונות ומוודאים את הטיפול בכל אחת, בלי רשת אמיתית.
    probe = r"""
const calls = [];
function $(id){ return { value: "x", textContent: "", classList: {add(){}, remove(){}} }; }
async function loadContent(){ calls.push("loadContent"); }
function loadSupport(){ calls.push("loadSupport"); }
""" + fn + r"""
async function run(status, body) {
  calls.length = 0;
  global.fetch = async () => ({ status, ok: status >= 200 && status < 300,
                                 json: async () => body });
  ROLE = null; EDITOR_MAX_DELETE = null; PASS = "";
  await doLogin();
  return { calls: calls.slice(), ROLE, EDITOR_MAX_DELETE, PASS };
}
(async () => {
  let r;
  r = await run(401, {});
  if (r.calls.length) { console.error("FAIL: 401 still proceeded"); process.exit(1); }

  r = await run(429, {});
  if (r.calls.length) { console.error("FAIL: 429 still proceeded"); process.exit(1); }

  r = await run(200, {role: "editor", max_delete: 5});
  if (r.ROLE !== "editor" || r.EDITOR_MAX_DELETE !== 5) {
    console.error("FAIL: editor role not captured"); process.exit(1);
  }
  if (r.PASS !== "x" || !r.calls.includes("loadContent") || !r.calls.includes("loadSupport")) {
    console.error("FAIL: editor login did not proceed into the app"); process.exit(1);
  }

  r = await run(200, {role: "admin", max_delete: null});
  if (r.ROLE !== "admin" || r.PASS !== "x") {
    console.error("FAIL: admin login broke"); process.exit(1);
  }
  console.log("OK");
})();
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(probe)
        p = fh.name
    try:
        r = subprocess.run([node, p], capture_output=True, text=True)
        assert r.returncode == 0, \
            f"ההתנהגות בפועל לא תואמת:\n{(r.stderr or r.stdout).strip()[:500]}"
    finally:
        os.unlink(p)


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
            sys.exit(f"✗ העוגן '{label}' נמצא {got} פעמים (צפוי {want}) — לא נוגע בכלום.")
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
