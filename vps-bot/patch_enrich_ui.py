#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# כרטיס הסורק בפאנל: הפעלה, עצירה, התקדמות, והצעות הקטגוריה.
#
# הסריקה כבר רצה בשרת כמשימת asyncio, ולכן היא ממשיכה גם כשהדפדפן סגור.
# הכרטיס הזה הוא חלון להסתכל דרכו — לא המנוע. סגירת הדפדפן עוצרת רק את
# הסקר (poll), לא את העבודה.
#
# ‎setInterval‎ פועל רק בזמן שהלשונית פתוחה ונעצר ביציאה ממנה: סקר שממשיך
# ברקע על פאנל שנשכח פתוח שולח בקשה כל שלוש שניות לנצח.
#
#   python3 patch_enrich_ui.py [נתיב ל-admin.html]
#   python3 patch_enrich_ui.py --revert
# ─────────────────────────────────────────────────────────────────────────────
import io
import os
import shutil
import sys

H = "/opt/zovex-bot/admin.html"
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if args:
    H = args[0]
REVERT = "--revert" in sys.argv
MARK = "enrich_ui"

OLD_PANE = '''<div id="pane-notrailer" class="hidden">
  <div class="card">'''
NEW_PANE = '''<div id="pane-notrailer" class="hidden">
  <!-- [enrich_ui] הסורק רץ בשרת; הכרטיס הזה רק מציג אותו -->
  <div class="card">
    <h2>🔎 סורק השלמות</h2>
    <p class="muted">ממלא תיאורים ופוסטרים חסרים מ-TMDB — תקציר שקיים רק
    באנגלית מתורגם לעברית — ואוסף הצעות לשיוך קטגוריה.
    <b>רץ בשרת: אפשר לסגור את הדפדפן והוא ימשיך.</b></p>
    <p class="muted">שדות שכבר מלאים לא נדרסים. קטגוריות רק מוצעות —
    שום דבר לא משתנה עד שתאשר.</p>
    <div id="enStat" class="muted">טוען…</div>
    <div style="background:#e9e9ed;border-radius:8px;height:10px;overflow:hidden;margin:8px 0">
      <div id="enBar" style="height:100%;width:0;background:#1a7f37;transition:width .4s"></div>
    </div>
    <div class="row" style="gap:6px;flex-wrap:wrap">
      <button class="mini" id="enStart" onclick="enrichStart()">▶ הפעל סריקה</button>
      <button class="mini sec" id="enStop" onclick="enrichStop()">■ עצור</button>
      <button class="mini sec" onclick="recatList()">📋 הצעות קטגוריה</button>
    </div>
    <div id="enSugg" style="margin-top:12px"></div>
  </div>
  <div class="card">'''

OLD_HOOK = '''  if(n==="notrailer") loadNoTrailer();'''
NEW_HOOK = '''  if(n==="notrailer"){ loadNoTrailer(); enrichPollStart(); } else enrichPollStop();'''

