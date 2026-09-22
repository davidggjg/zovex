#!/usr/bin/env python3
"""fix_panel_msg_read — הודעה שקראתי תיחשב קראתי, ולכל הודעה יהיה תאריך ושעה.

## שני דברים קטנים בפאנל

**1. המונה לא נעלם כשקוראים.** ‎unread_admin מתאפס במקום אחד בלבד —
‎/feedback/reply. כלומר פתחת את השיחה, קראת אותה, ואם לא ענית, הספרה
על טאב "תמיכה" ממשיכה להגיד שיש הודעה שמחכה. אין לזה שום נתיב אחר:

    th["unread_admin"] = False      # רק כאן, ורק בתשובה

מעכשיו יש ‎POST /feedback/read — מוגן באותה סיסמה — והפאנל קורא לו
ברגע שהשיחה נפתחת. השרת מחזיר גם את המונה המעודכן, ולכן הספרה על
הטאב יורדת מיד, בלי לרענן.

אם הבקשה נכשלת, השיחה נשארת מסומנת "חדש". עדיף שהסימון יישאר ממה
שייראה נקרא בלי שנשמר.

**2. אין תאריך ושעה.** הן נשמרות בכל הודעה כבר עכשיו (‎ts) ופשוט לא
הוצגו. מעכשיו מוצגות מתחת לכל בועה, ובשורת השיחה — מתי היא עודכנה.

יש שם מלכודת: השרת כותב ‎datetime.utcnow().isoformat() — בלי סימון
אזור זמן. ‎new Date("2026-09-21T18:04:00") בדפדפן קורא מחרוזת כזאת
כזמן **מקומי**, כלומר השעות היו מוצגות שלוש שעות אחורה. לכן
‎tsFmt מוסיפה Z כשאין סיומת אזור, ואז ה-toLocaleString מתרגם לשעון
ישראל נכון.

## מה נוגעים

    /opt/zovex-bot/main.py       — נתיב /feedback/read
    /opt/zovex-bot/admin.html    — סימון בפתיחה + תאריך ושעה

שני הקבצים נבדקים לפני שנכתב משהו, ושניהם נכתבים או אף אחד מהם.

    python3 fix_panel_msg_read.py --check
    python3 fix_panel_msg_read.py
    python3 fix_panel_msg_read.py --revert
"""
import ast
import os
import shutil
import sys

PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
HTML = os.environ.get("ADMIN_HTML", "/opt/zovex-bot/admin.html")
BAK = PATH + ".bak_panel_msg_read"
BAK_HTML = HTML + ".bak_panel_msg_read"
MARK = "/feedback/read"

# ── main.py: הנתיב החדש, לפני רשימת השיחות ────────────────────────────────
PA = "class FeedbackListReq(BaseModel):\n"
PN = '''class FeedbackReadReq(BaseModel):
    password: str
    user_id: str

@api.post("/feedback/read")
async def feedback_read(req: FeedbackReadReq, request: Request):
    """מסמן שיחה כנקראה כשהמנהל *פותח* אותה, ולא רק כשהוא מגיב.

    עד עכשיו unread_admin התאפס רק ב-/feedback/reply, ולכן הספרה על טאב
    התמיכה נשארה דלוקה אחרי קריאה בלי מענה. ראה fix_panel_msg_read.py.

    מחזיר גם את המונה הכולל, כדי שהפאנל יוריד את הספרה בלי לטעון הכל
    מחדש.
    """
    check_panel_password(request, req.password)
    d = load_feedback()
    th = d.get(req.user_id)
    if not th:
        raise HTTPException(status_code=404, detail="לא נמצא")
    if th.get("unread_admin"):
        th["unread_admin"] = False
        save_feedback(d)
    return {"ok": True,
            "unread": sum(1 for t in d.values() if t.get("unread_admin"))}

class FeedbackListReq(BaseModel):
'''

