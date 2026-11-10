#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_series_tools — שלושה כלי-סדרה לפאנל הניהול (admin.html בלבד).

  1. הפצה אוטומטית של פוסטר/תקציר/שנה/קטגוריה/טריילר/slug לכל פרקי
     הסדרה בכל שמירה. (האתר לוקח את הפוסטר מהפרק הראשון — בלי הפצה,
     סדרה בלי פוסטר בפרק הראשון מופיעה ריקה.)
  2. כפתור "✏️ שם" על כותרת הסדרה — משנה את השם בכל הפרקים במכה אחת.
  3. כפתור "🔗 מזג" — מעביר סדרה שהתפצלה לתוך סדרה אחרת (לפי series_name
     ו-slug, כך שבאתר/אפליקציה הן מתאחדות לכרטיס אחד).

אין נגיעה בקוד השרת ואין restart — זה קובץ HTML שנקרא מחדש בכל פנייה.

    python3 patch_series_tools.py --check
    python3 patch_series_tools.py
    python3 patch_series_tools.py --revert
"""
import os, shutil, sys

PATH = os.environ.get("PANEL", "/opt/zovex-bot/admin.html")
MARKER = "window._sersView"

# ── עריכה 1: הפצה אוטומטית ב-saveItem ────────────────────────────────────────
A1 = '''  if(await mutate({upsert:[item]})){
    if(_fromUploadCmid!=null){
      try{ await fetch("/uploads/clear",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({password:PASS, channel_msg_ids:[_fromUploadCmid]})}); }catch{}
      _fromUploadCmid=null;
    }
    if(wasEditing){
      editingId=null;
      showTab("manage");          // חזרה לרשימה מרועננת — רואים מיד את השינוי
    } else {
      clearForm();
      $("addMsg").innerHTML='<span class="ok">נשמר ✓</span>';
    }
  }
}'''
N1 = '''  // ── הפצה אוטומטית של שדות ברמת-הסדרה לכל הפרקים ──
  let _ups=[item], _prop=0;
  if(item.series_name){
    const META=['thumbnail_url','description','category','trailer_url','year','custom_slug'];
    const patch={}; META.forEach(k=>{ const v=item[k]; if(v!==undefined&&v!==null&&v!=='') patch[k]=v; });
    if(Object.keys(patch).length){
      const sibs=movies.filter(m=>m.series_name===item.series_name && String(m.id)!==String(item.id));
      _ups=_ups.concat(sibs.map(m=>({id:m.id,...patch})));
      _prop=sibs.length;
    }
  }
  if(await mutate({upsert:_ups})){
    if(_fromUploadCmid!=null){
      try{ await fetch("/uploads/clear",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({password:PASS, channel_msg_ids:[_fromUploadCmid]})}); }catch{}
      _fromUploadCmid=null;
    }
    const _note = _prop ? `נשמר ✓ · הופץ אוטומטית ל-${_prop} פרקים נוספים` : 'נשמר ✓';
    if(wasEditing){
      editingId=null;
      $("addMsg").innerHTML=`<span class="ok">${_note}</span>`;
      setTimeout(()=>showTab("manage"), _prop?1100:0);
    } else {
      clearForm();
      $("addMsg").innerHTML=`<span class="ok">${_note}</span>`;
    }
  }
}'''

# ── עריכה 2: כפתורי שם/מיזוג בכותרת הסדרה ────────────────────────────────────
A2 = '''    html+=sers.slice(0,60).map(n=>{ const eps=sm[n].slice().sort((a,b)=>((a.season_number||1)-(b.season_number||1))||((a.episode_number||0)-(b.episode_number||0)));
      return `<div class="ser"><div class="head" onclick="this.nextElementSibling.classList.toggle('hidden')">
        <img src="${eps[0].thumbnail_url||''}" style="width:32px;height:46px;object-fit:cover;border-radius:5px" onerror="this.style.visibility='hidden'">
        <div class="t">${esc(n)}</div><span class="pill">${eps.length} פרקים</span>
        <button class="mini gray" onclick="event.stopPropagation();delSeries('${esc(n).replace(/'/g,"")}')">🗑</button></div>'''
N2 = '''    const _shown=sers.slice(0,60); window._sersView=_shown;
    html+=_shown.map((n,si)=>{ const eps=sm[n].slice().sort((a,b)=>((a.season_number||1)-(b.season_number||1))||((a.episode_number||0)-(b.episode_number||0)));
      return `<div class="ser"><div class="head" onclick="this.nextElementSibling.classList.toggle('hidden')">
        <img src="${eps[0].thumbnail_url||''}" style="width:32px;height:46px;object-fit:cover;border-radius:5px" onerror="this.style.visibility='hidden'">
        <div class="t">${esc(n)}</div><span class="pill">${eps.length} פרקים</span>
        <button class="mini" style="background:#5e5ce6" onclick="event.stopPropagation();renameSeries(${si})" title="שנה שם לכל הפרקים">✏️ שם</button>
        <button class="mini" style="background:#b4532a" onclick="event.stopPropagation();mergeSeries(${si})" title="מזג לתוך סדרה אחרת">🔗 מזג</button>
        <button class="mini gray" onclick="event.stopPropagation();delSeries('${esc(n).replace(/'/g,"")}')">🗑</button></div>'''

# ── עריכה 3: הפונקציות renameSeries / mergeSeries ────────────────────────────
A3 = '''async function delSeries(n){ if(!confirm(`למחוק את כל הסדרה «${n}»?`)) return; const ids=movies.filter(m=>m.series_name===n).map(m=>m.id).filter(Boolean); if(await mutate({delete_ids:ids})){ renderManage(); } }'''
N3 = A3 + '''

async function renameSeries(si){
  const from=(window._sersView||[])[si]; if(!from) return;
  const to=(prompt(`שם חדש לכל פרקי «${from}»:`, from)||"").trim();
  if(!to || to===from) return;
  const eps=movies.filter(m=>m.series_name===from);
  if(!eps.length){ alert("לא נמצאו פרקים"); return; }
  if(!confirm(`לשנות את השם של ${eps.length} הפרקים\\nמ-«${from}»\\nל-«${to}»?`)) return;
  const ups=eps.map(m=>({id:m.id, series_name:to, title:to}));
  if(await mutate({upsert:ups})){ renderManage(); }
}

async function mergeSeries(si){
  const from=(window._sersView||[])[si]; if(!from) return;
  const names=Object.keys(seriesMap()).filter(x=>x!==from).sort();
  if(!names.length){ alert("אין סדרה אחרת למזג אליה"); return; }
  const list=names.map((x,i)=>`${i+1}. ${x}`).join("\\n");
  const pick=prompt(`מזג את «${from}» לתוך — הקלד מספר:\\n\\n${list}`);
  const idx=parseInt(pick,10)-1;
  if(isNaN(idx) || idx<0 || idx>=names.length) return;
  const to=names[idx];
  const tgt=(seriesMap()[to]||[])[0]||{};
  const eps=movies.filter(m=>m.series_name===from);
  if(!confirm(`להעביר את ${eps.length} הפרקים של «${from}»\\nאל «${to}»?\\n\\n(אם יש חפיפה במספרי עונה+פרק ייתכנו כפילויות)`)) return;
  const ups=eps.map(m=>({ id:m.id, series_name:to, title:to,
    custom_slug: tgt.custom_slug||m.custom_slug||null,
    category: tgt.category||m.category }));
  if(await mutate({upsert:ups})){ renderManage(); }
}'''

EDITS = [("הפצה אוטומטית", A1, N1), ("כפתורי סדרה", A2, N2), ("פונקציות סדרה", A3, N3)]


def apply(src: str) -> str:
    if MARKER in src:
        print("✓ כבר מותקן"); return src
    out = src
    for name, a, n in EDITS:
        c = out.count(a)
        assert c == 1, f"עוגן '{name}': נמצא {c} פעמים (ציפינו 1)"
        out = out.replace(a, n, 1)
    assert "renameSeries" in out and "mergeSeries" in out, "הפונקציות לא נוספו"
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
        shutil.copy2(PATH, PATH + ".bak_series_tools")
        open(PATH, "w", encoding="utf-8").write(revert(src))
        print("✓ שוחזר"); return 0
    out = apply(src)
    if arg == "--check":
        print("✓ בדיקה עברה"); return 0
    if MARKER in src: return 0
    shutil.copy2(PATH, PATH + ".bak_series_tools")
    open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", PATH + ".bak_series_tools"); return 0


if __name__ == "__main__":
    sys.exit(main())
