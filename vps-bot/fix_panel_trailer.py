#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
פאנל: שדה קישור טריילר, ולשונית שמראה למי אין טריילר.

הטריילר האוטומטי תלוי ב-tmdb_id, ולתוכן ישראלי רבות אין טריילר ב-TMDB גם
כשהמזהה קיים. שדה ידני פותר כל מקרה כזה מיד; הרשימה נותנת לדעת על מה
לעבוד, במקום לגלות פריט חסר רק כשנתקלים בו.

הסדרות ברשימה מקובצות לפי שם. רשימה של 424 פרקים לאותה סדרה אינה רשימת
עבודה. הזנת קישור על פרק אחד בסדרה + «עדכן טריילר לכל הסדרה» מכסה את כולה.

הקובץ נערך במקום ולא מוחלף: עותק admin.html שבמאגר ישן ואינו כולל תוספות
שהוחלו ישירות על השרת.

    python3 fix_panel_trailer.py --check
    python3 fix_panel_trailer.py
    python3 fix_panel_trailer.py --revert
"""
import argparse, datetime, glob, os, pathlib, shutil, sys

TARGET = pathlib.Path(os.environ.get("ADMIN_HTML", "/opt/zovex-bot/admin.html"))
MARK = "f_trailer"

PATCHES = [
 ("שדה קישור טריילר",
  '''      <label>פוסטר (thumbnail_url)</label><input id="f_thumb" dir="ltr">''',
  '''      <label>פוסטר (thumbnail_url)</label><input id="f_thumb" dir="ltr">
      <label>קישור טריילר <span class="muted">(יוטיוב — גובר על הטריילר האוטומטי)</span></label>
      <input id="f_trailer" dir="ltr" placeholder="https://www.youtube.com/watch?v=… או המזהה בלבד">'''),

 ("שמירת הערך",
  '''    type:info.type, video_id:info.video_id, video_url:vid, thumbnail_url:$("f_thumb").value.trim(),''',
  '''    type:info.type, video_id:info.video_id, video_url:vid, thumbnail_url:$("f_thumb").value.trim(),
    trailer_url:$("f_trailer").value.trim()||null,'''),

 ("טעינת הערך לעריכה",
  '''  $("f_thumb").value=m.thumbnail_url||""; $("f_desc").value=m.description||"";''',
  '''  $("f_thumb").value=m.thumbnail_url||""; $("f_desc").value=m.description||"";
  $("f_trailer").value=m.trailer_url||"";'''),

 ("החלה על כל הסדרה",
  '''  category:      {label:"קטגוריה", get:()=>$("f_category").value.trim()},''',
  '''  category:      {label:"קטגוריה", get:()=>$("f_category").value.trim()},
  trailer_url:   {label:"טריילר",   get:()=>$("f_trailer").value.trim()},'''),

 ("כפתור לכל הסדרה",
  '''        <button class="mini" style="background:#0a8f5a" onclick="applyToSeries('category')">קבע קטגוריה לכל הסדרה</button>''',
  '''        <button class="mini" style="background:#0a8f5a" onclick="applyToSeries('category')">קבע קטגוריה לכל הסדרה</button>
        <button class="mini" style="background:#b4532a" onclick="applyToSeries('trailer_url')">עדכן טריילר לכל הסדרה</button>'''),

 ("לשונית",
  '''    <button id="tab-stats" onclick="showTab('stats')">📊 סטטיסטיקות</button>''',
  '''    <button id="tab-notrailer" onclick="showTab('notrailer')">🎬 בלי טריילר</button>
    <button id="tab-stats" onclick="showTab('stats')">📊 סטטיסטיקות</button>'''),

 ("רישום הלשונית",
  '''  ["add","manage","cats","live","uploads","support","pool","import","stats","admins"].forEach(x=>{''',
  '''  ["add","manage","cats","live","uploads","support","pool","import","stats","admins","notrailer"].forEach(x=>{'''),

 ("טעינה בבחירה",
  '''  if(n==="manage") renderManage();''',
  '''  if(n==="manage") renderManage();
  if(n==="notrailer") loadNoTrailer();'''),
]

PANE = '''
<div id="pane-notrailer" class="hidden">
  <div class="card">
    <h2>תוכן בלי טריילר</h2>
    <p class="muted">טריילר אוטומטי מגיע מ-TMDB ודורש <code>tmdb_id</code>. לתוכן
    ישראלי רבות אין שם טריילר גם כשהמזהה קיים. כאן מה שחסר — לוחצים «ערוך»,
    מדביקים קישור יוטיוב בשדה «קישור טריילר», ושומרים.</p>
    <p class="muted">סדרות מקובצות לפי שם: אחרי הזנת קישור בפרק אחד אפשר
    «עדכן טריילר לכל הסדרה» וזה מכסה את כל הפרקים.</p>
    <div class="row" style="margin-bottom:8px">
      <button class="mini" onclick="loadNoTrailer()">רענן</button>
      <input id="nt_q" placeholder="סינון לפי שם…" oninput="renderNoTrailer()" style="flex:1">
    </div>
    <div id="ntMsg" class="muted">טוען…</div>
    <div id="ntList"></div>
  </div>
</div>
'''

JS = '''
// ── תוכן בלי טריילר ─────────────────────────────────────────────────────────
let _nt = null;
async function loadNoTrailer(){
  $("ntMsg").textContent="טוען…"; $("ntList").innerHTML="";
  try{
    const r=await fetch("/panel/no-trailer?password="+encodeURIComponent(PASS));
    if(!r.ok) throw new Error("שגיאה "+r.status);
    _nt=await r.json();
    $("ntMsg").innerHTML=`<b>${_nt.counts.movies}</b> סרטים ו-<b>${_nt.counts.series}</b> סדרות בלי טריילר`;
    renderNoTrailer();
  }catch(e){ $("ntMsg").innerHTML='<span class="err">'+e.message+'</span>'; }
}
function renderNoTrailer(){
  if(!_nt) return;
  const q=($("nt_q").value||"").trim().toLowerCase();
  const hit=s=>!q||String(s||"").toLowerCase().includes(q);
  const row=(id,title,sub,img)=>`<div class="item">
      <img src="${img||''}" onerror="this.style.visibility='hidden'">
      <div class="meta"><div class="t">${esc(title||"—")}</div><div class="s">${esc(sub)}</div></div>
      <button class="mini sec" onclick="startEdit('${id}');showTab('add')">ערוך</button>
    </div>`;
  // תקרה של 300 לכל רשימה: הדפדפן נחנק על אלפי שורות, והסינון למעלה הוא
  // הדרך להגיע למה שמחפשים.
  const mv=_nt.movies.filter(m=>hit(m.title)).slice(0,300);
  const se=_nt.series.filter(s=>hit(s.series_name)).slice(0,300);
  $("ntList").innerHTML =
    `<h3 style="margin:14px 0 6px">סדרות (${se.length})</h3>` +
    (se.map(s=>row(s.id,s.series_name,`${s.episodes} פרקים · ${s.category||""}`+(s.tmdb_id?"":" · ללא tmdb_id"),s.thumbnail_url)).join("")||'<div class="muted">אין</div>') +
    `<h3 style="margin:18px 0 6px">סרטים (${mv.length})</h3>` +
    (mv.map(m=>row(m.id,m.title,`${m.year||""} · ${m.category||""}`+(m.tmdb_id?"":" · ללא tmdb_id"),m.thumbnail_url)).join("")||'<div class="muted">אין</div>');
}
'''


def _fail(m):
    print(f"❌ {m}"); sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    if not TARGET.exists():
        _fail(f"{TARGET} לא נמצא")

    if a.revert:
        baks = sorted(glob.glob(str(TARGET) + ".bak-ptrailer-*"))
        if not baks:
            _fail("לא נמצא גיבוי")
        shutil.copy2(baks[-1], TARGET)
        print(f"✓ שוחזר מ-{os.path.basename(baks[-1])}")
        return

    src = TARGET.read_text(encoding="utf-8")
    if MARK in src:
        print("✓ כבר מוחל. לא שונה כלום.")
        return
    if "SERIES_FIELDS" not in src:
        _fail("fix_panel_series_category.py עוד לא הוחל — צריך אותו קודם.")
    for name, o, _ in PATCHES:
        if src.count(o) != 1:
            _fail(f"{name}: נמצאו {src.count(o)} עוגנים, ציפינו ל-1.")
    if src.count("</body>") != 1 or src.count("<script>") < 1:
        _fail("מבנה ה-HTML לא מה שציפינו לו.")

    out = src
    for name, o, x in PATCHES:
        out = out.replace(o, x)
        print(f"  ✓ {name}")
    out = out.replace("</body>", PANE + "</body>", 1)
    # ה-JS נכנס לבלוק הסקריפט האחרון, כדי שיראה את PASS ואת esc/startEdit.
    i = out.rindex("</script>")
    out = out[:i] + JS + out[i:]

    if a.check:
        print("\n✓ כל העוגנים מתאימים. לא שונה כלום (--check).")
        return

    bak = f"{TARGET}.bak-ptrailer-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(TARGET, bak)
    TARGET.write_text(out, encoding="utf-8")
    print(f"\n✓ הוחל. גיבוי: {os.path.basename(bak)}")
    print("   רענן את הפאנל ב-Ctrl+Shift+R.")


if __name__ == "__main__":
    main()