OLD_JS = '''let _nt = null;'''
NEW_JS = '''// ── [enrich_ui] סורק ההשלמות ────────────────────────────────────────────────
let _enTimer = null;
function enrichPollStart(){ enrichStatus(); if(!_enTimer) _enTimer=setInterval(enrichStatus,3000); }
// נעצר ביציאה מהלשונית: סקר שממשיך על פאנל שנשכח פתוח שולח בקשה כל 3 שניות לנצח
function enrichPollStop(){ if(_enTimer){ clearInterval(_enTimer); _enTimer=null; } }
async function enrichPost(path){
  const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},
                            body:JSON.stringify({password:PASS})});
  if(!r.ok) throw new Error("שגיאה "+r.status);
  return r.json();
}
function _hms(s){ s=Math.max(0,s|0); const h=s/3600|0,m=(s%3600)/60|0;
  return h? `${h} שע' ${m} דק'` : (m? `${m} דק'` : `${s} שנ'`); }
async function enrichStatus(){
  try{
    const d=await enrichPost("/panel/enrich/status");
    const pct = d.total ? Math.round(d.done/d.total*100) : 0;
    $("enBar").style.width = pct+"%";
    $("enStart").disabled = !!d.running;
    $("enStop").disabled  = !d.running;
    const warn = (!d.tmdb?'<span class="err">אין מפתח TMDB</span> · ':'')+
                 (!d.groq?'<span class="muted">בלי Groq — תקצירים באנגלית לא יתורגמו</span> · ':'');
    $("enStat").innerHTML = warn +
      (d.running ? `<b>רץ</b> · ${d.done}/${d.total} (${pct}%)`+
                   (d.eta?` · נותרו ${_hms(d.eta)}`:"")
                 : (d.done? `<b>הסתיים</b> · ${d.done}/${d.total}` : "לא רץ")) +
      `<div style="margin-top:4px;font-size:12px">`+
      `התאמות TMDB: <b>${d.matched_tmdb||0}</b> · `+
      `תיאורים: <b>${d.filled_desc||0}</b> (מתורגמים ${d.translated||0}) · `+
      `פוסטרים: <b>${d.filled_poster||0}</b> · `+
      `הצעות קטגוריה: <b>${d.suggestions||0}</b> · `+
      `בלי TMDB: ${d.skipped_no_tmdb||0} · שגיאות: ${d.errors||0}</div>`;
  }catch(e){ $("enStat").innerHTML='<span class="err">'+e.message+'</span>'; }
}
async function enrichStart(){
  try{ const d=await enrichPost("/panel/enrich/start");
       if(!d.ok) alert(d.reason||"לא התחיל"); enrichStatus(); }
  catch(e){ alert(e.message); }
}
async function enrichStop(){
  try{ await enrichPost("/panel/enrich/stop"); enrichStatus(); }
  catch(e){ alert(e.message); }
}
async function recatList(){
  $("enSugg").innerHTML="טוען…";
  try{
    const d=await enrichPost("/panel/recat/list");
    if(!d.count){ $("enSugg").innerHTML='<div class="muted">אין הצעות. הרץ סריקה קודם.</div>'; return; }
    const rows=d.items.slice(0,400).map(x=>`<div class="item">
      <div class="meta"><div class="t">${x.kind==="s"?"📺":"🎬"} ${esc(x.name||"—")}</div>
      <div class="s">${esc(x.from||"— ללא —")} → <b>${esc(x.to)}</b>${x.by==="groq"?' · <span class="muted">לפי Groq</span>':''}</div></div></div>`).join("");
    $("enSugg").innerHTML =
      `<div class="row" style="gap:6px;flex-wrap:wrap;margin-bottom:8px">
         <b>${d.count} הצעות</b>
         <button class="mini" onclick="recatApply()">✓ אשר הכל</button>
         <button class="mini sec" onclick="recatUndo()">↩ בטל שינוי אחרון</button>
       </div>` + rows +
      (d.count>400?'<div class="muted">מוצגות 400 הראשונות</div>':'');
  }catch(e){ $("enSugg").innerHTML='<span class="err">'+e.message+'</span>'; }
}
async function recatApply(){
  if(!confirm("להחיל את כל ההצעות?\\n\\nיישמר יומן ביטול — אפשר להחזיר בלחיצה אחת.")) return;
  try{ const d=await enrichPost("/panel/recat/apply");
       alert(d.ok?`שונו ${d.changed} פריטים.`:(d.reason||"נכשל")); recatList(); }
  catch(e){ alert(e.message); }
}
async function recatUndo(){
  if(!confirm("להחזיר את הקטגוריות כפי שהיו לפני ההחלה האחרונה?")) return;
  try{ const d=await enrichPost("/panel/recat/undo");
       alert(d.ok?`הוחזרו ${d.restored} פריטים.`:(d.reason||"אין מה לבטל")); recatList(); }
  catch(e){ alert(e.message); }
}

let _nt = null;'''


def main():
    bak = H + ".before_enrichui"
    if REVERT:
        if not os.path.exists(bak):
            sys.exit("❌ אין גיבוי לשחזר")
        shutil.copy(bak, H)
        print("✓ שוחזר")
        return
    try:
        h = io.open(H, encoding="utf-8").read()
    except OSError as e:
        sys.exit(f"❌ לא נפתח {H}: {e}")
    if MARK in h:
        print("✓ כבר מתוקן — מדלג")
        return
    for i, old in enumerate((OLD_PANE, OLD_HOOK, OLD_JS), 1):
        if h.count(old) != 1:
            sys.exit(f"❌ קטע {i} נמצא {h.count(old)} פעמים. לא נגעתי בכלום.")
    shutil.copy(H, bak)
    h = h.replace(OLD_PANE, NEW_PANE, 1).replace(OLD_HOOK, NEW_HOOK, 1)
    h = h.replace(OLD_JS, NEW_JS, 1)
    io.open(H, "w", encoding="utf-8").write(h)
    print(f"✓ הוחל. גיבוי: {bak}")
    print("  כרטיס הסורק בלשונית «חסרים»")


if __name__ == "__main__":
    main()