# ── admin.html 1: עזר לתאריך ושעה + סימון כנקרא ───────────────────────────
HA1 = "let _threads=[], _curThread=null;\n"
HN1 = '''// [fix_panel_msg_read]
// ts נשמר כ-datetime.utcnow().isoformat() — בלי סימון אזור זמן. דפדפן
// קורא מחרוזת כזאת כזמן מקומי, וכל השעות היו מוצגות שלוש שעות אחורה.
// לכן מוסיפים Z כשאין סיומת אזור, ורק אז מתרגמים לשעון המקומי.
function tsFmt(s){
  if(!s) return "";
  const iso=/[zZ]|[+-]\\d\\d:?\\d\\d$/.test(s) ? s : s+"Z";
  const d=new Date(iso);
  if(isNaN(d.getTime())) return "";
  return d.toLocaleString("he-IL",{day:"2-digit",month:"2-digit",
    year:"2-digit",hour:"2-digit",minute:"2-digit"});
}
// [fix_panel_msg_read]
// מסמן את השיחה כנקראה ברגע שפתחתי אותה. אם הבקשה נכשלה — משאירים
// את הסימון "חדש", כי עדיף שיישאר ממה שייראה נקרא בלי שנשמר.
async function markRead(t){
  if(!t || !t.unread_admin) return;
  try{
    const r=await fetch("/feedback/read",{method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({password:PASS,user_id:t.user_id})});
    if(!r.ok) return;
    const d=await r.json();
    t.unread_admin=false;
    renderThreads();
    updateSupBadge(d.unread||0);
  }catch(e){}
}
let _threads=[], _curThread=null;
'''

# ── admin.html 2: שורת השיחה — מתי עודכנה ─────────────────────────────────
HA2 = ('      <div class="s">${who}${preview}</div></div></div>`; })'
       '.join("");\n')
HN2 = ('      <div class="s">${who}${preview}</div>\n'
       '      <div class="s" style="font-size:11px;opacity:.6">'
       '${tsFmt(t.updated||(last&&last.ts))}</div>'
       '</div></div>`; }).join("");\n')

# ── admin.html 3: תאריך ושעה בכל בועה ─────────────────────────────────────
# בלי רווח או שורה חדשה בין הטקסט לתאריך: לבועה יש white-space:pre-wrap,
# וכל רווח שהיה נכנס לתבנית היה נראה על המסך.
HA3 = ('        ${mine?\'\':kind}${esc(m.text||"")}</div></div>`; })'
       '.join("");\n')
HN3 = ('        ${mine?\'\':kind}${esc(m.text||"")}'
       '<div style="font-size:10px;opacity:.6;margin-top:4px;direction:ltr;'
       'text-align:${mine?\'left\':\'right\'}">${tsFmt(m.ts)}</div>'
       '</div></div>`; }).join("");\n')

# ── admin.html 4: לסמן כנקרא בפתיחת השיחה ─────────────────────────────────
HA4 = ('    <div id="supReplyMsg" class="muted" style="margin-top:6px">'
       '</div>`;\n}\n')
HN4 = ('    <div id="supReplyMsg" class="muted" style="margin-top:6px">'
       '</div>`;\n'
       '  markRead(t);   // [fix_panel_msg_read] נפתחה = נקראה\n'
       '}\n')

HTML_EDITS = [("עזר תאריך וסימון", HA1, HN1),
              ("שורת השיחה", HA2, HN2),
              ("בועת ההודעה", HA3, HN3),
              ("סימון בפתיחה", HA4, HN4)]


