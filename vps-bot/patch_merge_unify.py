#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_merge_unify — טופס איחוד אחד במקום שניים באזור הממתינים.

אחרי patch_upload_select היו שני טפסים כמעט זהים (שם + קטגוריה): "אחד את
כל הממתינים" ו"אחד את הנבחרים". כאן נשאר טופס אחד:
  · בלי בחירה  → מאחד את כל הממתינים, בדיוק כמו קודם.
  · עם בחירה   → אותו טופס הופך ל"אחד את N הנבחרים" ומציג את המספור-מחדש.

מניח ש-patch_upload_select (+fix) כבר הוחלו. admin.html בלבד, אין restart.

    python3 patch_merge_unify.py --check | (ריק) | --revert
"""
import os, re, shutil, sys

PATH = os.environ.get("PANEL", "/opt/zovex-bot/admin.html")
MARKER = 'id="mrgTitle"'

E = []
E.append(("כותרת",
 '      <h2>🔗 אחד את כל הממתינים לסדרה אחת</h2>\n      <div class="muted">',
 '      <h2 id="mrgTitle">🔗 אחד את כל הממתינים לסדרה אחת</h2>\n      <div id="mrgDesc" class="muted">'))
E.append(("כפתור + מספור",
 '      <button onclick="mergeUploads()" style="width:100%;margin-top:8px">🔗 אחד הכל והוסף לאתר</button>',
 '      <label id="mrgRenumRow" class="hidden" style="display:flex;align-items:center;gap:6px;margin-top:8px"><input type="checkbox" id="mrg_renum" checked> מספר את הפרקים מחדש ע1פ1..ע1פN לפי סדר ההעלאה</label>\n'
 '      <div class="row" style="margin-top:8px"><button id="mrgBtn" onclick="mergeUploads()" style="flex:1">🔗 אחד הכל והוסף לאתר</button>\n'
 '        <button id="mrgClear" class="gray hidden" onclick="clearSelUploads()">נקה בחירה</button></div>'))
E.append(("updateSelBar",
 '''function updateSelBar(){
  const bar=$("selBar"); if(!bar) return;
  bar.classList.toggle("hidden", _selUploads.size===0);
  const c=$("selCount"); if(c) c.textContent=_selUploads.size;
}''',
 '''function updateSelBar(){
  // טופס אחד: בלי בחירה — "אחד הכל"; עם בחירה — "אחד את N הנבחרים".
  const n=_selUploads.size, t=$("mrgTitle"), b=$("mrgBtn"), d=$("mrgDesc");
  if(!t||!b) return;
  t.textContent = n ? `🔗 אחד את ${n} הנבחרים לסדרה אחת` : "🔗 אחד את כל הממתינים לסדרה אחת";
  b.textContent = n ? `🔗 אחד את ${n} הנבחרים והוסף לאתר` : "🔗 אחד הכל והוסף לאתר";
  if(d) d.style.display = n ? "none" : "";
  $("mrgRenumRow").classList.toggle("hidden", !n);
  $("mrgClear").classList.toggle("hidden", !n);
}'''))
E.append(("קריאת שדות",
 'const name=$("sel_name").value.trim(), cat=$("sel_cat").value, renum=$("sel_renum").checked;',
 'const name=$("mrg_name").value.trim(), cat=$("mrg_cat").value, renum=$("mrg_renum").checked;'))
E.append(("שגיאת שם",
 '''if(!name){ $("selMsg").innerHTML='<span class="err">הקלד שם סדרה</span>'; return; }''',
 '''if(!name){ $("mrgMsg").innerHTML='<span class="err">הקלד שם סדרה</span>'; return; }'''))
E.append(("איפוס",
 '_selUploads.clear(); $("sel_name").value=""; $("selMsg").textContent="";',
 '_selUploads.clear(); $("mrg_name").value=""; $("mrgMsg").textContent="";'))
E.append(("ניתוב",
 'async function mergeUploads(){\n  const name=$("mrg_name").value.trim(), cat=$("mrg_cat").value;',
 'async function mergeUploads(){\n  if(_selUploads.size) return mergeSelectedUploads();   // יש בחירה → רק הנבחרים\n  const name=$("mrg_name").value.trim(), cat=$("mrg_cat").value;'))

SEL_RE = re.compile(r'    <div id="selBar" class="card hidden".*?\n    </div>\n(?=    <div class="card"><div class="toprow"><h2>העלאות)', re.S)


def apply(src):
    if MARKER in src:
        print("✓ כבר מותקן"); return src, None
    m = SEL_RE.search(src)
    assert m, "לא נמצא הטופס הכפול (selBar) — ודא ש-patch_upload_select הוחל"
    removed = m.group(0)
    out = src[:m.start()] + src[m.end():]
    for name, a, n in E:
        c = out.count(a)
        assert c == 1, f"עוגן '{name}': נמצא {c} פעמים"
        out = out.replace(a, n, 1)
    assert "selBar" not in out and 'id="sel_name"' not in out
    return out, removed


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read()
    bak = PATH + ".bak_merge_unify"
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        assert os.path.exists(bak), "אין גיבוי לשחזור"
        shutil.copy2(bak, PATH); print("✓ שוחזר מהגיבוי"); return 0
    out, _ = apply(src)
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    if MARKER in src: return 0
    shutil.copy2(PATH, bak)
    open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", bak); return 0


if __name__ == "__main__":
    sys.exit(main())
