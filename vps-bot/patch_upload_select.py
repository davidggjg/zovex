#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_upload_select — בחירת פרקים ידנית באזור הממתינים + "אחד את הנבחרים".

כששתי סדרות (או יותר) מתפצלות יחד ברשימת הממתינים, "אחד את כל הממתינים"
מאחד אותן בטעות לסדרה אחת. כאן מוסיפים:

  · צ'קבוקס לכל פרק ממתין (וגם לכל סרט).
  · סרגל "אחד את הנבחרים לסדרה אחת" — בוחרים פרקים של סדרה אחת, שם,
    ואיחוד; אח"כ חוזרים על זה לסדרה הבאה.
  · מספור-מחדש אוטומטי ע1פ1..ע1פN לפי סדר ההעלאה (כי כשזה מתפצל כל
    פרק נקלט כ-ע1פ1) — ניתן לכיבוי בצ'קבוקס.

admin.html בלבד — אין נגיעה בקוד השרת ואין restart. עצמאי מ-
patch_series_tools.py (מרקר נפרד), אפשר להחיל את שניהם בכל סדר.

    python3 patch_upload_select.py --check
    python3 patch_upload_select.py
    python3 patch_upload_select.py --revert
"""
import os, shutil, sys

PATH = os.environ.get("PANEL", "/opt/zovex-bot/admin.html")
MARKER = "mergeSelectedUploads"

# ── עריכה 1: סרגל הבחירה (HTML) ──────────────────────────────────────────────
A1 = r'''      <div id="mrgMsg" class="muted" style="margin-top:6px"></div>
    </div>
    <div class="card"><div class="toprow"><h2>העלאות שממתינות מהבוט</h2>'''
N1 = r'''      <div id="mrgMsg" class="muted" style="margin-top:6px"></div>
    </div>
    <div id="selBar" class="card hidden" style="border:1px solid #5e5ce6;position:sticky;top:0;z-index:5">
      <h2>🔗 אחד את הנבחרים לסדרה אחת (<span id="selCount">0</span> נבחרו)</h2>
      <div class="muted">כמה סדרות התפצלו יחד? סמן ✓ רק את הפרקים של סדרה אחת, הקלד שם, ואחד. אח"כ סמן את השאר לסדרה הבאה.</div>
      <input id="sel_name" placeholder="שם הסדרה (למשל: פאודה)" style="margin-top:8px">
      <div style="margin-top:8px"><label>קטגוריה</label><select id="sel_cat">
        <option value="סדרות">סדרות</option>
        <option value="סדרות לילדים">סדרות לילדים</option>
        <option value="סדרות ישראליות">סדרות ישראליות</option>
        <option value="אנימה">אנימה</option>
      </select></div>
      <label style="display:flex;align-items:center;gap:6px;margin-top:8px"><input type="checkbox" id="sel_renum" checked> מספר את הפרקים מחדש ע1פ1..ע1פN לפי סדר ההעלאה</label>
      <div class="row" style="margin-top:8px">
        <button class="green" style="flex:1" onclick="mergeSelectedUploads()">🔗 אחד את הנבחרים</button>
        <button class="gray" onclick="clearSelUploads()">נקה בחירה</button></div>
      <div id="selMsg" class="muted" style="margin-top:6px"></div>
    </div>
    <div class="card"><div class="toprow"><h2>העלאות שממתינות מהבוט</h2>'''

# ── עריכה 2: state + פונקציות ────────────────────────────────────────────────
A2 = r'''let _uploads=[];
let _serGroups=[];
async function loadUploads(){
  const el=$("uploadsList"); el.innerHTML="טוען…";
  try{ const d=await (await fetch("/uploads/new")).json();
    _uploads=d.items||[];'''
N2 = r'''let _uploads=[];
let _serGroups=[];
let _selUploads=new Set();   // אינדקסים של פרקים ממתינים שסומנו לאיחוד ידני
function updateSelBar(){
  const bar=$("selBar"); if(!bar) return;
  bar.classList.toggle("hidden", _selUploads.size===0);
  const c=$("selCount"); if(c) c.textContent=_selUploads.size;
}
function toggleSelUpload(i,on){ if(on)_selUploads.add(i); else _selUploads.delete(i); updateSelBar(); }
function clearSelUploads(){ _selUploads.clear(); document.querySelectorAll(".uplsel").forEach(c=>c.checked=false); updateSelBar(); }
async function mergeSelectedUploads(){
  const name=$("sel_name").value.trim(), cat=$("sel_cat").value, renum=$("sel_renum").checked;
  if(!_selUploads.size){ alert("לא נבחרו פרקים"); return; }
  if(!name){ $("selMsg").innerHTML='<span class="err">הקלד שם סדרה</span>'; return; }
  let idxs=[..._selUploads].filter(i=>_uploads[i]);
  if(!idxs.length){ clearSelUploads(); return; }
  idxs.sort((a,b)=>((_uploads[a].channel_msg_id||0)-(_uploads[b].channel_msg_id||0)));
  if(!confirm(`לאחד ${idxs.length} פרקים נבחרים לסדרה «${name}»?`+(renum?`\nימוספרו ע1פ1..ע1פ${idxs.length}.`:""))) return;
  const exist=movies.find(m=>m.series_name===name && (m.thumbnail_url||m.description));
  const inhPoster=exist?exist.thumbnail_url||"":"", inhDesc=exist?exist.description||"":"";
  const ids=[]; let ep=0;
  const newItems=idxs.map(i=>{const u=_uploads[i]; const vid=(u.video_url||"").trim(); const info=extractVideoInfo(vid); ep++;
    if(u.channel_msg_id!=null) ids.push(u.channel_msg_id);
    return { id:crypto.randomUUID(), created_date:new Date().toISOString(),
      title:name, year:u.year?parseInt(u.year):(exist?exist.year:null),
      category:cat||"סדרות", description:u.description||inhDesc,
      type:info.type, video_id:info.video_id, video_url:vid,
      thumbnail_url:u.thumbnail_url||inhPoster, custom_slug:exist?exist.custom_slug||null:null,
      series_name:name, season_number:renum?1:(u.season_number||1),
      episode_number:renum?ep:(u.episode_number||null), episode_title:"" };
  });
  movies=[...newItems, ...movies];
  if(await persist()){
    try{ await fetch("/uploads/clear",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({password:PASS, channel_msg_ids:ids})}); }catch{}
    _selUploads.clear(); $("sel_name").value=""; $("selMsg").textContent="";
    refreshDerived(); await loadUploads();
    alert(`אוחדו ${newItems.length} פרקים → «${name}» ✓`);
  }
}
async function loadUploads(){
  const el=$("uploadsList"); el.innerHTML="טוען…"; _selUploads.clear();
  try{ const d=await (await fetch("/uploads/new")).json();
    _uploads=d.items||[];'''

# ── עריכה 3: צ'קבוקס לכל פרק בקבוצת סדרה ─────────────────────────────────────
A3 = r'''      html+=idxs.map(i=>{const u=_uploads[i];
        return `<div class="item" style="padding:6px 12px"><img src="${u.thumbnail_url||''}" onerror="this.style.visibility='hidden'">'''
N3 = r'''      html+=idxs.map(i=>{const u=_uploads[i];
        return `<div class="item" style="padding:6px 12px"><input type="checkbox" class="uplsel" onchange="toggleSelUpload(${i},this.checked)" ${_selUploads.has(i)?'checked':''} style="margin-left:8px;transform:scale(1.4)" title="סמן לאיחוד ידני"><img src="${u.thumbnail_url||''}" onerror="this.style.visibility='hidden'">'''

# ── עריכה 4: צ'קבוקס לכל סרט בודד ────────────────────────────────────────────
A4 = r'''      const renderMovie=i=>{const u=_uploads[i];
        return `<div class="item"><img src="${u.thumbnail_url||''}" onerror="this.style.visibility='hidden'">'''
N4 = r'''      const renderMovie=i=>{const u=_uploads[i];
        return `<div class="item"><input type="checkbox" class="uplsel" onchange="toggleSelUpload(${i},this.checked)" ${_selUploads.has(i)?'checked':''} style="margin-left:8px;transform:scale(1.4)" title="סמן לאיחוד ידני"><img src="${u.thumbnail_url||''}" onerror="this.style.visibility='hidden'">'''

# ── עריכה 5: רענון הסרגל בסוף loadUploads ────────────────────────────────────
A5 = r'''    }
    el.innerHTML=html;
  }catch(e){ el.innerHTML='<span class="err">'+e.message+'</span>'; }
}
// הוספת כל פרקי סדרה בכפתור אחד'''
N5 = r'''    }
    el.innerHTML=html; updateSelBar();
  }catch(e){ el.innerHTML='<span class="err">'+e.message+'</span>'; }
}
// הוספת כל פרקי סדרה בכפתור אחד'''

EDITS = [("סרגל בחירה", A1, N1), ("state+פונקציות", A2, N2),
         ("צ'קבוקס פרק", A3, N3), ("צ'קבוקס סרט", A4, N4),
         ("רענון סרגל", A5, N5)]


def apply(src: str) -> str:
    if MARKER in src:
        print("✓ כבר מותקן"); return src
    out = src
    for name, a, n in EDITS:
        c = out.count(a)
        assert c == 1, f"עוגן '{name}': נמצא {c} פעמים (ציפינו 1)"
        out = out.replace(a, n, 1)
    assert "mergeSelectedUploads" in out and 'class="uplsel"' in out, "לא הוחל כראוי"
    return out


def revert(src: str) -> str:
    out = src
    for name, a, n in EDITS:
        if n in out:
            out = out.replace(n, a, 1)
    return out


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read()
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        shutil.copy2(PATH, PATH + ".bak_upload_select")
        open(PATH, "w", encoding="utf-8").write(revert(src))
        print("✓ שוחזר"); return 0
    out = apply(src)
    if arg == "--check":
        print("✓ בדיקה עברה"); return 0
    if MARKER in src: return 0
    shutil.copy2(PATH, PATH + ".bak_upload_select")
    open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", PATH + ".bak_upload_select"); return 0


if __name__ == "__main__":
    sys.exit(main())