def fn_source(src, name):
    for n in ast.walk(ast.parse(src)):
        if getattr(n, "name", "") == name and isinstance(
                n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ast.get_source_segment(src, n)
    return None


def validate_py(s):
    compile(s, PATH, "exec")
    names = {n.name for n in ast.walk(ast.parse(s))
             if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))}
    for f in ("feedback_read", "feedback_reply", "feedback_all",
              "feedback_send", "feedback_mine"):
        assert f in names, f"{f} חסרה"
    assert s.count('@api.post("/feedback/read")') == 1, "הנתיב לא נוצר פעם אחת"
    body = fn_source(s, "feedback_read")
    assert "check_panel_password" in body, "הנתיב בלי בדיקת סיסמה"
    assert 'th["unread_admin"] = False' in body, "הנתיב לא מסמן כנקרא"
    # התשובה של המנהל ממשיכה לאפס כמו קודם — לא נגעתי בה
    assert s.count('th["unread_admin"] = False') == 2, "שינוי לא צפוי ב-reply"


def validate_html(h):
    assert h.count("function tsFmt(") == 1, "tsFmt לא נוצרה פעם אחת"
    assert h.count("async function markRead(") == 1, "markRead לא נוצרה"
    assert h.count("markRead(t);") == 1, "markRead לא נקראת בפתיחה"
    assert h.count("let _threads=[], _curThread=null;") == 1, \
        "המשתנים הוכפלו"
    assert h.count("tsFmt(m.ts)") == 1, "אין שעה על ההודעה"
    assert h.count("tsFmt(t.updated") == 1, "אין שעה על שורת השיחה"
    # הקריאה לסימון חייבת לשבת בתוך openThread, אחרי בניית הצ'אט
    i = h.index("function openThread(")
    j = h.index("async function sendReply(")
    assert i < h.index("markRead(t);") < j, "הסימון לא בתוך openThread"
    # וסדר ההגדרות: markRead מוגדרת לפני openThread מבחינת קריאה בזמן ריצה
    # זה לא מחייב, כי הצהרות פונקציה מורמות — אבל renderThreads ו-
    # updateSupBadge חייבות להתקיים.
    for f in ("function renderThreads(", "function updateSupBadge("):
        assert h.count(f) == 1, f"{f} חסרה או הוכפלה"


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

    if MARK in s and "fix_panel_msg_read" in h:
        print("כבר מותקן. אין מה לעשות.")
        return 0

    for need in ("def load_feedback", "def save_feedback",
                 "def check_panel_password"):
        if need not in s:
            print(f"❌ לא מצאתי {need} ב-main.py — לא נוגע.")
            return 1

    # main.py
    if s.count(PA) != 1:
        print(f"❌ העוגן ב-main.py נמצא {s.count(PA)} פעמים (ציפיתי 1).")
        return 1
    out_py = s.replace(PA, PN, 1)

    # admin.html
    out_html = h
    for name, a, b in HTML_EDITS:
        n = out_html.count(a)
        if n != 1:
            print(f"❌ העוגן '{name}' ב-admin.html נמצא {n} פעמים (ציפיתי 1).")
            print("   הפאנל שונה ממה שציפיתי — לא נוגע בכלום.")
            return 1
        out_html = out_html.replace(a, b, 1)

    try:
        validate_py(out_py)
        validate_html(out_html)
    except Exception as e:
        print(f"❌ התוצאה לא תקינה ({e}) — לא נכתב כלום.")
        return 1

    print(f"יעד:   {PATH}")
    print(f"       {HTML}")
    print("שינוי: פתיחת שיחה מסמנת אותה כנקראה · תאריך ושעה בכל הודעה")
    if arg == "--check":
        print("--check: שום דבר לא נכתב.")
        return 0

    for src, bak in ((PATH, BAK), (HTML, BAK_HTML)):
        if not os.path.exists(bak):
            shutil.copyfile(src, bak)
    for dst, data, suf in ((PATH, out_py, ".tmp_pmr"),
                           (HTML, out_html, ".tmp_pmr")):
        tmp = dst + suf
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, dst)

    print(f"✓ הוחל · גיבויים: {BAK}")
    print(f"              {BAK_HTML}")
    print("  הרץ:  systemctl restart zovex-bot")
    print("  ואז Ctrl+Shift+R בפאנל — הדפדפן שומר את admin.html.")
    print("  לביטול:  python3 fix_panel_msg_read.py --revert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
